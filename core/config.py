"""Configuration loading.

Three layers, so nothing secret or machine-specific is committed:
  1. <project>/uetool.toml         (committed, non-secret: app id, depot ids)
  2. <project>/uetool.local.toml   (untracked, per-machine: ue_root, steam user, apple ids)
  3. environment variables         (override both; for CI)

Machine-WIDE settings are environment variables, not in any toml, because they
are shared across every project on the machine:
  UETOOL_PYTHON       interpreter for the launcher (handled by the launcher itself)
  UETOOL_STEAM_SDK    folder containing steamcmd; the exact binary is derived per-OS
Secrets are env-only and never written to a file:
  UETOOL_STEAM_PASSWORD, UETOOL_APPLE_APP_PASSWORD
Per-machine overrides (optional, otherwise read from uetool.local.toml):
  UETOOL_UE_ROOT, UETOOL_STEAM_USER, UETOOL_APPLE_ID, UETOOL_APPLE_TEAM_ID,
  UETOOL_APPLE_SIGNING_IDENTITY, UETOOL_STEAMCMD
"""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .paths import steamcmd_for_sdk


@dataclass
class Config:
    project_root: Path
    uproject: Path
    ini_path: Path
    counter_file: Path             # <project>/.build_number (tracked)
    version_file: Path             # <project>/.version (generated)
    work_dir: Path                 # <project>/.uetool (generated working files)
    ue_root: Path | None
    stage_dir: Path                # UE's -stage output root (Saved/StagedBuilds)
    build_config: str
    app_id: str
    depot_ids: dict[str, str]      # platform -> depot id, e.g. {"win": "...", "mac": "..."}
    stage_subdirs: dict[str, str]  # platform -> staged subfolder, e.g. {"win": "Windows"}
    steam_user: str
    steam_password: str | None
    steamcmd: str
    apple_id: str
    apple_team_id: str
    apple_signing_identity: str
    apple_password: str | None     # app-specific password; env only, never a file


def _load_toml(path: Path) -> dict:
    if path.is_file():
        with path.open("rb") as fh:
            return tomllib.load(fh)
    return {}


def _find_uproject(root: Path, name_override: str | None) -> Path:
    """The project's .uproject. Auto-detected from the single *.uproject in root,
    unless [project] name pins a specific one."""
    if name_override:
        return root / f"{name_override}.uproject"
    uprojects = sorted(root.glob("*.uproject"))
    if len(uprojects) == 1:
        return uprojects[0]
    raise SystemExit(
        f"Expected exactly one .uproject in {root}, found {len(uprojects)}. "
        "Set [project] name in uetool.toml to pick one, or pass the right -P path."
    )


def load(project_root: Path) -> Config:
    root = Path(project_root).expanduser().resolve()
    base = _load_toml(root / "uetool.toml")
    local = _load_toml(root / "uetool.local.toml")

    def get(section: str, key: str, default=None):
        return local.get(section, {}).get(key, base.get(section, {}).get(key, default))

    uproject = _find_uproject(root, get("project", "name"))
    stage_rel = get("project", "stage_dir", "Saved/StagedBuilds")
    build_config = get("project", "build_config", "Shipping")

    ue_root_str = os.environ.get("UETOOL_UE_ROOT") or get("engine", "ue_root")
    ue_root = Path(ue_root_str).expanduser() if ue_root_str else None

    steam_user = os.environ.get("UETOOL_STEAM_USER") or get("steam", "user", "")
    steam_password = os.environ.get("UETOOL_STEAM_PASSWORD")  # never from a file

    # steamcmd: explicit override > derived from the machine-wide SDK folder >
    # toml value > "steamcmd" on PATH.
    steamcmd = os.environ.get("UETOOL_STEAMCMD")
    if not steamcmd:
        sdk = os.environ.get("UETOOL_STEAM_SDK")
        steamcmd = steamcmd_for_sdk(Path(sdk)) if sdk else get("steam", "steamcmd", "steamcmd")

    # Apple notarization. Identifiers may come from env (CI) or the [apple] section;
    # the app-specific password is read only from the environment, like Steam's.
    apple_id = os.environ.get("UETOOL_APPLE_ID") or get("apple", "apple_id", "")
    apple_team_id = os.environ.get("UETOOL_APPLE_TEAM_ID") or get("apple", "team_id", "")
    apple_signing_identity = (
        os.environ.get("UETOOL_APPLE_SIGNING_IDENTITY") or get("apple", "signing_identity", "")
    )
    apple_password = os.environ.get("UETOOL_APPLE_APP_PASSWORD")  # never from a file

    depot_ids = {
        "win": str(get("steam", "depot_win_id", "")),
        "mac": str(get("steam", "depot_mac_id", "")),
    }
    stage_subdirs = {
        "win": get("steam", "win_stage_subdir", "Windows"),
        "mac": get("steam", "mac_stage_subdir", "Mac"),
    }

    return Config(
        project_root=root,
        uproject=uproject,
        ini_path=root / "Config" / "DefaultGame.ini",
        counter_file=root / ".build_number",
        version_file=root / ".version",
        work_dir=root / ".uetool",
        ue_root=ue_root,
        stage_dir=(root / stage_rel),
        build_config=build_config,
        app_id=str(get("steam", "app_id", "")),
        depot_ids=depot_ids,
        stage_subdirs=stage_subdirs,
        steam_user=steam_user,
        steam_password=steam_password,
        steamcmd=steamcmd,
        apple_id=apple_id,
        apple_team_id=apple_team_id,
        apple_signing_identity=apple_signing_identity,
        apple_password=apple_password,
    )
