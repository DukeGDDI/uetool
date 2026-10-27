"""Non-functional PySide6 mockup of the proposed UETool Control Panel.

Nothing here runs uetool: every value is hard-coded sample data. The one piece of
live behaviour is the command preview on the Build tab, which rebuilds from the
form so the real design (UI builds the CLI string) is visible.

    pip install PySide6
    python ui/mockup.py                      # open the window
    python ui/mockup.py --shot out.png       # save a screenshot of every tab
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

STYLE = """
QLabel[role="muted"] { color: #6b6b6b; }
QLabel[role="badge-ok"]   { background:#e3f4e1; color:#1e6b2a; border-radius:4px; padding:2px 8px; }
QLabel[role="badge-warn"] { background:#fbf0d2; color:#8a5a00; border-radius:4px; padding:2px 8px; }
QLabel[role="badge-fail"] { background:#fbe3e1; color:#a0281f; border-radius:4px; padding:2px 8px; }
QLabel[role="warn-box"]   { background:#fbf0d2; color:#8a5a00; border-radius:6px; padding:8px; }
QLabel[role="err"]        { color:#a0281f; }
QPlainTextEdit[role="mono"], QLineEdit[role="mono"] {
    font-family: Menlo, Consolas, monospace; background:#f4f4f2; border:1px solid #ddd; border-radius:6px; }
QPushButton[role="primary"] { background:#1f6feb; color:white; border:none; border-radius:5px; padding:6px 16px; }
QPushButton[role="primary"]:disabled { background:#9db9e8; }
"""


def muted(text):
    lab = QLabel(text)
    lab.setProperty("role", "muted")
    return lab


def badge(text, kind):
    lab = QLabel(text)
    lab.setProperty("role", f"badge-{kind}")
    lab.setFixedWidth(52)
    lab.setAlignment(Qt.AlignCenter)
    return lab


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#e2e2e0;")
    return f


class SetupTab(QWidget):
    CHECKS = [
        ("ok", "Python 3.11+", "Found 3.13.1 at /opt/homebrew/bin/python3.13", None),
        ("ok", "Single .uproject", "MyGame.uproject", None),
        ("warn", "Unreal Engine root",
         "Detected UE_5.7 in /Users/Shared/Epic Games. Not saved yet.", "Use this"),
        ("fail", "steamcmd", "UETOOL_STEAM_SDK is not set.", "Locate…"),
        ("fail", "Steam login cached",
         "Run the one-time login to cache the Steam Guard sentry.", "Open login terminal"),
        ("warn", "Steam ids",
         "app_id and depot_win_id are still placeholder values (0000…).", "Open Config"),
        ("ok", "Apple signing", "Not needed on this machine (Windows target).", None),
    ]

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("Setup doctor")
        title.setStyleSheet("font-weight:600; font-size:14px;")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(QPushButton("Re-check all"))
        outer.addLayout(head)
        for kind, name, detail, action in self.CHECKS:
            outer.addWidget(hline())
            row = QHBoxLayout()
            row.addWidget(badge({"ok": "Pass", "warn": "Fix", "fail": "Fail"}[kind], kind))
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(QLabel(name))
            col.addWidget(muted(detail))
            row.addLayout(col, 1)
            if action:
                row.addWidget(QPushButton(action))
            outer.addLayout(row)
        outer.addStretch()


class BuildTab(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)

        grid = QGridLayout()
        self.command = QComboBox()
        self.command.addItems(["release", "package", "archive", "upload",
                               "notarize", "bootstrap", "bump"])
        self.platform = QComboBox()
        self.platform.addItems(["win", "mac"])
        self.config = QComboBox()
        self.config.addItems(["Shipping", "Development"])
        self.layer = QComboBox()
        self.layer.addItems(["none", "Demo"])
        for i, (label, w) in enumerate([("Command", self.command), ("Platform", self.platform),
                                        ("Build configuration", self.config),
                                        ("Custom config layer", self.layer)]):
            grid.addWidget(muted(label), (i // 2) * 2, i % 2)
            grid.addWidget(w, (i // 2) * 2 + 1, i % 2)
        outer.addLayout(grid)
        self.layer_hint = muted("Disabled for release, which uploads to Steam.")
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

        self.clean_warn = QLabel("Clean build deletes Binaries, Intermediate and "
                                 "Saved/Cooked. You'll be asked to confirm.")
        self.clean_warn.setProperty("role", "warn-box")
        self.clean_warn.setWordWrap(True)
        outer.addWidget(self.clean_warn)

        self.preview = QLineEdit()
        self.preview.setReadOnly(True)
        self.preview.setProperty("role", "mono")
        outer.addWidget(self.preview)

        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Dry run"))
        run = QPushButton("▶  Run")
        run.setProperty("role", "primary")
        buttons.addWidget(run)
        cancel = QPushButton("Cancel")
        cancel.setEnabled(False)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(muted("Idle"))
        outer.addLayout(buttons)

        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setProperty("role", "mono")
        log.setPlainText(
            "$ uetool -P ~/games/MyGame release --platform win --dry-run\n"
            "Version: v1.2.0.48\n"
            "$ Build.bat MyGameEditor Win64 Development -project=… -WaitMutex\n"
            "$ RunUAT.bat BuildCookRun -project=… -platform=Win64 -clientconfig=Shipping "
            "-cook -build -stage -pak\n"
            "$ steamcmd +login build_acct +run_app_build …\n"
            "This build is NOT live yet. Set it live on a branch in Steamworks.\n"
            "Exit code 0")
        outer.addWidget(log, 1)

        for w in (self.command, self.platform, self.config, self.layer):
            w.currentIndexChanged.connect(self.refresh)
        for c in (self.bump, self.bootstrap, self.clean):
            c.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self):
        cmd = self.command.currentText()
        is_release = cmd == "release"
        can_layer = cmd in ("package",)
        self.layer.setEnabled(can_layer)
        self.layer_hint.setVisible(is_release)
        has_flags = cmd in ("package", "release")
        for c in (self.bump, self.bootstrap, self.clean):
            c.setEnabled(has_flags)
        self.clean_warn.setVisible(self.clean.isChecked() and has_flags)

        parts = ["uetool", "-P", "~/games/MyGame", cmd]
        if cmd not in ("bootstrap",):
            parts += ["--platform", self.platform.currentText()]
        if cmd in ("package", "release", "upload", "notarize", "bump"):
            parts += ["--config", self.config.currentText()]
        if has_flags:
            if not self.bump.isChecked():
                parts.append("--no-bump")
            if not self.bootstrap.isChecked():
                parts.append("--no-bootstrap")
            if self.clean.isChecked():
                parts.append("--clean")
        if can_layer and self.layer.currentText() != "none":
            parts += ["--custom-config", self.layer.currentText()]
        self.preview.setText("$ " + " ".join(parts))


class ConfigTab(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)

        shared = QGroupBox("uetool.toml (committed)")
        f1 = QFormLayout(shared)
        build_cfg = QComboBox()
        build_cfg.addItems(["Shipping", "Development"])
        f1.addRow("Build configuration", build_cfg)
        f1.addRow("Stage directory", QLineEdit("Saved/StagedBuilds"))
        for label in ("Steam app id", "Windows depot id"):
            edit = QLineEdit("0000000" if "app" in label else "0000001")
            edit.setStyleSheet("border:1px solid #d0463b;")
            f1.addRow(label, edit)
        outer.addWidget(shared)
        err = QLabel("Replace the placeholder ids with the ones from your Steamworks app.")
        err.setProperty("role", "err")
        outer.addWidget(err)

        local = QGroupBox("uetool.local.toml (this machine only)")
        f2 = QFormLayout(local)
        f2.addRow("Unreal Engine root", QLineEdit("C:/Program Files/Epic Games/UE_5.7"))
        f2.addRow("Steam build account", QLineEdit("build_acct"))
        pw = QLineEdit("Stored in your OS keychain")
        pw.setEnabled(False)
        f2.addRow("Steam password", pw)
        apple = QLineEdit()
        apple.setEnabled(False)
        f2.addRow("Apple ID (macOS only)", apple)
        outer.addWidget(local)

        row = QHBoxLayout()
        row.addWidget(QPushButton("Revert"))
        save = QPushButton("Save")
        save.setProperty("role", "primary")
        row.addWidget(save)
        row.addWidget(muted("Comments in the files are preserved."))
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch()


class HistoryTab(QWidget):
    ROWS = [
        ("MyGame-v1.2.0.48-win.zip", "win", "3.4 GB", "Today 14:02"),
        ("MyGame-v1.2.0.47-win.zip", "win", "3.4 GB", "Yesterday"),
        ("MyGame-v1.2.0.47-mac.zip", "mac", "3.1 GB", "Yesterday"),
    ]

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        ver = QVBoxLayout()
        ver.addWidget(muted("Current version"))
        v = QLabel("v1.2.0.48")
        v.setStyleSheet("font-size:20px; font-weight:600;")
        ver.addWidget(v)
        top.addLayout(ver)
        top.addSpacing(32)
        st = QVBoxLayout()
        st.addWidget(muted("Steam state"))
        b = QLabel("Uploaded, not live")
        b.setProperty("role", "badge-warn")
        st.addWidget(b)
        top.addLayout(st)
        top.addStretch()
        outer.addLayout(top)

        table = QTableWidget(len(self.ROWS), 4)
        table.setHorizontalHeaderLabels(["Archive", "Platform", "Size", "Created"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for r, row in enumerate(self.ROWS):
            for c, text in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(text))
        outer.addWidget(table, 1)

        btns = QHBoxLayout()
        btns.addWidget(QPushButton("Reveal in folder"))
        btns.addWidget(QPushButton("Open Steamworks builds page"))
        btns.addStretch()
        outer.addLayout(btns)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UETool Control Panel (mockup)")
        self.resize(760, 640)
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        proj = QHBoxLayout()
        proj.addWidget(muted("Project"))
        path = QLineEdit("~/games/MyGame/MyGame.uproject")
        path.setReadOnly(True)
        proj.addWidget(path, 1)
        proj.addWidget(QPushButton("Browse…"))
        proj.addWidget(badge("Ready", "ok"))
        v.addLayout(proj)

        self.tabs = QTabWidget()
        for widget, name in ((SetupTab(), "Setup"), (BuildTab(), "Build"),
                             (ConfigTab(), "Config"), (HistoryTab(), "History")):
            self.tabs.addTab(widget, name)
        v.addWidget(self.tabs, 1)

        self.statusBar().showMessage("Last run: release win, exit 0")


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    if "--shot" in sys.argv:
        base = sys.argv[sys.argv.index("--shot") + 1]
        stem = base.rsplit(".", 1)[0]
        win.show()
        for i, name in enumerate(["setup", "build", "config", "history"]):
            win.tabs.setCurrentIndex(i)
            app.processEvents()
            win.grab().save(f"{stem}-{name}.png")
        return 0
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
