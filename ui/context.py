"""State shared by every tab: the open project, its config, machine settings."""
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal

from core.paths import host_platform

from . import keychain
from .configstore import ProjectConfig


class Context(QObject):
    project_changed = Signal()
    config_changed = Signal()      # config saved/reverted, or a setting/secret changed
    run_state_changed = Signal(bool)
    run_finished = Signal()
    goto_tab = Signal(str, str)    # tab name, field to focus ("" for none)

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.settings = settings or QSettings("UETool", "ControlPanel")
        self.project: Path | None = None
        self.cfg: ProjectConfig | None = None
        self.running = False
        self.host = host_platform()

    # -- project -----------------------------------------------------------
    def open_project(self, path: Path | str) -> bool:
        """Accept a project folder or a .uproject file. False if it isn't a UE project."""
        p = Path(path).expanduser()
        if p.suffix == ".uproject":
            p = p.parent
        if not p.is_dir() or not list(p.glob("*.uproject")):
            return False
        self.project = p.resolve()
        self.cfg = ProjectConfig(self.project)
        self.settings.setValue("last_project", str(self.project))
        self.project_changed.emit()
        return True

    def last_project(self) -> str:
        return self.settings.value("last_project", "", str)

    # -- machine-wide settings (not in any project file) --------------------
    @property
    def steam_sdk(self) -> str:
        return self.settings.value("steam_sdk", "", str)

    @steam_sdk.setter
    def steam_sdk(self, value: str) -> None:
        self.settings.setValue("steam_sdk", value.strip())
        self.config_changed.emit()

    @property
    def epic_sdk(self) -> str:
        return self.settings.value("epic_sdk", "", str)

    @epic_sdk.setter
    def epic_sdk(self, value: str) -> None:
        self.settings.setValue("epic_sdk", value.strip())
        self.config_changed.emit()

    def run_env(self) -> dict[str, str]:
        """Extras for the child process: the SDK folders and keychain secrets. They go
        into the child's environment only; nothing is written to disk. Empty values are
        dropped so they don't blank out a variable the child already inherits."""
        env = {"UETOOL_STEAM_SDK": self.steam_sdk, "UETOOL_EPIC_SDK": self.epic_sdk}
        if self.cfg:
            env.update(keychain.env_for(self.cfg.get("steam_user"), self.cfg.get("apple_id"),
                                        self.cfg.get("epic_client_id")))
        return {k: v for k, v in env.items() if v}

    def set_running(self, running: bool) -> None:
        self.running = running
        self.run_state_changed.emit(running)
        if not running:
            self.run_finished.emit()
