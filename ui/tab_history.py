"""History tab (read-only): current version, staged builds and archives on disk."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import history
from .context import Context
from .widgets import muted


class HistoryTab(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.entries: list[history.Entry] = []
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        self.version = QLabel("—")
        self.version.setStyleSheet("font-size:20px; font-weight:600;")
        self.counter = QLabel("—")
        self.ini = QLabel("—")
        for label, w in (("Last built version", self.version), ("Build counter", self.counter),
                         ("DefaultGame.ini version", self.ini)):
            col = QVBoxLayout()
            col.addWidget(muted(label))
            col.addWidget(w)
            top.addLayout(col)
            top.addSpacing(32)
        top.addStretch()
        outer.addLayout(top)
        outer.addWidget(muted("Uploads are never promoted automatically: set a build live on a branch "
                              "in Steamworks."))

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Kind", "Platform", "Size", "Modified"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 5):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        outer.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.reveal = QPushButton("Reveal in folder")
        self.reveal.clicked.connect(self.reveal_selected)
        self.steamworks = QPushButton("Open Steamworks builds page")
        self.steamworks.clicked.connect(self.open_steamworks)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        for b in (self.reveal, self.steamworks, refresh):
            btns.addWidget(b)
        btns.addStretch()
        outer.addLayout(btns)

        ctx.project_changed.connect(self.refresh)
        ctx.run_finished.connect(self.refresh)
        ctx.config_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        self.entries = []
        if not self.ctx.project:
            return
        info = history.collect(self.ctx.project, self.ctx.cfg)
        self.version.setText(info.version or "—")
        self.counter.setText(str(info.counter) if info.counter is not None else "—")
        self.ini.setText(info.ini_version or "—")
        self.entries = info.entries
        self.table.setRowCount(len(info.entries))
        for r, e in enumerate(info.entries):
            for c, text in enumerate((e.name, e.kind, e.platform, history.human_size(e.size),
                                      e.modified.strftime("%Y-%m-%d %H:%M"))):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.update_buttons()

    def update_buttons(self):
        self.reveal.setEnabled(bool(self.table.selectedItems()))
        self.steamworks.setEnabled(bool(self.ctx.cfg and history.builds_url(self.ctx.cfg.get("app_id"))))

    def reveal_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            e = self.entries[rows[0].row()]
            folder = e.path if e.path.is_dir() else e.path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_steamworks(self):
        url = history.builds_url(self.ctx.cfg.get("app_id"))
        if url:
            QDesktopServices.openUrl(QUrl(url))
