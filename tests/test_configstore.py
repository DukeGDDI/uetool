import tomllib

from ui.configstore import BASE, LOCAL, ProjectConfig, is_placeholder


def test_placeholders():
    assert is_placeholder("") and is_placeholder("0000001") and not is_placeholder("4852730")


def test_read_and_layering(project):
    (project / LOCAL).write_text('[steam]\nuser = "bob"\n[project]\nbuild_config = "Development"\n')
    cfg = ProjectConfig(project)
    assert cfg.get("main_app_id") == "0000000"
    assert cfg.get("steam_user") == "bob"
    assert cfg.get("build_config") == "Development"   # local wins
    assert cfg.get("stage_dir") == "Saved/StagedBuilds"  # default
    assert cfg.is_unset("main_app_id") and cfg.is_unset("main_depot_mac_id") and not cfg.is_unset("steam_user")
    assert cfg.configured_apps() == [] and not cfg.legacy_steam_keys()


def test_save_preserves_comments_and_writes_home_file(project):
    cfg = ProjectConfig(project)
    cfg.set("main_app_id", "4852730")
    cfg.set("ue_root", "/Users/Shared/Epic Games/UE_5.7")
    assert cfg.dirty and not (project / LOCAL).exists()
    written = {p.name for p in cfg.save()}
    assert written == {BASE, LOCAL}
    text = (project / BASE).read_text()
    assert "# committed" in text and "# fill me" in text and "# default" in text
    assert tomllib.loads(text)["steam"]["main"]["app_id"] == "4852730"
    assert tomllib.loads((project / LOCAL).read_text())["engine"]["ue_root"].endswith("UE_5.7")
    assert not cfg.dirty and cfg.get("main_app_id") == "4852730"


def test_new_app_table_is_created_and_others_untouched(project):
    cfg = ProjectConfig(project)
    cfg.set("playtest_app_id", "4852730")
    cfg.set("playtest_depot_win_id", "4852731")
    cfg.save()
    text = (project / BASE).read_text()
    data = tomllib.loads(text)
    assert data["steam"]["playtest"] == {"app_id": "4852730", "depot_win_id": "4852731"}
    assert data["steam"]["main"]["app_id"] == "0000000" and "# fill me" in text
    assert "demo" not in data["steam"]
    assert cfg.configured_apps() == ["playtest"]
    # Clearing the app id makes it unconfigured again and removes the key.
    cfg.set("playtest_app_id", "")
    cfg.save()
    assert "app_id" not in tomllib.loads((project / BASE).read_text())["steam"]["playtest"]
    assert cfg.configured_apps() == []


def test_legacy_flat_keys_detected(project):
    (project / BASE).write_text('[steam]\napp_id = "1"\ndepot_win_id = "2"\n')
    cfg = ProjectConfig(project)
    assert cfg.legacy_steam_keys() and cfg.configured_apps() == []


def test_problems_per_app(project):
    cfg = ProjectConfig(project)
    p = cfg.problems()
    assert p["main_app_id"][0] == "warn" and "main_depot_win_id" not in p   # nothing configured yet
    cfg.set("main_app_id", "4547240")
    p = cfg.problems()
    assert "main_app_id" not in p and p["main_depot_win_id"][0] == "warn"   # placeholder depot
    cfg.set("main_depot_win_id", "4547241")
    assert not any(n.startswith("main_") for n in cfg.problems())
    assert not any(n.startswith("demo_") or n.startswith("playtest_") for n in cfg.problems())
    cfg.set("demo_depot_win_id", "5466762")                                   # depot without app id
    assert cfg.problems()["demo_app_id"][0] == "warn"
    cfg.set("demo_app_id", "x")
    assert cfg.problems()["demo_app_id"][0] == "error" and not cfg.can_save()


def test_epic_fields_configured_and_saved(project):
    cfg = ProjectConfig(project)
    assert not cfg.configured_epic()
    for name, val in (("epic_org_id", "o-x"), ("epic_product_id", "p"),
                      ("epic_artifact_id", "a"), ("epic_client_id", "c")):
        cfg.set(name, val)
    assert cfg.configured_epic()
    cfg.save()
    assert tomllib.loads((project / BASE).read_text())["epic"] == {
        "org_id": "o-x", "product_id": "p", "artifact_id": "a", "client_id": "c"}
    assert ProjectConfig(project).configured_epic()   # persists across reload


def test_epic_partial_config_warns(project):
    cfg = ProjectConfig(project)
    cfg.set("epic_org_id", "o-x")                       # only one of four set
    p = cfg.problems()
    assert p["epic_product_id"][0] == "warn" and p["epic_artifact_id"][0] == "warn"
    assert "epic_org_id" not in p and cfg.can_save()    # the set one isn't flagged; warns don't block
    assert not cfg.configured_epic()


def test_local_file_seeded_from_example_keeps_its_comments(project):
    cfg = ProjectConfig(project)
    cfg.set("steam_user", "builder")
    cfg.save()
    text = (project / LOCAL).read_text()
    assert "Do NOT commit it" in text and 'user = "builder"' in text


def test_save_only_touches_dirty_fields_and_survives_external_edits(project):
    cfg = ProjectConfig(project)
    cfg.set("main_depot_win_id", "123")
    (project / BASE).write_text((project / BASE).read_text() + '\n[extra]\nk = 1\n')
    cfg.save()
    data = tomllib.loads((project / BASE).read_text())
    assert data["extra"]["k"] == 1 and data["steam"]["main"]["depot_win_id"] == "123"
    assert data["steam"]["main"]["app_id"] == "0000000"


def test_validation_blocks_save(project):
    cfg = ProjectConfig(project)
    cfg.set("main_app_id", "abc")
    assert not cfg.can_save() and cfg.problems()["main_app_id"][0] == "error"
    try:
        cfg.save()
        raise AssertionError
    except ValueError:
        pass
    cfg.set("main_app_id", "")
    assert cfg.can_save() and cfg.problems()["main_app_id"][0] == "warn"


def test_setting_back_to_saved_value_is_not_dirty(project):
    cfg = ProjectConfig(project)
    cfg.set("main_app_id", "9")
    cfg.set("main_app_id", "0000000")
    assert not cfg.dirty


def test_clearing_removes_key_and_revert(project):
    (project / LOCAL).write_text('[steam]\nuser = "bob"\n')
    cfg = ProjectConfig(project)
    cfg.set("steam_user", "")
    cfg.save()
    assert "user" not in tomllib.loads((project / LOCAL).read_text()).get("steam", {})
    cfg.set("main_app_id", "5")
    cfg.revert()
    assert cfg.get("main_app_id") == "0000000"


def test_integer_ids_stay_integers(project):
    (project / BASE).write_text("[steam.main]\napp_id = 4852730\n")
    cfg = ProjectConfig(project)
    cfg.set("main_app_id", "555")
    cfg.save()
    assert tomllib.loads((project / BASE).read_text())["steam"]["main"]["app_id"] == 555


def test_value_in_other_file_is_written_where_it_lives(project):
    (project / LOCAL).write_text('[steam.main]\napp_id = "777"\n')
    cfg = ProjectConfig(project)
    assert cfg.get("main_app_id") == "777"
    cfg.set("main_app_id", "888")
    cfg.save()
    assert tomllib.loads((project / LOCAL).read_text())["steam"]["main"]["app_id"] == "888"


def test_apply_now_keeps_other_edits_pending(project):
    cfg = ProjectConfig(project)
    cfg.set("main_app_id", "42")
    cfg.apply_now("ue_root", "/x/UE_5.7")
    assert tomllib.loads((project / LOCAL).read_text())["engine"]["ue_root"] == "/x/UE_5.7"
    assert cfg.dirty_fields() == {"main_app_id"} and cfg.get("main_app_id") == "42"
    assert tomllib.loads((project / BASE).read_text())["steam"]["main"]["app_id"] == "0000000"
