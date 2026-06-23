"""Packaging via Unreal's RunUAT BuildCookRun."""
from .config import Config
from .paths import host_is_windows, run, runuat_path

_UE_PLATFORM = {"win": "Win64", "mac": "Mac"}


def package(cfg: Config, target: str, build_config: str, dry_run: bool) -> None:
    if cfg.ue_root is None:
        raise SystemExit(
            "Engine path not set. Add [engine] ue_root to uetool.local.toml "
            "or set the UETOOL_UE_ROOT environment variable."
        )

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

    run(cmd, dry_run)
