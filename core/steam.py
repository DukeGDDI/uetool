"""Steam upload via steamcmd + ContentBuilder VDF scripts."""
from pathlib import Path

from .config import Config
from .paths import run

_TEMPLATE_DIR = Path(__file__).resolve().parent / "steam"


def _render(text: str, repl: dict[str, str]) -> str:
    for token, value in repl.items():
        text = text.replace(token, value)
    return text


def _read_version(cfg: Config) -> str:
    if cfg.version_file.exists():
        v = cfg.version_file.read_text(encoding="utf-8").strip()
        if v:
            return v
    raise SystemExit(
        f"No version recorded at {cfg.version_file}. Run 'bump' or 'package' first."
    )


def upload(cfg: Config, target: str, dry_run: bool) -> None:
    if not cfg.app_id or cfg.app_id.startswith("0000"):
        raise SystemExit("Set [steam] app_id in uetool.toml before uploading.")
    if not cfg.steam_user:
        raise SystemExit(
            "Steam user not set. Add [steam] user to uetool.local.toml "
            "or set UETOOL_STEAM_USER."
        )

    depot_id = cfg.depot_ids.get(target, "")
    if not depot_id or depot_id.startswith("0000"):
        raise SystemExit(f"Set the Steam depot id for platform '{target}' in uetool.toml.")

    version = _read_version(cfg)
    content_root = cfg.stage_dir / cfg.stage_subdirs[target]
    if not dry_run and not content_root.exists():
        raise SystemExit(
            f"Staged build not found at {content_root}. Run 'package' first."
        )

    gen = cfg.work_dir / "steam_build"
    gen.mkdir(parents=True, exist_ok=True)
    build_output = gen / "output"
    build_output.mkdir(parents=True, exist_ok=True)

    repl = {
        "@APP_ID@": cfg.app_id,
        "@DEPOT_ID@": depot_id,
        "@DESC@": version,
        # Forward slashes: ContentBuilder accepts them on every OS and avoids
        # backslash-escaping headaches inside VDF.
        "@CONTENT_ROOT@": content_root.resolve().as_posix(),
        "@BUILD_OUTPUT@": build_output.resolve().as_posix(),
        "@DEPOT_VDF@": "depot.vdf",
    }

    app_tpl = (_TEMPLATE_DIR / "app_build.vdf.tmpl").read_text(encoding="utf-8")
    depot_tpl = (_TEMPLATE_DIR / "depot.vdf.tmpl").read_text(encoding="utf-8")

    app_vdf = gen / "app_build.vdf"
    depot_vdf = gen / "depot.vdf"
    app_vdf.write_text(_render(app_tpl, repl), encoding="utf-8")
    depot_vdf.write_text(_render(depot_tpl, repl), encoding="utf-8")

    print(f"Rendered Steam scripts in {gen} (app {cfg.app_id}, depot {depot_id}, {version})")

    login = ["+login", cfg.steam_user]
    if cfg.steam_password:
        login.append(cfg.steam_password)

    cmd = [cfg.steamcmd, *login, "+run_app_build", str(app_vdf.resolve()), "+quit"]
    run(cmd, dry_run)
