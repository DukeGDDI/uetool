"""Shared macOS code signing — the inside-out walk used by two backends.

`codesign --deep` is unreliable (and Apple-deprecated): it misses nested dylibs in
non-standard locations like Contents/UE/.../Binaries, so the signature is rejected. We
sign every embedded .dylib/.so individually (deepest first), then seal the .app last.

Two callers parameterize it differently:
  - notarize.py  → Developer ID identity, hardened runtime, secure timestamp, no entitlements.
  - appstore.py  → Apple Distribution identity, NO hardened runtime, no timestamp, MAS
                   entitlements applied to the bundle (nested binaries get none).
"""
from pathlib import Path

from .paths import run


def codesign(target: Path, identity: str, *, entitlements: Path | None = None,
             hardened: bool = True, timestamp: bool = True, dry_run: bool = False) -> None:
    """Sign one Mach-O/bundle. Flag order matches notarize's historical command when
    (hardened, timestamp, entitlements) are (True, True, None)."""
    cmd = ["codesign", "--force", "--timestamp" if timestamp else "--timestamp=none"]
    if hardened:
        cmd += ["--options", "runtime"]
    if entitlements is not None:
        cmd += ["--entitlements", str(entitlements)]
    cmd += ["--sign", identity, str(target)]
    run(cmd, dry_run)


def sign_inside_out(app: Path, identity: str, *, entitlements: Path | None = None,
                    hardened: bool = True, timestamp: bool = True, dry_run: bool = False) -> None:
    """Sign every embedded Mach-O deepest-first, then the bundle itself.

    Entitlements are applied only to the final bundle seal (the main executable);
    nested dylibs/helpers are signed without them, the same inside-out order."""
    libs = sorted(
        (p for p in app.rglob("*")
         if p.suffix in {".dylib", ".so"} and p.is_file() and not p.is_symlink()),
        key=lambda p: len(p.parts), reverse=True,  # deepest first
    )
    for lib in libs:
        codesign(lib, identity, hardened=hardened, timestamp=timestamp, dry_run=dry_run)
    codesign(app, identity, entitlements=entitlements, hardened=hardened,
             timestamp=timestamp, dry_run=dry_run)


def find_app(content_root: Path) -> Path:
    """Locate the single .app bundle in a staged Mac build (shared by notarize/appstore)."""
    # Prefer a top-level bundle; fall back to a recursive search for engines that nest it.
    # Exclude .app dirs that live inside another .app (helper bundles).
    candidates = sorted(content_root.glob("*.app")) or [
        p for p in content_root.rglob("*.app")
        if ".app/" not in str(p.relative_to(content_root).parent)
    ]
    if not candidates:
        raise SystemExit(
            f"No .app bundle found under {content_root}. Run 'package --platform mac' first.")
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise SystemExit(
            f"Expected one .app under {content_root}, found {len(candidates)}: {names}")
    return candidates[0]
