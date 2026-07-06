"""Packaging via Unreal's RunUAT BuildCookRun."""
from pathlib import Path

from . import version as ver
from .config import Config
from .paths import build_script_path, host_is_windows, host_platform, run, runuat_path

_UE_PLATFORM = {"win": "Win64", "mac": "Mac"}


def _editor_target_file(cfg: Config) -> Path:
    """The editor .target receipt RunUAT's cook step reads, for the host platform."""
    host_dir = _UE_PLATFORM[host_platform()]
    return cfg.uproject.parent / "Binaries" / host_dir / f"{cfg.uproject.stem}Editor.target"


def bootstrap(cfg: Config, dry_run: bool, force: bool = False) -> bool:
    """Build the editor target so RunUAT's cook step finds its .target receipt.

    On a fresh checkout of a C++ project, Binaries/<host>/<Project>Editor.target
    does not exist yet, and RunUAT's Cook reads it before doing anything — failing
    with "Could not find file ...Editor.target". Normally you'd first open the
    project in the editor (or build it in Rider / Visual Studio); this does the same
    thing headlessly by invoking UnrealBuildTool via Build.bat/Build.sh, so the tool
    works on a clean checkout with no manual pre-build.

    Idempotent: returns False without building when the receipt already exists
    (unless force=True); returns True when it runs a build.
    """
    if cfg.ue_root is None:
        raise SystemExit(
            "Engine path not set. Add [engine] ue_root to uetool.local.toml "
            "or set the UETOOL_UE_ROOT environment variable."
        )

    if _editor_target_file(cfg).exists() and not force:
        return False

    build_script = build_script_path(cfg.ue_root)
    if not dry_run and not build_script.exists():
        raise SystemExit(f"UnrealBuildTool Build script not found at {build_script}")

    editor_target = f"{cfg.uproject.stem}Editor"
    host_ue = _UE_PLATFORM[host_platform()]
    cmd = [
        str(build_script), editor_target, host_ue, "Development",
        f"-project={cfg.uproject}", "-WaitMutex",
    ]
    if build_script.suffix.lower() == ".bat" and host_is_windows():
        cmd = ["cmd", "/c"] + cmd

    print(f"# fresh checkout: building {editor_target} ({host_ue} Development) "
          f"so RunUAT has its .target receipt")
    run(cmd, dry_run)
    return True


def package(cfg: Config, target: str, build_config: str, dry_run: bool,
            bootstrap_if_needed: bool = True) -> None:
    if cfg.ue_root is None:
        raise SystemExit(
            "Engine path not set. Add [engine] ue_root to uetool.local.toml "
            "or set the UETOOL_UE_ROOT environment variable."
        )

    # A fresh checkout has no editor .target receipt; build it first so RunUAT's
    # cook step can start (see bootstrap()). No-op once the project has been built.
    if bootstrap_if_needed:
        bootstrap(cfg, dry_run)

    runuat = runuat_path(cfg.ue_root)
    if not dry_run and not runuat.exists():
        raise SystemExit(f"RunUAT not found at {runuat}")

    # We deliberately do NOT pass -archive/-archivedirectory. On Mac that step
    # copies the bare Binaries/.app (no cooked content) instead of the staged
    # bundle, producing an app that fails with "Failed to open descriptor file".
    # The self-contained build from -stage lands in cfg.stage_dir/<subdir>.
    cmd = [
        str(runuat), "BuildCookRun",
        f"-project={cfg.uproject}",
        "-noP4",
        f"-platform={_UE_PLATFORM[target]}",
        f"-clientconfig={build_config}",
        "-cook", "-build", "-stage", "-pak",
        "-nocompileeditor", "-utf8output",
    ]

    # On Windows, .bat files must be launched through cmd.exe.
    if runuat.suffix.lower() == ".bat" and host_is_windows():
        cmd = ["cmd", "/c"] + cmd

    base_version = ver.base(cfg)
    full_version = ver.compute(cfg)  # base + build counter

    if dry_run:
        print(f"# would stamp ProjectVersion={full_version} for the cook, "
              f"then restore the base {base_version}")
        run(cmd, dry_run)
        return

    # Stamp the full build version into DefaultGame.ini so the cook embeds it,
    # then restore the authored base so source control never accumulates ".N".
    # The finally guard restores even if the build fails or is interrupted.
    ver.stamp(cfg, full_version)
    cfg.version_file.write_text(f"{full_version}\n", encoding="utf-8")
    try:
        run(cmd, dry_run)
    finally:
        ver.stamp(cfg, base_version)
