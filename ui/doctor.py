"""Setup Doctor: check that this machine + project can actually run uetool.

Pure logic, no Qt. Each check returns a CheckResult whose status is PASS, FIX (a
fixable gap, with an action attached), FAIL (broken, needs the user) or NA (doesn't
apply here). Every external fact (home dir, env, platform, keychain, engine search) is
injectable so the checks are unit-testable without touching the real machine.
"""
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core.paths import buildpatchtool_for_sdk, host_platform, runuat_path, steamcmd_for_sdk

from . import keychain, projectstate
from .configstore import (APPSTORE_KEYS, APPSTORE_REQUIRED, EPIC_IDS, EPIC_KEYS,
                          ProjectConfig, steam_field)

PASS, FIX, FAIL, NA = "pass", "fix", "fail", "na"


@dataclass(frozen=True)
class Action:
    kind: str       # set_field | open_config | pick_sdk | steam_login | restore_version
    label: str
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    key: str
    name: str
    status: str
    detail: str
    action: Action | None = None


def _ver_key(p: Path):
    return tuple(int(n) for n in re.findall(r"\d+", p.name)) or (0,)


def find_engines(host: str | None = None) -> list[Path]:
    """Launcher-installed engines (…/Epic Games/UE_*), newest first."""
    host = host or host_platform()
    roots = ([Path("/Users/Shared/Epic Games")] if host == "mac"
             else [Path("C:/Program Files/Epic Games")] if host == "win" else [])
    found = [p for r in roots if r.is_dir() for p in r.glob("UE_*") if p.is_dir()]
    return sorted(found, key=_ver_key, reverse=True)


def steam_config_vdf(host: str, home: Path, steamcmd: Path | None) -> Path | None:
    if host == "mac":
        return home / "Library/Application Support/Steam/config/config.vdf"
    if host == "win":
        return steamcmd.parent / "config" / "config.vdf" if steamcmd else None
    return home / ".steam/steam/config/config.vdf"


def account_cached(vdf_text: str, user: str) -> bool:
    """True if config.vdf lists `user` as a logged-in account ("name" { … })."""
    return re.search(r'"' + re.escape(user) + r'"\s*\{', vdf_text, re.I) is not None


def steamcmd_path(sdk: str) -> tuple[str, bool]:
    """(resolved command, found) the same way core.config resolves it."""
    resolved = steamcmd_for_sdk(Path(sdk)) if sdk else "steamcmd"
    found = Path(resolved).is_file() if os.path.isabs(resolved) else shutil.which(resolved) is not None
    return resolved, found


def buildpatchtool_path(sdk: str) -> tuple[str, bool]:
    """(resolved BuildPatchTool, found), the same way core.config resolves it."""
    resolved = buildpatchtool_for_sdk(Path(sdk)) if sdk else "BuildPatchTool"
    found = Path(resolved).is_file() if os.path.isabs(resolved) else shutil.which(resolved) is not None
    return resolved, found


def export_lines(steam_sdk: str, host: str | None = None, epic_sdk: str = "") -> str:
    """Copy-paste shell lines that make the CLI behave like the UI does."""
    host = host or host_platform()
    lines = []
    for var, val in (("UETOOL_STEAM_SDK", steam_sdk), ("UETOOL_EPIC_SDK", epic_sdk)):
        if val:
            lines.append(f'setx {var} "{val}"' if host == "win" else f'export {var}="{val}"')
    return "\n".join(lines)


def run_checks(project: Path | str, cfg: ProjectConfig, steam_sdk: str = "", *,
               epic_sdk: str = "", host: str | None = None, home: Path | None = None, environ=None,
               py_version: tuple | None = None, engines=None, has_secret=None) -> list[CheckResult]:
    project = Path(project)
    host = host or host_platform()
    home = home or Path.home()
    environ = os.environ if environ is None else environ
    py_version = py_version or sys.version_info[:3]
    engines = find_engines(host) if engines is None else engines
    has_secret = has_secret or keychain.has
    out: list[CheckResult] = []

    def add(key, name, status, detail, action=None):
        out.append(CheckResult(key, name, status, detail, action))

    # 1. Python
    ver = ".".join(map(str, py_version[:3]))
    if tuple(py_version[:2]) >= (3, 11):
        add("python", "Python 3.11+", PASS, f"Running {ver} ({sys.executable})")
    else:
        add("python", "Python 3.11+", FAIL, f"Running {ver}; uetool needs 3.11+ (tomllib). "
            "Start the UI with a newer interpreter.")

    # 2. .uproject
    ups = sorted(project.glob("*.uproject"))
    if len(ups) == 1:
        add("uproject", "Single .uproject", PASS, ups[0].name)
    elif not ups:
        add("uproject", "Single .uproject", FAIL, f"No .uproject in {project}. Pick the project root.")
    else:
        add("uproject", "Single .uproject", FAIL,
            f"{len(ups)} found ({', '.join(u.name for u in ups)}). Pin one with "
            "[project] name in uetool.toml, or pick a different folder.")

    # 3. Unreal Engine root
    ue = environ.get("UETOOL_UE_ROOT") or cfg.get("ue_root")
    runuat = runuat_path(Path(ue).expanduser()) if ue else None
    if runuat and runuat.is_file():
        add("ue_root", "Unreal Engine root", PASS, f"{ue} (RunUAT found)")
    else:
        why = f"{ue} has no RunUAT." if ue else "Not set."
        if engines:
            best = engines[0]
            add("ue_root", "Unreal Engine root", FIX, f"{why} Detected {best.name} in {best.parent}.",
                Action("set_field", f"Use {best.name}", {"field": "ue_root", "value": str(best)}))
        else:
            add("ue_root", "Unreal Engine root", FAIL,
                f"{why} No Epic Games/UE_* install found; set it on the Config tab.",
                Action("open_config", "Open Config"))

    # 4. steamcmd
    sdk = steam_sdk or environ.get("UETOOL_STEAM_SDK", "")
    cmd, found = steamcmd_path(sdk)
    if found:
        add("steamcmd", "steamcmd", PASS, cmd if os.path.isabs(cmd) else f"{cmd} (on PATH)")
    else:
        why = (f"Nothing usable under {sdk}." if sdk else
               "UETOOL_STEAM_SDK is not set and steamcmd isn't on PATH.")
        add("steamcmd", "steamcmd", FAIL, why, Action("pick_sdk", "Locate…"))

    # 5. Steam user
    user = cfg.get("steam_user") or environ.get("UETOOL_STEAM_USER", "")
    if user:
        pw = "password in keychain" if has_secret("steam", user) else "no password saved (cached login is enough)"
        add("steam_user", "Steam user", PASS, f"{user}, {pw}")
    else:
        add("steam_user", "Steam user", FIX, "Set the dedicated build account name on the Config tab.",
            Action("open_config", "Open Config"))

    # 6. Steam login cached
    if not user or not found:
        add("steam_login", "Steam login cached", NA,
            "Needs a Steam user and a working steamcmd first.")
    else:
        vdf = steam_config_vdf(host, home, Path(cmd) if os.path.isabs(cmd) else None)
        cached = False
        if vdf and vdf.is_file():
            try:
                cached = account_cached(vdf.read_text(encoding="utf-8", errors="replace"), user)
            except OSError:
                pass
        if cached:
            add("steam_login", "Steam login cached", PASS, f"{user} is cached in {vdf.name}")
        else:
            add("steam_login", "Steam login cached", FIX,
                f"No cached login for {user}. Run the one-time interactive login "
                "(password + Steam Guard) so uploads don't prompt.",
                Action("steam_login", "Open login terminal", {"command": [cmd, "+login", user]}))

    # 7. Steam apps (main / demo / playtest; any subset, each needs the host's depot)
    host_depot = "depot_win_id" if host == "win" else "depot_mac_id"
    apps = cfg.configured_apps()
    if cfg.legacy_steam_keys():
        add("steam_ids", "Steam apps", FAIL,
            "uetool.toml still uses the old flat [steam] app_id layout, which the CLI refuses. "
            "Move the ids into [steam.main] / [steam.demo] / [steam.playtest].",
            Action("open_config", "Open Config"))
    elif not apps:
        add("steam_ids", "Steam apps", FIX,
            "No Steam app configured: set the app id for main, demo or playtest.",
            Action("open_config", "Open Config"))
    else:
        miss = [a for a in apps if cfg.is_unset(steam_field(a, host_depot))]
        if miss:
            add("steam_ids", "Steam apps", FIX,
                f"{host_depot} still unset or a 0000… placeholder for: {', '.join(miss)}.",
                Action("open_config", "Open Config"))
        else:
            add("steam_ids", "Steam apps", PASS,
                ", ".join(f"{a} {cfg.get(steam_field(a, 'app_id'))}" for a in apps))

    # 8. Apple (macOS only)
    if host != "mac":
        add("apple", "Apple notarization", NA, "Only needed when building for macOS.")
    else:
        need = {"apple_id": "Apple ID", "team_id": "Team ID", "signing_identity": "Signing identity"}
        miss = [lab for n, lab in need.items() if cfg.is_unset(n) and not environ.get("UETOOL_" + n.upper())]
        apple_id = cfg.get("apple_id") or environ.get("UETOOL_APPLE_ID", "")
        has_pw = bool(environ.get("UETOOL_APPLE_APP_PASSWORD")) or (apple_id and has_secret("apple", apple_id))
        if not has_pw:
            miss.append("app-specific password")
        if miss:
            add("apple", "Apple notarization", FIX, f"Missing: {', '.join(miss)}.",
                Action("open_config", "Open Config"))
        else:
            add("apple", "Apple notarization", PASS, f"{apple_id}, password in keychain")

    # 9. Epic Games Store (optional — only when the project declares an [epic] target)
    epic_vals = {name: cfg.get(name).strip() for name in EPIC_IDS}
    set_n = sum(bool(v) for v in epic_vals.values())
    if set_n == 0:
        add("epic", "Epic Games Store", NA, "No [epic] target configured (optional).")
    elif set_n < len(EPIC_IDS):
        miss = [EPIC_KEYS[name] for name, v in epic_vals.items() if not v]
        add("epic", "Epic Games Store", FIX, f"Incomplete [epic]: missing {', '.join(miss)}.",
            Action("open_config", "Open Config"))
    else:
        bpt, bpt_found = buildpatchtool_path(epic_sdk or environ.get("UETOOL_EPIC_SDK", ""))
        has_bpt_secret = (bool(environ.get("UETOOL_EPIC_CLIENT_SECRET"))
                          or has_secret("epic", epic_vals["epic_client_id"]))
        gaps = []
        if not bpt_found:
            gaps.append("BuildPatchTool not found")
        if not has_bpt_secret:
            gaps.append("BPT client secret not set")
        if gaps:
            add("epic", "Epic Games Store", FIX,
                "; ".join(gaps) + " (UETOOL_EPIC_SDK / UETOOL_EPIC_CLIENT_SECRET, or the UI fields).",
                Action("pick_epic_sdk", "Locate BPT…") if not bpt_found else Action("open_config", "Open Config"))
        else:
            where = bpt if os.path.isabs(bpt) else f"{bpt} (on PATH)"
            add("epic", "Epic Games Store", PASS,
                f"artifact {epic_vals['epic_artifact_id']}; BPT {where}; secret set")

    # 10. Mac App Store (optional — macOS only, only when [appstore] is declared)
    mas_vals = {name: cfg.get(name).strip() for name in APPSTORE_REQUIRED}
    mas_set = sum(bool(v) for v in mas_vals.values())
    if host != "mac":
        add("appstore", "Mac App Store", NA, "Only on macOS." if mas_set
            else "No [appstore] target configured (optional; macOS only).")
    elif mas_set == 0:
        add("appstore", "Mac App Store", NA, "No [appstore] target configured (optional).")
    elif mas_set < len(APPSTORE_REQUIRED):
        miss = [APPSTORE_KEYS[name] for name, v in mas_vals.items() if not v]
        add("appstore", "Mac App Store", FIX, f"Incomplete [appstore]: missing {', '.join(miss)}.",
            Action("open_config", "Open Config"))
    else:
        gaps = []
        prof = cfg.get("appstore_provision_path").strip()
        if prof and not Path(prof).expanduser().is_file():
            gaps.append("provisioning profile not found")
        ent = cfg.get("appstore_entitlements_path").strip()
        if ent and not Path(ent).expanduser().is_file():
            gaps.append("entitlements plist not found")
        key_id = cfg.get("appstore_asc_key_id").strip()
        key_path = cfg.get("appstore_api_key_path").strip() or environ.get("UETOOL_ASC_API_KEY_PATH", "")
        key_dirs = [home / ".appstoreconnect/private_keys", home / ".private_keys", home / "private_keys"]
        found_key = (any((kd / f"AuthKey_{key_id}.p8").is_file() for kd in key_dirs)
                     or (bool(key_path) and Path(key_path).expanduser().is_file()))
        if not found_key:
            gaps.append(f"AuthKey_{key_id}.p8 not found in ~/.appstoreconnect/private_keys")
        if gaps:
            add("appstore", "Mac App Store", FIX, "; ".join(gaps) + ".",
                Action("open_config", "Open Config"))
        else:
            add("appstore", "Mac App Store", PASS,
                f"{cfg.get('appstore_bundle_id')}; profile + API key present")

    # 11. Stamped DefaultGame.ini / leftover overlay
    stamped = projectstate.stamped_version(project)
    overlaid = projectstate.overlaid_files(project)
    if stamped:
        add("stamped", "DefaultGame.ini clean", FAIL,
            f"ProjectVersion is {stamped}: a build was interrupted before the version "
            "was restored. Commit nothing until it's back to the 3-part version.",
            Action("restore_version", "Restore"))
    elif overlaid:
        add("stamped", "DefaultGame.ini clean", FAIL,
            "A --custom-config merge was left in " + ", ".join(p.name for p in overlaid)
            + ". Revert with `git checkout` on those files.")
    else:
        v = projectstate.project_version(project)
        add("stamped", "DefaultGame.ini clean", PASS if v else FIX,
            f"ProjectVersion {v}" if v else "No ProjectVersion=vX.Y.Z line found in Config/DefaultGame.ini.")
    return out


def summary(results: list[CheckResult]) -> str:
    """'ready' when nothing needs attention, else 'needs setup'."""
    return "ready" if all(r.status in (PASS, NA) for r in results) else "needs setup"
