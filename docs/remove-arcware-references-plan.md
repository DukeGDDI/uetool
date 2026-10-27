# Remove ArcWare / pixel-streaming references — uetool plan

## Context
ArcWare cloud pixel streaming is retired. uetool has **no PixelStreaming2-specific code** —
only two *generic* features whose docs cited ArcWare as the example:
- **`--custom-config`** (an ini-layer overlay via `core/inioverlay.py`) — **load-bearing**: the
  Steam **Demo** build uses `--custom-config Demo`.
- **`archive`** (zip a staged build for non-Steam distribution) — generic (itch.io, direct
  download).

Both features **stay**. This change only strips the ArcWare *wording/examples*.

## Changes
- `core/cli.py` — usage synopsis `[--custom-config Arcware]` → `[--custom-config Demo]`; the
  `--custom-config` help drops "Arcware (pixel streaming)" for the Demo example; the `archive`
  help "non-Steam distribution (e.g. pixel streaming)" → "(e.g. itch.io, a direct download)".
- `core/archive.py` — module docstring: drop "ArcWare pixel streaming", keep "itch.io, a plain
  download".
- `ui/mockup.py` — the design-mockup layer combo `["none", "Arcware"]` → `["none", "Demo"]`.
- `README.md` — rewrite the "Non-Steam distribution (`archive`)" and "Per-host ini layers
  (`--custom-config`)" sections to use **Demo** as the example and generic non-Steam framing;
  delete the "ArcWare pixel streaming / Pixel Streaming plugin" paragraph.

## Keep (do NOT remove)
- `--custom-config` and `core/inioverlay.py` — the Demo build needs them.
- `archive` and `core/archive.py` — generic non-Steam distribution.

## Verify
- `.venv/bin/python -m pytest -q` stays green.
- `grep -riE "arcware|pixel ?stream" core ui README.md uetool.toml.example` returns nothing
  (this plan doc aside).

## Out of scope
- The D6scend game-project removal (PixelStreaming2 plugin, `Config/Custom/Arcware/`, the
  `FD6scendModule` unfocused-audio workaround) — separate doc in the D6scend repo at
  `Docs/Design/2026-10-27-remove-pixelstreaming2-plan.md`.
