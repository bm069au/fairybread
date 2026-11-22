# Fairybread Privacy Policy

**Last Updated:** 2026-11-22  
**Developer / Publisher:** Brett Martin Moore (`bm069au@gmail.com`)  
**Website:** https://fairybread.me

---

## 1. Local-First Privacy Summary

Fairybread is designed around **local-first, zero-telemetry architecture**:

- **No Fairybread Account or Telemetry Servers:** Fairybread does not create cloud accounts, sell user data, display third-party ads, or upload usage analytics, crash dumps, or telemetry to the developer.
- **100% Local Data Storage:** Your conversations, Memory Palace database (`memory.db`), Experimental Mode notes/sandbox files, uploaded attachments, generated images, and app settings remain on your device under `%LOCALAPPDATA%\Palace` (or whichever custom local folder/drive you choose in **Settings → Backup & Restore**).
- **Windows DPAPI Encrypted Credentials:** API keys you enter are encrypted on disk using your Windows user account's **Data Protection API (DPAPI)** inside `%LOCALAPPDATA%\Palace\credentials.json`. Password-locked backup archives (`.zip`) protect exported keys using **PBKDF2-HMAC-SHA256 + AES-256-GCM**.

---

## 2. Third-Party AI Providers You Choose (Bring Your Own Key)

Fairybread connects directly from your PC over HTTPS to the third-party AI API providers **you** explicitly configure and enable with your own API keys (for example: Google Gemini, OpenAI, Anthropic, xAI, DeepSeek, Groq, Qwen/DeepInfra, Cohere, Mistral, Cerebras, OpenRouter, Deepgram, or ElevenLabs):

- **What is sent:** When you submit a prompt or request a response/voice generation, only the prompt text, relevant local conversation/memory context, and any files or images you explicitly attach for that request are transmitted directly to the active providers' API endpoints.
- **Provider Policies Apply:** Once transmitted to an external AI provider, handling and retention of that API request are governed by that provider's own privacy policy and terms of service (for local Ollama models or Windows native speech/spellcheck, requests stay on your PC).
- **You Stay in Control:** You can toggle providers ON/OFF, use **No-History** mode, remove API keys, or edit/delete your local Memory Palace at any time.

---

## 3. Microphone & Speech Features

- **Microphone Access:** Fairybread uses your system microphone **only** when you explicitly activate voice dictation or Live Voice Mode. Audio is never recorded or transmitted in the background while voice features are off.
- **Speech Recognition & Synthesis:** Depending on your selected settings in **Settings → Voice & Audio**, speech audio may be processed locally using Windows speech APIs or transmitted to your configured voice/AI provider (e.g., OpenAI, Gemini, Deepgram, ElevenLabs) solely to fulfill that request.

---

## 4. Model Catalog & Pricing Sync (`fairybread.me`)

- When enabled in **Settings → General**, Fairybread periodically fetches a public, static JSON file (`https://fairybread.me/feed/catalog.json`, cached locally for 6 hours) to keep supported model names and published API token rates accurate.
- This request uses a standard HTTP `GET` with `User-Agent: Fairybread` and sends **zero** personal information, hardware IDs, API keys, or conversation data.
- For builds distributed via the **Microsoft Store (MSIX)**, application updates are managed exclusively by the Microsoft Store.
- You can turn catalog auto-refresh off anytime in **Settings → General**.

---

## 5. External Agent Bridge (Local MCP)

- If you enable the optional **External Agent Bridge (MCP)** in Settings, Fairybread writes local configuration entries for supported desktop coding/AI apps on your machine (ChatGPT Desktop/Codex, Antigravity, Grok CLI, Claude Desktop). Nothing is shared remotely unless you run those local tools.

---

## 6. Data Retention, Backups & Uninstallation

- **Deleting Data:** You can delete stored files/images inside **Settings → Backup & Restore**, delete individual discussions, or uninstall Fairybread cleanly at any time via Windows **Installed apps** / **Programs and Features**.
- **Clean Removal:** Uninstalling Fairybread removes the installed application binaries, shortcuts, MCP registrations, and registry entries, and lets you choose whether to keep or erase `%LOCALAPPDATA%\Palace` user data.

---

## 7. Contact

Questions about privacy, data handling, or licensing?  
Email: **Brett Martin Moore** — [`bm069au@gmail.com`](mailto:bm069au@gmail.com)
