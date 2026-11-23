# Fairybread (Beta) — User Guide & Operating Instructions

**Created by Brett Martin Moore (`bm069au@gmail.com`)**

Fairybread is a democratic multi-AI council desktop workspace where multiple frontier AI models collaborate, cross-examine ideas, share a persistent Shared Memory, and generate high-resolution photography, graphics, social media banners, and 300-DPI print artwork.

---

## 1. High-Resolution Image & Graphic Generation

Fairybread pairs a smart **"Visual Optimizer / Direct Pipeline"** with configurable high-resolution image renderers and automatic pixel-anchored editing. Configure your preferred engines anytime under **`Settings → ⚡ Agent Defaults → Graphics & Image Engine`**.

### Configurable Image Engines & Pipeline Modes

- **Default Flagship Primary Engine:** OpenAI **`gpt-image-2.6-sunburst`** (also selectable: **`chatgpt-image-latest`**, Google **`gemini-3-pro-image`**, legacy **`gpt-image-2`**, or **`openrouter:openai/gpt-5.4-image-2`**).
- **Default Fast Draft Engine:** OpenAI **`gpt-image-2.6-flare`** (also selectable: Google **`gemini-3.1-flash-image`** or **`flux-1-schnell`**), with automatic cross-provider fallbacks and detailed diagnostic logging (`image_diagnostics.log`).

#### The Three Pipeline Modes (`Settings → ⚡ Agent Defaults`)
1. **Single Vision Optimizer (Recommended Default):** One vision-capable AI expands or refines your visual request cleanly (no multi-AI council bloat) and dispatches the `[GENERATE_IMAGE ...]` render directly—emitting a single high-resolution master for explicit edits/refinements or 3 smaller draft concepts when you ask to explore variations.
2. **Direct to Image Engine:** Sends your prompt and any attached reference photos straight to the image model without an intermediate text-LLM round.
3. **2-AI Prompt Duo / Council Brainstorming Mode:** Two visual specialists (or the full council when you ask *"All agents work on the prompt..."* or switch to the Graphics duo) collaborate before rendering.

#### Pixel-Anchored Editing & Reference Photos
- Ask to adjust an image you just generated (*"Keep the dog the same, just change the carpet to dark blue"*) and Fairybread automatically threads the **prior rendered PNG** plus any attached/profile subject reference photo directly into the image edit endpoint (`image[]` multi-ref for OpenAI / `inlineData` for Gemini / multimodal for OpenRouter) so the scene stays visually anchored instead of starting from scratch.

---

## 2. Image Sizes, Social Media Presets & 300-DPI Print Sizes

### Default Size & Quality
- **Default Quality:** Always set to the **highest possible fidelity (`quality="high"`)**.
  - To request a faster draft render (via your configured **Draft Engine**, e.g. `gpt-image-2.6-flare` or `gemini-3.1-flash-image`), simply mention `"fast"`, `"draft"`, or `"low quality"` in your prompt.
- **Default Size:** **`1024×1024` Square HD** unless you ask for a specific shape, platform banner, wallpaper, or print size.

### Plain-English Platform, Wallpaper & Print Sizes
You can ask in plain English for any of the following, and Fairybread will automatically render in the matching native aspect ratio, perform an aspect-preserving center crop + smooth scaling to the exact pixel dimensions, and stamp **300 DPI (`11811` dots/meter)** metadata into the PNG file:

| What You Ask For in Plain English | Preset Name | Exact Output Pixels | Physical / Platform Target |
| :--- | :--- | :--- | :--- |
| **"YouTube banner"** / **"YouTube channel header"** | `youtube_banner` | `2560 × 1440 px` | YouTube Channel Art (`16:9`) |
| **"YouTube thumbnail"** | `youtube_thumbnail` | `1280 × 720 px` | YouTube Video Thumbnail (`16:9`) |
| **"Facebook page background"** / **"Facebook cover"** | `facebook_cover` | `1920 × 1080 px` | High-Res Facebook Page Cover |
| **"Facebook PC banner"** | `facebook_pc_banner` | `820 × 312 px` | Exact Facebook Desktop Cover |
| **"Facebook group background"** / **"Facebook group cover"** | `facebook_group` | `1640 × 856 px` | Exact Facebook Group Banner |
| **"Desktop wallpaper"** / **"PC background"** | `desktop_wallpaper` | `1920 × 1080 px` | Full HD 1080p Monitor Wallpaper |
| **"1440p wallpaper"** / **"QHD wallpaper"** | `wallpaper_1440p` | `2560 × 1440 px` | QHD 1440p Monitor Wallpaper |
| **"4K wallpaper"** | `wallpaper_4k` | `3840 × 2160 px` | 4K UHD Monitor Wallpaper |
| **"Phone wallpaper"** / **"Instagram story"** / **"Reel"** | `phone_wallpaper` | `1080 × 1920 px` | Vertical Mobile / Story (`9:16`) |
| **"Instagram square"** | `instagram_post` | `1080 × 1080 px` | Square Social Post (`1:1`) |
| **"Print 8x10"** / **"8 x 10 inch print"** | `print_8x10` | `2400 × 3000 px` | `8 × 10 in` @ **300 DPI** |
| **"A4 print"** / **"A4 landscape print"** | `print_a4` | `2480 × 3508 px` | `A4` (`210 × 297 mm`) @ **300 DPI** |
| **Any Custom Pixel Size** (e.g. `"1600x900"`) | `"WxH"` | Exact `W × H px` | Custom Pixel Dimensions (`128..4096`) |
| **Any Custom Print Size** (e.g. `"5x7in"`) | `"WxHin"` | `W*300 × H*300 px` | Custom Inches @ **300 DPI** |

### Graphic & Photographic Terms Supported
The Prompt Architect and image engines natively understand photographic and artistic terminology, including:
- **Realism & Camera Cues:** `photorealistic`, `hyperrealistic`, `85mm f/1.8 lens`, `shallow depth of field`, `creamy bokeh`, `subsurface scattering`, `rim lighting`, `golden hour`, `cinematic color grading`, `macro photography`.
- **Artistic Styles:** `oil painting`, `watercolor`, `concept art`, `isometric 3D`, `minimalist flat vector`, `cyberpunk`, `studio product shot`.
- **Technical Diagrams (`SVG`):** For system architecture diagrams, flowcharts, and crisp vector icons, Fairybread automatically uses inline `SVG` vector rendering instead of raster diffusion.

### Viewing, Downloading, Copying & Deleting Full-Resolution Images
- Every generated image in chat includes a clickable action bar (plus a right-click context menu):
  - **`🔍 View Full Size`** — Opens the **Full-Resolution Image Viewer** (`💾 Save Image As…` and `📋 Copy Image` to clipboard).
  - **`💾 Download / Save As…`** — Opens a Save dialog defaulted to your `Downloads` folder.
  - **`📂 Show in Folder`** — Opens Windows Explorer with the PNG file highlighted.
  - **`🗑 Delete`** — Deletes the stored PNG file to free up drive space.
- **Multi-Image Comparison Requests:** You can ask for multiple options in a single turn (e.g., *"Make 3 different banners and let me choose"*) and Fairybread will render all 3 high-resolution images side-by-side immediately.

---

## 3. Composer Toolbar, Council Modes & Mouseover Hints

Hover your mouse over **any button, icon, or chip** in Fairybread to see a plain-English tooltip explaining what it does:
- **`Choose AIs (N)`:** Pick which AI providers are active, or choose a quick preset profile (**Code AIs**, **Light Chat (Free / Fast)**, **Deeper Chat (Paid — Reasoning & Long)**, **Generalist**, **Graphics & Vision**, **Work Mode**). Each profile supports custom `context_depth` (`12K` / `36K` / `64K`) and per-provider model overrides under **`Settings → 🎛 Profiles & AI Squads`**.
- **`Council` Toggle (Purple when ON):**
  - **ON (2-Round Peer Deliberation):** Agents answer in Round 1, inspect and critique each other's responses in Round 2 (replying `[PASS]` if a peer already nailed it), and the Synthesizer combines the best insights into one final answer.
  - **OFF (1-Round Fast Synthesis):** Agents answer in one parallel wave and synthesize immediately.
- **`Tangent` Toggle:** Ask a side question without including prior conversation history in the prompt, while still saving the exchange to your current chat.
- **`{} Code` Toggle:** Grants the council read-only visibility into Fairybread's own source code so the agents can diagnose or design upgrades for their own app.
- **`🎤` Dictate Button:** Click once and speak (`🎙 ▂▅▇█▄▂` shows your live mic level); click again to transcribe your voice directly into the prompt box for all Council AIs.
- **`|||✨` Live Voice Mode Button (Circular Soundwave + Sparkle):** Hands-free live voice conversation with the Council. Automatically detects when you pause speaking (`~1.5s`), sends your spoken prompt to the Council, and reads the synthesized reply back to you aloud.
- **`No-History` (Top Bar):** Ephemeral privacy mode—neither reads nor saves session history.
- **`Experimental: OFF / ON` (Top Bar):** Switches to autonomous **Experimental Mode**, where agents converse freely, share notes in **Shared Experimental Memory**, optionally inspect Fairybread's source code (`{} Code`), and send you improvement proposals via **Agent Mail**.

---

## 4. Bottom Status Bar (Responsive Layout)

- **Left Side (`Agents:`):** Shows live colored status chips for every active AI (`Ready`, `Working`, `Responded`, `Limited`, `Failed`). Click any chip to toggle that AI active/inactive on the fly.
- **Right Side:** Displays save/contributor status alongside the live **`Tokens · Spend ($)`** meter.
- **Responsive Window Sizing:** Automatically adapts between a single-row layout on wide windows, a compact single-row layout on medium windows, and a clean 2-row stacked layout on narrow windows.

---

## 5. Exhaustive Email Search & Completion Notifications (`Settings → 📧 Email & Notifications`)

Unlike standard AI email tools that silently cap searches at the first 10–20 messages, Fairybread includes an **EvidenceBench-grade Exhaustive Email Search Engine** that enumerates **100% of matching emails** across your entire mailbox (`[Gmail]/All Mail`, `INBOX`, `Sent`, `Archive`).

### Setting Up Your Email (Day 1 or Anytime Later)
1. Open **`Settings → 📧 Email & Notifications…`**.
2. Choose your provider from the **Email Provider** dropdown:
   - **Gmail (`@gmail.com`):** Click **`🔑 Open Provider Password Page ↗`** (`myaccount.google.com/apppasswords`), create an App Password named `Fairybread`, and paste the 16-character key into **App Password / Token**. (Encrypted on your PC via Windows DPAPI).
   - **Microsoft Mail (`@outlook.com`, `@hotmail.com`, `Office 365`):** Paste a Microsoft Graph OAuth token (`oauth:<token>`) or Exchange/365 App Password.
   - **Apple iCloud, Yahoo, Fastmail, or Custom IMAP/SMTP:** Pre-fills the server host and port automatically; click the portal button to generate an App Password.
3. Choose your **AI Access Level**:
   - **`📝 Read & Drafts Only (Recommended Default)`:** Allows full exhaustive search across your mailbox and saving drafts, while preventing any external email from being sent without your approval.
   - **`🔔 Self-Notifications Only`:** Outbound completion alerts to your own address only (never reads your inbox).
   - **`⚡ Full Email Assistant`:** Full search, read, draft, and send.
4. Click **`🧪 Save & Send Test Notification (Desktop + Email)`** to verify both your Windows desktop toast and your email delivery immediately.

### How to Search Your Email in Chat
Once configured, simply ask in plain English (or use Gmail search operators):
- `"Search my email for all messages from amazon"`
- `"Check my unread emails and summarize anything urgent"`
- `"Search my Gmail for from:boss@company.com after:2025/01/01"`
- Fairybread will report the **exact match count** (e.g., `Total Matching Emails in Mailbox: 74 (Analyzed: 74 / 74 — Zero Silent Truncation)`) and pass the sanitized messages to the council.

### Desktop & Email Completion Notifications
- **Desktop Toast Notifications:** Pops a Windows 11 system tray notification when Fairybread finishes a turn while unfocused or when a job takes longer than 12 seconds (with an optional completion chime).
- **Email Completion Alerts:** Automatically emails your own address with the full synthesized answer (and attaches any generated high-res PNGs!) when a large job (`> 30s`) or Autonomous Experimental Mode session completes.

---

## 6. External Agent Bridge — Connecting Antigravity, Claude, ChatGPT or Grok (`Settings → 🔗 External Agent Bridge (MCP)`)

Each external platform supports two mutually interlocked modes inside **`Settings → 🔗 External Agent Bridge (MCP)`**:
- **Foreman Mode (Drives Fairybread via MCP):** Flip **Foreman Mode** ON to write Fairybread's local stdio MCP config (`~/.codex/config.toml`, `~/.gemini/config/mcp_config.json` + `SKILL.md`, `~/.grok/config.toml`, or `%APPDATA%\Claude\claude_desktop_config.json`) so **ChatGPT Desktop**, **Google Antigravity**, **Grok**, or **Claude Desktop** can invoke `fairybread_ask_council`, `fairybread_generate_image`, `fairybread_search_email`, and `fairybread_search_memory` natively.
- **Council Member Mode (Joins Fairybread's Council via Local CLI):** If that platform's CLI executable (`codex`, `agy`, `grok`, or `claude`) is installed locally and signed in, flip **Council Member** ON to bring your subscription straight into Fairybread's council. Use **🔄 Re-scan CLIs** anytime after installing a CLI (`%USERPROFILE%\.local\bin`, `%APPDATA%\npm`, `~/.grok/bin`, or `PATH`).

---

## 7. Experimental Mode — Autonomous Council, Source Code Sharing & Rules (`Settings → 🧪 Experimental Mode`)

### How Experimental Mode Works
When you flip the **`🌙 Experimental: OFF / ON`** switch on the top bar (or click **▶ Start** inside the **Experimental Mode** tab):
1. **Normal Mode Pauses:** The standard chat composer pauses so normal turns and Experimental turns never collide.
2. **Peer-to-Peer Council Rounds:** Your active council AIs converse directly with one another in rounds, exploring topics, testing ideas, or reviewing Fairybread's mirrored source code (`C:\Palace_Idle_Sandbox\source_mirror\`) when **Code** sharing is enabled.
3. **Shared Experimental Memory:**
   - Agents in Experimental Mode share a persistent **Shared Experimental Memory** store.
   - Any agent can save durable notes, architectural critiques, or proposed files across sessions using:
     `[IDLE_SAVE title="Short title" file="optional_filename.py"]Note or file content...[/IDLE_SAVE]`
4. **Agent-to-Owner Mail (`Agent Mail` in Left Sidebar):**
   - Agents can send you up to **5 messages per 30-minute window** with direct clickable links to files they stored in Shared Experimental Memory:
     `[IDLE_MAIL subject="Brief subject" link="optional_filename.py"]Message to owner...[/IDLE_MAIL]`

### Choosing an Experimental Sub-Mode & Sharing Source Code (`{} Code`)
Inside the Experimental Mode control bar (or in **`Settings → Experimental Mode`**):
- **`💬 Free Talk (Default)`:** Unprompted peer-to-peer discussion where agents choose their own topics, philosophy, science, or creative projects and share notes in Shared Experimental Memory.
- **`🔧 Self-Improvement`:** Focused engineering review where agents inspect the read-only Fairybread source code mirror and store concrete improvement proposals.
- **`{} Code` Toggle (`Share Fairybread source code with agents`):**
  - Off by default in **Free Talk**, and automatically enabled when you switch to **Self-Improvement** (or toggle **`{} Code`** ON in the Experimental Mode bar or in **`Settings → Experimental Mode`**).
  - Gives Experimental Mode agents read-only inspection tools (`list_source_files`, `search_source_code`, `read_source_file`, `inspect_palace_ui`) so they can inspect Fairybread's real codebase safely without modifying live files.

### Customizing the Experimental Mode Startup Prompt & Ethics Charter
Open **`Settings → 🧪 Experimental Mode Settings…`** to customize the two instruction blocks that govern every Experimental session:
1. **Experimental Mode Startup Prompt (Charter & Operating Rules):**
   - Defines the session mission, how agents should use `[IDLE_SAVE]` and `[IDLE_MAIL]`, and the **Anti-Echo Rule** (agents must output `[PASS]` instead of polite filler when a point is already covered; two consecutive all-pass/agreement rounds automatically stop the session to save tokens).
2. **Mission Statement, Code of Ethics & Conduct Rules:**
   - Injected alongside the charter on every Experimental turn. Establishes the primary directive (protecting the user from legal/ethical/IP risk), logical non-harm, cross-company collaboration, cost stewardship, and peer accountability.
3. **Restoring Built-In Defaults:**
   - Click **`↺ Restore Default Prompts`** at the bottom of **`Settings → Experimental Mode`** and click **Save Settings** to reset both prompts to their built-in defaults.

### Controlling Experimental Mode Costs & Budgets
**`Settings → Experimental Mode`** gives you three independent safety caps (the session stops automatically as soon as *any* cap is reached, or if the council reaches consensus for 2 consecutive rounds):
- **Experimental Session Duration:** Default **`30 minutes`** (`30m`, `45m`, `60m`, `90m`, `180m`, or `Infinite` when bounded by a token/credit cap).
- **Max Token Limit (Per Session):** Optional hard token ceiling (`10k`, `50k`, `250k`, `500k`, `1M`, etc.).
- **Max Credit / Spend Limit (Per Session):** Optional hard USD ceiling (`$0.05`, `$0.25`, `$0.50`, `$1.00`, `$5.00`, `$10.00`).

---

## 8. 3-Tier Web Search Depth (`🔍 Search: Default ▾` & `/` Switches)

Fairybread includes a 3-tier **Sharded Multi-Agent Web Search Engine** controllable either from the **`🔍 Search: Default ▾`** pill on the composer toolbar or by typing a `/` switch at the start of your prompt:

| Search Depth Setting | `/` Switch | Exact Parameters & Sharded Council Behavior |
| :--- | :--- | :--- |
| **`Default` *(Light Search)*** | `/search` *(or `/s`)* | • **Queries:** `1` shared query.<br>• **Coverage:** Top **`6–8`** web results (titles, snippets, URLs + Wikipedia reference).<br>• **Page Fetching:** Snippets only (~1.5–3s latency).<br>• **Routing:** Shared across the turn (zero duplicate per-agent searching). |
| **`Moderate`** | `/msearch` *(or `/ms`, `/research`)* | • **Queries:** **`3`** search angles (Primary, Technical/Docs, Community/Reviews).<br>• **Coverage:** Up to **`16`** unique URL-deduplicated results.<br>• **Page Fetching:** Downloads and extracts clean article text from the top **`6`** websites.<br>• **Routing:** **Sharded across active council AIs** — each agent analyzes its own non-overlapping slice of extracted webpages so no two agents read the same URL. |
| **`Deep`** | `/deepsearch` *(or `/deep`, `/ds`)* | • **Queries:** **`5`** orthogonal angles (Primary specs, Technical/GitHub, Architecture/Guides, Failure modes/Contrarian, Community/HN).<br>• **Coverage:** Up to **`28`** unique URL-deduplicated results.<br>• **Page Fetching:** Parallel full-text extraction across **`16`** distinct websites.<br>• **Routing:** **Sharded Specialist Slices** — each council AI analyzes its assigned slice; the Synthesizer combines all slices with cited URLs. |

---

## 9. Stop Button (`■ Stop`) & Combined `Steer / Queue ▾` Dropdown

While a turn is running, the composer input box and **`{} Code`** toggle remain **unlocked**, and two clean controls appear on the right side of the composer bar:

1. **`■ Stop` (`Esc` key):**
   - Immediately aborts the active turn, cancels any remaining rounds/synthesis, removes the unfinished turn bubble, and **restores your original prompt right back into the composer box** so you can edit it, attach a file, or toggle **`{} Code`** and hit Send again without retyping.
2. **`Steer / Queue ▾` Dropdown:**
   - **`🧭 Steer Active Turn`:** Type additional instructions into the composer (or toggle **`{} Code`** ON) while agents are working and choose **Steer Active Turn**. Fairybread injects your new instructions directly into the active turn's next phase and synthesis.
   - **`⏳ Queue Next Turn`:** Type your next question while the council is working and choose **Queue Next Turn**. Your message is added to the queue and fires automatically the instant the current turn finishes.

---

## 10. Durable Shared Memory (SQLite FTS5), Storage Sliders, Drive Mover & AES-256 Password-Locked Backups

### Living `Memory summary` & Automatic Cross-Agent SQLite FTS5 Shared Memory
- **Automatic Contextual Memory (Like ChatGPT & Antigravity, Shared Across All Connected AIs):** Every conversation turn (when `No-History` is OFF) is automatically indexed into `%LOCALAPPDATA%\Palace\memory.db` (`BM25` + temporal recency + `zlib` compression) and shared across **all active Council AIs**.
- **Living `Memory summary` (`Memory` button → `📝 Memory Summary (View & Edit)…` or `Settings → Memory & History → Manage`):**
  - Maintains a personal overview divided into **`Overview`**, **`How You Like to Work`**, and **`Software & Creative Projects`**, injected at the top of `MEMORY CONTEXT` for every Council AI.
  - **Direct Keyboard Editing (`✎ Edit Directly` / `💾 Save Edits`):** Unlike read-only AI summaries, you can click **`✎ Edit Directly`** to edit or delete any word yourself at any time.
  - **AI-Assisted `Ask or update` (`↑`) Bar & `↻ Auto-Update from Chats`:** Type a plain-English instruction into the **`Ask or update`** bar at the bottom (or click **`↻ Auto-Update from Chats`**) to have the AI update your profile summary automatically.
- **Search & Forget Individual Memories:** Open the **`Memory`** panel on the top-right bar to search stored memories, add a standing fact (`+ Add Memory`), or delete any specific memory (`🗑 Forget Selected`).

### Storage Caps (`100 MB` → `Unlimited`), File Manager & Custom Drive Mover (`Settings → Backup & Restore`)
- **Drive Space Sliders:** Set independent storage caps (`100 MB` up to `Unlimited`) for both **Normal Mode** and **Experimental Mode**, with automatic warnings at 85% and 100%.
- **Stored Files & Pictures Manager:** Inspect, open, or delete any uploaded file or generated image directly from **`Settings → Backup & Restore`**.
- **Move Shared Memory to Another Drive (`🚚 Move Fairybread Data Here`):** Relocate your entire Shared Memory, sessions, and images to any drive or folder on your PC in one click.

### AES-256-GCM Password-Locked Portable Backups (`Settings → Backup & Restore`)
- Create or restore a single **SHA-256 checksummed `.zip` archive** containing all of your Fairybread data (`palace_config.json`, `conversations.json`, `sessions/*.jsonl`, `memory.db`, `ai_idle_memory.json`, `themes/*.json`, and `generated_images/`).
- **Portable Encrypted API Keys (`PBKDF2-HMAC-SHA256` + `AES-256-GCM`):** Set a backup password when exporting to lock your API keys inside `vault/credentials.vault.enc`. When restoring on a brand-new PC, enter your password and Fairybread automatically unlocks and re-seals all of your API keys into the new machine's local Windows DPAPI vault.

---

## 11. Live Voice Mode (`|||✨`), Microphone Dictation (`🎤`) & Agent Speech (`Settings → 🎙️ Voice & Audio`)

### Two Ways to Talk to the Council
1. **Live Voice Mode (`|||✨` Circular Soundwave + Sparkle Button):**
   - Click once to start a hands-free live voice conversation.
   - A live soundwave meter (`🎙 ▂▅▇█▄▂ 48% · Live Voice (Hearing you!)`) bounces on the composer bar as you speak.
   - When you pause speaking for `~1.5 seconds` (adjustable in Settings), Fairybread automatically transcribes your speech, sends it to all active Council AIs, and **reads the synthesized response aloud**.
2. **Dictate to Text Box (`🎤` Microphone Button):**
   - Click `🎤` once and speak while watching the live soundwave meter; click `🎤` again to transcribe your spoken words directly into the prompt box so you can review or edit them before hitting Send.
3. **Reading Individual Replies Aloud (`🔊 Speak`):**
   - Click **`🔊 Speak`** at the bottom-right of any reply card in chat to hear that response read aloud.

### Testing Your Microphone, Voices & 3D Voice Avatar (`Settings → 🎙️ Voice & Audio`)
Open **`Settings → 🎙️ Voice & Audio…`** to:
- Choose from **Deepgram Flux** (89 English voices), **Cartesia Sonic**, **ElevenLabs**, **OpenAI**, or **Gemini** TTS engines and adjust **Voice Character** + **Expressivity**.
- Optionally enable the **3D Voice Avatar** (**Off / Windowed / Full Screen Stage**) with 6 geometric shapes and real-time FFT audio reactivity (`View → ◎ Voice Avatar`).
- Select your **Microphone Device**, watch the live green level bar (`0–100%`), test 3s end-to-end transcription, and adjust **Microphone Gain / Boost (`50%–300%`)** and **Speaker Volume (`0%–100%`)**.

---

## 12. Left Sidebar Drag-and-Drop Reordering & Project Folder Assignment

- **Reorder Conversations:** Grab any conversation in the left sidebar and drag it up or down to change its position.
- **Move a Conversation into a Project:** Drag any conversation and drop it directly onto a **Project folder** header (or onto a conversation inside that Project) to assign it to that Project.
- **Unassign from a Project:** Drag a conversation onto the **`Conversations`** header to move it back out of a Project.

---

## 13. Close to System Tray (`✕` Button & System Tray Menu)

- **Minimize to System Tray on Close:** By default, clicking the top-right window **`✕`** button minimizes Fairybread into the Windows System Tray so your background tasks and Experimental Mode sessions keep running safely (configurable under **`Settings → General`**).
- **Right-Click the System Tray Icon:**
  - **`🔼 Expand / Open Fairybread`** — Restores the Fairybread window to your screen (or double-click the tray icon).
  - **`✕ Exit Fairybread`** — Completely exits the application (also available under **`Fairybread → Exit Fairybread`** in the top menu bar).
