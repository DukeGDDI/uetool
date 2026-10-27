"""Mac App Store backend: command construction + guards, no real codesign/altool."""
import pytest

from core import appstore, config


def _project(tmp_path, *, appstore_toml=True, staged=True, entitlements=True, api_key_path=""):
    root = tmp_path / "Game"
    (root / "Config").mkdir(parents=True)
    (root / "Game.uproject").write_text("{}")
    (root / "Config" / "DefaultGame.ini").write_text(
        "[/Script/EngineSettings.GeneralProjectSettings]\nProjectVersion=v1.2.0\n")
    toml = '[project]\nbuild_config = "Shipping"\n'
    if appstore_toml:
        prof = root / "D6.provisionprofile"
        prof.write_text("profile")
        ent_line = ""
        if entitlements:
            e = root / "MAS.entitlements"
            e.write_text("<plist/>")
            ent_line = f'entitlements_path = "{e}"\n'
        key_line = f'api_key_path = "{api_key_path}"\n' if api_key_path else ""
        toml += ('\n[appstore]\n'
                 'bundle_id = "com.game"\n'
                 'team_id = "TEAMID123"\n'
                 'app_identity = "Apple Distribution: Me (TEAMID123)"\n'
                 'installer_identity = "3rd Party Mac Developer Installer: Me (TEAMID123)"\n'
                 f'provision_path = "{prof}"\n{ent_line}{key_line}'
                 'asc_key_id = "KEYID123"\n'
                 'asc_issuer_id = "issuer-uuid"\n')
    (root / "uetool.toml").write_text(toml)
    (root / ".build_number").write_text("8\n")
    (root / ".version").write_text("v1.2.0.8\n")
    if staged:
        (root / "Saved" / "StagedBuilds" / "Mac" / "Game.app" / "Contents").mkdir(parents=True)
    return root


def _capture(monkeypatch, *, mac=True):
    """Record every external command (appstore's own + the shared signing helper's)."""
    calls: list[list[str]] = []
    rec = lambda cmd, dry: calls.append([str(x) for x in cmd])
    monkeypatch.setattr(appstore, "run", rec)
    monkeypatch.setattr(appstore.macsign, "run", rec)
    monkeypatch.setattr(appstore, "host_is_macos", lambda: mac)
    return calls


def _find(calls, head):
    return [c for c in calls if c and c[0] == head]


def test_not_configured_raises(tmp_path, monkeypatch):
    _capture(monkeypatch)
    cfg = config.load(_project(tmp_path, appstore_toml=False))
    assert cfg.appstore is None
    with pytest.raises(SystemExit):
        appstore.upload(cfg, "mac", dry_run=True)


def test_requires_mac_host(tmp_path, monkeypatch):
    _capture(monkeypatch, mac=False)
    with pytest.raises(SystemExit, match="needs macOS"):
        appstore.upload(config.load(_project(tmp_path)), "mac", dry_run=True)


def test_requires_mac_target(tmp_path, monkeypatch):
    _capture(monkeypatch, mac=True)
    with pytest.raises(SystemExit, match="mac-only"):
        appstore.upload(config.load(_project(tmp_path)), "win", dry_run=True)


def test_upload_sequence(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    appstore.upload(config.load(_project(tmp_path)), "mac", dry_run=True)

    # cp embeds the provisioning profile into the bundle
    cp = _find(calls, "cp")[0]
    assert cp[1].endswith("D6.provisionprofile")
    assert cp[2].endswith("Game.app/Contents/embedded.provisionprofile")

    # the bundle codesign: Apple Distribution identity + MAS entitlements, NO hardened runtime
    bundle_sign = next(c for c in calls if c[0] == "codesign" and "--entitlements" in c)
    assert "Apple Distribution: Me (TEAMID123)" in bundle_sign
    assert bundle_sign[-1].endswith("Game.app")
    assert "runtime" not in bundle_sign
    assert "--timestamp=none" in bundle_sign

    assert _find(calls, "codesign")  # (verify call also present)
    assert any(c[:3] == ["codesign", "--verify", "--deep"] for c in calls)

    # chmod a+rX fixes the 90255 root-only-files rejection
    chmod = _find(calls, "chmod")[0]
    assert chmod[1:3] == ["-R", "a+rX"] and chmod[3].endswith("Game.app")

    # productbuild signs the .pkg with the Installer identity
    pb = _find(calls, "productbuild")[0]
    assert pb[1:3] == ["--component"] + [pb[2]] and pb[3] == "/Applications"
    assert "3rd Party Mac Developer Installer: Me (TEAMID123)" in pb and pb[-1].endswith("Game.pkg")

    # altool uploads the pkg with the API-key ids (no secret)
    alt = _find(calls, "xcrun")[0]
    assert alt[:3] == ["xcrun", "altool", "--upload-app"]
    assert "--type" in alt and "macos" in alt
    assert "--apiKey" in alt and "KEYID123" in alt
    assert "--apiIssuer" in alt and "issuer-uuid" in alt

    # order: cp -> sign -> verify -> chmod -> productbuild -> altool
    heads = [c[0] for c in calls]
    assert heads.index("cp") < heads.index("chmod") < heads.index("productbuild") < heads.index("xcrun")


def test_validate_uses_validate_app(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    appstore.upload(config.load(_project(tmp_path)), "mac", dry_run=True, validate=True)
    alt = _find(calls, "xcrun")[0]
    assert "--validate-app" in alt and "--upload-app" not in alt


def test_generated_entitlements_when_unset(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    appstore.upload(config.load(_project(tmp_path, entitlements=False)), "mac", dry_run=True)
    bundle_sign = next(c for c in calls if c[0] == "codesign" and "--entitlements" in c)
    ent = bundle_sign[bundle_sign.index("--entitlements") + 1]
    assert ent.endswith("mas.entitlements")


def test_no_secret_in_output(tmp_path, monkeypatch, capsys):
    # The .p8 is never read: its bytes must never reach argv or stdout.
    secret = tmp_path / "AuthKey_KEYID123.p8"
    secret.write_text("SENTINEL-PRIVATE-KEY")
    calls = _capture(monkeypatch)
    appstore.upload(config.load(_project(tmp_path, api_key_path=str(secret))), "mac", dry_run=True)
    blob = capsys.readouterr().out + "\n".join(" ".join(c) for c in calls)
    assert "SENTINEL-PRIVATE-KEY" not in blob
    assert str(secret) not in blob            # not even the path reaches the command line
    assert "KEYID123" in blob and "issuer-uuid" in blob   # only the ids do
