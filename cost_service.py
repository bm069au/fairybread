"""Live Multi-Modal Conversation Cost Metering & Ledger Service for Fairybread.

Meters actual LLM token usage, neural TTS audio duration, speech-to-text audio duration,
and network image generations incrementally in real time, with per-session persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any, Callable

from palace_config import PROVIDER_TOKEN_RATES_PER_1M


# Per-model approximate (input_usd_per_1m, output_usd_per_1m) rates
MODEL_TOKEN_RATES_PER_1M: dict[str, tuple[float, float]] = {
    "gemini-4-neon": (0.50, 3.00),
    "gemini-4-hydrogen": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash-lite": (0.075, 0.30),
    "gemini-2.5-flash": (0.15, 0.60),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.2": (1.75, 14.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5": (1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-chat": (0.27, 1.10),
    "qwen/qwen3.8-27b": (0.15, 0.60),
    "qwen/": (0.15, 0.60),
    "codestral-latest": (0.30, 0.90),
    "gpt-oss-120b": (0.10, 0.10),
    "command-a-03-2025": (0.00, 0.00),
}

# Approximate per-minute audio & per-render image rates (USD)
TTS_COST_PER_MINUTE_USD: dict[str, float] = {
    "openai:gpt-4o-mini-tts": 0.015,
    "openai:tts-1": 0.015,
    "gemini:gemini-3.8-flash-lite-tts": 0.012,
    "gemini:gemini-3.8-flash-tts": 0.018,
    "gemini:gemini-2.5-flash-preview-tts": 0.015,
    "system:sapi5": 0.0,
}

# Approximate per-1,000-character neural TTS rates (USD) for char-billed providers
TTS_COST_PER_1K_CHARS_USD: dict[str, float] = {
    "groq:canopylabs/orpheus-v1-english": 0.022,
    "groq:orpheus": 0.022,
    "cartesia:sonic-latest": 0.045,
    "cartesia:sonic-3": 0.045,
    "cartesia:sonic-2": 0.045,
    "cartesia:sonic": 0.045,
    "elevenlabs:": 0.18,
    "deepgram:aura-2": 0.025,
    "deepgram:aura": 0.020,
}

STT_COST_PER_MINUTE_USD: dict[str, float] = {
    "groq:whisper-large-v3-turbo": 0.00067,
    "openai:whisper-1": 0.006,
    "gemini:gemini-4-hydrogen": 0.002,
    "gemini:gemini-2.5-flash": 0.002,
    "gemini:transcribe": 0.002,
}

IMAGE_COST_PER_RENDER_USD: dict[str, float] = {
    "gemini-3-pro-image": 0.06,
    "gemini-3.1-flash-image": 0.03,
    "gpt-image-2": 0.08,
    "flux-1-dev": 0.025,
}

_LISTENER_LOCK = threading.RLock()
_COST_LISTENERS: list[Callable[[dict[str, Any]], None]] = []


def estimate_tokens_from_text(text: str) -> int:
    clean = (text or "").strip()
    if not clean:
        return 0
    return max(1, (len(clean) + 3) // 4)


def _usage_attr_optional_int(obj: Any, *names: str) -> int | None:
    if obj is None:
        return None
    saw_zero = False
    for nm in names:
        val = obj.get(nm) if isinstance(obj, dict) else getattr(obj, nm, None)
        if val is not None:
            try:
                iv = int(val)
                if iv > 0:
                    return iv
                if iv == 0:
                    saw_zero = True
            except (TypeError, ValueError):
                continue
    return 0 if saw_zero else None


def _usage_attr_int(obj: Any, *names: str) -> int:
    val = _usage_attr_optional_int(obj, *names)
    return val if val is not None else 0


def extract_sdk_usage_tokens(
    response_obj: Any,
    *,
    prompt_text: str = "",
    output_text: str = "",
) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from OpenAI/Gemini/Groq/Mistral/Cerebras/Cohere responses."""
    in_tok = 0
    out_tok = 0

    if response_obj is not None:
        usage = (
            response_obj.get("usage")
            if isinstance(response_obj, dict)
            else getattr(response_obj, "usage", None)
        )
        if usage is None and not isinstance(response_obj, dict):
            usage = getattr(response_obj, "usage_metadata", None)
        if usage is None and not isinstance(response_obj, dict):
            meta = getattr(response_obj, "meta", None)
            if meta is not None:
                usage = getattr(meta, "tokens", None) or getattr(meta, "billed_units", None) or meta
        elif isinstance(response_obj, dict) and usage is None:
            usage = response_obj.get("usage_metadata")

        if usage is not None:
            in_tok = _usage_attr_int(
                usage,
                "input_tokens",
                "prompt_tokens",
                "prompt_token_count",
                "total_input_tokens",
            )
            out_tok = _usage_attr_int(
                usage,
                "output_tokens",
                "completion_tokens",
                "candidates_token_count",
                "response_token_count",
                "total_output_tokens",
            )

    if in_tok <= 0 and prompt_text:
        in_tok = estimate_tokens_from_text(prompt_text)
    if out_tok <= 0 and output_text:
        out_tok = estimate_tokens_from_text(output_text)
    return max(0, in_tok), max(0, out_tok)


def _lookup_model_rates(provider: str, model: str = "") -> tuple[float, float]:
    m_low = (model or "").strip().lower()
    if m_low:
        if m_low in MODEL_TOKEN_RATES_PER_1M:
            return MODEL_TOKEN_RATES_PER_1M[m_low]
        for key in sorted(MODEL_TOKEN_RATES_PER_1M.keys(), key=len, reverse=True):
            if m_low.startswith(key):
                return MODEL_TOKEN_RATES_PER_1M[key]
    p_low = (provider or "").strip().lower()
    return PROVIDER_TOKEN_RATES_PER_1M.get(p_low, (0.25, 1.00))


def estimate_llm_cost_usd(
    provider: str,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    in_rate, out_rate = _lookup_model_rates(provider, model)
    return (max(0, int(input_tokens)) * in_rate + max(0, int(output_tokens)) * out_rate) / 1_000_000.0


def estimate_tts_cost_usd(engine: str, duration_sec: float = 0.0, *, char_count: int = 0) -> float:
    dur = max(0.0, float(duration_sec or 0.0))
    chars = max(0, int(char_count or 0))
    if dur <= 0.0 and chars <= 0:
        return 0.0
    eng_low = (engine or "").strip().lower()
    if "system" in eng_low or "sapi" in eng_low or "kokoro" in eng_low:
        return 0.0

    for k in sorted(TTS_COST_PER_1K_CHARS_USD.keys(), key=len, reverse=True):
        if eng_low == k or eng_low.startswith(k):
            effective_chars = float(chars) if chars > 0 else (dur * 15.0)
            return (effective_chars / 1000.0) * TTS_COST_PER_1K_CHARS_USD[k]

    rate_per_min = 0.0
    for k, r in TTS_COST_PER_MINUTE_USD.items():
        if eng_low == k or eng_low.startswith(k):
            rate_per_min = r
            break
    else:
        if eng_low.startswith("gemini:"):
            rate_per_min = 0.012
        elif eng_low.startswith("openai:"):
            rate_per_min = 0.015
    eff_dur = dur if dur > 0.0 else (chars / 15.0)
    return (eff_dur / 60.0) * rate_per_min


def estimate_stt_cost_usd(engine: str, duration_sec: float) -> float:
    dur = max(0.0, float(duration_sec or 0.0))
    if dur <= 0.0:
        return 0.0
    eng_low = (engine or "").strip().lower()
    rate_per_min = STT_COST_PER_MINUTE_USD.get(eng_low)
    if rate_per_min is None:
        if eng_low.startswith("groq:"):
            rate_per_min = 0.00067
        elif eng_low.startswith("openai:"):
            rate_per_min = 0.006
        elif eng_low.startswith("gemini:"):
            rate_per_min = 0.002
        else:
            rate_per_min = 0.002
    return (dur / 60.0) * rate_per_min


def estimate_image_cost_usd(engine: str) -> float:
    eng_low = (engine or "").strip().lower()
    for k, r in IMAGE_COST_PER_RENDER_USD.items():
        if eng_low == k or k in eng_low:
            return r
    return 0.04


def format_usd_compact(amount: float) -> str:
    val = max(0.0, float(amount or 0.0))
    if val == 0.0:
        return "~$0.000"
    if val < 0.01:
        return f"~${val:.4f}"
    if val < 1.0:
        return f"~${val:.3f}"
    return f"~${val:.2f}"


def register_cost_listener(callback: Callable[[dict[str, Any]], None]) -> None:
    if callback is None:
        return
    with _LISTENER_LOCK:
        if callback not in _COST_LISTENERS:
            _COST_LISTENERS.append(callback)


def unregister_cost_listener(callback: Callable[[dict[str, Any]], None]) -> None:
    if callback is None:
        return
    with _LISTENER_LOCK:
        if callback in _COST_LISTENERS:
            _COST_LISTENERS.remove(callback)


def emit_cost_event(event: dict[str, Any]) -> None:
    if not isinstance(event, dict):
        return
    with _LISTENER_LOCK:
        listeners = list(_COST_LISTENERS)
    for cb in listeners:
        try:
            cb(dict(event))
        except Exception:
            pass


def emit_llm_cost(
    provider: str,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    *,
    prompt_text: str = "",
    output_text: str = "",
    source: str = "chat",
) -> float:
    in_tok = int(input_tokens or 0) or estimate_tokens_from_text(prompt_text)
    out_tok = int(output_tokens or 0) or estimate_tokens_from_text(output_text)
    cost = estimate_llm_cost_usd(provider, model, in_tok, out_tok)
    if in_tok > 0 or out_tok > 0 or cost > 0.0:
        emit_cost_event({
            "kind": "llm",
            "provider": (provider or "llm").strip().lower(),
            "model": (model or "").strip(),
            "source": source,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": cost,
        })
    return cost


def emit_tts_cost(engine: str, duration_sec: float = 0.0, *, char_count: int = 0) -> float:
    dur = max(0.0, float(duration_sec or 0.0))
    chars = max(0, int(char_count or 0))
    cost = estimate_tts_cost_usd(engine, dur, char_count=chars)
    if dur > 0.0 or chars > 0:
        emit_cost_event({
            "kind": "tts",
            "provider": (engine or "tts").split(":", 1)[0].strip().lower(),
            "model": engine,
            "duration_sec": dur,
            "char_count": chars,
            "cost_usd": cost,
        })
    return cost


def emit_stt_cost(engine: str, duration_sec: float) -> float:
    dur = max(0.0, float(duration_sec or 0.0))
    cost = estimate_stt_cost_usd(engine, dur)
    if dur > 0.0:
        emit_cost_event({
            "kind": "stt",
            "provider": (engine or "stt").split(":", 1)[0].strip().lower(),
            "model": engine,
            "duration_sec": dur,
            "cost_usd": cost,
        })
    return cost


def emit_image_cost(engine: str) -> float:
    cost = estimate_image_cost_usd(engine)
    prov = "gemini" if "gemini" in (engine or "").lower() else ("openai" if "gpt" in (engine or "").lower() else "image")
    emit_cost_event({
        "kind": "image",
        "provider": prov,
        "model": engine,
        "cost_usd": cost,
    })
    return cost


@dataclass
class ConversationCostLedger:
    input_tokens: int = 0
    output_tokens: int = 0
    llm_cost_usd: float = 0.0
    voice_tts_cost_usd: float = 0.0
    voice_tts_seconds: float = 0.0
    voice_stt_cost_usd: float = 0.0
    voice_stt_seconds: float = 0.0
    image_cost_usd: float = 0.0
    image_count: int = 0
    last_event_cost_usd: float = 0.0
    last_event_label: str = ""
    by_provider: dict[str, float] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return max(0, int(self.input_tokens) + int(self.output_tokens))

    @property
    def total_cost_usd(self) -> float:
        return (
            float(self.llm_cost_usd)
            + float(self.voice_tts_cost_usd)
            + float(self.voice_stt_cost_usd)
            + float(self.image_cost_usd)
        )

    def record(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        kind = str(event.get("kind") or "llm").lower()
        cost = max(0.0, float(event.get("cost_usd", 0.0) or 0.0))
        prov = str(event.get("provider") or "other").strip().lower() or "other"

        if kind == "llm":
            self.input_tokens += max(0, int(event.get("input_tokens", 0) or 0))
            self.output_tokens += max(0, int(event.get("output_tokens", 0) or 0))
            self.llm_cost_usd += cost
            self.last_event_label = f"LLM ({prov})"
        elif kind == "tts":
            self.voice_tts_seconds += max(0.0, float(event.get("duration_sec", 0.0) or 0.0))
            self.voice_tts_cost_usd += cost
            self.last_event_label = f"Voice TTS ({prov})"
        elif kind == "stt":
            self.voice_stt_seconds += max(0.0, float(event.get("duration_sec", 0.0) or 0.0))
            self.voice_stt_cost_usd += cost
            self.last_event_label = f"Voice Mic ({prov})"
        elif kind == "image":
            self.image_count += 1
            self.image_cost_usd += cost
            self.last_event_label = f"Image ({event.get('model') or prov})"

        self.last_event_cost_usd = cost
        if cost > 0.0 or prov in self.by_provider:
            self.by_provider[prov] = round(self.by_provider.get(prov, 0.0) + cost, 8)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": int(self.input_tokens),
            "output_tokens": int(self.output_tokens),
            "llm_cost_usd": round(float(self.llm_cost_usd), 8),
            "voice_tts_cost_usd": round(float(self.voice_tts_cost_usd), 8),
            "voice_tts_seconds": round(float(self.voice_tts_seconds), 3),
            "voice_stt_cost_usd": round(float(self.voice_stt_cost_usd), 8),
            "voice_stt_seconds": round(float(self.voice_stt_seconds), 3),
            "image_cost_usd": round(float(self.image_cost_usd), 8),
            "image_count": int(self.image_count),
            "last_event_cost_usd": round(float(self.last_event_cost_usd), 8),
            "last_event_label": str(self.last_event_label),
            "by_provider": dict(self.by_provider),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ConversationCostLedger:
        if not isinstance(raw, dict):
            return cls()
        by_p = raw.get("by_provider")
        clean_bp = {
            str(k): max(0.0, float(v or 0.0))
            for k, v in (by_p.items() if isinstance(by_p, dict) else [])
        }
        return cls(
            input_tokens=max(0, int(raw.get("input_tokens", 0) or 0)),
            output_tokens=max(0, int(raw.get("output_tokens", 0) or 0)),
            llm_cost_usd=max(0.0, float(raw.get("llm_cost_usd", 0.0) or 0.0)),
            voice_tts_cost_usd=max(0.0, float(raw.get("voice_tts_cost_usd", 0.0) or 0.0)),
            voice_tts_seconds=max(0.0, float(raw.get("voice_tts_seconds", 0.0) or 0.0)),
            voice_stt_cost_usd=max(0.0, float(raw.get("voice_stt_cost_usd", 0.0) or 0.0)),
            voice_stt_seconds=max(0.0, float(raw.get("voice_stt_seconds", 0.0) or 0.0)),
            image_cost_usd=max(0.0, float(raw.get("image_cost_usd", 0.0) or 0.0)),
            image_count=max(0, int(raw.get("image_count", 0) or 0)),
            last_event_cost_usd=max(0.0, float(raw.get("last_event_cost_usd", 0.0) or 0.0)),
            last_event_label=str(raw.get("last_event_label", "") or ""),
            by_provider=clean_bp,
        )

    def format_bottom_bar(self) -> str:
        tot = self.total_tokens
        tok_str = f"{tot / 1000.0:.1f}k" if (tot == 0 or tot >= 1000) else f"{tot}"
        return f"Tokens: {tok_str} · Conv: {format_usd_compact(self.total_cost_usd)}"

    def format_tooltip(self) -> str:
        voice_total = self.voice_tts_cost_usd + self.voice_stt_cost_usd
        lines = [
            "Live Conversation Cost Estimate (API Usage):",
            f"• Total Estimated Cost: {format_usd_compact(self.total_cost_usd)} USD",
            f"• Chat & Voice LLMs: {format_usd_compact(self.llm_cost_usd)} ({self.input_tokens:,} in / {self.output_tokens:,} out tokens)",
            f"• Voice Audio: {format_usd_compact(voice_total)} (TTS {self.voice_tts_seconds:.1f}s · Mic {self.voice_stt_seconds:.1f}s)",
            f"• Images: {format_usd_compact(self.image_cost_usd)} ({self.image_count} render(s))",
        ]
        if self.last_event_label:
            lines.append(f"• Last Step: {self.last_event_label} ({format_usd_compact(self.last_event_cost_usd)})")
        if self.by_provider:
            top_p = sorted(self.by_provider.items(), key=lambda kv: kv[1], reverse=True)[:5]
            lines.append("• By Provider: " + ", ".join(f"{k} {format_usd_compact(v)}" for k, v in top_p))
        lines.append("Note: Estimated from real API token/audio/image counts and model rate table.")
        return "\n".join(lines)
