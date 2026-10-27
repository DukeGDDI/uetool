"""Configuration loading.

Three layers, so nothing secret or machine-specific is committed:
  1. <project>/uetool.toml         (committed, non-secret: Steam app + depot ids)
  2. <project>/uetool.local.toml   (untracked, per-machine: ue_root, steam user, apple ids)
  3. environment variables         (override both; for CI)

Steam apps live in per-app tables, any subset of which may be present:
  [steam.main]      the store app
  [steam.demo]      the demo app
  [steam.playtest]  the playtest app
each holding app_id, depot_win_id and (optionally) depot_mac_id. The old flat
[steam] app_id / depot_*_id layout is rejected with a migration hint.

An optional [epic] table adds an Epic Games Store target (one artifact, uploaded via
BuildPatchTool): org_id, product_id, artifact_id, client_id (non-secret ids). The BPT
client secret is env-only (UETOOL_EPIC_CLIENT_SECRET); BuildPatchTool is resolved from
UETOOL_EPIC_BPT or the UETOOL_EPIC_SDK folder.

An optional [appstore] table adds a Mac App Store target (macOS-only): bundle_id,
app_identity / installer_identity (signing certs), provision_path, entitlements_path,
asc_key_id / asc_issuer_id (App Store Connect API key ids). All non-secret; the API
key .p8 is read by altool from ~/.appstoreconnect/private_keys, never stored here.
ASC ids / key path can be overridden with UETOOL_ASC_KEY_ID / UETOOL_ASC_ISSUER_ID /
UETOOL_ASC_API_KEY_PATH.

Machine-WIDE settings are environment variables, not in any toml, because they
are shared across every project on the machine:
  UETOOL_PYTHON       interpreter for the launcher (handled by the launcher itself)
  UETOOL_STEAM_SDK    folder containing steamcmd; the exact binary is derived per-OS
Secrets are env-only and never written to a file:
  UETOOL_STEAM_PASSWORD, UETOOL_APPLE_APP_PASSWORD
Per-machine overrides (optional, otherwise read from uetool.local.toml):
  UETOOL_UE_ROOT, UETOOL_STEAM_USER, UETOOL_APPLE_ID, UETOOL_APPLE_TEAM_ID,
  UETOOL_APPLE_SIGNING_IDENTITY, UETOOL_STEAMCMD
"""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .paths import buildpatchtool_for_sdk, steamcmd_for_sdk

# The Steam apps a project may declare, in display order. Each is a [steam.<name>] table.
STEAM_APPS = ("main", "demo", "playtest")

# Keys of the pre-multi-app layout; their presence directly under [steam] is an error.
LEGACY_STEAM_KEYS = ("app_id", "depot_win_id", "depot_mac_id")

MIGRATION_HINT = (
    "uetool.toml uses the old single-app [steam] layout. Move the ids into a per-app "
    "table (any of main / demo / playtest may be omitted):\n"
    "\n"
    "  [steam]\n"
    "  win_stage_subdir = \"Windows\"\n"
    "  mac_stage_subdir = \"Mac\"\n"
    "\n"
    "  [steam.main]\n"
    "  app_id = \"...\"\n"
    "  depot_win_id = \"...\"\n"
    "  depot_mac_id = \"...\"\n"
    "\n"
    "  [steam.playtest]\n"
    "  app_id = \"...\"\n"
    "  depot_win_id = \"...\"\n"
)


def is_placeholder(value) -> bool:
    """Steam ids that are empty or still the template's 0000… count as unset."""
    v = str(value if value is not None else "").strip()
    return v == "" or v.startswith("0000")


@dataclass(frozen=True)
class SteamApp:
    name: str                      # "main" | "demo" | "playtest"
    app_id: str
    depot_ids: dict[str, str]      # platform -> depot id, e.g. {"win": "...", "mac": "..."}


@dataclass(frozen=True)
class EpicConfig:
    """Epic Games Store target (one artifact), uploaded via BuildPatchTool."""
    org_id: str
    product_id: str
    artifact_id: str
    client_id: str                 # the BPT Client ID (not an EOS/SDK client)
    app_launch: dict[str, str]     # platform -> exe relative to BuildRoot ("" = derive from name)
    bpt: str                       # resolved BuildPatchTool path or "BuildPatchTool" on PATH
    client_secret: str | None      # env only (UETOOL_EPIC_CLIENT_SECRET), never a file


@dataclass(frozen=True)
class AppStoreConfig:
    """Mac App Store target: sign (Apple Distribution) → productbuild → altool upload.
    All fields are non-secret. The App Store Connect API key (.p8) is NOT here — altool
    reads it from ~/.appstoreconnect/private_keys by filename convention; only the key id
    and issuer id (both non-secret) are passed on the command line."""
    bundle_id: str                 # com.d6scend
    app_sku: str                   # App Store Connect SKU (free-form), optional
    app_apple_id: str              # numeric App Store app id (adamId), optional
    team_id: str                   # Apple team id (defaults to [apple] team_id)
    app_identity: str              # "Apple Distribution: Name (TEAMID)"
    installer_identity: str        # "3rd Party Mac Developer Installer: Name (TEAMID)"
    provision_path: str            # path to the .provisionprofile (non-secret)
    entitlements_path: str         # path to the MAS entitlements plist ("" = generate one)
    asc_key_id: str                # App Store Connect API key id (non-secret)
    asc_issuer_id: str             # ASC issuer id (non-secret)
    api_key_path: str | None       # optional path to the .p8 (NOT its contents)


@dataclass
class Config:
    project_root: Path
    uproject: Path
    ini_path: Path
    counter_file: Path             # <project>/.build_number (tracked)
    version_file: Path             # <project>/.version (generated)
    work_dir: Path                 # <project>/.uetool (generated working files)
    ue_root: Path | None
    stage_dir: Path                # UE's -stage output root (Saved/StagedBuilds)
    build_config: str
    steam_apps: dict[str, SteamApp]  # only the configured apps, keyed by name
    epic: "EpicConfig | None"      # the [epic] target, or None when not configured
    appstore: "AppStoreConfig | None"  # the [appstore] target, or None when not configured
    stage_subdirs: dict[str, str]  # platform -> staged subfolder, e.g. {"win": "Windows"}
    steam_user: str
    steam_password: str | None
    steamcmd: str
    apple_id: str
    apple_team_id: str
    apple_signing_identity: str
    apple_password: str | None     # app-specific password; env only, never a file


def _load_toml(path: Path) -> dict:
    if path.is_file():
        with path.open("rb") as fh:
            return tomllib.load(fh)
    return {}


def _find_uproject(root: Path, name_override: str | None) -> Path:
    """The project's .uproject. Auto-detected from the single *.uproject in root,
    unless [project] name pins a specific one."""
    if name_override:
        return root / f"{name_override}.uproject"
    uprojects = sorted(root.glob("*.uproject"))
    if len(uprojects) == 1:
        return uprojects[0]
    raise SystemExit(
        f"Expected exactly one .uproject in {root}, found {len(uprojects)}. "
        "Set [project] name in uetool.toml to pick one, or pass the right -P path."
    )


def has_legacy_steam_keys(steam_section: dict) -> bool:
    return any(k in steam_section for k in LEGACY_STEAM_KEYS)


def _load_steam_apps(base: dict, local: dict) -> dict[str, SteamApp]:
    """Read [steam.<name>] from both files (local wins per key). Tables whose app_id
    is empty or a 0000… placeholder are treated as 'this project has no such app'."""
    for layer in (base, local):
        if has_legacy_steam_keys(layer.get("steam", {})):
            raise SystemExit(MIGRATION_HINT)
    apps: dict[str, SteamApp] = {}
    for name in STEAM_APPS:
        b = base.get("steam", {}).get(name, {})
        l = local.get("steam", {}).get(name, {})
        if not isinstance(b, dict) or not isinstance(l, dict):
            raise SystemExit(f"[steam.{name}] must be a table of app_id / depot ids.")
        merged = {**b, **l}
        app_id = str(merged.get("app_id", "")).strip()
        if is_placeholder(app_id):
            continue
        apps[name] = SteamApp(
            name=name,
            app_id=app_id,
            depot_ids={
                "win": str(merged.get("depot_win_id", "")).strip(),
                "mac": str(merged.get("depot_mac_id", "")).strip(),
            },
        )
    return apps


def select_app(cfg: Config, name: str | None) -> SteamApp:
    """The Steam app an upload goes to. An explicit name must be configured; with no
    name, the single configured app is used, and several configured apps require a
    choice (so a store upload is never accidental)."""
    apps = cfg.steam_apps
    if not apps:
        raise SystemExit(
            "No Steam app configured. Add a [steam.main] (or demo / playtest) table with "
            "app_id and depot ids to uetool.toml."
        )
    if name is not None:
        if name not in STEAM_APPS:
            raise SystemExit(f"Unknown Steam app '{name}'. Choose one of: {', '.join(STEAM_APPS)}.")
        if name not in apps:
            raise SystemExit(
                f"Steam app '{name}' is not configured in uetool.toml "
                f"(configured: {', '.join(apps)})."
            )
        return apps[name]
    if len(apps) == 1:
        return next(iter(apps.values()))
    raise SystemExit(
        "Several Steam apps are configured; pick one with --app "
        f"{{{','.join(apps)}}}."
    )


def _load_epic(base: dict, local: dict) -> "EpicConfig | None":
    """Read the [epic] table (local wins per key). None when nothing is configured.
    org/product/artifact/client_id are non-secret ids; the secret is env-only."""
    b, l = base.get("epic", {}), local.get("epic", {})
    if not isinstance(b, dict) or not isinstance(l, dict):
        raise SystemExit("[epic] must be a table (org_id, product_id, artifact_id, client_id).")
    m = {**b, **l}
    org = str(m.get("org_id", "")).strip()
    product = str(m.get("product_id", "")).strip()
    artifact = str(m.get("artifact_id", "")).strip()
    client = str(m.get("client_id", "")).strip()
    if not any((org, product, artifact, client)):
        return None  # no [epic] section, or all blank -> this project has no Epic target

    # BuildPatchTool: explicit path > derived from the machine-wide SDK folder >
    # toml value > "BuildPatchTool" on PATH.
    bpt = os.environ.get("UETOOL_EPIC_BPT")
    if not bpt:
        sdk = os.environ.get("UETOOL_EPIC_SDK")
        bpt = buildpatchtool_for_sdk(Path(sdk)) if sdk else str(m.get("buildpatchtool", "BuildPatchTool"))

    return EpicConfig(
        org_id=org, product_id=product, artifact_id=artifact, client_id=client,
        app_launch={"win": str(m.get("app_launch_win", "")).strip(),
                    "mac": str(m.get("app_launch_mac", "")).strip()},
        bpt=bpt,
        client_secret=os.environ.get("UETOOL_EPIC_CLIENT_SECRET"),  # never from a file
    )


def _load_appstore(base: dict, local: dict, apple_team_id: str) -> "AppStoreConfig | None":
    """Read the [appstore] table (local wins per key). None when nothing is configured.
    All ids/paths are non-secret; the .p8 is a file altool reads (never stored here).
    team_id falls back to [apple] team_id; env overrides the ASC ids / key path."""
    b, l = base.get("appstore", {}), local.get("appstore", {})
    if not isinstance(b, dict) or not isinstance(l, dict):
        raise SystemExit("[appstore] must be a table (bundle_id, app_identity, …).")
    m = {**b, **l}

    def s(key: str) -> str:
        return str(m.get(key, "")).strip()

    core_ids = (s("bundle_id"), s("app_identity"), s("installer_identity"),
                s("provision_path"), s("asc_key_id"), s("asc_issuer_id"))
    if not any(core_ids):
        return None  # no [appstore] section, or all blank -> this project has no MAS target

    key_path = os.environ.get("UETOOL_ASC_API_KEY_PATH") or s("api_key_path")
    return AppStoreConfig(
        bundle_id=s("bundle_id"),
        app_sku=s("app_sku"),
        app_apple_id=s("app_apple_id"),
        team_id=s("team_id") or apple_team_id,
        app_identity=s("app_identity"),
        installer_identity=s("installer_identity"),
        provision_path=s("provision_path"),
        entitlements_path=s("entitlements_path"),
        asc_key_id=os.environ.get("UETOOL_ASC_KEY_ID") or s("asc_key_id"),
        asc_issuer_id=os.environ.get("UETOOL_ASC_ISSUER_ID") or s("asc_issuer_id"),
        api_key_path=key_path or None,
    )


def load(project_root: Path) -> Config:
    root = Path(project_root).expanduser().resolve()
    base = _load_toml(root / "uetool.toml")
    local = _load_toml(root / "uetool.local.toml")

    def get(section: str, key: str, default=None):
        return local.get(section, {}).get(key, base.get(section, {}).get(key, default))

    uproject = _find_uproject(root, get("project", "name"))
    stage_rel = get("project", "stage_dir", "Saved/StagedBuilds")
    build_config = get("project", "build_config", "Shipping")

    ue_root_str = os.environ.get("UETOOL_UE_ROOT") or get("engine", "ue_root")
    ue_root = Path(ue_root_str).expanduser() if ue_root_str else None

    steam_user = os.environ.get("UETOOL_STEAM_USER") or get("steam", "user", "")
    steam_password = os.environ.get("UETOOL_STEAM_PASSWORD")  # never from a file

    # steamcmd: explicit override > derived from the machine-wide SDK folder >
    # toml value > "steamcmd" on PATH.
    steamcmd = os.environ.get("UETOOL_STEAMCMD")
    if not steamcmd:
        sdk = os.environ.get("UETOOL_STEAM_SDK")
        steamcmd = steamcmd_for_sdk(Path(sdk)) if sdk else get("steam", "steamcmd", "steamcmd")

    # Apple notarization. Identifiers may come from env (CI) or the [apple] section;
    # the app-specific password is read only from the environment, like Steam's.
    apple_id = os.environ.get("UETOOL_APPLE_ID") or get("apple", "apple_id", "")
    apple_team_id = os.environ.get("UETOOL_APPLE_TEAM_ID") or get("apple", "team_id", "")
    apple_signing_identity = (
        os.environ.get("UETOOL_APPLE_SIGNING_IDENTITY") or get("apple", "signing_identity", "")
    )
    apple_password = os.environ.get("UETOOL_APPLE_APP_PASSWORD")  # never from a file

    stage_subdirs = {
        "win": get("steam", "win_stage_subdir", "Windows"),
        "mac": get("steam", "mac_stage_subdir", "Mac"),
    }

    return Config(
        project_root=root,
        uproject=uproject,
        ini_path=root / "Config" / "DefaultGame.ini",
        counter_file=root / ".build_number",
        version_file=root / ".version",
        work_dir=root / ".uetool",
        ue_root=ue_root,
        stage_dir=(root / stage_rel),
        build_config=build_config,
        steam_apps=_load_steam_apps(base, local),
        epic=_load_epic(base, local),
        appstore=_load_appstore(base, local, apple_team_id),
        stage_subdirs=stage_subdirs,
        steam_user=steam_user,
        steam_password=steam_password,
        steamcmd=steamcmd,
        apple_id=apple_id,
        apple_team_id=apple_team_id,
        apple_signing_identity=apple_signing_identity,
        apple_password=apple_password,
    )
