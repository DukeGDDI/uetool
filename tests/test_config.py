"""core.config: per-app Steam tables, legacy rejection, app selection."""
import pytest

from core import config


def write_toml(project, text):
    (project / "uetool.toml").write_text(text)


def test_apps_loaded_and_placeholders_skipped(project):
    write_toml(project, '''
[steam]
win_stage_subdir = "Win"

[steam.main]
app_id = "4547240"
depot_win_id = "4547241"
depot_mac_id = "4547242"

[steam.demo]
app_id = "0000000"      # placeholder: project has no demo
depot_win_id = "1"

[steam.playtest]
app_id = 4852730
depot_win_id = 4852731
''')
    cfg = config.load(project)
    assert list(cfg.steam_apps) == ["main", "playtest"]
    assert cfg.steam_apps["main"].depot_ids == {"win": "4547241", "mac": "4547242"}
    assert cfg.steam_apps["playtest"].app_id == "4852730"
    assert cfg.steam_apps["playtest"].depot_ids == {"win": "4852731", "mac": ""}
    assert cfg.stage_subdirs == {"win": "Win", "mac": "Mac"}


def test_no_apps(project):
    write_toml(project, "[project]\n")
    cfg = config.load(project)
    assert cfg.steam_apps == {}
    with pytest.raises(SystemExit, match="No Steam app configured"):
        config.select_app(cfg, None)


def test_legacy_layout_rejected(project):
    write_toml(project, '[steam]\napp_id = "4852730"\ndepot_win_id = "4852731"\n')
    with pytest.raises(SystemExit, match=r"\[steam\.main\]"):
        config.load(project)
    # ... in the local file too
    write_toml(project, "[steam.main]\napp_id = \"1\"\n")
    (project / "uetool.local.toml").write_text('[steam]\ndepot_mac_id = "2"\n')
    with pytest.raises(SystemExit, match="old single-app"):
        config.load(project)


def test_local_layer_overrides_per_key(project):
    write_toml(project, '[steam.main]\napp_id = "1"\ndepot_win_id = "2"\n')
    (project / "uetool.local.toml").write_text('[steam.main]\ndepot_win_id = "99"\n')
    cfg = config.load(project)
    assert cfg.steam_apps["main"].depot_ids["win"] == "99" and cfg.steam_apps["main"].app_id == "1"


def test_select_app(project):
    write_toml(project, '[steam.playtest]\napp_id = "7"\ndepot_win_id = "8"\n')
    cfg = config.load(project)
    assert config.select_app(cfg, None).name == "playtest"          # single app implied
    assert config.select_app(cfg, "playtest").app_id == "7"
    with pytest.raises(SystemExit, match="not configured"):
        config.select_app(cfg, "main")
    with pytest.raises(SystemExit, match="Unknown Steam app"):
        config.select_app(cfg, "beta")

    write_toml(project, '[steam.main]\napp_id = "1"\n[steam.playtest]\napp_id = "7"\n')
    cfg = config.load(project)
    with pytest.raises(SystemExit, match=r"--app \{main,playtest\}"):
        config.select_app(cfg, None)
    assert config.select_app(cfg, "main").app_id == "1"


def test_is_placeholder():
    assert config.is_placeholder("") and config.is_placeholder(" 0000001 ") and config.is_placeholder(None)
    assert not config.is_placeholder("4852730") and not config.is_placeholder(4852730)


def test_appstore_loaded(project):
    write_toml(project, '''
[appstore]
bundle_id = "com.d6scend"
app_identity = "Apple Distribution: X (T1)"
installer_identity = "3rd Party Mac Developer Installer: X (T1)"
provision_path = "/p/D6.provisionprofile"
asc_key_id = "K1"
asc_issuer_id = "iss"
''')
    a = config.load(project).appstore
    assert a and a.bundle_id == "com.d6scend" and a.asc_key_id == "K1"
    assert a.installer_identity.startswith("3rd Party") and a.team_id == ""  # no [apple] team set


def test_appstore_absent_is_none(project):
    write_toml(project, "[project]\n")
    assert config.load(project).appstore is None


def test_appstore_team_falls_back_to_apple(project):
    write_toml(project, '[appstore]\nbundle_id = "com.x"\napp_identity = "A"\n')
    (project / "uetool.local.toml").write_text('[apple]\nteam_id = "APPLETEAM"\n')
    assert config.load(project).appstore.team_id == "APPLETEAM"
