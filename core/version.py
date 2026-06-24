"""Version handling.

The authored base `ProjectVersion=vMAJOR.MINOR.PATCH` in Config/DefaultGame.ini is
edited by hand and never carries a build number in source control. The monotonic
build counter lives in <project>/.build_number. The full build version is the base
plus the counter (e.g. base v1.9.0 + counter 8 -> v1.9.0.8).

`package` stamps that full version into DefaultGame.ini *just for the cook* (so the
shipped build embeds it at runtime / in crash reports), then restores the file to
the bare base — so the tracked source never accumulates build numbers.
"""
import re

from .config import Config

# Prefix + the three authored components; any existing 4th component is ignored.
_VERSION_RE = re.compile(r"^(ProjectVersion=v)(\d+)\.(\d+)\.(\d+)(?:\.\d+)?\s*$")


def _read_counter(cfg: Config) -> int:
    if cfg.counter_file.exists():
        text = cfg.counter_file.read_text(encoding="utf-8").strip()
        return int(text) if text else 0
    return 0


def base(cfg: Config) -> str:
    """The authored 3-part base, e.g. 'v1.9.0' (any 4th component is ignored)."""
    data = cfg.ini_path.read_bytes().decode("utf-8")
    for line in data.splitlines():
        m = _VERSION_RE.match(line.rstrip("\r\n"))
        if m:
            return f"v{m.group(2)}.{m.group(3)}.{m.group(4)}"
    raise SystemExit(f"Could not find a 'ProjectVersion=vX.Y.Z' line in {cfg.ini_path}")


def compute(cfg: Config) -> str:
    """Full build version = authored base + current counter, e.g. 'v1.9.0.8'."""
    return f"{base(cfg)}.{_read_counter(cfg)}"


def current(cfg: Config) -> str:
    """The full build version for the current counter (no mutation)."""
    return compute(cfg)


def bump(cfg: Config) -> str:
    """Increment the build counter and record the new full version in .version.

    Does NOT modify DefaultGame.ini — the authored base there stays vX.Y.Z. The
    build number is folded into the ini only at package time, via stamp()."""
    n = _read_counter(cfg) + 1
    version = f"{base(cfg)}.{n}"
    cfg.counter_file.write_text(f"{n}\n", encoding="utf-8")
    cfg.version_file.write_text(f"{version}\n", encoding="utf-8")
    return version


def stamp(cfg: Config, version: str) -> None:
    """Rewrite only the ProjectVersion line to `version` (e.g. 'v1.9.0.8' for the
    cook, or the bare base 'v1.9.0' to restore). The rest of the file and the
    original line endings are byte-preserved."""
    num = version[1:] if version.startswith("v") else version
    data = cfg.ini_path.read_bytes().decode("utf-8")
    lines = data.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        ending = line[len(stripped):]  # preserve original CRLF/LF
        m = _VERSION_RE.match(stripped)
        if m:
            lines[i] = f"{m.group(1)}{num}{ending}"
            cfg.ini_path.write_bytes("".join(lines).encode("utf-8"))
            return
    raise SystemExit(f"Could not find a 'ProjectVersion=vX.Y.Z' line in {cfg.ini_path}")
