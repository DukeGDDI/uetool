"""Read and write uetool.toml / uetool.local.toml, keeping template comments intact.

Reads mirror core/config.py (local layer wins over the committed one). Writes use
tomlkit, touch only the fields the user changed, and re-parse the file first, so an
edit made elsewhere in the meantime isn't clobbered.
"""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomlkit

REPO = Path(__file__).resolve().parent.parent
BASE, LOCAL = "uetool.toml", "uetool.local.toml"


@dataclass(frozen=True)
class Field:
    name: str
    file: str       # file the key lives in when it isn't present in either
    section: str
    key: str
    kind: str = "text"   # text | id | path


FIELDS: dict[str, Field] = {f.name: f for f in [
    Field("build_config", BASE, "project", "build_config"),
    Field("stage_dir", BASE, "project", "stage_dir", "path"),
    Field("app_id", BASE, "steam", "app_id", "id"),
    Field("depot_win_id", BASE, "steam", "depot_win_id", "id"),
    Field("depot_mac_id", BASE, "steam", "depot_mac_id", "id"),
    Field("ue_root", LOCAL, "engine", "ue_root", "path"),
    Field("steam_user", LOCAL, "steam", "user"),
    Field("apple_id", LOCAL, "apple", "apple_id"),
    Field("team_id", LOCAL, "apple", "team_id"),
    Field("signing_identity", LOCAL, "apple", "signing_identity"),
]}

DEFAULTS = {"build_config": "Shipping", "stage_dir": "Saved/StagedBuilds"}
TEMPLATES = {BASE: "uetool.toml.example", LOCAL: "uetool.local.toml.example"}


def is_placeholder(value: str) -> bool:
    """Steam ids that are empty or still the template's 0000… count as unset."""
    v = (value or "").strip()
    return v == "" or v.startswith("0000")


def _load(path: Path) -> dict:
    if path.is_file():
        with path.open("rb") as fh:
            return tomllib.load(fh)
    return {}


class ProjectConfig:
    def __init__(self, project_root: Path | str):
        self.root = Path(project_root).expanduser()
        self._edits: dict[str, str] = {}
        self.load()

    def path(self, which: str) -> Path:
        return self.root / which

    def load(self) -> None:
        self._data = {BASE: _load(self.path(BASE)), LOCAL: _load(self.path(LOCAL))}
        self._edits.clear()

    revert = load

    # -- reading -----------------------------------------------------------
    def _stored(self, name: str) -> tuple[str, str | None]:
        """(value, file it came from). Local overrides base, as in core.config."""
        f = FIELDS[name]
        for which in (LOCAL, BASE):
            sec = self._data[which].get(f.section, {})
            if f.key in sec:
                return str(sec[f.key]), which
        return DEFAULTS.get(name, ""), None

    def saved(self, name: str) -> str:
        return self._stored(name)[0]

    def get(self, name: str) -> str:
        return self._edits.get(name, self.saved(name))

    def set(self, name: str, value: str) -> None:
        value = value.strip()
        if value == self.saved(name):
            self._edits.pop(name, None)
        else:
            self._edits[name] = value

    @property
    def dirty(self) -> bool:
        return bool(self._edits)

    def dirty_fields(self) -> set[str]:
        return set(self._edits)

    def is_unset(self, name: str) -> bool:
        v = self.get(name)
        return is_placeholder(v) if FIELDS[name].kind == "id" else v.strip() == ""

    # -- validation --------------------------------------------------------
    def problems(self) -> dict[str, tuple[str, str]]:
        """{field: (level, message)}; level is 'error' (won't save) or 'warn'."""
        out: dict[str, tuple[str, str]] = {}
        for name, f in FIELDS.items():
            v = self.get(name).strip()
            if f.kind == "id":
                if v and not v.isdigit():
                    out[name] = ("error", "Steam ids are numbers only.")
                elif is_placeholder(v) and name != "depot_mac_id":
                    out[name] = ("warn", "Still a placeholder: use the id from Steamworks.")
        if not self.get("stage_dir").strip():
            out["stage_dir"] = ("error", "Stage directory can't be empty.")
        if not self.get("build_config").strip():
            out["build_config"] = ("error", "Build configuration can't be empty.")
        return out

    def can_save(self) -> bool:
        return not any(lvl == "error" for lvl, _ in self.problems().values())

    # -- writing -----------------------------------------------------------
    def _document(self, which: str):
        p = self.path(which)
        if p.is_file():
            return tomlkit.parse(p.read_text(encoding="utf-8"))
        tpl = REPO / TEMPLATES[which]
        if tpl.is_file():
            return tomlkit.parse(tpl.read_text(encoding="utf-8"))
        return tomlkit.document()

    def save(self) -> list[Path]:
        """Write the pending edits. Returns the files that were changed."""
        if not self._edits:
            return []
        if not self.can_save():
            raise ValueError("Fix the highlighted fields before saving.")
        docs: dict[str, object] = {}
        for name, value in self._edits.items():
            f = FIELDS[name]
            _, where = self._stored(name)
            which = where or f.file
            doc = docs.get(which) or docs.setdefault(which, self._document(which))
            table = doc.get(f.section)
            if value == "":
                if table is not None and f.key in table:
                    del table[f.key]
                continue
            if table is None:
                doc[f.section] = tomlkit.table()
                table = doc[f.section]
            old = table.get(f.key)
            table[f.key] = int(value) if isinstance(old, int) and value.isdigit() else value
        written = []
        for which, doc in docs.items():
            p = self.path(which)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
            os.replace(tmp, p)
            written.append(p)
        self.load()
        return written
