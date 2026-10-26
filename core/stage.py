"""Helpers for the staged output that package, notarize, archive and upload share.

UE names the macOS bundle after the target *and* configuration
("<Project>-Mac-Shipping.app"), and that name is fixed by the Xcode project UBT
generates, so it can't be changed from Target.cs. A Steam launch option has to
name one bundle, so uetool renames the staged bundle to "<Project>.app" right
after staging, and every later step normalizes again in case the stage folder
was produced by hand. Windows needs nothing: UAT already stages an undecorated
"<Project>.exe" launcher at the root for every configuration.

Only the folder is renamed. Info.plist's CFBundleExecutable still names the real
executable inside Contents/MacOS, and code signatures seal the contents, not the
folder name, so signing, notarization and stapling are unaffected.
"""
import plistlib
from pathlib import Path

from .config import Config


def mac_bundle(cfg: Config) -> Path:
    """Where the staged macOS bundle lives once normalized: <stage>/Mac/<Project>.app."""
    return cfg.stage_dir / cfg.stage_subdirs["mac"] / f"{cfg.uproject.stem}.app"


def mac_bundle_executable(cfg: Config) -> str:
    """The inner Mach-O name (CFBundleExecutable) of the normalized staged .app. UE keeps
    the config-decorated name inside the bundle even after the folder is renamed, so this
    is '<Project>-Mac-Shipping' for a Shipping build and '<Project>' for Development. Reads
    it from Info.plist; falls back to the project name when nothing is staged (e.g. a dry
    run with no cooked bundle). Callers that need the launch path want
    <Project>.app/Contents/MacOS/<this>."""
    info = mac_bundle(cfg) / "Contents" / "Info.plist"
    try:
        with info.open("rb") as fh:
            if exe := plistlib.load(fh).get("CFBundleExecutable"):
                return str(exe)
    except (OSError, ValueError):  # not staged, or not a readable plist
        pass
    return cfg.uproject.stem


def normalize_mac_bundle(cfg: Config, dry_run: bool = False) -> Path | None:
    """Rename a decorated staged bundle (<Project>-Mac-<Config>.app) to <Project>.app.

    Returns the bundle path, or None when nothing is staged. Already-normalized
    output is left alone. Two bundles side by side means a stale copy survived a
    manual edit, which is refused rather than guessed at."""
    target = mac_bundle(cfg)
    root = target.parent
    if not root.is_dir():
        return None
    stem = cfg.uproject.stem
    decorated = sorted(p for p in root.glob(f"{stem}-Mac-*.app") if p.is_dir())
    if target.is_dir():
        if decorated:
            raise SystemExit(
                f"Both {target.name} and {decorated[0].name} exist in {root}. "
                "Delete the stale one, or run 'package' again to restage from scratch."
            )
        return target
    if not decorated:
        return None
    if len(decorated) > 1:
        names = ", ".join(p.name for p in decorated)
        raise SystemExit(
            f"Expected one staged bundle in {root}, found {len(decorated)}: {names}. "
            "Run 'package' again to restage from scratch."
        )
    print(f"$ mv {decorated[0]} {target}")
    if not dry_run:
        decorated[0].rename(target)
    return target
