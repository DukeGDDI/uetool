from ui import commands as c
from ui.commands import BuildSpec, ERROR


def argv(spec, **kw):
    return c.build_argv(spec, "/p", python="py", script="u.py", **kw)


def test_release_defaults():
    assert argv(BuildSpec(platform="win")) == ["py", "u.py", "-P", "/p", "release", "--platform", "win"]


def test_flags_only_where_accepted():
    s = BuildSpec(command="upload", platform="mac", build_config="Shipping", bump=False,
                  bootstrap=False, clean=True, custom_config="X", dry_run=True)
    assert argv(s)[4:] == ["upload", "--platform", "mac", "--config", "Shipping", "--dry-run"]
    s = BuildSpec(command="upload", platform="mac", app="playtest")
    assert argv(s)[4:] == ["upload", "--platform", "mac", "--app", "playtest"]
    assert argv(BuildSpec(command="package", app="playtest", bump=False))[4:] == [
        "package", "--platform", "win", "--no-bump"]
    assert argv(BuildSpec(command="bootstrap", dry_run=True, clean=True))[4:] == ["bootstrap", "--dry-run"]
    assert argv(BuildSpec(command="archive", build_config="Dev"))[4:] == ["archive", "--platform", "win"]


def test_package_all_flags():
    s = BuildSpec(command="package", platform="win", build_config="Development", bump=False,
                  bootstrap=False, clean=True, custom_config="Arcware", dry_run=True)
    assert argv(s)[4:] == ["package", "--platform", "win", "--config", "Development", "--no-bump",
                           "--no-bootstrap", "--clean", "--custom-config", "Arcware", "--dry-run"]


def test_caps_match_cli_parser():
    """CAPS must agree with what core/cli.py's argparse really accepts."""
    import argparse
    import core.cli as cli
    captured = {}
    orig = argparse.ArgumentParser.parse_args

    def spy(self, *a, **k):
        captured["p"] = self
        raise SystemExit
    argparse.ArgumentParser.parse_args = spy
    try:
        try:
            cli.main()
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = orig
    sub = next(a for a in captured["p"]._actions if isinstance(a, argparse._SubParsersAction))
    flagmap = {"platform": "--platform", "config": "--config", "dry_run": "--dry-run",
               "bump": "--no-bump", "bootstrap": "--no-bootstrap", "clean": "--clean",
               "custom_config": "--custom-config", "app": "--app", "store": "--store"}
    # `ui` is a CLI-only launcher (opens the Control Panel); the UI form doesn't model it,
    # so it has no CAPS entry. Every other subcommand must match CAPS exactly.
    assert set(sub.choices) - {"ui"} == set(c.CAPS)
    for name in c.CAPS:
        opts = {o for a in sub.choices[name]._actions for o in a.option_strings}
        assert {flagmap[f] for f in c.CAPS[name]} == opts & set(flagmap.values()), name


def test_validate_release_custom_config_allowed():
    # A custom layer on release is permitted (e.g. a Demo layer -> Demo app); it is only
    # an error if the named layer folder doesn't exist.
    ok = BuildSpec(command="release", custom_config="Demo", bump=False, app="demo")
    assert not c.blocking(c.validate(ok, "win", layers=["Demo"], apps=["demo"]))
    missing = BuildSpec(command="release", custom_config="Nope", bump=False, app="demo")
    assert c.blocking(c.validate(missing, "win", layers=["Demo"], apps=["demo"]))


def test_validate_custom_config_must_exist_for_package():
    s = BuildSpec(command="package", custom_config="Nope", bump=False)
    assert c.blocking(c.validate(s, "win", layers=["Arcware"]))
    assert not c.blocking(c.validate(s, "win", layers=["Nope"]))


def test_release_custom_config_in_argv():
    # release must now emit --custom-config (CAPS already allows it).
    s = BuildSpec(command="release", platform="win", custom_config="Demo", bump=False, app="demo")
    assert "--custom-config" in argv(s) and "Demo" in argv(s)


def test_store_epic_in_argv_steam_omitted():
    epic = BuildSpec(command="release", platform="win", store="epic", bump=False)
    assert argv(epic)[4:] == ["release", "--platform", "win", "--no-bump", "--store", "epic"]
    # steam is the default and is kept out of the command line.
    steam = BuildSpec(command="upload", platform="win", store="steam", app="main")
    assert "--store" not in argv(steam)


def test_store_appstore_in_argv():
    s = BuildSpec(command="release", platform="mac", store="appstore", bump=False)
    assert argv(s)[4:] == ["release", "--platform", "mac", "--no-bump", "--store", "appstore"]


def test_validate_appstore_requires_config_and_mac():
    base = dict(command="release", platform="mac", store="appstore", bump=False)
    assert c.blocking(c.validate(BuildSpec(**base), "mac", appstore_configured=False))     # not set up
    assert not c.blocking(c.validate(BuildSpec(**base), "mac", appstore_configured=True))  # set up on mac
    assert c.blocking(c.validate(BuildSpec(**base), "win", appstore_configured=True))      # non-mac host
    win = BuildSpec(command="release", platform="win", store="appstore", bump=False)
    assert c.blocking(c.validate(win, "mac", appstore_configured=True))                    # non-mac target


def test_validate_epic_requires_config_and_skips_steam_app():
    epic = BuildSpec(command="release", platform="win", store="epic", bump=False)
    assert c.blocking(c.validate(epic, "win", epic_configured=False))        # not set up -> error
    assert not c.blocking(c.validate(epic, "win", epic_configured=True))     # set up -> fine
    # with store=epic, an ambiguous/missing Steam app is irrelevant (not checked).
    assert not c.blocking(c.validate(epic, "win", apps=["main", "demo"], epic_configured=True))


def test_validate_steam_app_choice():
    one, many = ["playtest"], ["main", "playtest"]
    rel = BuildSpec(command="release", bump=False)
    assert not c.blocking(c.validate(rel, "win"))                       # apps=None: skipped
    assert not c.blocking(c.validate(rel, "win", apps=one))             # single app implied
    assert c.blocking(c.validate(rel, "win", apps=[]))                  # nothing configured
    bad = c.blocking(c.validate(rel, "win", apps=many))
    assert bad and "choose" in bad[0].message                          # ambiguous
    assert not c.blocking(c.validate(BuildSpec(command="release", bump=False, app="main"), "win", apps=many))
    assert c.blocking(c.validate(BuildSpec(command="release", bump=False, app="demo"), "win", apps=many))
    # Commands that don't upload never care.
    assert not c.blocking(c.validate(BuildSpec(command="package", bump=False), "win", apps=many))


def test_notarize_only_on_mac():
    assert c.blocking(c.validate(BuildSpec(command="notarize", platform="mac"), "win"))
    assert c.blocking(c.validate(BuildSpec(command="release", platform="mac", bump=False), "win"))
    assert not c.blocking(c.validate(BuildSpec(command="release", platform="mac", bump=False), "mac"))
    assert not c.blocking(c.validate(BuildSpec(command="release", platform="win", bump=False), "win"))


def test_dry_run_with_bump_is_blocked_and_for_dry_run_fixes_it():
    s = BuildSpec(command="package", dry_run=True)
    assert c.blocking(c.validate(s, "win"))
    d = c.for_dry_run(BuildSpec(command="package"))
    assert d.dry_run and not d.bump and not c.blocking(c.validate(d, "win"))
    assert c.blocking(c.validate(c.for_dry_run(BuildSpec(command="bump")), "win"))


def test_effective_bump():
    assert c.effective_bump(BuildSpec(command="bump"))
    assert c.effective_bump(BuildSpec(command="release", bump=True))
    assert not c.effective_bump(BuildSpec(command="release", bump=False))
    assert not c.effective_bump(BuildSpec(command="upload", bump=True))


def test_clean_warning():
    assert c.clean_warning(BuildSpec(command="package", clean=True))
    assert c.clean_warning(BuildSpec(command="package", clean=True, dry_run=True)) is None
    assert c.clean_warning(BuildSpec(command="upload", clean=True)) is None


def test_display_quotes_paths():
    out = c.display(BuildSpec(command="upload", platform="win"), "/My Games/Fake")
    assert out == "uetool -P '/My Games/Fake' upload --platform win"


def test_custom_layers(project):
    assert c.custom_layers(project) == []
    (project / "Config" / "Custom" / "Arcware").mkdir(parents=True)
    (project / "Config" / "Custom" / "A.txt").write_text("x")
    assert c.custom_layers(project) == ["Arcware"]
