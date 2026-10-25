"""Epic Games Store upload via BuildPatchTool (BPT).

Parallel to steam.py: it uploads the SAME staged build (`package` output) to an Epic
artifact. `release --store epic` on Mac still notarizes first — Epic distributes outside
the App Store, exactly like Steam. Upload registers the binary in the Dev sandbox; it is
NOT live until you assign the platform to the artifact in the Dev Portal (self-service),
which sets the Live label.
"""
import os

from . import stage
from . import version as ver
from .config import Config, EpicConfig
from .paths import run

SECRET_VAR = "UETOOL_EPIC_CLIENT_SECRET"
# How BPT / the Dev Portal names each platform (for the "assign platform" reminder).
_BPT_PLATFORM = {"win": "Windows", "mac": "Mac"}


def _require_epic(cfg: Config) -> EpicConfig:
    e = cfg.epic
    if e is None:
        raise SystemExit(
            "No [epic] target configured. Add org_id / product_id / artifact_id / client_id "
            "under [epic] in uetool.toml (ids are on the Epic Dev Portal)."
        )
    missing = [n for n, v in (("org_id", e.org_id), ("product_id", e.product_id),
                              ("artifact_id", e.artifact_id), ("client_id", e.client_id)) if not v]
    if missing:
        raise SystemExit(f"[epic] is missing {', '.join(missing)} in uetool.toml.")
    return e


def _read_version(cfg: Config) -> str:
    if cfg.version_file.exists():
        v = cfg.version_file.read_text(encoding="utf-8").strip()
        if v:
            return v
    raise SystemExit(f"No version recorded at {cfg.version_file}. Run 'bump' or 'package' first.")


def _app_launch(cfg: Config, target: str) -> str:
    """The executable to launch, relative to BuildRoot. Overridable per platform in
    [epic]; default derives from the project name. Mac is the inner Mach-O binary inside
    the .app (not the bundle), as BPT requires."""
    if explicit := cfg.epic.app_launch.get(target):
        return explicit
    name = cfg.uproject.stem
    return f"{name}.exe" if target == "win" else f"{name}.app/Contents/MacOS/{name}"


def upload(cfg: Config, target: str, dry_run: bool, custom_config: str | None = None) -> None:
    """Upload the staged `target` build to the project's Epic artifact via BPT."""
    epic = _require_epic(cfg)
    if not dry_run and not os.environ.get(SECRET_VAR):
        raise SystemExit(
            f"Set the BPT client secret before uploading:  export {SECRET_VAR}=…\n"
            "(the BPT Client Secret from the Dev Portal → Product Settings → BPT credentials tab)."
        )

    version = _read_version(cfg)
    # BPT BuildVersion must be UNIQUE PER PLATFORM (one string can't exist for both win
    # and mac) and whitespace-free, chars [A-Za-z0-9.+-_]. So platform-stamp it, and fold
    # any custom layer in with an underscore rather than Steam's "(Demo)" style.
    build_version = f"{version}-{target}" + (f"_{custom_config}" if custom_config else "")

    content_root = cfg.stage_dir / cfg.stage_subdirs[target]
    if not dry_run and not content_root.exists():
        raise SystemExit(f"Staged build not found at {content_root}. Run 'package' first.")
    if target == "mac":
        stage.normalize_mac_bundle(cfg, dry_run)

    # CloudDir is BPT's chunk cache; a fresh per-run dir keeps concurrent uploads safe.
    cloud = cfg.work_dir / "epic" / "cloud"
    if not dry_run:
        cloud.mkdir(parents=True, exist_ok=True)
    app_launch = _app_launch(cfg, target)

    # Forward slashes, no trailing slash: BPT's documented path rules (we also pass argv
    # as a list, so no shell quoting is involved).
    cmd = [
        epic.bpt, "-mode=UploadBinary",
        f"-OrganizationId={epic.org_id}",
        f"-ProductId={epic.product_id}",
        f"-ArtifactId={epic.artifact_id}",
        f"-ClientId={epic.client_id}",
        f"-ClientSecretEnvVar={SECRET_VAR}",
        f"-BuildRoot={content_root.resolve().as_posix()}",
        f"-CloudDir={cloud.resolve().as_posix()}",
        f"-BuildVersion={build_version}",
        f"-AppLaunch={app_launch}",
        "-AppArgs=",
    ]

    print(f"Uploading to Epic (artifact {epic.artifact_id}, build {build_version}, launch {app_launch})")
    run(cmd, dry_run)

    if not dry_run:
        bar = "=" * 72
        print(f"\n{bar}")
        print(f"Uploaded {build_version} to the Epic artifact {epic.artifact_id}.")
        print("This binary is NOT live yet. In the Dev Portal, open your product → Epic Games")
        print(f"Store → Artifacts and Binaries, attach it and assign the {_BPT_PLATFORM[target]} "
              "platform —")
        print("that sets the Live label. (https://dev.epicgames.com/portal)")
        print(bar)
