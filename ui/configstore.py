"""Read and write uetool.toml / uetool.local.toml, keeping template comments intact.

Reads mirror core/config.py (local layer wins over the committed one). Writes use
tomlkit, touch only the fields the user changed, and re-parse the file first, so an
edit made elsewhere in the meantime isn't clobbered.

Steam ids are per app: the fields main_app_id, demo_depot_win_id, … map onto the
[steam.main] / [steam.demo] / [steam.playtest] tables (a dotted `section`).
"""
# ProjectConfig has a method named `set`, which would shadow the builtin in the
# `-> set[str]` annotation on Python < 3.14 (eager annotation evaluation).
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from core.config import LEGACY_STEAM_KEYS, STEAM_APPS, is_placeholder  # noqa: F401 (re-exported)

REPO = Path(__file__).resolve().parent.parent
BASE, LOCAL = "uetool.toml", "uetool.local.toml"


@dataclass(frozen=True)
class Field:
    name: str
    file: str       # file the key lives in when it isn't present in either
    section: str    # toml table, dotted for a nested one ("steam.main")
    key: str
    kind: str = "text"   # text | id | path


def steam_field(app: str, key: str) -> str:
    """Field name for `key` ('app_id', 'depot_win_id', 'depot_mac_id') of a Steam app."""
    return f"{app}_{key}"


FIELDS: dict[str, Field] = {f.name: f for f in [
    Field("build_config", BASE, "project", "build_config"),
    Field("stage_dir", BASE, "project", "stage_dir", "path"),
    *[Field(steam_field(app, key), BASE, f"steam.{app}", key, "id")
      for app in STEAM_APPS for key in ("app_id", "depot_win_id", "depot_mac_id")],
    Field("ue_root", LOCAL, "engine", "ue_root", "path"),
    Field("steam_user", LOCAL, "steam", "user"),
    Field("apple_id", LOCAL, "apple", "apple_id"),
    Field("team_id", LOCAL, "apple", "team_id"),
    Field("signing_identity", LOCAL, "apple", "signing_identity"),
]}

DEFAULTS = {"build_config": "Shipping", "stage_dir": "Saved/StagedBuilds"}
TEMPLATES = {BASE: "uetool.toml.example", LOCAL: "uetool.local.toml.example"}


def _load(path: Path) -> dict:
    if path.is_file():
        with path.open("rb") as fh:
            return tomllib.load(fh)
    return {}


def _lookup(data: dict, section: str) -> dict:
    """The (possibly nested) table `section` names, or {} if absent."""
    cur = data
    for part in section.split("."):
        cur = cur.get(part, {}) if isinstance(cur, dict) else {}
    return cur if isinstance(cur, dict) else {}


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
            sec = _lookup(self._data[which], f.section)
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

    def apply_now(self, name: str, value: str) -> None:
        """Save one field immediately, leaving any other pending edits pending."""
        others = {k: v for k, v in self._edits.items() if k != name}
        self._edits = {}
        self.set(name, value)
        try:
            self.save()
        finally:
            for k, v in others.items():
                self.set(k, v)

    # -- Steam apps --------------------------------------------------------
    def configured_apps(self) -> list[str]:
        """Steam apps (main/demo/playtest) with a real app id, pending edits included."""
        return [app for app in STEAM_APPS if not self.is_unset(steam_field(app, "app_id"))]

    def legacy_steam_keys(self) -> bool:
        """True if either file still has the pre-multi-app flat [steam] app_id / depot ids,
        which core.config refuses to load."""
        return any(k in self._data[which].get("steam", {})
                   for which in (BASE, LOCAL) for k in LEGACY_STEAM_KEYS)

    # -- validation --------------------------------------------------------
    def problems(self) -> dict[str, tuple[str, str]]:
        """{field: (level, message)}; level is 'error' (won't save) or 'warn'."""
        out: dict[str, tuple[str, str]] = {}
        for name, f in FIELDS.items():
            v = self.get(name).strip()
            if f.kind == "id" and v and not v.isdigit():
                out[name] = ("error", "Steam ids are numbers only.")
        apps = self.configured_apps()
        for app in STEAM_APPS:
            app_f, win_f, mac_f = (steam_field(app, k) for k in ("app_id", "depot_win_id", "depot_mac_id"))
            if app in apps:
                if win_f not in out and self.is_unset(win_f):
                    out[win_f] = ("warn", "Still a placeholder: use the depot id from Steamworks.")
            elif not (self.is_unset(win_f) and self.is_unset(mac_f)) and app_f not in out:
                out[app_f] = ("warn", "Depot ids are set but the app id is still a placeholder.")
        if not apps and "main_app_id" not in out:
            out["main_app_id"] = ("warn", "No Steam app configured yet: fill in at least one app.")
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

    @staticmethod
    def _table(doc, section: str, create: bool):
        """The tomlkit table for a (dotted) section, creating the path if asked."""
        cur = doc
        for part in section.split("."):
            nxt = cur.get(part)
            if nxt is None:
                if not create:
                    return None
                cur[part] = tomlkit.table()
                nxt = cur[part]
            cur = nxt
        return cur

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
            table = self._table(doc, f.section, create=False)
            if value == "":
                if table is not None and f.key in table:
                    del table[f.key]
                continue
            if table is None:
                table = self._table(doc, f.section, create=True)
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
