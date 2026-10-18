"""core.stage: the staged macOS bundle gets a configuration-independent name."""
import pytest

from core import config, stage


@pytest.fixture
def cfg(project):
    (project / "uetool.toml").write_text("[project]\n")
    return config.load(project)


def mac_root(cfg):
    root = cfg.stage_dir / "Mac"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_decorated_bundle_is_renamed(cfg, capsys):
    root = mac_root(cfg)
    (root / "Fake-Mac-Shipping.app" / "Contents" / "MacOS").mkdir(parents=True)
    out = stage.normalize_mac_bundle(cfg)
    assert out == root / "Fake.app" and out.is_dir() and not (root / "Fake-Mac-Shipping.app").exists()
    assert (out / "Contents" / "MacOS").is_dir()                 # contents moved, not copied
    assert "$ mv" in capsys.readouterr().out
    # Idempotent: a second call finds the normalized bundle and does nothing.
    assert stage.normalize_mac_bundle(cfg) == out and capsys.readouterr().out == ""


def test_any_configuration_is_normalized(cfg):
    root = mac_root(cfg)
    (root / "Fake-Mac-Development.app").mkdir()
    assert stage.normalize_mac_bundle(cfg) == root / "Fake.app"


def test_nothing_staged(cfg):
    assert stage.normalize_mac_bundle(cfg) is None          # no Mac folder at all
    root = mac_root(cfg)
    assert stage.normalize_mac_bundle(cfg) is None          # folder, but no bundle
    (root / "Other-Mac-Shipping.app").mkdir()                # not this project's bundle
    assert stage.normalize_mac_bundle(cfg) is None


def test_dry_run_only_prints(cfg, capsys):
    root = mac_root(cfg)
    (root / "Fake-Mac-Shipping.app").mkdir()
    assert stage.normalize_mac_bundle(cfg, dry_run=True) == root / "Fake.app"
    assert (root / "Fake-Mac-Shipping.app").is_dir() and not (root / "Fake.app").exists()
    assert "$ mv" in capsys.readouterr().out


def test_ambiguous_bundles_are_refused(cfg):
    root = mac_root(cfg)
    (root / "Fake-Mac-Shipping.app").mkdir()
    (root / "Fake-Mac-Development.app").mkdir()
    with pytest.raises(SystemExit, match="found 2"):
        stage.normalize_mac_bundle(cfg)
    (root / "Fake-Mac-Development.app").rmdir()
    (root / "Fake.app").mkdir()
    with pytest.raises(SystemExit, match="Both Fake.app and Fake-Mac-Shipping.app"):
        stage.normalize_mac_bundle(cfg)


def test_mac_bundle_path(cfg):
    assert stage.mac_bundle(cfg) == cfg.stage_dir / "Mac" / "Fake.app"
