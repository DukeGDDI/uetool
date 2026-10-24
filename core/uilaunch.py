"""Launch the PySide6 Control Panel (ui/app.py) as a detached process.

core/ stays stdlib-only: this only *spawns* a PySide6-capable interpreter, it never
imports PySide6 itself. The interpreter is resolved from the uetool INSTALL dir (the
folder holding uetool.py / core/ / ui/ / .venv), found via __file__ — never the UE
project, which is only the argument saying which project to open. So `uetool ui` works
from anywhere once the install-dir venv exists.
"""
import os
import subprocess
import sys
from pathlib import Path

# The uetool install directory (resolve() follows a PATH symlink to the real location).
INSTALL_DIR = Path(__file__).resolve().parent.parent
UI_APP = INSTALL_DIR / "ui" / "app.py"


def _venv_python(install_dir: Path) -> Path | None:
    """The install-dir virtualenv interpreter, if present — Windows then POSIX layout."""
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        cand = install_dir.joinpath(".venv", *rel)
        if cand.is_file():
            return cand
    return None


def _has_pyside(python: str) -> bool:
    try:
        return subprocess.run([python, "-c", "import PySide6"],
                              capture_output=True).returncode == 0
    except OSError:
        return False


def resolve_python(install_dir: Path = INSTALL_DIR, require: bool = True) -> str:
    """Pick a PySide6-capable interpreter for the UI, in order:
    UETOOL_UI_PYTHON > install-dir .venv > the current interpreter.

    With require=True (a real launch) the current-interpreter fallback is only taken
    when it actually imports PySide6, otherwise SystemExit explains how to create the
    venv. With require=False (dry run) the best candidate is returned without checking.
    """
    override = os.environ.get("UETOOL_UI_PYTHON")
    if override:
        return override
    if venv := _venv_python(install_dir):
        return str(venv)
    if not require or _has_pyside(sys.executable):
        return sys.executable
    venv_dir = install_dir / ".venv"
    raise SystemExit(
        "The Control Panel needs PySide6, which isn't installed for any interpreter uetool "
        "can find.\nCreate the UI venv in the uetool install dir and install its deps:\n"
        f"  python3 -m venv {venv_dir}\n"
        f"  {venv_dir / 'bin' / 'python'} -m pip install -r {UI_APP.parent / 'requirements.txt'}\n"
        "(Windows: use .venv\\Scripts\\python.exe). Or set UETOOL_UI_PYTHON to a Python with PySide6."
    )


def _popen_kwargs() -> dict:
    """Detach the child so closing the terminal doesn't kill the UI, on either OS."""
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kw["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kw["close_fds"] = True
    else:
        kw["start_new_session"] = True  # setsid: no SIGHUP when the terminal closes
    return kw


def launch(target: Path | None, dry_run: bool = False) -> int:
    """Open the Control Panel detached, returning immediately. `target` is the project
    to open (None lets the UI fall back to its last-used project)."""
    python = resolve_python(require=not dry_run)
    argv = [str(python), str(UI_APP)] + ([str(target)] if target else [])

    if dry_run:
        print("$ " + subprocess.list2cmdline(argv))
        return 0

    subprocess.Popen(argv, cwd=str(INSTALL_DIR), **_popen_kwargs())
    where = f" for {target}" if target else ""
    print(f"Launched the UETool Control Panel{where}. Close the window to quit; this terminal is free.")
    return 0
