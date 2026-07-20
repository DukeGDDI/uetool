"""Zip the staged build into a distributable archive (non-Steam distribution).

For hosts that take a packaged build directly rather than a Steam depot — Arcware
pixel streaming, itch.io, a plain download. Produces
<project>/.uetool/dist/<Project>-<version>-<platform>.zip with the game's
executable at the archive root (the CONTENTS of the staged folder are zipped, not
the folder itself), so the host finds the .exe immediately on extract.
"""
import os
import zipfile
from pathlib import Path

from . import version as ver
from .config import Config


def _add_symlink(zf: zipfile.ZipFile, path: Path, stage_root: Path) -> None:
    """Store a symlink as a symlink (e.g. macOS .app framework links) rather than
    copying its target — keeps bundles valid and the zip small."""
    st = path.lstat()
    info = zipfile.ZipInfo(path.relative_to(stage_root).as_posix())
    info.create_system = 3  # Unix, so the symlink mode bits are honored on extract
    info.external_attr = (st.st_mode & 0xFFFF) << 16
    zf.writestr(info, os.readlink(path))


def archive(cfg: Config, target: str, dry_run: bool) -> Path:
    stage_root = cfg.stage_dir / cfg.stage_subdirs[target]
    version = ver.compute(cfg)
    dist = cfg.work_dir / "dist"
    zip_path = dist / f"{cfg.uproject.stem}-{version}-{target}.zip"

    print(f"$ archive {stage_root} -> {zip_path}")
    if dry_run:
        return zip_path

    if not stage_root.is_dir():
        raise SystemExit(
            f"Staged build not found at {stage_root}. "
            f"Run `uetool package --platform {target}` first."
        )

    dist.mkdir(parents=True, exist_ok=True)
    count = 0
    # allowZip64 defaults True (UE builds exceed 4 GB). os.walk with
    # followlinks=False avoids descending into symlinked dirs (no duplication).
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(stage_root, followlinks=False):
            dp = Path(dirpath)
            for name in dirnames:                       # symlinked dirs, not recursed
                p = dp / name
                if p.is_symlink():
                    _add_symlink(zf, p, stage_root)
                    count += 1
            for name in filenames:
                p = dp / name
                if p.is_symlink():
                    _add_symlink(zf, p, stage_root)
                else:
                    # zf.write streams the file (safe for multi-GB paks) and
                    # preserves the Unix mode, incl. the exec bit for Linux/Mac.
                    zf.write(p, p.relative_to(stage_root).as_posix())
                count += 1

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"Archived {count} files -> {zip_path} ({size_mb:.0f} MB)")
    return zip_path
