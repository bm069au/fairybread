# Fairybread (Beta) — Democratic Multi-AI Council & Shared Memory Workspace

**Created by Brett Martin Moore (`bm069au@gmail.com`)**

Fairybread is a native Windows desktop workspace where multiple AI models (**Gemini**, **OpenAI**, **DeepSeek**, **Qwen**, **Cohere**, **Mistral/Codestral**, **Anthropic**, **xAI**, **Groq**, **OpenRouter**, **DeepInfra**, **Cerebras**, and local **Ollama**) collaborate democratically, cross-examine ideas, share a persistent Memory Palace, and render high-resolution photography, social media banners, and 300-DPI print graphics.

👉 **Full Operating & Drawing Instructions:** See [USER_GUIDE.md](USER_GUIDE.md) (or press **`F1`** / **`Help → 📖 User Guide & Drawing Instructions…`** inside the Fairybread desktop app).

---

## ❤️ Support Fairybread (USD Donations) & Licensing

Fairybread is **Source-Available Donationware** under the [Fairybread Dual License](LICENSE.md):

- **Personal, Non-Profit & Small Teams (Up to 2 Seats):** Free to install and use on up to **two (2) seats/workstations**. If Fairybread saves you time or enhances your workflow, please consider supporting independent development with a one-time **USD donation** via GitHub Sponsors (0% platform fee):
  - [**💵 Donate \$5 USD**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=5)
  - [**💵 Donate \$10 USD**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=10)
  - [**💵 Donate \$20 USD**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=20)
  - [**💵 Donate \$50 USD**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=50)
  - [**💝 Custom USD Amount**](https://github.com/sponsors/bm069au?frequency=one-time)
- **Commercial / Corporate License (More Than 2 Seats):** Businesses and commercial organizations deploying Fairybread across **more than two (2) seats/users** require a commercial license (negotiable pricing based on seat count).
  - 📧 Contact **Brett Martin Moore** at [`bm069au@gmail.com`](mailto:bm069au@gmail.com?subject=Fairybread%20Corporate%20License%20Inquiry%20%28%3E2%20Seats%29) to arrange a Corporate Seat License.

---

## Key Highlights

- **Two-Stage High-Resolution Image Pipeline (`Prompt Architect → Single High-Res Image Renderer`):**
  - **Default 1-Pass Drawing Mode:** Ask *"Draw me a brown dog on a black carpet in front of a fireplace"* and a single top Prompt Architect (`DeepSeek` / `OpenAI` / `Gemini`) expands your description into a rich photographic specification and sends it to the high-resolution image engine (**`gemini-3-pro-image`** *Nano Banana Pro* → **`gemini-3.1-flash-image`** *Nano Banana 2* → **`gpt-image-2`**) in one fast pass.
  - **Council-Assisted Prompt Brainstorming Mode:** Ask *"All agents work on the prompt and then only one of you execute the drawing: ..."* to have the entire council collaborate on lighting, anatomy, and composition before the Synthesizer renders **one** final consolidated image.
- **Smart Default Size (`1024×1024`) + Social, Wallpaper & 300-DPI Print Presets:**
  - Automatically understands plain-English requests for **YouTube banners** (`2560×1440`), **YouTube thumbnails** (`1280×720`), **Facebook page covers** (`1920×1080`), **Facebook PC banners** (`820×312`), **Facebook group covers** (`1640×856`), **desktop/4K/phone wallpapers**, and **300-DPI print sizes** (`8×10 in`, `A4`, or any `"WxHin"` / `"WxH"` dimensions).
- **16-Worker Parallel Council Deliberation & Live Per-Agent Progress Ticks:**
  - Dispatches all active council AIs in one simultaneous wave per round, streams live per-agent completion ticks on the bottom status chips (`Responded` / `Working`), preserves both Round 1 proposals and Round 2 peer reviews for the synthesizer, and automatically fails over if any single provider is rate-limited.
- **Live Turn Control (`■ Stop`, `🧭 Steer`, `⏳ Queue`) & 3-Tier Search Depth (`🔍 Fast / Deep / Research`):**
  - Interrupt any active turn cleanly, inject a live mid-turn steering note before the next phase/synthesis, or queue follow-up prompts to execute automatically.
- **Universal External Agent Bridge (MCP Server + Skill Installer):**
  - One-click registration in **`Settings → 🔗 External Agent Bridge (MCP)`** exposes Fairybread's Council and SQLite FTS5 Memory Palace to **Antigravity**, **Claude Desktop / Claude Code**, and **ChatGPT Desktop**.
- **Exhaustive Multi-Folder Email Connector & Completion Notifications:**
  - Read-only IMAP scanning across all mailbox folders (`INBOX`, `Archive`, `Sent`, custom labels) with automatic pagination, plus optional completion notification emails (`[NOTIFY_EMAIL]`).
- **Durable SQLite FTS5 Memory Palace & Full Atomic ZIP Backup/Restore:**
  - Full-text BM25 search over shared notes and sessions, plus one-click full ZIP backup and atomic restore under **`File → Backup / Restore All Data…`**.
