"""uetool — build & Steam release CLI for Unreal Engine projects.

Cross-platform orchestration around Unreal's RunUAT (packaging), Apple's
codesign/notarytool (macOS signing), and steamcmd (Steam upload). Runs against
the UE project at the current directory, or one given with -P/--project:

    uetool bump
    uetool package [--platform win|mac] [--config Shipping] [--no-bump]
                   [--custom-config Arcware]
    uetool upload
    uetool notarize
    uetool release                       # bump -> package -> [notarize on mac] -> upload
    uetool -P /path/to/Project release --platform mac

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
                    help="Apply the Config/Custom/NAME ini layer (RunUAT -CustomConfig). "
                         "Use for builds aimed at a different host, e.g. --custom-config "
                         "Arcware for pixel streaming. Omit for storefront builds.")


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
    _add_common(sub.add_parser("upload", help="Upload the staged build to Steam."))
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
        steam_mod.upload(cfg, args.platform, args.dry_run)

    elif args.command == "archive":
        archive_mod.archive(cfg, args.platform, args.dry_run)

    elif args.command == "notarize":
        notarize_mod.notarize(cfg, args.dry_run)

    elif args.command == "release":
        # release ends in a Steam upload. A custom ini layer exists to make a build for
        # somewhere that is NOT the storefront, so shipping one to a depot is almost
        # certainly a mistake — and a silent one, since the layer leaves no trace in the
        # staged output. Refuse rather than warn.
        if args.custom_config:
            raise SystemExit(
                f"--custom-config {args.custom_config} is not allowed with `release`, "
                "which uploads to Steam.\n"
                f"For a non-Steam build use:  uetool package --platform {args.platform} "
                f"--custom-config {args.custom_config}  &&  uetool archive --platform {args.platform}"
            )
        if not args.no_bump:
            print(f"Version: {version_mod.bump(cfg)}")
        package_mod.package(cfg, args.platform, build_config, args.dry_run,
                            bootstrap_if_needed=not args.no_bootstrap, clean=args.clean)
        # macOS builds must be signed + notarized before they leave the machine.
        if args.platform == "mac":
            notarize_mod.notarize(cfg, args.dry_run)
        steam_mod.upload(cfg, args.platform, args.dry_run)

    return 0
