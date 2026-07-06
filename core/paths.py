"""Platform-aware path and process helpers."""
import os
import subprocess
import sys
from pathlib import Path


def host_is_windows() -> bool:
    return os.name == "nt"


def host_is_macos() -> bool:
    return sys.platform == "darwin"


def host_platform() -> str:
    """Default build target for this host: 'win' or 'mac'."""
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "win"


def runuat_path(ue_root: Path) -> Path:
    """RunUAT entrypoint for the *host* (the engine that does the packaging)."""
    name = "RunUAT.bat" if host_is_windows() else "RunUAT.sh"
    return Path(ue_root) / "Engine" / "Build" / "BatchFiles" / name


def build_script_path(ue_root: Path) -> Path:
    """UnrealBuildTool's Build script for the *host*, used to build the editor
    target (Build.bat on Windows, Mac/Build.sh on macOS, Linux/Build.sh else)."""
    base = Path(ue_root) / "Engine" / "Build" / "BatchFiles"
    if host_is_windows():
        return base / "Build.bat"
    if host_is_macos():
        return base / "Mac" / "Build.sh"
    return base / "Linux" / "Build.sh"


def steamcmd_for_sdk(sdk: Path | None) -> str:
    """Resolve the steamcmd executable from UETOOL_STEAM_SDK, per host OS.

    The env var may point at a standalone steamcmd folder or a full Steamworks
    SDK; we probe the usual layouts and fall back to 'steamcmd' on PATH.
    """
    if not sdk:
        return "steamcmd"
    sdk = Path(sdk).expanduser()
    if host_is_windows():
        rels = ["steamcmd.exe", "builder/steamcmd.exe",
                "tools/ContentBuilder/builder/steamcmd.exe"]
    elif host_is_macos():
        rels = ["steamcmd.sh", "builder_osx/steamcmd.sh",
                "tools/ContentBuilder/builder_osx/steamcmd.sh"]
    else:
        rels = ["steamcmd.sh", "builder_linux/steamcmd.sh",
                "tools/ContentBuilder/builder_linux/steamcmd.sh"]
    for rel in rels:
        candidate = sdk / rel
        if candidate.exists():
            return str(candidate)
    return "steamcmd"


def run(args, dry_run: bool = False) -> None:
    """Run an external command, streaming its output. Raises on non-zero exit."""
    printable = subprocess.list2cmdline([str(a) for a in args])
    print(f"$ {printable}")
    if dry_run:
        return
    subprocess.run([str(a) for a in args], check=True)
