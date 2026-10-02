import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def project(tmp_path):
    """A fake UE project: never use a real one in tests."""
    root = tmp_path / "Fake"
    (root / "Config").mkdir(parents=True)
    (root / "Fake.uproject").write_text("{}")
    (root / "Config" / "DefaultGame.ini").write_text(
        "[/Script/EngineSettings.GeneralProjectSettings]\nProjectVersion=v1.2.0\n")
    (root / "uetool.toml").write_text(
        '# committed\n[project]\nbuild_config = "Shipping"   # default\n\n'
        '[steam]\napp_id = "0000000"  # fill me\ndepot_win_id = "0000001"\n')
    return root
