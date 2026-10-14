from ui import projectstate as ps


def test_stamped_detection_and_restore(project):
    ini = project / "Config" / "DefaultGame.ini"
    assert ps.stamped_version(project) is None
    ini.write_bytes(b"[A]\r\nProjectVersion=v3.1.0.5\r\nOther=1\r\n")
    assert ps.stamped_version(project) == "v3.1.0.5"
    assert ps.restore_base(project) == "v3.1.0"
    assert ini.read_bytes() == b"[A]\r\nProjectVersion=v3.1.0\r\nOther=1\r\n"
    assert ps.restore_base(project) is None


def test_missing_ini(tmp_path):
    assert ps.project_version(tmp_path) is None and ps.stamped_version(tmp_path) is None


def test_overlaid_files(project):
    (project / "Config" / "DefaultEngine.ini").write_text("; uetool: merged from Config/Custom/X/ for this build only\n")
    assert [p.name for p in ps.overlaid_files(project)] == ["DefaultEngine.ini"]
