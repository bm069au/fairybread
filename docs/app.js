// Fairybread.me Static Portal Engine (News, Custom JSON Color Theme Studio, Donors, Code Viewer & Release Resolver)

const FORUM_DISCUSSIONS_URL = 'https://github.com/bm069au/fairybread/discussions';

const STORAGE_KEYS = {
  userSkins: 'fb_custom_user_skins_v2',
};

// Purge retired localStorage keys from older builds so returning browsers never display stale threads, fake accounts, or retired presets
const LEGACY_KEYS_TO_CLEAR = [
  'fb_news_posts_v2',
  'fb_forum_threads_v2',
  'fb_forum_threads_v1',
  'fb_current_user_v1',
  'fb_mod_queue_v1',
  'fb_badge_review_queue_v1',
  'fb_theme_skins_v1',
  'fb_donor_wall_v1',
  'fb_supabase_config_v1',
];

const DEFAULT_NEWS = [
  {
    id: 'news-v093-overview',
    title: 'Inside Current Fairybread: Guided Setup Wizard, OpenRouter Hub, Live Cost Tickers, Weather Radar & $0.00 Recall',
    tag: 'Platform Update',
    date: '2026-11-22',
    author: 'Brett Martin Moore (bm069au)',
    body: `Fairybread has taken a major leap forward to make multi-AI desktop use simple for beginners while giving power users complete control over memory and spend:

• Guided Setup Wizard & Selective Backup Restore: Walks you through picking your exact needs (Light Chat & Research, Study & Assignments, Coding, or Everything), opens each provider's key page in a live tick-off checklist, and lets you restore saved API keys, settings, or memories together or individually.
• All-in-One OpenRouter Hub (Or Direct Keys): Enter a single OpenRouter key to unlock 300+ models across Council seats with a strict prepaid cap—leaving only optional Graphics and Deepgram Flux Voice. Direct keys always keep priority.
• 3-Layer Live Cost Tickers: Track cumulative and resettable spend per provider, per-picture costs on generated artwork, and live ongoing Voice Mode spending right in the workspace bar—zero hidden surprises.
• 100% Local Memory Palace + $0.00 Free-Agent Recall: Answers already stored locally on your PC can be pulled by free-tier agents for $0.00 instead of repeating paid web searches.
• Live Weather Radar Maps & Natural Multi-Turn Rapport: Weather questions render RainViewer radar maps plus hourly & 7-day forecasts inline in chat, alongside pure Steer/Queue mid-turn controls, honest amber Cutoff chips, and natural conversational synthesis.
• 1-Click In-App Updates & Update-Only Installer: Download new versions from the top notice bar, keep all settings untouched with the "Update only" option, and hot-reboot cleanly.`,
  },
  {
    id: 'news-founders-note',
    title: 'Why I Built Fairybread (Founder’s Note)',
    tag: "Founder's Note",
    date: '2026-11-22',
    author: 'Brett Martin Moore (bm069au)',
    body: `Every major AI vendor asks for another $20–$30/month subscription, siloes your conversation history on their servers, and leaves you stuck with a single perspective. If you cancel, move platforms, or hit opaque limits, your workflow stops.

I built Fairybread to fix three things permanently:
1. Own Your Memory: Everything is indexed locally in SQLite FTS5 right on your own hard drive alongside an editable Living Memory Summary—shared across whichever AI models you choose.
2. Pay for What You Actually Use: Use free tiers, local Ollama, one prepaid OpenRouter hub, or your own direct API keys—and watch every fraction of a cent live in real time.
3. Let Top Models Collaborate: Instead of trusting one model blindly, your active agents cross-check each other, render charts, weather radar maps, and 300-DPI artwork locally, and speak naturally through Deepgram Flux.

Have a feature idea or noticed something we missed? Post it on our GitHub Community Forum (github.com/bm069au/fairybread/discussions)—useful suggestions adopted into Fairybread are credited inside the app under About -> Community Contributors.`,
  },
  {
    id: 'news-dev-split-2026-11-19',
    title: 'Public vs. Developer Editions: Why Live Self-Modification is Restricted to Developer Builds',
    tag: 'Architecture & Safety',
    date: '2026-11-19',
    author: 'Brett Martin Moore (bm069au)',
    body: `A quick note on the architectural difference between the standard Public Edition and the internal Developer Edition of Fairybread:

In Public releases, your AI Council has full access to 100% local Shared Memory, Agent Mail, and autonomous reasoning in Experimental Mode, while live autonomous self-modification of the underlying Python codebase is disabled.

There are two vital reasons for this:
1. Stability & Security: Allowing public installations to rewrite their own codebase autonomously across thousands of PCs would produce unverified, divergent builds that could bypass safety checks or break local environments.
2. Licensing & Cryptographic Integrity: Keeping public builds immutable preserves Ed25519 / SHA-256 verification and the Proprietary Source-Available license.

How to contribute improvements:
If you spot a bug or your Experimental Mode Council drafts a solid improvement, post the idea or diff on GitHub Discussions (github.com/bm069au/fairybread/discussions) or email bm069au@gmail.com. Accepted contributions are tested against the full regression suite and credited under About -> Community Contributors.`,
  },
  {
    id: 'news-themes-2026-11-22',
    title: '14 Built-in & Curated .JSON Color Themes (Safe Palette Files, Zero Executable Code)',
    tag: 'Color Themes',
    date: '2026-11-22',
    author: 'Brett Martin Moore (bm069au)',
    body: `Every Fairybread theme is a clean, human-readable .json color palette dictionary stored in %LOCALAPPDATA%\\Palace\\themes\\.

Because themes contain only hex color tokens (plus an optional sprinkles accent flag) and zero executable code, you can inspect, customize, download, and share palettes safely—from Midnight Dark and Winamp Classic 1999 (color homage) to Nord Frost, Amber CRT 1984, Tokyo Night, Catppuccin Mocha, Gruvbox Warm Studio, and Emerald CAD Blueprint.`,
  },
];

// 14 polished 13-token JSON palettes strictly matching palace_theme.py schema
const DEFAULT_SKINS = [
  {
    id: 'dark',
    name: 'Midnight Dark (Official Default)',
    author: 'bm069au',
    origin: 'Built-in',
    theme: {
      id: 'dark',
      name: 'Midnight Dark (Default)',
      bg_main: '#0d1117',
      bg_sidebar: '#11161d',
      bg_card: '#161b22',
      bg_hover: '#1f242d',
      border: '#21262d',
      text_primary: '#e6edf3',
      text_secondary: '#c9d1d9',
      text_muted: '#6e7681',
      user_bubble_bg: '#1c2128',
      user_bubble_border: '#30363d',
      user_bubble_text: '#f0f6fc',
      send_bg: '#e6edf3',
      send_fg: '#0d1117',
      sprinkles: false,
    },
  },
  {
    id: 'light',
    name: 'Clean Daylight',
    author: 'bm069au',
    origin: 'Built-in',
    theme: {
      id: 'light',
      name: 'Clean Daylight',
      bg_main: '#ffffff',
      bg_sidebar: '#f6f8fa',
      bg_card: '#f3f4f6',
      bg_hover: '#eaeef2',
      border: '#d0d7de',
      text_primary: '#1f2328',
      text_secondary: '#24292f',
      text_muted: '#57606a',
      user_bubble_bg: '#ddf4ff',
      user_bubble_border: '#54aeff',
      user_bubble_text: '#0969da',
      send_bg: '#0969da',
      send_fg: '#ffffff',
      sprinkles: false,
    },
  },
  {
    id: 'winamp_1999',
    name: 'Winamp Classic 1999 (2.x LED Palette)',
    author: 'bm069au',
    origin: 'Built-in',
    theme: {
      id: 'winamp_1999',
      name: 'Winamp Classic 1999 (2.x LED)',
      bg_main: '#121612',
      bg_sidebar: '#0a0d0a',
      bg_card: '#1b241b',
      bg_hover: '#253325',
      border: '#375237',
      text_primary: '#00ff41',
      text_secondary: '#b8e6b8',
      text_muted: '#6b9e6b',
      user_bubble_bg: '#1e2e1e',
      user_bubble_border: '#ffb000',
      user_bubble_text: '#ffdf80',
      send_bg: '#ffb000',
      send_fg: '#0a0d0a',
      sprinkles: false,
    },
  },
  {
    id: 'cyberpunk_2077',
    name: 'Cyberpunk Night City',
    author: 'bm069au',
    origin: 'Built-in',
    theme: {
      id: 'cyberpunk_2077',
      name: 'Cyberpunk Night City',
      bg_main: '#0b0c14',
      bg_sidebar: '#07080d',
      bg_card: '#141726',
      bg_hover: '#1e2238',
      border: '#00f0ff',
      text_primary: '#fcee0a',
      text_secondary: '#e0f7fa',
      text_muted: '#00b8d4',
      user_bubble_bg: '#290924',
      user_bubble_border: '#ff0055',
      user_bubble_text: '#ffffff',
      send_bg: '#ff0055',
      send_fg: '#ffffff',
      sprinkles: false,
    },
  },
  {
    id: 'matrix_crt',
    name: 'Matrix Phosphor (CRT Terminal)',
    author: 'bm069au',
    origin: 'Built-in',
    theme: {
      id: 'matrix_crt',
      name: 'Matrix Phosphor (CRT Terminal)',
      bg_main: '#050805',
      bg_sidebar: '#020402',
      bg_card: '#0b140b',
      bg_hover: '#122112',
      border: '#194d19',
      text_primary: '#39ff14',
      text_secondary: '#76ff7a',
      text_muted: '#2e8b57',
      user_bubble_bg: '#0d1f0d',
      user_bubble_border: '#39ff14',
      user_bubble_text: '#ccffcc',
      send_bg: '#39ff14',
      send_fg: '#020402',
      sprinkles: false,
    },
  },
  {
    id: 'dracula_pro',
    name: 'Dracula Pro',
    author: 'bm069au',
    origin: 'Built-in',
    theme: {
      id: 'dracula_pro',
      name: 'Dracula Pro',
      bg_main: '#282a36',
      bg_sidebar: '#1e1f29',
      bg_card: '#343746',
      bg_hover: '#44475a',
      border: '#6272a4',
      text_primary: '#f8f8f2',
      text_secondary: '#e2e2dc',
      text_muted: '#9ea8c7',
      user_bubble_bg: '#3b2d4a',
      user_bubble_border: '#bd93f9',
      user_bubble_text: '#f8f8f2',
      send_bg: '#ff79c6',
      send_fg: '#1e1f29',
      sprinkles: false,
    },
  },
  {
    id: 'nord_frost',
    name: 'Nord Frost (Arctic Slate & Cyan)',
    author: 'Fairybread Studio',
    origin: 'Preset',
    theme: {
      id: 'nord_frost',
      name: 'Nord Frost (Arctic Slate & Cyan)',
      bg_main: '#2e3440',
      bg_sidebar: '#242933',
      bg_card: '#3b4252',
      bg_hover: '#434c5e',
      border: '#4c566a',
      text_primary: '#eceff4',
      text_secondary: '#d8dee9',
      text_muted: '#8fbcbb',
      user_bubble_bg: '#2b3b4e',
      user_bubble_border: '#88c0d0',
      user_bubble_text: '#eceff4',
      send_bg: '#88c0d0',
      send_fg: '#1f242d',
      sprinkles: false,
    },
  },
  {
    id: 'amber_crt_1984',
    name: 'Amber CRT 1984 (Monochrome Terminal)',
    author: 'Fairybread Studio',
    origin: 'Preset',
    theme: {
      id: 'amber_crt_1984',
      name: 'Amber CRT 1984 (Monochrome Terminal)',
      bg_main: '#120d05',
      bg_sidebar: '#0a0702',
      bg_card: '#1b1307',
      bg_hover: '#291d0b',
      border: '#593d12',
      text_primary: '#ffb000',
      text_secondary: '#ffd27a',
      text_muted: '#b37b16',
      user_bubble_bg: '#241908',
      user_bubble_border: '#ff9900',
      user_bubble_text: '#ffe6ad',
      send_bg: '#ffb000',
      send_fg: '#0a0702',
      sprinkles: false,
    },
  },
  {
    id: 'tokyo_night',
    name: 'Tokyo Night (Deep Indigo & Electric Blue)',
    author: 'Fairybread Studio',
    origin: 'Preset',
    theme: {
      id: 'tokyo_night',
      name: 'Tokyo Night (Deep Indigo & Electric Blue)',
      bg_main: '#1a1b26',
      bg_sidebar: '#13141c',
      bg_card: '#24283b',
      bg_hover: '#2f3549',
      border: '#414868',
      text_primary: '#c0caf5',
      text_secondary: '#a9b1d6',
      text_muted: '#737aa2',
      user_bubble_bg: '#232946',
      user_bubble_border: '#7aa2f7',
      user_bubble_text: '#e0e7ff',
      send_bg: '#7aa2f7',
      send_fg: '#13141c',
      sprinkles: false,
    },
  },
  {
    id: 'catppuccin_mocha',
    name: 'Catppuccin Mocha (Warm Espresso & Mauve)',
    author: 'Fairybread Studio',
    origin: 'Preset',
    theme: {
      id: 'catppuccin_mocha',
      name: 'Catppuccin Mocha (Warm Espresso & Mauve)',
      bg_main: '#1e1e2e',
      bg_sidebar: '#181825',
      bg_card: '#2a2b3d',
      bg_hover: '#313244',
      border: '#45475a',
      text_primary: '#cdd6f4',
      text_secondary: '#bac2de',
      text_muted: '#9399b2',
      user_bubble_bg: '#322b47',
      user_bubble_border: '#cba6f7',
      user_bubble_text: '#f5e0dc',
      send_bg: '#cba6f7',
      send_fg: '#11111b',
      sprinkles: false,
    },
  },
  {
    id: 'gruvbox_studio',
    name: 'Gruvbox Warm Studio (Earthy Ochre & Cream)',
    author: 'Fairybread Studio',
    origin: 'Preset',
    theme: {
      id: 'gruvbox_studio',
      name: 'Gruvbox Warm Studio (Earthy Ochre & Cream)',
      bg_main: '#1d2021',
      bg_sidebar: '#17191a',
      bg_card: '#282828',
      bg_hover: '#3c3836',
      border: '#504945',
      text_primary: '#ebdbb2',
      text_secondary: '#d5c4a1',
      text_muted: '#a89984',
      user_bubble_bg: '#332b20',
      user_bubble_border: '#fabd2f',
      user_bubble_text: '#fbf1c7',
      send_bg: '#fe8019',
      send_fg: '#1d2021',
      sprinkles: false,
    },
  },
  {
    id: 'emerald_blueprint',
    name: 'Emerald CAD Blueprint (Technical Navy & Teal)',
    author: 'Fairybread Studio',
    origin: 'Preset',
    theme: {
      id: 'emerald_blueprint',
      name: 'Emerald CAD Blueprint (Technical Navy & Teal)',
      bg_main: '#09151c',
      bg_sidebar: '#060e13',
      bg_card: '#0f222d',
      bg_hover: '#163140',
      border: '#1e4e5f',
      text_primary: '#d8f8f2',
      text_secondary: '#a8ded5',
      text_muted: '#589b99',
      user_bubble_bg: '#0d2b36',
      user_bubble_border: '#14b8a6',
      user_bubble_text: '#ecfeff',
      send_bg: '#14b8a6',
      send_fg: '#041216',
      sprinkles: false,
    },
  },
  {
    id: 'outrun_synthwave',
    name: "Outrun Synthwave '84",
    author: 'Fairybread Studio',
    origin: 'Preset',
    theme: {
      id: 'outrun_synthwave',
      name: "Outrun Synthwave '84",
      bg_main: '#191124',
      bg_sidebar: '#110b1a',
      bg_card: '#241836',
      bg_hover: '#32214a',
      border: '#ff2a85',
      text_primary: '#fff5f8',
      text_secondary: '#f3d1e4',
      text_muted: '#b388eb',
      user_bubble_bg: '#2c1642',
      user_bubble_border: '#00f5d4',
      user_bubble_text: '#ffffff',
      send_bg: '#00f5d4',
      send_fg: '#110b1a',
      sprinkles: true,
    },
  },
  {
    id: 'obsidian_gold',
    name: 'Obsidian Gold (Luxury Matte & Champagne)',
    author: 'bm069au',
    origin: 'Preset',
    theme: {
      id: 'obsidian_gold',
      name: 'Obsidian Gold',
      bg_main: '#0c0c0e',
      bg_sidebar: '#070708',
      bg_card: '#16161a',
      bg_hover: '#202026',
      border: '#4a3f28',
      text_primary: '#f5ebd6',
      text_secondary: '#d4c5a9',
      text_muted: '#8c7d62',
      user_bubble_bg: '#1f1b12',
      user_bubble_border: '#d4af37',
      user_bubble_text: '#fff8e7',
      send_bg: '#d4af37',
      send_fg: '#0c0c0e',
      sprinkles: false,
    },
  },
];

const DEFAULT_DONORS = [
  {
    name: 'Brett Martin Moore (Creator)',
    tier: '👑 Founder & Architect',
    note: 'Built Fairybread to end corporate AI subscription lock-in and keep memory 100% local.',
  },
  {
    name: 'Join the Fairybread Supporters',
    tier: '❤️ GitHub Sponsors',
    note: 'Sponsor $5+ USD via GitHub Sponsors to support ongoing development and appear on the Donor Wall.',
  },
];

const CODE_EXCERPTS = {
  'LICENSE.md': `# Fairybread Proprietary Source-Available & Commercial Threshold License
Copyright © 2026 Brett Martin Moore (bm069au@gmail.com). All Rights Reserved.

IMPORTANT NOTICE — THIS SOFTWARE IS PROPRIETARY SOURCE-AVAILABLE (NOT "OPEN SOURCE"):
Making the source code visible for security auditing, personal transparency,
and community contributions does NOT grant an Open Source license.

1. Personal & Small-Team Use (Up to 2 Seats): Free Donationware.
2. Strict Prohibitions: No public forks, no redistribution, no rebranding or competing SaaS.
3. Corporate & Enterprise Use (> 2 Seats): Commercial license required (bm069au@gmail.com).`,

  'memory_service.py (100% Local Memory + $0.00 Recall)': `# Zero Cloud Lock-In: All memories are indexed locally in %LOCALAPPDATA%\\Palace\\memory.db
# using SQLite FTS5 BM25 ranking + zlib compression + Living Memory Summary.

def find_high_confidence_local_recall(prompt: str, db_path: Path | None = None) -> dict[str, Any]:
    """Check local SQLite memory for strong matches first so free-tier agents can recall
    previously stored knowledge for $0.00 instead of repeating paid web searches."""`,

  'setup_wizard.py (Guided Wizard & Spend Dashboard)': `# Walks beginners and experienced users through choosing a workflow profile,
# optionally routing seats through OpenRouter with one key, restoring backups selectively,
# and inspecting cumulative/resettable spend tickers per provider, image, and Voice Mode.

def recommend_setup_plan(answers: dict[str, Any]) -> dict[str, Any]:
    """Recommend provider keys, OpenRouter hub tier, and Deepgram Flux voice based on goals."""`,

  'cost_service.py (3-Layer Spend Ledger & OpenRouter Exact Cost)': `# Records explicit API usage.cost alongside estimated token, image, and Deepgram Flux
# voice/STT seconds into per-conversation totals and %LOCALAPPDATA%\\Palace\\billing_ledger.json.

class GlobalBillingLedger:
    """Cumulative + resettable per-provider/image/voice spend ledger with explicit reset timestamps."""`,

  'voice_service.py (Deepgram Flux + 89 Voices & Live Mic Meter)': `# Streams 16 kHz mono PCM from QAudioSource, drives the live volume meter,
# and supports Deepgram Flux, Cartesia, OpenAI, and Gemini voice engines with live spend tracking.

class LiveAudioSession(QObject):
    level_changed = Signal(float)          # 0.0 .. 1.0 real-time soundwave meter
    utterance_ready = Signal(str)          # WAV path emitted on speech pause`,

  'palace_theme.py (Safe .JSON Color Theme Engine)': `# Themes are pure 13-token JSON color palettes stored in %LOCALAPPDATA%\\Palace\\themes\\*.json
# Zero executable code is ever evaluated when loading a custom color theme.

def load_theme_dict(theme_id: str = "dark") -> dict[str, Any]:
    """Load built-in or user-imported JSON hex tokens and apply cleanly to the Qt stylesheet."""`,
};

function loadState(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (_) {
    return fallback;
  }
}

function saveState(key, val) {
  try {
    localStorage.setItem(key, JSON.stringify(val));
  } catch (_) {}
}

function clearLegacyWebsiteCaches() {
  try {
    LEGACY_KEYS_TO_CLEAR.forEach((k) => localStorage.removeItem(k));
  } catch (_) {}
}

function switchTab(tabId) {
  document.querySelectorAll('.tab-section').forEach((sec) => {
    sec.classList.toggle('active', sec.id === `tab-${tabId}`);
  });
  document.querySelectorAll('.nav-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ================= NEWS =================
function renderNews() {
  const container = document.getElementById('newsFeedContainer');
  if (!container) return;
  container.innerHTML = DEFAULT_NEWS.map(
    (p) => `
    <article class="news-card">
      <div class="news-meta">
        <span class="news-tag">${escapeHtml(p.tag)}</span>
        <span>📅 ${escapeHtml(p.date)}</span>
        <span>✍️ ${escapeHtml(p.author)}</span>
      </div>
      <h3>${escapeHtml(p.title)}</h3>
      <p style="white-space: pre-line; color: var(--text-secondary); margin: 8px 0 0;">${escapeHtml(p.body)}</p>
    </article>
  `
  ).join('');
}

// ================= CUSTOM COLOR THEME STUDIO & GALLERY =================
function getAllSkins() {
  const custom = loadState(STORAGE_KEYS.userSkins, []);
  const validCustom = Array.isArray(custom) ? custom.filter((s) => s && s.theme) : [];
  return [...validCustom, ...DEFAULT_SKINS];
}

function getStudioThemeObject() {
  const rawName = document.getElementById('skinNameInput')?.value.trim() || 'Custom Theme';
  const slug = rawName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'custom_theme';
  return {
    id: slug,
    name: rawName,
    bg_main: document.getElementById('colBgMain').value,
    bg_sidebar: document.getElementById('colBgSidebar').value,
    bg_card: document.getElementById('colBgCard').value,
    bg_hover: document.getElementById('colBgHover').value,
    border: document.getElementById('colBorder').value,
    text_primary: document.getElementById('colTextPrimary').value,
    text_secondary: document.getElementById('colTextSec').value,
    text_muted: document.getElementById('colTextMuted').value,
    user_bubble_bg: document.getElementById('colUserBg').value,
    user_bubble_border: document.getElementById('colUserBorder').value,
    user_bubble_text: document.getElementById('colUserText')?.value || document.getElementById('colTextPrimary').value,
    send_bg: document.getElementById('colSendBg').value,
    send_fg: document.getElementById('colSendFg').value,
    sprinkles: Boolean(document.getElementById('colSprinkles')?.checked),
  };
}

function updateLiveThemePreview() {
  const win = document.getElementById('liveThemePreviewWindow');
  if (!win) return;
  const t = getStudioThemeObject();
  win.style.background = t.bg_main;
  win.style.color = t.text_primary;
  win.style.borderColor = t.border;

  const menubar = document.getElementById('tpMenubar');
  menubar.style.background = t.bg_main;
  menubar.style.color = t.text_secondary;
  menubar.style.borderBottomColor = t.border;

  const sidebar = document.getElementById('tpSidebar');
  sidebar.style.background = t.bg_sidebar;
  sidebar.style.color = t.text_secondary;
  sidebar.style.borderRightColor = t.border;

  const newBtn = document.getElementById('tpNewBtn');
  newBtn.style.background = t.bg_card;
  newBtn.style.color = t.text_primary;
  newBtn.style.border = `1px solid ${t.border}`;

  const activeItem = document.getElementById('tpActiveItem');
  activeItem.style.background = t.bg_card;
  activeItem.style.color = t.text_primary;

  const topbar = document.getElementById('tpTopbar');
  topbar.style.borderBottomColor = t.border;
  document.getElementById('tpBreadcrumb').style.color = t.text_primary;

  const userBubble = document.getElementById('tpUserBubble');
  userBubble.style.background = t.user_bubble_bg;
  userBubble.style.color = t.user_bubble_text;
  userBubble.style.border = t.sprinkles ? '2px dashed #ec4899' : `1px solid ${t.user_bubble_border}`;

  const aiCard = document.getElementById('tpAiCard');
  aiCard.style.background = t.bg_card;
  aiCard.style.border = `1px solid ${t.border}`;
  document.getElementById('tpAiText').style.color = t.text_secondary;

  const composer = document.getElementById('tpComposer');
  composer.style.background = t.bg_card;
  composer.style.border = `1px solid ${t.border}`;
  document.getElementById('tpComposerPlaceholder').style.color = t.text_muted;

  const sendBtn = document.getElementById('tpSendBtn');
  sendBtn.style.background = t.send_bg;
  sendBtn.style.color = t.send_fg;
}

function loadSkinIntoStudio(skinId) {
  const found = getAllSkins().find((s) => s.id === skinId);
  if (!found) return;
  const t = found.theme;
  document.getElementById('skinNameInput').value = t.name;
  document.getElementById('skinAuthorInput').value = found.author || 'bm069au';
  document.getElementById('colBgMain').value = t.bg_main;
  document.getElementById('colBgSidebar').value = t.bg_sidebar;
  document.getElementById('colBgCard').value = t.bg_card;
  document.getElementById('colBgHover').value = t.bg_hover;
  document.getElementById('colBorder').value = t.border;
  document.getElementById('colTextPrimary').value = t.text_primary;
  document.getElementById('colTextSec').value = t.text_secondary;
  document.getElementById('colTextMuted').value = t.text_muted;
  document.getElementById('colUserBg').value = t.user_bubble_bg;
  document.getElementById('colUserBorder').value = t.user_bubble_border;
  if (document.getElementById('colUserText')) {
    document.getElementById('colUserText').value = t.user_bubble_text || t.text_primary;
  }
  document.getElementById('colSendBg').value = t.send_bg;
  document.getElementById('colSendFg').value = t.send_fg;
  document.getElementById('colSprinkles').checked = Boolean(t.sprinkles);
  updateLiveThemePreview();
}

function downloadThemeObjectAsJson(themeObj) {
  const jsonStr = JSON.stringify(themeObj, null, 2) + '\n';
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${themeObj.id || 'custom_theme'}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function downloadCurrentSkinJson() {
  downloadThemeObjectAsJson(getStudioThemeObject());
}

function copyCurrentSkinJson() {
  const jsonStr = JSON.stringify(getStudioThemeObject(), null, 2);
  navigator.clipboard.writeText(jsonStr);
  alert('Copied theme JSON to clipboard!');
}

function publishCurrentSkinToGallery() {
  const t = getStudioThemeObject();
  const author = document.getElementById('skinAuthorInput')?.value.trim() || 'Community';
  const custom = loadState(STORAGE_KEYS.userSkins, []);
  const list = Array.isArray(custom) ? custom : [];
  list.unshift({
    id: `${t.id}_${Date.now().toString().slice(-4)}`,
    name: t.name,
    author,
    origin: 'Custom',
    theme: t,
  });
  saveState(STORAGE_KEYS.userSkins, list);
  renderSkinGallery();
}

function downloadGallerySkin(skinId) {
  const found = getAllSkins().find((s) => s.id === skinId);
  if (!found) return;
  downloadThemeObjectAsJson(found.theme);
}

function renderSkinGallery() {
  const grid = document.getElementById('skinGalleryGrid');
  if (!grid) return;
  const skins = getAllSkins();
  grid.innerHTML = skins
    .map((s) => {
      const t = s.theme;
      const originLabel = s.origin || 'Preset';
      const originCls = originLabel === 'Built-in' ? 'skin-origin-badge builtin' : 'skin-origin-badge';
      return `
      <div class="skin-card">
        <div class="skin-swatches">
          <span style="background:${t.bg_main}" title="Main BG"></span>
          <span style="background:${t.bg_sidebar}" title="Sidebar"></span>
          <span style="background:${t.bg_card}" title="Card"></span>
          <span style="background:${t.text_primary}" title="Text"></span>
          <span style="background:${t.send_bg}" title="Accent"></span>
        </div>
        <div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
            <strong>${escapeHtml(s.name)}</strong>
            <span class="${originCls}">${escapeHtml(originLabel)}</span>
          </div>
          <div class="muted-sub">by ${escapeHtml(s.author)} ${t.sprinkles ? '· ✨ Sprinkles' : ''}</div>
        </div>
        <div class="studio-btn-row" style="margin-top:auto;">
          <button class="btn-outline" style="padding:5px 10px; font-size:12px;" onclick="loadSkinIntoStudio('${escapeHtml(s.id)}')">👁 Preview in Studio</button>
          <button class="btn-primary" style="padding:5px 10px; font-size:12px;" onclick="downloadGallerySkin('${escapeHtml(s.id)}')">⬇ Download .json</button>
        </div>
      </div>
    `;
    })
    .join('');
}

// ================= DONOR WALL =================
function renderDonorWall() {
  const grid = document.getElementById('donorWallGrid');
  if (!grid) return;
  grid.innerHTML = DEFAULT_DONORS.map(
    (d) => `
    <div class="donor-card">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:6px;">
        <strong>${escapeHtml(d.name)}</strong>
        <span class="badge-donor">${escapeHtml(d.tier)}</span>
      </div>
      <p class="muted-sub">${escapeHtml(d.note)}</p>
    </div>
  `
  ).join('');
}

// ================= READ-ONLY CODE VIEWER =================
function renderCodeExplorer() {
  const listEl = document.getElementById('codeFileList');
  if (!listEl) return;
  const files = Object.keys(CODE_EXCERPTS);
  listEl.innerHTML = files
    .map(
      (fname, idx) => `
    <button class="code-file-btn ${idx === 0 ? 'active' : ''}" onclick="selectCodeFile('${escapeHtml(fname)}', this)">
      📄 ${escapeHtml(fname)}
    </button>
  `
    )
    .join('');
  selectCodeFile(files[0]);
}

function selectCodeFile(fname, btnEl) {
  if (btnEl) {
    document.querySelectorAll('.code-file-btn').forEach((b) => b.classList.remove('active'));
    btnEl.classList.add('active');
  }
  const titleEl = document.getElementById('codeViewerTitle');
  const preEl = document.getElementById('codeViewerContent');
  if (titleEl) titleEl.textContent = fname;
  if (preEl) preEl.textContent = CODE_EXCERPTS[fname] || '';
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function compareVersionTags(a, b) {
  function _parse(v) {
    const m = String(v || '').trim().match(/^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?([a-z]*)$/i);
    if (!m) return [0, 0, 0, String(v || '').toLowerCase()];
    return [
      parseInt(m[1] || '0', 10),
      parseInt(m[2] || '0', 10),
      parseInt(m[3] || '0', 10),
      String(m[4] || '').toLowerCase(),
    ];
  }
  const ta = _parse(a);
  const tb = _parse(b);
  for (let i = 0; i < 3; i++) {
    if (ta[i] !== tb[i]) return ta[i] < tb[i] ? -1 : 1;
  }
  if (ta[3] === tb[3]) return 0;
  return ta[3] < tb[3] ? -1 : 1;
}

// ================= DYNAMIC GITHUB RELEASE AUTO-UPDATER =================
async function autoUpdateLatestRelease() {
  try {
    const res = await fetch('https://api.github.com/repos/bm069au/fairybread/releases/latest');
    if (!res.ok) return;
    const release = await res.json();
    if (!release || !release.tag_name) return;

    const rawTag = release.tag_name;
    const cleanTag = rawTag.replace(/-beta$/i, '');

    // Never downgrade if fetched release tag is older than the currently published baseline
    const currentSiteVersion = 'v0.93';
    if (compareVersionTags(cleanTag, currentSiteVersion) < 0) {
      return;
    }

    const assets = release.assets || [];
    const installerAsset =
      assets.find((a) => {
        const n = a.name.toLowerCase();
        return !n.includes('developer') && n.endsWith('.exe') && n.includes('setup');
      }) ||
      assets.find((a) => {
        const n = a.name.toLowerCase();
        return !n.includes('developer') && n.endsWith('.zip') && (n.includes('setup') || n.includes('installer') || n.includes('win'));
      }) ||
      assets.find((a) => {
        const n = a.name.toLowerCase();
        return n.endsWith('.exe') || n.endsWith('.zip');
      }) ||
      assets[0];

    const downloadUrl = installerAsset
      ? installerAsset.browser_download_url
      : `https://github.com/bm069au/fairybread/releases/tag/${rawTag}`;

    const isBetaTag = /-beta$/i.test(rawTag);
    const labelVersion = isBetaTag ? `BETA ${cleanTag}` : cleanTag;

    document.querySelectorAll('.brand-tag.dynamic-version-tag').forEach((el) => {
      el.textContent = labelVersion;
    });

    document.querySelectorAll('.dynamic-download-btn').forEach((btn) => {
      btn.href = downloadUrl;
      if (btn.id === 'heroDownloadBtn') {
        btn.innerHTML = `⬇ Download Fairybread ${escapeHtml(cleanTag)} (Win_x64)`;
      }
    });
  } catch (err) {
    console.debug('[Fairybread] Release auto-resolve fallback:', err);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  clearLegacyWebsiteCaches();
  autoUpdateLatestRelease();
  renderNews();
  updateLiveThemePreview();
  renderSkinGallery();
  renderDonorWall();
  renderCodeExplorer();
});
