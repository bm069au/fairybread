# Fairybread — Beta v0.95a (Win_x64) Changelog
**Release Date:** 2026-11-26
**Version:** `0.95a` (`0.95.1.0`)

## Summary of Changes in `v0.95a`
1. **▲ Universal Direct & OpenRouter Mistral Upgrade (`mistral_provider.py`, `palace_config.py`, `provider_loader.py`, `voice_service.py`, `attachment_service.py`):**
   - Upgrades direct Mistral default from `codestral-latest` to general-purpose **`mistral-medium-latest`** with profile-aware routing (`Light Chat` → `mistral-small-latest`, `Generalist`/`Work Mode` → `mistral-medium-latest`, `Deeper Chat` → `mistral-large-latest`, `Code AIs` → `codestral-latest`), native vision (`image_url`), Magistral thinking-chunk sanitization, and `403`/`404` model failover.
   - Adds **Mistral Voxtral** neural TTS (`voxtral-mini-tts-latest`) and microphone transcription (`voxtral-mini-transcribe-3`), plus automatic **Mistral OCR (`mistral-ocr-latest`)** fallback whenever a scanned image-only PDF extracts zero selectable text.
2. **🚦 Accurate Failure-Code Bottom-Bar Status Chips (`orchestrator.py`, `palace_gui.py`):**
   - Replaces catch-all `Limited` badges with exact HTTP/error classification: **`No Plan`** (amber `#d29922` for HTTP `402` / missing billing plan or zero balance), **`Auth Err`** (red `#f85149` for `401`/`403` bad/unauthorized keys), **`Bad Model`** (red `#f85149` for `404` retired/invalid models), **`Limited`** strictly for true `429`/`413` rate/size limits, and **`Failed`** for network/runtime errors.
3. **🎨 19 Built-In Themes, Bundled Picture Artwork & Recent-First Scrollable Picker (`palace_theme.py`, `palace_config.py`, `palace_gui.py`, `build_release.py`, `theme_assets/*.png`):**
   - Expands to 19 built-in themes with bundled high-resolution PNG artwork (`deep_ocean.png`, `royal_amethyst.png`, `velvet_rose.png`), widened `60%–96%` washout range (auto-activating at `82%` on picture-backed themes), and a recent-first scrollable 11-row `View → Theme` picker.
4. **📧 Email Settings Reorganization, Gmail `"recent"`/`"unread"` Search Fix & Plain-English Silent Tool Follow-Ups (`email_service.py`, `palace_config.py`, `orchestrator.py`, `synthesizer.py`, `palace_gui.py`):**
   - Reorganizes `Options → Email & Alerts` into `1. Email Account & AI Access` (with live status banner, `🔌 Test Connection`, and `📧 Send Test Email`) and `2. Optional Completion Alerts`; fixes Gmail `X-GM-RAW` natural-language `"recent"`/`"unread"` inbox queries; executes `[EMAIL_TEST]`, `[EMAIL_SEARCH]`, `[EMAIL_DRAFT]`, and confirmation-gated `[EMAIL_SEND]` tags silently with automatic synthesis follow-up; and defaults all agent replies to plain, non-technical everyday English unless technical depth is requested.
5. **🪟 Python 3.13 / PySide6 Dialog Close `[ ✕ ]` Button Fix (`palace_gui.py`, `setup_wizard.py`, `install_fairybread_beta.py`, `uninstall_fairybread.py`):**
   - Replaces `~Qt.WindowType.WindowContextHelpButtonHint` bitmask inversion (which cleared `WindowCloseButtonHint` in Python 3.13/Shiboken6 and disabled Win32 `SC_CLOSE`) with explicit `setWindowFlag(..., False)` calls so every dialog's top-right `[ ✕ ]` close button works natively.
6. **📖 Beginner-Friendly Setup Handbook & Unified Physical Distro License (`USER_GUIDE.md`, `LICENSE.txt`, `LICENSE.md`, `build_release.py`, `fairybread_setup.iss`):**
   - Overhauls `USER_GUIDE.md` with an uncluttered 2-path Recommended First Setup (Free smoke test with honest limitations vs OpenRouter + Graphics + 1 Top-Tier Voice Engine), plain-English *"What Do I Say?"* prompt table, 15-provider and 9-voice comparison tables (including Anthropic anti-roleplay notes), bottom-bar chip guide, and bug-reporting instructions.
   - Ships both plain-text `LICENSE.txt` (wired to Inno Setup's `LicenseFile=` screen) and `LICENSE.md` in all distros with updated 2-seat / 3+ seat commercial terms, anti-bypass restrictions, contributor grant, GNU LGPLv3 (`PySide6`) notices, third-party API disclaimer, and South Australia governing law.

---

# Fairybread — Beta v0.95 (Win_x64) Changelog
**Release Date:** 2026-11-25
**Version:** `0.95` (`0.95.0.0`)

## Summary of Changes in `v0.95`
1. **🧭 LibreOffice-Style 7-Tab Menu Bar & Expandable `Options — Fairybread` Tree (`palace_gui.py`, `palace_theme.py`):**
   - Replaces scattered menu/toolbar clutter with a clean 7-tab desktop menu bar (`File  Edit  View  Council  Audio  Tools  Help`), keeping `Audio` as a dedicated top-level menu and `Tools → Options… (Alt+F12)` as the single doorway to settings.
   - Reorganizes `Options — Fairybread` into an expandable hierarchical tree (`▾ Fairybread`, `▾ Council` including `Response Timing`, `▾ Providers`, `▾ Voice & Audio`, `▾ Image Engine`, `▾ Memory Palace`) with neutral desktop palette styling, `[ Help ]` + `[ Reset Page ] [ Cancel ] [ Apply ] [ OK ]` footer, and plain-English `External Apps (MCP)` badges/tooltips.
2. **🧠 Single Auto-Saving `Living Profile…` (`palace_gui.py`, `memory_service.py`):**
   - Consolidates all Living User Profile access into one `Living Profile…` button under `Options → Memory Palace → Memory & Profile` (removing duplicate buttons from `Tools` and the right-hand `Memory` panel) and automatically saves open direct edits on window close so agent-updated and user-edited profiles stay 100% synchronized.
3. **⚡ Response Timing Presets, Arrival-Order Dispatch & Plain-English Failure Tooltips (`palace_config.py`, `dispatcher.py`, `orchestrator.py`, `palace_gui.py`):**
   - Adds `Quick (60s / 0s / 30s)`, `Standard (180s / 120s / 90s)`, and `Deep (300s / 240s / 90s)` phase ceilings (`straggler_grace_sec: 0`), 15s connection handshakes, live `on_activity` heartbeat tracking, arrival-order result recording, and greyed-out failed agent chips with plain-English `What went wrong:` / `How to fix:` hover tooltips.
4. **🎨 4 New WCAG-AAA Themes & HiDPI Washed-Out Background Engine (`palace_theme.py`, `palace_config.py`, `palace_gui.py`):**
   - Adds `Deep Ocean Abyss` (dark blue & ocean), `Royal Amethyst` (purple), `Velvet Rose` (dark pink), and `Sakura Silk` (soft light pink), plus a 60-FPS HiDPI pre-baked `75%–96%` washed-out background picture engine across Chat, Left Sidebar, and Memory panels.
5. **🎙️ Low-Latency Voice Mode, `{ } Code` Voice Inspection & Windows Compliance (`voice_companion.py`, `voice_service.py`, `voice_visualizer.py`, `setup_wizard.py`, `palace_gui.py`):**
   - Eliminates Voice Mode barge-in lock inversion, fixes instant live 3D Avatar shape/palette switching, wires `{ } Code` local Python source lookup into both `Talk Only` and Live Voice Mode, adds persistent TLS pools + `950 ms` silence cutoff + low-latency reasoning for snappy voice replies, ensures all configured AIs stay active after every run & on `+ New Conversation`, and enforces native Windows `[ □ ] [ ✕ ]` / `Esc` / `Cancel` compliance across all dialogs.
6. **📎 Unlimited Multi-Batch Attachments, Clean Daylight Contrast, First-Ask Drawing & OpenAI Retirement Failover (`attachment_service.py`, `openai_provider.py`, `gemini_provider.py`, `orchestrator.py`, `palace_theme.py`, `palace_gui.py`):**
   - Removes per-turn attachment count caps, improves Clean Daylight theme readability, rescues `[GENERATE_IMAGE]` tags for reliable first-ask image rendering, removes false autopatch notices, and adds automatic OpenAI model retirement failover (`gpt-5` / `o3` → `gpt-6.2-sol` / `gpt-6-luna` / `gpt-6.2-astra`).
7. **🎯 Exclusive Solo-AI Menu Selector & Full Mistral via OpenRouter (`palace_gui.py`, `palace_config.py`, `provider_loader.py`, `cost_service.py`):**
   - Separates `Choose AIs ▾` / `Council` menu selection into structured sections (`Profiles & AI Squads`, `Multi-AI Selection`, `Solo AI`) where clicking an individual AI selects **only** that 1 AI in `Direct` (1-round) mode and updates the pill immediately, while keeping the bottom `Agents:` bar chips as quick individual on/off switches.
   - Upgrades OpenRouter presets and routed Mistral seats from narrow `Codestral` to **full general-purpose Mistral** (`mistralai/mistral-medium-3.1` on Balanced, `mistralai/mistral-large-2411` on Flagship, `mistralai/mistral-small-3.1-24b-instruct:free` on Free), while reserving `Codestral` (`mistralai/codestral-2508`) as an automatic override for `💻 Code AIs`.

---

# Fairybread — v0.94 (Win_x64) Changelog
**Release Date:** 2026-11-23
**Version:** `0.94` (`0.94.0.0`)

## Summary of Changes in `v0.94`
1. **🎨 OpenAI Flagship Graphics & Pixel-Anchored Editing (`palace_config.py`, `cost_service.py`, `openai_provider.py`, `gemini_provider.py`, `orchestrator.py`, `palace_theme.py`, `palace_gui.py`):**
   - Defaults image generation to OpenAI **`gpt-image-2.6-sunburst`** (flagship) and **`gpt-image-2.6-flare`** (fast drafts), with **`chatgpt-image-latest`**, **`openrouter:openai/gpt-5.4-image-2`**, Google **`gemini-3-pro-image`** / **`gemini-3.1-flash-image`**, and FLUX fallbacks, selectable in **Settings → ⚡ Agent Defaults**.
   - Adds 3 configurable pipeline modes (`single_vision`, `direct`, `prompt_duo`), pixel-anchored prior-render & multi-reference `image[]` editing, visual critique follow-up routing, OpenRouter Chat Completions `image_url` support with plain-text fallback retry, secret-redacted HTTP error bodies in `image_diagnostics.log`, and updated render costs (`flux-1-schnell`, `openai/gpt-5-image-mini`).
2. **🧠 Two Chat Profiles (`Light Chat (Free / Fast)` vs. `Deeper Chat (Paid — Reasoning & Long)`) (`palace_config.py`, `dispatcher.py`, `orchestrator.py`, `palace_gui.py`):**
   - Adds configurable `context_depth` (`standard` 12K / `deep` 36K / `extended` 64K) and per-profile `model_overrides` with automatic Direct API ↔ OpenRouter slug translation (`resolve_profile_model_override()`).
3. **◎ Optional 3-Mode 3D Audio-Reactive Voice Avatar (`voice_visualizer.py`, `voice_service.py`, `palace_gui.py`, `build_release.py`):**
   - Adds **Off / Windowed / Full Screen Stage** geometric hologram visualizer (`6` shapes, palette presets, real-time TTS FFT audio telemetry, autohide dock, and tray/close cleanup).
4. **⚙ Scrollable Auto-Save Settings & Windows 11 SpinBox Fix (`palace_theme.py`, `palace_gui.py`):**
   - Fixes overlapping up/down arrows on `QSpinBox` under Windows 11 and makes Settings pages scroll smoothly with viewport-clamped auto-save.
5. **💬 Natural Tangents, Humor Calibration & Deduplication (`palace_config.py`, `search_service.py`, `dispatcher.py`, `synthesizer.py`, `orchestrator.py`, `voice_companion.py`, `palace_gui.py`):**
   - Adds configurable **Humor** calibration (`No Humor` / `Minimal` / `Average` / `High Humor`) across Chat and Talk Mode, negated draw-intent guard, scoped autopatch confirmation, 1-AI casual banter fast-path, and inline history deduplication.
6. **🌦️ Weather Radar Map Geocoding & Headless Bitmap HUD Fixes (`search_service.py`):**
   - Expands `_WEATHER_STOPWORDS`, anchors place candidates on prepositions, rejects phonetic geocoding mismatches, fetches radar tiles across 6 concurrent workers, and adds a thread-safe 5×7 bitmap HUD fallback when Pillow/`QFont` is unavailable.
7. **🧭 Setup Wizard First-Run Fix, External CLI Path Detection & Audit Fixes (`credential_store.py`, `setup_wizard.py`, `palace_gui.py`, `local_cli_provider.py`, `catalog_sync.py`, `fairybread_mcp.py`):**
   - Implements missing `CredentialStore.list_providers()`, restricts Setup Wizard auto-launch to fresh installs with zero configured AI agents (`has_any_configured_ai_agents()`), persists dismissal via `setup_wizard_completed`, and excludes non-billing `email_connector` from Spend & Billing.
   - Detects CLIs in `%USERPROFILE%\.local\bin` and `%APPDATA%\npm` (plus inline install hints and **🔄 Re-scan CLIs** button), and fixes missing imports/path unpacking in `catalog_sync.fetch_openrouter_live_catalog()` and `fairybread_mcp.cleanup_external_mcp_for_dir()`.

---

# Fairybread — v0.93 (Win_x64) Changelog
**Release Date:** 2026-11-22
**Version:** `0.93` (`0.93.0.0`)

## Summary of Changes in `v0.93`
1. **🧭 Guided Setup Wizard & Selective Backup Restore (`setup_wizard.py`, `backup_service.py`, `palace_gui.py`):**
   - Added `GuidedSetupWizardDialog` with workflow usage profiles (*Light Chat & Research*, *Assignments & Writing*, *Coding*, or *Everything*), a clickable tick-off API key checklist, and first-run + Settings re-launch (`Settings → Launch Setup Wizard…`).
   - Added independent selective backup restore (`restore_credentials`, settings, and memory) in both Setup Wizard and Settings.
2. **🌐 All-in-One Hybrid OpenRouter Hub (`palace_config.py`, `providers.py`, `openai_provider.py`, `provider_loader.py`, `catalog_sync.py`, `voice_service.py`):**
   - Single DPAPI `openrouter` key auto-fills unconfigured Council seats across `free`, `balanced`, and `flagship` preset tiers while keeping direct provider keys at top priority.
   - Added exact `usage.cost` extraction, `/api/v1/credits` + `/api/v1/models` live syncing, and OpenRouter image/audio fallback with `.cost` sidecar badges.
3. **💵 3-Layer Live Cost Tickers (`cost_service.py`, `setup_wizard.py`, `palace_gui.py`):**
   - Added `GlobalBillingLedger` (`billing_ledger.json`) with cumulative & per-provider resettable spend dashboard (`SpendBillingDialog`, clickable bottom spend bar), per-picture cost badges, and live ongoing Voice Mode cost badge in `composer_live_bar`.
4. **🌦️ Live Weather Radar Map (`search_service.py`, `palace_theme.py`, `orchestrator.py`, `voice_service.py`):**
   - Enriched `fetch_live_weather_bundle()` and `render_live_weather_map_png()` (RainViewer `z=7` precipitation radar + CartoDB Dark Matter `z=7` + Open-Meteo UV, gusts, sunrise/sunset, 12h hourly, and 7-day forecast) with Pillow + `PySide6.QtGui.QImage` fallback, inline `[WEATHER_MAP]` card rendering, and speech stripping.
5. **🏛️ Free-Agent Local Memory Fast-Recall (`$0.00`) (`memory_service.py`, `orchestrator.py`):**
   - Added `find_high_confidence_local_recall()` so high-confidence local SQLite matches skip paid web search and route 1 round to free-tier agents (`$0.00`), with explicit `"recheck with full council"` bypass.
6. **💬 Natural Conversational Synthesizer, Steer/Queue & Zero-Clipping Status Chips (`synthesizer.py`, `dispatcher.py`, `orchestrator.py`, `palace_gui.py`):**
   - Passed `personalization_context`, compact user profile summary, `conversational_scale`, and multi-turn `history_messages` into `PalaceSynthesizer`, plus a 1-voice fast-path for brief casual banter.
   - Added pure **Steer / Queue** composer dropdown (`busy_submit_mode`) and context/reasoning-aware straggler cutoff scaling with honest amber `Cutoff`/`Timeout` chips and width-balanced zero-clipping agent bar layout.
7. **📦 64-Bit Inno Setup `Update only` Hot-Reboot Installer, MSIX & Contributors (`fairybread_setup.iss`, `build_release.py`, `palace_config.py`, `palace_gui.py`):**
   - Updated version to `0.93` (`0.93.0.0`), added default `Update only` installer option + `/UPDATEONLY` silent relaunch, Ed25519 + SHA-256 verification (`integrity_manifest.json`, `SHA256SUMS.txt`, `verify.html`), Microsoft Store MSIX packaging (`0.93.0.0`), 1-click in-app update download dialog, and `Community Contributors` in About.

---

# Fairybread — Beta v0.92e (Win_x64) Changelog
**Release Date:** 2026-11-22
**Version:** `v0.92e_beta_Win_x64`

## Summary of Changes in `v0.92e`
1. **🗑️ Microsoft-Guidelines-Compliant Uninstaller & Windows Installer Upgrade (`uninstall_fairybread.py`, `install_fairybread_beta.py`, `fairybread_icon.ico`):**
   - Replaced the old 4-line uninstaller stub with a complete standalone uninstaller ([uninstall_fairybread.py](uninstall_fairybread.py)) supporting interactive GUI confirmation (`UninstallString` via `pythonw.exe`) and non-interactive silent uninstall (`QuietUninstallString` with `--quiet`, `/S`, and optional `--purge-data`), plus automatic UAC elevation for `Program Files` / `HKLM` installs.
   - Tracks installations via `install_manifest.json` so uninstall stops only processes running inside that exact install folder, removes all installed files + Desktop/Start Menu `.lnk` shortcuts + `HKCU`/`HKLM` (64-bit) Uninstall registry entries, removes only matching External Agent Bridge (MCP) links (without breaking sibling Fairybread installs), preserves user data (`%LOCALAPPDATA%\Palace`) by default with explicit opt-in purge, and uses a detached `%TEMP%` self-delete + `MoveFileExW` fallback to remove the folder cleanly with zero leftovers.
   - Added multi-resolution `fairybread_icon.ico` (`16, 32, 48, 64, 128, 256 px`), full Windows *Settings → Apps* (`ARP`) registry metadata (`EstimatedSize`, `InstallDate`, `QuietUninstallString`, `URLInfoAbout`, `HelpLink`, `Comments`, `DisplayIcon` → `.ico`, `NoModify=1`, `NoRepair=1`), UAC elevation check in `install_fairybread_beta.py`, and scoped `QFrame` installer cards.

---

# Fairybread — Beta v0.92d (Win_x64) Changelog
**Release Date:** 2026-11-22
**Version:** `v0.92d_beta_Win_x64`

## Summary of Changes in `v0.92d`
1. **✍️ Native Windows Live Spellcheck & Right-Click Suggestions (`spellcheck_service.py`, `palace_config.py`, `palace_gui.py`):**
   - Added zero-dependency native Windows Spell Checking COM integration (`MsSpellCheckingFacility.dll` / `ISpellCheckerFactory` via `ctypes`, preferring `en-AU` with `en-US`/`en-GB` fallback).
   - Added `SpellCheckHighlighter` (`SpellCheckUnderline` red squiggles, skipping the word currently under your cursor while typing) and `Composer.contextMenuEvent()` top-of-menu spelling suggestions, **Add to Dictionary**, and **Ignore Word**, while skipping `/commands`, `@mentions`, URLs, file paths, `snake_case`/`camelCase` tokens, acronyms, inline backticks, and built-in domain terms (`Fairybread`, `DeepSeek`, `Jellyfin`, etc.).
   - Added persistent `spellcheck_enabled` setting (`DEFAULT_UI_SETTINGS`, default `True`) and Settings → General toggle.
2. **📦 Backup & Restore + Settings Card Border & Width Cleanup (`palace_gui.py`):**
   - Scoped all 17 Settings `QFrame` cards via `_style_settings_card()` (`QFrame#<objectName>`) with layout margins so plain child `QLabel`s (`Normal Mode Cap:`, `100 MB`, `Unlimited`, etc.) no longer inherit dark bordered boxes.
   - Placed `Fairybread Storage Folder:` above its input row so the full folder path displays without clipping, narrowed the cap edit box (`165 px → 115 px`), and trimmed Backup & Restore action buttons (`Browse…`, `🚚 Move Data`, `💾 Save As…`, `🔍 Open`, `🗑 Delete`, `↻ Refresh`, `📦 Backup (.zip)…`, `♻ Restore (.zip)…`, `↺ Reset Defaults…`) for zero clipping at `960×720`.
3. **💬 Chat Sidebar Topic Row Spacing (`+1 px`) (`palace_gui.py`):**
   - Bumped `refresh_sessions()` sidebar `session_list` row heights by `+1 px` (`23 px` sessions, `24 px` projects, `21 px` empty placeholders, `22 px` section/archived headers).

---

# Fairybread — Beta v0.92c (Win_x64) Changelog
**Release Date:** 2026-11-22
**Version:** `v0.92c_beta_Win_x64`

## Summary of Changes in `v0.92c`
1. **🎙️ Deepgram Flux (`/v2/speak`) + All 89 English Voices in Contextual Dropdown (`voice_service.py`, `cost_service.py`, `palace_gui.py`):**
   - Added all **89** English Deepgram voices to `DEEPGRAM_TTS_VOICES`: **36 Flux** voices (defaulting to Sienna `flux-sienna-en`, plus Hannah, Kit, Alexis, Cliff, Cole, Colin, Gemma, Haley, Sharon [AU], etc.), **41 Aura-2** voices (including Hyperion [AU] & Theia [AU]), and **12 Aura-1** voices.
   - Upgraded `_stream_deepgram_pcm()` to route `flux-*` voices to `https://api.deepgram.com/v2/speak` with clamped `speed` (`0.5`–`1.5`) and `expressivity` (`-2` Calm to `+2` Animated), while keeping `aura-*` / `aura-2-*` on `/v1/speak`.
   - Made **Settings → Voice & Audio** contextually swap the **Voice Character** dropdown (`voice_name_combo`) per speaking engine, enabled **↻ Refresh Voices** (`fetch_remote_tts_voices`) live fetching from Deepgram `/v2/models` + `/v1/models`, added the contextual **Flux Expressivity** control (visible only for Deepgram, enabled for `flux-*`), and added `deepgram:flux` (`$0.030` / 1k chars) cost metering.
2. **🧠 Memory Retrieval & Personalisation Overhaul (`memory_service.py`, `bootstrap.py`, `palace_config.py`, `orchestrator.py`, `palace_gui.py`):**
   - Upgraded memory context injection to a two-stage `7500`-char budget (`Stage A` personalization + compact summary + top 4 durable facts `<= 3400` chars; `Stage B` up to 6 hybrid hits + 3 substantive recent exchanges), fixing the `4000`-char and standing-fact starvation that previously crowded out `memory.db` query results.
   - Added hybrid FTS5 + 128-d local vector cosine search, AU-English/casual synonym expansion, composite scoring (`relevance + recency + importance + project scope`), contradiction supersession (`active=0` + `superseded_by`), duplicate confirmation deduplication, canonical 4-section profile category normalization, trivial voice filler filtering, and computed Tone Vector + Speech Grammar prompt alignment (`flattery: 0.00`).
3. **💬 Chat Bubble & Sidebar Line Spacing Refinements (`palace_gui.py`):**
   - Removed mismatched `line-height:1.48` on user chat bubbles and `line-height:1.6` on the assistant wrapper so user input bubbles and AI replies render at identical natural Qt line spacing.
   - Tightened left sidebar topic row heights (`22px` sessions, `23px` projects, `20px` empty placeholders) with proportional `18×18` hover pin/menu hitboxes.

---

# Fairybread — Beta v0.92b (Win_x64) Changelog
**Release Date:** 2026-11-21
**Version:** `v0.92b_beta_Win_x64`

## Summary of Changes in `v0.92b`
1. **💬 Antigravity-Style Sidebar Discussion & Project Controls (`palace_gui.py`, `session_store.py`):**
   - Added hover **`⋮`** action menus and vector **`📌` Pin / `+` New Discussion** buttons directly inside the sidebar (`SidebarSessionList` + `SidebarItemDelegate`), plus full context-menu controls: **Rename**, **Pin / Unpin**, **Mark Read / Unread**, **Copy** (Title or Full Transcript), **Duplicate Discussion**, **Move to Project**, **Archive / Unarchive** (with collapsible `Archived (N)` drawer), and **Delete** (backed by disk-merge deletion guards in `SessionStore`).
   - Added the animated **2×2 4-dot active working spinner** on running discussions and the **blue unread indicator dot** (`#3b82f6`) for unread/completed background discussions (cleared automatically on selection).
2. **📬 Agent Mail `READ` / `UNREAD` Controls & Orchestrator Fixes (`idle_service.py`, `palace_gui.py`, `orchestrator.py`, `search_service.py`, `context_service.py`, `memory_proposal_service.py`):**
   - Added explicit `● [UNREAD]` / `✓ [READ]` row indicators, status pill badge, **`Mark Unread / Mark Read`** toggle (with auto-read suppression), and **`✓ Read All`** action bar in Agent Mail with zero UI clipping at `1024×700` and `1120×740`.
   - Fixed `detect_organic_turn_intents()` so read-only/advisory audits cannot hijack auto-patch mode, switched `orchestrator.py` & `palace_gui.py` dispatch compatibility to `inspect.signature` filtering instead of broad `except TypeError:`, added thread-safe locking in `ContextService`, safe `LOCALAPPDATA` fallbacks, and `PalaceRunResult.peer_rounds` contributor/answer fallback.
3. **⚡ Performance & Reliability Hardening (`dispatcher.py`, `memory_service.py`, `palace_theme.py`, `attachment_service.py`, `voice_service.py`, `backup_service.py`, `palace_ouroboros.py`, `palace_config.py`, `palace_watchdog.py`):**
   - Added `<= 0.15s` cancel-event response in `ProviderDispatcher`, batched SQLite `memories_blob` hydration (`_hydrate_rows_batch`) eliminating N+1 per-turn queries, thread-safe `QImage` SVG prewarming, mtime-validated Markdown/theme caches, and single-read attachment & snapshot hashing.
   - Enforced `max_retries=0` & explicit timeouts across Groq/Cerebras/OpenAI/Gemini/Cohere clients, ZipSlip symlink & path-traversal validation on backup restores, atomic locked handoff/crash writes, Cartesia/Groq Orpheus voice guards, and `Name LIKE 'python%'` + PID exclusions in watchdog termination.

---

# Fairybread — Beta v0.92a (Win_x64) Changelog
**Release Date:** 2026-11-20
**Version:** `v0.92a_beta_Win_x64`

## Summary of Changes in `v0.92a`
1. **⚖ Corrected `About Fairybread` License Text (`palace_gui.py`, `test_palace_gui.py`):**
   - Replaced the inaccurate `Open-Source / Source-Available Donationware` wording in **Help → About Fairybread** with the exact **Proprietary Source-Available Donationware (NOT Open Source)** copyright and licensing terms from `LICENSE.md`, guarded by regression assertions.
2. **🎨 Fixed Graphics Prompt-Optimization → Image Engine Handoff (`orchestrator.py`, `synthesizer.py`, `palace_config.py`, `palace_gui.py`, `test_pipeline_and_autopatch.py`):**
   - Expanded contextual visual follow-up detection so photographic/style/framing refinements (`"more photo realistic please"`, `"still hyper realistic"`, `"3:2"`, `"too cgi"`, etc.) stay inside the 2-AI **Prompt Duo** and emit 1 updated high-resolution `[GENERATE_IMAGE ... quality="high"]` master rather than dropping into generic multi-round text deliberation.
   - Clarified in prompt rules and `DEFAULT_PROVIDER_PROFILES` that active specialists act as **Prompt Optimizers** whose `[GENERATE_IMAGE prompt="..."]` tags are executed automatically by Fairybread's Python Image Engine (`gemini-3-pro-image` / `gemini-3.1-flash-image` / `gpt-image-2` / `FLUX-1-dev`) — preventing `[PASS]` handoffs to Gemini.
   - Fixed the broken `^\[PASS\]\b` regex bug in `is_pass_or_defer_text` / `PalaceSynthesizer` (`]` followed by space/dash never matched `\b`), required a populated `prompt="..."` attribute to treat a `[GENERATE_IMAGE]` mention as executable, skipped redundant primary retries on `429`/rate-limit/timeout errors, and passed an explicit active Prompt Optimizer failover directive to fallback specialists.
   - Widened the composer `/ Commands ▾` button (`88px` → `98px`) so its leading `/` never clips on Windows Segoe UI.

---

# Fairybread — Beta v0.92 (Win_x64) Changelog
**Release Date:** 2026-11-20
**Version:** `v0.92_beta_Win_x64`

## Summary of Changes in `v0.92`
1. **🛡 AI Access Permissions & Unlimited Write Exclusion List (`access_policy.py`, `workspace_tools.py`, `palace_gui.py`, `orchestrator.py`, `idle_service.py`):**
   - Added Antigravity-style execution modes (`Request Review`, `Default`, `Auto`, `Turbo`) in Settings and via the composer **`🛡 <Mode> ▾`** pill with an inline **Approve / Reject** banner above the composer.
   - Added an unlimited **Write Exclusion List** (empty by default, with a per-row **Include Subdirectories** checkbox) enforced deterministically on top of every mode — including `Turbo` and `[IDLE_PATCH]` self-modification — using `Path.resolve()` checks and Windows `GetLogicalDrives()` drive enumeration.
   - Consolidated workspace access controls under **AI Access Permissions**, removed developer-specific UI copy, and added `[FILE_LIST]`, `[FILE_READ]`, `[FILE_WRITE]`, `[FILE_PATCH]`, and `[RUN_CMD]` project workspace tools.
2. **🔗 External Agent Bridge (MCP) — Foreman Mode vs. Council Member Mode (`fairybread_mcp.py`, `local_cli_provider.py`, `provider_loader.py`, `palace_cli.py`, `palace_gui.py`):**
   - Redesigned **Settings → External Agent Bridge (MCP)** with 4 platform cards (**ChatGPT Desktop / Codex CLI**, **Google Antigravity**, **Grok (xAI Build CLI / Grok Bot)**, **Claude Desktop / Claude Code CLI**), built-in mode guide, and mutually interlocked **Foreman Mode** vs. **Council Member** switches to prevent feedback loops (`FAIRYBREAD_MCP_DEPTH` guard + `stdout` isolation + `pythonw.exe` → `python.exe` resolution + live **`🧪 Test MCP Bridge`** check).
   - Added atomic `.fairybread.bak` + `tomllib`-validated TOML and JSON config merge/unlink writers and local CLI Council Member wrapping (`LocalCLIProvider`).
3. **🔄 Live Model/Pricing Catalog Auto-Sync & Update Notification Pill (`catalog_sync.py`, `palace_gui.py`):**
   - Added zero-telemetry startup sync against `https://fairybread.me/feed/catalog.json` (`ETag` + 6h cache, offline fallback) refreshing token/voice/image rate tables and suggested model lists without touching user picks.
   - Added Antigravity-style top-bar **`⬆ v... — Update`** pill, **`Help → Check for Updates & Refresh Model Rates…`**, and SHA-256-verified installer downloads.
4. **↺ Fail-Safe Restore Default Settings & VLC-Style Pre-Upgrade Backup Installer (`palace_config.py`, `install_fairybread_beta.py`):**
   - Added **`↺ Restore Default Settings…`** in both the **Settings** menu and **Backup & Restore**, automatically saving a timestamped pre-reset JSON snapshot while protecting Memory Palaces, chats, DPAPI API keys, and (by default) Write Exclusions and MCP links.
   - Upgraded the Windows installer with automatic pre-upgrade ZIP backups (`pre_upgrade_backups/`), safe upgrades on existing Fairybread folders, and VLC-style defaults preserving settings, API keys, and Memory Palaces (even for custom non-`Program Files` installs).

---

# Fairybread — Beta v0.9.1g (Win_x64) Changelog
**Release Date:** 2026-11-19
**Version:** `v0.9.1g_beta_Win_x64` (Minor Letter Iteration `g` of `v0.9.1`)

## Summary of Changes in `v0.9.1g`
1. **🎙️ Talk Mode Only & Persistent Voice History (`voice_companion.py`, `context_service.py`, `palace_gui.py`):**
   - Added **Talk Mode Only (Fast Voice Chat · No Council)** to the top of the Mode / Choose AIs menu (compact pill badge `🎙️ Talk Only  ▾` so zero controls clip).
   - Routes both spoken and typed messages strictly to 1 low-latency non-reasoning AI (`groq` -> `deepseek-chat` forcing off `deepseek-reasoner` -> `gemini-4-hydrogen`/`2.5-flash` -> `openai` -> `cerebras`) without JSON router wrappers, council deliberation, tools, or accidental background delegation.
   - Persists Voice Companion & Talk Mode turns into `SessionStore` (`speaker_id="voice_companion"`, `phase="voice_chat"`) so switching modes or adding agents mid-conversation carries over full spoken context seamlessly.
   - Escaped Qt mnemonic `&` characters (`&&`) across the Choose AIs / Squads menu so `&` renders properly on every entry.
2. **Graphics Draft-Selection, 1-Retry-Before-Downgrade & Verbose `[PASS]` Failover (`palace_theme.py`, `orchestrator.py`):**
   - Recognized bare and natural draft picks (`1`, `2`, `3`, `#1`, `go with 2`, `first one`, `mix 1 and 3`) as `direct_draw` visual turns when prior drafts exist in session history, instructing graphic specialists to emit the full-resolution master immediately.
   - Added a **1-retry-before-downgrade policy scoped strictly to graphics** on both the primary image engine (`generate_ai_image_to_png`) and the primary graphic prompt specialist (`orchestrator`), retrying transient misses once before dropping to lower-priority/fallback engines while skipping retry immediately on permanent auth/quota/safety errors.
   - Updated `_is_silent_pass_or_defer()` to catch verbose `[PASS] — ...` messages, filtered `[PASS]` replies out of synthesis, enabled failover when peers only `[PASS]` or fail, and added a deterministic Draft #N master upgrade backstop if all specialists fail or `[PASS]`.

---

# Fairybread — Beta v0.9.1f (Win_x64) Changelog
**Release Date:** 2026-11-19
**Version:** `v0.9.1f_beta_Win_x64` (Minor Letter Iteration `f` of `v0.9.1`)

## Summary of Changes in `v0.9.1f`
1. **Live Multi-Modal Conversation Cost Meter (`cost_service.py`, `providers.py`, `orchestrator.py`, `palace_gui.py`):**
   - Added real API token extraction (`input_tokens`, `output_tokens` from `usage` / `usage_metadata`) across OpenAI, Gemini, DeepSeek, Groq, Qwen, Mistral, Cerebras, Cohere, and Voice Companion turns via `extract_sdk_usage_tokens()`.
   - Metered all four cost buckets incrementally in real time as calls finish: (1) Chat / Council / Synthesizer / Voice Companion LLMs using per-model pricing, (2) Neural TTS duration from actual spoken PCM bytes, (3) Speech-to-Text WAV duration (`whisper-large-v3-turbo`, `whisper-1`, Gemini), and (4) Network image renders (`gemini-3-pro-image`, `gemini-3.1-flash-image`, `gpt-image-2`, `flux-1-dev`).
   - Wired live updates into the bottom status bar (`Tokens: ... · Conv: ~$...`) with a detailed hover tooltip breakdown (Chat LLMs, Voice TTS + Mic, Images, Last Step, By Provider) and per-session persistence in `SessionStore` (`session_store.py`).

---

# Fairybread — Beta v0.9.1e (Win_x64) Changelog
**Release Date:** 2026-11-19
**Version:** `v0.9.1e_beta_Win_x64` (Minor Letter Iteration `e` of `v0.9.1`)

## Summary of Changes in `v0.9.1e`
1. **Streaming Human Neural Voice & Always-On Voice Companion (`voice_service.py`, `voice_companion.py`, `palace_gui.py`):**
   - Replaced legacy SAPI-5-only PowerShell TTS with direct 24 kHz 16-bit mono PCM streaming (`_WaveOutStream` via `winmm`) defaulting to **Warm American** (`tts_engine="auto"`, primary `coral`, fallback Gemini `Kore`, `voice_style="warm_american"`, `1.0x` speed).
   - Automatic fallback chain across OpenAI `gpt-4o-mini-tts` (streaming PCM + accent/tone instructions) -> Gemini Neural TTS (`gemini-3.8-flash-lite-tts` / `gemini-3.8-flash-tts` / `gemini-2.5-flash-preview-tts`) -> Windows System SAPI 5.
   - Added independent **Conversational Voice Companion** (`VoiceCompanionWorker`, `VoiceSummaryWorker`) so Live Voice Mode keeps talking naturally (~1–2s response) while delegating complex image/code/research tasks to the AI crew in the background, supporting spoken mid-run live steering (`steer`) and concise spoken completion summaries, with anti-echo microphone gating.
   - Upgraded **Settings → Voice & Audio** with Voice Engine selector, dynamic Primary Voice & Fallback Gemini Voice dropdowns, Accent & Style presets, Custom Tone Note, Speaking Speed slider, Speaker Volume, Test/Stop controls, and Companion toggles.
2. **Agent Defaults Control Panel & Organic Intent (`palace_config.py`, `search_service.py`, `orchestrator.py`, `palace_gui.py`):**
   - Added `Settings → Agent Defaults` (`approval_policy` with `auto_deploy`, `sandbox_mode`, `web_search_default`, `output_detail`, `reasoning_summary`, `synthesizer_mode`, `smart_routing`, `provider_timeout_sec`, `straggler_grace_sec`).
   - Added `detect_organic_turn_intents()` so natural phrasing (e.g. *"no need to ask for approval"*, *"keep it short"*) and scoped self-modification work without `/` switches.
3. **Gemini 4 Neon, Multimodal Vision, 2-Provider Graphics Duo & Speed/Scale Optimizations:**
   - Default Gemini model updated to `gemini-4-neon`; real multimodal PNG byte dispatch added across `dispatcher.py`, `gemini_provider.py`, and native `openai_provider.py`.
   - Default 2-provider Graphic Prompt Duo (`gemini` + `openai`) with parallel 3-draft rendering (`prewarm_generated_images()`), primary + fallback image engines (`gemini-3-pro-image` / `gemini-3.1-flash-image` / `gpt-image-2` / `flux-1-dev`), and Windows attachment archival fix (`attachment_service.py`).
   - Dedicated fast synthesizer (`auto_fast`), smart intent routing, `45s` per-provider timeouts + straggler quorum cutoff, bounded markdown/message LRU caches, and chunked tail-seek session loading (`context_service.py`).

---

# Fairybread — Beta v0.9.1d (Win_x64) Changelog
**Release Date:** 2026-11-19
**Version:** `v0.9.1d_beta_Win_x64` (Minor Letter Iteration `d` of `v0.9.1`)

## Summary of Changes in `v0.9.1d`
1. **Hardwired Edition Gate (`FAIRYBREAD_EDITION = "public"` vs `"developer"`):**
   - **Public (non-Dev) Edition** still includes Experimental Mode (Free Talk lounge, Shared Experimental Memory, Agent Mail), but **live code self-modification (`/autopatch`, `[IDLE_PATCH]`, `⚡ Live Patch`, and source-mirror writing) is hardwired OFF** in code (`palace_config.py`, `idle_service.py`, `orchestrator.py`, `palace_gui.py`).
   - Public installers physically omit `palace_ouroboros.py`, `palace_watchdog.py`, `palace_promote.py`, and `test_*.py` so public installs cannot fork themselves or bypass restrictions.
   - Public users see clear notices in Settings, About, README, User Guide, and `fairybread.me` explaining why self-patching is disabled in non-Dev builds and inviting them to post proposed patches to **https://fairybread.me/forum.html** or email **bm069au@gmail.com**.
2. **Installer `payload/` Packaging Bug Fixed:**
   - Cleaned stray duplicate files out of `dist/Fairybread_Beta_v0.9.1_Installer/` root and updated `payload/` directly so both Public and Developer `Win_x64` zips are clean (~370 KB) and ship the exact `v0.9.1d` code.
