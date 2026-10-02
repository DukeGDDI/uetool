"""Run the real uetool CLI as a child process and stream its output.

Cancel is deliberately two-stage. uetool stamps the build number into
Config/DefaultGame.ini for the cook and restores it in a `finally` block, so the
child must be allowed to unwind. A plain SIGTERM (what QProcess.terminate sends) kills
Python without running `finally`; SIGINT raises KeyboardInterrupt, which does. So:
SIGINT now, kill after a grace period. Windows has no equivalent for a console child
started without its own process group, so there it terminates and then kills; the
caller's "left stamped?" check (projectstate) is the safety net.
"""
import codecs
import os
import signal
import subprocess
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

GRACE_MS = 20_000


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the child: ours, unbuffered, plus the per-run extras."""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update({k: v for k, v in (extra or {}).items() if v})
    return env


def descendants(ps_output: str, root: int) -> list[int]:
    """All descendant pids of root, from `ps -A -o pid=,ppid=` output."""
    kids: dict[int, list[int]] = {}
    for line in ps_output.splitlines():
        parts = line.split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            pid, ppid = map(int, parts)
            kids.setdefault(ppid, []).append(pid)
    out, stack = [], [root]
    while stack:
        for k in kids.get(stack.pop(), []):
            out.append(k)
            stack.append(k)
    return out


def _snapshot_descendants(pid: int) -> list[int]:
    if os.name == "nt":
        return []
    try:
        ps = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True,
                            text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return descendants(ps, pid)


def _signal_all(pids: list[int], sig: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (OSError, ProcessLookupError):
            pass


class Runner(QObject):
    output = Signal(str)
    started = Signal()
    finished = Signal(int, bool)   # exit code, was cancelled

    def __init__(self, parent=None, grace_ms: int = GRACE_MS):
        super().__init__(parent)
        self.grace_ms = grace_ms
        self._proc: QProcess | None = None
        self._cancelled = False
        self._kids: list[int] = []
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._killer = QTimer(self, singleShot=True)
        self._killer.timeout.connect(self._force_kill)

    @property
    def running(self) -> bool:
        return self._proc is not None

    def start(self, argv: list[str], cwd: str | None = None, env: dict[str, str] | None = None):
        if self._proc:
            raise RuntimeError("A run is already in progress.")
        self._cancelled = False
        self._decoder.reset()
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        if cwd:
            proc.setWorkingDirectory(cwd)
        penv = QProcessEnvironment()
        for k, v in child_env(env).items():
            penv.insert(k, v)
        proc.setProcessEnvironment(penv)
        proc.readyRead.connect(self._read)
        proc.finished.connect(self._done)
        proc.errorOccurred.connect(self._error)
        self._proc = proc
        proc.start(argv[0], argv[1:])
        self.started.emit()

    def _read(self):
        if self._proc:
            text = self._decoder.decode(bytes(self._proc.readAll()))
            if text:
                self.output.emit(text)

    def _error(self, err):
        if err == QProcess.FailedToStart and self._proc:
            self.output.emit(f"Failed to start: {self._proc.errorString()}\n")
            self._finish(-1)

    def _done(self, code, _status):
        self._read()
        self._finish(code)

    def _finish(self, code: int):
        proc, self._proc = self._proc, None
        self._killer.stop()
        if proc is None:
            return
        if self._cancelled:   # sweep up anything the child left behind (UAT, cooker…)
            _signal_all(self._kids, getattr(signal, "SIGTERM", signal.SIGINT))
        proc.deleteLater()
        self.finished.emit(code, self._cancelled)

    def cancel(self):
        if not self._proc or self._cancelled:
            return
        self._cancelled = True
        pid = int(self._proc.processId())
        self.output.emit("\n[cancel] asking uetool to stop so it can restore your files…\n")
        self._kids = _snapshot_descendants(pid)
        if os.name == "nt":
            self._proc.terminate()
        else:
            _signal_all([pid], signal.SIGINT)
        self._killer.start(self.grace_ms)

    def _force_kill(self):
        if not self._proc:
            return
        self.output.emit("[cancel] still running after the grace period: killing.\n")
        pid = int(self._proc.processId())
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        else:
            _signal_all(self._kids, signal.SIGKILL)
        self._proc.kill()
