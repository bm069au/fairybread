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
