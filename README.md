# uetool

A small, cross-platform CLI that **bumps**, **packages**, **signs/notarizes**, and
**publishes** any Unreal Engine project — to **Steam**, the **Epic Games Store**, or the
**Mac App Store** — without living inside the project. It is a thin orchestration layer:
Unreal's `RunUAT` cooks/packages, Apple's `codesign`/`notarytool`/`altool` do macOS signing,
and `steamcmd` / Epic's `BuildPatchTool` / App Store Connect do the uploads. `uetool` just
wires them together with consistent versioning and config.

Install it once, put it on your `PATH`, and point it at any UE project.

Prefer a window? The same tool ships with a desktop **Control Panel** — see
[Starting the UI](#starting-the-ui).

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
   # Epic Games Store (optional, only if you publish there — see "Epic Games Store" below):
   export UETOOL_EPIC_SDK="$HOME/BuildPatchTool"         # folder you extracted BuildPatchTool to
   export UETOOL_EPIC_CLIENT_SECRET=xxxxxxxx             # BPT Client Secret (Dev Portal)
   ```
5. **BuildPatchTool (optional, for Epic)** — download it from the Dev Portal
   (*Epic Games Store → Artifacts and Binaries → Download build patch tool*), extract it,
   and point `UETOOL_EPIC_SDK` at that folder (uetool finds the binary under its
   `Engine/Binaries/<host>/`).
6. **One-time Steam login** to cache the Steam Guard sentry — see
   [Steam login](#steam-login-one-time-per-machine).
7. **macOS signing (for `notarize`):** you need a *Developer ID Application*
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
   :: Epic Games Store (optional — see "Epic Games Store" below):
   setx UETOOL_EPIC_SDK C:\BuildPatchTool
   setx UETOOL_EPIC_CLIENT_SECRET xxxxxxxx
   ```
   (Use the full `python.exe` path if `python` isn't already on `PATH`. The macOS
   Apple vars don't apply on Windows.)
5. **BuildPatchTool (optional, for Epic)** — download it from the Dev Portal
   (*Epic Games Store → Artifacts and Binaries → Download build patch tool*), extract to
   e.g. `C:\BuildPatchTool`, and point `UETOOL_EPIC_SDK` at it (uetool finds the binary
   under its `Engine\Binaries\Win64\`).
6. **One-time Steam login** to cache the Steam Guard sentry — see
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
   - `uetool.toml` — **committed**, non-secret: build config and one `[steam.<app>]` table
     per Steam app the game has (`main`, `demo`, `playtest` — any subset), each with its
     `app_id` and depot ids.
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
usage: uetool [-P PATH] {bump,bootstrap,package,upload,notarize,archive,release,ui} ...
              [--platform win|mac] [--config Shipping] [--dry-run]
              [--no-bump] [--no-bootstrap] [--clean] [--custom-config NAME]
              [--store steam|epic|appstore] [--app main|demo|playtest] [--validate]
```

Run from inside the project, or point at it with `-P`:

```bash
uetool bump                              # advance the build counter only (writes .version)
uetool bootstrap                         # build the editor target (headless; for a fresh checkout)
uetool package --platform mac            # bump + RunUAT package
uetool package --platform mac --no-bump  # package without bumping
uetool notarize                          # sign + notarize + staple the staged macOS .app
uetool upload --platform mac --app playtest      # push the staged build to the playtest app
uetool archive --platform win            # zip the staged build for non-Steam distribution
uetool release --platform mac --app main # bump -> package -> [notarize on mac] -> upload to the store app
uetool release --platform win --store epic       # same build, uploaded to Epic via BuildPatchTool
uetool release --platform mac --store appstore   # Mac App Store: sign + .pkg + App Store Connect
uetool -P ~/games/MyGame release --platform win --app demo   # operate on a project elsewhere
```

`--platform` defaults to the host (`win` on Windows, `mac` on a Mac). `--dry-run`
prints every external command without executing it (and still validates config) — the
safe way to verify wiring with no engine or Steam access.

### Steam apps (`--app main|demo|playtest`)

A game on Steam is often several Steamworks apps: the **store** app, a **demo** app and a
**playtest** app, each with its own app id and depots. `uetool.toml` declares whichever of
the three the project has, as `[steam.main]`, `[steam.demo]` and `[steam.playtest]` tables
(omit the ones you don't have):

```toml
[steam.main]
app_id = "4547240"
depot_win_id = "4547241"
depot_mac_id = "4547242"

[steam.playtest]
app_id = "4852730"
depot_win_id = "4852731"
depot_mac_id = "4852732"
```

`upload` and `release` take `--app` to pick the destination. With exactly one app
configured the flag may be omitted; with two or more it is **required** — the CLI refuses
and lists the choices, so a build never lands on the store app by accident. `release`
resolves the app *before* packaging, so a missing `--app` fails in a second, not after an
hour-long cook. The packaging, notarization and versioning steps are the same for every
app; only the app/depot ids in the generated VDFs (kept per app under
`.uetool/steam_build/<app>/`) differ.

The older single-app layout (`app_id` / `depot_*_id` directly under `[steam]`) is no longer
read; the tool exits with the new layout spelled out, and the Control Panel's Setup tab
flags it.

### Epic Games Store (`--store epic`)

`upload` and `release` take `--store {steam,epic}` (default `steam`). With `--store epic`
uetool uploads the **same staged build** to an Epic artifact via Epic's **BuildPatchTool**:

```toml
[epic]                       # ids are on the Epic Dev Portal (non-secret)
org_id = "o-xxxxxxxx"
product_id = "xxxxxxxx"
artifact_id = "xxxxxxxx"
client_id = "xyza…"          # the BPT Client ID (it does start with xyza)
# app_launch_win = "MyGame.exe"                      # defaults from the project name
# app_launch_mac = "MyGame.app/Contents/MacOS/MyGame"
```

Setup (once): download **BuildPatchTool** from the Dev Portal (*Epic Games Store → Artifacts
and Binaries → Download build patch tool*), extract it, and point uetool at the folder with
`UETOOL_EPIC_SDK` (or a direct path in `UETOOL_EPIC_BPT`). The **BPT Client Secret** is
env-only, like every other secret:

```bash
export UETOOL_EPIC_SDK="$HOME/BuildPatchTool"
export UETOOL_EPIC_CLIENT_SECRET='…'     # Dev Portal → Product Settings → BPT credentials
```

```bash
uetool release --platform win --store epic         # bump -> package -> BPT upload
uetool upload  --platform mac --store epic          # mac: notarize first, like Steam
```

Notes specific to Epic:
- **A Mac Epic build still notarizes** (Developer ID) before upload — Epic distributes
  outside the App Store, exactly like Steam.
- **`BuildVersion` is platform-distinct and whitespace-free:** uetool labels the build
  `vX.Y.Z.N-win` / `vX.Y.Z.N-mac` (a custom layer becomes `…-mac_Demo`), because BPT forbids
  one version string spanning both platforms and disallows spaces.
- **Upload ≠ live.** BPT registers the binary in your Dev sandbox; it goes Live when you
  **assign the platform to the artifact** on the *Artifacts and Binaries* page (self-service
  publishing). uetool prints the reminder with the portal link.
- `--app` is Steam-only; Epic has one `[epic]` artifact (multiple artifacts can be added
  later the same way Steam grew multiple apps).

### Mac App Store (`--store appstore`)

**macOS only.** Unlike Steam/Epic (Developer-ID notarized), a Mac App Store build is
**sandboxed**, signed with an **Apple Distribution** identity, packaged into a **signed
installer `.pkg`**, and uploaded to **App Store Connect** — **no notarytool, no stapler**.
`release --store appstore` runs bump → package → MAS-sign → `productbuild` → `altool` upload,
*skipping* the Developer-ID notarize step. It refuses anything but a macOS host and
`--platform mac`.

```bash
uetool release --platform mac --store appstore              # sign -> .pkg -> upload
uetool release --platform mac --store appstore --validate   # rehearse (altool --validate-app, no submit)
uetool upload  --platform mac --store appstore              # package already staged
```

The exact signing sequence (each step printed; verified end-to-end against App Store Connect's
`--validate-app`):
1. embed the Mac App Store provisioning profile as `Contents/embedded.provisionprofile`;
2. sign inside-out with the Apple Distribution identity + MAS entitlements (**no** hardened runtime);
3. **`chmod -R a+rX`** the bundle — without this, altool rejects with error **90255** ("files
   only readable by root"); mode bits aren't sealed, so this doesn't disturb the signature;
4. `productbuild --component <app> /Applications --sign "3rd Party Mac Developer Installer: …"`;
5. `xcrun altool --upload-app --file <pkg> --type macos --apiKey <id> --apiIssuer <id>`.

**Prerequisites** (obtain once; they gate only the first real upload):
- an **Apple Distribution** cert and a **3rd Party Mac Developer Installer** cert in your
  login keychain. If a freshly-created cert shows `CSSMERR_TP_NOT_TRUSTED`, install the current
  **Apple WWDR G3 intermediate** (`curl http://certs.apple.com/wwdrg3.der` → double-click, or
  `security import`) — new MAS certs chain through it;
- a **Mac App Store provisioning profile** for your bundle id (`.provisionprofile`);
- an **App Store Connect API key**: the key id + issuer id go in `[appstore]`; place the
  secret **`AuthKey_<KEYID>.p8` in `~/.appstoreconnect/private_keys/`** — altool reads it there
  and **uetool never touches the key** (only the two ids reach the command line). Point
  `[appstore] api_key_path` / `UETOOL_ASC_API_KEY_PATH` at a `.p8` elsewhere and uetool symlinks
  it into place (still never reading its bytes);
- an **App Store Connect app record** for the bundle id (SKU chosen).

Config (`[appstore]` in `uetool.toml`, all non-secret — see `uetool.toml.example`):
`bundle_id`, `team_id` (defaults to `[apple] team_id`), `app_identity`, `installer_identity`,
`provision_path`, `entitlements_path` (optional — uetool generates an app-sandbox +
network.client plist if unset), `asc_key_id`, `asc_issuer_id`, and optional `app_sku` /
`app_apple_id` / `api_key_path`.

Notes:
- **Upload ≠ submission.** altool uploads the build; metadata, screenshots and **review** are
  manual in App Store Connect (uetool prints the link).
- The MAS build should be a **non-Steam** variant with a `Sandbox.MAS.entitlements` file on the
  **project** side; uetool's re-sign makes the entitlements authoritative regardless.
- Alternative uploader: `xcrun iTMSTransporter` (inside Transporter.app) is a manual fallback;
  altool is the supported CLI path and the only one uetool drives.

### Stable launch paths (`<Project>.app` / `<Project>.exe`)

Steam's launch options name one executable per platform, and they must not change
between a Development and a Shipping upload to the same depot. UE decorates its
binaries with the configuration (`D6scend-Mac-Shipping.app`), and on macOS that name is
fixed by the Xcode project UBT generates, so it cannot be changed from `Target.cs`
(`UndecoratedConfiguration` only renames the raw executable, and a mismatch there makes
the bundle silently keep the *previous* build). uetool therefore renames the staged macOS
bundle to **`<Project>.app`** right after `package`, and `notarize`, `archive` and `upload`
normalize again in case the stage folder was produced by hand. Only the folder is renamed:
the executable inside, `Info.plist` and the code signature are untouched. Windows needs no
help: UAT already stages an undecorated **`<Project>.exe`** launcher at the staged root for
every configuration.

Set the Steamworks launch options once — macOS `D6scend.app`, Windows `D6scend.exe` — and
they hold for every configuration.

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

Some hosts take a packaged build directly instead of a Steam depot — itch.io, a direct
download, a key reseller. `uetool archive --platform <win|mac>` zips the
staged build into `.uetool/dist/<Project>-<version>-<platform>.zip`, with the executable
at the **zip root** (it zips the *contents* of the staged folder), names the file with
the current version, and prints the path. It streams large `.pak` files (no memory blow-up
on multi-GB builds), and preserves the Unix exec bit and symlinks so Linux/macOS builds
stay intact.

```bash
uetool package --platform win     # produce Saved/StagedBuilds/Windows
uetool archive --platform win     # -> .uetool/dist/<Project>-vX.Y.Z.N-win.zip, ready to upload
```

### Per-host ini layers (`--custom-config`)

A build variant — for example the free **Demo** — sometimes needs settings that would be
*wrong* on the main store build. Put those overrides in
`<project>/Config/Custom/<Name>/Default*.ini` and pass `--custom-config NAME`; uetool
merges the layer into the base `Config/Default*.ini` for the duration of the cook and
restores the originals afterwards, the same borrow-and-restore the version stamp uses.
Without the flag nothing is merged, so the storefront build is unaffected by construction.

Matching keys are replaced in place, new keys are appended to their section, and sections
the base lacks are appended at the end. Restore is byte-exact and runs from a `finally`, so
a failed or interrupted build still leaves your tracked config clean.

> **Why not Unreal's own `-CustomConfig`?** The engine has this exact feature — it layers
> `Config/Custom/<Name>/` above the base when `-CustomConfig=<Name>` is passed — but it
> **cannot work in a packaged Shipping build made with a Launcher (installed) engine**, and
> it fails *silently*: the files stage, and nothing reads them. UBT bakes the `CUSTOM_CONFIG`
> define only for targets not using the shared build environment, `BuildEnvironment` is
> forced to `Shared` whenever the engine is installed, and forcing `Unique` is rejected
> outright ("Targets with a unique build environment cannot be built with an installed
> engine"). The command-line fallback is compiled out of Shipping too
> (`ALLOW_INI_OVERRIDE_FROM_COMMANDLINE` is `(UE_SERVER || !UE_BUILD_SHIPPING)`). Hence the
> merge. uetool does **not** pass `-CustomConfig` to RunUAT.

```bash
# storefront build: base ini only — no flag, nothing to remember
uetool release --platform win --app main

# Steam demo build: the Demo layer, uploaded to the demo app
uetool release --platform win --app demo --custom-config Demo
```

It is deliberately **not** settable in `uetool.toml`. A committed default would apply
silently to every build including the ones headed for a depot, which is exactly the mistake
the layer exists to prevent — so it is opt-in per run.

`release` **accepts** `--custom-config` too — e.g. the `Demo` layer uploaded to the demo
app, or a `Playtest` layer to the playtest app. Because a custom layer leaves no visible
trace in the staged output, uetool tags the layer name into the **Steam build description**
(`vX.Y.Z.N (Demo)`), so the destination is identifiable in the Steamworks build history
rather than silent. (The UI also names the layer in its upload confirmation.)

> Note: `archive` names the zip `<Project>-<version>-<platform>.zip` with no layer suffix,
> so a streaming zip and a storefront zip of the same version collide. Move or rename one
> before building the other.

### Clean rebuilds (`--clean`)

`package` builds and cooks **incrementally** (RunUAT `-build`, plus `-nocompileeditor`), so
after a project change that must land in the shipped build — most commonly **enabling a
plugin** — an incremental package can miss it, and `archive`/`upload` would then ship a
stale build. `package --clean` (also on `release`) wipes `Binaries/`, `Intermediate/`,
`Saved/Cooked/`, and the target's staged output first, forcing a from-scratch compile +
cook. Deleting `Binaries/` also drops the editor `.target`, so `bootstrap` rebuilds the
editor with the change before cooking.

```bash
uetool package --platform win --clean     # after enabling a plugin, or any "why isn't it in the build?" moment
```

> **IMPORTANT** Uploading **never** auto-promotes a build to a live Steam branch; that stays a deliberate step on the Steamworks site.

---

## Configuration model

Three sources, lowest precedence first: `uetool.toml` < `uetool.local.toml` < env.

| Where | Scope | Holds |
|-------|-------|-------|
| **Env vars** (set once on the machine) | machine-wide | `UETOOL_PYTHON`, `UETOOL_STEAM_SDK`, secret passwords; optional overrides (`UETOOL_UE_ROOT`, `UETOOL_STEAM_USER`, `UETOOL_APPLE_*`, `UETOOL_STEAMCMD`) |
| **`uetool.toml`** (committed, project root) | per-project | `[steam.main|demo|playtest]` app + depot ids, `build_config`, stage subdirs |
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
        │                               source DefaultGame.ini stays vX.Y.Z)
        │  [mac] rename <Project>-Mac-<Config>.app -> <Project>.app (stable launch path)
        │  notarize() [mac only]: sign inside-out -> notarytool submit -> staple
        │  upload(--app X): render VDFs into .uetool/steam_build/X/, run steamcmd +run_app_build
        ▼
   Steam build (labeled "vX.Y.Z.N"), NOT set live automatically
```

### Repo layout
```
uetool/
├── uetool            bash launcher (macOS/Linux)
├── uetool.cmd        Windows launcher (works in cmd AND PowerShell)
├── uetool.py         Python entry (sets sys.path, runs core.cli)
└── core/             the package (config, version, package, steam, epic, appstore, notarize)
    └── steam/        VDF templates (@TOKEN@ placeholders)
    └── macsign.py    shared inside-out codesign walk (notarize + appstore)
    └── stage.py      staged-output helpers (macOS bundle rename)
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
- **Mac App Store ≠ Developer ID.** A MAS build is **sandboxed** and signed with an *Apple
  Distribution* identity into a signed `.pkg` — **no** hardened runtime, **no** notarytool,
  **no** stapler (all of which the Steam/Epic macOS path uses). Two gotchas uetool bakes in:
  `chmod -R a+rX` before `productbuild` (else altool error 90255), and new MAS certs need the
  **WWDR G3** intermediate installed or they read as `CSSMERR_TP_NOT_TRUSTED`. See
  [Mac App Store](#mac-app-store---store-appstore).
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

## Control Panel (PySide6 UI)

A desktop front end for the CLI. It shells out to `uetool.py` for every action, so
the CLI stays stdlib-only; the UI's own dependencies (PySide6, tomlkit, keyring,
pytest) live in `ui/requirements.txt`.

### Starting the UI

**One-time setup** — make a virtual environment inside the uetool folder and install
the UI dependencies into it (the CLI itself needs none of this):

```bash
# macOS / Linux — use the same 3.11+ interpreter as UETOOL_PYTHON
cd ~/Workspace/uetool
python3 -m venv .venv
.venv/bin/pip install -r ui/requirements.txt
```
```bat
:: Windows
cd D:\Workspace\uetool
python -m venv .venv
.venv\Scripts\pip install -r ui\requirements.txt
```

**Launch** — the easy way, from anywhere `uetool` is on `PATH`:

```bash
uetool ui                 # opens the current project (if the dir has a .uproject)
uetool -P /path/to/Game ui
```

`uetool ui` finds a PySide6 interpreter — `UETOOL_UI_PYTHON` if set, else the `.venv`
in the uetool **install** folder (the one created above; never the project folder), else
the current interpreter if it already has PySide6 — and launches the app **detached**, so
your terminal returns immediately and closing it doesn't kill the window. Run from a folder
with no `.uproject` and it reopens your last project (or pick one with *Browse…*). If no
PySide6 interpreter is found it prints the venv setup commands. `uetool ui --dry-run` shows
the launch command without starting anything.

You can still launch it directly if you prefer:

```bash
.venv/bin/python ui/app.py /path/to/YourGame          # macOS / Linux
.venv\Scripts\python ui\app.py D:\path\to\YourGame    # Windows
```

**First run:** on the **Config** tab set *Steam SDK folder* to the folder containing
steamcmd (the same path as `UETOOL_STEAM_SDK`). The UI keeps its own copy of that
setting rather than reading your shell's environment, and passes it to every run; the
**Setup** tab's *Copy export lines* button gives you the matching shell line for the
CLI. Steam and Apple passwords are entered once on the Config tab and stored in the OS
keychain, never in a file. Then check the **Setup** tab: when every row is *Pass* or
*n/a* the header badge reads *Ready*.

### Tabs

- **Setup** — a doctor that checks Python, `.uproject`, engine, steamcmd, Steam
  login, the configured Steam apps, Apple fields, and a stamped `DefaultGame.ini`,
  with one-click fixes.
- **Build** — pick the command, platform and the Steam app to upload to; the exact
  CLI line is previewed, the log streams live, and *Cancel* stops the run cleanly.
  *Dry run* rehearses with the bump off so `.build_number` is untouched.
- **Config** — edits `uetool.toml` / `uetool.local.toml` preserving comments, one box
  per Steam app, plus the keychain passwords and the Steam SDK folder.
- **History** — read-only: current version, staged builds and archives on disk, and a
  Steamworks builds link per app.

Passwords reach the CLI only as environment variables of the child process. Tests:
`.venv/bin/python -m pytest`.
