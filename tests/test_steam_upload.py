"""core.steam.upload renders the VDFs for the chosen app and calls steamcmd."""
import pytest

from core import config, steam


@pytest.fixture
def steam_project(project, monkeypatch):
    (project / "uetool.toml").write_text('''
[steam.main]
app_id = "4547240"
depot_win_id = "4547241"
depot_mac_id = "4547242"

[steam.playtest]
app_id = "4852730"
depot_win_id = "4852731"
''')
    (project / "uetool.local.toml").write_text('[steam]\nuser = "builder"\n')
    (project / ".version").write_text("v1.2.0.7\n")
    monkeypatch.setenv("UETOOL_STEAMCMD", "/sdk/steamcmd.sh")
    monkeypatch.delenv("UETOOL_STEAM_PASSWORD", raising=False)
    calls = []
    monkeypatch.setattr(steam, "run", lambda cmd, dry_run=False: calls.append([str(a) for a in cmd]))
    return project, calls


def test_upload_renders_per_app(steam_project):
    project, calls = steam_project
    cfg = config.load(project)
    steam.upload(cfg, "win", dry_run=True, app="playtest")
    gen = project / ".uetool" / "steam_build" / "playtest"
    app_vdf = (gen / "app_build.vdf").read_text()
    assert '"appid"\t"4852730"' in app_vdf and '"4852731"\t"depot.vdf"' in app_vdf and '"v1.2.0.7"' in app_vdf
    assert '"DepotID"\t"4852731"' in (gen / "depot.vdf").read_text()
    assert calls[-1] == ["/sdk/steamcmd.sh", "+login", "builder", "+run_app_build",
                         str((gen / "app_build.vdf").resolve()), "+quit"]

    steam.upload(cfg, "mac", dry_run=True, app="main")
    main_vdf = (project / ".uetool/steam_build/main/app_build.vdf").read_text()
    assert '"appid"\t"4547240"' in main_vdf and '"4547242"\t"depot.vdf"' in main_vdf
    assert '"appid"\t"4852730"' in app_vdf        # the playtest scripts were not overwritten


def test_upload_requires_choice_and_depot(steam_project):
    project, calls = steam_project
    cfg = config.load(project)
    with pytest.raises(SystemExit, match="--app"):
        steam.upload(cfg, "win", dry_run=True)
    with pytest.raises(SystemExit, match=r"depot_mac_id under \[steam\.playtest\]"):
        steam.upload(cfg, "mac", dry_run=True, app="playtest")
    assert calls == []


def test_upload_single_app_is_implicit(steam_project):
    project, calls = steam_project
    (project / "uetool.toml").write_text('[steam.demo]\napp_id = "5466760"\ndepot_win_id = "5466762"\n')
    steam.upload(config.load(project), "win", dry_run=True)
    assert '"appid"\t"5466760"' in (project / ".uetool/steam_build/demo/app_build.vdf").read_text()
    assert len(calls) == 1
