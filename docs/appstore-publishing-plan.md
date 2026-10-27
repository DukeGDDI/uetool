# Mac App Store publishing for uetool — implementation plan

Status date: 2026-10-25. Scope: add **Mac App Store (MAS)** publishing as a third `--store`
backend (`--store appstore`, macOS-only) alongside the existing Steam and Epic paths,
mirroring `core/steam.py` / `core/epic.py` across the CLI, the PySide6 UI, config, tests and
docs. **Planning only — this document changes no code.**

> Unlike the Epic plan (which was written against an already-finished implementation), **none
> of this exists yet.** Everything below is to-be-built. The Steam and Epic backends are the
> templates; `core/notarize.py` is the closest sibling for the signing walk, but the MAS
> signer is a **different pipeline** (different certs, embedded provisioning profile + sandbox
> entitlements, a signed installer `.pkg`, and an App Store Connect upload — **no notarytool,
> no stapler**).

---

## 0. What is already proven / already in the tree

- **Sandbox feasibility is PROVEN for D6scend.** The existing Developer-ID Mac build was
  re-signed locally with only `com.apple.security.app-sandbox` + `com.apple.security.network.client`,
  launched, and played a full maze — mazes loaded (sandboxed HTTP catalog fetch works) and
  saved, **zero** sandbox denials in `log show`. So `network.client` is required, and a
  *thorough* sandbox pass (gamepad / audio / demo / kiosk / any file I/O outside the container)
  is a **pre-ship checklist item, not a feasibility risk** (§9).
- **The project already ships the needed assets.** In `D6scend/Build/Mac/Resources/`:
  - `Sandbox.NoNet.entitlements` — `app-sandbox` only.
  - `Sandbox.Server.entitlements` — `app-sandbox` + `network.client` + **`network.server`**.
  - `Info.Template.plist` — `CFBundleName`/`CFBundleDisplayName` = D6scend, `ITSAppUsesNonExemptEncryption=false`.
  - `Config/DefaultEngine.ini [/Script/MacTargetPlatform.XcodeProjectSettings]` already sets
    `BundleIdentifier=com.d6scend`, `CodeSigningPrefix=com.d6scend`, `ApplicationDisplayName=D6scend`.
  - Neither sandbox entitlements file as-shipped is MAS-correct: MAS needs `app-sandbox` +
    `network.client` and should **not** carry `network.server` unless actually used (Steam's
    local socket is the usual reason it creeps in — and MAS forbids Steam anyway, §5). A new
    `Sandbox.MAS.entitlements` (app-sandbox + network.client, **no** network.server) is the
    right artifact; see §5.
- **uetool already has the multi-backend `--store` selector** (Steam + Epic). MAS slots in as
  the third value with the same dispatch shape.
- **The host toolchain is present and was verified for this plan** (`xcrun --find` /
  `--help`): `altool`, `notarytool`, `productbuild`, and a current signing identity
  `Developer ID Application: Rodney Aiglstorfer (T5Y4JCK337)`. **No** Apple Distribution or
  3rd Party Mac Installer identity exists yet — that is a user prerequisite (§10).
- Baseline: `./.venv/bin/python -m pytest -q` → **106 passed**.

---

## 1. How Steam/Epic work today (the shape being mirrored)

Both backends are a single `upload(cfg, target, dry_run, …, custom_config=None)`:

1. Resolve the destination (`config.select_app` for Steam; `epic._require_epic` for Epic) —
   and `cli.release` resolves it **before** the hour-long build so a misconfig fails up front.
2. Guard required identity/credentials; read the version from `.version` (`_read_version`).
3. `content_root = cfg.stage_dir / cfg.stage_subdirs[target]`; on mac,
   `stage.normalize_mac_bundle` renames `<Project>-Mac-<Config>.app` → `<Project>.app`.
4. Build an argv **list** (never a shell string); emit paths `as_posix()`; run via
   `core.paths.run(cmd, dry_run)`, which **prints the full command** with
   `subprocess.list2cmdline`. **A dry run must print a complete, secret-free command.**
5. Print a **"NOT live yet — finish in the portal"** banner with the portal URL.
6. Secrets are **env-only**, never in a file, never in argv: Steam appends the password to
   argv only when present (acceptable for Steam); Epic passes the *env-var name*
   (`-ClientSecretEnvVar=…`) so the value never enters argv at all.

The MAS backend mirrors 1–5 exactly. For 6 it goes further than Steam: the App Store Connect
API key is **two non-secret ids in argv + a `.p8` file altool finds by directory convention**,
so no secret value ever reaches argv or the printed line (§3, §2).

---

## 2. The MAS pipeline vs. Steam/Epic — and the verified upload tool

A MAS build is **not** Developer-ID-notarized. `core/notarize.py` (sign hardened-runtime →
`notarytool submit` → `stapler staple`) **does not apply**. The MAS sequence is:

1. **Re-sign the staged `.app` inside-out** with an **Apple Distribution** identity (a.k.a.
   "3rd Party Mac Developer Application"), embedding **MAS sandbox entitlements** —
   **not** `--options runtime` (hardened runtime is a Developer-ID / notarization concept; MAS
   apps are sandboxed, not hardened-runtime-notarized).
2. **Embed the Mac App Store provisioning profile** as `Contents/embedded.provisionprofile`
   **before** signing the bundle (it is sealed by the signature).
3. **`productbuild --component <app> /Applications --sign "3rd Party Mac Developer Installer: …"`**
   to produce a **signed installer `.pkg`** (MAS requires a signed pkg — not a `.app`/`.zip`).
4. **Upload the `.pkg` to App Store Connect.** **No notarytool. No stapler.**
5. Print **"uploaded — now finish in App Store Connect"** (metadata, screenshots, submit for
   review): the direct URL `https://appstoreconnect.apple.com/apps`.

### Verified upload tool (checked against the live toolchain + Apple docs)

**Recommendation: `xcrun altool --upload-package <pkg> --type macos` authenticated with an
App Store Connect API key (`--api-key <KEYID> --api-issuer <ISSUERID>`).**

Grounding (each cited):
- **`altool` is deprecated only for *notarization*, not for App Store uploads.** Apple DTS
  (Developer Forums) states the deprecation "covers only macOS notarization"; altool "continues
  to be a recommended operation for other purposes" (App Store Connect / TestFlight uploads).
  So: notarytool is for the notary service (irrelevant to MAS); **altool is still the MAS
  upload path.** Confirmed `xcrun --find altool` resolves on this machine
  (`…/Xcode.app/Contents/Developer/usr/bin/altool`).
- **`--upload-package <file>` accepts a `.pkg`.** Verified locally from `xcrun altool --help`:
  `--upload-package <filepath>`, `--upload-app -f <filepath>` ("Path to the .ipa or .pkg"),
  `--validate-app <filepath>` (use to rehearse before a real upload). Examples in the same help
  use `--type macos`.
- **API-key auth uses `--api-key <KEYID> --api-issuer <ISSUERID>`** (both **non-secret**), and
  altool locates the secret `.p8` **by filename convention** — `AuthKey_<KEYID>.p8` in one of
  `./private_keys`, `~/private_keys`, `~/.private_keys`, or `~/.appstoreconnect/private_keys`.
  Verified from local `altool --help` (`--api-key <string>`, `--generate-jwt --apiKey …
  --apiIssuer …`, example `--api-key ABC123 --api-issuer <uuid>`). **This is the key property
  for us: the key id and issuer id go in argv (fine to print), and the private key is a file
  altool reads itself — uetool never reads, copies into memory, or prints it.**
- **TN3147** ("Migrating to the latest notarization tool") confirms the **same** App Store
  Connect API key `.p8` works for both altool and notarytool — so one key serves the user's
  existing Developer-ID notarize path and the new MAS path.

**Flag-spelling caveat to settle at implementation (≤5 min, `altool --help` on the build Mac):**
the help's parameter table lists `--api-key` / `--api-issuer` (hyphenated) while older Apple
docs show `--apiKey` / `--apiIssuer`. Current Xcode altool accepts the hyphenated forms; pin the
exact spelling from `--help` on the actual build machine before the first real upload. Also
confirm `--type macos` is accepted (the help examples use it; `osx` is **not** attested).

**Alternatives (documented, not chosen):**
- **Transporter / `xcrun iTMSTransporter`** — works, but heavier (ships inside Transporter.app),
  CLI vs GUI behavior has drifted (a forum ITMS-90529 case), and it offers nothing altool lacks
  for a single-pkg upload. Keep as a manual fallback in the README only.
- **App Store Connect API (REST) directly** — no benefit for a binary upload; altool already
  wraps it. Not worth the code.

Flag uncertainty is explicitly flagged in §9 as a pre-first-upload verification, exactly as the
Epic plan did for `-ClientSecretEnvVar`.

---

## 3. `core/appstore.py` — the backend (new; mirror steam.py/epic.py)

Public surface, parallel to `epic.py`:

```
upload(cfg, target, dry_run, custom_config=None) -> None
_require_appstore(cfg) -> AppStoreConfig     # reused by cli.release for the up-front check
```

**Host/platform guard (new vs. Steam/Epic).** MAS is macOS-only *and* mac-target-only. The
backend raises `SystemExit` unless `host_is_macos()` and `target == "mac"` — the same spirit as
`notarize` being mac-only (the CLI also guards this; §4). This guard is in the backend too so a
direct call can't bypass it.

**Steps (dry-run must print every command, secret-free):**

1. `appstore = _require_appstore(cfg)` — `SystemExit` when `cfg.appstore is None` or any of the
   required fields (bundle id, team id, app signing identity, installer signing identity,
   provisioning-profile path, ASC key id, ASC issuer id) is missing. Message names what's
   missing, like `epic._require_epic`.
2. Guards (real runs only; skipped in dry-run so wiring can be rehearsed with nothing present):
   provisioning profile file exists; entitlements plist exists; and the `.p8` is resolvable
   (see §3a). Signing-identity *presence in the keychain* is left to `codesign`/`productbuild`
   to report (same as notarize leaves it to `codesign`).
3. `version = _read_version(cfg)` (identical helper to steam/epic; factor to one place if easy,
   else copy — the Epic plan accepted the copy).
4. `content_root = cfg.stage_dir / cfg.stage_subdirs["mac"]`; `stage.normalize_mac_bundle(cfg,
   dry_run)`; locate the bundle with the **same `_find_app` logic as notarize** (consider moving
   `_find_app` to `stage.py` so both backends share it rather than duplicating).
5. **Embed the provisioning profile:** copy `appstore.provision_path` →
   `<app>/Contents/embedded.provisionprofile` (printed as `$ cp …`; a profile is not a secret).
6. **Sign inside-out with the MAS identity + entitlements.** Reuse the walk from
   `notarize._sign_inside_out` but parameterized:
   - identity = `appstore.app_identity` (Apple Distribution), **not** `cfg.apple_signing_identity`.
   - **entitlements** applied to the **main executable and the `.app`** via
     `--entitlements <appstore.entitlements_path>`; nested dylibs/helpers are signed **without**
     the entitlements (same inside-out order, deepest first).
   - **no `--options runtime`** (that's hardened-runtime for notarization).
   The cleanest refactor: generalize `notarize._codesign` / `_sign_inside_out` into
   `stage.py` (or a new `core/macsign.py`) taking `(identity, entitlements|None, hardened:bool)`,
   and have **both** `notarize.py` (identity=Developer ID, entitlements=None, hardened=True) and
   `appstore.py` (identity=Apple Distribution, entitlements=MAS plist, hardened=False) call it.
   This keeps the hard-won "sign inside-out, not `--deep`" lesson in one place.
7. `codesign --verify --deep --strict --verbose=2 <app>` (rehearse the seal before building the pkg).
8. **`productbuild`** the signed installer:
   `productbuild --component <app> /Applications --sign "<installer_identity>" <out.pkg>`
   into `.uetool/appstore/<Project>.pkg` (one dir, like steam's per-app dirs).
9. **Upload:** `xcrun altool --upload-package <out.pkg> --type macos --api-key <KEYID>
   --api-issuer <ISSUERID>` (optionally `--bundle-id <com.d6scend>` /
   `--bundle-version <version>` / `--bundle-short-version-string <…>` if the help/validate step
   shows they're wanted). Consider running `--validate-app <pkg>` first behind a note, or expose
   it as a separate `appstore` verb later — out of scope for v1.
10. Post-upload banner: **"Uploaded to App Store Connect. NOT submitted for review. Add
    metadata + screenshots and submit in App Store Connect"**, link
    `https://appstoreconnect.apple.com/apps`.

**`custom_config` handling.** MAS has no "build description" field like Steam, and the pkg
version comes from the bundle's `CFBundleVersion`. A custom layer (e.g. a MAS-specific layer,
§5) is cooked into the build like any other; there is nothing to tag in the upload, so
`custom_config` is accepted for signature-parity with steam/epic but only used to (a) pass
through for the release flow and (b) optionally appear in uetool's own console log. Document
that unlike Steam/Epic it does not alter the uploaded artifact's label.

### 3a. The `.p8` — never read, never printed

altool finds `AuthKey_<KEYID>.p8` by directory convention (§2). Design, in order of preference:
- **Preferred:** config holds only `asc_key_id` + `asc_issuer_id` (both non-secret, go in argv).
  The user places the `.p8` at `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8` once. uetool
  **never touches the file** — it just passes the two ids. (README documents the placement.)
- **Optional convenience:** config/env `asc_api_key_path` points at the `.p8` elsewhere. If set,
  uetool ensures altool can find it by creating a **symlink** into `~/.appstoreconnect/private_keys/`
  (a symlink does not read or copy the key bytes, so the "never read/echo/store the value" rule
  holds). The path itself is not a secret and may be printed; the **contents** are never read.
  Guard: if neither the conventional file nor `asc_api_key_path` resolves, `SystemExit` with the
  placement instructions. This keeps the uniform secret policy: value never in argv, never in a
  committed file, never printed.

---

## 4. Config — the `[appstore]` table (new)

Mirror `_load_epic` / `EpicConfig`. Add to `core/config.py`:

```python
@dataclass(frozen=True)
class AppStoreConfig:
    bundle_id: str            # com.d6scend
    app_sku: str              # the App Store Connect SKU (free-form, your own id)
    asc_app_id: str           # the numeric App Store app id (Apple-assigned), optional for upload
    team_id: str              # Apple team id (may reuse [apple] team_id)
    app_identity: str         # "Apple Distribution: Name (TEAMID)" / "3rd Party Mac Developer Application: …"
    installer_identity: str   # "3rd Party Mac Developer Installer: Name (TEAMID)"
    provision_path: str       # path to the .provisionprofile (non-secret)
    entitlements_path: str    # path to the MAS entitlements plist (non-secret)
    asc_key_id: str           # App Store Connect API key id (non-secret)
    asc_issuer_id: str        # ASC issuer id (non-secret)
    api_key_path: str | None  # optional path to the .p8 (NOT its contents); env override only for the path
```

- `_load_appstore(base, local)`: read `[appstore]` from both files (local wins per key), return
  `None` when nothing meaningful is set (mirror `_load_epic`'s "all blank → None"). Add
  `appstore: AppStoreConfig | None` to `Config` and the `load()` return.
- **No secret values in the table.** The `.p8` contents are never here; `api_key_path` is a path
  only (resolved from `[appstore]` or `UETOOL_ASC_API_KEY_PATH`), consistent with `ue_root` etc.
- **team_id reuse:** default `team_id` to the `[apple]` `team_id` when `[appstore]` omits it
  (same team), but allow an override.
- **Resolver `select_appstore` / `_require_appstore`** parallel to `select_app`/`_require_epic`,
  used by `cli.release` for the up-front check.
- Env overrides (optional, matching the Steam/Apple pattern): `UETOOL_ASC_KEY_ID`,
  `UETOOL_ASC_ISSUER_ID`, `UETOOL_ASC_API_KEY_PATH`. There is **no** secret env var for MAS
  (the `.p8` is a file altool reads), which is simpler than Steam/Epic.

**Update `uetool.toml.example`** with a commented `[appstore]` block (bundle_id, app_sku,
asc_app_id, team_id, app_identity, installer_identity, provision_path, entitlements_path,
asc_key_id, asc_issuer_id), a one-line "macOS-only; the .p8 lives in
~/.appstoreconnect/private_keys, never here" note, mirroring the existing `[epic]` comment block.

---

## 5. The MAS build variant — UE project vs. uetool (a prerequisite)

A MAS build differs from the storefront build in three ways. **Spelling out who owns each:**

| Concern | Owner | What |
|---|---|---|
| **No Steam integration** | **UE project** | The MAS binary must not link or load the Steamworks/OnlineSubsystemSteam framework (MAS review rejects it; it also wants `network.server`). *Finding:* the committed `D6scend.uproject` enables **no** Steam plugin and `Config/*.ini` has **no** `[OnlineSubsystemSteam]` block, so the committed tree is already Steam-free. Confirm whether the real Steam build enables OnlineSubsystemSteam via a per-machine/uncommitted plugin or a Steam custom layer; if so, the MAS variant must disable it. |
| **Sandbox entitlements** | **UE project** | Add a MAS entitlements file `Build/Mac/Resources/Sandbox.MAS.entitlements` = `app-sandbox` + `network.client` **only** (drop `network.server`, per Phase 0). Point the Mac target's **Shipping** entitlements at it (Project Settings → Platforms → Mac / Xcode Projects: `[/Script/MacTargetPlatform.XcodeProjectSettings]` entitlement keys, Development vs Shipping). Bundle id is already `com.d6scend`. |
| **Signing / provisioning / pkg / upload** | **uetool** (`core/appstore.py`) | Everything in §3. |

**Is `--custom-config` the right mechanism for the MAS variant?** Use the project's existing
`Config/Custom/<Name>` layer system **only if** the MAS build needs *ini* differences from the
storefront build (e.g. turning off a Steam subsystem that is configured in ini, or a
MAS-specific store/URL flag). From what is committed, the storefront `DefaultEngine.ini` is
already sandbox-ready and Steam-free, so a `Config/Custom/AppStore/` layer may be unnecessary.
**Recommendation:**
- The **entitlements** choice is a *build-target* setting (Development vs Shipping entitlement
  file in `XcodeProjectSettings`), **not** an ini layer — so `--custom-config` does **not**
  drive it. The MAS entitlements apply because the Shipping Mac target points at the MAS plist,
  or because **uetool re-signs with the MAS entitlements in §3 step 6 regardless of what UE
  baked in** (the re-sign is authoritative — this is the robust path and means the UE-side
  entitlement wiring is belt-and-suspenders, not load-bearing).
- If the real Steam build *does* enable Steam via ini/plugin, add a `Config/Custom/AppStore`
  layer (or better, make Steam opt-in only in the storefront path) and pass
  `--custom-config AppStore` for MAS. Treat this as an **open question for the user** (does the
  shipping Steam build enable OnlineSubsystemSteam, and where?).

Net: **uetool's §3 re-sign makes the sandbox/entitlements correct by construction.** The UE
project work that genuinely must happen first is (a) ensure the MAS build links no Steam
framework, and (b) create `Sandbox.MAS.entitlements`. Both are small and belong to the user /
a follow-up UE task, not to uetool.

---

## 6. CLI — `--store appstore` (macOS + mac-target only)

Edit `core/cli.py`:
- `_add_store`: extend choices to `["steam", "epic", "appstore"]` (default stays `steam`, so
  every existing command/test is unchanged). Update the help text.
- **`upload`**: add an `elif args.store == "appstore": appstore_mod.upload(cfg, args.platform,
  args.dry_run)` branch.
- **`release`**: in the up-front destination check, add
  `elif args.store == "appstore": appstore_mod._require_appstore(cfg)` **plus the host/platform
  guard** — error (like notarize) when `host_platform() != "mac"` or `args.platform != "mac"`.
  Then: bump → package → **SKIP `notarize`** when `store == "appstore"` (MAS is not
  Developer-ID-notarized) → `appstore_mod.upload(...)`. Concretely the existing
  `if args.platform == "mac": notarize(...)` becomes
  `if args.platform == "mac" and args.store != "appstore": notarize(...)`.
- `--app` stays Steam-only (help already says so); appstore ignores it.
- Update the module docstring usage block to show `--store appstore` and the mac-only note.

**Guard placement:** put the "appstore ⇒ macOS host + mac platform" refusal in **both** the CLI
(fast, friendly) and the backend (§3, can't be bypassed), exactly as notarize is guarded in the
CLI and relies on the Apple tools existing.

---

## 7. UI

- **Build tab (`ui/tab_build.py`)**: add `"appstore"` to the `self.store` combo. Enable the
  appstore option **only on a mac host** (`ctx.host == "mac"`) — disable/grey it elsewhere with
  a tooltip ("Mac App Store publishing requires macOS"). When `store == "appstore"`, force
  platform to `mac` (and disable the platform combo, or validate it), and disable `--app` (as it
  already does for epic). Add an `appstore_configured()` accessor (→ `cfg.configured_appstore()`).
  The upload confirm dialog gets an appstore branch: "This signs a MAS build, builds a signed
  .pkg and uploads it to App Store Connect. It won't be submitted for review until you do that in
  App Store Connect. Continue?"
- **Config tab (`ui/tab_config.py`)**: a new "Mac App Store" `QGroupBox` with the non-secret
  `[appstore]` fields (bundle id, SKU, ASC app id, team id, app identity, installer identity,
  provisioning-profile path [with a Browse… file picker], entitlements path [Browse…], ASC key
  id, ASC issuer id, and the optional `.p8` path [Browse…]). **No `SecretRow`** — MAS has no
  secret-string input (the `.p8` is a file altool reads; its *path* is a normal field). A muted
  note: "macOS only. The App Store Connect private key (.p8) is read by Apple's altool from
  ~/.appstoreconnect/private_keys; uetool never reads it." Grey the whole group on a non-mac host
  like the Apple fields.
- **`ui/configstore.py`**: add the `[appstore]` fields to `FIELDS` (all `BASE`, kind `text`/`path`;
  `provision_path`/`entitlements_path`/`api_key_path` are `path`), an `APPSTORE_KEYS` map and
  `APPSTORE_IDS` tuple mirroring `EPIC_KEYS`/`EPIC_IDS`, a `configured_appstore()` predicate
  ("all required ids present"), and `problems()` validation ("fill all MAS fields or none",
  mirroring the Epic partial-config warning).
- **`ui/commands.py`**:
  - `BuildSpec.store` already exists; no new field (appstore is just a `store` value). Validation:
    in `validate(...)`, when `store == "appstore"`: require `appstore_configured` (error if
    False, mirroring the epic branch) **and** require host==mac + platform==mac (new errors).
    Thread an `appstore_configured: bool | None` param alongside `epic_configured`.
  - `build_argv`: `--store` is already emitted for any non-`steam` value, so `appstore` flows
    through unchanged. Verify `--app` is suppressed (it is gated by `accepts(...,"app")` + store).
  - **`CAPS` needs no change** — `store` is already in `upload`/`release` caps; `appstore` is a
    value, not a new flag. `test_caps_match_cli_parser` keeps passing because `--store` is still
    the only new option string (its *choices* widening doesn't affect the flagmap).
- **`ui/doctor.py` (Setup tab)**: add a "Mac App Store" check (NA when `[appstore]` unset or host
  ≠ mac; FIX when partial / provisioning profile or entitlements file missing / `.p8` not found
  in a conventional dir; PASS when all present), mirroring the Epic check block. Reuse the
  `security find-identity`-free approach notarize uses (don't shell out in the doctor; just check
  files + config strings).

---

## 8. Tests

Mirror `tests/test_epic.py` in a new `tests/test_appstore.py`, monkeypatching `appstore.run`
and the signing helpers so no real codesign/productbuild/altool executes:

- `test_not_configured_raises` — no `[appstore]` → `SystemExit`.
- `test_requires_mac_host_and_mac_target` — monkeypatch host to non-mac → `SystemExit`;
  `target="win"` → `SystemExit`.
- `test_builds_codesign_productbuild_altool_argv` — capture the **sequence** of commands (the
  test double appends each `run` call) and assert:
  - the inside-out codesign uses the **Apple Distribution** `app_identity` and
    `--entitlements <mas plist>` on the bundle, and **no** `--options runtime`;
  - `productbuild --component … /Applications --sign "<installer_identity>" <pkg>`;
  - `altool --upload-package <pkg> --type macos --api-key <KEYID> --api-issuer <ISSUERID>`.
- `test_no_secret_in_argv_or_output` — **the key safety test**: assert no `.p8` contents and no
  secret value appear in any captured argv or printed line; only the key id / issuer id (ids,
  not secrets) appear. (The `.p8` is never read, so there is nothing to leak — assert the file
  is not opened by the backend, e.g. by pointing `api_key_path` at a file whose bytes are a
  sentinel and asserting the sentinel never appears in output.)
- `test_provision_profile_embedded` — assert the backend copies the profile to
  `Contents/embedded.provisionprofile` before signing (check the `cp`/copy was issued with the
  right dest).
- `test_app_launch_bundle_located` / decorated-bundle handling — reuse the staged `Info.plist`
  decorated-executable fixture from `test_epic.py` to prove `_find_app` + normalize work.
- `test_p8_resolution` — conventional path present → no error; absent and no `api_key_path` →
  `SystemExit` with placement hint.
- Config tests in `tests/test_config.py`: `[appstore]` loads into `AppStoreConfig`; absent →
  `None`; team_id falls back to `[apple]`.
- `tests/test_commands.py`:
  - extend/confirm `test_caps_match_cli_parser` still passes (the `--store` choice widening is
    invisible to the flagmap; **no flagmap change needed** — note this explicitly in the test
    comment so a future reader doesn't "fix" it).
  - `test_store_appstore_in_argv` — `--store appstore` is emitted (and steam still omitted).
  - `test_validate_appstore_requires_config_and_mac` — error when not configured, error on a
    non-mac host / non-mac platform, OK when configured on mac.
- `tests/test_doctor.py`: an appstore-check block mirroring the epic doctor tests.

Keep the existing 106 tests untouched and green; the suite should grow, not change.

---

## 9. README

Add a "Mac App Store (`--store appstore`)" section after the Epic section:
- **Prerequisites** (§10): Apple Distribution + 3rd Party Mac Developer Installer certs in the
  login keychain; a **Mac App Store provisioning profile** for `com.d6scend`; an **App Store
  Connect API key** (issuer id + key id + `.p8`); an App Store Connect **app record** for
  `com.d6scend`.
- **`.p8` placement**: `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8` (altool's convention);
  uetool never reads it. Note the optional `UETOOL_ASC_API_KEY_PATH` symlink convenience.
- **`[appstore]` table** example (non-secret only).
- **Usage**: `uetool release --platform mac --store appstore` (bump → package → **MAS-sign →
  productbuild → altool upload**, *skipping* Developer-ID notarize); `uetool upload --platform
  mac --store appstore`.
- **Differences to call out**: MAS is **macOS-only** and **not notarized/stapled**; the app is
  **sandboxed** (app-sandbox + network.client), ships **no Steam**, and the upload is **not a
  submission** — metadata, screenshots and review are manual in App Store Connect.
- **Flag caveat**: confirm `--api-key`/`--api-issuer` spelling and `--type macos` from
  `xcrun altool --help` on the build Mac (§2).
- **Alternatives**: one line noting Transporter / `xcrun iTMSTransporter` as a manual fallback.

Also update the top-of-README one-liner and the Usage synopsis block to include
`--store steam|epic|appstore`, and the "Platform notes (hard-won)" list with the MAS vs
Developer-ID distinction (sandbox + Apple Distribution + signed pkg, **no** hardened runtime /
notarytool / stapler).

---

## 10. Out of scope / non-automatable, and the sandbox checklist

**uetool's job ends at a successful altool upload.** Explicitly NOT automated:
- App Store Connect **metadata** (name, description, keywords, category, pricing, age rating,
  privacy nutrition labels, export-compliance answers).
- **Screenshots** and preview media.
- **Submitting for review** and responding to reviewer feedback.
- Creating the **App Store Connect app record**, certificates, and the provisioning profile
  (these are user prerequisites, below).
- TestFlight / phased release / version management inside App Store Connect.

**Remaining sandbox-thoroughness checklist** (feasibility is proven; these are pre-ship
verifications to run once in a sandboxed build, watching `log show --predicate 'eventMessage
CONTAINS "Sandbox"'`): **gamepad** input (DualSense/Xbox), **audio** (MetaSound layered music
output), **demo mode** (URL-detected demo + `Config/Custom/Demo` layer), **kiosk mode** (idle
watchdog, teaser loop), and **any file I/O outside the container** (saves, logs, catalog cache —
all must land in the app container or user-selected locations). Only `network.client` is required;
confirm `network.server` is genuinely unused once Steam is out.

**User prerequisites (must be obtained before the first real upload):**
1. **Apple Distribution** certificate (a.k.a. "3rd Party Mac Developer Application") in the login
   keychain. *(Only "Developer ID Application: Rodney Aiglstorfer (T5Y4JCK337)" exists today.)*
2. **3rd Party Mac Developer Installer** certificate in the login keychain.
3. A **Mac App Store provisioning profile** for App ID `com.d6scend` (`.provisionprofile`).
4. An **App Store Connect API key**: issuer id + key id + the `.p8` file (placed per §3a).
5. An **App Store Connect app record** for `com.d6scend` (bundle id registered, SKU chosen).

---

## 11. Effort estimate + suggested order

Assumes the user obtains the prerequisites in parallel (they gate only the *first real upload*,
not the code/tests, which run in dry-run).

| # | Work | Est. |
|---|---|---|
| 1 | **Refactor the signing walk** out of `notarize.py` into a shared helper taking `(identity, entitlements, hardened)`; keep notarize green. | 0.5 day |
| 2 | **`core/config.py`**: `AppStoreConfig` + `_load_appstore` + `select/_require_appstore` + env overrides; `uetool.toml.example`. | 0.5 day |
| 3 | **`core/appstore.py`**: embed profile → MAS-sign → verify → productbuild → altool upload → banner; host/platform + `.p8` guards. | 1 day |
| 4 | **`core/cli.py`**: `--store appstore`, mac-only guard, skip-notarize in release. | 0.25 day |
| 5 | **Tests** (`test_appstore.py`, config/commands/doctor additions); keep 106 green. | 1 day |
| 6 | **UI** (tab_build store option + mac-gating, tab_config group, configstore fields, doctor check). | 1 day |
| 7 | **README** + example + platform notes. | 0.5 day |
| 8 | **Verify** altool flag spelling / `--type macos` / `--validate-app` on the build Mac; settle Steam-in-MAS open question. | 0.25 day |
| 9 | **UE project**: `Sandbox.MAS.entitlements`, Shipping entitlement wiring, confirm no Steam link (user / follow-up UE task). | 0.25–0.5 day |
| 10 | **First real smoke upload** once prerequisites land: `release --platform mac --store appstore`, confirm the build appears in App Store Connect. | 0.5 day |

**Total: ~5–6 days of uetool work** (items 1–8), plus a small UE-side task (9) and a gated smoke
upload (10). The critical path is `core/appstore.py` + its tests; the UI and README are
mechanical mirrors of the Epic work.

**Suggested order:** 1 → 2 → 3 → 4 → 5 (land a dry-run-tested, mac-guarded CLI backend first) →
6 → 7 → 8 → 9 → 10.

---

## 12. Open questions for the user

1. **Does the shipping Steam build of D6scend enable OnlineSubsystemSteam / link the Steamworks
   SDK, and where?** (The committed tree does not — confirm it's not added per-machine or via an
   uncommitted plugin.) Determines whether a `Config/Custom/AppStore` layer or a plugin
   gate is needed (§5).
2. **Which entitlements for MAS** — confirm `app-sandbox` + `network.client` only (drop
   `network.server`), matching the proven Phase 0, once Steam is out (§5).
3. **One MAS app or variants?** MAS has no "demo app" like Steam; a demo on macOS is typically a
   separate app record or an in-app unlock. Assume **one** `[appstore]` target for now (like
   `[epic]`'s single artifact); promote to `[appstore.<name>]` later only if needed.
4. **App Store Connect app id / SKU** values for `com.d6scend`.

## 13. Sources

- altool deprecated for notarization only (still the App Store upload path): Apple Developer
  Forums — https://developer.apple.com/forums/thread/709364 and
  https://developer.apple.com/forums/thread/742588
- TN3147 "Migrating to the latest notarization tool" (same ASC API key `.p8` works for altool and
  notarytool): https://developer.apple.com/documentation/technotes/tn3147-migrating-to-the-latest-notarization-tool
- altool usage (`--upload-package`, `--type macos`, `--api-key`/`--api-issuer`, `.p8` by
  convention): Apple "appsaltool" help — https://help.apple.com/asc/appsaltool/ — and **verified
  locally** via `xcrun altool --help` on this build Mac (2026-10-25).
- Toolchain presence verified locally: `xcrun --find altool|notarytool`, `which productbuild`,
  `security find-identity -v -p codesigning` (2026-10-25).
