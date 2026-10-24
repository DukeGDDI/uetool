"""uetool ui launcher: interpreter resolution + detached spawn, no real window."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import uilaunch as ul


def _make_venv(install_dir: Path, windows=False) -> Path:
    rel = ("Scripts", "python.exe") if windows else ("bin", "python")
    p = install_dir.joinpath(".venv", *rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")
    return p


def test_resolve_prefers_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("UETOOL_UI_PYTHON", "/custom/py")
    _make_venv(tmp_path)  # present, but the explicit override must win
    assert ul.resolve_python(tmp_path) == "/custom/py"


def test_resolve_finds_install_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("UETOOL_UI_PYTHON", raising=False)
    venv = _make_venv(tmp_path)
    assert ul.resolve_python(tmp_path) == str(venv)


def test_resolve_dry_run_falls_back_without_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("UETOOL_UI_PYTHON", raising=False)
    # No venv in tmp_path; require=False returns the current interpreter unchecked.
    assert ul.resolve_python(tmp_path, require=False) == sys.executable


def test_resolve_requires_pyside_or_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("UETOOL_UI_PYTHON", raising=False)
    monkeypatch.setattr(ul, "_has_pyside", lambda _py: False)
    with pytest.raises(SystemExit):
        ul.resolve_python(tmp_path, require=True)


def test_launch_dry_run_prints_argv(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("UETOOL_UI_PYTHON", "/py")
    target = tmp_path / "Game"
    assert ul.launch(target, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "/py" in out and str(ul.UI_APP) in out and str(target) in out


def test_launch_dry_run_without_target(monkeypatch, capsys):
    monkeypatch.setenv("UETOOL_UI_PYTHON", "/py")
    assert ul.launch(None, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "/py" in out and str(ul.UI_APP) in out


def test_launch_spawns_detached(tmp_path, monkeypatch):
    monkeypatch.setenv("UETOOL_UI_PYTHON", "/py")
    captured = {}
    monkeypatch.setattr(ul.subprocess, "Popen",
                        lambda argv, **kw: captured.update(argv=argv, kw=kw) or object())
    target = tmp_path / "Game"
    assert ul.launch(target) == 0
    assert captured["argv"][0] == "/py"
    assert str(ul.UI_APP) in captured["argv"] and str(target) in captured["argv"]
    assert captured["kw"]["stdout"] == subprocess.DEVNULL
    if os.name == "nt":
        assert captured["kw"]["creationflags"]
    else:
        assert captured["kw"]["start_new_session"] is True
