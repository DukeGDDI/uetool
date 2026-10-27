"""macOS code signing + notarization.

Windows has no equivalent of this step. A macOS .app must be signed with a
hardened runtime, notarized by Apple's notary service, and stapled before it can
be distributed without Gatekeeper warnings. This runs AFTER package() and BEFORE
the Steam upload, because stapling writes the notarization ticket into the .app
bundle that the upload then ships.

Credentials mirror the Steam handling: identifiers live in uetool.local.toml's
[apple] section (untracked), and the app-specific password is read only from the
UETOOL_APPLE_APP_PASSWORD environment variable, never from a file.
"""
from . import macsign, stage
from .config import Config
from .paths import run


def notarize(cfg: Config, dry_run: bool) -> None:
    if not cfg.apple_signing_identity:
        raise SystemExit(
            "Code-signing identity not set. Add [apple] signing_identity to "
            "uetool.local.toml (e.g. 'Developer ID Application: Name (TEAMID)')."
        )
    if not cfg.apple_id or not cfg.apple_team_id:
        raise SystemExit(
            "Apple notarization identifiers not set. Add [apple] apple_id and "
            "team_id to uetool.local.toml."
        )
    if not cfg.apple_password and not dry_run:
        raise SystemExit(
            "App-specific password not set. Export it as UETOOL_APPLE_APP_PASSWORD "
            "(an app-specific password from appleid.apple.com, not your Apple ID password)."
        )

    content_root = cfg.stage_dir / cfg.stage_subdirs["mac"]
    if not dry_run and not content_root.exists():
        raise SystemExit(f"Staged build not found at {content_root}. Run 'package --platform mac' first.")
    # A hand-staged build still carries UE's decorated bundle name; normalize it first.
    stage.normalize_mac_bundle(cfg, dry_run)

    # A real run is guarded above so the staged build exists; locate the actual
    # bundle (RunUAT names it "<Project>-<Plat>-<Config>.app", not "<Project>.app").
    # In a dry run with nothing staged yet, fall back to a representative name.
    if not dry_run or content_root.exists():
        app = macsign.find_app(content_root)
    else:
        app = content_root / f"{cfg.uproject.stem}.app"

    # 1. Sign every embedded binary inside-out, then the bundle (NOT --deep). Developer ID
    #    with a hardened runtime + secure timestamp — the notarization combination.
    macsign.sign_inside_out(app, cfg.apple_signing_identity, hardened=True, timestamp=True,
                            dry_run=dry_run)

    # Verify the signature before spending a notary round-trip.
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], dry_run)

    # 2. Zip with ditto (preserves bundle symlinks/metadata; plain `zip` corrupts them).
    work = cfg.work_dir / "notarize"
    work.mkdir(parents=True, exist_ok=True)
    zip_path = work / f"{app.stem}.zip"
    run(["ditto", "-c", "-k", "--keepParent", str(app), str(zip_path)], dry_run)

    # 3. Submit and wait for Apple's notary service.
    submit = [
        "xcrun", "notarytool", "submit", str(zip_path),
        "--apple-id", cfg.apple_id,
        "--team-id", cfg.apple_team_id,
        "--wait",
    ]
    if cfg.apple_password:
        submit += ["--password", cfg.apple_password]
    run(submit, dry_run)

    # 4. Staple the ticket into the .app so it validates offline.
    run(["xcrun", "stapler", "staple", str(app)], dry_run)
    run(["xcrun", "stapler", "validate", str(app)], dry_run)
