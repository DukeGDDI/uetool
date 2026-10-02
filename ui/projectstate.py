"""Read-only facts about a project's working tree that the UI cares about.

The main one: did a cancelled/failed run leave Config/DefaultGame.ini stamped with a
4-part ProjectVersion (v3.1.0.5) instead of the authored v3.1.0? `restore_base` is the
only writer, and only ever called from an explicit user action.
"""
import re
from pathlib import Path

_VERSION_RE = re.compile(r"^(ProjectVersion=v)(\d+\.\d+\.\d+)(\.\d+)?\s*$")
OVERLAY_MARKER = "; uetool: merged from Config/Custom/"


def _ini(project: Path | str) -> Path:
    return Path(project) / "Config" / "DefaultGame.ini"


def project_version(project: Path | str) -> str | None:
    """The ProjectVersion string in DefaultGame.ini (e.g. 'v3.1.0.5'), or None."""
    try:
        text = _ini(project).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = _VERSION_RE.match(line)
        if m:
            return "v" + m.group(2) + (m.group(3) or "")
    return None


def stamped_version(project: Path | str) -> str | None:
    """The stamped 4-part version if DefaultGame.ini was left stamped, else None."""
    v = project_version(project)
    return v if v and v.count(".") == 3 else None


def overlaid_files(project: Path | str) -> list[Path]:
    """Config/Default*.ini files still carrying a --custom-config merge marker."""
    cfg = Path(project) / "Config"
    out = []
    for p in sorted(cfg.glob("Default*.ini")):
        try:
            if OVERLAY_MARKER in p.read_text(encoding="utf-8"):
                out.append(p)
        except OSError:
            pass
    return out


def restore_base(project: Path | str) -> str | None:
    """Rewrite a stamped ProjectVersion back to its 3-part base, preserving every other
    byte (line endings included). Returns the restored version, or None if nothing to do."""
    p = _ini(project)
    data = p.read_bytes().decode("utf-8")
    lines = data.splitlines(keepends=True)
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        m = _VERSION_RE.match(body)
        if m:
            if not m.group(3):
                return None
            lines[i] = m.group(1) + m.group(2) + line[len(body):]
            p.write_bytes("".join(lines).encode("utf-8"))
            return "v" + m.group(2)
    return None
