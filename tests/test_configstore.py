import tomllib

from ui.configstore import BASE, LOCAL, ProjectConfig, is_placeholder


def test_placeholders():
    assert is_placeholder("") and is_placeholder("0000001") and not is_placeholder("4852730")


def test_read_and_layering(project):
    (project / LOCAL).write_text('[steam]\nuser = "bob"\n[project]\nbuild_config = "Development"\n')
    cfg = ProjectConfig(project)
    assert cfg.get("app_id") == "0000000"
    assert cfg.get("steam_user") == "bob"
    assert cfg.get("build_config") == "Development"   # local wins
    assert cfg.get("stage_dir") == "Saved/StagedBuilds"  # default
    assert cfg.is_unset("app_id") and cfg.is_unset("depot_mac_id") and not cfg.is_unset("steam_user")


def test_save_preserves_comments_and_writes_home_file(project):
    cfg = ProjectConfig(project)
    cfg.set("app_id", "4852730")
    cfg.set("ue_root", "/Users/Shared/Epic Games/UE_5.7")
    assert cfg.dirty and not (project / LOCAL).exists()
    written = {p.name for p in cfg.save()}
    assert written == {BASE, LOCAL}
    text = (project / BASE).read_text()
    assert "# committed" in text and "# fill me" in text and "# default" in text
    assert tomllib.loads(text)["steam"]["app_id"] == "4852730"
    assert tomllib.loads((project / LOCAL).read_text())["engine"]["ue_root"].endswith("UE_5.7")
    assert not cfg.dirty and cfg.get("app_id") == "4852730"


def test_local_file_seeded_from_example_keeps_its_comments(project):
    cfg = ProjectConfig(project)
    cfg.set("steam_user", "builder")
    cfg.save()
    text = (project / LOCAL).read_text()
    assert "Do NOT commit it" in text and 'user = "builder"' in text


def test_save_only_touches_dirty_fields_and_survives_external_edits(project):
    cfg = ProjectConfig(project)
    cfg.set("depot_win_id", "123")
    (project / BASE).write_text((project / BASE).read_text() + '\n[extra]\nk = 1\n')
    cfg.save()
    data = tomllib.loads((project / BASE).read_text())
    assert data["extra"]["k"] == 1 and data["steam"]["depot_win_id"] == "123"
    assert data["steam"]["app_id"] == "0000000"


def test_validation_blocks_save(project):
    cfg = ProjectConfig(project)
    cfg.set("app_id", "abc")
    assert not cfg.can_save() and cfg.problems()["app_id"][0] == "error"
    try:
        cfg.save()
        raise AssertionError
    except ValueError:
        pass
    cfg.set("app_id", "")
    assert cfg.can_save() and cfg.problems()["app_id"][0] == "warn"


def test_setting_back_to_saved_value_is_not_dirty(project):
    cfg = ProjectConfig(project)
    cfg.set("app_id", "9")
    cfg.set("app_id", "0000000")
    assert not cfg.dirty


def test_clearing_removes_key_and_revert(project):
    (project / LOCAL).write_text('[steam]\nuser = "bob"\n')
    cfg = ProjectConfig(project)
    cfg.set("steam_user", "")
    cfg.save()
    assert "user" not in tomllib.loads((project / LOCAL).read_text()).get("steam", {})
    cfg.set("app_id", "5")
    cfg.revert()
    assert cfg.get("app_id") == "0000000"


def test_integer_ids_stay_integers(project):
    (project / BASE).write_text("[steam]\napp_id = 4852730\n")
    cfg = ProjectConfig(project)
    cfg.set("app_id", "555")
    cfg.save()
    assert tomllib.loads((project / BASE).read_text())["steam"]["app_id"] == 555


def test_value_in_other_file_is_written_where_it_lives(project):
    (project / LOCAL).write_text('[steam]\napp_id = "777"\n')
    cfg = ProjectConfig(project)
    assert cfg.get("app_id") == "777"
    cfg.set("app_id", "888")
    cfg.save()
    assert tomllib.loads((project / LOCAL).read_text())["steam"]["app_id"] == "888"


def test_apply_now_keeps_other_edits_pending(project):
    cfg = ProjectConfig(project)
    cfg.set("app_id", "42")
    cfg.apply_now("ue_root", "/x/UE_5.7")
    assert tomllib.loads((project / LOCAL).read_text())["engine"]["ue_root"] == "/x/UE_5.7"
    assert cfg.dirty_fields() == {"app_id"} and cfg.get("app_id") == "42"
    assert tomllib.loads((project / BASE).read_text())["steam"]["app_id"] == "0000000"
