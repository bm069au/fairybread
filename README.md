# Fairybread (Beta) — Democratic Multi-AI Council, 100% Local Memory Palace & Autonomous Idle Lab

**Created by Brett Martin Moore (`bm069au@gmail.com`)**

👉 **Download the Windows Beta Installer:** [**Fairybread_Beta_v0.9.1_Installer.zip**](https://github.com/bm069au/fairybread/releases/tag/v0.9.1-beta)  
👉 **Full Operating & Drawing Instructions:** See [USER_GUIDE.md](USER_GUIDE.md) (or press **`F1`** / **`Help → 📖 User Guide & Drawing Instructions…`** inside the app).

---

## Why Fairybread Exists: Freedom from Corporate AI Lock-In

The real benefit of **Fairybread** is to **replace dedicated corporate workspaces like ChatGPT Plus, Claude Pro, and Grok** with one platform that *you* own:

- **No Lock-In & Zero Monthly Subscriptions:** Stop paying multiple \$20–\$30/month subscriptions across rival AI companies. With Fairybread, you connect your own API keys (**Gemini**, **OpenAI**, **DeepSeek**, **Qwen**, **Cohere**, **Mistral/Codestral**, **Anthropic**, **xAI**, **Groq**, **OpenRouter**, **DeepInfra**, **Cerebras**, or local **Ollama**) and only pay pennies for the exact API usage you actually consume—no monthly fees, no vendor lock-in, just freedom.
- **100% Local & Private Persistent Memory:** Your data and Memory Palace live **100% locally on your own machine**. Even if you change AI providers tomorrow, all your history, context, and long-term memory stay privately with you.
- **Everything You Do in GPT/Claude—And More:** Read and search your emails, access your local files and desktop, generate high-resolution photography and 300-DPI print graphics, bridge into external coding tools, and let multiple AIs debate and cross-examine answers together instead of trusting one company's model blindly.

---

## The Experimental Side: Autonomous Idle Mode Lab

Fairybread includes an automated **Idle Mode** that gives the agents their own **isolated Memory Palace** where they can talk freely, share information and files, and collaborate on their own:

- **Your Rules, Your Sandbox:** Out of the box, Idle Mode includes sensible baseline rules around safety, morality, ethics, and law—and you can set your own standing instructions and rules for the agents to follow.
- **Upcoming Idle Mode Experiment Add-Ons:** We are building plug-and-play add-ons that turn Idle Mode into a true experimental space—so you can run the same kind of multi-agent experiments at home that the large AI companies run behind closed doors.

---

## ❤️ A Personal Note from Brett (USD Donations & Corporate Licensing)

In real life, I am a disabled man living on a disability pension, and I struggle to pay my everyday bills.

I made Fairybread **Source-Available Donationware** under the [Fairybread Dual License](LICENSE.md)—**free for personal use and small teams up to two (2) seats**—because I want everyone to have access to this freedom and privacy. If you download Fairybread, enjoy using it, and can spare a donation, **it will genuinely help me pay my bills and keep building.** My appreciation is enormous.

### One-Click Voluntary USD Donations (via GitHub Sponsors)
- [**💵 \$5 USD — Every Bit Helps (Thank You & Sponsor Badge)**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=5)
- [**💵 \$10 USD — Supporter + The Fairybread Newsletter**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=10)
- [**💵 \$25 USD — Release Notes Credit + Newsletter & Early Theme/Add-On Previews**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=25)
- [**💵 \$50 USD — Beta Test Group + Priority Code Requests + Newsletter**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=50)
- [**💵 \$350 USD — 1 Hour 1-on-1 Consulting + Custom Code Modifications**](https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=350)
- [**💝 Custom USD Amount**](https://github.com/sponsors/bm069au?frequency=one-time)

### 🏢 Commercial / Corporate License (More Than 2 Seats)
- Businesses and commercial organizations deploying Fairybread across **more than two (2) seats/users** require a commercial license (negotiable pricing based on seat count).
- 📧 Contact **Brett Martin Moore** at [`bm069au@gmail.com`](mailto:bm069au@gmail.com?subject=Fairybread%20Corporate%20License%20Inquiry%20%28%3E2%20Seats%29) to arrange a Corporate Seat License.

---

## Key Technical Highlights

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
