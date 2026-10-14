"""What's on disk for a project: version, staged builds, archives. Read-only."""
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import projectstate
from .configstore import ProjectConfig


@dataclass(frozen=True)
class Entry:
    kind: str        # "archive" | "staged"
    name: str
    platform: str
    size: int | None
    modified: datetime
    path: Path


@dataclass(frozen=True)
class HistoryInfo:
    version: str | None      # last recorded full version (.version)
    counter: int | None      # .build_number
    ini_version: str | None  # ProjectVersion currently in DefaultGame.ini
    entries: list[Entry]


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def collect(project: Path | str, cfg: ProjectConfig) -> HistoryInfo:
    project = Path(project)
    counter = _read(project / ".build_number")
    entries: list[Entry] = []
    dist = project / ".uetool" / "dist"
    if dist.is_dir():
        for z in dist.glob("*.zip"):
            m = re.search(r"-(win|mac)\.zip$", z.name)
            st = z.stat()
            entries.append(Entry("archive", z.name, m.group(1) if m else "?", st.st_size,
                                 datetime.fromtimestamp(st.st_mtime), z))
    stage = project / cfg.get("stage_dir")
    for plat, sub in (("win", "Windows"), ("mac", "Mac")):
        d = stage / sub
        if d.is_dir():
            entries.append(Entry("staged", f"{cfg.get('stage_dir')}/{sub}", plat, None,
                                 datetime.fromtimestamp(d.stat().st_mtime), d))
    entries.sort(key=lambda e: e.modified, reverse=True)
    return HistoryInfo(_read(project / ".version"),
                       int(counter) if counter and counter.isdigit() else None,
                       projectstate.project_version(project), entries)


def human_size(n: int | None) -> str:
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def builds_url(app_id: str) -> str | None:
    return f"https://partner.steamgames.com/apps/builds/{app_id}" if app_id.isdigit() and not app_id.startswith("0000") else None
