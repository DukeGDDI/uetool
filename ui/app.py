"""UETool Control Panel: a PySide6 front end for the uetool CLI.

    pip install -r ui/requirements.txt
    python ui/app.py [PROJECT_DIR]
    QT_QPA_PLATFORM=offscreen python ui/app.py PROJECT_DIR --shot out_prefix   # screenshots

Everything runs through the real CLI (`python uetool.py -P <project> ...`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFileDialog, QHBoxLayout, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from ui import doctor  # noqa: E402
from ui.context import Context  # noqa: E402
from ui.tab_build import BuildTab  # noqa: E402
from ui.tab_config import ConfigTab  # noqa: E402
from ui.tab_history import HistoryTab  # noqa: E402
from ui.tab_setup import SetupTab  # noqa: E402
from ui.widgets import STYLE, muted, set_role  # noqa: E402

TAB_NAMES = ["Setup", "Build", "Config", "History"]


class MainWindow(QMainWindow):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("UETool Control Panel")
        self.resize(820, 700)
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        proj = QHBoxLayout()
        proj.addWidget(muted("Project"))
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("Choose a folder containing a .uproject")
        proj.addWidget(self.path, 1)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self.pick_project)
        proj.addWidget(self.browse)
        self.ready = muted()
        proj.addWidget(self.ready)
        v.addLayout(proj)

        self.tabs = QTabWidget()
        self.tab_widgets = {"Setup": SetupTab(ctx), "Build": BuildTab(ctx),
                            "Config": ConfigTab(ctx), "History": HistoryTab(ctx)}
        for name in TAB_NAMES:
            self.tabs.addTab(self.tab_widgets[name], name)
        v.addWidget(self.tabs, 1)

        ctx.project_changed.connect(self.on_project)
        ctx.config_changed.connect(self.update_ready)
        ctx.run_state_changed.connect(self.on_run_state)
        ctx.run_finished.connect(self.update_ready)
        ctx.goto_tab.connect(lambda name, _f: self.tabs.setCurrentIndex(TAB_NAMES.index(name)))
        self.on_project()

    def pick_project(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the UE project folder",
                                             str(self.ctx.project or Path.home()))
        if d and not self.ctx.open_project(d):
            QMessageBox.warning(self, "Not a UE project", f"No .uproject file found in {d}.")

    def on_project(self):
        self.path.setText(str(self.ctx.project or ""))
        self.update_ready()

    def update_ready(self):
        if not self.ctx.project:
            self.ready.setText("")
            return
        results = doctor.run_checks(self.ctx.project, self.ctx.cfg, self.ctx.steam_sdk,
                                    epic_sdk=self.ctx.epic_sdk, host=self.ctx.host)
        ok = doctor.summary(results) == "ready"
        self.ready.setText("Ready" if ok else "Needs setup")
        set_role(self.ready, "badge-pass" if ok else "badge-fix")
        self.ready.setFixedWidth(90)
        self.ready.setAlignment(Qt.AlignCenter)

    def on_run_state(self, running: bool):
        self.browse.setEnabled(not running)
        self.statusBar().showMessage("Running…" if running else "")

    def closeEvent(self, event):
        if self.ctx.running:
            if QMessageBox.question(self, "Run in progress",
                                    "A run is in progress. Cancel it and quit?") != QMessageBox.Yes:
                event.ignore()
                return
            runner = self.tab_widgets["Build"].runner
            runner.cancel()
            from PySide6.QtCore import QEventLoop
            loop = QEventLoop()
            runner.finished.connect(lambda *_: loop.quit())
            loop.exec()
        event.accept()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    shot = None
    if "--shot" in argv:
        i = argv.index("--shot")
        shot = argv[i + 1]
        del argv[i:i + 2]
    app = QApplication([sys.argv[0]])
    app.setStyleSheet(STYLE)
    settings = None
    if shot:   # screenshots must not read or write the user's real saved settings
        import tempfile
        from PySide6.QtCore import QSettings
        settings = QSettings(str(Path(tempfile.mkdtemp()) / "shot.ini"), QSettings.IniFormat)
    ctx = Context(settings)
    win = MainWindow(ctx)
    target = argv[0] if argv else ctx.last_project()
    if target:
        ctx.open_project(target)
    win.show()
    if shot:
        for i, name in enumerate(TAB_NAMES):
            win.tabs.setCurrentIndex(i)
            app.processEvents()
            win.grab().save(f"{shot}-{name.lower()}.png")
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
