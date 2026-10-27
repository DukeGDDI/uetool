"""Mac App Store publishing: sign (Apple Distribution) → productbuild → altool upload.

Unlike notarize.py (Developer ID + notarytool + stapler), a MAS build is **sandboxed**,
signed with an **Apple Distribution** identity (NO hardened runtime), packaged into a
**signed installer .pkg** with a "3rd Party Mac Developer Installer" identity, and uploaded
to App Store Connect — **no notarytool, no stapler**. macOS-only and mac-target-only.

The sequence (proven end-to-end against App Store Connect's --validate-app, 2026-10-27):
  1. stamp CFBundleShortVersionString / CFBundleVersion into Info.plist (before signing, so
     the edit is sealed) — Unreal's defaults (e.g. 5.7.4 / engine build metadata) don't
     increase per upload, and App Store Connect needs a strictly increasing CFBundleVersion
  2. embed the Mac App Store provisioning profile as Contents/embedded.provisionprofile
  3. xattr -cr the bundle — a profile copied out of ~/Downloads carries com.apple.quarantine,
     which App Store processing rejects with ITMS-91109; clearing before signing is safe
  4. sign inside-out with the Apple Distribution identity + MAS entitlements (no runtime)
  5. chmod -R a+rX the bundle  — WITHOUT this, altool rejects with error 90255
     ("files only readable by root"); mode bits aren't sealed, so this doesn't break the signature
  6. productbuild --component <app> /Applications --sign "<installer identity>" <pkg>
  7. xcrun altool --upload-app (or --validate-app) --file <pkg> --type macos --apiKey … --apiIssuer …

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


def _in_project(cfg: Config, p: str) -> Path:
    """Resolve a configured path: '~' and absolute paths as-is; a relative path against the
    project root, so [appstore] paths work regardless of the working directory."""
    path = Path(p).expanduser()
    return path if path.is_absolute() else (cfg.project_root / path)


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
        return _in_project(cfg, a.entitlements_path)
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


def _resolve_api_key(cfg: Config, a: AppStoreConfig) -> None:
    """Make sure altool can find AuthKey_<KEYID>.p8. Never reads the key's bytes.

    If it's already in a conventional dir, do nothing. If api_key_path points elsewhere,
    symlink it into ~/.appstoreconnect/private_keys (a symlink copies no bytes). Otherwise
    fail with placement instructions."""
    fname = f"AuthKey_{a.asc_key_id}.p8"
    for d in _KEY_DIRS:
        if (Path(d).expanduser() / fname).is_file():
            return
    key = _in_project(cfg, a.api_key_path) if a.api_key_path else None
    if key and key.is_file():
        dest_dir = Path("~/.appstoreconnect/private_keys").expanduser()
        dest_dir.mkdir(parents=True, exist_ok=True)
        link = dest_dir / fname
        print(f"$ ln -s {key} {link}")
        if not link.exists():
            link.symlink_to(key.resolve())
        return
    raise SystemExit(
        f"App Store Connect API key not found. Place {fname} in "
        "~/.appstoreconnect/private_keys/ (altool reads it there), or set [appstore] "
        "api_key_path / UETOOL_ASC_API_KEY_PATH to the .p8. uetool never reads the key itself."
    )


def _bundle_versions(version: str) -> tuple[str, str]:
    """(CFBundleShortVersionString, CFBundleVersion) from uetool's 'vMAJOR.MINOR.PATCH.BUILD'.

    Short is the 3-part marketing version (Apple allows at most three integers); build is
    the monotonic counter, which App Store Connect requires to strictly increase on every
    upload for a given short version. A plain '.version' with no build component yields '0'."""
    nums = version.lstrip("v").split(".")
    short = ".".join(nums[:3]) or "1.0.0"
    build = nums[3] if len(nums) >= 4 else "0"
    return short, build


def _stamp_info_plist(app: Path, short_version: str, build_version: str, dry_run: bool) -> None:
    """Write CFBundleShortVersionString / CFBundleVersion into the app's Info.plist, so the
    App Store build carries uetool's version instead of Unreal's engine defaults. Called before
    signing (the edit is sealed by the signature); the plist's on-disk format is preserved."""
    info = app / "Contents" / "Info.plist"
    print(f"$ stamp {info}  CFBundleShortVersionString={short_version} CFBundleVersion={build_version}")
    if dry_run:
        return
    if not info.is_file():
        raise SystemExit(f"Info.plist not found at {info}; is this a staged .app?")
    raw = info.read_bytes()
    fmt = plistlib.FMT_BINARY if raw[:8] == b"bplist00" else plistlib.FMT_XML
    data = plistlib.loads(raw)
    data["CFBundleShortVersionString"] = short_version
    data["CFBundleVersion"] = build_version
    info.write_bytes(plistlib.dumps(data, fmt=fmt))


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

    profile = _in_project(cfg, a.provision_path)
    work = cfg.work_dir / "appstore"
    ent = _entitlements(cfg, a, work, dry_run)
    if not dry_run:
        if not profile.is_file():
            raise SystemExit(
                f"Provisioning profile not found at {profile} ([appstore] provision_path).")
        if not ent.is_file():
            raise SystemExit(f"Entitlements plist not found at {ent} ([appstore] entitlements_path).")
        _resolve_api_key(cfg, a)
        work.mkdir(parents=True, exist_ok=True)

    if custom_config:
        # MAS has no build-label field (the version comes from the bundle); a custom layer
        # is cooked into the build like any other, but changes nothing in the upload itself.
        print(f"# custom-config layer '{custom_config}' is cooked into the build (not reflected in MAS upload)")

    # 1. Stamp the App Store version into Info.plist (sealed by the signature, so before
    #    signing). Without this the bundle keeps Unreal's engine defaults (e.g. 5.7.4 / a
    #    build-metadata CFBundleVersion), which don't increase per upload — so App Store
    #    Connect treats a re-upload as a redundant binary.
    short_version, build_version = _bundle_versions(version)
    _stamp_info_plist(app, short_version, build_version, dry_run)

    # 2. Embed the provisioning profile (sealed by the signature, so before signing).
    embedded = app / "Contents" / "embedded.provisionprofile"
    run(["cp", str(profile), str(embedded)], dry_run)

    # 3. Strip extended attributes. A profile copied out of ~/Downloads carries
    #    com.apple.quarantine, which App Store processing rejects with ITMS-91109. Clearing
    #    all xattrs here (after the cp, before signing) is safe — the signature is applied next.
    run(["xattr", "-cr", str(app)], dry_run)

    # 4. Sign inside-out: Apple Distribution identity, MAS entitlements on the bundle, NO
    #    hardened runtime (that's a Developer-ID/notarization concept).
    macsign.sign_inside_out(app, a.app_identity, entitlements=ent, hardened=False,
                            timestamp=False, dry_run=dry_run)
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], dry_run)

    # 5. Make every file non-root-readable (altool error 90255). Mode bits aren't sealed.
    run(["chmod", "-R", "a+rX", str(app)], dry_run)

    # 6. Build the signed installer .pkg with the Installer identity.
    pkg = work / f"{cfg.uproject.stem}.pkg"
    run(["productbuild", "--component", str(app), "/Applications",
         "--sign", a.installer_identity, str(pkg)], dry_run)

    # 7. Upload to App Store Connect (or validate). The .p8 is found by convention; only the
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
            print(f"Uploaded {version} for {a.bundle_id} to App Store Connect "
                  f"(version {short_version}, build {build_version}).")
            print("It is NOT submitted for review. Add metadata + screenshots and submit in")
            print(f"App Store Connect:  {_ASC_URL}")
        print(bar)
