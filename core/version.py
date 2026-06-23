"""Version stamping.

Reads `ProjectVersion=vMAJOR.MINOR.PATCH[.OLDBUILD]` from Config/DefaultGame.ini,
strips any existing 4th component, increments the monotonic build counter, and
writes back `vMAJOR.MINOR.PATCH.N`. Only that one line is rewritten so the rest of
the file (the long +IniKeyDenylist arrays, etc.) is byte-preserved.
"""
import re

from .config import Config

# Capture the prefix and the three authored components; ignore any existing 4th.
_VERSION_RE = re.compile(r"^(ProjectVersion=v)(\d+)\.(\d+)\.(\d+)(?:\.\d+)?\s*$")


def _read_counter(cfg: Config) -> int:
    if cfg.counter_file.exists():
        text = cfg.counter_file.read_text(encoding="utf-8").strip()
        return int(text) if text else 0
    return 0


def current(cfg: Config) -> str | None:
    """Return the current full ProjectVersion string, or None if absent."""
    data = cfg.ini_path.read_bytes().decode("utf-8")
    for line in data.splitlines():
        m = _VERSION_RE.match(line)
        if m:
            return line.strip().split("=", 1)[1]
    return None


def bump(cfg: Config) -> str:
    """Increment the build number, stamp the ini, and return the new version."""
    data = cfg.ini_path.read_bytes().decode("utf-8")
    lines = data.splitlines(keepends=True)

    n = _read_counter(cfg) + 1
    new_version = None

    for i, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        ending = line[len(stripped):]  # preserve original CRLF/LF
        m = _VERSION_RE.match(stripped)
        if m:
            base = f"{m.group(2)}.{m.group(3)}.{m.group(4)}"
            new_version = f"v{base}.{n}"
            lines[i] = f"{m.group(1)}{base}.{n}{ending}"
            break

    if new_version is None:
        raise SystemExit(
            f"Could not find a 'ProjectVersion=vX.Y.Z' line in {cfg.ini_path}"
        )

    cfg.ini_path.write_bytes("".join(lines).encode("utf-8"))
    cfg.counter_file.write_text(f"{n}\n", encoding="utf-8")
    cfg.version_file.write_text(f"{new_version}\n", encoding="utf-8")
    return new_version
