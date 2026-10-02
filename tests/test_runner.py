import sys
import textwrap
import time

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from ui.runner import Runner, child_env, descendants


def run_to_end(runner, argv, cancel_after_ms=None, cwd=None, env=None, timeout_ms=15000):
    out, result = [], {}
    loop = QEventLoop()
    runner.output.connect(out.append)
    runner.finished.connect(lambda c, x: (result.update(code=c, cancelled=x), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    if cancel_after_ms is not None:
        QTimer.singleShot(cancel_after_ms, runner.cancel)
    runner.start(argv, cwd=cwd, env=env)
    loop.exec()
    return "".join(out), result


def test_streams_unbuffered_and_exit_code(app, tmp_path):
    script = tmp_path / "s.py"
    script.write_text("import os,time\nprint('one', os.environ['X'])\ntime.sleep(.3)\nprint('two')\nraise SystemExit(3)\n")
    out, res = run_to_end(Runner(), [sys.executable, str(script)], env={"X": "val"})
    assert "one val" in out and "two" in out and res == {"code": 3, "cancelled": False}


def test_failed_to_start(app):
    out, res = run_to_end(Runner(), ["/nonexistent/binary"])
    assert "Failed to start" in out and res["code"] == -1


def test_child_env_unbuffered_and_skips_empty():
    e = child_env({"A": "1", "B": ""})
    assert e["PYTHONUNBUFFERED"] == "1" and e["A"] == "1" and "B" not in e


def test_descendants():
    ps = "10 1\n11 10\n12 11\n13 10\n20 1\n"
    assert sorted(descendants(ps, 10)) == [11, 12, 13]


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX signals")
def test_cancel_lets_finally_restore_the_file(app, tmp_path):
    """The reason cancel uses SIGINT: a stamped file must be restored on cancel."""
    target = tmp_path / "ini"
    target.write_text("v1.0.0")
    script = tmp_path / "s.py"
    script.write_text(textwrap.dedent(f"""
        import pathlib, subprocess, sys
        p = pathlib.Path({str(target)!r})
        p.write_text("v1.0.0.9")
        print("stamped", flush=True)
        try:
            subprocess.run([sys.executable, "-c", "import time; time.sleep(60)"])
        finally:
            p.write_text("v1.0.0")
    """))
    out, res = run_to_end(Runner(grace_ms=10000), [sys.executable, str(script)], cancel_after_ms=1500)
    assert res["cancelled"] is True
    assert target.read_text() == "v1.0.0"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX signals")
def test_cancel_kills_stubborn_child_after_grace(app, tmp_path):
    script = tmp_path / "s.py"
    script.write_text("import signal,time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\nprint('up',flush=True)\ntime.sleep(60)\n")
    t0 = time.time()
    out, res = run_to_end(Runner(grace_ms=700), [sys.executable, str(script)], cancel_after_ms=800)
    assert res["cancelled"] and time.time() - t0 < 6 and "killing" in out
