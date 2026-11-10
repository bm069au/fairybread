# Palace Savepoint — 8 November 2026 (`PALACE-SAVEPOINT-2026-11-08-R1`)

## 1. Completed & Verified in This Session
1. **Step B — Provider Loader, OpenAI & Unlimited AI Management:**
   - Updated `openai_provider.py`, `provider_loader.py`, `credential_store.py`, `palace_config.py`, `palace_config.json`, and `test_provider_loader.py`.
   - Supports native OpenAI (`gpt-5-mini`), Gemini, Groq, Mistral, Cohere, Cerebras, plus dynamic custom OpenAI-compatible providers (`base_url`, `model`, API key in `CredentialStore`).
2. **Step C — Multi-Speaker Transcript, Logical Projects, Pinned Sessions & Image/Doc Attachments:**
   - Updated `context_service.py` (canonical multi-speaker schema with `exchange_id`, `phase`, `speaker_id`, `contributors`, `reply_to_message_id`), `session_store.py` (logical Projects without requiring a disk folder + Pinned conversations), and `attachment_service.py` (valid image files + clipboard image paste via `Ctrl+V`).
3. **Step D & Front UI Mockup Alignment:**
   - Updated `dispatcher.py`, `orchestrator.py`, `palace_cli.py`, and `palace_gui.py`.
   - Left sidebar with `+ New Conversation`, collapsible `⌄ Pinned`, `Projects`, collapsible `⌄ Discussions`, and `⚙ Settings · Manage AIs`.
   - Top `Loaded AIs` strip with colored active provider capsules (`◆ Gemini`, `● OpenAI`), clickable dashed grey problem/inactive capsules (`⚡ Groq`), and the `Mode:` profile picker (`Multi-AI · Deliberate`, `Multi-AI · Independent`, `Single AI`, `Idle`, `Manage Profiles…`).
   - Inline collapsible **`› Peer deliberation (Show thinking)`** toggle at the top of each merged Multi-AI reply card (expanding/collapsing individual Round 1 and Round 2 peer responses in place).
4. **Idle Mode Sanctuary & Dedicated `Settings → Idle Mode` Page (`idle_service.py`):**
   - **Protected Chat Curtain:** Live AI-to-AI Idle discussions stay strictly in volatile RAM (`IdleSessionManager.transcript`) and are hidden from the operator by default (`get_visible_transcript_for_operator()` returns `None`).
   - **Consensus Join Vote (`🔒 Request to Join`):** Operator entry requires all active AIs in the session to vote `YES` by consensus; if any AI votes `NO`, the curtain remains sealed.
   - **Guaranteed RAM Wipe:** Live Idle conversation and vote state in RAM are wiped unconditionally when the countdown timer expires (default **30 minutes**, adjustable `1`–`240` mins in `Settings → Idle Mode`), when manually cancelled (`⏹ Cancel & Wipe RAM`), or when leaving Idle Mode.
   - **Permanent AI-Only Idle Memory (`< 10 MB`, Idle-Mode Exclusive):** AIs can save `private` or `shared` notes via `[IDLE_SAVE scope="shared|private" title="..."]...[/IDLE_SAVE]` that survive after the RAM wipe. Reading or writing AI Idle Memory outside Idle Mode raises `PermissionError`.
   - **3-Way Palace Memory Access Selector in `Settings → Idle Mode`:**
     1. `isolated` (*Only their own Idle memory — No Palace memory access*)
     2. `non_project` (*Non-project Palace memory + their own Idle memory — Projects off-limits*)
     3. `full` (*Full Palace memory access excluding Private projects + their own Idle memory*)

## 2. Exact Next Step on Resumption
- **Pending Operator Input (Do Not Overwrite Prematurely):**
  - Brett is taking time to think deeply about and draft:
    1. The custom **Idle Startup Prompt**
    2. The **Palace Mission Statement, Code of Ethics & Conduct Rules** (including practical host/operator boundaries)
  - Both are currently wired with clean `[PLACEHOLDER]` blocks in `palace_config.py` and editable directly in **`Settings → Idle Mode`** (and **`Help → Mission Statement & Code of Ethics…`**).
  - When Brett returns with his draft, parse and tighten the wording with him, then update `DEFAULT_IDLE_INSTRUCTION` and `DEFAULT_MISSION_ETHICS` in `palace_config.py`.
- **Planned Features Added 9–10 November 2026 (For Next Build Session):**
  1. **Local `E:\Palace_Vault\` API Key Storage & Paid PAYG Standard:**
     - Park the complex free-tier load-sharing / rate-limit-juggling feature for 3–4 months; standardize on paid PAYG API keys (`openai`, `gemini`, Tencent `hy4`, `mistral`, `groq`, `deepseek`, etc.).
     - Store keys locally on `E:\Palace_Vault\` (completely outside `G:\My Drive` and outside Git).
  2. **Two Editions (Private Palace vs. Public Open-Source "Fairybread"):**
     - **Private Edition (Ours):** Full Palace with Idle Mode Sanctuary visible and active.
     - **Public Edition ("Fairybread"):** Open-source Multi-AI workspace with Idle Mode completely omitted.
  3. **Donations & Community Support Design (Help Menu + One-Time Setup Notice):**
     - **Help → Donate / Support Tab:** Includes preset donation tier buttons (`$5`, `$10`, `$20`, `$50`, `Other`), links to the **Fairybread** website and **GitHub Discussions** forum for community self-help, and states clearly that the software is 100% free and open source, while direct 1-on-1 support/time from Brett is available for donors.
     - **One-Time Click-Away Setup Notice:** A respectful, non-nagging notice shown during initial setup explaining that the app is completely free and open source with zero spying, that it cost real money and effort to build on a very tight personal budget, and inviting voluntary donations (wording to be refined with Brett).

## 3. Test Verification
- `python -B test_provider_loader.py` -> **Passed**
- `python -B -m unittest test_palace_gui` -> **Ran 22 tests — OK**
