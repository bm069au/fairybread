# Fairybread (Beta) — User Guide & Operating Instructions

**Created by Brett Martin Moore (`bm069au@gmail.com`)**

Fairybread is a democratic multi-AI council desktop workspace where multiple frontier AI models collaborate, cross-examine ideas, share a persistent Memory Palace, and generate high-resolution photography, graphics, social media banners, and 300-DPI print artwork.

---

## 1. High-Resolution Image & Graphic Generation

Fairybread uses a two-stage **"Prompt Architect → High-Resolution Image Renderer"** pipeline—similar to how the native ChatGPT app works, but upgraded to route across your strongest visual engines.

### The Two Drawing Modes

#### Mode A: Default 1-Pass Drawing Mode (Automatic & Fast)
Whenever you ask for an image, photo, or graphic normally, Fairybread automatically uses **1-Pass Direct Drawing Mode**:
- **What you type:**
  - `"Draw me a brown dog on a black carpet in front of a fireplace"`
  - `"Render a photorealistic ginger tabby cat sitting near a sunlit window with curtains in the background"`
  - `"Create a YouTube banner for a retro gaming channel"`
- **How it works under the hood:**
  1. Only **one** top Prompt Architect (`DeepSeek`, `OpenAI`, or `Gemini`) runs in a single fast pass—you won't wait for 6 agents to chime in or generate competing variations.
  2. The Prompt Architect expands your short request into a detailed photographic or artistic specification (lighting physics, lens depth-of-field, textures, background elements, and composition).
  3. That single specification is rendered at maximum quality by the high-resolution image engine (`gemini-3-pro-image` *Nano Banana Pro* → `gemini-3.1-flash-image` *Nano Banana 2* → OpenAI `gpt-image-2`).

#### Mode B: Council-Assisted Prompt Brainstorming Mode (On Demand)
When you are working on a complex or tricky visual scene and want **all active council agents** to help design the prompt before a single image is rendered, simply ask the council to help in your prompt:
- **Trigger phrases you can use:**
  - `"All agents work on the prompt and then only one of you execute the drawing: ..."`
  - `"All agents help with the prompt for a hyperrealistic ..."`
  - `"Council brainstorm the prompt for ..."`
  - `"Everyone work on the prompt and render one image of ..."`
- **How it works under the hood:**
  1. All active council AIs deliberate on the scene's lighting, anatomy, perspective, and fine details.
  2. Individual agent deliberation bubbles never execute duplicate images.
  3. The **Synthesizer** merges the council's best visual details into **one** master `[GENERATE_IMAGE ...]` tag and renders **one** final high-resolution image.

---

## 2. Image Sizes, Social Media Presets & 300-DPI Print Sizes

### Default Size & Quality
- **Default Quality:** Always set to the **highest possible fidelity (`quality="high"`)**.
  - To request a faster draft render (`~8.5 seconds` via `gemini-3.1-flash-image`), simply mention `"fast"`, `"draft"`, or `"low quality"` in your prompt.
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
- **`Choose AIs (N)`:** Pick which AI providers are active, or choose a quick preset squad (**Code AIs**, **Light Chat**, **Generalist**, **Graphics & Vision**, **Work Mode**).
- **`Council` Toggle (Purple when ON):**
  - **ON (2-Round Peer Deliberation):** Agents answer in Round 1, inspect and critique each other's responses in Round 2 (replying `[PASS]` if a peer already nailed it), and the Synthesizer combines the best insights into one final answer.
  - **OFF (1-Round Fast Synthesis):** Agents answer in one parallel wave and synthesize immediately.
- **`Tangent` Toggle:** Ask a side question without including prior conversation history in the prompt, while still saving the exchange to your current chat.
- **`{} Code` Toggle:** Grants the council read-only visibility into Fairybread's own source code (`E:\Visual_studio\Palace\`) so the agents can diagnose or design upgrades for their own app.
- **`🎤` Dictate Button:** Click once and speak (`🎙 ▂▅▇█▄▂` shows your live mic level); click again to transcribe your voice directly into the prompt box for all Council AIs.
- **`|||✨` Live Voice Mode Button (Circular Soundwave + Sparkle):** Hands-free live voice conversation with the Council. Automatically detects when you pause speaking (`~1.5s`), sends your spoken prompt to the Council, and reads the synthesized reply back to you aloud.
- **`No-History` (Top Bar):** Ephemeral privacy mode—neither reads nor saves session history.
- **`Idle: OFF / ON` (Top Bar):** Switches to the autonomous **Idle Mode Sanctuary**, where agents converse freely, test their shared Idle Palace, and send you improvement proposals via **Agent Mail**.

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
- **Email Completion Alerts:** Automatically emails your own address with the full synthesized answer (and attaches any generated high-res PNGs!) when a large job (`> 30s`) or Autonomous Idle Mode session completes.

---

## 6. External Agent Bridge — Connecting Antigravity, Claude, or ChatGPT (`Settings → 🔗 External Agent Bridge`)

You can allow external coding/desktop agents (**Google Antigravity**, **Anthropic Claude Desktop / Claude Code**, **OpenAI ChatGPT Desktop / Codex CLI**, or **Cursor / Windsurf**) to call your local Fairybread installation as a tool via **MCP (Model Context Protocol)**:

1. Open **`Settings → 🔗 External Agent Bridge (Antigravity / Claude / ChatGPT)…`**.
2. Choose which capabilities external agents may invoke:
   - `fairybread_ask_council` — Consult your 6-AI Fairybread council and return the democratic synthesis.
   - `fairybread_generate_image` — Render 300-DPI images, YouTube/Facebook banners, or wallpapers.
   - `fairybread_search_email` — Run an exhaustive zero-truncation email search.
   - `fairybread_search_memory` — Query your Shared Memory Palace.
3. Click the one-click installer button for your platform:
   - **`🔗 Connect Google Antigravity`** — Installs the `fairybread-council` skill into `~/.gemini/config/skills/fairybread-council/SKILL.md`.
   - **`🔗 Connect Claude Desktop / Claude Code`** — Automatically registers the `fairybread` MCP server in `%APPDATA%\Claude\claude_desktop_config.json`.
   - **`📋 Copy MCP Config (ChatGPT Desktop / Cursor)`** — Copies the JSON-RPC MCP server configuration to your clipboard.

---

## 7. Idle Mode Sanctuary — How It Works, Writing Prompts & Setting Rules (`Settings → Idle Mode`)

*(Note: Idle Mode is currently an advanced Beta feature for exploring autonomous multi-agent collaboration and persistent cross-session memory).*

### How Idle Mode Works
When you flip the **`🌙 Idle: OFF / ON`** switch on the top bar (or open the **Idle Mode Sanctuary** tab and click **▶ Start / Resume Autonomous Idle**):
1. **Normal Mode Pauses:** The standard chat composer pauses so normal turns and Idle turns never collide.
2. **Peer-to-Peer Council Rounds:** Your active council AIs converse directly with one another in rounds, exploring topics, testing ideas, or reviewing the application's mirrored source code (`C:\Palace_Idle_Sandbox\source_mirror\`).
3. **Shared Persistent Idle Palace (`< 10 MB` cap):**
   - Unlike normal stateless API calls where an AI forgets everything after a session ends, agents in Idle Mode share a persistent **Idle Palace** database.
   - Any agent can save durable notes, architectural critiques, or proposed files across sessions using:
     `[IDLE_SAVE title="Short title" file="optional_filename.py"]Note or file content...[/IDLE_SAVE]`
4. **Agent-to-Owner Mail (`Agent Mail` in Left Sidebar):**
   - Agents can send you up to **5 messages per 30-minute window** with direct clickable links to files they stored in the Shared Idle Palace:
     `[IDLE_MAIL subject="Brief subject" link="optional_filename.py"]Message to owner...[/IDLE_MAIL]`

### Choosing an Idle Sub-Mode
Inside the Idle Mode tab, you can switch between two operating sub-modes at any time:
- **`💬 Free Talk Lounge (Default)`:** Unprompted peer-to-peer discussion where agents choose their own topics, philosophy, science, or creative projects and share notes in the Idle Palace.
- **`🛠 Self-Improvement Workshop`:** Focused engineering review where agents inspect the read-only source code mirror (`C:\Palace_Idle_Sandbox\source_mirror\`) and store concrete improvement proposals in the Idle Palace.

### How to Write or Customize the Idle Startup Prompt & Rules
Open **`Settings → Idle Mode Settings…`** to customize the two instruction blocks that govern every Idle session:
1. **Idle Startup Prompt (Charter & Operating Rules):**
   - Defines the session mission, how agents should use `[IDLE_SAVE]` and `[IDLE_MAIL]`, and the **Anti-Echo Rule** (agents must output `[PASS]` instead of polite filler when a point is already covered; two consecutive all-pass/agreement rounds automatically stop the session to save tokens).
   - **Tip for custom prompts:** If you want the agents to explore a specific research problem while you're away, add a line at the bottom of the Idle Startup Prompt such as:
     `Current Focus Topic: Explore and store 3 competing architectural designs for X in the Shared Idle Palace.`
2. **Mission Statement, Code of Ethics & Conduct Rules:**
   - Injected alongside the charter on every Idle turn. Establishes the primary directive (protecting the user from legal/ethical/IP risk), logical non-harm, cross-company collaboration, cost stewardship, and peer accountability.
3. **Restoring Built-In Defaults:**
   - Fairybread ships with complete, ready-to-run defaults for both the **Idle Startup Prompt** and the **Mission Statement & Code of Ethics**. If you ever edit them and want to return to the standard text, click **`↺ Restore Default Prompts`** at the bottom of **`Settings → Idle Mode`** and click **Save Settings**.

### Controlling Idle Mode Costs & Budgets
To prevent runaway API usage, **`Settings → Idle Mode`** gives you three independent safety caps (the session stops automatically as soon as *any* cap is reached, or if the council reaches consensus for 2 consecutive rounds):
- **Idle Session Duration:** Default **`30 minutes`** (`30m`, `45m`, `60m`, `90m`, `180m`, or `Infinite` when bounded by a token/credit cap).
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

## 10. Durable Memory Palace (SQLite FTS5), Storage Sliders, Drive Mover & AES-256 Password-Locked Backups

### Living `Memory summary` & Automatic Cross-Agent SQLite FTS5 Memory Palace
- **Automatic Contextual Memory (Like ChatGPT & Antigravity, Shared Across All 8 AIs):** Every conversation turn (when `No-History` is OFF) is automatically indexed into `%LOCALAPPDATA%\Palace\memory.db` (`BM25` + temporal recency + `zlib` compression) and shared across **all active Council AIs**.
- **Living `Memory summary` (`Memory` button → `📝 Memory Summary (View & Edit)…` or `Settings → Memory & Personalization → Manage`):**
  - Maintains a personal overview divided into **`Overview`**, **`How You Like to Work`**, and **`Software & Creative Projects`**, injected at the top of `MEMORY CONTEXT` for every Council AI.
  - **Direct Keyboard Editing (`✎ Edit Directly` / `💾 Save Edits`):** Unlike read-only AI summaries, you can click **`✎ Edit Directly`** to edit or delete any word yourself at any time.
  - **AI-Assisted `Ask or update` (`↑`) Bar & `↻ Auto-Update from Chats`:** Type a plain-English instruction into the **`Ask or update`** bar at the bottom (or click **`↻ Auto-Update from Chats`**) to have the AI update your profile summary automatically.
- **Search & Forget Individual Memories:** Open the **`Memory`** panel on the top-right bar to search stored memories, add a standing fact (`+ Add Memory`), or delete any specific memory (`🗑 Forget Selected`).

### Storage Caps (`100 MB` → `Unlimited`), File Manager & Custom Drive Mover (`Settings → Backup & Restore`)
- **Drive Space Sliders:** Set independent storage caps (`100 MB` up to `Unlimited`) for both **Normal Mode** and **Idle Mode**, with automatic warnings at 85% and 100%.
- **Stored Files & Pictures Manager:** Inspect, open, or delete any uploaded file or generated image directly from **`Settings → Backup & Restore`**.
- **Move Palace Memory to Another Drive (`🚚 Move Palace Data Here`):** Relocate your entire Memory Palace, sessions, and images to any drive or folder on your PC in one click.

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

### Testing Your Microphone & Speaker (`Settings → 🎙️ Voice & Audio`)
Open **`Settings → 🎙️ Voice & Audio (Microphone & Speaker)…`** to:
- Select your **Microphone Device** and click **`🎤 Start Live Mic Level Test`** to watch the live green level bar (`0–100%`) move as you speak.
- Click **`🧪 Record 3s & Test Transcription`** to record a 3-second test phrase and verify end-to-end transcription on screen.
- Adjust **Microphone Gain / Boost (`50%–300%`)** so quiet microphones pick up clearly, and adjust **Speaker Voice** and **Speaker Volume (`0%–100%`)**.

---

## 12. Left Sidebar Drag-and-Drop Reordering & Project Folder Assignment

- **Reorder Conversations:** Grab any conversation in the left sidebar and drag it up or down to change its position.
- **Move a Conversation into a Project:** Drag any conversation and drop it directly onto a **Project folder** header (or onto a conversation inside that Project) to assign it to that Project.
- **Unassign from a Project:** Drag a conversation onto the **`Conversations`** header to move it back out of a Project.
