import os

from ui.configstore import ProjectConfig
from ui.history import builds_url, collect, human_size


def test_collect(project):
    (project / ".build_number").write_text("48\n")
    (project / ".version").write_text("v1.2.0.48\n")
    dist = project / ".uetool/dist"
    dist.mkdir(parents=True)
    old, new = dist / "Fake-v1.2.0.47-win.zip", dist / "Fake-v1.2.0.48-mac.zip"
    old.write_bytes(b"x" * 2048)
    new.write_bytes(b"y")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    (project / "Saved/StagedBuilds/Windows").mkdir(parents=True)
    info = collect(project, ProjectConfig(project))
    assert (info.version, info.counter, info.ini_version) == ("v1.2.0.48", 48, "v1.2.0")
    assert [(e.kind, e.platform) for e in info.entries][-1] == ("archive", "win")
    assert {e.kind for e in info.entries} == {"archive", "staged"}


def test_collect_empty(project):
    info = collect(project, ProjectConfig(project))
    assert info.version is None and info.counter is None and info.entries == []


def test_helpers():
    assert human_size(None) == "—" and human_size(512) == "512 B" and human_size(3 * 1024**3) == "3.0 GB"
    assert builds_url("4852730").endswith("/4852730") and builds_url("0000000") is None and builds_url("") is None
