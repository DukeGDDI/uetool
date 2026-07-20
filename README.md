# uetool

A small, cross-platform CLI that **bumps**, **packages**, **signs/notarizes**, and
**uploads to Steam** any Unreal Engine project — without living inside the project.
It is a thin orchestration layer: Unreal's `RunUAT` does the cooking/packaging,
Apple's `codesign`/`notarytool` do macOS signing, and `steamcmd` does the upload.
`uetool` just wires them together with consistent versioning and config.

Install it once, put it on your `PATH`, and point it at any UE project.

---

## Install

Clone (or download-and-extract) this repo anywhere — it's self-contained, and only
the folder needs to go on your `PATH`:

```
git clone https://github.com/DukeGDDI/uetool.git
```

**Requirements (both platforms):**
- **Python 3.11+** (uses stdlib `tomllib`).
- **steamcmd** — Valve's standalone build, or the Steamworks SDK's ContentBuilder.
- For **macOS** target builds: a Mac with Xcode's command-line tools and a
  *Developer ID Application* certificate (see the macOS section).

Then follow the setup for your OS below. Both set the same two machine-wide env vars
(`UETOOL_PYTHON`, `UETOOL_STEAM_SDK`) plus secrets; everything project-specific lives
in the project's `uetool.toml` / `uetool.local.toml` (see [Per-project setup](#per-project-setup)).

---

## Machine setup — macOS / Linux

1. **Put uetool on `PATH`** (zsh shown — adjust for your shell):
   ```bash
   echo 'export PATH="$HOME/Workspace/uetool:$PATH"' >> ~/.zshrc
   ```
2. **Python 3.11+** — e.g. `brew install python@3.13`.
3. **steamcmd** — install Valve's standalone build:
   ```bash
   mkdir -p ~/steamcmd && cd ~/steamcmd
   curl -sSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz | tar xz
   ./steamcmd.sh +quit        # first run self-updates
   ```
   (Linux: use `steamcmd_linux.tar.gz`.)
4. **Machine-wide env vars** (add to `~/.zshrc`), shared by every project:
   ```bash
   export UETOOL_PYTHON=/opt/homebrew/bin/python3.13     # a 3.11+ interpreter
   export UETOOL_STEAM_SDK="$HOME/steamcmd"              # folder containing steamcmd
   export UETOOL_APPLE_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx  # macOS notarization only
   ```
5. **One-time Steam login** to cache the Steam Guard sentry — see
   [Steam login](#steam-login-one-time-per-machine).
6. **macOS signing (for `notarize`):** you need a *Developer ID Application*
   certificate in your **login keychain** (with Apple's *Developer ID* intermediate),
   and an Apple ID enrolled in the Apple Developer Program. The `apple_id`, `team_id`,
   and `signing_identity` go in the project's `uetool.local.toml`; the app-specific
   password is the `UETOOL_APPLE_APP_PASSWORD` env var above.

Open a new terminal so the changes take effect.

---

## Machine setup — Windows (PC)

1. **Put uetool on `PATH`** — add the `uetool` folder (e.g. `D:\Workspace\uetool`) to
   your `Path` via *System → Environment Variables* (or `setx`). `uetool.cmd` runs in
   both `cmd.exe` and PowerShell (no execution-policy issues).
2. **Python 3.11+** — `winget install Python.Python.3.13` (or from python.org).
3. **steamcmd** — download and extract Valve's standalone build:
   - Get **https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip**
   - Extract to e.g. `C:\steamcmd\`.
   - Run `C:\steamcmd\steamcmd.exe` once so it self-updates.
   - **Add `C:\steamcmd` to `Path` as well** (see the note below).
4. **Machine-wide env vars** (*System → Environment Variables*, or `setx`):
   ```
   setx UETOOL_PYTHON python
   setx UETOOL_STEAM_SDK C:\steamcmd
   ```
   (Use the full `python.exe` path if `python` isn't already on `PATH`. The macOS
   Apple vars don't apply on Windows.)
5. **One-time Steam login** to cache the Steam Guard sentry — see
   [Steam login](#steam-login-one-time-per-machine).

> **Important (Windows):** the steamcmd folder goes in **two** places —
> `UETOOL_STEAM_SDK` (so uetool finds `steamcmd.exe`) **and** `Path` (so
> `steamcmd.exe` can load its own runtime DLLs). Without it on `Path`, uploads can
> fail to start even though `UETOOL_STEAM_SDK` is correct.

Open a new terminal (or sign out/in) so the changes take effect.

---

## Steam login (one-time, per machine)

Before the first `upload`/`release`, run the **interactive** login once. It prompts
for the build account's password and a Steam Guard 2FA code:

```bash
# macOS / Linux
~/steamcmd/steamcmd.sh +login <build_account> +quit
```
```bat
:: Windows
C:\steamcmd\steamcmd.exe +login <build_account> +quit
```

steamcmd then caches a **sentry** file, so every later `uetool upload` (which logs in
non-interactively) runs **unattended** — you do *not* repeat this per build. Re-run it
only when the sentry lapses: after a password change, long inactivity, a Steam Guard
change, or moving/replacing steamcmd. The sentry is per-machine + per-OS-user, so
**each build machine needs its own one-time login**.

---

## Per-project setup

At the **root of your UE project** (next to `YourGame.uproject`):

1. Copy the two templates from this repo and fill them in:
   - `uetool.toml` — **committed**, non-secret (Steam `app_id`, depot ids, build config).
   - `uetool.local.toml` — **untracked**, per-machine (`ue_root`; Steam `user`; Apple ids).
     `ue_root` is platform-specific, e.g. `"/Users/Shared/Epic Games/UE_5.7"` (macOS)
     or `"C:/Program Files/Epic Games/UE_5.7"` (Windows — forward slashes).
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
usage: uetool [-P PATH] {bump,bootstrap,package,upload,notarize,archive,release} ...
              [--platform win|mac] [--config Shipping] [--dry-run] [--no-bump] [--no-bootstrap]
```

Run from inside the project, or point at it with `-P`:

```bash
uetool bump                              # advance the build counter only (writes .version)
uetool bootstrap                         # build the editor target (headless; for a fresh checkout)
uetool package --platform mac            # bump + RunUAT package
uetool package --platform mac --no-bump  # package without bumping
uetool notarize                          # sign + notarize + staple the staged macOS .app
uetool upload --platform mac             # push the staged build to Steam
uetool archive --platform win            # zip the staged build for non-Steam distribution
uetool release --platform mac            # bump -> package -> [notarize on mac] -> upload
uetool -P ~/games/MyGame release --platform win   # operate on a project elsewhere
```

`--platform` defaults to the host (`win` on Windows, `mac` on a Mac). `--dry-run`
prints every external command without executing it (and still validates config) — the
safe way to verify wiring with no engine or Steam access.

### Fresh checkout / CI

A C++ project that has never been built has no `Binaries/<host>/<Project>Editor.target`
receipt, and RunUAT's cook step reads it before doing anything — so a raw `package`
would fail with *"Could not find file …Editor.target"*. (Normally you'd first open the
project in the editor, or build it in Rider / Visual Studio.)

`package` and `release` handle this automatically: if the receipt is missing they run
**`bootstrap`** first, which builds the editor target headlessly via UnrealBuildTool
(`Build.bat`/`Build.sh`) — no manual pre-build, no `.sln`/Xcode project needed. It's a
no-op once the project has been built, so a CI agent can run `uetool release` on a clean
checkout and it just works. Pass `--no-bootstrap` to skip it (e.g. when the editor target
is already cached), or run `uetool bootstrap` on its own as an explicit CI step.

### Non-Steam distribution (`archive`)

Some hosts take a packaged build directly instead of a Steam depot — **Arcware pixel
streaming**, itch.io, a plain download. `uetool archive --platform <win|mac>` zips the
staged build into `.uetool/dist/<Project>-<version>-<platform>.zip`, with the executable
at the **zip root** (it zips the *contents* of the staged folder), names the file with
the current version, and prints the path. It streams large `.pak` files (no memory blow-up
on multi-GB builds), and preserves the Unix exec bit and symlinks so Linux/macOS builds
stay intact.

```bash
uetool package --platform win     # produce Saved/StagedBuilds/Windows
uetool archive --platform win     # -> .uetool/dist/<Project>-vX.Y.Z.N-win.zip, ready to upload
```

For **Arcware pixel streaming** specifically, the project must have the **Pixel Streaming**
plugin enabled (UE 5.5+: *Pixel Streaming 2*) so it's compiled into the build — uetool
packages and zips, but it can't add the plugin. The streaming launch args
(`-PixelStreamingURL`, `-RenderOffScreen`, …) are supplied by Arcware at runtime, not baked
into the build.

> **IMPORTANT** Uploading **never** auto-promotes a build to a live Steam branch; that stays a deliberate step on the Steamworks site.

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
| `.version` | no | full build label `vX.Y.Z.N` (generated) |
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
  Application* certificate in the login keychain plus the *Developer ID* intermediate.
- **Steam depots:** the target depot must be **created and published** under the app
  before an upload to it will succeed (otherwise steamcmd reports *Access Denied*).
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
