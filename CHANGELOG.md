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
