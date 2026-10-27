"""Mac App Store publishing: sign (Apple Distribution) → productbuild → altool upload.

Unlike notarize.py (Developer ID + notarytool + stapler), a MAS build is **sandboxed**,
signed with an **Apple Distribution** identity (NO hardened runtime), packaged into a
**signed installer .pkg** with a "3rd Party Mac Developer Installer" identity, and uploaded
to App Store Connect — **no notarytool, no stapler**. macOS-only and mac-target-only.

The sequence (proven end-to-end against App Store Connect's --validate-app, 2026-10-27):
  1. embed the Mac App Store provisioning profile as Contents/embedded.provisionprofile
  2. sign inside-out with the Apple Distribution identity + MAS entitlements (no runtime)
  3. chmod -R a+rX the bundle  — WITHOUT this, altool rejects with error 90255
     ("files only readable by root"); mode bits aren't sealed, so this doesn't break the signature
  4. productbuild --component <app> /Applications --sign "<installer identity>" <pkg>
  5. xcrun altool --upload-app (or --validate-app) --file <pkg> --type macos --apiKey … --apiIssuer …

The App Store Connect API key (.p8) is read by altool from ~/.appstoreconnect/private_keys
by filename convention (AuthKey_<KEYID>.p8); uetool passes only the non-secret key id +
issuer id and never reads, copies, or prints the key itself.
"""
import plistlib
import shutil
from pathlib import Path

from . import macsign, stage
from .config import AppStoreConfig, Config
from .paths import host_is_macos, run

_ASC_URL = "https://appstoreconnect.apple.com/apps"
# altool finds AuthKey_<KEYID>.p8 in one of these, in Apple's documented search order.
_KEY_DIRS = ("./private_keys", "~/private_keys", "~/.private_keys", "~/.appstoreconnect/private_keys")


def _require_appstore(cfg: Config) -> AppStoreConfig:
    a = cfg.appstore
    if a is None:
        raise SystemExit(
            "No [appstore] target configured. Add bundle_id / team_id / app_identity / "
            "installer_identity / provision_path / asc_key_id / asc_issuer_id under [appstore] "
            "in uetool.toml (macOS only)."
        )
    missing = [n for n, v in (
        ("bundle_id", a.bundle_id), ("team_id", a.team_id), ("app_identity", a.app_identity),
        ("installer_identity", a.installer_identity), ("provision_path", a.provision_path),
        ("asc_key_id", a.asc_key_id), ("asc_issuer_id", a.asc_issuer_id)) if not v]
    if missing:
        raise SystemExit(f"[appstore] is missing {', '.join(missing)} in uetool.toml.")
    return a


def _ensure_mac(target: str) -> None:
    """MAS is macOS-only AND mac-target-only (enforced here so a direct call can't bypass
    the CLI guard)."""
    if not host_is_macos():
        raise SystemExit("Mac App Store publishing needs macOS (codesign + productbuild + altool).")
    if target != "mac":
        raise SystemExit("Mac App Store publishing is mac-only; use --platform mac.")


def _read_version(cfg: Config) -> str:
    if cfg.version_file.exists():
        v = cfg.version_file.read_text(encoding="utf-8").strip()
        if v:
            return v
    raise SystemExit(f"No version recorded at {cfg.version_file}. Run 'bump' or 'package' first.")


def _entitlements(cfg: Config, a: AppStoreConfig, work: Path, dry_run: bool) -> Path:
    """The MAS entitlements plist: the configured file, or one generated here (app-sandbox
    + network.client + the application/team identifiers that match the provisioning profile)."""
    if a.entitlements_path:
        return Path(a.entitlements_path).expanduser()
    ent = work / "mas.entitlements"
    print(f"$ write {ent}  (app-sandbox + network.client)")
    if not dry_run:
        work.mkdir(parents=True, exist_ok=True)
        with ent.open("wb") as fh:
            plistlib.dump({
                "com.apple.application-identifier": f"{a.team_id}.{a.bundle_id}",
                "com.apple.developer.team-identifier": a.team_id,
                "com.apple.security.app-sandbox": True,
                "com.apple.security.network.client": True,
            }, fh)
    return ent


def _resolve_api_key(a: AppStoreConfig) -> None:
    """Make sure altool can find AuthKey_<KEYID>.p8. Never reads the key's bytes.

    If it's already in a conventional dir, do nothing. If api_key_path points elsewhere,
    symlink it into ~/.appstoreconnect/private_keys (a symlink copies no bytes). Otherwise
    fail with placement instructions."""
    fname = f"AuthKey_{a.asc_key_id}.p8"
    for d in _KEY_DIRS:
        if (Path(d).expanduser() / fname).is_file():
            return
    if a.api_key_path and Path(a.api_key_path).expanduser().is_file():
        dest_dir = Path("~/.appstoreconnect/private_keys").expanduser()
        dest_dir.mkdir(parents=True, exist_ok=True)
        link = dest_dir / fname
        print(f"$ ln -s {a.api_key_path} {link}")
        if not link.exists():
            link.symlink_to(Path(a.api_key_path).expanduser().resolve())
        return
    raise SystemExit(
        f"App Store Connect API key not found. Place {fname} in "
        "~/.appstoreconnect/private_keys/ (altool reads it there), or set [appstore] "
        "api_key_path / UETOOL_ASC_API_KEY_PATH to the .p8. uetool never reads the key itself."
    )


def upload(cfg: Config, target: str, dry_run: bool, custom_config: str | None = None,
           validate: bool = False) -> None:
    """Sign the staged macOS build for the App Store, build a signed .pkg, and upload it
    (or, with validate=True, rehearse via altool --validate-app without submitting)."""
    a = _require_appstore(cfg)
    _ensure_mac(target)
    version = _read_version(cfg)

    content_root = cfg.stage_dir / cfg.stage_subdirs["mac"]
    if not dry_run and not content_root.exists():
        raise SystemExit(
            f"Staged build not found at {content_root}. Run 'package --platform mac' first.")
    stage.normalize_mac_bundle(cfg, dry_run)
    if not dry_run or content_root.exists():
        app = macsign.find_app(content_root)
    else:
        app = content_root / f"{cfg.uproject.stem}.app"

    profile = Path(a.provision_path).expanduser()
    work = cfg.work_dir / "appstore"
    ent = _entitlements(cfg, a, work, dry_run)
    if not dry_run:
        if not profile.is_file():
            raise SystemExit(
                f"Provisioning profile not found at {profile} ([appstore] provision_path).")
        if not ent.is_file():
            raise SystemExit(f"Entitlements plist not found at {ent} ([appstore] entitlements_path).")
        _resolve_api_key(a)
        work.mkdir(parents=True, exist_ok=True)

    if custom_config:
        # MAS has no build-label field (the version comes from the bundle); a custom layer
        # is cooked into the build like any other, but changes nothing in the upload itself.
        print(f"# custom-config layer '{custom_config}' is cooked into the build (not reflected in MAS upload)")

    # 1. Embed the provisioning profile (sealed by the signature, so before signing).
    embedded = app / "Contents" / "embedded.provisionprofile"
    run(["cp", str(profile), str(embedded)], dry_run)

    # 2. Sign inside-out: Apple Distribution identity, MAS entitlements on the bundle, NO
    #    hardened runtime (that's a Developer-ID/notarization concept).
    macsign.sign_inside_out(app, a.app_identity, entitlements=ent, hardened=False,
                            timestamp=False, dry_run=dry_run)
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], dry_run)

    # 3. Make every file non-root-readable (altool error 90255). Mode bits aren't sealed.
    run(["chmod", "-R", "a+rX", str(app)], dry_run)

    # 4. Build the signed installer .pkg with the Installer identity.
    pkg = work / f"{cfg.uproject.stem}.pkg"
    run(["productbuild", "--component", str(app), "/Applications",
         "--sign", a.installer_identity, str(pkg)], dry_run)

    # 5. Upload to App Store Connect (or validate). The .p8 is found by convention; only the
    #    non-secret key id + issuer id are on the command line.
    verb = "--validate-app" if validate else "--upload-app"
    run(["xcrun", "altool", verb, "--file", str(pkg), "--type", "macos",
         "--apiKey", a.asc_key_id, "--apiIssuer", a.asc_issuer_id], dry_run)

    if not dry_run:
        bar = "=" * 72
        print(f"\n{bar}")
        if validate:
            print(f"Validated {version} for {a.bundle_id} (App Store Connect rehearsal, NOT uploaded).")
        else:
            print(f"Uploaded {version} for {a.bundle_id} to App Store Connect.")
            print("It is NOT submitted for review. Add metadata + screenshots and submit in")
            print(f"App Store Connect:  {_ASC_URL}")
        print(bar)
