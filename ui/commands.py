"""Build the uetool command line from form state. Pure logic: no Qt, no subprocess.

CAPS mirrors which flags each subcommand accepts in core/cli.py. Flags a subcommand
doesn't take are simply left off the argv, so the form can stay one shared widget set.
"""
import shlex
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UETOOL = REPO / "uetool.py"

COMMANDS = ["release", "package", "archive", "upload", "notarize", "bootstrap", "bump"]

# Flags (form-field names) each subcommand accepts. Keep in sync with core/cli.py.
_COMMON = {"platform", "config", "dry_run"}
_BUILD = _COMMON | {"bump", "bootstrap", "clean"}
CAPS: dict[str, frozenset[str]] = {
    "bump": frozenset(_COMMON),
    "bootstrap": frozenset({"dry_run"}),
    "package": frozenset(_BUILD | {"custom_config"}),
    "upload": frozenset(_COMMON),
    "archive": frozenset({"platform", "dry_run"}),
    "notarize": frozenset(_COMMON),
    "release": frozenset(_BUILD | {"custom_config"}),
}

ERROR, WARN = "error", "warn"


@dataclass(frozen=True)
class BuildSpec:
    command: str = "release"
    platform: str = "win"
    build_config: str | None = None     # None -> let uetool.toml decide
    dry_run: bool = False
    bump: bool = True                   # False -> --no-bump
    bootstrap: bool = True              # False -> --no-bootstrap
    clean: bool = False
    custom_config: str | None = None


@dataclass(frozen=True)
class Issue:
    level: str       # ERROR blocks the run, WARN is informational
    message: str


def accepts(command: str, flag: str) -> bool:
    return flag in CAPS.get(command, frozenset())


def effective_bump(spec: BuildSpec) -> bool:
    """Will this run increment .build_number? bump/package/release do, and none of
    them is dry-run aware, so even --dry-run changes the tracked counter."""
    if spec.command == "bump":
        return True
    return accepts(spec.command, "bump") and spec.bump


def needs_notarize(spec: BuildSpec) -> bool:
    return spec.command == "notarize" or (spec.command == "release" and spec.platform == "mac")


def uses_clean(spec: BuildSpec) -> bool:
    return accepts(spec.command, "clean") and spec.clean


def for_dry_run(spec: BuildSpec) -> BuildSpec:
    """The spec a 'Dry run' button should run: same, but with the bump skipped so a
    rehearsal can't touch .build_number."""
    return replace(spec, dry_run=True, bump=False)


def validate(spec: BuildSpec, host: str, layers: list[str] | None = None) -> list[Issue]:
    """Problems that should stop (ERROR) or merely flag (WARN) a run.

    host is 'win' or 'mac' (core.paths.host_platform()); layers are the available
    Config/Custom/* names, or None to skip the existence check.
    """
    out: list[Issue] = []
    if spec.command not in CAPS:
        return [Issue(ERROR, f"Unknown command '{spec.command}'.")]
    if spec.platform not in ("win", "mac"):
        out.append(Issue(ERROR, f"Platform must be win or mac, not '{spec.platform}'."))

    if spec.custom_config and accepts(spec.command, "custom_config"):
        if spec.command == "release":
            out.append(Issue(ERROR, "--custom-config is not allowed with release, which "
                             "uploads to Steam. Use package + archive for a non-Steam build."))
        elif layers is not None and spec.custom_config not in layers:
            out.append(Issue(ERROR, f"No Config/Custom/{spec.custom_config} folder in the project."))

    if needs_notarize(spec) and host != "mac":
        out.append(Issue(ERROR, "Notarization needs macOS (codesign + notarytool); "
                         f"this host is {host}."))
    elif spec.command in ("package", "release") and spec.platform == "mac" and host != "mac":
        out.append(Issue(ERROR, "A macOS build can only be made on a Mac."))

    if spec.dry_run and effective_bump(spec):
        out.append(Issue(ERROR, "A dry run still bumps .build_number (the version step isn't "
                         "dry-run aware). Turn off Bump for a dry run."))
    if spec.command == "bump" and spec.dry_run:
        out.append(Issue(ERROR, "bump has no dry-run mode: it always increments .build_number."))
    return out


def blocking(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == ERROR]


def clean_warning(spec: BuildSpec) -> str | None:
    """Confirmation text when the run would delete build output, else None."""
    if not uses_clean(spec) or spec.dry_run:
        return None
    return ("Clean build deletes Binaries, Intermediate, Saved/Cooked and the staged "
            f"{spec.platform} output, then rebuilds and recooks from scratch. "
            "This can take a long time. Continue?")


def build_argv(spec: BuildSpec, project: Path | str, *, python: str | None = None,
               script: Path | str | None = None) -> list[str]:
    argv = [python or sys.executable, str(script or UETOOL), "-P", str(project), spec.command]
    if accepts(spec.command, "platform"):
        argv += ["--platform", spec.platform]
    if accepts(spec.command, "config") and spec.build_config:
        argv += ["--config", spec.build_config]
    if accepts(spec.command, "bump") and not spec.bump:
        argv.append("--no-bump")
    if accepts(spec.command, "bootstrap") and not spec.bootstrap:
        argv.append("--no-bootstrap")
    if accepts(spec.command, "clean") and spec.clean:
        argv.append("--clean")
    if accepts(spec.command, "custom_config") and spec.custom_config:
        argv += ["--custom-config", spec.custom_config]
    if accepts(spec.command, "dry_run") and spec.dry_run:
        argv.append("--dry-run")
    return argv


def display(spec: BuildSpec, project: Path | str) -> str:
    """Copy-pasteable form of the command, with the launcher shortened to `uetool`."""
    argv = build_argv(spec, project)[2:]  # drop interpreter + script
    if sys.platform.startswith("win"):
        return "uetool " + subprocess.list2cmdline(argv)
    return "uetool " + shlex.join(argv)


def custom_layers(project: Path | str) -> list[str]:
    """Names of the Config/Custom/<name> folders available in the project."""
    root = Path(project) / "Config" / "Custom"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
