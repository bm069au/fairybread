import json
import os
from pathlib import Path
from typing import Any


def _resolve_default_config_path() -> Path:
    local_cfg = Path(__file__).with_name("palace_config.json")
    s_path = str(local_cfg.resolve()).lower()
    if "program files" in s_path:
        appdata_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace"
        appdata_dir.mkdir(parents=True, exist_ok=True)
        user_cfg = appdata_dir / "palace_config.json"
        if not user_cfg.exists() and local_cfg.exists():
            try:
                user_cfg.write_text(local_cfg.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass
        return user_cfg
    return local_cfg


CONFIG_PATH = _resolve_default_config_path()

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
        "default_model": "gemini-2.5-flash",
        "suggested_models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "billing_note": "Free tier available via Google AI Studio, or pay-as-you-go via Google Cloud.",
    },
    "openai": {
        "display_name": "OpenAI (ChatGPT)",
        "icon": "●",
        "color": "#22c55e",       # Emerald Green
        "bg_color": "#11281b",
        "key_url": "https://platform.openai.com/api-keys",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "suggested_models": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
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
        "default_model": "deepseek-chat",
        "suggested_models": ["deepseek-chat", "deepseek-reasoner"],
        "billing_note": "Strict prepaid top-up balance ($2/$5/$10) — never auto-charges past your balance.",
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
        "default_model": "codestral-latest",
        "suggested_models": ["codestral-latest", "mistral-large-latest", "mistral-small-latest"],
        "billing_note": "Free Experiment tier available on La Plateforme, or prepaid/pay-as-you-go.",
    },
    "openrouter": {
        "display_name": "OpenRouter (All Models)",
        "icon": "⊕",
        "color": "#14b8a6",       # Teal Mint
        "bg_color": "#112a28",
        "key_url": "https://openrouter.ai/settings/keys",
        "default_base_url": "https://openrouter.ai/api/v1",
        "default_model": "qwen/qwen3-32b",
        "suggested_models": ["qwen/qwen3-32b", "anthropic/claude-3.7-sonnet", "deepseek/deepseek-r1", "google/gemini-2.5-pro"],
        "billing_note": "Strict prepaid credit wallet + optional per-key dollar cap. Over 300 models with one key.",
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
        "default_model": "llama-3.3-70b-versatile",
        "suggested_models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3.8-27b"],
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
    "qwen": (0.15, 1.88),
    "cohere": (0.00, 0.00),
    "mistral": (0.00, 0.00),
    "cerebras": (0.10, 0.10),
}

DEFAULT_PROVIDER_PROFILES: dict[str, str] = {
    "gemini": (
        "Strong at system architecture, coding, research, multimodal vision analysis, "
        "and native high-resolution photorealistic image rendering (gemini-3-pro-image / gemini-3.1-flash-image)."
    ),
    "openai": (
        "Strong at visual Prompt Architecture, graphics/layout composition, native high-resolution "
        "image rendering (gpt-image-2), general reasoning, and coding."
    ),
    "deepseek": (
        "Strong at deep software engineering, algorithms, math, logic, and rich photographic/visual "
        "Prompt Architecture (crafting detailed scene, lighting, anatomy, and camera-lens specifications)."
    ),
    "mistral": (
        "Codestral specialist: strong at code generation, syntax review, and refactoring; "
        "replies with [PASS] on pure artistic drawing tasks unless the user asks all agents to help."
    ),
    "groq": (
        "Fast free-tier reasoning, brainstorming, and critical review; "
        "contributes concise planning/edge-case notes."
    ),
    "qwen": (
        "Qwen3.8-27B (DeepInfra): Strong at analytical problem decomposition, mathematical logic, code architecture, and visual QA critique."
    ),
    "cohere": (
        "Strong at structured synthesis, summarization, and critique; "
        "replies with [PASS] on pure artistic drawing tasks unless the user asks all agents to help."
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


def format_democratic_roster(provider_names: list[str] | None = None) -> str:
    names = provider_names or list(DEFAULT_PROVIDER_PROFILES.keys())
    lines = []
    for name in names:
        clean = (name or "").strip().lower()
        desc = DEFAULT_PROVIDER_PROFILES.get(
            clean,
            "General peer agent in the democratic council."
        )
        lines.append(f"- {clean.upper()}: {desc}")
    return "\n".join(lines)


DEFAULT_IDLE_SETTINGS: dict[str, Any] = {
    "duration_minutes": 30,          # 30, 45, 60, 90, 180, or 0 (Infinite)
    "max_tokens_limit": 0,           # 0 = Rely on 30-minute timer (no hard token cap unless set > 0)
    "max_credit_usd": 0.0,           # 0.0 = Rely on 30-minute timer (no hard USD cap unless set > 0)
    "max_storage_mb": 0,             # 0 = Unlimited, or >= 100 MB (adjustable via slider/box)
    "idle_submode": "free_talk",     # "free_talk" (unprompted peer chat) | "self_improve" (Fairybread code & UI improvement)
    "share_source_code": False,      # Read-only Fairybread source code access in Experimental Mode
     # Owner-only: allow agents to stage/apply live patches, hot-reboot & auto-continue
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
    config_path: Path = CONFIG_PATH
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

    providers[normalized_name] = entry
    _write_raw_config(data, config_path)
    return load_provider_configs(config_path=config_path)


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
            c = Cerebras(api_key=key)
            discovered = [str(m.id) for m in c.models.list().data if getattr(m, "id", None)]
        elif clean == "gemini":
            from google import genai
            client = genai.Client(api_key=key)
            for m in client.models.list():
                mname = str(getattr(m, "name", "") or "").replace("models/", "")
                if mname and ("gemini" in mname or "imagen" in mname):
                    discovered.append(mname)
        elif clean == "cohere":
            import cohere
            client = cohere.ClientV2(api_key=key)
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


DEFAULT_AI_SQUADS: dict[str, dict[str, Any]] = {
    "code": {
        "label": "💻 Code AIs",
        "providers": ["deepseek", "mistral", "gemini"],
        "deliberate": True,
        "code_access": True,
        "max_ais": 0,
    },
    "light_chat": {
        "label": "💬 Light Chat (Cheap)",
        "providers": ["groq", "qwen", "cohere"],
        "deliberate": False,
        "code_access": False,
        "max_ais": 0,
    },
    "generalist": {
        "label": "🧠 Generalist",
        "providers": ["gemini", "openai", "deepseek", "cohere"],
        "deliberate": True,
        "code_access": False,
        "max_ais": 0,
    },
    "graphics": {
        "label": "🎨 Graphics & Vision (Pictures)",
        "providers": ["openai", "gemini"],
        "deliberate": False,
        "code_access": False,
        "max_ais": 0,
    },
    "work_mode": {
        "label": "🛠 Work Mode",
        "providers": ["deepseek", "mistral", "gemini", "openai"],
        "deliberate": True,
        "code_access": True,
        "max_ais": 0,
    },
}


def load_ai_squads(config_path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    data = _read_raw_config(config_path)
    raw = data.get("ai_squads")
    if not isinstance(raw, dict) or not raw:
        return {k: dict(v, providers=list(v.get("providers", []))) for k, v in DEFAULT_AI_SQUADS.items()}
    out: dict[str, dict[str, Any]] = {}
    for k, val in raw.items():
        if not isinstance(val, dict):
            continue
        slug = str(k).strip()
        if not slug:
            continue
        out[slug] = {
            "label": str(val.get("label") or slug).strip(),
            "providers": [str(p).strip().lower() for p in (val.get("providers") or []) if str(p).strip()],
            "deliberate": bool(val.get("deliberate", True)),
            "code_access": bool(val.get("code_access", False)),
            "max_ais": max(0, int(val.get("max_ais") or 0)),
        }
    return out or {k: dict(v, providers=list(v.get("providers", []))) for k, v in DEFAULT_AI_SQUADS.items()}


def save_ai_squads(
    squads: dict[str, dict[str, Any]],
    config_path: Path = CONFIG_PATH,
) -> dict[str, dict[str, Any]]:
    data = _read_raw_config(config_path)
    cleaned: dict[str, dict[str, Any]] = {}
    for k, val in (squads or {}).items():
        if not isinstance(val, dict):
            continue
        slug = str(k).strip()
        if not slug:
            continue
        cleaned[slug] = {
            "label": str(val.get("label") or slug).strip(),
            "providers": [str(p).strip().lower() for p in (val.get("providers") or []) if str(p).strip()],
            "deliberate": bool(val.get("deliberate", True)),
            "code_access": bool(val.get("code_access", False)),
            "max_ais": max(0, int(val.get("max_ais") or 0)),
        }
    data["ai_squads"] = cleaned or {k: dict(v) for k, v in DEFAULT_AI_SQUADS.items()}
    _write_raw_config(data, config_path)
    return load_ai_squads(config_path)

DEFAULT_UI_SETTINGS: dict[str, Any] = {
    "enter_to_send": True,  # True: Enter sends, Shift+Enter newline; False: Shift+Enter sends, Enter newline
    "include_palace_code": False,
    "badge_display_mode": "icons_only",  # "icons_only" | "icons_and_names" | "names_only"
    "theme": "dark",  # "dark" | "light" | "system" | "fairybread" | custom theme slug
    "normal_max_storage_mb": 0,  # 0 = Unlimited, or >= 100 MB (warns at 85% and 100%)
    "custom_data_dir": "",  # Empty = %LOCALAPPDATA%\Palace; or custom directory path on any drive
    "close_to_tray": True,  # True: window X button minimizes Fairybread to system tray
}


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
    current["close_to_tray"] = bool(current.get("close_to_tray", True))
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
    data["ui_settings"] = current
    _write_raw_config(data, config_path)
    return load_ui_settings(config_path)


DEFAULT_PERSONALIZATION_SETTINGS: dict[str, Any] = {
    "auto_evolve_profile": True,
    "base_style": "Friendly",           # "Friendly" | "Candid & Direct (No Flattery)" | "Technical & Concise" | "Casual & Witty" | "Professional"
    "warmth": "Default",                # "Less" | "Default" | "More"
    "enthusiasm": "Less",               # "Less" | "Default" | "More"
    "emoji": "Less",                    # "None" | "Less" | "Default" | "More"
    "visual_answers": "Default",        # "Less" | "Default" | "More"
    "headers_and_lists": "More",        # "Less" | "Default" | "More"
    "custom_instructions_general": "",
    "custom_instructions_coding": "",
    "reference_photo_face": "",
    "reference_photo_body": "",
}


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


def format_personalization_prompt_block(config_path: Path = CONFIG_PATH) -> str:
    """Compile the user's Tone, Formatting, Custom Instructions, and Reference Photo status into a compact prompt block."""
    p = load_personalization_settings(config_path)
    lines = [
        "[USER PERSONALIZATION & TONE PREFERENCES]:",
        f"- Base Style & Tone: {p.get('base_style', 'Friendly')} | Warmth: {p.get('warmth', 'Default')} | Enthusiasm: {p.get('enthusiasm', 'Less')}",
        f"- Formatting: Emoji={p.get('emoji', 'Less')} | Visual Answers={p.get('visual_answers', 'Default')} | Headers & Lists={p.get('headers_and_lists', 'More')}",
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
    """Resolve the active Palace data directory (custom drive/folder if set, otherwise %LOCALAPPDATA%\\Palace)."""
    try:
        ui = load_ui_settings(config_path)
        custom = str(ui.get("custom_data_dir") or "").strip()
        if custom and not custom.upper().startswith("M:"):
            p = Path(custom)
            p.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    default_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace"
    default_root.mkdir(parents=True, exist_ok=True)
    return default_root


def move_palace_data_to_directory(
    new_dir: str | Path,
    *,
    config_path: Path = CONFIG_PATH,
    remove_source_after_copy: bool = False,
) -> dict[str, Any]:
    """Move or copy all Palace Memory, Conversations, Uploaded Files, Generated Images, and Idle Palace to a new folder/drive."""
    import shutil
    target = Path(new_dir).resolve()
    if str(target.drive).upper().startswith("M:"):
        raise ValueError("M: drive is strictly off-limits.")
    old_root = get_palace_data_root(config_path).resolve()
    if target == old_root:
        return {"moved_files": 0, "new_root": str(target)}
    target.mkdir(parents=True, exist_ok=True)

    moved_count = 0
    # Copy SQLite memory.db safely using online backup API if present
    mem_src = old_root / "memory.db"
    if mem_src.exists():
        try:
            from memory_service import SQLiteMemoryIndex
            SQLiteMemoryIndex(mem_src).backup_to_file(target / "memory.db")
            moved_count += 1
        except Exception:
            shutil.copy2(mem_src, target / "memory.db")
            moved_count += 1

    for item in old_root.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(old_root)
        if rel.name in {"memory.db", "memory.db-wal", "memory.db-shm"}:
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
    sandbox_root: Path = IDLE_SANDBOX_ROOT,
) -> dict[str, Any]:
    """Compute live disk space breakdown and warning states for both Normal Mode and Idle Mode."""
    root = Path(data_root) if data_root is not None else get_palace_data_root(config_path)
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

    idle_bytes = _dir_size_bytes(root / "idle_palace") + _dir_size_bytes(Path(sandbox_root) / "files")
    for ip in (root / "ai_idle_memory.json", Path(sandbox_root) / "ai_idle_memory.json"):
        if ip.exists():
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
    sandbox_root: Path = IDLE_SANDBOX_ROOT,
) -> list[dict[str, Any]]:
    """List all user-accessible files stored in the Palace (Uploaded Files, Generated Images, and Idle Shared Files)."""
    from datetime import datetime
    root = Path(data_root) if data_root is not None else get_palace_data_root(config_path)
    items: list[dict[str, Any]] = []
    sources = [
        ("Uploaded File", root / "uploaded_files"),
        ("Generated Picture", root / "generated_images"),
        ("Idle Shared File", root / "idle_palace" / "files"),
        ("Idle Shared File", Path(sandbox_root) / "files"),
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


def build_palace_source_context(
    question: str = "",
    *,
    force_include: bool = False,
    max_chars: int = 14_000,
) -> str:
    """Return read-only Palace source code context for Normal Mode debugging & improvement discussions."""
    q_lower = (question or "").lower()
    code_keywords = (
        "palace_gui", "idle_service", "orchestrator", "synthesizer",
        "provider_loader", "palace_config", "session_store", "credential_store",
        "palace code", "source code", "debug palace", "this app",
    )
    auto_triggered = any(k in q_lower for k in code_keywords)
    if not force_include and not auto_triggered:
        return ""

    mirror_dir = IDLE_SANDBOX_ROOT / "source_mirror"
    src_dir = mirror_dir if mirror_dir.exists() else Path(__file__).resolve().parent
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

    manifest = ", ".join(p.name for p in py_files[:30])
    prioritized: list[Path] = []
    core_names = ["palace_gui.py", "orchestrator.py", "idle_service.py", "palace_config.py", "synthesizer.py"]
    for p in py_files:
        if p.name.lower() in q_lower or p.stem.lower() in q_lower:
            prioritized.append(p)
    for cname in core_names:
        for p in py_files:
            if p.name == cname and p not in prioritized:
                prioritized.append(p)

    excerpts: list[str] = [
        f"PALACE APPLICATION SOURCE CODE (Read-Only Mirror in {src_dir}):\n"
        f"Available Python modules: {manifest}"
    ]
    used = len(excerpts[0])
    for p in prioritized[:4]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        budget = max(1200, (max_chars - used) // 2)
        snippet = text[:budget]
        if len(text) > budget:
            snippet += f"\n... [truncated {len(text) - budget} chars of {p.name}]"
        block = f"\n--- FILE: {p.name} ---\n{snippet}"
        if used + len(block) > max_chars:
            break
        excerpts.append(block)
        used += len(block)

    return "\n".join(excerpts)


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
