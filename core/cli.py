"""uetool — build & Steam release CLI for Unreal Engine projects.

Cross-platform orchestration around Unreal's RunUAT (packaging), Apple's
codesign/notarytool (macOS signing), and steamcmd (Steam upload). Runs against
the UE project at the current directory, or one given with -P/--project:

    uetool bump
    uetool package [--platform win|mac] [--config Shipping] [--no-bump]
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
    _add_common(sub.add_parser("package", help="Package the project via RunUAT."), allow_no_bump=True)
    _add_common(sub.add_parser("upload", help="Upload the staged build to Steam."))
    _add_common(sub.add_parser("notarize", help="Sign + notarize + staple the staged macOS .app."))
    _add_common(sub.add_parser("release", help="bump -> package -> [notarize on mac] -> upload."), allow_no_bump=True)

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
                            bootstrap_if_needed=not args.no_bootstrap)

    elif args.command == "upload":
        steam_mod.upload(cfg, args.platform, args.dry_run)

    elif args.command == "notarize":
        notarize_mod.notarize(cfg, args.dry_run)

    elif args.command == "release":
        if not args.no_bump:
            print(f"Version: {version_mod.bump(cfg)}")
        package_mod.package(cfg, args.platform, build_config, args.dry_run,
                            bootstrap_if_needed=not args.no_bootstrap)
        # macOS builds must be signed + notarized before they leave the machine.
        if args.platform == "mac":
            notarize_mod.notarize(cfg, args.dry_run)
        steam_mod.upload(cfg, args.platform, args.dry_run)

    return 0
