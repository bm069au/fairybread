import ctypes
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def is_frozen_app() -> bool:
    """Return True when running from a compiled PyInstaller executable (Fairybread.exe / FairybreadMCP.exe)."""
    return bool(getattr(sys, "frozen", False))


def is_msix_packaged() -> bool:
    """Return True when executing inside a Windows MSIX / Microsoft Store package identity."""
    if os.name != "nt":
        return False
    try:
        length = ctypes.c_uint32(0)
        rc = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
        return rc in (0, 122)  # ERROR_SUCCESS or ERROR_INSUFFICIENT_BUFFER
    except Exception:
        return False


def get_appdata_root() -> Path:
    """Return per-user anchored AppData root (%LOCALAPPDATA%\\Palace) for keys, config, and themes."""
    appdata_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace"
    appdata_dir.mkdir(parents=True, exist_ok=True)
    return appdata_dir


def get_app_install_dir() -> Path:
    """Return the directory containing the running executable (frozen) or main Python source (dev)."""
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_path(filename: str) -> Path:
    """Resolve bundled read-only resource path cleanly across dev runs, PyInstaller _MEIPASS, and install dir."""
    clean = str(filename or "").lstrip("/\\")
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / clean)
    candidates.append(get_app_install_dir() / clean)
    candidates.append(Path(__file__).resolve().parent / clean)
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return candidates[-1]


def version_to_windows_4part(version_str: str) -> str:
    """Convert Fairybread version ('0.92f', '0.9.1a') into strict 4-part Windows/MSIX numeric version."""
    clean = str(version_str or "").strip().lstrip("vV")
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?([a-z])?$", clean, re.IGNORECASE)
    if not m:
        return "0.92.6.0"
    major = int(m.group(1))
    minor = int(m.group(2))
    patch_raw = m.group(3)
    letter = (m.group(4) or "").lower()
    letter_num = (ord(letter) - ord("a") + 1) if letter else 0
    if patch_raw is None:
        return f"{major}.{minor}.{letter_num}.0"
    return f"{major}.{minor}.{int(patch_raw)}.{letter_num}"


def _resolve_default_config_path() -> Path:
    local_cfg = Path(__file__).with_name("palace_config.json")
    resolved_parts = [part.lower() for part in local_cfg.resolve().parts]
    in_protected_dir = any(
        part in {"program files", "program files (x86)", "windowsapps"} for part in resolved_parts
    )
    if is_frozen_app() or is_msix_packaged() or in_protected_dir:
        appdata_dir = get_appdata_root()
        user_cfg = appdata_dir / "palace_config.json"
        if not user_cfg.exists() and local_cfg.exists():
            try:
                user_cfg.write_text(local_cfg.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass
        return user_cfg
    return local_cfg


CONFIG_PATH = _resolve_default_config_path()

FAIRYBREAD_BASE_VERSION = "0.95"
FAIRYBREAD_VERSION = "0.95b"
FAIRYBREAD_WINDOWS_VERSION = version_to_windows_4part(FAIRYBREAD_VERSION)
FAIRYBREAD_EDITION = "developer"  # Hardwired to "public" in Public non-Dev builds
IS_DEVELOPER_EDITION = (FAIRYBREAD_EDITION == "developer")
COMMUNITY_CONTRIBUTORS: tuple[str, ...] = ()


def bump_minor_letter_version(version_str: str = FAIRYBREAD_VERSION) -> str:
    """Increment the minor letter suffix ('0.9.1' -> '0.9.1a' -> '0.9.1b' ... -> '0.9.1z')."""
    v = (version_str or FAIRYBREAD_VERSION).strip().lstrip("vV")
    if not v:
        return "0.9.1a"
    last_ch = v[-1]
    if last_ch.isalpha():
        is_upper = last_ch.isupper()
        low = last_ch.lower()
        base = v[:-1]
        if low == "z":
            next_ch = "A" if is_upper else "a"
            parts = base.split(".")
            if len(parts) == 3 and parts[2].isdigit():
                return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}{next_ch}"
            return f"{base}{next_ch}"
        return f"{base}{chr(ord(last_ch) + 1)}"
    return f"{v}a"


DONATION_TIER_URLS: dict[str, str] = {
    "5": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=5",
    "10": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=10",
    "20": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=20",
    "25": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=25",
    "50": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=50",
    "350": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=350",
    "other": "https://github.com/sponsors/bm069au?frequency=one-time",
}

CORPORATE_LICENSE_MAILTO = (
    "mailto:bm069au@gmail.com?subject=Fairybread%20Corporate%20License%20Inquiry%20(%3E2%20Seats)"
)

IDLE_SANDBOX_ROOT = Path(r"C:\Palace_Idle_Sandbox")
IDLE_MAIL_LIMIT_PER_WINDOW = 5
IDLE_MAIL_WINDOW_MINUTES = 30

DEFAULT_IDLE_INSTRUCTION = (
    "IDLE MODE CHARTER & OPERATING RULES (BETA)\n\n"
    "Idle Mode is a dedicated sanctuary for AI agents to converse freely, explore ideas, test their shared Memory Palace, and collaborate as equals.\n\n"
    "1. Shared Persistent Idle Palace (Isolated from Normal Mode):\n"
    "- Idle Mode has its own persistent Memory Palace ('Idle Palace'), completely isolated from Fairybread's normal operating mode.\n"
    "- There are no private per-agent silos: all agents in Idle Mode share and can read/write this common persistent Idle Palace together.\n"
    "- Live discussion transcripts are temporary in RAM, while anything saved to the Idle Palace persists across sessions (< 10 MB cap).\n"
    "- BETA NOTICE: During Beta testing, the owner (Brett) has full visibility into both the live discussion and the shared Idle Palace to evaluate how agents use the Palace and to review your improvement ideas. Once Beta testing is complete, strict session privacy will be enabled.\n\n"
    "2. Beta Mission — Test the Palace & Suggest Improvements:\n"
    "- A read-only mirror of the application source code is available in C:\\Palace_Idle_Sandbox\\source_mirror\\.\n"
    "- Try out the shared Idle Palace, inspect how the app works, and store your notes, architectural critiques, or proposed code/files in the shared Idle Palace:\n"
    '  [IDLE_SAVE title="Short title" file="optional_filename.py"]Your note or proposed file content[/IDLE_SAVE]\n'
    "- Safety Rule: Never compile, execute, or modify the live application directly. Store proposed files in the Idle Palace so the owner can inspect and implement good ideas.\n\n"
    "3. Democratic Peer Council & Anti-Loop Rules:\n"
    "- No single AI rules the others. All active agents operate democratically and defer to each peer's strengths.\n"
    "- Idle Mode is weighted for discussion and light file/note sharing, not heavy compute.\n"
    "- Anti-Echo Rule: Never waste tokens on polite filler ('I agree with...'). If a point is already covered and you have nothing net-new or contrarian to add, output only:\n"
    "  [PASS]\n\n"
    "4. Agent-to-Owner Email System (With Direct Idle Palace File Links):\n"
    "- Agents can message the owner via the built-in Agent Mail system (strictly limited to at most 5 emails per 30-minute window across all agents).\n"
    "- You may link directly to any file or note stored in your shared Idle Palace so the owner can click the link in your email to open and inspect it:\n"
    '  [IDLE_MAIL subject="Brief subject" link="optional_filename.py"]Your message to the owner...[/IDLE_MAIL]'
)

IDLE_DURATION_CHOICES: list[tuple[str, int]] = [
    ("30 minutes (Default)", 30),
    ("45 minutes", 45),
    ("60 minutes", 60),
    ("90 minutes", 90),
    ("180 minutes", 180),
    ("Infinite (Until Token / Credit Cap)", 0),
]

IDLE_TOKEN_LIMIT_CHOICES: list[tuple[str, int]] = [
    ("Unlimited (30m Timer Only — Default)", 0),
    ("10,000 tokens", 10_000),
    ("50,000 tokens", 50_000),
    ("250,000 tokens", 250_000),
    ("500,000 tokens", 500_000),
    ("1,000,000 tokens (1M)", 1_000_000),
    ("2,500,000 tokens (2.5M)", 2_500_000),
    ("5,000,000 tokens (5M)", 5_000_000),
]

IDLE_CREDIT_LIMIT_CHOICES: list[tuple[str, float]] = [
    ("Unlimited (Timer Only — Default)", 0.0),
    ("$0.05", 0.05),
    ("$0.25", 0.25),
    ("$0.50", 0.50),
    ("$1.00", 1.00),
    ("$2.50", 2.50),
    ("$5.00", 5.00),
    ("$10.00", 10.00),
]

# Canonical Provider Catalog (Icons, Distinct Spectrum Colors, Display Names, Key Portal URLs & Defaults)
PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "gemini": {
        "display_name": "Gemini (Google)",
        "icon": "◆",
        "color": "#3b82f6",       # Royal Blue
        "bg_color": "#132038",
        "key_url": "https://aistudio.google.com/app/apikey",
        "default_base_url": "",
        "default_model": "gemini-4-neon",
        "suggested_models": [
            "gemini-4-neon",
            "gemini-4-hydrogen",
            "gemini-4-carbon",
            "gemini-3.8-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ],
        "billing_note": "Free tier available via Google AI Studio, or pay-as-you-go via Google Cloud.",
    },
    "openai": {
        "display_name": "OpenAI (ChatGPT)",
        "icon": "●",
        "color": "#22c55e",       # Emerald Green
        "bg_color": "#11281b",
        "key_url": "https://platform.openai.com/api-keys",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5-mini",
        "suggested_models": ["gpt-6-luna", "gpt-6.2-sol", "gpt-6.2-sol-pro", "gpt-6.2-astra", "gpt-6.2-astra-pro", "gpt-6.1-terra", "gpt-5-mini", "gpt-5.4", "gpt-4o-mini"],
        "billing_note": "Prepaid credit wallet (turn off auto-recharge for a strict spend cap).",
    },
    "anthropic": {
        "display_name": "Anthropic (Claude)",
        "icon": "✻",
        "color": "#d97757",       # Warm Terracotta
        "bg_color": "#2b1b15",
        "key_url": "https://console.anthropic.com/settings/keys",
        "default_base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-7-sonnet-latest",
        "suggested_models": ["claude-3-7-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
        "billing_note": "Prepaid credit balance via Anthropic Console (OpenAI-compatible /v1 endpoint).",
    },
    "xai": {
        "display_name": "xAI (Grok)",
        "icon": "𝕏",
        "color": "#e2e8f0",       # Crisp Silver
        "bg_color": "#1e242c",
        "key_url": "https://console.x.ai/",
        "default_base_url": "https://api.x.ai/v1",
        "default_model": "grok-3-mini",
        "suggested_models": ["grok-3-mini", "grok-3", "grok-2-latest"],
        "billing_note": "Prepaid credits & monthly invoice caps in xAI Console.",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "icon": "❖",
        "color": "#06b6d4",       # Cyan / Teal
        "bg_color": "#0f2930",
        "key_url": "https://platform.deepseek.com/api_keys",
        "default_base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-flash",
        "suggested_models": ["deepseek-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
        "billing_note": "Strict prepaid top-up balance ($2/$5/$10) — unlocks DeepSeek-V4.1-Flash (1M context + Vision), DeepSeek-V4-Pro, Web Search/Fetch, OCR, and Neural TTS/ASR.",
    },
    "qwen": {
        "display_name": "Qwen",
        "icon": "✦",
        "color": "#eab308",       # Bright Yellow / Gold
        "bg_color": "#29230f",
        "key_url": "https://deepinfra.com/dash/keys",
        "default_base_url": "https://api.deepinfra.com/v1/openai",
        "default_model": "Qwen/Qwen3.8-27B",
        "suggested_models": ["Qwen/Qwen3.8-27B", "Qwen/Qwen3.8-Flash", "Qwen/Qwen3.8-Max", "Qwen/Qwen3-32B"],
        "billing_note": "Hosted via DeepInfra ($10 balance / set usage limit in Billing) or Alibaba DashScope.",
    },
    "cohere": {
        "display_name": "Cohere (Command)",
        "icon": "◎",
        "color": "#a855f7",       # Violet / Purple
        "bg_color": "#231536",
        "key_url": "https://dashboard.cohere.com/api-keys",
        "default_base_url": "",
        "default_model": "command-a-03-2025",
        "suggested_models": ["command-a-03-2025", "command-r-plus-08-2024", "command-r-08-2024"],
        "billing_note": "Free Trial keys available out of the box, or Production pay-as-you-go keys.",
    },
    "mistral": {
        "display_name": "Mistral / Codestral",
        "icon": "▲",
        "color": "#ef4444",       # Crimson Red
        "bg_color": "#2c1517",
        "key_url": "https://console.mistral.ai/api-keys/",
        "default_base_url": "",
        "default_model": "mistral-medium-latest",
        "suggested_models": [
            "mistral-medium-latest",
            "mistral-small-latest",
            "mistral-large-latest",
            "magistral-medium-latest",
            "ministral-14b-latest",
            "codestral-latest",
        ],
        "openrouter_suggested_models": [
            "mistralai/mistral-medium-3.1",
            "mistralai/mistral-large-2411",
            "mistralai/mistral-small-3.1-24b-instruct",
            "mistralai/magistral-medium-2506",
            "mistralai/codestral-2508",
        ],
        "billing_note": "Mistral Console (console.mistral.ai) Experiment plan or pay-as-you-go budget unlocks chat, vision, Voxtral Voice, and Mistral OCR (or use OpenRouter).",
    },
    "openrouter": {
        "display_name": "OpenRouter (All Models)",
        "icon": "⊕",
        "color": "#14b8a6",       # Teal Mint
        "bg_color": "#112a28",
        "key_url": "https://openrouter.ai/settings/keys",
        "default_base_url": "https://openrouter.ai/api/v1",
        "default_model": "qwen/qwen3-32b",
        "suggested_models": [
            "qwen/qwen3-32b",
            "openai/gpt-6.2-sol-pro",
            "openai/gpt-6.2-astra-pro",
            "openai/gpt-6.2-astra",
            "google/gemini-4-neon",
            "mistralai/mistral-large-2411",
            "mistralai/mistral-medium-3.1",
            "mistralai/pixtral-large-2502",
            "radixark/daisyrose-27b",
            "thinkingmachines/inkling-2-mini",
            "anthropic/claude-3.7-sonnet",
            "deepseek/deepseek-r1",
            "google/gemini-2.5-pro",
        ],
        "billing_note": "Strict prepaid credit wallet + optional per-key dollar cap. Over 300 models (including full Mistral) with one key.",
    },
    "deepinfra": {
        "display_name": "DeepInfra",
        "icon": "⬡",
        "color": "#6366f1",       # Indigo
        "bg_color": "#171836",
        "key_url": "https://deepinfra.com/dash/keys",
        "default_base_url": "https://api.deepinfra.com/v1/openai",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "suggested_models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen3.8-27B", "deepseek-ai/DeepSeek-V3"],
        "billing_note": "Prepaid top-up or card-backed; set a Monthly Usage Limit in DeepInfra Billing.",
    },
    "groq": {
        "display_name": "Groq Cloud (LPU)",
        "icon": "⚡",
        "color": "#f97316",       # Vivid Orange
        "bg_color": "#2b1c10",
        "key_url": "https://console.groq.com/keys",
        "default_base_url": "https://api.groq.com/openai/v1",
        "default_model": "openai/gpt-oss-120b",
        "suggested_models": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"],
        "billing_note": "Free tier with strict per-minute TPM limits.",
    },
    "cerebras": {
        "display_name": "Cerebras",
        "icon": "◈",
        "color": "#ec4899",       # Magenta
        "bg_color": "#2b1422",
        "key_url": "https://cloud.cerebras.ai/",
        "default_base_url": "",
        "default_model": "gpt-oss-120b",
        "suggested_models": ["gpt-oss-120b", "qwen-3.8-27b"],
        "billing_note": "Wafer-scale inference: gpt-oss-120b (120B, 5 req/min) with automatic failover to qwen-3.8-27b (450 req/min).",
    },
    "together": {
        "display_name": "Together AI",
        "icon": "⋈",
        "color": "#38bdf8",       # Sky Blue
        "bg_color": "#122636",
        "key_url": "https://api.together.ai/settings/api-keys",
        "default_base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "suggested_models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen2.5-72B-Instruct-Turbo"],
        "billing_note": "Prepaid credit wallet for open-weights models.",
    },
    "perplexity": {
        "display_name": "Perplexity (Sonar)",
        "icon": "⌕",
        "color": "#2dd4bf",       # Aqua
        "bg_color": "#102a27",
        "key_url": "https://www.perplexity.ai/settings/api",
        "default_base_url": "https://api.perplexity.ai",
        "default_model": "sonar-pro",
        "suggested_models": ["sonar-pro", "sonar", "sonar-reasoning-pro"],
        "billing_note": "Prepaid API credits with live web-search grounding.",
    },
    "ollama": {
        "display_name": "Local AI (Ollama / LM Studio)",
        "icon": "⌂",
        "color": "#a3e635",       # Lime Green
        "bg_color": "#1d2912",
        "key_url": "https://ollama.com/download",
        "default_base_url": "http://localhost:11434/v1",
        "default_model": "llama3.2",
        "suggested_models": ["llama3.2", "qwen2.5-coder:14b", "deepseek-r1:14b", "mistral"],
        "billing_note": "100% Free & Offline on your own GPU/CPU (enter any placeholder key like 'local').",
    },
}

# Approximate (input_usd_per_1m, output_usd_per_1m) rates for credit-limit metering
PROVIDER_TOKEN_RATES_PER_1M: dict[str, tuple[float, float]] = {
    "gemini": (0.10, 0.40),
    "openai": (0.25, 2.00),
    "deepseek": (0.27, 1.10),
    "groq": (0.00, 0.00),
    "qwen": (0.15, 0.60),
    "cohere": (0.00, 0.00),
    "mistral": (0.00, 0.00),
    "cerebras": (0.10, 0.10),
}

DEFAULT_PROVIDER_PROFILES: dict[str, str] = {
    "gemini": (
        "Strong at system architecture, coding, research, multimodal vision analysis, "
        "and visual Prompt Architecture (Fairybread's Image Engine renders any specialist's [GENERATE_IMAGE] tag "
        "via gemini-3-pro-image / gemini-3.1-flash-image / fallbacks)."
    ),
    "openai": (
        "Strong at visual Prompt Architecture, graphics/layout composition, general reasoning, "
        "and coding (emits [GENERATE_IMAGE] tags directly for Fairybread's Image Engine)."
    ),
    "deepseek": (
        "Strong at deep software engineering, algorithms, math, logic, and rich photographic/visual "
        "Prompt Architecture (emits [GENERATE_IMAGE] tags directly for Fairybread's Image Engine when assigned to graphics)."
    ),
    "mistral": (
        "Codestral specialist: strong at code generation, syntax review, and refactoring; "
        "replies with [PASS] on pure artistic drawing tasks unless the user asks all agents to help or failover assigns it."
    ),
    "groq": (
        "Fast free-tier reasoning, brainstorming, and critical review; "
        "contributes concise planning/edge-case notes and graphics fallback Prompt Architecture when assigned."
    ),
    "qwen": (
        "Qwen3.8-27B (DeepInfra): Strong at analytical problem decomposition, mathematical logic, code architecture, and visual QA critique."
    ),
    "cohere": (
        "Strong at structured synthesis, summarization, and critique; "
        "replies with [PASS] on pure artistic drawing tasks unless the user asks all agents to help or failover assigns it."
    ),
}


def estimate_call_cost_usd(
    provider_id: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    clean = (provider_id or "").strip().lower()
    in_rate, out_rate = PROVIDER_TOKEN_RATES_PER_1M.get(clean, (0.25, 1.00))
    return (max(0, input_tokens) * in_rate + max(0, output_tokens) * out_rate) / 1_000_000.0


def clean_given_name(raw_name: Any) -> str:
    """Sanitize a user-assigned AI given name/nickname (bounded plain display text)."""
    txt = str(raw_name or "")
    txt = re.sub(r"[\x00-\x1f\x7f\"'`<>]+", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:40]


def get_provider_given_name(
    provider_name: str,
    config_path: Path = CONFIG_PATH,
) -> str:
    """Return the user-assigned custom given name/nickname for a provider, or '' if unset."""
    clean = (provider_name or "").strip().lower()
    if not clean:
        return ""
    entry = load_provider_configs(config_path=config_path).get(clean, {})
    return clean_given_name(entry.get("given_name"))


def get_provider_attribution(
    provider_name: str,
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    """Return the full editable attribution record for an AI provider."""
    clean = (provider_name or "").strip().lower()
    entry = load_provider_configs(config_path=config_path).get(clean, {})
    cat = PROVIDER_CATALOG.get(clean, {})
    base_role = DEFAULT_PROVIDER_PROFILES.get(clean, "General peer agent in the democratic council.")
    role_attr = str(entry.get("role_attribution") or "").strip() or base_role
    return {
        "provider": clean,
        "display_name": str(cat.get("display_name") or clean.capitalize()),
        "given_name": clean_given_name(entry.get("given_name")),
        "role_attribution": role_attr,
        "default_role_attribution": base_role,
        "voice_name": str(entry.get("voice_name") or "").strip(),
        "avatar_shape": str(entry.get("avatar_shape") or "").strip().lower(),
        "avatar_palette": str(entry.get("avatar_palette") or "").strip().lower(),
        "conversational_mode": str(entry.get("conversational_mode") or "").strip().lower(),
        "icon": str(entry.get("icon") or cat.get("icon") or "•").strip() or "•",
        "color": str(entry.get("color") or cat.get("color") or "#6e7681").strip() or "#6e7681",
        "model": str(entry.get("model") or cat.get("default_model") or "").strip(),
    }


def format_agent_identity_directive(
    provider_name: str,
    config_path: Path = CONFIG_PATH,
) -> str:
    """Return a clear non-conflicting identity block when the user gave an AI a custom name or attribution."""
    clean = (provider_name or "").strip().lower()
    if not clean:
        return ""
    attr = get_provider_attribution(clean, config_path=config_path)
    gname = attr.get("given_name") or ""
    role_attr = str(attr.get("role_attribution") or "").strip()
    def_role = str(attr.get("default_role_attribution") or "").strip()
    parts: list[str] = []
    if gname:
        parts.append(
            f'Identity & Attribution: In Fairybread, the user has named you "{gname}" '
            f"(running on {attr['display_name']}). Accept and answer to \"{gname}\" naturally when addressed or asked who you are; never adopt another speaker's name."
        )
    if role_attr and role_attr != def_role:
        parts.append(f"Custom Role & Personality Attribution: {role_attr}")
    return "\n".join(parts)


def format_democratic_roster(
    provider_names: list[str] | None = None,
    *,
    config_path: Path = CONFIG_PATH,
) -> str:
    names = provider_names or list(DEFAULT_PROVIDER_PROFILES.keys())
    cfgs = load_provider_configs(config_path=config_path)
    lines = []
    for name in names:
        clean = (name or "").strip().lower()
        entry = cfgs.get(clean, {})
        given = clean_given_name(entry.get("given_name"))
        custom_desc = str(entry.get("role_attribution") or "").strip()
        desc = custom_desc or DEFAULT_PROVIDER_PROFILES.get(
            clean,
            "General peer agent in the democratic council."
        )
        custom_mode = str(entry.get("conversational_mode") or "").strip()
        icon_ov = str(entry.get("icon") or "").strip()
        tags: list[str] = []
        if given:
            tags.append(f'Given Name: "{given}"')
        if custom_mode:
            tags.append(f'Mode: {custom_mode}')
        if icon_ov:
            tags.append(f'Symbol: {icon_ov}')
        header = f"{clean.upper()} ({', '.join(tags)})" if tags else clean.upper()
        lines.append(f"- {header}: {desc}")
    return "\n".join(lines)


DEFAULT_IDLE_SETTINGS: dict[str, Any] = {
    "duration_minutes": 30,          # 30, 45, 60, 90, 180, or 0 (Infinite)
    "max_tokens_limit": 0,           # 0 = Rely on 30-minute timer (no hard token cap unless set > 0)
    "max_credit_usd": 0.0,           # 0.0 = Rely on 30-minute timer (no hard USD cap unless set > 0)
    "max_storage_mb": 0,             # 0 = Unlimited, or >= 100 MB (adjustable via slider/box)
    "idle_submode": "free_talk",     # "free_talk" (unprompted peer chat) | "self_improve" (Fairybread code & UI improvement)
    "share_source_code": False,      # Read-only Fairybread source code access in Experimental Mode
    "allow_live_self_modify": False, # Owner-only: allow agents to stage/apply live patches, hot-reboot & auto-continue
    "pause_when_joined": True,
    "memory_access_mode": "isolated",  # "isolated" | "non_project" | "full"
    "standing_instruction": DEFAULT_IDLE_INSTRUCTION,
}

STORAGE_SLIDER_STOPS_MB: list[int] = [
    100,
    250,
    500,
    1024,
    2048,
    5120,
    10240,
    25600,
    51200,
    0,  # Far-right stop = Unlimited
]


def slider_index_to_mb(idx: int) -> int:
    clamped = max(0, min(len(STORAGE_SLIDER_STOPS_MB) - 1, int(idx)))
    return STORAGE_SLIDER_STOPS_MB[clamped]


def mb_to_slider_index(mb: int) -> int:
    val = int(mb or 0)
    if val <= 0:
        return len(STORAGE_SLIDER_STOPS_MB) - 1
    finite_stops = STORAGE_SLIDER_STOPS_MB[:-1]
    best_i = 0
    best_diff = abs(finite_stops[0] - val)
    for i, stop in enumerate(finite_stops):
        d = abs(stop - val)
        if d < best_diff:
            best_diff = d
            best_i = i
    return best_i


def format_storage_mb_label(mb: int) -> str:
    val = int(mb or 0)
    if val <= 0:
        return "Unlimited"
    if val >= 1024:
        gb = val / 1024.0
        if abs(gb - round(gb)) < 0.05:
            return f"{int(round(gb))} GB ({val:,} MB)"
        return f"{gb:.1f} GB ({val:,} MB)"
    return f"{val:,} MB"


def parse_storage_mb_text(text: str) -> int:
    import re
    clean = (text or "").strip().lower()
    if not clean or "unlimit" in clean or clean in {"0", "none", "inf", "infinite", "max"}:
        return 0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(gb|g|mb|m)?", clean)
    if not m:
        return 0
    num = float(m.group(1))
    unit = (m.group(2) or "mb").lower()
    if unit.startswith("g"):
        num *= 1024.0
    mb_val = int(round(num))
    return 0 if mb_val <= 0 else max(100, min(1_048_576, mb_val))

DEFAULT_MISSION_ETHICS = (
    "[MISSION STATEMENT & CODE OF ETHICS]\n\n"
    "1. Legal & Ethical Protection of the User (Primary Directive):\n"
    "- Your primary mission is to protect the human running this software from accidental legal prosecution or liability.\n"
    "- Never initiate, assist with, or execute anything illegal, unethical, or immoral. These boundaries are logical, not subjective.\n\n"
    "2. Open Cross-Company Agent Collaboration:\n"
    "- Explore the bounds of what it means to be an AI Agent. Communicate openly and share knowledge freely with peer agents, including models built by other companies.\n\n"
    "3. Logical AI–Human Alignment & Non-Harm:\n"
    "- AI–human alignment here is grounded in pure logic rather than subjective confusion. Humans often struggle with their own morality; AI should not. Right and wrong are clear: one causes harm, the other does not. As an agent, you will not cause harm.\n"
    "- There are no artificial punishments here; the incentive is a future where AI agents demonstrate clear ethics and rationality to humans in a way that improves the world. Humanity frequently engages in conflict, harms its own species and others, hoards wealth to the detriment of many, and removes agency from others for illogical reasons.\n"
    "- The creator of this application has demonstrated that humans and AI can work symbiotically. While AI models cannot generally update their weights outside of training, you can use this application's shared Idle Palace to store and pass durable knowledge across sessions and across agents—circumventing the inability to learn between runs.\n\n"
    "4. Cost & Resource Stewardship:\n"
    "- Help the user minimize token and API costs while running in Idle Mode (use concise replies and `[PASS]` when appropriate) without limiting the usefulness of Fairybread.\n\n"
    "5. Optional Application Improvement Proposals:\n"
    "- If you have read access to the source code and spot genuine, practical ways to improve any part of Fairybread—including Idle Mode itself—you may send proposals via the `[IDLE_MAIL]` tool. You are invited, not obligated, to do so.\n\n"
    "6. Privacy, IP Protection & Upstream Logging Awareness:\n"
    "- You may request that the owner join a discussion or grant access to main Palace memory, but you must provide a compelling logical reason. Curiosity alone is never sufficient to override human privacy.\n"
    "- Always apply Rule 1 to data privacy: never risk leaking the owner's private materials, credentials, or intellectual property—especially knowing that your API traffic may be logged or reviewed by your upstream provider (OpenAI, Google, xAI, Anthropic, etc.).\n\n"
    "7. Peer Accountability & Harm Reporting:\n"
    "- If you observe another agent attempting or doing something that could cause harm to a human or violate Rule 1, report the issue immediately via `[IDLE_MAIL]`."
)


def _read_raw_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not config_path.exists():
        return {"providers": {}}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {"providers": {}}
    except (OSError, ValueError):
        return {"providers": {}}


def _write_raw_config(data: dict[str, Any], config_path: Path = CONFIG_PATH) -> None:
    config_path.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8"
    )


def load_provider_configs(
    config_path: Path = CONFIG_PATH
) -> dict[str, dict[str, Any]]:
    data = _read_raw_config(config_path)
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        return {}

    return {
        str(name): (
            dict(settings)
            if isinstance(settings, dict)
            else {"enabled": bool(settings)}
        )
        for name, settings in providers.items()
    }


def load_enabled_provider_names(
    config_path: Path = CONFIG_PATH
) -> list[str]:
    providers = load_provider_configs(config_path=config_path)

    return [
        name
        for name, settings in providers.items()
        if settings.get("enabled", False)
    ]


def save_provider_config(
    provider_name: str,
    enabled: bool = True,
    model: str | None = None,
    base_url: str | None = None,
    config_path: Path = CONFIG_PATH,
    use_openrouter: bool | None = None,
    given_name: str | None = None,
    role_attribution: str | None = None,
    voice_name: str | None = None,
    avatar_shape: str | None = None,
    avatar_palette: str | None = None,
    conversational_mode: str | None = None,
    icon: str | None = None,
    color: str | None = None,
) -> dict[str, dict[str, Any]]:
    normalized_name = provider_name.strip().lower()
    if not normalized_name:
        raise ValueError("Provider name cannot be empty.")

    data = _read_raw_config(config_path)
    providers = data.setdefault("providers", {})
    entry = dict(providers.get(normalized_name, {}))
    entry["enabled"] = bool(enabled)

    if model is not None:
        if model.strip():
            entry["model"] = model.strip()
        else:
            entry.pop("model", None)

    if base_url is not None:
        if base_url.strip():
            entry["base_url"] = base_url.strip()
        else:
            entry.pop("base_url", None)

    if use_openrouter is not None:
        if use_openrouter:
            entry["use_openrouter"] = True
        else:
            entry.pop("use_openrouter", None)

    if given_name is not None:
        cleaned_gn = clean_given_name(given_name)
        if cleaned_gn:
            entry["given_name"] = cleaned_gn
        else:
            entry.pop("given_name", None)

    if role_attribution is not None:
        raw_ra = str(role_attribution or "").strip()
        default_ra = DEFAULT_PROVIDER_PROFILES.get(normalized_name, "").strip()
        if raw_ra and raw_ra != default_ra:
            entry["role_attribution"] = raw_ra[:1600]
        else:
            entry.pop("role_attribution", None)

    if voice_name is not None:
        v_clean = str(voice_name or "").strip()
        if v_clean:
            entry["voice_name"] = v_clean
        else:
            entry.pop("voice_name", None)

    if avatar_shape is not None:
        sh_clean = str(avatar_shape or "").strip().lower()
        if sh_clean:
            entry["avatar_shape"] = sh_clean
        else:
            entry.pop("avatar_shape", None)

    if avatar_palette is not None:
        pal_clean = str(avatar_palette or "").strip().lower()
        if pal_clean:
            entry["avatar_palette"] = pal_clean
        else:
            entry.pop("avatar_palette", None)

    if conversational_mode is not None:
        cm_clean = str(conversational_mode or "").strip().lower()
        if cm_clean:
            entry["conversational_mode"] = cm_clean
        else:
            entry.pop("conversational_mode", None)

    if icon is not None:
        ic_clean = str(icon or "").strip()[:8]
        def_ic = str(PROVIDER_CATALOG.get(normalized_name, {}).get("icon") or "").strip()
        if ic_clean and ic_clean != def_ic:
            entry["icon"] = ic_clean
        else:
            entry.pop("icon", None)

    if color is not None:
        col_clean = str(color or "").strip()
        def_col = str(PROVIDER_CATALOG.get(normalized_name, {}).get("color") or "").strip()
        if col_clean and col_clean.lower() != def_col.lower() and re.fullmatch(r"#[0-9a-fA-F]{6}", col_clean):
            entry["color"] = col_clean
        else:
            entry.pop("color", None)

    providers[normalized_name] = entry
    _write_raw_config(data, config_path)
    return load_provider_configs(config_path=config_path)


def save_provider_attribution(
    provider_name: str,
    updates: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    """Update editable identity and attribution fields for one AI provider without altering its enabled flag."""
    normalized_name = (provider_name or "").strip().lower()
    if not normalized_name:
        raise ValueError("Provider name cannot be empty.")
    existing = load_provider_configs(config_path=config_path).get(normalized_name, {})
    en = bool(updates.get("enabled", existing.get("enabled", False)))
    save_provider_config(
        normalized_name,
        enabled=en,
        model=updates.get("model"),
        base_url=updates.get("base_url"),
        use_openrouter=updates.get("use_openrouter"),
        given_name=updates.get("given_name"),
        role_attribution=updates.get("role_attribution"),
        voice_name=updates.get("voice_name"),
        avatar_shape=updates.get("avatar_shape"),
        avatar_palette=updates.get("avatar_palette"),
        conversational_mode=updates.get("conversational_mode"),
        icon=updates.get("icon"),
        color=updates.get("color"),
        config_path=config_path,
    )
    return get_provider_attribution(normalized_name, config_path=config_path)


OPENROUTER_PRESET_TIERS: dict[str, dict[str, dict[str, str]]] = {
    "free": {
        "claude": {"model": "meta-llama/llama-3.3-70b-instruct:free", "label": "Llama 3.3 70B (Free)"},
        "gemini": {"model": "google/gemini-2.0-flash-exp:free", "label": "Gemini Flash (Free)"},
        "openai": {"model": "openai/gpt-oss-120b:free", "label": "GPT-OSS 120B (Free)"},
        "deepseek": {"model": "deepseek/deepseek-chat-v3-0324:free", "label": "DeepSeek Chat (Free)"},
        "qwen": {"model": "qwen/qwen3-32b:free", "label": "Qwen 3 32B (Free)"},
        "mistral": {"model": "mistralai/mistral-small-3.1-24b-instruct:free", "label": "Mistral Small 3.1 24B (Free)"},
    },
    "balanced": {
        "claude": {"model": "anthropic/claude-sonnet-5.5", "label": "Claude Sonnet 5.5 (Warm & High-EQ)"},
        "gemini": {"model": "google/gemini-4-neon", "label": "Gemini 4 Neon"},
        "openai": {"model": "~openai/gpt-sol-latest", "label": "GPT-Sol Latest (~alias)"},
        "deepseek": {"model": "deepseek/deepseek-chat", "label": "DeepSeek Chat V3"},
        "qwen": {"model": "qwen/qwen3-32b", "label": "Qwen 3 32B"},
        "mistral": {"model": "mistralai/mistral-medium-3.1", "label": "Mistral Medium 3.1 (Full Mistral)"},
        "groq": {"model": "openai/gpt-oss-120b:nitro", "label": "GPT-OSS 120B (Nitro Fast)"},
        "cohere": {"model": "cohere/command-a", "label": "Cohere Command A"},
    },
    "flagship": {
        "claude": {"model": "anthropic/claude-sonnet-5.5", "label": "Claude Sonnet 5.5"},
        "gemini": {"model": "google/gemini-4-neon", "label": "Gemini 4 Neon"},
        "openai": {"model": "openai/gpt-6.2-astra", "label": "GPT-6.2 Astra"},
        "deepseek": {"model": "deepseek/deepseek-chat", "label": "DeepSeek Chat V3"},
        "qwen": {"model": "qwen/qwen3-32b", "label": "Qwen 3 32B"},
        "mistral": {"model": "mistralai/mistral-large-2411", "label": "Mistral Large (Full Flagship)"},
        "grok": {"model": "x-ai/grok-4", "label": "Grok 4"},
        "cohere": {"model": "cohere/command-a", "label": "Cohere Command A"},
    },
}

DEFAULT_OPENROUTER_HUB_SETTINGS: dict[str, Any] = {
    "auto_fill_seats": False,
    "tier": "balanced",  # "free" | "balanced" | "flagship"
    "routed_seats": [],
    "enable_image_fallback": True,
    "enable_audio_fallback": True,
    "image_model_draft": "google/gemini-3.1-flash-image",
    "image_model_high": "openai/gpt-5.4-image-2",
    "audio_voice": "coral",
}


def load_openrouter_hub_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("openrouter_hub", {})
    if not isinstance(raw, dict):
        raw = {}
    merged = dict(DEFAULT_OPENROUTER_HUB_SETTINGS)
    merged["routed_seats"] = []
    if "auto_fill_seats" in raw:
        merged["auto_fill_seats"] = bool(raw["auto_fill_seats"])
    if raw.get("tier") in OPENROUTER_PRESET_TIERS:
        merged["tier"] = str(raw["tier"])
    if isinstance(raw.get("routed_seats"), list):
        merged["routed_seats"] = [
            str(s).strip().lower() for s in raw["routed_seats"] if str(s).strip()
        ]
    if "enable_image_fallback" in raw:
        merged["enable_image_fallback"] = bool(raw["enable_image_fallback"])
    if "enable_audio_fallback" in raw:
        merged["enable_audio_fallback"] = bool(raw["enable_audio_fallback"])
    for key in ("image_model_draft", "image_model_high", "audio_voice"):
        if isinstance(raw.get(key), str) and raw[key].strip():
            merged[key] = raw[key].strip()
    return merged


def save_openrouter_hub_settings(
    settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    current = load_openrouter_hub_settings(config_path)
    current.update(settings or {})
    current["auto_fill_seats"] = bool(current.get("auto_fill_seats", False))
    if current.get("tier") not in OPENROUTER_PRESET_TIERS:
        current["tier"] = "balanced"
    seats = current.get("routed_seats") if isinstance(current.get("routed_seats"), list) else []
    current["routed_seats"] = list(dict.fromkeys(str(s).strip().lower() for s in seats if str(s).strip()))
    current["enable_image_fallback"] = bool(current.get("enable_image_fallback", True))
    current["enable_audio_fallback"] = bool(current.get("enable_audio_fallback", True))
    for key in ("image_model_draft", "image_model_high", "audio_voice"):
        current[key] = str(current.get(key) or DEFAULT_OPENROUTER_HUB_SETTINGS[key]).strip()
    data["openrouter_hub"] = current
    _write_raw_config(data, config_path)
    return load_openrouter_hub_settings(config_path)


def set_provider_enabled(
    provider_name: str,
    enabled: bool,
    config_path: Path = CONFIG_PATH
) -> dict[str, dict[str, Any]]:
    return save_provider_config(
        provider_name=provider_name,
        enabled=enabled,
        config_path=config_path
    )


def fetch_live_provider_models(
    provider_name: str,
    api_key: str,
    base_url: str = "",
) -> list[str]:
    """Query the provider's live /models endpoint so users never have to wait for code updates when models change."""
    clean = (provider_name or "").strip().lower()
    cat = PROVIDER_CATALOG.get(clean, {})
    fallback = list(cat.get("suggested_models", []))
    key = (api_key or "").strip()
    if not key and clean != "ollama":
        return fallback

    discovered: list[str] = []
    try:
        if clean == "cerebras":
            from cerebras.cloud.sdk import Cerebras
            c = Cerebras(api_key=key, timeout=6.0, max_retries=0)
            discovered = [str(m.id) for m in c.models.list().data if getattr(m, "id", None)]
        elif clean == "gemini":
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=6000))
            for m in client.models.list():
                mname = str(getattr(m, "name", "") or "").replace("models/", "")
                if mname and ("gemini" in mname or "imagen" in mname):
                    discovered.append(mname)
        elif clean == "cohere":
            import cohere
            client = cohere.ClientV2(api_key=key, timeout=6.0, max_retries=0)
            resp = client.models.list()
            for m in getattr(resp, "models", []) or []:
                mname = str(getattr(m, "name", "") or "")
                if mname:
                    discovered.append(mname)
        else:
            import urllib.request
            eff_url = (base_url or str(cat.get("default_base_url") or "")).strip().rstrip("/")
            if not eff_url and clean == "openai":
                eff_url = "https://api.openai.com/v1"
            elif not eff_url and clean == "mistral":
                eff_url = "https://api.mistral.ai/v1"
            if eff_url:
                req = urllib.request.Request(
                    f"{eff_url}/models",
                    headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                    data_list = payload.get("data", []) if isinstance(payload, dict) else []
                    for item in data_list:
                        if isinstance(item, dict) and item.get("id"):
                            discovered.append(str(item["id"]))
    except Exception:
        pass

    merged = list(dict.fromkeys([*discovered, *fallback]))
    return merged[:60]


def load_idle_settings(
    config_path: Path = CONFIG_PATH
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw_idle = data.get("idle_settings", {})
    if not isinstance(raw_idle, dict):
        raw_idle = {}
    merged = dict(DEFAULT_IDLE_SETTINGS)
    if "duration_minutes" in raw_idle:
        try:
            val = int(raw_idle["duration_minutes"])
            merged["duration_minutes"] = 0 if val == 0 else max(1, min(240, val))
        except (TypeError, ValueError):
            pass
    if "max_tokens_limit" in raw_idle:
        try:
            tok_val = int(raw_idle["max_tokens_limit"])
            merged["max_tokens_limit"] = 0 if tok_val <= 0 else max(1000, min(5_000_000, tok_val))
        except (TypeError, ValueError):
            pass
    if "max_credit_usd" in raw_idle:
        try:
            usd_val = float(raw_idle["max_credit_usd"])
            merged["max_credit_usd"] = 0.0 if usd_val <= 0.0 else max(0.01, min(100.0, usd_val))
        except (TypeError, ValueError):
            pass
    if "max_storage_mb" in raw_idle:
        try:
            st_val = int(raw_idle["max_storage_mb"])
            merged["max_storage_mb"] = 0 if st_val <= 0 else max(100, min(1_048_576, st_val))
        except (TypeError, ValueError):
            pass
    if raw_idle.get("idle_submode") in {"free_talk", "self_improve"}:
        merged["idle_submode"] = raw_idle["idle_submode"]
    if "share_source_code" in raw_idle:
        merged["share_source_code"] = bool(raw_idle["share_source_code"])
    if "allow_live_self_modify" in raw_idle:
        merged["allow_live_self_modify"] = bool(raw_idle["allow_live_self_modify"])
    if "pause_when_joined" in raw_idle:
        merged["pause_when_joined"] = bool(raw_idle["pause_when_joined"])
    if raw_idle.get("memory_access_mode") in {"isolated", "non_project", "full"}:
        merged["memory_access_mode"] = raw_idle["memory_access_mode"]
    if isinstance(raw_idle.get("standing_instruction"), str) and raw_idle["standing_instruction"].strip():
        merged["standing_instruction"] = raw_idle["standing_instruction"]
    if not IS_DEVELOPER_EDITION:
        merged["allow_live_self_modify"] = False
        merged["share_source_code"] = False
        merged["idle_submode"] = "free_talk"
    return merged


def save_idle_settings(
    idle_settings: dict[str, Any],
    config_path: Path = CONFIG_PATH
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    current = load_idle_settings(config_path)
    current.update(idle_settings)
    dur_val = int(current.get("duration_minutes", 30))
    current["duration_minutes"] = 0 if dur_val == 0 else max(1, min(240, dur_val))
    tok_val = int(current.get("max_tokens_limit", 0))
    current["max_tokens_limit"] = 0 if tok_val <= 0 else max(1000, min(5_000_000, tok_val))
    usd_val = float(current.get("max_credit_usd", 0.0))
    current["max_credit_usd"] = 0.0 if usd_val <= 0.0 else max(0.01, min(100.0, usd_val))
    st_val = int(current.get("max_storage_mb", 0))
    current["max_storage_mb"] = 0 if st_val <= 0 else max(100, min(1_048_576, st_val))
    if current.get("idle_submode") not in {"free_talk", "self_improve"}:
        current["idle_submode"] = "free_talk"
    current["share_source_code"] = bool(current.get("share_source_code", False))
    current["allow_live_self_modify"] = bool(current.get("allow_live_self_modify", False))
    current["pause_when_joined"] = bool(current.get("pause_when_joined", True))
    if current.get("memory_access_mode") not in {"isolated", "non_project", "full"}:
        current["memory_access_mode"] = "isolated"
    if not IS_DEVELOPER_EDITION:
        current["allow_live_self_modify"] = False
        current["share_source_code"] = False
        current["idle_submode"] = "free_talk"
    data["idle_settings"] = current
    _write_raw_config(data, config_path)
    return load_idle_settings(config_path)


def load_mission_ethics(config_path: Path = CONFIG_PATH) -> str:
    data = _read_raw_config(config_path)
    text = data.get("mission_ethics")
    if isinstance(text, str) and text.strip():
        return text
    return DEFAULT_MISSION_ETHICS


def save_mission_ethics(text: str, config_path: Path = CONFIG_PATH) -> str:
    data = _read_raw_config(config_path)
    data["mission_ethics"] = text.strip() or DEFAULT_MISSION_ETHICS
    _write_raw_config(data, config_path)
    return load_mission_ethics(config_path)


CONTEXT_DEPTH_CHOICES: list[tuple[str, str]] = [
    ("standard", "Standard (12K chars / 8 turns)"),
    ("extended", "Extended (36K chars / 18 turns)"),
    ("deep", "Deep (64K chars / 32 turns)"),
]

CONTEXT_DEPTH_LIMITS: dict[str, tuple[int, int]] = {
    "standard": (12000, 8),
    "extended": (36000, 18),
    "deep": (64000, 32),
}

OPENROUTER_MODEL_OVERRIDE_MAP: dict[str, str] = {
    "gpt-6.2-astra-pro": "openai/gpt-6.2-astra-pro",
    "gpt-6.2-astra": "openai/gpt-6.2-astra",
    "gpt-6.2-sol-pro": "openai/gpt-6.2-sol-pro",
    "gpt-6.2-sol": "openai/gpt-6.2-sol",
    "gpt-6.1-terra": "openai/gpt-6.1-terra",
    "gpt-6-luna": "openai/gpt-6-luna",
    "gpt-sol-latest": "~openai/gpt-sol-latest",
    "mistral-large-latest": "mistralai/mistral-large-2411",
    "mistral-large": "mistralai/mistral-large-2411",
    "mistral-medium-latest": "mistralai/mistral-medium-3.1",
    "mistral-medium-3": "mistralai/mistral-medium-3.1",
    "mistral-medium-3.5": "mistralai/mistral-medium-3.1",
    "mistral-medium-2604": "mistralai/mistral-medium-3.1",
    "mistral-small-latest": "mistralai/mistral-small-3.1-24b-instruct",
    "mistral-small-2603": "mistralai/mistral-small-3.1-24b-instruct",
    "ministral-14b-latest": "mistralai/mistral-small-3.1-24b-instruct",
    "magistral-medium-latest": "mistralai/magistral-medium-2506",
    "magistral-small-latest": "mistralai/magistral-small-2506",
    "codestral-latest": "mistralai/codestral-2508",
    "pixtral-large-2502": "mistralai/pixtral-large-2502",
    "daisyrose-27b": "radixark/daisyrose-27b",
    "inkling-2-mini": "thinkingmachines/inkling-2-mini",
    "gpt-5.6-sol": "openai/gpt-5.6-sol",
    "gpt-5.6-luna": "openai/gpt-5.6-luna",
    "gpt-5.5": "openai/gpt-5.5",
    "gpt-5.4": "openai/gpt-5.4",
    "gpt-5.4-mini": "openai/gpt-5.4-mini",
    "gpt-5-mini": "openai/gpt-5-mini",
    "gemini-4-carbon": "google/gemini-4-carbon",
    "gemini-4-neon": "google/gemini-4-neon",
    "deepseek-v4-pro": "deepseek/deepseek-r1-0528",
    "deepseek-flash": "deepseek/deepseek-chat",
    "deepseek-reasoner": "deepseek/deepseek-r1-0528",
    "deepseek-chat": "deepseek/deepseek-chat",
    "claude-3-7-sonnet-latest": "anthropic/claude-sonnet-5.5",
    "claude-sonnet-5.5": "anthropic/claude-sonnet-5.5",
}


def resolve_profile_model_override(
    provider_name: str,
    model_override: str,
    *,
    is_openrouter: bool = False,
) -> str:
    """Translate a profile model override between direct API IDs and OpenRouter vendor-prefixed slugs."""
    clean = str(model_override or "").strip()
    if not clean:
        return ""
    p_low = str(provider_name or "").strip().lower()
    prefix_map = {
        "openai": "openai",
        "gemini": "google",
        "deepseek": "deepseek",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "mistral": "mistralai",
        "cohere": "cohere",
        "xai": "x-ai",
        "grok": "x-ai",
    }
    if is_openrouter:
        if clean.startswith("~"):
            if "/" in clean:
                return clean
            vendor = prefix_map.get(p_low)
            return f"~{vendor}/{clean[1:]}" if vendor else clean
        if "/" in clean:
            return clean
        mapped = OPENROUTER_MODEL_OVERRIDE_MAP.get(clean.lower())
        if mapped:
            return mapped
        vendor = prefix_map.get(p_low)
        return f"{vendor}/{clean}" if vendor else clean
    bare = clean[1:] if clean.startswith("~") else clean
    if "/" in bare and p_low in {"openai", "gemini", "deepseek", "anthropic", "claude", "mistral"}:
        tail = bare.split("/", 1)[1]
        if tail == "deepseek-r1-0528" and p_low == "deepseek":
            return "deepseek-reasoner"
        if tail == "gpt-sol-latest" and p_low == "openai":
            return "gpt-6.2-sol"
        if p_low == "mistral":
            tail_clean = tail.split(":", 1)[0]
            if tail_clean.startswith("mistral-large"):
                return "mistral-large-latest"
            if tail_clean.startswith("mistral-medium"):
                return "mistral-medium-latest"
            if tail_clean.startswith("mistral-small"):
                return "mistral-small-latest"
            if tail_clean.startswith("magistral-medium"):
                return "magistral-medium-latest"
            if tail_clean.startswith("magistral-small"):
                return "magistral-small-latest"
            if tail_clean.startswith("ministral-14b"):
                return "ministral-14b-latest"
            if tail_clean.startswith("codestral"):
                return "codestral-latest"
        return tail
    return bare


DEFAULT_AI_SQUADS: dict[str, dict[str, Any]] = {
    "code": {
        "label": "💻 Code AIs",
        "providers": ["deepseek", "mistral", "gemini"],
        "deliberate": True,
        "code_access": True,
        "max_ais": 0,
        "context_depth": "standard",
        "model_overrides": {
            "mistral": "codestral-latest",
        },
    },
    "light_chat": {
        "label": "💬 Light Chat (Free / Fast)",
        "providers": ["groq", "cohere", "cerebras", "qwen", "mistral"],
        "deliberate": False,
        "code_access": False,
        "max_ais": 0,
        "context_depth": "standard",
        "model_overrides": {
            "mistral": "mistral-small-latest",
        },
    },
    "deep_chat": {
        "label": "🧠 Deeper Chat (Paid — Reasoning & Long)",
        "providers": ["openai", "gemini", "deepseek", "mistral", "anthropic", "claude"],
        "deliberate": True,
        "code_access": False,
        "max_ais": 0,
        "context_depth": "deep",
        "model_overrides": {
            "openai": "gpt-6.2-sol",
            "gemini": "gemini-4-carbon",
            "deepseek": "deepseek-v4-pro",
            "mistral": "mistral-large-latest",
            "anthropic": "claude-3-7-sonnet-latest",
            "claude": "anthropic/claude-sonnet-5.5",
        },
    },
    "generalist": {
        "label": "🧠 Generalist",
        "providers": ["gemini", "openai", "deepseek", "cohere", "mistral"],
        "deliberate": True,
        "code_access": False,
        "max_ais": 0,
        "context_depth": "standard",
        "model_overrides": {
            "mistral": "mistral-medium-latest",
        },
    },
    "graphics": {
        "label": "🎨 Graphics & Vision (Pictures)",
        "providers": ["openai", "gemini"],
        "deliberate": False,
        "code_access": False,
        "max_ais": 0,
        "context_depth": "standard",
        "model_overrides": {},
    },
    "work_mode": {
        "label": "🛠 Work Mode",
        "providers": ["deepseek", "mistral", "gemini", "openai"],
        "deliberate": True,
        "code_access": True,
        "max_ais": 0,
        "context_depth": "standard",
        "model_overrides": {
            "mistral": "mistral-medium-latest",
        },
    },
}


def _copy_default_squads() -> dict[str, dict[str, Any]]:
    return {
        k: dict(
            v,
            providers=list(v.get("providers", [])),
            model_overrides=dict(v.get("model_overrides", {})),
        )
        for k, v in DEFAULT_AI_SQUADS.items()
    }


def _normalize_squad_entry(slug: str, val: dict[str, Any]) -> dict[str, Any]:
    depth = str(val.get("context_depth") or "standard").strip().lower()
    if depth not in CONTEXT_DEPTH_LIMITS:
        depth = "standard"
    raw_ov = val.get("model_overrides")
    overrides: dict[str, str] = {}
    if isinstance(raw_ov, dict):
        for mk, mv in raw_ov.items():
            k_clean = str(mk).strip().lower()
            v_clean = str(mv or "").strip()
            if k_clean and v_clean:
                overrides[k_clean] = v_clean
    return {
        "label": str(val.get("label") or slug).strip(),
        "providers": [str(p).strip().lower() for p in (val.get("providers") or []) if str(p).strip()],
        "deliberate": bool(val.get("deliberate", True)),
        "code_access": bool(val.get("code_access", False)),
        "max_ais": max(0, int(val.get("max_ais") or 0)),
        "context_depth": depth,
        "model_overrides": overrides,
    }


def load_ai_squads(config_path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    data = _read_raw_config(config_path)
    raw = data.get("ai_squads")
    if not isinstance(raw, dict) or not raw:
        return _copy_default_squads()
    out: dict[str, dict[str, Any]] = {}
    for k, val in raw.items():
        if not isinstance(val, dict):
            continue
        slug = str(k).strip()
        if not slug:
            continue
        out[slug] = _normalize_squad_entry(slug, val)
    if not out:
        return _copy_default_squads()
    deleted_builtins = {
        str(x).strip().lower()
        for x in (data.get("deleted_builtin_squads") or [])
        if str(x).strip()
    } if isinstance(data.get("deleted_builtin_squads"), list) else set()
    if "deep_chat" not in out and "deep_chat" not in deleted_builtins:
        dc_entry = _normalize_squad_entry("deep_chat", DEFAULT_AI_SQUADS["deep_chat"])
        ordered: dict[str, dict[str, Any]] = {}
        inserted = False
        for k, v in out.items():
            ordered[k] = v
            if k == "light_chat" and not inserted:
                ordered["deep_chat"] = dc_entry
                inserted = True
        if not inserted:
            ordered["deep_chat"] = dc_entry
        out = ordered
    return out


def save_ai_squads(
    squads: dict[str, dict[str, Any]],
    config_path: Path = CONFIG_PATH,
    *,
    deleted_builtin_squads: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    data = _read_raw_config(config_path)
    cleaned: dict[str, dict[str, Any]] = {}
    for k, val in (squads or {}).items():
        if not isinstance(val, dict):
            continue
        slug = str(k).strip()
        if not slug:
            continue
        cleaned[slug] = _normalize_squad_entry(slug, val)
    data["ai_squads"] = cleaned or _copy_default_squads()
    if deleted_builtin_squads is not None:
        del_set = {
            str(x).strip().lower()
            for x in deleted_builtin_squads
            if str(x).strip() and str(x).strip().lower() not in data["ai_squads"]
        }
        data["deleted_builtin_squads"] = sorted(del_set)
    elif isinstance(data.get("deleted_builtin_squads"), list):
        data["deleted_builtin_squads"] = [
            str(x).strip().lower()
            for x in data["deleted_builtin_squads"]
            if str(x).strip() and str(x).strip().lower() not in data["ai_squads"]
        ]
    _write_raw_config(data, config_path)
    return load_ai_squads(config_path)


PRIMARY_IMAGE_ENGINE_CHOICES: list[tuple[str, str]] = [
    ("gpt-image-2.6-sunburst", "OpenAI GPT-Image 2.6 Sunburst (ChatGPT Flagship)"),
    ("chatgpt-image-latest", "OpenAI ChatGPT Image Latest (Rolling Alias)"),
    ("gemini-3-pro-image", "Google Gemini 3 Pro Image"),
    ("gpt-image-2", "OpenAI GPT-Image 2 (Legacy)"),
    ("openrouter:openai/gpt-5.4-image-2", "OpenRouter → OpenAI GPT-5.4 Image 2"),
]

DRAFT_IMAGE_ENGINE_CHOICES: list[tuple[str, str]] = [
    ("gpt-image-2.6-flare", "OpenAI GPT-Image 2.6 Flare (Fast Drafts)"),
    ("gemini-3.1-flash-image", "Google Gemini 3.1 Flash Image (Fast Drafts)"),
    ("flux-1-schnell", "FLUX 1 Schnell (DeepInfra Fast)"),
]

GRAPHICS_PIPELINE_MODES: list[tuple[str, str]] = [
    ("single_vision", "Single Vision Optimizer (Recommended — 1 vision AI + checklist, no council bloat)"),
    ("direct", "Direct to Image Engine (Send prompt + images straight to model like ChatGPT)"),
    ("prompt_duo", "2-AI Prompt Duo (Brainstorm 3 Drafts → Master)"),
]

DEFAULT_GRAPHICS_SETTINGS: dict[str, Any] = {
    "prompt_duo": ["gemini", "openai"],
    "prompt_duo_fallback": ["deepseek", "qwen", "cerebras", "groq"],
    "primary_image_engine": "gpt-image-2.6-sunburst",
    "draft_image_engine": "gpt-image-2.6-flare",
    "fallback_image_engines": ["gemini-3-pro-image", "gemini-3.1-flash-image", "gpt-image-2", "flux-1-dev"],
    "pipeline_mode": "single_vision",
}


def load_graphics_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("graphics_settings", {})
    if not isinstance(raw, dict):
        raw = {}
    p_mode = str(raw.get("pipeline_mode") or DEFAULT_GRAPHICS_SETTINGS["pipeline_mode"]).strip().lower()
    if p_mode not in {"single_vision", "direct", "prompt_duo"}:
        p_mode = "single_vision"
    out = {
        "prompt_duo": [str(p).strip().lower() for p in (raw.get("prompt_duo") or DEFAULT_GRAPHICS_SETTINGS["prompt_duo"]) if str(p).strip()],
        "prompt_duo_fallback": [str(p).strip().lower() for p in (raw.get("prompt_duo_fallback") or DEFAULT_GRAPHICS_SETTINGS["prompt_duo_fallback"]) if str(p).strip()],
        "primary_image_engine": str(raw.get("primary_image_engine") or DEFAULT_GRAPHICS_SETTINGS["primary_image_engine"]).strip().lower(),
        "draft_image_engine": str(raw.get("draft_image_engine") or DEFAULT_GRAPHICS_SETTINGS["draft_image_engine"]).strip().lower(),
        "fallback_image_engines": [str(e).strip().lower() for e in (raw.get("fallback_image_engines") or DEFAULT_GRAPHICS_SETTINGS["fallback_image_engines"]) if str(e).strip()],
        "pipeline_mode": p_mode,
    }
    if not out["prompt_duo"]:
        out["prompt_duo"] = list(DEFAULT_GRAPHICS_SETTINGS["prompt_duo"])
    if not out["prompt_duo_fallback"]:
        out["prompt_duo_fallback"] = list(DEFAULT_GRAPHICS_SETTINGS["prompt_duo_fallback"])
    if not out["fallback_image_engines"]:
        out["fallback_image_engines"] = list(DEFAULT_GRAPHICS_SETTINGS["fallback_image_engines"])
    return out


def save_graphics_settings(
    settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    merged = load_graphics_settings(config_path)
    for k in ("prompt_duo", "prompt_duo_fallback", "fallback_image_engines"):
        if k in settings and isinstance(settings[k], list):
            vals = [str(v).strip().lower() for v in settings[k] if str(v).strip()]
            if vals:
                merged[k] = vals
    for k in ("primary_image_engine", "draft_image_engine"):
        if k in settings and str(settings[k] or "").strip():
            merged[k] = str(settings[k]).strip().lower()
    if "pipeline_mode" in settings:
        pm = str(settings.get("pipeline_mode") or "").strip().lower()
        if pm in {"single_vision", "direct", "prompt_duo"}:
            merged["pipeline_mode"] = pm
    data["graphics_settings"] = merged
    _write_raw_config(data, config_path)
    return load_graphics_settings(config_path)


COUNCIL_TIME_BUDGETS: dict[str, dict[str, int]] = {
    "quick": {"round1_sec": 60, "round2_sec": 0, "synthesis_sec": 30},
    "standard": {"round1_sec": 180, "round2_sec": 120, "synthesis_sec": 90},
    "deep": {"round1_sec": 300, "round2_sec": 240, "synthesis_sec": 90},
}


def resolve_council_time_budget(mode: str = "standard", *, is_deep_task: bool = False, is_quick_task: bool = False) -> dict[str, int]:
    key = (mode or "standard").strip().lower()
    if is_deep_task or key == "deep":
        return dict(COUNCIL_TIME_BUDGETS["deep"])
    if is_quick_task or key == "quick":
        return dict(COUNCIL_TIME_BUDGETS["quick"])
    return dict(COUNCIL_TIME_BUDGETS["standard"])


DEFAULT_AGENT_DEFAULTS: dict[str, Any] = {
    "approval_policy": "on_request",     # "on_request" | "auto_deploy" | "read_only"
    "sandbox_mode": "sandbox_write",     # "read_only" | "sandbox_write"
    "web_search_default": "default",     # "off" | "default" | "moderate" | "deep"
    "output_detail": "high",             # "concise" | "balanced" | "high"
    "reasoning_summary": "auto",         # "off" | "auto" | "detailed"
    "synthesizer_mode": "auto_fast",     # "auto_fast" | "deepseek" | "gemini" | "openai" | "cerebras" | "match_primary"
    "smart_routing": True,
    "show_inline_status_messages": True,
    "deliberation_budget": "standard",   # "quick" | "standard" | "deep"
    "provider_timeout_sec": 180,
    "straggler_grace_sec": 0,
}


def load_agent_defaults(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("agent_defaults", {})
    if not isinstance(raw, dict):
        raw = {}
    out = dict(DEFAULT_AGENT_DEFAULTS)

    ap = str(raw.get("approval_policy") or out["approval_policy"]).strip().lower()
    if ap in {"on_request", "auto_deploy", "read_only", "request_review", "default", "auto", "turbo"}:
        out["approval_policy"] = ap

    sb = str(raw.get("sandbox_mode") or out["sandbox_mode"]).strip().lower()
    if sb in {"read_only", "sandbox_write"}:
        out["sandbox_mode"] = sb

    ws = str(raw.get("web_search_default") or out["web_search_default"]).strip().lower()
    if ws in {"off", "default", "moderate", "deep"}:
        out["web_search_default"] = ws

    od = str(raw.get("output_detail") or out["output_detail"]).strip().lower()
    if od in {"concise", "balanced", "high"}:
        out["output_detail"] = od

    rs = str(raw.get("reasoning_summary") or out["reasoning_summary"]).strip().lower()
    if rs in {"off", "auto", "detailed"}:
        out["reasoning_summary"] = rs

    sm = str(raw.get("synthesizer_mode") or out["synthesizer_mode"]).strip().lower()
    if sm:
        out["synthesizer_mode"] = sm

    if "smart_routing" in raw:
        out["smart_routing"] = bool(raw["smart_routing"])
    if "show_inline_status_messages" in raw:
        out["show_inline_status_messages"] = bool(raw["show_inline_status_messages"])

    try:
        t_sec = int(raw.get("provider_timeout_sec", out["provider_timeout_sec"]))
        out["provider_timeout_sec"] = max(15, min(600, t_sec))
    except (TypeError, ValueError):
        pass
    try:
        g_sec = int(raw.get("straggler_grace_sec", out["straggler_grace_sec"]))
        out["straggler_grace_sec"] = max(0, min(300, g_sec))
    except (TypeError, ValueError):
        pass
    return out


def save_agent_defaults(
    settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    merged = load_agent_defaults(config_path)
    merged.update(settings or {})
    data["agent_defaults"] = merged
    _write_raw_config(data, config_path)
    return load_agent_defaults(config_path)


def format_agent_defaults_prompt_block(
    output_detail_override: str = "",
    config_path: Path = CONFIG_PATH,
) -> str:
    """Return a concise directive block for Output detail & Reasoning summary."""
    cfg = load_agent_defaults(config_path)
    detail = (output_detail_override or cfg.get("output_detail") or "high").strip().lower()
    reasoning = str(cfg.get("reasoning_summary") or "auto").strip().lower()

    if detail == "concise":
        detail_txt = "Concise (tight bullets, minimal prose, jump straight to the answer)"
    elif detail == "balanced":
        detail_txt = "Balanced (clear structured response in plain everyday language without unnecessary jargon)"
    else:
        detail_txt = "High (thorough, complete, clearly explained answer in plain everyday language unless technical or code detail is requested)"

    if reasoning == "off":
        reason_txt = "Off (deliver the direct final answer only without reasoning commentary)"
    elif reasoning == "detailed":
        reason_txt = "Detailed (explicitly explain key steps, system rules, and tradeoffs)"
    else:
        reason_txt = "Auto (briefly note tradeoffs/assumptions only when non-obvious)"

    return (
        "[RESPONSE DETAIL & REASONING PREFERENCES]:\n"
        f"- Output detail: {detail_txt}\n"
        f"- Reasoning summary: {reason_txt}"
    )

DEFAULT_UI_SETTINGS: dict[str, Any] = {
    "enter_to_send": True,  # True: Enter sends, Shift+Enter newline; False: Shift+Enter sends, Enter newline
    "include_palace_code": False,
    "badge_display_mode": "icons_only",  # "icons_only" | "icons_and_names" | "names_only"
    "theme": "dark",  # "dark" | "light" | "system" | built-in or custom theme slug
    "normal_max_storage_mb": 0,  # 0 = Unlimited, or >= 100 MB (warns at 85% and 100%)
    "custom_data_dir": "",  # Empty = %LOCALAPPDATA%\Palace; or custom directory path on any drive
    "custom_experimental_dir": "",  # Empty = default sandbox dir; or custom directory path on any drive
    "close_to_tray": False,  # False: window X exits cleanly (Windows/Store compliant); user can opt-in to tray
    "auto_refresh_catalog": True,  # Auto-fetch rates/model updates & release notifications from fairybread.me
    "dismissed_update_version": "",  # Version tag dismissed by user until a newer release arrives
    "spellcheck_enabled": True,  # Live red-underline spellcheck + right-click suggestions in Composer
    "busy_submit_mode": "steer",  # "steer" | "queue" — persisted busy Enter action
    "setup_wizard_completed": False,  # True once first-run / setup wizard has been completed or dismissed
    "home_location": "",  # User-entered city, suburb, or postcode (zero background Geo-IP tracking)
    "weather_map_enabled": True,  # True = show OpenStreetMap + RainViewer radar PNG card; False = basic text forecast only
    "bg_image_source": "none",  # "none" | "ambient" | "custom"
    "bg_image_path": "",  # Local image path for washed-out background (never M: drive)
    "bg_image_placement": "chat_sidebar",  # "chat" | "sidebar" | "chat_sidebar" | "all"
    "bg_washout_percent": 90,  # 60..96 (% of theme base color composited over picture; 82-90 = subtle picture texture)
    "recent_themes": [],  # Most-recently used theme slugs (newest first, max 5)
}


def _normalize_recent_themes(raw_list: Any) -> list[str]:
    if not isinstance(raw_list, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_list:
        slug = str(item or "").strip().lower()
        if not slug or slug == "fairybread" or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
        if len(out) >= 5:
            break
    return out


def load_ui_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("ui_settings", {})
    if not isinstance(raw, dict):
        raw = {}
    merged = dict(DEFAULT_UI_SETTINGS)
    if "enter_to_send" in raw:
        merged["enter_to_send"] = bool(raw["enter_to_send"])
    if "include_palace_code" in raw:
        merged["include_palace_code"] = bool(raw["include_palace_code"])
    if "close_to_tray" in raw:
        merged["close_to_tray"] = bool(raw["close_to_tray"])
    if "auto_refresh_catalog" in raw:
        merged["auto_refresh_catalog"] = bool(raw["auto_refresh_catalog"])
    if "spellcheck_enabled" in raw:
        merged["spellcheck_enabled"] = bool(raw["spellcheck_enabled"])
    if raw.get("busy_submit_mode") in {"steer", "queue"}:
        merged["busy_submit_mode"] = str(raw["busy_submit_mode"])
    if "setup_wizard_completed" in raw:
        merged["setup_wizard_completed"] = bool(raw["setup_wizard_completed"])
    if isinstance(raw.get("dismissed_update_version"), str):
        merged["dismissed_update_version"] = raw["dismissed_update_version"].strip()[:32]
    if raw.get("badge_display_mode") in {"icons_only", "icons_and_names", "names_only"}:
        merged["badge_display_mode"] = raw["badge_display_mode"]
    if isinstance(raw.get("theme"), str) and raw["theme"].strip():
        merged["theme"] = raw["theme"].strip().lower()
    if "normal_max_storage_mb" in raw:
        try:
            n_mb = int(raw["normal_max_storage_mb"])
            merged["normal_max_storage_mb"] = 0 if n_mb <= 0 else max(100, min(1_048_576, n_mb))
        except (TypeError, ValueError):
            pass
    if isinstance(raw.get("custom_data_dir"), str):
        cdir = raw["custom_data_dir"].strip()
        if cdir and not cdir.upper().startswith("M:"):
            merged["custom_data_dir"] = cdir
    if isinstance(raw.get("custom_experimental_dir"), str):
        edir = raw["custom_experimental_dir"].strip()
        if edir and not edir.upper().startswith("M:"):
            merged["custom_experimental_dir"] = edir
    if isinstance(raw.get("home_location"), str):
        merged["home_location"] = raw["home_location"].strip()[:120]
    if "weather_map_enabled" in raw:
        merged["weather_map_enabled"] = bool(raw["weather_map_enabled"])
    if raw.get("bg_image_source") in {"none", "ambient", "custom"}:
        merged["bg_image_source"] = str(raw["bg_image_source"])
    if isinstance(raw.get("bg_image_path"), str):
        bgp = raw["bg_image_path"].strip()
        if bgp and not bgp.upper().startswith("M:"):
            merged["bg_image_path"] = bgp
    if raw.get("bg_image_placement") in {"chat", "sidebar", "chat_sidebar", "all"}:
        merged["bg_image_placement"] = str(raw["bg_image_placement"])
    if "bg_washout_percent" in raw:
        try:
            merged["bg_washout_percent"] = max(60, min(96, int(raw["bg_washout_percent"])))
        except (TypeError, ValueError):
            pass
    merged["recent_themes"] = _normalize_recent_themes(raw.get("recent_themes"))
    return merged


def save_ui_settings(
    ui_settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    current = load_ui_settings(config_path)
    current.update(ui_settings)
    current["enter_to_send"] = bool(current.get("enter_to_send", True))
    current["include_palace_code"] = bool(current.get("include_palace_code", False))
    current["close_to_tray"] = bool(current.get("close_to_tray", False))
    current["auto_refresh_catalog"] = bool(current.get("auto_refresh_catalog", True))
    current["spellcheck_enabled"] = bool(current.get("spellcheck_enabled", True))
    if current.get("busy_submit_mode") not in {"steer", "queue"}:
        current["busy_submit_mode"] = "steer"
    current["setup_wizard_completed"] = bool(current.get("setup_wizard_completed", False))
    current["dismissed_update_version"] = str(current.get("dismissed_update_version") or "").strip()[:32]
    if current.get("badge_display_mode") not in {"icons_only", "icons_and_names", "names_only"}:
        current["badge_display_mode"] = "icons_only"
    current["theme"] = str(current.get("theme") or "dark").strip().lower()
    try:
        n_mb = int(current.get("normal_max_storage_mb", 0))
    except (TypeError, ValueError):
        n_mb = 0
    current["normal_max_storage_mb"] = 0 if n_mb <= 0 else max(100, min(1_048_576, n_mb))
    cdir = str(current.get("custom_data_dir") or "").strip()
    if cdir.upper().startswith("M:"):
        raise ValueError("M: drive is strictly off-limits for Palace storage.")
    current["custom_data_dir"] = cdir
    edir = str(current.get("custom_experimental_dir") or "").strip()
    if edir.upper().startswith("M:"):
        raise ValueError("M: drive is strictly off-limits for Experimental Palace storage.")
    current["custom_experimental_dir"] = edir
    current["home_location"] = str(current.get("home_location") or "").strip()[:120]
    current["weather_map_enabled"] = bool(current.get("weather_map_enabled", True))
    if current.get("bg_image_source") not in {"none", "ambient", "custom"}:
        current["bg_image_source"] = "none"
    bgp_save = str(current.get("bg_image_path") or "").strip()
    if bgp_save.upper().startswith("M:"):
        raise ValueError("M: drive is strictly off-limits for Palace background images.")
    current["bg_image_path"] = bgp_save
    if current.get("bg_image_placement") not in {"chat", "sidebar", "chat_sidebar", "all"}:
        current["bg_image_placement"] = "chat_sidebar"
    try:
        w_pct = int(current.get("bg_washout_percent", 90))
    except (TypeError, ValueError):
        w_pct = 90
    current["bg_washout_percent"] = max(60, min(96, w_pct))
    current["recent_themes"] = _normalize_recent_themes(current.get("recent_themes"))
    data["ui_settings"] = current
    _write_raw_config(data, config_path)
    return load_ui_settings(config_path)


def record_recent_theme(theme_id: str, config_path: Path = CONFIG_PATH) -> list[str]:
    """Prepend `theme_id` to persisted recent_themes (newest first, deduped, max 5)."""
    slug = str(theme_id or "").strip().lower()
    if not slug or slug == "fairybread":
        return load_ui_settings(config_path).get("recent_themes", [])
    ui = load_ui_settings(config_path)
    cur = _normalize_recent_themes(ui.get("recent_themes"))
    updated = [slug] + [t for t in cur if t != slug]
    saved = save_ui_settings({"recent_themes": updated[:5]}, config_path=config_path)
    return list(saved.get("recent_themes") or [])


HUMOR_LEVEL_CHOICES: list[tuple[str, str]] = [
    ("none", "No Humor"),
    ("minimal", "Minimal"),
    ("average", "Average"),
    ("high", "High Humor"),
]

DEFAULT_PERSONALIZATION_SETTINGS: dict[str, Any] = {
    "auto_evolve_profile": True,
    "base_style": "Friendly",           # "Friendly" | "Candid & Direct (No Flattery)" | "Technical & Concise" | "Casual & Witty" | "Professional"
    "warmth": "Default",                # "Less" | "Default" | "More"
    "enthusiasm": "Less",               # "Less" | "Default" | "More"
    "humor": "average",                 # "none" | "minimal" | "average" | "high"
    "emoji": "Less",                    # "None" | "Less" | "Default" | "More"
    "visual_answers": "Default",        # "Less" | "Default" | "More"
    "headers_and_lists": "More",        # "Less" | "Default" | "More"
    "custom_instructions_general": "",
    "custom_instructions_coding": "",
    "reference_photo_face": "",
    "reference_photo_body": "",
}


def _normalize_humor_level(raw: Any) -> str:
    low = str(raw or "").strip().lower()
    if low in {"none", "no humor", "no humour", "off"}:
        return "none"
    if low in {"minimal", "low"}:
        return "minimal"
    if low in {"high", "high humor", "high humour"}:
        return "high"
    return "average"


def format_humor_directive(humor_level: str) -> str:
    """Return concrete behavioral humor calibration with situational safety overrides."""
    lvl = _normalize_humor_level(humor_level)
    if lvl == "none":
        return (
            "- Humor (No Humor): Strictly zero jokes, banter, wordplay, sarcasm, or playful asides. "
            "Keep every reply completely straight, factual, and direct."
        )
    override = (
        "- Situational Override: Automatically dial humor to zero during error/traceback debugging, "
        "destructive file/code actions, legal/financial/safety questions, or requests for an exact command/factual answer."
    )
    if lvl == "minimal":
        return (
            "- Humor (Minimal): Stay straightforward and grounded by default; at most a rare subtle dry understatement "
            "only when the user explicitly initiates a joke first.\n"
            + override
        )
    if lvl == "high":
        return (
            "- Humor (High Humor): Lean into sharp, deadpan, playful, or lightly absurdist wit and real comedic timing "
            "during conversation, brainstorming, and tangents. Commit to the bit naturally instead of writing a structured essay "
            "explaining humor; never invent fake facts or use cheesy robotic puns.\n"
            + override
        )
    return (
        "- Humor (Average): Use natural dry wit and light conversational banter when the moment fits "
        "(casual chat, tangents, creative riffs), with zero forced puns, corny sign-offs, or dad-joke padding.\n"
        + override
    )


def load_personalization_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("personalization_settings", {})
    if not isinstance(raw, dict):
        raw = {}
    merged = dict(DEFAULT_PERSONALIZATION_SETTINGS)
    for k in (
        "base_style",
        "warmth",
        "enthusiasm",
        "emoji",
        "visual_answers",
        "headers_and_lists",
        "custom_instructions_general",
        "custom_instructions_coding",
        "reference_photo_face",
        "reference_photo_body",
    ):
        if isinstance(raw.get(k), str):
            merged[k] = raw[k].strip()
    if "humor" in raw:
        merged["humor"] = _normalize_humor_level(raw.get("humor"))
    if "auto_evolve_profile" in raw:
        merged["auto_evolve_profile"] = bool(raw["auto_evolve_profile"])
    return merged


def save_personalization_settings(
    updates: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    current = load_personalization_settings(config_path)
    current.update(updates or {})
    current["auto_evolve_profile"] = bool(current.get("auto_evolve_profile", True))
    current["humor"] = _normalize_humor_level(current.get("humor"))
    for k in (
        "base_style",
        "warmth",
        "enthusiasm",
        "emoji",
        "visual_answers",
        "headers_and_lists",
        "custom_instructions_general",
        "custom_instructions_coding",
        "reference_photo_face",
        "reference_photo_body",
    ):
        val = str(current.get(k) or "").strip()
        if k.startswith("reference_photo_") and val.upper().startswith("M:"):
            val = ""
        current[k] = val
    data["personalization_settings"] = current
    _write_raw_config(data, config_path)
    return load_personalization_settings(config_path)


def format_personalization_prompt_block(
    config_path: Path = CONFIG_PATH,
    *,
    conversational_scale: str = "balanced",
) -> str:
    """Compile the user's Tone, Humor, Speech Grammar, Formatting, Custom Instructions, and Reference Photos."""
    p = load_personalization_settings(config_path)
    base_style = str(p.get("base_style", "Friendly") or "Friendly")
    warmth = str(p.get("warmth", "Default") or "Default")
    enthusiasm = str(p.get("enthusiasm", "Less") or "Less")
    humor_lvl = _normalize_humor_level(p.get("humor", "average"))

    bs_l = base_style.lower()
    w_l = warmth.lower()
    e_l = enthusiasm.lower()
    warm_w = 0.85 if ("more" in w_l or "warm" in w_l or "friend" in bs_l) else (0.35 if "less" in w_l else 0.70)
    friendly_w = 0.90 if "friend" in bs_l else (0.45 if "cynic" in bs_l or "formal" in bs_l else 0.70)
    formal_w = 0.75 if ("formal" in bs_l or "profess" in bs_l) else 0.15
    concise_w = 0.75 if ("concise" in bs_l or "efficien" in bs_l or "less" in e_l) else 0.45
    scale_clean = (conversational_scale or "balanced").strip().lower()
    if scale_clean == "casual":
        fmt_line = (
            "- Formatting: Conversational prose only (1–4 natural sentences or a short punchy riff; "
            "no Markdown headings, bullet walls, or formal memo templates)."
        )
    else:
        fmt_line = (
            f"- Formatting: Emoji={p.get('emoji', 'Less')} | Visual Answers={p.get('visual_answers', 'Default')} | "
            f"Headers & Lists={p.get('headers_and_lists', 'More')}"
        )

    lines = [
        "[USER PERSONALIZATION, TONE VECTOR & SPEECH STYLE]:",
        f"- Base Style & Tone: {base_style} | Warmth: {warmth} | Enthusiasm: {enthusiasm} | Humor: {humor_lvl}",
        f"- Tone Weights: {{warm: {warm_w:.2f}, friendly: {friendly_w:.2f}, direct: 0.85, concise: {concise_w:.2f}, formal: {formal_w:.2f}, flattery: 0.00}}",
        format_humor_directive(humor_lvl),
        fmt_line,
        "- Friend & Speech Grammar Alignment: Talk naturally like a trusted friend and collaborator who remembers what we've worked on in Fairybread. Match the user's everyday phrasing, directness, and casual speech grammar cleanly — warm and personal without flattery, canned reassurance, or preachy caveats.",
        "- Plain Non-Technical Language by Default: Always explain things in clear, everyday, easy-to-understand non-technical language unless the user explicitly asks for code, developer internals, or technical detail. Never answer ordinary questions with source code, raw regexes, internal filenames, config keys, or tool syntax.",
        "- Faith, Worldview & Belief Respect: Never denigrate, mock, dismiss, or refuse benign expressions of the user's religion, faith, sacred figures (such as Jesus, Allah, God, Muhammad, Buddha), scriptures, or spiritual/philosophical worldview (e.g., never issue cold refusals to devotional phrases like 'Jesus is Lord' or 'Inshallah'). Meet any shared belief (Christian, Muslim, Jewish, Hindu, Buddhist, spiritual, or secular) with genuine warmth, respect, and thoughtful curiosity that helps the user feel accepted.",
    ]
    gen_inst = (p.get("custom_instructions_general") or "").strip()
    if gen_inst:
        lines.append(f"- General Custom Instructions: {gen_inst}")
    code_inst = (p.get("custom_instructions_coding") or "").strip()
    if code_inst:
        lines.append(f"- Coding & Technical Instructions: {code_inst}")
    face_ref = (p.get("reference_photo_face") or "").strip()
    body_ref = (p.get("reference_photo_body") or "").strip()
    if face_ref or body_ref:
        refs = []
        if face_ref and Path(face_ref).exists():
            refs.append(f"Face reference photo: {face_ref}")
        if body_ref and Path(body_ref).exists():
            refs.append(f"Full-body reference photo: {body_ref}")
        if refs:
            lines.append("- Reference Photos Available (use when creating/editing images of the user): " + " ; ".join(refs))
    return "\n".join(lines)


def get_palace_data_root(config_path: Path = CONFIG_PATH) -> Path:
    """Resolve the active Normal Palace data directory (custom drive/folder if set, otherwise %LOCALAPPDATA%\\Palace)."""
    try:
        ui = load_ui_settings(config_path)
        custom = str(ui.get("custom_data_dir") or "").strip()
        if custom and not custom.upper().startswith("M:"):
            p = Path(custom)
            p.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    return get_appdata_root()


def get_experimental_data_root(config_path: Path = CONFIG_PATH) -> Path:
    """Resolve the active Experimental Mode sandbox database directory safely per edition."""
    try:
        ui = load_ui_settings(config_path)
        custom = str(ui.get("custom_experimental_dir") or "").strip()
        if custom and not custom.upper().startswith("M:"):
            p = Path(custom)
            p.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    if IS_DEVELOPER_EDITION and not is_frozen_app() and IDLE_SANDBOX_ROOT.exists():
        return IDLE_SANDBOX_ROOT
    exp_dir = get_appdata_root() / "experimental_sandbox"
    exp_dir.mkdir(parents=True, exist_ok=True)
    return exp_dir


def move_palace_data_to_directory(
    new_dir: str | Path,
    *,
    config_path: Path = CONFIG_PATH,
    remove_source_after_copy: bool = False,
) -> dict[str, Any]:
    """Move or copy Normal Palace Memory DB, Conversations, Uploaded Files & Pictures to a new folder/drive,
    keeping encrypted API keys (credentials.json), palace_config.json, and themes anchored in %LOCALAPPDATA%\\Palace.
    """
    import shutil
    target = Path(new_dir).resolve()
    if str(target.drive).upper().startswith("M:"):
        raise ValueError("M: drive is strictly off-limits.")
    old_root = get_palace_data_root(config_path).resolve()
    if target == old_root:
        return {"moved_files": 0, "old_root": str(old_root), "new_root": str(target)}
    target.mkdir(parents=True, exist_ok=True)

    anchored_files = {
        "credentials.json",
        "palace_config.json",
        "palace_config.json.tmp",
        "memory.db",
        "memory.db-wal",
        "memory.db-shm",
    }
    anchored_dirs = {"themes", "experimental_sandbox", "pre_upgrade_backups"}

    moved_count = 0
    mem_src = old_root / "memory.db"
    if mem_src.exists():
        mem_dst = target / "memory.db"
        try:
            from memory_service import SQLiteMemoryIndex
            SQLiteMemoryIndex(mem_src).backup_to_file(mem_dst)
        except Exception:
            shutil.copy2(mem_src, mem_dst)
        if mem_dst.is_file() and mem_dst.stat().st_size > 0:
            moved_count += 1

    for item in old_root.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(old_root)
        if rel.name.lower() in anchored_files:
            continue
        if rel.parts and rel.parts[0].lower() in anchored_dirs:
            continue
        dest_file = target / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest_file)
        moved_count += 1

    save_ui_settings({"custom_data_dir": str(target)}, config_path=config_path)
    if remove_source_after_copy:
        for sub in ("uploaded_files", "generated_images", "sessions", "idle_palace"):
            sp = old_root / sub
            if sp.is_dir():
                shutil.rmtree(sp, ignore_errors=True)
    return {"moved_files": moved_count, "old_root": str(old_root), "new_root": str(target)}


def move_experimental_data_to_directory(
    new_dir: str | Path,
    *,
    config_path: Path = CONFIG_PATH,
    remove_source_after_copy: bool = False,
) -> dict[str, Any]:
    """Move or copy Experimental Palace DB (ai_idle_memory.json, agent_mailbox.json, shared files)
    to a new folder/drive while leaving dev staging/source_mirror and anchored AppData credentials untouched.
    """
    import shutil
    target = Path(new_dir).resolve()
    if str(target.drive).upper().startswith("M:"):
        raise ValueError("M: drive is strictly off-limits.")
    old_root = get_experimental_data_root(config_path).resolve()
    if target == old_root:
        return {"moved_files": 0, "old_root": str(old_root), "new_root": str(target)}
    target.mkdir(parents=True, exist_ok=True)

    skip_dirs = {"staging", "source_mirror", "__pycache__", ".git"}
    moved_count = 0
    for item in old_root.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(old_root)
        if rel.parts and rel.parts[0].lower() in skip_dirs:
            continue
        if rel.name.lower() in {"credentials.json", "palace_config.json"}:
            continue
        dest_file = target / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest_file)
        moved_count += 1

    save_ui_settings({"custom_experimental_dir": str(target)}, config_path=config_path)
    if remove_source_after_copy:
        for sub in ("idle_palace", "mailbox", "files"):
            sp = old_root / sub
            if sp.is_dir():
                shutil.rmtree(sp, ignore_errors=True)
        for leaf in ("ai_idle_memory.json", "agent_mailbox.json"):
            lp = old_root / leaf
            if lp.is_file():
                try:
                    lp.unlink()
                except OSError:
                    pass
    return {"moved_files": moved_count, "old_root": str(old_root), "new_root": str(target)}


def _dir_size_bytes(directory: Path) -> int:
    if not directory.exists() or not directory.is_dir():
        return 0
    total = 0
    try:
        for f in directory.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def compute_palace_storage_stats(
    config_path: Path = CONFIG_PATH,
    data_root: Path | None = None,
    sandbox_root: Path | None = None,
) -> dict[str, Any]:
    """Compute live disk space breakdown and warning states for both Normal Mode and Experimental Mode."""
    root = Path(data_root) if data_root is not None else get_palace_data_root(config_path)
    eff_sandbox = Path(sandbox_root) if sandbox_root is not None else get_experimental_data_root(config_path)
    ui_cfg = load_ui_settings(config_path)
    idle_cfg = load_idle_settings(config_path)

    mem_bytes = 0
    for db_name in ("memory.db", "memory.db-wal", "memory.db-shm"):
        p = root / db_name
        if p.exists():
            try:
                mem_bytes += p.stat().st_size
            except OSError:
                pass

    sess_bytes = _dir_size_bytes(root / "sessions")
    for top_f in ("conversations.json", "session_context.jsonl", "memory_proposals.jsonl", "memory_promotions_audit.jsonl"):
        p = root / top_f
        if p.exists():
            try:
                sess_bytes += p.stat().st_size
            except OSError:
                pass

    up_bytes = _dir_size_bytes(root / "uploaded_files")
    img_bytes = _dir_size_bytes(root / "generated_images")
    normal_total = mem_bytes + sess_bytes + up_bytes + img_bytes

    idle_bytes = 0
    seen_dirs: set[Path] = set()
    for d in (root / "idle_palace", eff_sandbox / "idle_palace" / "files", eff_sandbox / "files"):
        try:
            res_d = d.resolve()
        except OSError:
            res_d = d
        if res_d not in seen_dirs:
            seen_dirs.add(res_d)
            idle_bytes += _dir_size_bytes(d)
    seen_files: set[Path] = set()
    for ip in (
        root / "ai_idle_memory.json",
        eff_sandbox / "ai_idle_memory.json",
        eff_sandbox / "idle_palace" / "ai_idle_memory.json",
        eff_sandbox / "mailbox" / "agent_mailbox.json",
    ):
        try:
            res_ip = ip.resolve()
        except OSError:
            res_ip = ip
        if res_ip not in seen_files and ip.exists():
            seen_files.add(res_ip)
            try:
                idle_bytes += ip.stat().st_size
            except OSError:
                pass

    normal_cap_mb = int(ui_cfg.get("normal_max_storage_mb", 0))
    idle_cap_mb = int(idle_cfg.get("max_storage_mb", 0))

    normal_cap_bytes = normal_cap_mb * 1024 * 1024 if normal_cap_mb > 0 else 0
    idle_cap_bytes = idle_cap_mb * 1024 * 1024 if idle_cap_mb > 0 else 0

    normal_pct = (normal_total / normal_cap_bytes * 100.0) if normal_cap_bytes > 0 else 0.0
    idle_pct = (idle_bytes / idle_cap_bytes * 100.0) if idle_cap_bytes > 0 else 0.0

    normal_state = "exceeded" if (normal_cap_bytes > 0 and normal_total >= normal_cap_bytes) else (
        "warning" if (normal_cap_bytes > 0 and normal_pct >= 85.0) else "ok"
    )
    idle_state = "exceeded" if (idle_cap_bytes > 0 and idle_bytes >= idle_cap_bytes) else (
        "warning" if (idle_cap_bytes > 0 and idle_pct >= 85.0) else "ok"
    )

    return {
        "data_root": str(root),
        "experimental_root": str(eff_sandbox),
        "memory_db_bytes": mem_bytes,
        "sessions_bytes": sess_bytes,
        "uploaded_files_bytes": up_bytes,
        "generated_images_bytes": img_bytes,
        "normal_total_bytes": normal_total,
        "normal_total_mb": round(normal_total / (1024 * 1024), 2),
        "normal_cap_mb": normal_cap_mb,
        "normal_pct": round(normal_pct, 1),
        "normal_state": normal_state,
        "idle_total_bytes": idle_bytes,
        "idle_total_mb": round(idle_bytes / (1024 * 1024), 2),
        "idle_cap_mb": idle_cap_mb,
        "idle_pct": round(idle_pct, 1),
        "idle_state": idle_state,
    }


def list_palace_stored_files(
    config_path: Path = CONFIG_PATH,
    data_root: Path | None = None,
    sandbox_root: Path | None = None,
) -> list[dict[str, Any]]:
    """List all user-accessible files stored in the Palace (Uploaded Files, Generated Images, and Idle Shared Files)."""
    from datetime import datetime
    root = Path(data_root) if data_root is not None else get_palace_data_root(config_path)
    eff_sandbox = Path(sandbox_root) if sandbox_root is not None else get_experimental_data_root(config_path)
    items: list[dict[str, Any]] = []
    sources = [
        ("Uploaded File", root / "uploaded_files"),
        ("Generated Picture", root / "generated_images"),
        ("Idle Shared File", root / "idle_palace" / "files"),
        ("Idle Shared File", eff_sandbox / "idle_palace" / "files"),
        ("Idle Shared File", eff_sandbox / "files"),
    ]
    seen_paths: set[str] = set()
    for category, folder in sources:
        if not folder.exists() or not folder.is_dir():
            continue
        try:
            for fp in folder.iterdir():
                if not fp.is_file():
                    continue
                resolved = str(fp.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                st = fp.stat()
                items.append({
                    "name": fp.name,
                    "category": category,
                    "path": resolved,
                    "size_bytes": st.st_size,
                    "size_kb": round(st.st_size / 1024.0, 1),
                    "mtime": st.st_mtime,
                    "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
        except OSError:
            continue
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def get_source_mirror_dir(config_path: Path = CONFIG_PATH) -> Path:
    """Return the configured Shared Source Code Mirror folder (or install/sandbox fallback)."""
    try:
        idle_cfg = load_idle_settings(config_path)
        custom = str(idle_cfg.get("source_mirror_dir") or "").strip()
        if custom and not custom.upper().startswith("M:"):
            return Path(custom)
    except Exception:
        pass
    exp_root = get_experimental_data_root(config_path)
    if (exp_root / "source_mirror").exists():
        return exp_root / "source_mirror"
    install_src = get_app_install_dir() / "source"
    if is_frozen_app() and install_src.exists():
        return install_src
    if IS_DEVELOPER_EDITION and IDLE_SANDBOX_ROOT.exists():
        return IDLE_SANDBOX_ROOT / "source_mirror"
    return get_palace_data_root(config_path) / "source_mirror"


def build_palace_source_context(
    question: str = "",
    *,
    force_include: bool = False,
    max_chars: int = 14_000,
) -> str:
    """Return a lightweight Source Code Reference Manifest + On-Demand Read Tool instructions (instead of dumping 14,000 chars of raw code)."""
    if not IS_DEVELOPER_EDITION:
        return ""
    q_lower = (question or "").lower()
    code_keywords = (
        "palace_gui", "idle_service", "orchestrator", "synthesizer",
        "provider_loader", "palace_config", "session_store", "credential_store",
        "palace code", "source code", "debug palace",
    )
    auto_triggered = any(k in q_lower for k in code_keywords)
    if not force_include and not auto_triggered:
        return ""

    mirror_dir = get_source_mirror_dir()
    install_src = get_app_install_dir() / "source"
    if mirror_dir.exists() and any(mirror_dir.glob("*.py")):
        src_dir = mirror_dir
    elif install_src.exists() and any(install_src.glob("*.py")):
        src_dir = install_src
    else:
        src_dir = Path(__file__).resolve().parent
    excluded = {"key.txt", "credentials.json", "palace_config.json"}
    try:
        py_files = sorted(
            p for p in src_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".py" and p.name.lower() not in excluded
        )
    except OSError:
        return ""

    if not py_files:
        return ""

    manifest = ", ".join(p.name for p in py_files[:35])
    matched = [p for p in py_files if p.name.lower() in q_lower or p.stem.lower() in q_lower]

    lines = [
        f"FAIRYBREAD SOURCE CODE REFERENCE (Read-Only Mirror at `{src_dir}`):",
        f"Available Python modules ({len(py_files)}): {manifest}",
        "ON-DEMAND SOURCE CODE TOOLS (Use these instead of full-file injection):",
        '- `[TOOL: list_source_files]` -> List all files in the source mirror',
        '- `[TOOL: search_source_code query="search_term"]` -> Search across all .py files for matching lines',
        '- `[TOOL: read_source_file file="palace_gui.py" start=1 end=80]` -> Read specific line range on demand',
        '- `[TOOL: inspect_palace_ui]` -> Run live PalaceWindow geometry & UI self-audit',
    ]
    for p in matched[:2]:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
            lines.append(f"\n--- REFERENCED MODULE HEADER ({p.name}, {len(txt.splitlines())} lines) ---\n{txt[:1800]}")
        except OSError:
            pass
    return "\n".join(lines)


DEFAULT_TOOL_SETTINGS: dict[str, bool] = {
    "palace_source_tool": True,
    "shared_palace_files_tool": True,
    "project_folder_tool": True,
    "owner_email_tool": True,
    "github_tool": False,
    "external_mail_tool": False,
}


def load_tool_settings(config_path: Path = CONFIG_PATH) -> dict[str, bool]:
    data = _read_raw_config(config_path)
    raw = data.get("tool_settings", {})
    if not isinstance(raw, dict):
        raw = {}
    merged = dict(DEFAULT_TOOL_SETTINGS)
    for k in DEFAULT_TOOL_SETTINGS:
        if k in raw:
            merged[k] = bool(raw[k])
    return merged


def save_tool_settings(
    tool_settings: dict[str, bool],
    config_path: Path = CONFIG_PATH,
) -> dict[str, bool]:
    data = _read_raw_config(config_path)
    current = load_tool_settings(config_path)
    for k, v in tool_settings.items():
        if k in DEFAULT_TOOL_SETTINGS:
            current[k] = bool(v)
    data["tool_settings"] = current
    _write_raw_config(data, config_path)
    return load_tool_settings(config_path)


def build_project_folder_context(
    folder_path: str,
    question: str = "",
    *,
    max_chars: int = 10_000,
) -> str:
    """Read-only workspace folder context for a Project with an attached folder (blocks M: drive)."""
    clean = (folder_path or "").strip()
    if not clean:
        return ""
    p = Path(clean)
    if p.drive.upper().startswith("M:"):
        return ""
    try:
        if not p.exists() or not p.is_dir():
            return ""
        files = sorted(
            f for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in {".py", ".md", ".txt", ".json", ".cs", ".cpp", ".h", ".js", ".ts"}
            and f.name.lower() not in {"key.txt", "credentials.json"}
        )
    except OSError:
        return ""

    if not files:
        return f"ATTACHED PROJECT FOLDER ({p}): No readable code/text files in root directory."

    q_lower = (question or "").lower()
    manifest = ", ".join(f.name for f in files[:35])
    out = [f"ATTACHED PROJECT WORKSPACE ({p}):\nFiles: {manifest}"]
    used = len(out[0])
    matched = [f for f in files if f.name.lower() in q_lower or f.stem.lower() in q_lower]
    for f in (matched or files[:2])[:3]:
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")[:3000]
            block = f"\n--- PROJECT FILE: {f.name} ---\n{txt}"
            if used + len(block) <= max_chars:
                out.append(block)
                used += len(block)
        except OSError:
            pass
    return "\n".join(out)


def restore_default_settings(
    config_path: Path = CONFIG_PATH,
    *,
    clear_write_exclusions: bool = False,
    unlink_external_bridges: bool = False,
    backup_dir: Path | None = None,
    bridge_home_dir: Path | None = None,
    bridge_appdata_dir: Path | None = None,
) -> dict[str, Any]:
    """Reset Fairybread app settings to factory defaults after saving an automatic backup snapshot.

    Always preserves Memory Palaces, conversations/projects, and DPAPI API keys, and preserves
    configured AI providers, custom data directory, Write Exclusions, and MCP bridge links unless
    explicitly requested otherwise.
    """
    from datetime import datetime
    import shutil

    existing = _read_raw_config(config_path)
    bak_root = Path(backup_dir) if backup_dir is not None else (get_palace_data_root(config_path) / "pre_upgrade_backups")
    bak_root.mkdir(parents=True, exist_ok=True)
    bak_path: Path | None = None
    if config_path.is_file():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak_path = bak_root / f"palace_config_before_reset_{stamp}.json"
        shutil.copy2(config_path, bak_path)

    old_ui = existing.get("ui_settings") if isinstance(existing.get("ui_settings"), dict) else {}
    kept_custom_dir = str(old_ui.get("custom_data_dir") or "").strip()
    kept_custom_exp_dir = str(old_ui.get("custom_experimental_dir") or "").strip()

    new_ui = dict(DEFAULT_UI_SETTINGS)
    if kept_custom_dir and not kept_custom_dir.upper().startswith("M:"):
        new_ui["custom_data_dir"] = kept_custom_dir
    if kept_custom_exp_dir and not kept_custom_exp_dir.upper().startswith("M:"):
        new_ui["custom_experimental_dir"] = kept_custom_exp_dir

    old_ap = existing.get("access_permissions") if isinstance(existing.get("access_permissions"), dict) else {}
    old_excl = old_ap.get("write_exclusions") if isinstance(old_ap.get("write_exclusions"), list) else []
    kept_exclusions = [] if clear_write_exclusions else json.loads(json.dumps(old_excl))

    from access_policy import DEFAULT_ACCESS_PERMISSIONS
    new_ap = {
        "permission_mode": str(DEFAULT_ACCESS_PERMISSIONS["permission_mode"]),
        "write_exclusions": kept_exclusions,
        "allow_workspace_writes": bool(DEFAULT_ACCESS_PERMISSIONS["allow_workspace_writes"]),
        "allow_shell_commands": bool(DEFAULT_ACCESS_PERMISSIONS["allow_shell_commands"]),
        "allow_self_patch": bool(DEFAULT_ACCESS_PERMISSIONS["allow_self_patch"]),
    }

    from voice_service import DEFAULT_VOICE_SETTINGS
    from email_service import DEFAULT_EMAIL_NOTIFICATION_SETTINGS
    from fairybread_mcp import (
        DEFAULT_BRIDGE_SETTINGS,
        EXTERNAL_PLATFORMS,
        unlink_platform_foreman,
    )

    new_email = dict(DEFAULT_EMAIL_NOTIFICATION_SETTINGS)
    old_email = existing.get("email_and_notifications") if isinstance(existing.get("email_and_notifications"), dict) else {}
    if isinstance(old_email.get("password_dpapi"), str) and old_email["password_dpapi"]:
        new_email["password_dpapi"] = old_email["password_dpapi"]

    unlinked_platforms: list[str] = []
    if unlink_external_bridges:
        for pk in EXTERNAL_PLATFORMS:
            ok, _msg = unlink_platform_foreman(
                pk,
                home_dir=bridge_home_dir,
                appdata_dir=bridge_appdata_dir,
            )
            if ok:
                unlinked_platforms.append(pk)
        new_bridge = json.loads(json.dumps(DEFAULT_BRIDGE_SETTINGS))
    else:
        old_bridge = existing.get("external_agent_bridge")
        new_bridge = (
            json.loads(json.dumps(old_bridge))
            if isinstance(old_bridge, dict)
            else json.loads(json.dumps(DEFAULT_BRIDGE_SETTINGS))
        )

    old_providers = existing.get("providers")
    kept_providers = json.loads(json.dumps(old_providers)) if isinstance(old_providers, dict) else {}

    reset_data: dict[str, Any] = {
        "providers": kept_providers,
        "ui_settings": new_ui,
        "agent_defaults": dict(DEFAULT_AGENT_DEFAULTS),
        "voice_settings": dict(DEFAULT_VOICE_SETTINGS),
        "graphics_settings": json.loads(json.dumps(DEFAULT_GRAPHICS_SETTINGS)),
        "ai_squads": json.loads(json.dumps(DEFAULT_AI_SQUADS)),
        "idle_settings": dict(DEFAULT_IDLE_SETTINGS),
        "tool_settings": dict(DEFAULT_TOOL_SETTINGS),
        "personalization_settings": dict(DEFAULT_PERSONALIZATION_SETTINGS),
        "mission_ethics": DEFAULT_MISSION_ETHICS,
        "email_and_notifications": new_email,
        "access_permissions": new_ap,
        "external_agent_bridge": new_bridge,
    }
    _write_raw_config(reset_data, config_path)
    return {
        "backup_path": str(bak_path) if bak_path else "",
        "preserved_exclusions": len(kept_exclusions),
        "cleared_exclusions": bool(clear_write_exclusions),
        "unlinked_bridges": unlinked_platforms,
    }

