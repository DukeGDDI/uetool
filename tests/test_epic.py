"""Epic (BuildPatchTool) upload backend: command construction + guards, no real BPT."""
import pytest

from core import config, epic


def _project(tmp_path, *, epic_toml=True, staged=("win",)):
    root = tmp_path / "Game"
    (root / "Config").mkdir(parents=True)
    (root / "Game.uproject").write_text("{}")
    (root / "Config" / "DefaultGame.ini").write_text(
        "[/Script/EngineSettings.GeneralProjectSettings]\nProjectVersion=v1.2.0\n")
    toml = '[project]\nbuild_config = "Shipping"\n'
    if epic_toml:
        toml += ('\n[epic]\norg_id = "o-abc"\nproduct_id = "prod123"\n'
                 'artifact_id = "art123"\nclient_id = "xyzaCLIENT"\n')
    (root / "uetool.toml").write_text(toml)
    (root / ".build_number").write_text("8\n")
    (root / ".version").write_text("v1.2.0.8\n")
    for p in staged:
        (root / "Saved" / "StagedBuilds" / ("Windows" if p == "win" else "Mac")).mkdir(parents=True)
    return root


def _capture(monkeypatch):
    calls = {}
    monkeypatch.setattr(epic, "run", lambda cmd, dry: calls.setdefault("cmd", cmd))
    return calls


def test_not_configured_raises(tmp_path):
    cfg = config.load(_project(tmp_path, epic_toml=False))
    assert cfg.epic is None
    with pytest.raises(SystemExit):
        epic.upload(cfg, "win", dry_run=True)


def test_upload_builds_bpt_command_win(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    epic.upload(config.load(_project(tmp_path)), "win", dry_run=True)
    cmd = calls["cmd"]
    assert cmd[0] == "BuildPatchTool" and "-mode=UploadBinary" in cmd
    assert "-OrganizationId=o-abc" in cmd and "-ProductId=prod123" in cmd
    assert "-ArtifactId=art123" in cmd and "-ClientId=xyzaCLIENT" in cmd
    assert "-ClientSecretEnvVar=UETOOL_EPIC_CLIENT_SECRET" in cmd
    assert "-BuildVersion=v1.2.0.8-win" in cmd          # platform-distinct, no whitespace
    assert "-AppLaunch=Game.exe" in cmd
    assert any(a.startswith("-BuildRoot=") and a.endswith("/Windows") for a in cmd)
    assert any(a.startswith("-CloudDir=") for a in cmd)


def test_upload_mac_app_launch_is_inner_binary(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(epic.stage, "normalize_mac_bundle", lambda c, d: None)
    epic.upload(config.load(_project(tmp_path, staged=("mac",))), "mac", dry_run=True)
    cmd = calls["cmd"]
    assert "-AppLaunch=Game.app/Contents/MacOS/Game" in cmd   # inner Mach-O, not the .app
    assert "-BuildVersion=v1.2.0.8-mac" in cmd


def test_upload_mac_app_launch_reads_decorated_executable(tmp_path, monkeypatch):
    # A Shipping bundle's folder is <Project>.app but its inner binary keeps UE's
    # config-decorated name; AppLaunch must use the real CFBundleExecutable.
    import plistlib
    calls = _capture(monkeypatch)
    monkeypatch.setattr(epic.stage, "normalize_mac_bundle", lambda c, d: None)
    root = _project(tmp_path, staged=("mac",))
    contents = root / "Saved/StagedBuilds/Mac/Game.app/Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump({"CFBundleExecutable": "Game-Mac-Shipping"}, fh)
    epic.upload(config.load(root), "mac", dry_run=True)
    assert "-AppLaunch=Game.app/Contents/MacOS/Game-Mac-Shipping" in calls["cmd"]


def test_custom_config_suffixes_build_version(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    epic.upload(config.load(_project(tmp_path)), "win", dry_run=True, custom_config="Demo")
    assert "-BuildVersion=v1.2.0.8-win_Demo" in calls["cmd"]


def test_secret_required_for_real_upload(tmp_path, monkeypatch):
    monkeypatch.delenv("UETOOL_EPIC_CLIENT_SECRET", raising=False)
    with pytest.raises(SystemExit) as e:
        epic.upload(config.load(_project(tmp_path)), "win", dry_run=False)
    assert "UETOOL_EPIC_CLIENT_SECRET" in str(e.value)


def test_app_launch_override(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    root = _project(tmp_path)
    root.joinpath("uetool.toml").write_text(
        root.joinpath("uetool.toml").read_text() + 'app_launch_win = "Sub/Dir/Launch.exe"\n')
    epic.upload(config.load(root), "win", dry_run=True)
    assert "-AppLaunch=Sub/Dir/Launch.exe" in calls["cmd"]
