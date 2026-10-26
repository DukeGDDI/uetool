"""Setup Doctor tab."""
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from . import doctor, projectstate
from .context import Context
from .terminal import shell_line, terminal_argv
from .widgets import badge, hline, muted


class SetupTab(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("Setup doctor")
        title.setStyleSheet("font-weight:600; font-size:14px;")
        head.addWidget(title)
        self.summary = muted()
        head.addWidget(self.summary)
        head.addStretch()
        self.export_btn = QPushButton("Copy export lines")
        self.export_btn.setToolTip("Shell lines that give the CLI the same machine settings the UI passes.")
        self.export_btn.clicked.connect(self.copy_exports)
        head.addWidget(self.export_btn)
        recheck = QPushButton("Re-check all")
        recheck.clicked.connect(self.refresh)
        head.addWidget(recheck)
        outer.addLayout(head)

        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(self.body)
        outer.addWidget(scroll, 1)

        ctx.project_changed.connect(self.refresh)
        ctx.config_changed.connect(self.refresh)
        ctx.run_finished.connect(self.refresh)
        self.refresh()

    # -- rendering ---------------------------------------------------------
    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if w := item.widget():
                w.hide()
                w.setParent(None)
                w.deleteLater()
        if not self.ctx.project:
            self.rows.addWidget(muted("Open a project to run the checks."))
            self.rows.addStretch()
            self.summary.setText("")
            return
        self.results = doctor.run_checks(self.ctx.project, self.ctx.cfg, self.ctx.steam_sdk,
                                         epic_sdk=self.ctx.epic_sdk, host=self.ctx.host)
        self.summary.setText("· " + doctor.summary(self.results))
        for r in self.results:
            self.rows.addWidget(hline())
            row = QHBoxLayout()
            b = badge(r.status)
            row.addWidget(b, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(QLabel(r.name))
            col.addWidget(muted(r.detail))
            row.addLayout(col, 1)
            if r.action:
                btn = QPushButton(r.action.label)
                btn.clicked.connect(lambda _=False, a=r.action: self.perform(a))
                row.addWidget(btn, 0, Qt.AlignTop)
            holder = QWidget()
            holder.setLayout(row)
            self.rows.addWidget(holder)
        self.rows.addStretch()

    # -- actions -----------------------------------------------------------
    def perform(self, a: doctor.Action):
        ctx = self.ctx
        if a.kind == "set_field":
            ctx.cfg.apply_now(a.data["field"], a.data["value"])
            ctx.config_changed.emit()
        elif a.kind == "open_config":
            ctx.goto_tab.emit("Config", "")
        elif a.kind == "pick_sdk":
            d = QFileDialog.getExistingDirectory(self, "Folder containing steamcmd (or the Steamworks SDK)",
                                                 ctx.steam_sdk or str(self.ctx.project))
            if d:
                ctx.steam_sdk = d
        elif a.kind == "pick_epic_sdk":
            d = QFileDialog.getExistingDirectory(self, "Folder containing BuildPatchTool",
                                                 ctx.epic_sdk or str(self.ctx.project))
            if d:
                ctx.epic_sdk = d
        elif a.kind == "steam_login":
            self.open_login(a.data["command"])
        elif a.kind == "restore_version":
            v = projectstate.stamped_version(ctx.project)
            if QMessageBox.question(
                    self, "Restore DefaultGame.ini",
                    f"Rewrite ProjectVersion {v} back to its 3-part version in "
                    "Config/DefaultGame.ini? No other line is touched.") == QMessageBox.Yes:
                projectstate.restore_base(ctx.project)
                self.refresh()

    def open_login(self, command: list[str]):
        argv = terminal_argv(command, self.ctx.host)
        line = shell_line(command, self.ctx.host)
        if argv:
            subprocess.Popen(argv)
        else:
            QApplication.clipboard().setText(line)
            QMessageBox.information(self, "Steam login",
                                    f"No terminal launcher for this OS. Command copied:\n\n{line}")

    def copy_exports(self):
        text = doctor.export_lines(self.ctx.steam_sdk, self.ctx.host, self.ctx.epic_sdk)
        if not text:
            QMessageBox.information(self, "Export lines", "Nothing to export yet: locate steamcmd first.")
            return
        QApplication.clipboard().setText(text)
        self.summary.setText("· copied to clipboard")
