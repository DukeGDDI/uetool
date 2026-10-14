"""Build tab: assemble a uetool command, run it, stream the log, cancel safely."""
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from . import commands as cmd
from . import projectstate
from .commands import BuildSpec
from .context import Context
from .runner import Runner
from .widgets import muted, set_role

DEFAULT_CONFIG = "(project default)"
CONFIGS = [DEFAULT_CONFIG, "Shipping", "Development", "DebugGame", "Test"]


class BuildTab(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.runner = Runner(self)
        self.runner.output.connect(self.append_log)
        self.runner.finished.connect(self.on_finished)
        self._last_dry = False
        outer = QVBoxLayout(self)

        grid = QGridLayout()
        self.command = QComboBox()
        self.command.addItems(cmd.COMMANDS)
        self.platform = QComboBox()
        self.platform.addItems(["win", "mac"])
        self.platform.setCurrentText(ctx.host)
        self.config = QComboBox()
        self.config.addItems(CONFIGS)
        self.layer = QComboBox()
        for i, (label, w) in enumerate([("Command", self.command), ("Platform", self.platform),
                                        ("Build configuration", self.config),
                                        ("Custom config layer", self.layer)]):
            grid.addWidget(muted(label), (i // 2) * 2, i % 2)
            grid.addWidget(w, (i // 2) * 2 + 1, i % 2)
        outer.addLayout(grid)
        self.layer_hint = muted()
        outer.addWidget(self.layer_hint)

        flags = QHBoxLayout()
        self.bump = QCheckBox("Bump version")
        self.bump.setChecked(True)
        self.bootstrap = QCheckBox("Bootstrap editor target")
        self.bootstrap.setChecked(True)
        self.clean = QCheckBox("Clean build")
        for c in (self.bump, self.bootstrap, self.clean):
            flags.addWidget(c)
        flags.addStretch()
        outer.addLayout(flags)

        self.clean_warn = QLabel("Clean build deletes Binaries, Intermediate and Saved/Cooked. "
                                 "You'll be asked to confirm.")
        self.clean_warn.setProperty("role", "warn-box")
        self.clean_warn.setWordWrap(True)
        outer.addWidget(self.clean_warn)
        self.issues = QLabel()
        self.issues.setProperty("role", "err-box")
        self.issues.setWordWrap(True)
        outer.addWidget(self.issues)

        self.preview = QLineEdit()
        self.preview.setReadOnly(True)
        self.preview.setProperty("role", "mono")
        outer.addWidget(self.preview)

        buttons = QHBoxLayout()
        self.dry_btn = QPushButton("Dry run")
        self.run_btn = QPushButton("▶  Run")
        self.run_btn.setProperty("role", "primary")
        self.cancel_btn = QPushButton("Cancel")
        for b in (self.dry_btn, self.run_btn, self.cancel_btn):
            buttons.addWidget(b)
        buttons.addStretch()
        self.state = muted("Idle")
        self.state.setWordWrap(False)
        buttons.addWidget(self.state)
        outer.addLayout(buttons)
        self.dry_hint = muted()
        outer.addWidget(self.dry_hint)

        self.leftover = QLabel()
        self.leftover.setProperty("role", "err-box")
        self.leftover.setWordWrap(True)
        self.leftover.hide()
        outer.addWidget(self.leftover)
        self.restore_btn = QPushButton("Restore DefaultGame.ini")
        self.restore_btn.hide()
        self.restore_btn.clicked.connect(self.restore)
        outer.addWidget(self.restore_btn)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setProperty("role", "mono")
        self.log.setMaximumBlockCount(50_000)
        outer.addWidget(self.log, 1)

        for w in (self.command, self.platform, self.config, self.layer):
            w.currentIndexChanged.connect(self.refresh)
        for c in (self.bump, self.bootstrap, self.clean):
            c.toggled.connect(self.refresh)
        self.run_btn.clicked.connect(lambda: self.start(dry=False))
        self.dry_btn.clicked.connect(lambda: self.start(dry=True))
        self.cancel_btn.clicked.connect(self.runner.cancel)
        ctx.project_changed.connect(self.on_project)
        ctx.config_changed.connect(self.refresh)
        self.on_project()

    # -- form <-> spec -------------------------------------------------------
    def spec(self) -> BuildSpec:
        c = self.config.currentText()
        layer = self.layer.currentText()
        return BuildSpec(
            command=self.command.currentText(), platform=self.platform.currentText(),
            build_config=None if c == DEFAULT_CONFIG else c,
            bump=self.bump.isChecked(), bootstrap=self.bootstrap.isChecked(),
            clean=self.clean.isChecked(), custom_config=None if layer == "none" else layer)

    def on_project(self):
        self.layer.blockSignals(True)
        self.layer.clear()
        self.layer.addItem("none")
        if self.ctx.project:
            self.layer.addItems(cmd.custom_layers(self.ctx.project))
        self.layer.blockSignals(False)
        self.config.setItemText(0, DEFAULT_CONFIG)
        self.refresh()

    def refresh(self):
        spec = self.spec()
        c = spec.command
        self.layer.setEnabled(cmd.accepts(c, "custom_config") and c != "release")
        self.layer_hint.setText("Disabled for release, which uploads to Steam. Use package, then archive."
                                if c == "release" else "")
        self.layer_hint.setVisible(c == "release")
        self.platform.setEnabled(cmd.accepts(c, "platform"))
        self.config.setEnabled(cmd.accepts(c, "config"))
        for box, flag in ((self.bump, "bump"), (self.bootstrap, "bootstrap"), (self.clean, "clean")):
            box.setEnabled(cmd.accepts(c, flag))
        self.bump.setText("Bump version" if c != "bump" else "Bump version (always)")
        self.clean_warn.setVisible(cmd.uses_clean(spec))

        project = self.ctx.project
        self.preview.setText("$ " + cmd.display(spec, project) if project else "")
        issues = cmd.blocking(cmd.validate(spec, self.ctx.host, cmd.custom_layers(project) if project else None))
        # The Dry run button rehearses with the bump off, so judge it on that spec.
        dry_issues = cmd.blocking(cmd.validate(cmd.for_dry_run(spec), self.ctx.host,
                                               cmd.custom_layers(project) if project else None))
        # The live (non-dry) run is only blocked by problems unrelated to dry-running.
        shown = issues if not spec.dry_run else dry_issues
        self.issues.setText("\n".join(i.message for i in shown))
        self.issues.setVisible(bool(shown))

        idle = project is not None and not self.ctx.running
        self.run_btn.setEnabled(idle and not shown)
        can_dry = cmd.accepts(c, "dry_run") and c != "bump"
        self.dry_btn.setEnabled(idle and can_dry and not dry_issues)
        self.dry_btn.setToolTip("" if c != "bump" else "bump has no dry-run mode.")
        self.dry_hint.setText("Dry run prints the commands without running them, and skips the bump "
                              "so .build_number isn't touched." if cmd.effective_bump(spec) and c != "bump" else "")
        self.cancel_btn.setEnabled(self.ctx.running)

    # -- running -------------------------------------------------------------
    def start(self, dry: bool):
        ctx, spec = self.ctx, self.spec()
        if dry:
            spec = cmd.for_dry_run(spec)
        if cmd.blocking(cmd.validate(spec, ctx.host, cmd.custom_layers(ctx.project))):
            return
        if ctx.cfg.dirty and QMessageBox.question(
                self, "Unsaved config",
                "The Config tab has unsaved changes that this run won't see. Run anyway?") != QMessageBox.Yes:
            return
        if (warn := cmd.clean_warning(spec)) and QMessageBox.warning(
                self, "Clean build", warn, QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel) != QMessageBox.Yes:
            return
        if not dry and spec.command in ("upload", "release") and QMessageBox.question(
                self, "Upload to Steam",
                f"This uploads the {spec.platform} build to Steam app {ctx.cfg.get('app_id') or '?'}. "
                "It won't go live until you set it live in Steamworks. Continue?") != QMessageBox.Yes:
            return

        self.log.clear()
        self.leftover.hide()
        self.restore_btn.hide()
        self._last_dry = dry
        argv = cmd.build_argv(spec, ctx.project)
        self.append_log("$ " + cmd.display(spec, ctx.project) + "\n")
        self.state.setText("Running…")
        ctx.set_running(True)
        self.refresh()
        self.runner.start(argv, cwd=str(ctx.project), env=ctx.run_env())

    def append_log(self, text: str):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        bar = self.log.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        if at_end:
            bar.setValue(bar.maximum())

    def on_finished(self, code: int, cancelled: bool):
        self.ctx.set_running(False)
        if cancelled:
            self.state.setText("Cancelled")
            set_role(self.state, "warn")
        elif code == 0:
            self.state.setText("Done (exit 0)")
            set_role(self.state, "muted")
        else:
            self.state.setText(f"Failed (exit {code})")
            set_role(self.state, "err")
        self.append_log(f"\nExit code {code}{' (cancelled)' if cancelled else ''}\n")
        if cancelled or code != 0:
            self.check_leftovers()
        self.refresh()

    def check_leftovers(self):
        problems = []
        if (v := projectstate.stamped_version(self.ctx.project)):
            problems.append(f"Config/DefaultGame.ini was left stamped as {v}; it should be the 3-part "
                            "version. Don't commit it like this.")
            self.restore_btn.show()
        if (files := projectstate.overlaid_files(self.ctx.project)):
            problems.append("A --custom-config merge was left in " + ", ".join(p.name for p in files)
                            + ". Revert those files with git.")
        if problems:
            self.leftover.setText("\n".join(problems))
            self.leftover.show()

    def restore(self):
        v = projectstate.stamped_version(self.ctx.project)
        if v and QMessageBox.question(
                self, "Restore DefaultGame.ini",
                f"Rewrite ProjectVersion {v} back to its 3-part version? No other line is touched."
        ) == QMessageBox.Yes:
            projectstate.restore_base(self.ctx.project)
            self.check_leftovers()
            if not projectstate.stamped_version(self.ctx.project):
                self.restore_btn.hide()
                self.leftover.hide()
            self.ctx.config_changed.emit()
