"""uetool — build & Steam release CLI for Unreal Engine projects.

Cross-platform orchestration around Unreal's RunUAT (packaging), Apple's
codesign/notarytool (macOS signing), and steamcmd (Steam upload). Runs against
the UE project at the current directory, or one given with -P/--project:

    uetool bump
    uetool package [--platform win|mac] [--config Shipping] [--no-bump]
                   [--custom-config Arcware]
    uetool upload [--app main|demo|playtest]
    uetool notarize
    uetool release [--app ...] [--custom-config NAME]   # bump -> package -> [notarize] -> upload
    uetool -P /path/to/Project release --platform mac --app playtest

--app picks which of the project's Steam apps ([steam.main] / [steam.demo] /
[steam.playtest] in uetool.toml) receives the upload. It may be omitted only when
exactly one app is configured.

Add --dry-run to any command to print the external commands without running them.
"""
import argparse
from pathlib import Path

from . import (
    config,
    version as version_mod,
    package as package_mod,
    steam as steam_mod,
    notarize as notarize_mod,
    archive as archive_mod,
)
from .config import STEAM_APPS
from .paths import host_platform


def _add_common(sp, allow_no_bump=False):
    sp.add_argument("--platform", choices=["win", "mac"], default=host_platform(),
                    help="Target platform (defaults to the host).")
    sp.add_argument("--config", dest="build_config", default=None,
                    help="Build configuration (default from uetool.toml, e.g. Shipping).")
    sp.add_argument("--dry-run", action="store_true",
                    help="Print external commands instead of executing them.")
    if allow_no_bump:
        sp.add_argument("--no-bump", action="store_true",
                        help="Skip the version bump for this run.")
        sp.add_argument("--no-bootstrap", action="store_true",
                        help="Skip building the editor target even if it's missing.")
        sp.add_argument("--clean", action="store_true",
                        help="Wipe Binaries/Intermediate/Cooked/staged output first "
                             "(forces a from-scratch build + cook).")


def _add_custom_config(sp):
    sp.add_argument("--custom-config", dest="custom_config", default=None, metavar="NAME",
                    help="Apply the Config/Custom/NAME ini layer for this build, e.g. "
                         "--custom-config Arcware (pixel streaming) or --custom-config Demo "
                         "(Steam demo app). On release the layer name is tagged into the Steam "
                         "build description. Omit for a plain storefront build.")


def _add_app(sp):
    sp.add_argument("--app", choices=list(STEAM_APPS), default=None,
                    help="Which Steam app to upload to ([steam.<app>] in uetool.toml). "
                         "Required when more than one app is configured; otherwise the "
                         "single configured app is used.")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="uetool", description="Unreal Engine build & Steam release tool")
    parser.add_argument("-P", "--project", default=".", metavar="PATH",
                        help="Path to the UE project root (default: current directory).")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_common(sub.add_parser("bump", help="Increment build number and stamp ProjectVersion."))
    bootstrap_p = sub.add_parser(
        "bootstrap", help="Build the editor target for a fresh checkout (no cook/stage).")
    bootstrap_p.add_argument("--dry-run", action="store_true",
                             help="Print external commands instead of executing them.")
    package_p = sub.add_parser("package", help="Package the project via RunUAT.")
    _add_common(package_p, allow_no_bump=True)
    _add_custom_config(package_p)
    upload_p = sub.add_parser("upload", help="Upload the staged build to Steam.")
    _add_common(upload_p)
    _add_app(upload_p)
    archive_p = sub.add_parser(
        "archive", help="Zip the staged build for non-Steam distribution (e.g. pixel streaming).")
    archive_p.add_argument("--platform", choices=["win", "mac"], default=host_platform(),
                           help="Which staged build to zip (defaults to the host).")
    archive_p.add_argument("--dry-run", action="store_true",
                           help="Print what would happen instead of writing the zip.")
    _add_common(sub.add_parser("notarize", help="Sign + notarize + staple the staged macOS .app."))
    release_p = sub.add_parser("release", help="bump -> package -> [notarize on mac] -> upload.")
    _add_common(release_p, allow_no_bump=True)
    _add_custom_config(release_p)
    _add_app(release_p)

    args = parser.parse_args()

    project_root = Path(args.project).expanduser().resolve()
    if not project_root.is_dir():
        raise SystemExit(f"Project root not found: {project_root}")

    cfg = config.load(project_root)
    # bootstrap has no --config; other commands do (may be None -> fall back to toml).
    build_config = getattr(args, "build_config", None) or cfg.build_config

    if args.command == "bump":
        print(f"Version: {version_mod.bump(cfg)}")

    elif args.command == "bootstrap":
        if not package_mod.bootstrap(cfg, args.dry_run):
            print("Editor target already built; nothing to bootstrap.")

    elif args.command == "package":
        if not args.no_bump:
            print(f"Version: {version_mod.bump(cfg)}")
        package_mod.package(cfg, args.platform, build_config, args.dry_run,
                            bootstrap_if_needed=not args.no_bootstrap, clean=args.clean,
                            custom_config=args.custom_config)

    elif args.command == "upload":
        steam_mod.upload(cfg, args.platform, args.dry_run, app=args.app)

    elif args.command == "archive":
        archive_mod.archive(cfg, args.platform, args.dry_run)

    elif args.command == "notarize":
        notarize_mod.notarize(cfg, args.dry_run)

    elif args.command == "release":
        # A custom ini layer is allowed here — e.g. the Demo layer uploaded to the Demo
        # app. It leaves no trace in the staged output, so to keep the destination honest
        # the layer name is tagged into the Steam build description (see steam.upload).
        # Resolve the target app before spending an hour on a build, so a missing or
        # ambiguous --app fails up front rather than after packaging.
        config.select_app(cfg, args.app)
        if not args.no_bump:
            print(f"Version: {version_mod.bump(cfg)}")
        package_mod.package(cfg, args.platform, build_config, args.dry_run,
                            bootstrap_if_needed=not args.no_bootstrap, clean=args.clean,
                            custom_config=args.custom_config)
        # macOS builds must be signed + notarized before they leave the machine.
        if args.platform == "mac":
            notarize_mod.notarize(cfg, args.dry_run)
        steam_mod.upload(cfg, args.platform, args.dry_run, app=args.app,
                         custom_config=args.custom_config)

    return 0
