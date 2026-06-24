# uetool

A small, cross-platform CLI that **bumps**, **packages**, **signs/notarizes**, and
**uploads to Steam** any Unreal Engine project — without living inside the project.
It is a thin orchestration layer: Unreal's `RunUAT` does the cooking/packaging,
Apple's `codesign`/`notarytool` do macOS signing, and `steamcmd` does the upload.
`uetool` just wires them together with consistent versioning and config.

Install it once, put it on your `PATH`, and point it at any UE project.

---

## Install

Clone or download-and-extract this repo anywhere, then add the folder to `PATH`:

```bash
git clone <repo-url> ~/Workspace/uetool
# add ~/Workspace/uetool to PATH (zsh example):
echo 'export PATH="$HOME/Workspace/uetool:$PATH"' >> ~/.zshrc
```

Set the **machine-wide** environment variables once (these are shared by every
project on the machine):

```bash
export UETOOL_PYTHON=python3.13        # a Python 3.11+ interpreter (needs stdlib tomllib)
export UETOOL_STEAM_SDK="$HOME/steamcmd" # folder containing steamcmd (standalone or full SDK)
```

Secrets are environment variables too, and are never written to any file:

```bash
export UETOOL_STEAM_PASSWORD=...        # optional; prefer steamcmd's cached sentry
export UETOOL_APPLE_APP_PASSWORD=...     # macOS notarization only
```

> **Windows:** add the `uetool` folder to `PATH`; `uetool.cmd` works from both
> `cmd.exe` and PowerShell. Set `UETOOL_PYTHON`/`UETOOL_STEAM_SDK` via *System →
> Environment Variables* (or `setx`).
>
> **Important (Windows):** also add the **steamcmd folder itself to `PATH`** (e.g.
> `C:\steamcmd`). On Windows `steamcmd.exe` needs its own directory on `PATH` to
> locate its runtime DLLs; without it, uploads can fail to start even though
> `UETOOL_STEAM_SDK` points at the right place. So on a PC you set the steamcmd
> folder in **two** spots: `UETOOL_STEAM_SDK` (so uetool finds the binary) *and*
> `PATH` (so the binary finds its DLLs).

---

## Per-project setup

At the **root of your UE project** (next to `YourGame.uproject`):

1. Copy the two config templates from this repo and fill them in:
   - `uetool.toml` — **committed**, non-secret (app id, depot ids, build config).
   - `uetool.local.toml` — **untracked**, per-machine (engine path, Steam user, Apple ids).
2. Add to the project's ignore rules (`.gitignore` / `.dvignore`):
   ```
   uetool.local.toml
   .version
   .uetool/
   ```
   Keep `.build_number` **tracked** — it's the monotonic counter and must persist.

The project name is auto-detected from the single `*.uproject` in the folder, so
there is nothing project-specific to hardcode.

---

## Usage

```
usage: uetool [-P PATH] {bump,package,upload,notarize,release} ...
              [--platform win|mac] [--config Shipping] [--dry-run] [--no-bump]
```

Run from inside the project, or point at it with `-P`:

```bash
uetool bump                              # advance the build counter only (writes .version)
uetool package --platform mac            # bump + RunUAT package
uetool package --platform mac --no-bump  # package without bumping
uetool notarize                          # sign + notarize + staple the staged macOS .app
uetool upload --platform mac             # push the staged build to Steam
uetool release --platform mac            # bump -> package -> [notarize on mac] -> upload
uetool -P ~/games/MyGame release         # operate on a project elsewhere
```

`--dry-run` prints every external command without executing it (and still
validates config) — the safe way to verify wiring with no engine or Steam access.

Uploading **never** auto-promotes a build to a live Steam branch; that stays a
deliberate step on the Steamworks site.

---

## Configuration model

Three sources, lowest precedence first: `uetool.toml` < `uetool.local.toml` < env.

| Where | Scope | Holds |
|-------|-------|-------|
| **Env vars** (set once on the machine) | machine-wide | `UETOOL_PYTHON`, `UETOOL_STEAM_SDK`, secret passwords; optional overrides (`UETOOL_UE_ROOT`, `UETOOL_STEAM_USER`, `UETOOL_APPLE_*`, `UETOOL_STEAMCMD`) |
| **`uetool.toml`** (committed, project root) | per-project | `app_id`, depot ids, `build_config`, stage subdirs |
| **`uetool.local.toml`** (untracked, project root) | per-project, per-machine | `ue_root`, Steam `user`, Apple `apple_id`/`team_id`/`signing_identity` |

Files the tool reads/writes at the **project root**:

| Path | Tracked? | Purpose |
|------|----------|---------|
| `uetool.toml` | yes | committed config |
| `uetool.local.toml` | no | per-machine config |
| `.build_number` | **yes** | monotonic build counter |
| `.version` | no | last stamped `vX.Y.Z.N` (generated) |
| `.uetool/` | no | rendered VDFs, notarization zip, steamcmd output (generated) |

`steamcmd` is resolved from `UETOOL_STEAM_SDK` per-OS (standalone `steamcmd.sh`/
`.exe` or the SDK's `ContentBuilder/builder_*`), falling back to `steamcmd` on PATH.

---

## How it works

```
ProjectVersion in Config/DefaultGame.ini   (authored "vX.Y.Z" by hand; never carries .N in source)
        │  bump(): increment .build_number (monotonic); write .version = "vX.Y.Z.N"
        ▼            (DefaultGame.ini is NOT modified by bump)
   <project>/.version  ("vX.Y.Z.N")  ── full build label = base + counter
        │  package(): stamp "vX.Y.Z.N" into the .ini -> RunUAT -cook -build -stage -pak
        │             (NO -archive) -> restore the base "vX.Y.Z" (finally-guarded)
        ▼
   Saved/StagedBuilds/<Windows|Mac>/   (self-contained build embedding vX.Y.Z.N;
                                        source DefaultGame.ini stays vX.Y.Z)
        │  notarize() [mac only]: sign inside-out -> notarytool submit -> staple
        │  upload(): render VDFs into .uetool/, run steamcmd +run_app_build
        ▼
   Steam build (labeled "vX.Y.Z.N"), NOT set live automatically
```

### Repo layout
```
uetool/
├── uetool            bash launcher (macOS/Linux)
├── uetool.cmd        Windows launcher (works in cmd AND PowerShell)
├── uetool.py         Python entry (sets sys.path, runs core.cli)
└── core/             the package (host detection, config, version, package, steam, notarize)
    └── steam/        VDF templates (@TOKEN@ placeholders)
```

The launcher picks the interpreter (`UETOOL_PYTHON`) and runs `uetool.py`, which
resolves the project root (`-P`, default cwd) and dispatches to `core`.

---

## Platform notes (hard-won)

- **Deliver from `-stage`, not `-archive`.** On macOS, UE's `-archive` step copies
  the bare `Binaries/.app` (no cooked content) instead of the staged bundle, so the
  archived app dies at launch with *"Failed to open descriptor file"*. The reliable,
  self-contained build is always the `-stage` output under `Saved/StagedBuilds/`.
- **Sign macOS bundles inside-out, not with `--deep`.** `codesign --deep` misses
  UE's embedded dylibs (`libtbb`, `libonnxruntime`, …), so notarization returns
  *Invalid*. `uetool` signs every nested `.dylib`/`.so` individually (deepest first)
  then seals the `.app` last.
- **macOS builds must be built on a Mac** (Apple toolchain) with a *Developer ID
  Application* certificate in the login keychain plus the `Developer ID` intermediate.
- **steamcmd auth:** do one interactive `steamcmd +login <user> +quit` to cache the
  Steam Guard sentry; afterwards uploads run unattended. A depot must be **created
  and published** under the app before an upload to it will succeed.
- **TOML backslashes:** in double-quoted strings `\` is an escape — use forward
  slashes or 'single quotes' for Windows paths.

---

## Design rationale

Orchestration in Python (cross-platform, strong string/path handling, absorbs the
macOS signing/notarization divergence cleanly); the real work is delegated to the
platform's own tools. Everything project-specific lives in the project's two
`uetool*.toml` files and the project's `.uproject`/`Config/DefaultGame.ini`, so the
tool itself carries nothing about any particular game and can serve every UE project
on the machine from a single install.
