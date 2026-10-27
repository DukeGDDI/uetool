# Epic Games Store publishing for uetool — implementation plan

Status date: 2026-10-25. Scope: add Epic Games Store (EGS) publishing alongside the
existing Steam path, mirroring `core/steam.py`, across the CLI, the PySide6 UI, config,
tests and docs. Planning only — no code is changed by this document.

> **Important reality check.** When this plan was written the working tree already
> contained a complete, passing implementation of nearly everything below
> (`core/epic.py`, the `[epic]` config model, the `--store` selector, UI wiring,
> `tests/test_epic.py`, README and `uetool.toml.example` sections; `./.venv/bin/python -m
> pytest -q` → **106 passed**). This plan therefore does two jobs: (1) it records the
> design that is already in place so the choices are reviewable, and (2) it isolates the
> **genuinely unresolved items** — chiefly whether the secret-passing flag
> `-ClientSecretEnvVar` is real, and which Windows binary implements the online upload
> mode — which must be settled before the first real upload is trusted. Treat §2 and §9
> as the live worklist; §3–§8 are "verify matches the committed code," not "write from
> scratch."

---

## 1. How Steam works today (the backend being mirrored)

`core/steam.py upload(cfg, target, dry_run, app, custom_config)`:

1. `select_app(cfg, app)` resolves one of `[steam.main|demo|playtest]` (`config.select_app`:
   explicit name must be configured; a single configured app is implicit; several require
   `--app`).
2. Guards: a Steam user (`cfg.steam_user`, env `UETOOL_STEAM_USER`) and a non-placeholder
   depot id for the target platform.
3. Version = `.version` file (`_read_version`), written by `bump`. Custom-config layer name
   is appended to the Steam build **description** (`"{version} ({custom})"`) so a custom
   build is identifiable in Steamworks.
4. `content_root = cfg.stage_dir / cfg.stage_subdirs[target]`; on mac,
   `stage.normalize_mac_bundle` renames `<Project>-Mac-<Config>.app` → `<Project>.app`.
5. Renders `steam/app_build.vdf.tmpl` + `depot.vdf.tmpl` into
   `.uetool/steam_build/<app>/`, one folder per app.
6. `run([steamcmd, +login user [pw], +run_app_build app.vdf, +quit], dry_run)`.
7. Prints a **"NOT live yet — set it live in Steamworks"** banner with the portal URL.
   The password is read from `UETOOL_STEAM_PASSWORD` (env only) and only *appended to
   argv when present* — it is otherwise absent.

The Epic backend mirrors this shape exactly, with BuildPatchTool (BPT) in place of
steamcmd and an "assign the platform to a label in the Dev Portal" step in place of
"set it live in Steamworks."

---

## 2. BuildPatchTool invocation — what is verified, and the two open questions

The BPT download on this machine is **BuildPatchTool 1.8.8** (`~/BuildPatchTool`, with
`BuildPatchTool Instructions 1.8.8 [docv1.8].pdf`, a root `BuildPatchToolInterface.exe`,
and `Engine/Binaries/{Win64,Mac,Linux}/BuildPatchTool[.exe]`).

### Confirmed from a real BPT upload log + third-party integration guides

A real UploadBinary command line (Unreal Engine forums, a 1.8-era Mac upload) and
Xsolla's EGS integration guide together confirm the flag set the code uses:

| Flag | Confirmed | Notes |
|---|---|---|
| `-mode=UploadBinary` | ✅ | Online mode; also `ReuploadBinary`, `LabelBinary`, `UnlabelBinary` exist (seen in the Mac binary's `BPTOnline`/`BuildPatchOnlineMcp` symbols). |
| `-OrganizationId=o-…` | ✅ | Org token, `o-` prefix. |
| `-ProductId=<32hex>` | ✅ | From EOS SDK Credentials / Product. |
| `-ArtifactId=<32hex>` | ✅ | The Epic "App"/artifact id, on the artifact's page. |
| `-ClientId=xyza…` | ✅ | BPT Client id (`xyza…` prefix), Product Settings → BPT credentials. |
| `-BuildRoot=<dir>` | ✅ | Must exist; the staged platform folder. |
| `-CloudDir=<dir>` | ✅ | Chunk cache; **must be outside BuildRoot**. Code uses `.uetool/epic/cloud` (outside `stage_dir`) ✅. |
| `-BuildVersion=<str>` | ✅ | Whitespace-free; unique per platform. |
| `-AppLaunch=<rel path>` | ✅ | Relative to BuildRoot. **Mac = the inner Mach-O under `…app/Contents/MacOS/<exe>`, not the `.app`** — the forum log shows exactly `/Contents/MacOS/<exe>`. Matches `epic._app_launch`. |
| `-AppArgs=` | ✅ | Present, may be empty. Code passes `"-AppArgs="`. |

The tool also auto-appends `-usehyperthreading -unattended`; uetool does not need to.

### OPEN QUESTION #1 (blocking trust of the first real upload) — the client secret flag

The code passes the secret **by env-var name**:

```
-ClientSecretEnvVar=UETOOL_EPIC_CLIENT_SECRET
```

so the secret value never enters `argv` and `core.paths.run()` (which prints the full
command via `subprocess.list2cmdline`) cannot leak it. This is the right *shape* for the
"dry-run must never print the secret" requirement.

**But every source I could reach shows the documented/observed form as
`-ClientSecret=<value>` on the command line** — the real forum upload used
`-ClientSecret=******` (masked), and Xsolla/usourcecontrol describe `-ClientSecret`. I
could **not** confirm that `-ClientSecretEnvVar` exists in BPT 1.8.8: it is absent from
the forum log and the third-party guides, web search found nothing, and the authoritative
`BuildPatchTool Instructions 1.8.8` PDF could not be text-extracted in this environment
(custom font encoding; no `poppler`/PDF lib available).

Action before first real upload (≤15 min): open that PDF (or run the resolved binary's
`-help`) and confirm whether `-ClientSecretEnvVar=<NAME>` is a supported argument.
- **If supported** (I believe recent BPT does support it, but it is unconfirmed): nothing
  changes; the current design is correct and secret-safe.
- **If NOT supported**: the backend must fall back to `-ClientSecret=<value>` read from
  `os.environ[SECRET_VAR]`. That puts the secret into `argv`, so `core.paths.run()` would
  print it. That is unacceptable, so this fallback **requires a redacting runner** — e.g.
  `run(cmd, dry_run, redact=[secret])` that replaces the value with `******` in the
  printed line (and the backend must still refuse to run without the env var). This is the
  one change with real design weight; flag it to the user rather than guessing.

### OPEN QUESTION #2 — which Windows binary implements UploadBinary

`paths.buildpatchtool_for_sdk` resolves `Engine/Binaries/Win64/BuildPatchTool.exe` on
Windows and `Engine/Binaries/Mac/BuildPatchTool` on Mac. The **Mac** binary's symbols
reference the online `UploadBinaryMode` (good — the resolved Mac binary can upload). The
**Win64** `BuildPatchTool.exe` strings list only the *offline* modes
(`ChunkBuildDirectory`, `PatchGeneration`, `compactify`, `enumeration`); the online upload
modes may instead live in the root **`BuildPatchToolInterface.exe`** (38 MB), which
`paths.py` does **not** resolve. (Strings alone are not conclusive — the token may just
not surface.) Action (Windows only, at first Windows upload): confirm whether
`Engine/Binaries/Win64/BuildPatchTool.exe -mode=UploadBinary …` works; if not, add
`BuildPatchToolInterface.exe` (root) to the Win64 `rels` list in
`paths.buildpatchtool_for_sdk`. Mac/Linux are unaffected.

Sources: forum UploadBinary log
(forums.unrealengine.com/t/upload-build-for-mac-os-was-failed-…/2703238), CloudDir
guidance (forums.unrealengine.com/t/buildpatchtool/1335194), Xsolla EGS guide
(developers.xsolla.com/doc/launcher/how-to/integration-with-egs), usourcecontrol publish
guide (usourcecontrol.com/docs/packaging/publish-to-epic), and the local
`BuildPatchTool Instructions 1.8.8` PDF (authoritative; not yet text-extracted).

---

## 3. `core/epic.py` — the backend (already present; verify against this spec)

Public: `upload(cfg, target, dry_run, custom_config=None)` and
`_require_epic(cfg) -> EpicConfig` (reused by `cli.release` for the up-front destination
check).

- `_require_epic`: `SystemExit` when `cfg.epic is None` (no `[epic]`) or any id missing.
- Secret guard (real runs only): `SystemExit` with a "set `UETOOL_EPIC_CLIENT_SECRET`"
  hint when the env var is absent and not `dry_run`.
- `version = .version` file (same `_read_version` as steam).
- `build_version = f"{version}-{target}"` + (`f"_{custom_config}"` if set). Platform-stamped
  because **BPT BuildVersion must be unique per platform and whitespace-free**
  (`v1.9.0.8-win`, `v1.9.0.8-mac`, `v1.9.0.8-mac_Demo`). This is the Epic analogue of
  Steam folding the custom layer into the build *description*.
- `content_root = cfg.stage_dir / cfg.stage_subdirs[target]`; mac →
  `stage.normalize_mac_bundle`.
- `_app_launch(cfg, target)`: per-platform override from `[epic]` wins; else win =
  `<Project>.exe`, mac = `<Project>.app/Contents/MacOS/<CFBundleExecutable>` where the
  inner name is read from the staged `Info.plist` via `stage.mac_bundle_executable`
  (Shipping keeps the decorated `<Project>-Mac-Shipping` inside the renamed bundle).
- `CloudDir = .uetool/epic/cloud` (outside BuildRoot), created per run.
- `cmd` = the flag list in §2; forward-slash, no trailing slash, argv list (no shell).
- Post-upload banner: **"NOT live — attach the binary and assign the `<Windows|Mac>`
  platform in the Dev Portal (that sets the Live label)"**, link `https://dev.epicgames.com/portal`.

Matches the committed `core/epic.py`. The only spec item contingent on §2/#1 is the secret
flag.

---

## 4. Config — `[epic]` table (already present; verify)

`config.py` adds `EpicConfig(org_id, product_id, artifact_id, client_id, app_launch{win,mac},
bpt, client_secret)` and `_load_epic(base, local)`:

- Reads `[epic]` from `uetool.toml` (+ `uetool.local.toml`, local wins per key). All ids
  blank/absent → `None` ("no Epic target"). `app_launch_win` / `app_launch_mac` optional.
- Secret is **env-only** (`UETOOL_EPIC_CLIENT_SECRET`), never read from a file — identical
  policy to `steam_password` / `apple_password`.
- BPT resolution order: `UETOOL_EPIC_BPT` → `buildpatchtool_for_sdk(UETOOL_EPIC_SDK)` →
  toml `buildpatchtool` → `"BuildPatchTool"` on PATH. (`buildpatchtool_for_sdk` already
  existed in `paths.py`; see Open Question #2 for the Win64 rels caveat.)

**Single `[epic]` artifact vs. `[epic.<target>]` multi-artifact.** The committed model is
**one** artifact (unlike Steam's per-app tables). Recommendation: keep one `[epic]` for
now. Steam separates main/demo/playtest because each is a distinct *appid+depot*; on Epic a
demo is usually either a separate **Artifact under the same Product** or a storefront
**Offer**, and D6scend does ship a Demo (Steam demo app + `Config/Custom/Demo` layer +
URL-detected demo mode). **Open question for the user:** does the D6scend Epic Product have
one artifact or separate main/demo artifacts? If separate, promote `[epic]` →
`[epic.<target>]` with a `select_epic(cfg, name)` resolver mirroring `select_app`, and add
an Epic target selector to CLI/UI. Until the Dev Portal layout is known, the single-artifact
model stays and `--custom-config Demo` just tags the BuildVersion. `uetool.toml.example`
already documents the single `[epic]` block.

---

## 5. CLI — `--store {steam,epic}` (already present; verify)

- `_add_store(sp)` adds `--store {steam,epic}` default **`steam`** (so every existing
  command/test is unchanged) to `upload` and `release`.
- `upload`: `args.store == "epic"` → `epic.upload(cfg, platform, dry_run)`; else
  `steam.upload(..., app=args.app)`.
- `release`: resolve destination **before** the hour-long build — `epic._require_epic(cfg)`
  or `config.select_app(cfg, args.app)` — then bump → package → **notarize on mac (Steam
  AND Epic: both distribute outside the App Store)** → `epic.upload(..., custom_config)` or
  `steam.upload(...)`.
- `--app` stays Steam-only (help text says so); `--store epic` ignores it.

Matches committed `core/cli.py`. If §4 goes multi-artifact, add an Epic target flag here.

---

## 6. UI (already present; verify)

- **Build tab** (`ui/tab_build.py`): a `Store` combo (`steam`/`epic`); `--store` enabled
  only where `CAPS` allows; `--app` disabled when store=epic; `epic_configured()` feeds
  validation; the Upload-to-Epic confirm dialog states the "assign platform in Dev Portal"
  step. `BuildSpec.store` default `"steam"`.
- **Config tab** (`ui/tab_config.py`): an "Epic Games Store" group with org/product/
  artifact/client ids (committed `[epic]`) + a `SecretRow("epic", …)` storing the BPT
  Client Secret in the OS keychain, and an "Epic SDK folder" (`UETOOL_EPIC_SDK`) picker.
- **Secret → child env**: keychain `epic:<client_id>` → `keychain.env_for(... epic_client)`
  → `UETOOL_EPIC_CLIENT_SECRET` → `context.run_env` → `runner.child_env`. The value lives
  only in the keychain and the child env; it never touches a file or `argv`.
- `ui/commands.py`: `CAPS["upload"|"release"]` include `"store"`; `build_argv` emits
  `--store` only when `!= "steam"`; `validate(...)` errors on `store=epic` +
  `epic_configured is False` and skips the Steam-app check in that case.

Matches committed UI. `test_caps_match_cli_parser` already maps `store`→`--store`.

---

## 7. Tests (already present; verify green)

`tests/test_epic.py` (mirrors `test_steam_upload.py`) asserts the full BPT argv for win and
mac, the inner-Mach-O AppLaunch (incl. reading a decorated `CFBundleExecutable` from a
staged `Info.plist`), the custom-config BuildVersion suffix, the app_launch override, the
not-configured `SystemExit`, and — critically — the **secret guard** for real runs. Note
the secret never appears in `argv` **because the backend passes the env-var name, not the
value**; if Open Question #1 forces the `-ClientSecret=<value>` fallback, add an explicit
test that the secret value is absent from both `argv` and the printed/redacted output.
`tests/test_commands.py` adds `test_store_epic_in_argv_steam_omitted` and
`test_validate_epic_requires_config_and_skips_steam_app`, and extends the CAPS flagmap.
Whole suite: **106 passed** as of this date.

---

## 8. README (already present; verify)

README has: env setup (`UETOOL_EPIC_SDK`, `UETOOL_EPIC_CLIENT_SECRET`) for mac and Windows;
a BPT-download step; an "Epic Games Store (`--store epic`)" section with the `[epic]` table,
`release`/`upload --store epic` usage, the mac-notarize note, the per-platform BuildVersion
rule, and the upload≠live manual step. Verify the secret-flag wording stays accurate once
Open Question #1 is resolved.

---

## 9. Remaining worklist (what is actually left)

Ordered; the implementation itself is done and green.

1. **Resolve Open Question #1** — confirm `-ClientSecretEnvVar` in the 1.8.8 PDF / `-help`.
   If unsupported, add a redacting `run(..., redact=[...])` and switch the backend to
   `-ClientSecret=<value>` from env, plus the secret-absence test. **≤0.5 day** (trivial if
   supported; ~0.5 day if the redacting-runner fallback is needed). *Blocking for a trusted
   first upload.*
2. **Resolve Open Question #2** — verify the Win64 upload binary; if needed add
   `BuildPatchToolInterface.exe` to `paths.buildpatchtool_for_sdk` Win64 rels. **≤0.25 day**,
   Windows only.
3. **Get the real ids from the user** — OrganizationId (`o-…`), ProductId, ArtifactId,
   ClientId (`xyza…`) for the D6scend Epic Product; put the ids in `uetool.toml` `[epic]`
   and the secret in the keychain / `UETOOL_EPIC_CLIENT_SECRET`. **User action.**
4. **Confirm one-artifact vs. main/demo** (§4). If separate, add `[epic.<target>]` +
   `select_epic` + CLI/UI target selector + tests. **~0.5–1 day if needed, else 0.**
5. **First real smoke upload** — `uetool release --platform win --store epic` (then mac),
   confirm the binary appears in the Dev Portal, assign the platform, verify it goes Live.
   **~0.5 day incl. a package.**

**Effort estimate.** Core/CLI/UI/tests/docs: **done**. Remaining to a trusted first
publish: **~1–1.5 days**, dominated by the two verifications, the real smoke upload, and
(only if Epic uses separate artifacts) the multi-artifact extension.

## 10. Cross-platform notes

- `paths.buildpatchtool_for_sdk` already OS-branches (Win64 `.exe`, Mac/Linux no ext), with
  the Win64 caveat in Open Question #2.
- Mac: `stage.normalize_mac_bundle` + `mac_bundle_executable` give the config-decorated
  inner binary for `-AppLaunch`; `release --store epic` notarizes first (Developer ID), same
  as Steam.
- All BPT paths are emitted `as_posix()` (BPT accepts forward slashes on every OS); argv is
  a list, so no shell quoting is involved.
- Secret policy is uniform with Steam/Apple: env-only, keychain in the UI, never a file,
  never `argv` (contingent on Open Question #1).
