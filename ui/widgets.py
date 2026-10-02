"""Small shared widgets and the app stylesheet."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel

STYLE = """
QLabel[role="muted"] { color: #6b6b6b; }
QLabel[role="badge-pass"] { background:#e3f4e1; color:#1e6b2a; border-radius:4px; padding:2px 8px; }
QLabel[role="badge-fix"]  { background:#fbf0d2; color:#8a5a00; border-radius:4px; padding:2px 8px; }
QLabel[role="badge-fail"] { background:#fbe3e1; color:#a0281f; border-radius:4px; padding:2px 8px; }
QLabel[role="badge-na"]   { background:#ececea; color:#6b6b6b; border-radius:4px; padding:2px 8px; }
QLabel[role="warn-box"]   { background:#fbf0d2; color:#8a5a00; border-radius:6px; padding:8px; }
QLabel[role="err-box"]    { background:#fbe3e1; color:#a0281f; border-radius:6px; padding:8px; }
QLabel[role="err"]        { color:#a0281f; }
QLabel[role="warn"]       { color:#8a5a00; }
QPlainTextEdit[role="mono"], QLineEdit[role="mono"] {
    font-family: Menlo, Consolas, monospace; background:#f4f4f2; color:#222;
    border:1px solid #ddd; border-radius:6px; }
QLineEdit[invalid="true"] { border:1px solid #d0463b; }
QPushButton[role="primary"] { background:#1f6feb; color:white; border:none; border-radius:5px; padding:6px 16px; }
QPushButton[role="primary"]:disabled { background:#9db9e8; }
"""

BADGE_TEXT = {"pass": "Pass", "fix": "Fix", "fail": "Fail", "na": "n/a"}


def muted(text="") -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "muted")
    lab.setWordWrap(True)
    return lab


def set_role(widget, role: str) -> None:
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def badge(status: str) -> QLabel:
    lab = QLabel(BADGE_TEXT[status])
    lab.setProperty("role", f"badge-{status}")
    lab.setFixedWidth(52)
    lab.setAlignment(Qt.AlignCenter)
    return lab


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#e2e2e0;")
    return f
