"""Apply a Config/Custom/<name>/ ini layer by folding it into the base config for a build.

Unreal has a native mechanism for exactly this — Config/Custom/<name>/Default*.ini layered
above Config/Default*.ini when -CustomConfig=<name> is passed — and it CANNOT work in a
packaged Shipping build made with a Launcher (installed) engine:

  * UBT bakes the CUSTOM_CONFIG define only when the target does not use the shared build
    environment, and TargetRules.BuildEnvironment is forced to Shared whenever the engine
    is installed.
  * Forcing BuildEnvironment = Unique to obtain the define is rejected outright —
    "Targets with a unique build environment cannot be built with an installed engine."
  * The command-line fallback is compiled out of Shipping:
    ALLOW_INI_OVERRIDE_FROM_COMMANDLINE is (UE_SERVER || !UE_BUILD_SHIPPING).

So FConfigCacheIni::GetCustomConfigString() returns "" at runtime and nothing ever reads
the layer, even though UAT stages the files quite happily. The failure is silent: the
package looks correct and every override simply does nothing.

This module sidesteps all of that by merging the layer into the base ini for the duration
of the cook and restoring the originals afterwards — the same borrow-and-restore shape
version.stamp() already uses for ProjectVersion. What ships is an ordinary
Config/Default*.ini needing no runtime flag and no engine cooperation.

Scope: only <project>/Config/Custom/<name>/Default*.ini is merged. Platform sub-layers
(Config/<Platform>/Custom/<name>/) are not handled; add them here if a project needs one.
"""
import re
from pathlib import Path

_SECTION_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")


def _parse_layer(text: str):
    """Ordered section list plus {section: [(key, line)]} for an overlay file.

    Comments and blanks are dropped — they document the layer, not the merged output. A
    key retains any UE array prefix (+ - . !) as part of its name, so a '+Foo=' line can
    never silently replace a plain 'Foo='.
    """
    order: list[str] = []
    sections: dict[str, list[tuple[str, str]]] = {}
    current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if _SECTION_RE.match(line):
            current = line
            if current not in sections:
                sections[current] = []
                order.append(current)
            continue
        if current is None or "=" not in line:
            continue
        sections[current].append((line.split("=", 1)[0].strip(), line))

    return order, sections


def _merge(base_text: str, order, sections, marker: str) -> str:
    """Return base_text with the overlay applied: matching keys replaced in place,
    new keys appended to their section, absent sections appended at the end."""
    pending = {section: list(kvs) for section, kvs in sections.items()}
    out: list[str] = []
    current = None

    def flush(section):
        """Emit overlay keys for `section` that the base file did not already contain."""
        leftovers = pending.get(section)
        if leftovers:
            out.append(marker)
            out.extend(line for _, line in leftovers)
            pending[section] = []

    for raw in base_text.splitlines():
        stripped = raw.strip()

        if _SECTION_RE.match(stripped):
            flush(current)              # close out the section being left
            current = stripped
            out.append(raw)
            continue

        if current in pending and "=" in stripped and not stripped.startswith((";", "#")):
            key = stripped.split("=", 1)[0].strip()
            replacement = next((l for k, l in pending[current] if k == key), None)
            if replacement is not None:
                out.append(replacement)
                pending[current] = [(k, l) for k, l in pending[current] if k != key]
                continue

        out.append(raw)

    flush(current)                      # the final section

    for section in order:               # sections the base file never had
        if pending.get(section):
            out.extend(["", section, marker])
            out.extend(line for _, line in pending[section])
            pending[section] = []

    return "\n".join(out) + "\n"


def apply(project_root: Path, name: str, dry_run: bool) -> dict[Path, str]:
    """Merge every Config/Custom/<name>/Default*.ini into its base counterpart.

    Returns {base_file: original_text} for restore(); empty on a dry run.
    """
    layer_dir = project_root / "Config" / "Custom" / name
    if not layer_dir.is_dir():
        raise SystemExit(f"No custom config layer at {layer_dir}")

    layer_files = sorted(layer_dir.glob("Default*.ini"))
    if not layer_files:
        raise SystemExit(f"No Default*.ini files in {layer_dir}")

    marker = f"; uetool: merged from Config/Custom/{name}/ for this build only"
    originals: dict[Path, str] = {}

    for layer_file in layer_files:
        base_file = project_root / "Config" / layer_file.name
        if not base_file.is_file():
            raise SystemExit(
                f"{layer_file.name} has no base counterpart at {base_file}. A custom layer "
                "may only override settings the base config also ships."
            )

        order, sections = _parse_layer(layer_file.read_text(encoding="utf-8"))
        base_text = base_file.read_text(encoding="utf-8")
        key_count = sum(len(v) for v in sections.values())
        print(f"$ merge {layer_file.relative_to(project_root)} -> "
              f"{base_file.relative_to(project_root)} ({key_count} key(s))")

        if not dry_run:
            originals[base_file] = base_text
            base_file.write_text(_merge(base_text, order, sections, marker), encoding="utf-8")

    return originals


def restore(originals: dict[Path, str]) -> None:
    """Put the base config files back byte-for-byte. Safe to call with {}."""
    for path, text in originals.items():
        path.write_text(text, encoding="utf-8")
