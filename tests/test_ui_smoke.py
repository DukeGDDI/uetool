"""End-to-end through the real widgets, runner and CLI, against a FAKE project and a fake RunUAT."""
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from core.paths import runuat_path
from ui.app import MainWindow
from ui.context import Context

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="fake RunUAT is a shell script")


@pytest.fixture
def win(app, project, tmp_path):
    eng = tmp_path / "UE"
    uat = runuat_path(eng)
    uat.parent.mkdir(parents=True)
    uat.write_text("#!/bin/sh\necho fake-uat \"$@\"\nsleep ${FAKE_UAT_SLEEP:-0}\n")
    uat.chmod(uat.stat().st_mode | stat.S_IXUSR)
    (project / "Config/Custom/Arcware").mkdir(parents=True)
    ctx = Context(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    w = MainWindow(ctx)
    assert ctx.open_project(project)
    ctx.cfg.apply_now("ue_root", str(eng))
    (project / ".build_number").write_text("7\n")
    w.show()
    yield w
    w.tab_widgets["Build"].runner.cancel()


def wait_finished(win, ms=20000):
    loop = QEventLoop()
    win.ctx.run_finished.connect(loop.quit)
    QTimer.singleShot(ms, loop.quit)
    if win.ctx.running:
        loop.exec()
    assert not win.ctx.running, "run did not finish"


def build(win):
    return win.tab_widgets["Build"]


def test_dry_run_package_streams_log_and_never_bumps(win, project):
    b = build(win)
    b.command.setCurrentText("package")
    b.platform.setCurrentText(win.ctx.host)
    b.bootstrap.setChecked(False)
    assert b.bump.isChecked() and b.dry_btn.isEnabled()
    b.dry_btn.click()
    wait_finished(win)
    log = b.log.toPlainText()
    assert "BuildCookRun" in log and "--dry-run" in log and "Exit code 0" in log
    assert (project / ".build_number").read_text() == "7\n"
    assert not (project / ".version").exists()
    assert "ProjectVersion=v1.2.0\n" in (project / "Config/DefaultGame.ini").read_text()


def test_release_with_custom_config_is_blocked(win):
    b = build(win)
    b.command.setCurrentText("package")
    b.layer.setCurrentText("Arcware")
    assert b.run_btn.isEnabled()
    b.command.setCurrentText("release")
    assert not b.run_btn.isEnabled() and "not allowed" in b.issues.text()


def test_notarize_blocked_off_mac(win):
    win.ctx.host = "win"
    b = build(win)
    b.command.setCurrentText("notarize")
    assert not b.run_btn.isEnabled() and "macOS" in b.issues.text()


def test_clean_needs_confirmation(win, monkeypatch):
    b = build(win)
    b.command.setCurrentText("package")
    b.clean.setChecked(True)
    asked = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: asked.append(a[2]) or QMessageBox.Cancel)
    b.run_btn.click()
    assert asked and "deletes Binaries" in asked[0] and not win.ctx.running


def test_cancel_lets_cli_restore_stamped_ini(win, project, monkeypatch):
    monkeypatch.setenv("FAKE_UAT_SLEEP", "60")
    b = build(win)
    b.command.setCurrentText("package")
    b.platform.setCurrentText(win.ctx.host)
    b.bump.setChecked(False)
    b.bootstrap.setChecked(False)
    b.runner.grace_ms = 15000
    b.run_btn.click()
    ini = project / "Config/DefaultGame.ini"
    deadline = time.time() + 10
    while "v1.2.0.7" not in ini.read_text() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.05)
    assert "ProjectVersion=v1.2.0.7" in ini.read_text()      # stamped mid-run
    b.cancel_btn.click()
    wait_finished(win)
    assert "ProjectVersion=v1.2.0\n" in ini.read_text()      # CLI's finally ran
    assert b.state.text() == "Cancelled" and b.leftover.isHidden()


def test_leftover_stamp_warns_and_restore_works(win, project, monkeypatch):
    ini = project / "Config/DefaultGame.ini"
    ini.write_text(ini.read_text().replace("v1.2.0", "v3.1.0.5"))
    b = build(win)
    b.on_finished(1, False)
    assert not b.leftover.isHidden() and "v3.1.0.5" in b.leftover.text() and not b.restore_btn.isHidden()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    b.restore_btn.click()
    assert "ProjectVersion=v3.1.0\n" in ini.read_text() and b.leftover.isHidden()


def test_setup_fix_sets_ue_root_and_config_tab_follows(win, project, tmp_path):
    win.ctx.cfg.apply_now("ue_root", "")
    setup, config = win.tab_widgets["Setup"], win.tab_widgets["Config"]
    setup.refresh()
    ue = next(r for r in setup.results if r.key == "ue_root")
    assert ue.status in ("fix", "fail")
    from ui.doctor import Action
    setup.perform(Action("set_field", "x", {"field": "ue_root", "value": "/some/UE_5.7"}))
    assert win.ctx.cfg.get("ue_root") == "/some/UE_5.7" and config.value("ue_root") == "/some/UE_5.7"


def test_config_tab_edit_save_roundtrip(win, project):
    c = win.tab_widgets["Config"]
    c.edits["main_app_id"].setText("abc")
    assert not c.save_btn.isEnabled() and "numbers only" in c.msgs["main_app_id"].text()
    c.edits["main_app_id"].setText("4852730")
    assert c.save_btn.isEnabled()
    c.save_btn.click()
    assert 'app_id = "4852730"  # fill me' in (project / "uetool.toml").read_text()
    assert not win.ctx.cfg.dirty


def test_build_tab_steam_app_selection(win, project):
    b = build(win)
    b.command.setCurrentText("upload")
    assert not b.run_btn.isEnabled() and "No Steam app" in b.issues.text()
    # One configured app: preselected; the UI always passes --app explicitly.
    win.ctx.cfg.apply_now("playtest_app_id", "4852730")
    win.ctx.config_changed.emit()
    assert b.app.currentData() == "playtest" and b.run_btn.isEnabled()
    assert b.preview.text().endswith("--app playtest")
    # Two configured apps: Run is blocked until one is chosen, then --app appears.
    win.ctx.cfg.apply_now("main_app_id", "4547240")
    win.ctx.config_changed.emit()
    assert b.app.currentData() == "playtest"       # the earlier choice survives the repopulate
    b.app.setCurrentIndex(0)                        # "(choose…)"
    assert b.app.currentData() is None and not b.run_btn.isEnabled() and "choose" in b.issues.text()
    b.app.setCurrentIndex(1)
    assert b.app.currentData() == "main" and b.run_btn.isEnabled()
    assert b.preview.text().endswith("upload --platform mac --app main") or \
        b.preview.text().endswith("upload --platform win --app main")
    # Commands that don't upload ignore the combo.
    b.command.setCurrentText("package")
    assert not b.app.isEnabled() and "--app" not in b.preview.text()
