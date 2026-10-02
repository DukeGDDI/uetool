"""Config tab: edits uetool.toml / uetool.local.toml, plus keychain secrets."""
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from . import keychain
from .configstore import BASE, LOCAL, ProjectConfig
from .context import Context
from .widgets import muted, set_role

BUILD_CONFIGS = ["Shipping", "Development", "DebugGame", "Test"]


class SecretRow(QWidget):
    """Write-only password box backed by the keychain."""

    def __init__(self, kind: str, ctx: Context, account_of):
        super().__init__()
        self.kind, self.ctx, self.account_of = kind, ctx, account_of
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.save_btn = QPushButton("Save to keychain")
        self.clear_btn = QPushButton("Remove")
        self.status = muted()
        row.addWidget(self.edit, 1)
        row.addWidget(self.save_btn)
        row.addWidget(self.clear_btn)
        self.save_btn.clicked.connect(self.save)
        self.clear_btn.clicked.connect(self.clear)
        self.edit.textChanged.connect(self.update_state)

    def update_state(self):
        acct = self.account_of()
        ok = keychain.available()
        stored = bool(acct) and ok and keychain.has(self.kind, acct)
        self.edit.setPlaceholderText("Stored in your OS keychain" if stored else
                                     ("Not set" if ok else "No keychain available"))
        self.edit.setEnabled(ok and bool(acct) and self.isEnabled())
        self.save_btn.setEnabled(bool(self.edit.text()) and bool(acct) and ok)
        self.clear_btn.setEnabled(stored)
        self.status.setText("" if acct else "Enter the account name first.")

    def save(self):
        keychain.set(self.kind, self.account_of(), self.edit.text())
        self.edit.clear()
        self.update_state()
        self.ctx.config_changed.emit()

    def clear(self):
        keychain.delete(self.kind, self.account_of())
        self.update_state()
        self.ctx.config_changed.emit()


class ConfigTab(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.edits: dict[str, QLineEdit | QComboBox] = {}
        self.msgs: dict[str, QLabel] = {}
        self._loading = False

        page = QWidget()
        outer = QVBoxLayout(page)

        shared = QGroupBox(f"{BASE} (committed)")
        f1 = QFormLayout(shared)
        self._add(f1, "build_config", "Build configuration", combo=True)
        self._add(f1, "stage_dir", "Stage directory")
        self._add(f1, "app_id", "Steam app id")
        self._add(f1, "depot_win_id", "Windows depot id")
        self._add(f1, "depot_mac_id", "macOS depot id")
        outer.addWidget(shared)

        local = QGroupBox(f"{LOCAL} (this machine only)")
        f2 = QFormLayout(local)
        self._add(f2, "ue_root", "Unreal Engine root", browse=True)
        self._add(f2, "steam_user", "Steam build account")
        self.steam_pw = SecretRow("steam", ctx, lambda: self.value("steam_user"))
        f2.addRow("Steam password", self.steam_pw)
        self.apple_box = QWidget()
        f3 = QFormLayout(self.apple_box)
        f3.setContentsMargins(0, 0, 0, 0)
        self._add(f3, "apple_id", "Apple ID")
        self._add(f3, "team_id", "Apple team ID")
        self._add(f3, "signing_identity", "Signing identity")
        self.apple_pw = SecretRow("apple", ctx, lambda: self.value("apple_id"))
        f3.addRow("App-specific password", self.apple_pw)
        f2.addRow(self.apple_box)
        self.apple_note = muted("Apple notarization settings apply to macOS builds only.")
        f2.addRow(self.apple_note)
        outer.addWidget(local)

        machine = QGroupBox("This machine (UI setting, passed to every run)")
        f4 = QFormLayout(machine)
        row = QHBoxLayout()
        self.sdk = QLineEdit()
        self.sdk.setPlaceholderText("UETOOL_STEAM_SDK: folder containing steamcmd")
        self.sdk.editingFinished.connect(lambda: self._set_sdk(self.sdk.text()))
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_sdk)
        row.addWidget(self.sdk, 1)
        row.addWidget(b)
        f4.addRow("Steam SDK folder", row)
        outer.addWidget(machine)

        btns = QHBoxLayout()
        self.revert_btn = QPushButton("Revert")
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("role", "primary")
        self.status = muted("Comments in the files are preserved. Passwords never touch these files.")
        self.revert_btn.clicked.connect(self.revert)
        self.save_btn.clicked.connect(self.save)
        btns.addWidget(self.revert_btn)
        btns.addWidget(self.save_btn)
        btns.addWidget(self.status, 1)
        outer.addLayout(btns)
        outer.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(page)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)

        ctx.project_changed.connect(self.load)
        ctx.config_changed.connect(self._on_external_change)
        ctx.run_state_changed.connect(lambda _: self.update_state())
        ctx.goto_tab.connect(self._focus)
        self.load()

    # -- construction helpers ----------------------------------------------
    def _add(self, form: QFormLayout, name: str, label: str, combo=False, browse=False):
        if combo:
            w = QComboBox()
            w.setEditable(True)
            w.addItems(BUILD_CONFIGS)
            w.currentTextChanged.connect(lambda t, n=name: self._edited(n, t))
        else:
            w = QLineEdit()
            w.textChanged.connect(lambda t, n=name: self._edited(n, t))
        self.edits[name] = w
        msg = QLabel()
        msg.setWordWrap(True)
        self.msgs[name] = msg
        box = QVBoxLayout()
        box.setSpacing(2)
        if browse:
            r = QHBoxLayout()
            r.addWidget(w, 1)
            b = QPushButton("Browse…")
            b.clicked.connect(lambda: self._browse(name))
            r.addWidget(b)
            box.addLayout(r)
        else:
            box.addWidget(w)
        box.addWidget(msg)
        form.addRow(label, box)

    def value(self, name: str) -> str:
        w = self.edits[name]
        return (w.currentText() if isinstance(w, QComboBox) else w.text()).strip()

    # -- state -------------------------------------------------------------
    def load(self):
        cfg = self.ctx.cfg
        self._loading = True
        for name, w in self.edits.items():
            v = cfg.get(name) if cfg else ""
            if isinstance(w, QComboBox):
                w.setCurrentText(v)
            else:
                w.setText(v)
        self.sdk.setText(self.ctx.steam_sdk)
        self._loading = False
        self.update_state()

    def _on_external_change(self):
        # A Setup-tab fix or secret change happened; reflect it without losing typing.
        if self.ctx.cfg and not self.ctx.cfg.dirty:
            self.load()
        else:
            self.update_state()

    def _edited(self, name: str, text: str):
        if self._loading or not self.ctx.cfg:
            return
        self.ctx.cfg.set(name, text)
        self.update_state()

    def update_state(self):
        cfg: ProjectConfig | None = self.ctx.cfg
        enabled = cfg is not None and not self.ctx.running
        problems = cfg.problems() if cfg else {}
        for name, w in self.edits.items():
            w.setEnabled(enabled)
            lvl, text = problems.get(name, ("", ""))
            w.setProperty("invalid", lvl == "error" or lvl == "warn")
            w.style().unpolish(w)
            w.style().polish(w)
            msg = self.msgs[name]
            msg.setText(text)
            set_role(msg, "err" if lvl == "error" else "warn")
        mac = self.ctx.host == "mac"
        self.apple_box.setEnabled(enabled and mac)
        self.apple_note.setVisible(not mac)
        for row in (self.steam_pw, self.apple_pw):
            row.setEnabled(enabled)
            row.update_state()
        dirty = bool(cfg and cfg.dirty)
        self.save_btn.setEnabled(enabled and dirty and cfg.can_save())
        self.revert_btn.setEnabled(enabled and dirty)
        if self.ctx.running:
            self.status.setText("Locked while a run is in progress.")
        elif dirty:
            self.status.setText("Unsaved changes.")
        else:
            self.status.setText("Comments in the files are preserved. Passwords never touch these files.")

    def save(self):
        try:
            written = self.ctx.cfg.save()
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return
        self.ctx.config_changed.emit()
        self.status.setText("Saved " + (", ".join(p.name for p in written) or "nothing to save"))

    def revert(self):
        self.ctx.cfg.revert()
        self.load()

    # -- misc --------------------------------------------------------------
    def _browse(self, name: str):
        d = QFileDialog.getExistingDirectory(self, "Choose folder", self.value(name) or str(self.ctx.project))
        if d:
            self.edits[name].setText(d)

    def _browse_sdk(self):
        d = QFileDialog.getExistingDirectory(self, "Folder containing steamcmd (or the Steamworks SDK)",
                                             self.ctx.steam_sdk or str(self.ctx.project))
        if d:
            self.sdk.setText(d)
            self._set_sdk(d)

    def _set_sdk(self, text: str):
        if text.strip() != self.ctx.steam_sdk:
            self.ctx.steam_sdk = text

    def _focus(self, tab: str, field: str):
        if tab == "Config" and field in self.edits:
            self.edits[field].setFocus()
