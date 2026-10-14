import os
from pathlib import Path

from ui import doctor as d
from ui.configstore import LOCAL, ProjectConfig


def run(project, sdk="", host="mac", home=None, environ=None, engines=(), secrets_=(), py=(3, 13, 1)):
    cfg = ProjectConfig(project)
    return {r.key: r for r in d.run_checks(
        project, cfg, sdk, host=host, home=home or project / "home", environ=environ or {},
        py_version=py, engines=list(engines), has_secret=lambda k, a: (k, a) in secrets_)}


def make_engine(root: Path) -> Path:
    from core.paths import runuat_path
    p = runuat_path(root)
    p.parent.mkdir(parents=True)
    p.write_text("")
    return root


def make_sdk(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / ("steamcmd.exe" if os.name == "nt" else "steamcmd.sh")).write_text("")
    return root


def test_python_version(project):
    assert run(project)["python"].status == d.PASS
    assert run(project, py=(3, 10, 0))["python"].status == d.FAIL


def test_uproject(project):
    assert run(project)["uproject"].status == d.PASS
    (project / "Other.uproject").write_text("{}")
    assert run(project)["uproject"].status == d.FAIL
    for u in project.glob("*.uproject"):
        u.unlink()
    assert run(project)["uproject"].status == d.FAIL


def test_ue_root_states(project, tmp_path):
    eng = tmp_path / "Epic/UE_5.7"
    r = run(project, engines=[eng])["ue_root"]
    assert r.status == d.FIX and r.action.kind == "set_field" and r.action.data["value"] == str(eng)
    assert run(project)["ue_root"].status == d.FAIL
    make_engine(eng)
    (project / LOCAL).write_text(f'[engine]\nue_root = "{eng}"\n')
    assert run(project)["ue_root"].status == d.PASS
    (project / LOCAL).write_text('[engine]\nue_root = "/nope"\n')
    assert run(project)["ue_root"].status == d.FAIL
    assert run(project, engines=[eng])["ue_root"].status == d.FIX


def test_find_engines_sorted(tmp_path, monkeypatch):
    root = tmp_path / "Epic Games"
    for n in ("UE_5.4", "UE_5.10", "UE_5.7"):
        (root / n).mkdir(parents=True)
    monkeypatch.setattr(d, "Path", lambda *a: root if a == ("/Users/Shared/Epic Games",) else Path(*a))
    assert [p.name for p in d.find_engines("mac")] == ["UE_5.10", "UE_5.7", "UE_5.4"]


def test_steamcmd(project, tmp_path, monkeypatch):
    monkeypatch.setattr(d.shutil, "which", lambda c: None)
    r = run(project)["steamcmd"]
    assert r.status == d.FAIL and r.action.kind == "pick_sdk"
    assert run(project, sdk=str(tmp_path / "empty"))["steamcmd"].status == d.FAIL
    sdk = make_sdk(tmp_path / "sdk")
    assert run(project, sdk=str(sdk))["steamcmd"].status == d.PASS
    assert run(project, environ={"UETOOL_STEAM_SDK": str(sdk)})["steamcmd"].status == d.PASS


def test_steam_login_cached(project, tmp_path):
    sdk = make_sdk(tmp_path / "sdk")
    (project / LOCAL).write_text('[steam]\nuser = "Builder"\n')
    r = run(project, sdk=str(sdk), host="mac")["steam_login"]
    assert r.status == d.FIX and r.action.kind == "steam_login" and r.action.data["command"][-1] == "Builder"
    vdf = project / "home/Library/Application Support/Steam/config/config.vdf"
    vdf.parent.mkdir(parents=True)
    vdf.write_text('"InstallConfigStore"\n{\n "Accounts"\n {\n  "builder"\n  {\n   "SteamID" "1"\n  }\n }\n}')
    assert run(project, sdk=str(sdk), host="mac")["steam_login"].status == d.PASS
    vdf.write_text('"Accounts" { "someoneelse" { } }')
    assert run(project, sdk=str(sdk), host="mac")["steam_login"].status == d.FIX


def test_steam_login_na_without_user(project):
    assert run(project)["steam_login"].status == d.NA


def test_account_cached_does_not_match_substring():
    assert d.account_cached('"bob" { }', "bob") and not d.account_cached('"bobby" { }', "bob")


def test_steam_ids_and_user(project):
    assert run(project, host="win")["steam_ids"].status == d.FIX
    (project / "uetool.toml").write_text('[steam]\napp_id = "5"\ndepot_win_id = "6"\n')
    assert run(project, host="win")["steam_ids"].status == d.PASS
    assert run(project, host="mac")["steam_ids"].status == d.FIX      # depot_mac_id missing
    assert run(project)["steam_user"].status == d.FIX


def test_apple_only_on_mac(project):
    assert run(project, host="win")["apple"].status == d.NA
    assert run(project, host="mac")["apple"].status == d.FIX
    (project / LOCAL).write_text('[apple]\napple_id = "a@b.c"\nteam_id = "T"\nsigning_identity = "Dev ID"\n')
    assert run(project, host="mac")["apple"].status == d.FIX            # no password yet
    assert run(project, host="mac", secrets_={("apple", "a@b.c")})["apple"].status == d.PASS


def test_stamped_ini(project):
    assert run(project)["stamped"].status == d.PASS
    (project / "Config/DefaultGame.ini").write_text("ProjectVersion=v3.1.0.5\n")
    r = run(project)["stamped"]
    assert r.status == d.FAIL and r.action.kind == "restore_version" and "v3.1.0.5" in r.detail


def test_export_lines_and_summary(project):
    assert d.export_lines("/s/sdk", "mac") == 'export UETOOL_STEAM_SDK="/s/sdk"'
    assert d.export_lines("C:/sdk", "win").startswith("setx ")
    assert d.export_lines("") == ""
    assert d.summary(list(run(project).values())) == "needs setup"
