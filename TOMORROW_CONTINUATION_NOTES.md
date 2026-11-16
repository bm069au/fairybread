# Fairybread — Continuation Memory & Roadmap (For Tomorrow's Session)

**Saved:** 2026-11-16  
**Creator:** Brett Martin Moore (`bm069au` / `bm069au@gmail.com`)  
**Repository:** `https://github.com/bm069au/fairybread`  
**Sponsors Page:** `https://github.com/sponsors/bm069au`  
**Latest Release:** `https://github.com/bm069au/fairybread/releases/tag/v0.9.1-beta`  
**Local Beta Installer ZIP (for Darren & testers):** `E:\Visual_studio\Palace\dist\Fairybread_Beta_v0.9.1_Installer.zip`

---

## 1. GitHub Sponsors Dashboard Copy (Ready to Paste in Browser if Not Yet Saved)

Dashboard URL: `https://github.com/sponsors/bm069au/dashboard`  
*(Note: No goal bar is used — we do not want an artificial ceiling on donations.)*

### A. Left Sidebar: `Profile details` → "About my work"

```markdown
G'day — I'm Brett Moore, the creator of **Fairybread**.

### Why Fairybread Exists: No Lock-In, 100% Local Privacy, No Monthly Subscriptions
The real benefit of Fairybread is to **replace dedicated corporate workspaces like ChatGPT Plus, Claude Pro, and Grok** with one platform that *you* own:
- **Zero Lock-In & No Monthly Fees:** Stop paying multiple $20–$30/month subscriptions. With Fairybread, you connect your own API keys (or local models) and only pay for the exact tokens you actually use—no monthly fees, no vendor lock-in, just freedom.
- **100% Local & Private Persistent Memory:** Your data and Memory Palace stay 100% on your own machine. Even if you switch AI providers tomorrow, all your history, context, and long-term memory stay with you.
- **Everything a Modern AI Workspace Should Do (And More):** Read and search your emails, access your local files and desktop, generate high-resolution artwork, bridge into coding tools, and have multiple AIs collaborate, debate, and verify answers together instead of trusting a single model blindly.

### The Experimental Side: Autonomous Idle Mode
Fairybread also includes an automated **Idle Mode** that gives the agents their own isolated Memory Palace where they can talk freely, share information and files, and collaborate on their own.
- **Your Rules, Your Sandbox:** Out of the box, it includes sensible baseline rules around safety, law, logic, and ethics—and you can set your own standing instructions and rules for the agents to follow.
- **Upcoming Idle Mode Experiment Add-Ons:** I am building add-on packs that turn Idle Mode into a true multi-agent experimental lab—so you can run the same kind of fascinating multi-AI experiments at home that the big AI companies run behind closed doors.

### A Bit About Me (And Why Your Donation Really Helps)
In real life, I am a disabled man living on a disability pension, and I struggle to pay my everyday bills. 

I made Fairybread free for personal use (up to 2 seats) because I want everyone to have access to this kind of freedom and privacy. If you download Fairybread, love what it does, and can spare a donation, **it will genuinely help me pay my bills and keep going.** I'm not begging—just asking nicely and letting you know that your support makes a massive, real-world difference to my life. My appreciation is enormous.

### What Supporters Get
There is a lot happening, and I want to look after the people who help me out:
- **The Fairybread Newsletter:** Updates on new features, Idle Mode experiments, and my upcoming animation series.
- **Beta Test Group & Code Requests:** I take code and feature requests from supporters and invite you into the beta group to test new builds first.
- **Themes & Idle Mode Add-Ons:** Custom visual themes, fun extras, and new experimental packs for Idle Mode.
```

### B. Left Sidebar: `Sponsor tiers` → **One-time tiers**
- **`$5 one time`**:
  > **Every Bit Helps — Thank You**  
  > Living on a disability pension means every single contribution genuinely helps me pay my bills. If you're enjoying Fairybread and want to say thanks, I appreciate this more than you know. Plus, you'll get the GitHub Sponsor badge on your profile.
- **`$10 one time`**:
  > **Supporter + The Fairybread Newsletter**  
  > Thank you for helping me out! Along with my huge gratitude and the GitHub Sponsor badge, you'll get the **Fairybread Newsletter**—covering new features, Idle Mode experiments, upcoming themes, and behind-the-scenes updates on my animation series.
- **`$25 one time`**:
  > **Release Notes Credit + Newsletter & Early Add-On Previews**  
  > A massive help toward my bills—thank you!  
  > - A permanent thank-you mention in our **Release Notes**  
  > - **The Fairybread Newsletter**  
  > - Early previews of new **Themes** and **Idle Mode Experiment Add-Ons** as I build them
- **`$50 one time`**:
  > **Beta Test Group + Priority Code Requests + Newsletter**  
  > A $50 donation makes a huge practical difference to my life on a pension, and I want to give plenty back in return:  
  > - **Beta Tester Group:** Join the beta group to test new builds, themes, and Idle Mode experiment add-ons before anyone else  
  > - **Priority Code & Feature Requests:** Have a feature idea or an add-on you want to see in Fairybread? I will prioritize looking at and building your suggestions  
  > - **The Fairybread Newsletter** + early access to info and merch for my upcoming animation series  
  > - Release Notes credit
- **`$350 one time`**:
  > **1 Hour 1-on-1 Consulting + Custom Code Modifications**  
  > If you help me out at this level, I will invest serious time into looking after you:  
  > - **1 Hour of 1-on-1 Consulting:** Personal help getting up and running or tailoring Fairybread to your setup  
  > - **Custom Code Modifications:** Need Fairybread to do something I didn't anticipate, or want a custom Idle Mode experiment or workflow built for you? Code changes are negotiable and I'll work with you directly  
  > - Includes the Beta Test Group, Newsletter, and all supporter perks

---

## 2. Completed Fixes in Tonight's Session (2026-11-16)

1. **Multi-Image / Plural Drawing Regex & Fence-Unwrapping Fixed (`orchestrator.py`, `synthesizer.py`, `palace_theme.py`):**
   - Fixed `_DIRECT_DRAW_VERB_RE` to match plural visual nouns (`banners`, `images`, `pictures`, `photos`, `covers`, `backgrounds`) and natural phrasing (*"make 3 different banners"*, *"I'd like a new background picture"*).
   - Stopped `orchestrator.py` from stripping `[GENERATE_IMAGE ...]` tags when the prompt mentions any visual/banner/picture topic.
   - Added `_unwrap_real_image_tags()` in `palace_theme.py` so if an AI wraps a real `[GENERATE_IMAGE ...]` tag inside ```` ```text ... ``` ```` fences or standalone line backticks, it automatically unwraps and renders the high-res image instead of displaying an empty code box.
   - Updated the Prompt Architect & Synthesizer rules so multi-image requests (e.g., *"make 3 different banners and let me choose"*) immediately render all 3 images rather than returning text descriptions asking the user to pick one first.
2. **Screen Flicker Fixed (`palace_gui.py`):**
   - Removed the `widget.setParent(None)` calls inside `_relayout_agent_bar()` and stopped duplicating `Round 1: 7/8 AIs responded` into `status_label` on every per-agent tick.
3. **UI De-Crowding, Combined `Steer / Queue ▾` Dropdown & Menu Cleanup (`palace_gui.py`, `palace_config.py`):**
   - Combined `Steer` + `Queue` into a single neutral dropdown button (`Steer / Queue ▾`) and styled `■ Stop` in neutral grey (`#161b22`) until hovered.
   - Hid disabled pre-turn setup buttons while a turn is running so the composer row never crowds or clips.
   - Replaced the duplicated `AIs` top menu with a clean `Mode` menu (**Normal AI Mode** / **Idle Experimental Mode**).
   - Shortened `Qwen (DeepInfra / DashScope)` → `Qwen` so the bottom chip no longer clips to `✦ Qwen ...`.
   - Added live model discovery (`↻ Fetch Live Models` dropdown in `Settings → AI Providers`) and set Cerebras to `gpt-oss-120b` with automatic failover to `qwen-3.8-27b` (`450 req/min`).
4. **Drive Space Sliders (`100 MB` → `Unlimited`), Custom Drive Mover, File/Image Download & Delete Manager, AES-256 Password-Locked Backups, and 6-AI Council Memory Optimizations:**
   - All implemented, unit-tested, and pushed to `https://github.com/bm069au/fairybread`.
5. **Sidebar Drag-and-Drop, Tight Line Spacing, Vector Folder Icons & Voice Mode (`2026-11-17`):**
   - Tightened left sidebar row spacing (`padding: 2px 6px; margin-bottom: 0px;`, `24px` height) to match Antigravity's density.
   - Added monochrome vector folder icons (`folder_grey_qicon`) on every Project row in the sidebar.
   - Added `SidebarSessionList(QListWidget)` (`session_store.reorder_and_assign_sessions`) so conversations can be dragged up/down to reorder them OR dragged and dropped directly onto a Project folder (or onto `Conversations` to unassign from a project).
   - Added `voice_service.py` + `🎤` Microphone button in the composer (`transcribe_audio_file` via Groq `whisper-large-v3-turbo`, OpenAI `whisper-1`, or Gemini `gemini-2.5-flash`) so voice dictation enters text for all 8 Council AIs at once.
   - Added `🔊 Speak` on every agent response card in chat (`speak:<idx>`) + optional auto-speak for final synthesized replies + the **Voice Mode** card (`Voice`, `Microphone`, `Volume 0–100%`, `🔊 Test Voice`) in `Settings → General & Voice Mode`.
   - Created `C:\Users\moore\Desktop\Fairybread.lnk` desktop shortcut.

---

## 3. Tomorrow's Next Tasks

1. **Build the Official Fairybread Website (Using Brett's Registered Domain):**
   - Get the exact domain name and registrar/DNS provider from Brett.
   - Design and build the landing page showcasing:
     - **Freedom from Corporate Lock-In** (Replace ChatGPT Plus / Claude Pro / Grok subscriptions; 100% local private Memory Palace; pay only raw API usage).
     - **Autonomous Idle Mode Multi-Agent Lab** (run the same experiments the big AI companies run).
     - **Direct Installer Download (`v0.9.1-beta`)** & Screenshots.
     - **One-Click USD Donation Tiers (`$5`, `$10`, `$25`, `$50`, `$350`, `Custom`)** + **Corporate Seat Licensing (`> 2 Seats`)**.
     - **Newsletter & Beta Test Group Sign-Up / Info**.
2. **Idle Mode Experiment Add-On Packs Architecture:**
   - Design plug-and-play `.json` / `.md` experiment scenarios for Idle Mode (e.g., Socratic Debate, Prisoner's Dilemma / Game Theory Lab, Red-Team Code Audit, Sci-Fi Worldbuilding Room, Ethics & Alignment Stress Test) that users can load in 1 click.
3. **Sponsor Newsletter Workflow:**
   - Use GitHub Sponsors' built-in `Manage → Newsletters` (`https://github.com/sponsors/bm069au/dashboard/newsletters`) to send updates directly to supporters.
