"""Open the user's own terminal on a command (for the one-time interactive Steam login).

The UI never types a password for them: they enter it, and Steam Guard, in a real
terminal. Returns the argv to spawn, or None when the platform has no known terminal
(the caller then copies the command to the clipboard instead).
"""
import shlex
import subprocess


def shell_line(argv: list[str], host: str) -> str:
    return subprocess.list2cmdline(argv) if host == "win" else shlex.join(argv)


def terminal_argv(argv: list[str], host: str) -> list[str] | None:
    line = shell_line(argv, host)
    if host == "mac":
        esc = line.replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", f'tell application "Terminal" to do script "{esc}"',
                "-e", 'tell application "Terminal" to activate']
    if host == "win":
        return ["cmd", "/c", "start", "uetool login", "cmd", "/k", line]
    return None
