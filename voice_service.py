"""Live Voice Mode, Microphone Dictation (QAudioSource PCM), Streaming Human Neural TTS & Transcriber for Fairybread."""
from __future__ import annotations

from array import array
import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.request
import wave

from credential_store import CredentialStore
from palace_config import CONFIG_PATH, _read_raw_config, _write_raw_config, get_palace_data_root


TTS_ENGINES: list[tuple[str, str]] = [
    ("auto", "Auto — Best Ready Voice (OpenAI → Gemini → Groq → System)"),
    ("openai", "OpenAI Neural (gpt-4o-mini-tts · ~$0.015/min)"),
    ("gemini", "Gemini Neural (gemini-3.8-flash-lite-tts · ~$0.012/min)"),
    ("groq", "Groq Orpheus (orpheus-v1-english · ~$0.02/min)"),
    ("openrouter", "OpenRouter Audio (gpt-audio-mini · Neural Voices)"),
    ("cartesia", "Cartesia Sonic (~$0.045/1k chars · ~50ms streaming)"),
    ("elevenlabs", "ElevenLabs (~$0.18/1k chars · Studio / Cloning)"),
    ("deepgram", "Deepgram Flux / Aura-2 (~$0.025–$0.03/1k chars · Low-Latency)"),
    ("system", "Windows System Offline (SAPI 5 · Free)"),
]

TTS_ENGINE_SHORT_LABELS: dict[str, str] = {
    "auto": "Auto",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "groq": "Groq Orpheus",
    "openrouter": "OpenRouter Audio",
    "cartesia": "Cartesia Sonic",
    "elevenlabs": "ElevenLabs",
    "deepgram": "Deepgram Flux / Aura-2",
    "system": "Windows Offline",
}

TTS_EXTERNAL_KEY_META: dict[str, dict[str, Any]] = {
    "cartesia": {
        "cred_key": "cartesia",
        "display_name": "Cartesia Sonic",
        "key_url": "https://play.cartesia.ai/keys",
        "billing_url": "https://play.cartesia.ai",
        "key_prefix_hint": "sk_car_...",
        "rate_hint": "~$0.045 / 1k chars · ~50ms Sonic streaming",
        "pricing_summary": "Free: $0/mo (20,000 credits ≈ ~25 min, no card) · Pro: $5/mo (100,000 credits ≈ ~2 hrs, card) · Startup: $49/mo (~1.25M credits)",
        "blurb": "Cartesia Sonic uses its own Sonic API key at play.cartesia.ai (do NOT sign up for Voice Agents / Line).",
        "setup_steps": [
            "Open play.cartesia.ai/keys directly (skip the cartesia.ai marketing homepage).",
            "Sign in or create a Free account — includes 20,000 credits/month (~25 min of Sonic speech, no card needed to test).",
            "IGNORE any prompt for 'Voice Agents' or 'Line' — that is a separate per-minute phone-agent service (Fairybread already provides the AI brain).",
            "Go to API Keys → New API Key → create a Standard API Key (starts with sk_car_..., NOT an Admin key sk_car_admin_...), copy it once, and paste it below.",
            "When you want more than Free: open Subscription / Billing at play.cartesia.ai → pick Pro ($5/mo by credit/debit card) → leave Overages OFF for a hard monthly cap (zero surprise bills).",
        ],
    },
    "elevenlabs": {
        "cred_key": "elevenlabs",
        "display_name": "ElevenLabs",
        "key_url": "https://elevenlabs.io/app/settings/api-keys",
        "billing_url": "https://elevenlabs.io/app/subscription",
        "key_prefix_hint": "sk_... (xi-api-key)",
        "rate_hint": "~$0.18 / 1k chars · Studio quality & voice cloning",
        "pricing_summary": "Free: 10,000 chars/mo · Starter: $5/mo (30,000 chars) · Creator: $22/mo (100,000 chars)",
        "blurb": "ElevenLabs requires an ElevenLabs API key (~$0.18/1k chars; ~10k–30k free/starter chars). Paste it below or revert to a ready voice.",
        "setup_steps": [
            "Open elevenlabs.io/app/settings/api-keys and sign in.",
            "Create a new API Key (for live remaining-character balance readout in Fairybread, keep Subscription/User read access enabled).",
            "Free gives 10,000 chars/month; paid Starter ($5/mo) and Creator ($22/mo) use monthly subscription plans billed by card.",
        ],
    },
    "deepgram": {
        "cred_key": "deepgram",
        "display_name": "Deepgram Flux / Aura-2",
        "key_url": "https://console.deepgram.com/",
        "billing_url": "https://console.deepgram.com/",
        "key_prefix_hint": "Deepgram Token",
        "rate_hint": "~$0.025–$0.03 / 1k chars · Flux + Aura-2 voices",
        "pricing_summary": "Free Starter: $200 welcome credit (no expiry catch on signup promo) · Pay-as-you-go: ~$0.025–$0.03 / 1k chars via card",
        "blurb": "Deepgram requires a Deepgram API key (~$0.025–$0.03/1k chars). Paste it below to unlock all 89 English Flux & Aura voices.",
        "setup_steps": [
            "Open console.deepgram.com and select your project.",
            "Go to Settings → API Keys → Create a New API Key (choose Member or Owner role if you want Fairybread to display live USD balance).",
            "New accounts receive $200 free starter credit; Pay-as-you-go top-ups & cards are managed under Billing in the Deepgram Console.",
        ],
    },
}

OPENAI_TTS_VOICES: list[tuple[str, str]] = [
    ("coral", "Coral — Warm, Natural Female (Default)"),
    ("ash", "Ash — Warm, Grounded Male"),
    ("sage", "Sage — Calm, Clear Female"),
    ("ballad", "Ballad — Expressive, Warm Male"),
    ("verse", "Verse — Conversational Male"),
    ("nova", "Nova — Friendly, Bright Female"),
    ("onyx", "Onyx — Deep, Steady Male"),
    ("marin", "Marin — Natural, Friendly"),
    ("cedar", "Cedar — Warm, Steady"),
    ("alloy", "Alloy — Balanced Neutral"),
    ("shimmer", "Shimmer — Soft, Gentle Female"),
]

GEMINI_TTS_VOICES: list[tuple[str, str]] = [
    ("Kore", "Kore — Warm, Clear Female (Default)"),
    ("Puck", "Puck — Friendly, Conversational Male"),
    ("Aoede", "Aoede — Warm, Expressive Female"),
    ("Charon", "Charon — Deep, Calm Male"),
    ("Fenrir", "Fenrir — Confident Male"),
    ("Zephyr", "Zephyr — Bright, Natural Female"),
    ("Leda", "Leda — Soft, Relaxed Female"),
    ("Orus", "Orus — Steady, Clear Male"),
]

GROQ_ORPHEUS_VOICES: list[tuple[str, str]] = [
    ("autumn", "Autumn — Warm Conversational Female"),
    ("diana", "Diana — Clear Natural Female"),
    ("hannah", "Hannah — Friendly Expressive Female"),
    ("austin", "Austin — Natural Conversational Male"),
    ("daniel", "Daniel — Deep Steady Male"),
    ("troy", "Troy — Crisp Upbeat Male"),
]

CARTESIA_TTS_VOICES: list[tuple[str, str]] = [
    ("db6b0ed5-d5d3-463d-ae85-518a07d3c2b4", "Skylar — Friendly American Female (Default)"),
    ("47c38ca4-5f35-497b-b1a3-415245fb35e1", "Daniel — Crisp American Male"),
    ("86faee7e-bf54-4293-bd90-076138544609", "Paige — Calm Articulate American Female"),
    ("30894953-bcce-41fe-892c-15ce19c843ff", "Parker — Casual Conversational American"),
    ("694f9389-aac1-45b6-b726-9d9369183238", "Sarah — Warm Steady Female"),
    ("12e85709-099c-480a-ba3e-875c41a9611a", "Arlo — Friendly Australian Male"),
    ("62ae83ad-4f6a-430b-af41-a9bede9286ca", "Gemma — Crisp British Female"),
    ("ef191366-f52f-447a-a398-ed8c0f2943a1", "Archie — Warm British Male"),
]
_RETIRED_CARTESIA_VOICE_IDS: set[str] = {
    "a0e99841-438c-4a64-b679-ae501e7d6091",
    "79a125e8-cd45-4c13-8a67-188112f4dd22",
    "b7d50908-b17c-442d-ad8d-810c63997ed9",
    "41534e16-2966-4c6b-9670-111411def906",
    "c2ac25f9-ecc4-4f56-9095-651354df60c0",
}
CARTESIA_SAMPLE_RATE = 44100

ELEVENLABS_TTS_VOICES: list[tuple[str, str]] = [
    ("21m00Tcm4TlvDq8ikWAM", "Rachel — Calm, Warm Female (Default)"),
    ("EXAVITQu4vr4xnSDxMaL", "Bella — Soft, Natural Female"),
    ("ErXwobaYiN019PkySvjV", "Antoni — Warm Conversational Male"),
    ("TxGEqnHWrfWFTfGW9XjX", "Josh — Deep Everyday Male"),
    ("pNInz6obpgDQGcFmaJgB", "Adam — Clear Studio Narrator"),
    ("XB0fDUnXU5powFXDhCwa", "Charlotte — Smooth Poised Female"),
]

DEEPGRAM_TTS_VOICES: list[tuple[str, str]] = [
    # Deepgram Flux (v2/speak — 36 English voices with speed + expressivity)
    ("flux-sienna-en", "Sienna [Flux] — American Female (Clear, Warm, Calm) (Default)"),
    ("flux-alexis-en", "Alexis [Flux] — American Female (Clear, Calm, Caring)"),
    ("flux-bree-en", "Bree [Flux] — American Female (Friendly, Sweet, Kind)"),
    ("flux-brittany-en", "Brittany [Flux] — American Female (Confident, Kind, Soft)"),
    ("flux-brooke-en", "Brooke [Flux] — American Female (Friendly, Confident, Energetic)"),
    ("flux-bruce-en", "Bruce [Flux] — American Male (Friendly, Natural, Engaged)"),
    ("flux-cliff-en", "Cliff [Flux] — American Male (Deep, Confident, Calm)"),
    ("flux-cole-en", "Cole [Flux] — American Male (Friendly, Clear, Engaging)"),
    ("flux-colin-en", "Colin [Flux] — British Male (Warm, Friendly, Trustworthy)"),
    ("flux-conor-en", "Conor [Flux] — Irish Male (Confident, Deep, Relaxed)"),
    ("flux-donovan-en", "Donovan [Flux] — American Male (Professional, Calm, Thoughtful)"),
    ("flux-drew-en", "Drew [Flux] — American Male (Confident, Relaxed, Soft)"),
    ("flux-elise-en", "Elise [Flux] — American Female (Clear, Calm, Empathetic)"),
    ("flux-gemma-en", "Gemma [Flux] — British Female (Friendly, Approachable, Warm)"),
    ("flux-haley-en", "Haley [Flux] — American Female (Clear, Caring, Calm)"),
    ("flux-hannah-en", "Hannah [Flux] — American Female (Clear, Confident, Pleasant)"),
    ("flux-heather-en", "Heather [Flux] — American Female (Clear, Engaging, Friendly)"),
    ("flux-jack-en", "Jack [Flux] — British Male (Confident, Thoughtful, Friendly)"),
    ("flux-kai-en", "Kai [Flux] — Singaporean Male (Clear, Calm, Professional)"),
    ("flux-kelsey-en", "Kelsey [Flux] — American Female (Clear, Caring, Calm)"),
    ("flux-kit-en", "Kit [Flux] — British Male (Friendly, Energetic, Thoughtful)"),
    ("flux-maeve-en", "Maeve [Flux] — Irish Female (Friendly, Confident, Gentle)"),
    ("flux-marcelo-en", "Marcelo [Flux] — Filipino Male (Clear, Calm, Professional)"),
    ("flux-marcus-en", "Marcus [Flux] — American Male (Friendly, Smooth, Helpful)"),
    ("flux-meena-en", "Meena [Flux] — Indian Female (Empathetic, Calm, Reassuring)"),
    ("flux-meghan-en", "Meghan [Flux] — American Female (Friendly, Energetic, Kind)"),
    ("flux-miles-en", "Miles [Flux] — American Male (Clear, Calm, Sincere)"),
    ("flux-naveen-en", "Naveen [Flux] — Indian Male (Clear, Calm, Professional)"),
    ("flux-paige-en", "Paige [Flux] — American Female (Clear, Calm, Comfortable)"),
    ("flux-priya-en", "Priya [Flux] — Indian Female (Confident, Empathetic, Calm)"),
    ("flux-rufus-en", "Rufus [Flux] — British Male (Friendly, Confident, Gentle)"),
    ("flux-sean-en", "Sean [Flux] — British Male (Friendly, Kind, Calming)"),
    ("flux-sharon-en", "Sharon [Flux] — Australian Female (Calm, Relaxed, Confident)"),
    ("flux-tanner-en", "Tanner [Flux] — British Male (Professional, Calm, Confident)"),
    ("flux-wade-en", "Wade [Flux] — American Male (Warm, Confident, Friendly)"),
    ("flux-wes-en", "Wes [Flux] — American Male (Thoughtful, Friendly, Warm)"),
    # Deepgram Aura-2 (v1/speak — 41 English voices)
    ("aura-2-thalia-en", "Thalia [Aura-2] — American Female (Clear, Confident, Energetic)"),
    ("aura-2-hyperion-en", "Hyperion [Aura-2] — Australian Male (Warm, Caring, Empathetic)"),
    ("aura-2-theia-en", "Theia [Aura-2] — Australian Female (Expressive, Polite, Sincere)"),
    ("aura-2-amalthea-en", "Amalthea [Aura-2] — Filipino Female (Engaging, Natural, Cheerful)"),
    ("aura-2-andromeda-en", "Andromeda [Aura-2] — American Female (Casual, Expressive, Comfortable)"),
    ("aura-2-apollo-en", "Apollo [Aura-2] — American Male (Confident, Comfortable, Casual)"),
    ("aura-2-arcas-en", "Arcas [Aura-2] — American Male (Natural, Smooth, Clear)"),
    ("aura-2-aries-en", "Aries [Aura-2] — American Male (Warm, Energetic, Caring)"),
    ("aura-2-asteria-en", "Asteria [Aura-2] — American Female (Clear, Confident, Knowledgeable)"),
    ("aura-2-athena-en", "Athena [Aura-2] — American Female (Calm, Smooth, Professional)"),
    ("aura-2-atlas-en", "Atlas [Aura-2] — American Male (Enthusiastic, Confident, Friendly)"),
    ("aura-2-aurora-en", "Aurora [Aura-2] — American Female (Cheerful, Expressive, Energetic)"),
    ("aura-2-callista-en", "Callista [Aura-2] — American Female (Clear, Energetic, Smooth)"),
    ("aura-2-cora-en", "Cora [Aura-2] — American Female (Smooth, Melodic, Caring)"),
    ("aura-2-cordelia-en", "Cordelia [Aura-2] — American Female (Approachable, Warm, Polite)"),
    ("aura-2-delia-en", "Delia [Aura-2] — American Female (Casual, Friendly, Cheerful)"),
    ("aura-2-draco-en", "Draco [Aura-2] — British Male (Warm, Trustworthy, Baritone)"),
    ("aura-2-electra-en", "Electra [Aura-2] — American Female (Professional, Engaging, Knowledgeable)"),
    ("aura-2-harmonia-en", "Harmonia [Aura-2] — American Female (Empathetic, Clear, Calm)"),
    ("aura-2-helena-en", "Helena [Aura-2] — American Female (Caring, Natural, Friendly)"),
    ("aura-2-hera-en", "Hera [Aura-2] — American Female (Smooth, Warm, Professional)"),
    ("aura-2-hermes-en", "Hermes [Aura-2] — American Male (Expressive, Engaging, Professional)"),
    ("aura-2-iris-en", "Iris [Aura-2] — American Female (Cheerful, Positive, Approachable)"),
    ("aura-2-janus-en", "Janus [Aura-2] — American Female (Southern, Smooth, Trustworthy)"),
    ("aura-2-juno-en", "Juno [Aura-2] — American Female (Natural, Engaging, Melodic)"),
    ("aura-2-jupiter-en", "Jupiter [Aura-2] — American Male (Expressive, Knowledgeable, Baritone)"),
    ("aura-2-luna-en", "Luna [Aura-2] — American Female (Friendly, Natural, Engaging)"),
    ("aura-2-mars-en", "Mars [Aura-2] — American Male (Smooth, Patient, Baritone)"),
    ("aura-2-minerva-en", "Minerva [Aura-2] — American Female (Positive, Friendly, Natural)"),
    ("aura-2-neptune-en", "Neptune [Aura-2] — American Male (Professional, Patient, Polite)"),
    ("aura-2-odysseus-en", "Odysseus [Aura-2] — American Male (Calm, Smooth, Professional)"),
    ("aura-2-ophelia-en", "Ophelia [Aura-2] — American Female (Expressive, Enthusiastic, Cheerful)"),
    ("aura-2-orion-en", "Orion [Aura-2] — American Male (Approachable, Comfortable, Calm)"),
    ("aura-2-orpheus-en", "Orpheus [Aura-2] — American Male (Professional, Clear, Confident)"),
    ("aura-2-pandora-en", "Pandora [Aura-2] — British Female (Smooth, Calm, Melodic)"),
    ("aura-2-phoebe-en", "Phoebe [Aura-2] — American Female (Energetic, Warm, Casual)"),
    ("aura-2-pluto-en", "Pluto [Aura-2] — American Male (Smooth, Calm, Baritone)"),
    ("aura-2-saturn-en", "Saturn [Aura-2] — American Male (Knowledgeable, Confident, Baritone)"),
    ("aura-2-selene-en", "Selene [Aura-2] — American Female (Expressive, Engaging, Energetic)"),
    ("aura-2-vesta-en", "Vesta [Aura-2] — American Female (Natural, Expressive, Empathetic)"),
    ("aura-2-zeus-en", "Zeus [Aura-2] — American Male (Deep, Trustworthy, Smooth)"),
    # Deepgram Aura-1 (v1/speak — 12 English voices)
    ("aura-angus-en", "Angus [Aura-1] — Irish Male (Casual, Friendly, Patient)"),
    ("aura-arcas-en", "Arcas [Aura-1] — American Male (Natural, Smooth, Clear)"),
    ("aura-asteria-en", "Asteria [Aura-1] — American Female (Clear, Confident, Knowledgeable)"),
    ("aura-athena-en", "Athena [Aura-1] — British Female (Smooth, Calm, Professional)"),
    ("aura-helios-en", "Helios [Aura-1] — British Male (Comfortable, Polite, Positive)"),
    ("aura-hera-en", "Hera [Aura-1] — American Female (Deep, Smooth, Warm)"),
    ("aura-luna-en", "Luna [Aura-1] — American Female (Friendly, Natural, Engaging)"),
    ("aura-orion-en", "Orion [Aura-1] — American Male (Approachable, Comfortable, Calm)"),
    ("aura-orpheus-en", "Orpheus [Aura-1] — American Male (Clear, Trustworthy, Professional)"),
    ("aura-perseus-en", "Perseus [Aura-1] — American Male (Expressive, Melodic, Charismatic)"),
    ("aura-stella-en", "Stella [Aura-1] — American Female (Engaging, Cheerful, Raspy)"),
    ("aura-zeus-en", "Zeus [Aura-1] — American Male (Deep, Trustworthy, Smooth)"),
]

VOICE_STYLE_PRESETS: dict[str, tuple[str, str]] = {
    "warm_american": (
        "Warm American (Default)",
        "Speak in a warm, natural, conversational American voice with relaxed human pacing, subtle warmth, and natural phrasing — never robotic or announcer-like.",
    ),
    "warm_australian": (
        "Warm Australian",
        "Speak in a warm, natural, conversational Australian voice with relaxed, friendly pacing and authentic understated tone.",
    ),
    "calm_british": (
        "Calm British",
        "Speak in a calm, clear, conversational modern British voice with natural warmth and poised pacing.",
    ),
    "friendly_energetic": (
        "Friendly & Upbeat",
        "Speak in a friendly, engaged, upbeat conversational American voice with lively natural energy.",
    ),
    "studio_narrator": (
        "Calm Studio Narrator",
        "Speak in a smooth, unhurried, clear studio voice with gentle warmth and clean articulation.",
    ),
    "crisp_concise": (
        "Crisp & Direct",
        "Speak clearly, naturally, and briskly like a sharp colleague giving a concise update.",
    ),
}

VOICE_AVATAR_MODES = ("no_avatar", "windowed", "fullscreen")
VOICE_AVATAR_SHAPES = ("neural_core", "tesseract", "astrolabe", "torus_knot", "swarm", "mandala")
VOICE_AVATAR_PALETTES = ("tulsa_cyan", "jarvis_amber", "emerald_holo", "nebula_violet", "theme_accent", "auto_ai")

DEFAULT_VOICE_SETTINGS: dict[str, Any] = {
    "tts_engine": "auto",
    "tts_fallback_engine": "auto",
    "voice_llm_provider": "auto",
    "voice_llm_fallback": "auto",
    "voice_name": "coral",
    "gemini_voice_name": "Kore",
    "groq_voice_name": "autumn",
    "cartesia_voice_id": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",
    "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
    "deepgram_voice_name": "flux-sienna-en",
    "deepgram_expressivity": 0,
    "system_voice_name": "System Default",
    "voice_style": "warm_american",
    "custom_style_prompt": "",
    "speech_speed": 1.0,
    "microphone_device": "System default",
    "mic_gain_percent": 150,
    "silence_timeout_ms": 1500,
    "volume_percent": 100,
    "barge_in_enabled": True,
    "status_notification_style": "text",
    "auto_speak_responses": False,
    "voice_companion_enabled": True,
    "spoken_summary_for_background": True,
    "voice_avatar_mode": "no_avatar",
    "voice_avatar_shape": "neural_core",
    "voice_avatar_palette": "tulsa_cyan",
    "voice_avatar_always_on_top": True,
    "voice_avatar_show_activity": True,
}

_WAVE_BAR_CHARS = "▁▂▃▄▅▆▇█"
_OPENAI_VOICE_IDS = {vid.lower(): vid for vid, _ in OPENAI_TTS_VOICES}
_GEMINI_VOICE_IDS = {vid.lower(): vid for vid, _ in GEMINI_TTS_VOICES}
_GROQ_VOICE_IDS = {vid.lower(): vid for vid, _ in GROQ_ORPHEUS_VOICES}
_DEEPGRAM_VOICE_IDS = {vid.lower(): vid for vid, _ in DEEPGRAM_TTS_VOICES}
_VALID_ENGINES = {eid for eid, _ in TTS_ENGINES}

_TTS_LOCK = threading.RLock()
_SPEECH_GEN = 0
_ACTIVE_CANCEL_EVENT: threading.Event | None = None
_ACTIVE_WAVEOUT: _WaveOutStream | None = None
_ACTIVE_TTS_PROC: subprocess.Popen | None = None
_TTS_SPEAKING = False
_TTS_LAST_END_MONO = 0.0
_LAST_TTS_ENGINE_USED = ""
_LAST_TTS_STATE: dict[str, Any] = {
    "engine_id": "",
    "engine_label": "",
    "voice_label": "",
    "requested_engine": "",
    "fell_back": False,
    "fallback_reason": "",
    "last_error": "",
    "updated_ts": 0.0,
}
_LIVE_VOLUME_PERCENT: int | None = None
_LIVE_VOLUME_BY_PATH: dict[str, int] = {}

_TTS_AUDIO_LOCK = threading.Lock()
_TTS_AUDIO_FRAMES: deque[tuple[float, float, tuple[float, ...]]] = deque(maxlen=240)


def _compute_pcm_rms_and_bands(samples_bytes: bytes, sample_rate: int = 24000) -> tuple[float, tuple[float, ...]]:
    """Compute smoothed RMS energy (0..1) and 16 logarithmic FFT frequency bands (0..1) from mono int16 PCM."""
    even_len = len(samples_bytes) - (len(samples_bytes) % 2)
    if even_len < 4:
        return 0.0, (0.0,) * 16
    sr = max(8000, int(sample_rate or 24000))
    raw_view = memoryview(samples_bytes)[:even_len]
    try:
        import numpy as np  # type: ignore

        sig = np.frombuffer(raw_view, dtype="<i2").astype(np.float32) / 32768.0
        n = sig.size
        if n < 8:
            return 0.0, (0.0,) * 16
        rms = float(np.sqrt(np.mean(sig * sig)))
        win = np.hanning(n).astype(np.float32)
        spec = np.abs(np.fft.rfft(sig * win)) / max(1.0, float(n) * 0.5)
        freqs = np.fft.rfftfreq(n, d=1.0 / float(sr))
        f_hi = min(6500.0, float(sr) * 0.45)
        edges = np.geomspace(80.0, max(160.0, f_hi), 17)
        bands: list[float] = []
        for idx in range(16):
            lo_f = float(edges[idx])
            hi_f = float(edges[idx + 1])
            mask = (freqs >= lo_f) & (freqs < hi_f)
            if np.any(mask):
                energy = float(np.mean(spec[mask]))
            else:
                nearest = int(np.argmin(np.abs(freqs - (lo_f + hi_f) * 0.5)))
                energy = float(spec[nearest])
            norm = min(1.0, math.log1p(energy * 26.0) / 3.1)
            bands.append(norm)
        rms_norm = min(1.0, (rms * 3.4) ** 0.78) if rms > 1e-6 else 0.0
        return rms_norm, tuple(bands)
    except Exception:
        vals = array("h")
        vals.frombytes(bytes(raw_view))
        if sys.byteorder != "little":
            vals.byteswap()
        n = len(vals)
        if n == 0:
            return 0.0, (0.0,) * 16
        sum_sq = sum((v / 32768.0) ** 2 for v in vals)
        rms = math.sqrt(sum_sq / n)
        rms_norm = min(1.0, (rms * 3.4) ** 0.78) if rms > 1e-6 else 0.0
        bands = tuple(min(1.0, rms_norm * (0.95 - 0.04 * i)) for i in range(16))
        return rms_norm, bands


def record_tts_pcm_telemetry(
    pcm_bytes: bytes,
    sample_rate: int = 24000,
    delay_sec: float = 0.0,
    *,
    base_ts: float | None = None,
) -> None:
    """Slice played 16-bit mono PCM into ~21ms frames aligned to speaker hardware playback time."""
    if not pcm_bytes or len(pcm_bytes) < 32:
        return
    sr = max(8000, int(sample_rate or 24000))
    even_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
    if even_len < 32:
        return
    sub_samples = max(256, int(sr * 0.021))
    sub_bytes = max(512, min(even_len, sub_samples * 2))
    t0 = (float(base_ts) if base_ts is not None else time.monotonic()) + max(0.0, float(delay_sec))
    sub_dur = float(sub_bytes) / float(max(1, sr * 2))
    frames: list[tuple[float, float, tuple[float, ...]]] = []
    pos = 0
    sub_idx = 0
    while pos + 16 <= even_len and sub_idx < 8:
        chunk = pcm_bytes[pos : min(even_len, pos + sub_bytes)]
        rms_val, bands = _compute_pcm_rms_and_bands(chunk, sr)
        frames.append((t0 + sub_idx * sub_dur, rms_val, bands))
        pos += sub_bytes
        sub_idx += 1
    if frames:
        with _TTS_AUDIO_LOCK:
            _TTS_AUDIO_FRAMES.extend(frames)


def clear_tts_audio_telemetry() -> None:
    """Clear queued TTS FFT telemetry frames (e.g., on stop or barge-in)."""
    with _TTS_AUDIO_LOCK:
        _TTS_AUDIO_FRAMES.clear()


def get_tts_audio_telemetry(now_ts: float | None = None) -> dict[str, Any]:
    """Return latest playback-aligned FFT spectrum and RMS amplitude for voice avatar animation."""
    cur_ts = float(now_ts) if now_ts is not None else time.monotonic()
    best_frame: tuple[float, float, tuple[float, ...]] | None = None
    with _TTS_AUDIO_LOCK:
        while _TTS_AUDIO_FRAMES and (cur_ts - _TTS_AUDIO_FRAMES[0][0]) > 0.35:
            _TTS_AUDIO_FRAMES.popleft()
        for fr in _TTS_AUDIO_FRAMES:
            if fr[0] <= cur_ts:
                best_frame = fr
            else:
                break
        if best_frame is not None and (cur_ts - best_frame[0]) <= 0.22:
            return {
                "speaking": True,
                "rms": float(best_frame[1]),
                "bands": list(best_frame[2]),
                "source": "pcm",
            }

    with _TTS_LOCK:
        sapi_speaking = bool(_TTS_SPEAKING and _ACTIVE_TTS_PROC is not None)
    if sapi_speaking:
        t = cur_ts
        env = max(0.0, 0.38 + 0.24 * math.sin(t * 9.5) + 0.14 * math.sin(t * 21.0))
        bands = [
            max(0.0, min(1.0, env * (0.88 - 0.03 * i + 0.16 * math.sin(t * (7.0 + i * 1.1)))))
            for i in range(16)
        ]
        return {"speaking": True, "rms": min(1.0, env), "bands": bands, "source": "sapi5"}
    return {"speaking": False, "rms": 0.0, "bands": [0.0] * 16, "source": "idle"}


def get_last_tts_status() -> dict[str, Any]:
    """Return a snapshot of the most recently active TTS engine/voice and any failure reason."""
    with _TTS_LOCK:
        return dict(_LAST_TTS_STATE)


def _log_voice_diagnostic(message: str) -> None:
    """Append a timestamped diagnostic note for audio/TTS debugging (size-capped at ~64 KB)."""
    try:
        log_path = get_palace_data_root() / "voice_diagnostics.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > 65536:
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-150:]
            log_path.write_text("\n".join(tail) + "\n", encoding="utf-8")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def set_live_volume(volume_percent: int, config_path: Path | None = None) -> int:
    """Update active playback volume in memory immediately without restarting TTS or touching Windows Mixer."""
    global _LIVE_VOLUME_PERCENT
    val = max(0, min(100, int(volume_percent)))
    with _TTS_LOCK:
        if config_path is None or Path(config_path).resolve() == Path(CONFIG_PATH).resolve():
            _LIVE_VOLUME_PERCENT = val
        if config_path is not None:
            _LIVE_VOLUME_BY_PATH[str(Path(config_path).resolve())] = val
    return val


def get_live_volume(config_path: Path = CONFIG_PATH) -> int:
    """Read current live speaker volume in memory first, falling back to config."""
    try:
        res_key = str(Path(config_path).resolve())
    except Exception:
        res_key = ""
    with _TTS_LOCK:
        if res_key and res_key in _LIVE_VOLUME_BY_PATH:
            return max(0, min(100, int(_LIVE_VOLUME_BY_PATH[res_key])))
        try:
            is_default = Path(config_path).resolve() == Path(CONFIG_PATH).resolve()
        except Exception:
            is_default = (config_path == CONFIG_PATH)
        if is_default and _LIVE_VOLUME_PERCENT is not None:
            return max(0, min(100, int(_LIVE_VOLUME_PERCENT)))
    try:
        cfg = load_voice_settings(config_path)
        return max(0, min(100, int(cfg.get("volume_percent", 100))))
    except Exception:
        return 100


def is_tts_engine_ready(engine_id: str, credential_store: CredentialStore | None = None) -> bool:
    """Return True if the selected TTS engine can play immediately without adding a new API key."""
    eid = (engine_id or "auto").strip().lower()
    if eid in {"auto", "system"}:
        return True
    try:
        store = credential_store or CredentialStore()
        return bool((store.get_api_key(eid) or "").strip())
    except Exception:
        return False


def get_tts_engine_display_label(engine_id: str, credential_store: CredentialStore | None = None) -> str:
    """Return honest status-prefixed label (`✓ ...` vs `🔑 ... Needs key`) for Voice Engine dropdowns."""
    eid = (engine_id or "auto").strip().lower()
    base = dict(TTS_ENGINES).get(eid, eid)
    if eid == "auto":
        return f"✓ {base}"
    if is_tts_engine_ready(eid, credential_store=credential_store):
        return f"✓ {base} · Ready"
    return f"🔑 {base} · Needs API key"


def _clamp_speed(raw_speed: Any) -> float:
    try:
        val = float(raw_speed)
    except (TypeError, ValueError):
        val = 1.0
    if math.isnan(val) or math.isinf(val):
        val = 1.0
    return round(max(0.80, min(1.30, val)), 2)


def _clamp_deepgram_expressivity(raw_expr: Any) -> int:
    try:
        val = int(round(float(raw_expr)))
    except (TypeError, ValueError):
        val = 0
    return max(-2, min(2, val))


def _normalize_deepgram_voice_model(voice_model: str) -> str:
    raw = (voice_model or "").strip().lower()
    if raw in _DEEPGRAM_VOICE_IDS:
        return _DEEPGRAM_VOICE_IDS[raw]
    if re.fullmatch(r"(?:flux|aura|aura-2)-[a-z0-9-]+", raw):
        return raw
    return DEFAULT_VOICE_SETTINGS["deepgram_voice_name"]


def load_voice_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("voice_settings", {})
    if not isinstance(raw, dict):
        raw = {}
    merged = dict(DEFAULT_VOICE_SETTINGS)

    engine = str(raw.get("tts_engine") or DEFAULT_VOICE_SETTINGS["tts_engine"]).strip().lower()
    merged["tts_engine"] = engine if engine in _VALID_ENGINES else "auto"

    fb_engine = str(raw.get("tts_fallback_engine") or DEFAULT_VOICE_SETTINGS["tts_fallback_engine"]).strip().lower()
    merged["tts_fallback_engine"] = fb_engine if fb_engine in (_VALID_ENGINES | {"none"}) else "auto"

    llm_p = str(raw.get("voice_llm_provider") or "auto").strip().lower()
    merged["voice_llm_provider"] = llm_p or "auto"
    llm_fb = str(raw.get("voice_llm_fallback") or "auto").strip().lower()
    merged["voice_llm_fallback"] = llm_fb or "auto"

    if isinstance(raw.get("voice_name"), str) and raw["voice_name"].strip():
        v_raw = raw["voice_name"].strip()
        if v_raw.lower() == "system default" and merged["tts_engine"] == "auto":
            merged["voice_name"] = "coral"
        elif v_raw.lower() in _OPENAI_VOICE_IDS:
            merged["voice_name"] = _OPENAI_VOICE_IDS[v_raw.lower()]
        else:
            merged["voice_name"] = v_raw

    if isinstance(raw.get("gemini_voice_name"), str) and raw["gemini_voice_name"].strip():
        gv_raw = raw["gemini_voice_name"].strip()
        merged["gemini_voice_name"] = _GEMINI_VOICE_IDS.get(gv_raw.lower(), gv_raw)

    if isinstance(raw.get("groq_voice_name"), str) and raw["groq_voice_name"].strip():
        grv_raw = raw["groq_voice_name"].strip()
        merged["groq_voice_name"] = _GROQ_VOICE_IDS.get(grv_raw.lower(), grv_raw)

    if isinstance(raw.get("cartesia_voice_id"), str) and raw["cartesia_voice_id"].strip():
        cid = raw["cartesia_voice_id"].strip()
        merged["cartesia_voice_id"] = (
            DEFAULT_VOICE_SETTINGS["cartesia_voice_id"] if cid.lower() in _RETIRED_CARTESIA_VOICE_IDS else cid
        )

    if isinstance(raw.get("elevenlabs_voice_id"), str) and raw["elevenlabs_voice_id"].strip():
        merged["elevenlabs_voice_id"] = raw["elevenlabs_voice_id"].strip()

    if isinstance(raw.get("deepgram_voice_name"), str) and raw["deepgram_voice_name"].strip():
        merged["deepgram_voice_name"] = _normalize_deepgram_voice_model(raw["deepgram_voice_name"])
    if "deepgram_expressivity" in raw:
        merged["deepgram_expressivity"] = _clamp_deepgram_expressivity(raw["deepgram_expressivity"])

    if isinstance(raw.get("system_voice_name"), str) and raw["system_voice_name"].strip():
        merged["system_voice_name"] = raw["system_voice_name"].strip()

    style = str(raw.get("voice_style") or DEFAULT_VOICE_SETTINGS["voice_style"]).strip().lower()
    merged["voice_style"] = style if style in VOICE_STYLE_PRESETS else "warm_american"

    if isinstance(raw.get("custom_style_prompt"), str):
        merged["custom_style_prompt"] = raw["custom_style_prompt"].strip()[:280]

    if "speech_speed" in raw:
        merged["speech_speed"] = _clamp_speed(raw["speech_speed"])

    if isinstance(raw.get("microphone_device"), str) and raw["microphone_device"].strip():
        merged["microphone_device"] = raw["microphone_device"].strip()
    if "mic_gain_percent" in raw:
        try:
            merged["mic_gain_percent"] = max(50, min(400, int(raw["mic_gain_percent"])))
        except (TypeError, ValueError):
            pass
    if "silence_timeout_ms" in raw:
        try:
            merged["silence_timeout_ms"] = max(700, min(4000, int(raw["silence_timeout_ms"])))
        except (TypeError, ValueError):
            pass
    if "volume_percent" in raw:
        try:
            merged["volume_percent"] = max(0, min(100, int(raw["volume_percent"])))
        except (TypeError, ValueError):
            pass
    if "barge_in_enabled" in raw:
        merged["barge_in_enabled"] = bool(raw["barge_in_enabled"])
    st_style = str(raw.get("status_notification_style") or DEFAULT_VOICE_SETTINGS["status_notification_style"]).strip().lower()
    merged["status_notification_style"] = st_style if st_style in {"text", "icons"} else "text"
    if "auto_speak_responses" in raw:
        merged["auto_speak_responses"] = bool(raw["auto_speak_responses"])
    if "voice_companion_enabled" in raw:
        merged["voice_companion_enabled"] = bool(raw["voice_companion_enabled"])
    if "spoken_summary_for_background" in raw:
        merged["spoken_summary_for_background"] = bool(raw["spoken_summary_for_background"])
    av_mode = str(raw.get("voice_avatar_mode") or DEFAULT_VOICE_SETTINGS["voice_avatar_mode"]).strip().lower()
    merged["voice_avatar_mode"] = av_mode if av_mode in VOICE_AVATAR_MODES else "no_avatar"
    av_shape = str(raw.get("voice_avatar_shape") or DEFAULT_VOICE_SETTINGS["voice_avatar_shape"]).strip().lower()
    merged["voice_avatar_shape"] = av_shape if av_shape in VOICE_AVATAR_SHAPES else "neural_core"
    av_pal = str(raw.get("voice_avatar_palette") or DEFAULT_VOICE_SETTINGS["voice_avatar_palette"]).strip().lower()
    merged["voice_avatar_palette"] = av_pal if av_pal in VOICE_AVATAR_PALETTES else "tulsa_cyan"
    if "voice_avatar_always_on_top" in raw:
        merged["voice_avatar_always_on_top"] = bool(raw["voice_avatar_always_on_top"])
    if "voice_avatar_show_activity" in raw:
        merged["voice_avatar_show_activity"] = bool(raw["voice_avatar_show_activity"])
    return merged


def save_voice_settings(
    voice_settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    current = load_voice_settings(config_path)
    current.update(voice_settings)

    engine = str(current.get("tts_engine") or "auto").strip().lower()
    current["tts_engine"] = engine if engine in _VALID_ENGINES else "auto"

    fb_engine = str(current.get("tts_fallback_engine") or "auto").strip().lower()
    current["tts_fallback_engine"] = fb_engine if fb_engine in (_VALID_ENGINES | {"none"}) else "auto"

    current["voice_llm_provider"] = str(current.get("voice_llm_provider") or "auto").strip().lower() or "auto"
    current["voice_llm_fallback"] = str(current.get("voice_llm_fallback") or "auto").strip().lower() or "auto"

    voice = str(current.get("voice_name") or "coral").strip() or "coral"
    if voice.lower() == "system default" and current["tts_engine"] == "auto":
        voice = "coral"
    current["voice_name"] = _OPENAI_VOICE_IDS.get(voice.lower(), voice)

    gvoice = str(current.get("gemini_voice_name") or "Kore").strip() or "Kore"
    current["gemini_voice_name"] = _GEMINI_VOICE_IDS.get(gvoice.lower(), gvoice)

    grvoice = str(current.get("groq_voice_name") or "autumn").strip() or "autumn"
    current["groq_voice_name"] = _GROQ_VOICE_IDS.get(grvoice.lower(), grvoice)

    cid = str(current.get("cartesia_voice_id") or DEFAULT_VOICE_SETTINGS["cartesia_voice_id"]).strip()
    if not cid or cid.lower() in _RETIRED_CARTESIA_VOICE_IDS:
        cid = DEFAULT_VOICE_SETTINGS["cartesia_voice_id"]
    current["cartesia_voice_id"] = cid
    current["elevenlabs_voice_id"] = str(current.get("elevenlabs_voice_id") or DEFAULT_VOICE_SETTINGS["elevenlabs_voice_id"]).strip()
    dgvoice = str(current.get("deepgram_voice_name") or DEFAULT_VOICE_SETTINGS["deepgram_voice_name"]).strip()
    current["deepgram_voice_name"] = _normalize_deepgram_voice_model(dgvoice)
    current["deepgram_expressivity"] = _clamp_deepgram_expressivity(current.get("deepgram_expressivity", 0))
    current["system_voice_name"] = str(current.get("system_voice_name") or "System Default").strip() or "System Default"

    style = str(current.get("voice_style") or "warm_american").strip().lower()
    current["voice_style"] = style if style in VOICE_STYLE_PRESETS else "warm_american"
    current["custom_style_prompt"] = str(current.get("custom_style_prompt") or "").strip()[:280]
    current["speech_speed"] = _clamp_speed(current.get("speech_speed", 1.0))

    current["mic_gain_percent"] = max(50, min(400, int(current.get("mic_gain_percent", 150))))
    current["silence_timeout_ms"] = max(700, min(4000, int(current.get("silence_timeout_ms", 1500))))
    current["volume_percent"] = max(0, min(100, int(current.get("volume_percent", 100))))
    current["barge_in_enabled"] = bool(current.get("barge_in_enabled", True))
    st_style = str(current.get("status_notification_style") or "text").strip().lower()
    current["status_notification_style"] = st_style if st_style in {"text", "icons"} else "text"
    current["auto_speak_responses"] = bool(current.get("auto_speak_responses", False))
    current["voice_companion_enabled"] = bool(current.get("voice_companion_enabled", True))
    current["spoken_summary_for_background"] = bool(current.get("spoken_summary_for_background", True))
    av_mode = str(current.get("voice_avatar_mode") or "no_avatar").strip().lower()
    current["voice_avatar_mode"] = av_mode if av_mode in VOICE_AVATAR_MODES else "no_avatar"
    av_shape = str(current.get("voice_avatar_shape") or "neural_core").strip().lower()
    current["voice_avatar_shape"] = av_shape if av_shape in VOICE_AVATAR_SHAPES else "neural_core"
    av_pal = str(current.get("voice_avatar_palette") or "tulsa_cyan").strip().lower()
    current["voice_avatar_palette"] = av_pal if av_pal in VOICE_AVATAR_PALETTES else "tulsa_cyan"
    current["voice_avatar_always_on_top"] = bool(current.get("voice_avatar_always_on_top", True))
    current["voice_avatar_show_activity"] = bool(current.get("voice_avatar_show_activity", True))

    data["voice_settings"] = current
    _write_raw_config(data, config_path)
    set_live_volume(current["volume_percent"], config_path=config_path)
    return load_voice_settings(config_path)


def build_voice_style_instructions(
    voice_style: str = "warm_american",
    custom_hint: str = "",
    speed: float = 1.0,
) -> str:
    _, base_instr = VOICE_STYLE_PRESETS.get(
        (voice_style or "warm_american").strip().lower(),
        VOICE_STYLE_PRESETS["warm_american"],
    )
    parts = [base_instr]
    hint = (custom_hint or "").strip()
    if hint:
        parts.append(hint)
    sp = _clamp_speed(speed)
    if sp <= 0.90:
        parts.append("Deliver at an unhurried, relaxed tempo.")
    elif sp >= 1.15:
        parts.append("Deliver at an energetic, brisk conversational tempo.")
    return " ".join(parts)


def is_loopback_audio_device(device_name: str) -> bool:
    """Return True if an audio input device is speaker loopback (e.g., Stereo Mix) rather than a microphone."""
    low = (device_name or "").strip().lower()
    return any(tok in low for tok in ("stereo mix", "what u hear", "loopback", "wave out mix"))


def list_audio_input_devices() -> list[str]:
    """Return available microphone input devices on this machine."""
    devices = ["System default"]
    try:
        from PySide6.QtMultimedia import QMediaDevices

        for dev in QMediaDevices.audioInputs():
            desc = (dev.description() or "").strip()
            if desc and desc not in devices:
                devices.append(desc)
    except Exception:
        pass
    return devices


def resolve_qaudio_input_device(preferred_name: str = "System default"):
    """Resolve the requested QAudioDevice (or system default microphone)."""
    from PySide6.QtMultimedia import QMediaDevices

    pref = (preferred_name or "").strip()
    if pref and pref.lower() != "system default":
        for dev in QMediaDevices.audioInputs():
            if (dev.description() or "").strip() == pref:
                return dev
    default_dev = QMediaDevices.defaultAudioInput()
    if not default_dev.isNull():
        return default_dev
    inputs = QMediaDevices.audioInputs()
    return inputs[0] if inputs else default_dev


def pcm_chunk_to_int16_mono_and_level(
    raw_bytes: bytes,
    sample_format_name: str = "Int16",
    channels: int = 1,
    gain_percent: int = 150,
) -> tuple[bytes, int]:
    """Convert raw PCM bytes from QAudioSource into 16-bit signed mono PCM and return (pcm16_bytes, level_0_to_100)."""
    if not raw_bytes:
        return b"", 0
    ch = max(1, int(channels or 1))
    gain = max(0.5, min(4.0, float(gain_percent or 150) / 100.0))
    fmt_lower = str(sample_format_name or "Int16").lower()

    samples_mono: list[int] = []
    if "float" in fmt_lower:
        frame_bytes = 4 * ch
        n_frames = len(raw_bytes) // frame_bytes
        for i in range(n_frames):
            val = struct.unpack_from("<f", raw_bytes, i * frame_bytes)[0]
            if math.isnan(val) or math.isinf(val):
                val = 0.0
            scaled = int(max(-32767.0, min(32767.0, val * 32767.0 * gain)))
            samples_mono.append(scaled)
    elif "int32" in fmt_lower:
        frame_bytes = 4 * ch
        n_frames = len(raw_bytes) // frame_bytes
        for i in range(n_frames):
            val = struct.unpack_from("<i", raw_bytes, i * frame_bytes)[0] >> 16
            scaled = int(max(-32767, min(32767, int(val * gain))))
            samples_mono.append(scaled)
    elif "uint8" in fmt_lower:
        frame_bytes = 1 * ch
        n_frames = len(raw_bytes) // frame_bytes
        for i in range(n_frames):
            val = (raw_bytes[i * frame_bytes] - 128) * 256
            scaled = int(max(-32767, min(32767, int(val * gain))))
            samples_mono.append(scaled)
    else:
        frame_bytes = 2 * ch
        n_frames = len(raw_bytes) // frame_bytes
        for i in range(n_frames):
            val = struct.unpack_from("<h", raw_bytes, i * frame_bytes)[0]
            scaled = int(max(-32767, min(32767, int(val * gain))))
            samples_mono.append(scaled)

    if not samples_mono:
        return b"", 0

    sum_sq = 0.0
    peak = 0
    for s in samples_mono:
        a = abs(s)
        if a > peak:
            peak = a
        sum_sq += float(s * s)
    rms = math.sqrt(sum_sq / len(samples_mono))
    effective = max(rms * 1.8, peak * 0.45)
    level_pct = int(min(100.0, (effective / 9500.0) * 100.0))
    packed = struct.pack(f"<{len(samples_mono)}h", *samples_mono)
    return packed, level_pct


def format_wave_bars(level_history: list[int], width: int = 6) -> str:
    """Render a live Unicode soundwave indicator like ▂▅▇█▄▂ from recent voice levels."""
    hist = ([0] * width + list(level_history))[-width:]
    chars = []
    for lvl in hist:
        idx = min(len(_WAVE_BAR_CHARS) - 1, max(0, int(round((lvl / 100.0) * (len(_WAVE_BAR_CHARS) - 1)))))
        chars.append(_WAVE_BAR_CHARS[idx])
    return "".join(chars)


def write_pcm16_wav(wav_path: Path, pcm16_mono_bytes: bytes, sample_rate: int = 16000) -> Path:
    """Write 16-bit mono PCM bytes to a standard RIFF .wav file."""
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate or 16000))
        wf.writeframes(pcm16_mono_bytes)
    return wav_path


def is_speaking(cooldown_sec: float = 0.0) -> bool:
    """Return True if Fairybread is currently speaking aloud (or within cooldown_sec of stopping)."""
    with _TTS_LOCK:
        if _TTS_SPEAKING:
            return True
        if _ACTIVE_TTS_PROC is not None:
            if _ACTIVE_TTS_PROC.poll() is None:
                return True
        if cooldown_sec > 0.0 and _TTS_LAST_END_MONO > 0.0:
            if (time.monotonic() - _TTS_LAST_END_MONO) < cooldown_sec:
                return True
        return False


def get_last_tts_engine_used() -> str:
    with _TTS_LOCK:
        return _LAST_TTS_ENGINE_USED


class LiveAudioSession:
    """Real-time QAudioSource microphone streamer supporting both Dictate Mode and Live Hands-Free Voice Mode."""

    def __init__(
        self,
        *,
        config_path: Path = CONFIG_PATH,
        live_mode: bool = False,
        on_level: Callable[[int, str, bool], None] | None = None,
        on_utterance_ready: Callable[[Path], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_barge_in: Callable[[], None] | None = None,
    ):
        self.config_path = config_path
        self.live_mode = bool(live_mode)
        self.on_level = on_level
        self.on_utterance_ready = on_utterance_ready
        self.on_error = on_error
        self.on_barge_in = on_barge_in

        self._audio_source = None
        self._io_device = None
        self._timer = None
        self._parent_widget = None
        self._sample_rate = 16000
        self._channels = 1
        self._sample_format_name = "Int16"
        self._gain_percent = 150
        self._silence_timeout_ms = 1500
        self._barge_in_enabled = True

        self._pcm_buffer = bytearray()
        self._barge_prebuf = bytearray()
        self._barge_ticks = 0
        self._level_history: list[int] = [10, 20, 15, 25, 15, 10]
        self._speech_detected = False
        self._speech_ticks = 0
        self._last_voice_ts = 0.0
        self._started_ts = 0.0
        self._restart_attempts = 0
        self._healthy_ticks_since_restart = 0
        self._poll_err_count = 0
        self.active = False
        self.muted = False

    def start(self, parent_widget=None) -> tuple[bool, str]:
        from PySide6.QtCore import QTimer
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource

        self._parent_widget = parent_widget
        v_cfg = load_voice_settings(self.config_path)
        self._gain_percent = int(v_cfg.get("mic_gain_percent", 150))
        self._silence_timeout_ms = int(v_cfg.get("silence_timeout_ms", 1500))
        self._barge_in_enabled = bool(v_cfg.get("barge_in_enabled", True))
        dev = resolve_qaudio_input_device(str(v_cfg.get("microphone_device", "System default")))
        if dev.isNull():
            return False, "No microphone input device detected on this system."

        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not dev.isFormatSupported(fmt):
            fmt = dev.preferredFormat()

        self._sample_rate = int(fmt.sampleRate() or 16000)
        self._channels = max(1, int(fmt.channelCount() or 1))
        self._sample_format_name = str(fmt.sampleFormat())

        self._pcm_buffer.clear()
        self._barge_prebuf.clear()
        self._barge_ticks = 0
        self._speech_detected = False
        self._speech_ticks = 0
        self._started_ts = time.monotonic()
        self._last_voice_ts = self._started_ts

        self._audio_source = QAudioSource(dev, fmt, parent_widget)
        self._io_device = self._audio_source.start()
        if self._io_device is None:
            return False, f"Could not open microphone: {dev.description()}"

        self.active = True
        self._restart_attempts = 0
        self._healthy_ticks_since_restart = 0
        self._poll_err_count = 0
        self._timer = QTimer(parent_widget)
        self._timer.setInterval(55)
        self._timer.timeout.connect(self._poll_audio)
        self._timer.start()
        return True, dev.description()

    def _poll_audio(self) -> None:
        if not self.active or self._io_device is None:
            return
        if self._audio_source is not None:
            try:
                from PySide6.QtMultimedia import QAudio

                state = self._audio_source.state()
                err = self._audio_source.error()
                if state == QAudio.State.StoppedState and self.active:
                    if self._restart_attempts < 2:
                        self._restart_attempts += 1
                        self._healthy_ticks_since_restart = 0
                        _log_voice_diagnostic(
                            f"LiveAudioSession audio source stopped unexpectedly (error={err}); recovering attempt {self._restart_attempts}"
                        )
                        try:
                            self._audio_source.stop()
                        except Exception:
                            pass
                        try:
                            self._io_device = self._audio_source.start()
                            if self._io_device is not None:
                                self._healthy_ticks_since_restart = 0
                                return
                        except Exception:
                            pass
                    _log_voice_diagnostic(f"LiveAudioSession lost microphone device (error={err})")
                    if self.on_error is not None:
                        try:
                            self.on_error("Microphone stream disconnected — click End Talk and restart, or check Settings → Voice & Audio.")
                        except Exception:
                            pass
                    self.stop(discard=True)
                    return
            except Exception as exc:
                self._poll_err_count = getattr(self, "_poll_err_count", 0) + 1
                if self._poll_err_count == 1 or self._poll_err_count % 20 == 0:
                    _log_voice_diagnostic(f"LiveAudioSession state check error (#{self._poll_err_count}): {exc}")
        try:
            raw = bytes(self._io_device.readAll())
        except Exception as exc:
            self._poll_err_count = getattr(self, "_poll_err_count", 0) + 1
            if self._poll_err_count == 1 or self._poll_err_count % 20 == 0:
                _log_voice_diagnostic(f"LiveAudioSession readAll error (#{self._poll_err_count}): {exc}")
            raw = b""
        if raw and getattr(self, "_restart_attempts", 0) > 0:
            self._healthy_ticks_since_restart = getattr(self, "_healthy_ticks_since_restart", 0) + 1
            if self._healthy_ticks_since_restart >= 36:
                self._restart_attempts = 0
                self._healthy_ticks_since_restart = 0

        if getattr(self, "muted", False):
            self._pcm_buffer.clear()
            self._barge_prebuf.clear()
            self._barge_ticks = 0
            self._speech_detected = False
            self._speech_ticks = 0
            self._last_voice_ts = time.monotonic()
            self._level_history = [0] * 6
            if self.on_level is not None:
                try:
                    self.on_level(0, format_wave_bars(self._level_history, width=6), False)
                except Exception:
                    pass
            return

        if self.live_mode:
            if is_speaking(cooldown_sec=0.0):
                if not self._barge_in_enabled:
                    self._pcm_buffer.clear()
                    self._barge_prebuf.clear()
                    self._barge_ticks = 0
                    self._speech_detected = False
                    self._speech_ticks = 0
                    self._last_voice_ts = time.monotonic()
                    self._level_history = [0] * 6
                    if self.on_level is not None:
                        try:
                            self.on_level(0, format_wave_bars(self._level_history, width=6), False)
                        except Exception:
                            pass
                    return
                if not raw:
                    return
                pcm16, lvl = pcm_chunk_to_int16_mono_and_level(
                    raw,
                    sample_format_name=self._sample_format_name,
                    channels=self._channels,
                    gain_percent=self._gain_percent,
                )
                if pcm16:
                    self._barge_prebuf.extend(pcm16)
                    max_pre = max(3200, int(self._sample_rate * 2 * 0.35))
                    if len(self._barge_prebuf) > max_pre:
                        del self._barge_prebuf[:-max_pre]
                self._level_history.append(lvl)
                if len(self._level_history) > 12:
                    self._level_history = self._level_history[-12:]
                bars = format_wave_bars(self._level_history, width=6)
                if lvl >= 18:
                    self._barge_ticks += 1
                else:
                    self._barge_ticks = 0
                if self._barge_ticks >= 4:
                    stop_speaking()
                    self._pcm_buffer = bytearray(self._barge_prebuf)
                    self._barge_prebuf.clear()
                    self._barge_ticks = 0
                    self._speech_detected = True
                    self._speech_ticks = 4
                    self._last_voice_ts = time.monotonic()
                    if self.on_barge_in is not None:
                        try:
                            self.on_barge_in()
                        except Exception:
                            pass
                    if self.on_level is not None:
                        try:
                            self.on_level(lvl, bars, True)
                        except Exception:
                            pass
                    return
                if self.on_level is not None:
                    try:
                        self.on_level(0, format_wave_bars([0] * 6, width=6), False)
                    except Exception:
                        pass
                return
            elif (not self._barge_in_enabled) and is_speaking(cooldown_sec=0.35):
                self._pcm_buffer.clear()
                self._barge_prebuf.clear()
                self._barge_ticks = 0
                self._speech_detected = False
                self._speech_ticks = 0
                self._last_voice_ts = time.monotonic()
                self._level_history = [0] * 6
                if self.on_level is not None:
                    try:
                        self.on_level(0, format_wave_bars(self._level_history, width=6), False)
                    except Exception:
                        pass
                return
            elif self._barge_prebuf:
                if self._barge_ticks > 0:
                    self._pcm_buffer.extend(self._barge_prebuf)
                    self._speech_ticks = max(self._speech_ticks, self._barge_ticks)
                    self._last_voice_ts = time.monotonic()
                self._barge_prebuf.clear()
                self._barge_ticks = 0

        if not raw:
            return

        pcm16, lvl = pcm_chunk_to_int16_mono_and_level(
            raw,
            sample_format_name=self._sample_format_name,
            channels=self._channels,
            gain_percent=self._gain_percent,
        )
        if pcm16:
            self._pcm_buffer.extend(pcm16)

        self._level_history.append(lvl)
        if len(self._level_history) > 12:
            self._level_history = self._level_history[-12:]
        bars = format_wave_bars(self._level_history, width=6)

        now = time.monotonic()
        if lvl >= 7:
            self._speech_ticks += 1
            self._last_voice_ts = now
            if self._speech_ticks >= 2:
                self._speech_detected = True
        else:
            if self.live_mode and not self._speech_detected:
                max_lead_bytes = self._sample_rate * 2
                if len(self._pcm_buffer) > max_lead_bytes:
                    del self._pcm_buffer[:-max_lead_bytes]

        if self.on_level is not None:
            try:
                self.on_level(lvl, bars, self._speech_detected)
            except Exception:
                pass

        if self.live_mode and self._speech_detected:
            silence_ms = (now - self._last_voice_ts) * 1000.0
            min_bytes = int(self._sample_rate * 2 * 0.35)
            if silence_ms >= self._silence_timeout_ms and len(self._pcm_buffer) >= min_bytes:
                wav_path = self.flush_utterance_to_wav("fairybread_live_utterance.wav")
                if wav_path and self.on_utterance_ready is not None:
                    self.on_utterance_ready(wav_path)

    def flush_utterance_to_wav(self, filename: str = "fairybread_voice_input.wav") -> Path | None:
        """Package current buffered PCM into a WAV file and reset utterance state."""
        if len(self._pcm_buffer) < 800:
            self._pcm_buffer.clear()
            self._speech_detected = False
            self._speech_ticks = 0
            return None
        raw_pcm = bytes(self._pcm_buffer)
        self._pcm_buffer.clear()
        self._speech_detected = False
        self._speech_ticks = 0
        self._last_voice_ts = time.monotonic()
        out_path = Path(tempfile.gettempdir()) / filename
        return write_pcm16_wav(out_path, raw_pcm, sample_rate=self._sample_rate)

    def stop(self, filename: str = "fairybread_voice_input.wav", *, discard: bool = False) -> Path | None:
        """Stop capturing and return the recorded WAV file path (or discard buffered audio when discard=True)."""
        self.active = False
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        if not discard and self._io_device is not None and not (self.live_mode and is_speaking(cooldown_sec=0.35)):
            try:
                raw = bytes(self._io_device.readAll())
                if raw:
                    pcm16, _ = pcm_chunk_to_int16_mono_and_level(
                        raw,
                        sample_format_name=self._sample_format_name,
                        channels=self._channels,
                        gain_percent=self._gain_percent,
                    )
                    self._pcm_buffer.extend(pcm16)
            except Exception:
                pass
        if self._audio_source is not None:
            try:
                self._audio_source.stop()
            except Exception:
                pass
            self._audio_source = None
        self._io_device = None
        if discard:
            self._pcm_buffer.clear()
            self._speech_detected = False
            self._speech_ticks = 0
            return None
        return self.flush_utterance_to_wav(filename)


def _list_sapi5_voices() -> list[str]:
    voices: list[str] = []
    if os.name == "nt":
        try:
            ps = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=4.0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in (res.stdout or "").splitlines():
                v = line.strip()
                if v and v not in voices:
                    voices.append(v)
        except Exception:
            pass
    return voices


def list_voices_for_engine(engine: str = "auto") -> list[tuple[str, str]]:
    """Return (voice_id, display_label) choices appropriate for the selected TTS engine."""
    eng = (engine or "auto").strip().lower()
    if eng == "gemini":
        return list(GEMINI_TTS_VOICES)
    if eng == "groq":
        return list(GROQ_ORPHEUS_VOICES)
    if eng == "cartesia":
        return list(CARTESIA_TTS_VOICES)
    if eng == "elevenlabs":
        return list(ELEVENLABS_TTS_VOICES)
    if eng == "deepgram":
        return list(DEEPGRAM_TTS_VOICES)
    if eng == "system":
        items = [("System Default", "System Default (Windows SAPI 5)")]
        for v in _list_sapi5_voices():
            items.append((v, v))
        return items
    return list(OPENAI_TTS_VOICES)


def fetch_remote_tts_voices(engine: str, api_key: str, *, timeout: float = 10.0) -> list[tuple[str, str]]:
    """Fetch live account voices for Cartesia, ElevenLabs, or Deepgram (falls back to curated defaults on error)."""
    eng = (engine or "").strip().lower()
    key = (api_key or "").strip()
    if not key:
        return list_voices_for_engine(eng)
    out: list[tuple[str, str]] = []
    if eng == "cartesia":
        req = urllib.request.Request(
            "https://api.cartesia.ai/voices?limit=40",
            headers={
                "X-API-Key": key,
                "Cartesia-Version": "2024-11-13",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        rows = payload if isinstance(payload, list) else (payload.get("data") or payload.get("voices") or [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            vid = str(row.get("id") or "").strip()
            name = str(row.get("name") or vid).strip()
            lang = str(row.get("language") or "").strip()
            if vid:
                lbl = f"{name} ({lang})" if lang else name
                out.append((vid, lbl))
    elif eng == "elevenlabs":
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": key},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        for row in payload.get("voices") or []:
            if not isinstance(row, dict):
                continue
            vid = str(row.get("voice_id") or "").strip()
            name = str(row.get("name") or vid).strip()
            cat = str(row.get("category") or "").strip()
            if vid:
                lbl = f"{name} ({cat})" if cat else name
                out.append((vid, lbl))
    elif eng == "deepgram":
        headers = {"Authorization": f"Token {key}"}
        seen: dict[str, tuple[tuple[int, int, str], str]] = {}
        last_exc: Exception | None = None
        for endpoint_url in ("https://api.deepgram.com/v2/models", "https://api.deepgram.com/v1/models"):
            try:
                req = urllib.request.Request(endpoint_url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                for row in payload.get("tts") or []:
                    if not isinstance(row, dict):
                        continue
                    cid = str(row.get("canonical_name") or "").strip().lower()
                    if not cid or cid in seen:
                        continue
                    vname = str(row.get("name") or cid).strip().title()
                    meta = row.get("metadata") or {}
                    accent = str(meta.get("accent") or "").strip()
                    tags = [str(t).strip() for t in (meta.get("tags") or []) if str(t).strip()]
                    lang = str((row.get("languages") or [""])[0] or "").strip()
                    if not lang and "-" in cid:
                        lang = cid.rsplit("-", 1)[-1]
                    is_en = lang.lower().startswith("en") or cid.endswith("-en")
                    if cid.startswith("flux-"):
                        fam = "Flux"
                        fam_rank = 0
                    elif cid.startswith("aura-2-"):
                        fam = "Aura-2"
                        fam_rank = 1
                    else:
                        fam = "Aura-1"
                        fam_rank = 2
                    gender = ""
                    desc_tags: list[str] = []
                    for t in tags:
                        tl = t.lower()
                        if tl == "feminine" and not gender:
                            gender = "Female"
                        elif tl == "masculine" and not gender:
                            gender = "Male"
                        elif len(desc_tags) < 3:
                            desc_tags.append(t.title())
                    lang_suffix = f" · {lang.upper()}" if (lang and not is_en) else ""
                    fam_badge = f"[{fam}{lang_suffix}]"
                    who = " ".join(p for p in (accent, gender) if p)
                    detail = f" ({', '.join(desc_tags)})" if desc_tags else ""
                    right = f"{who}{detail}".strip()
                    lbl = f"{vname} {fam_badge} — {right}" if right else f"{vname} {fam_badge}"
                    if cid == "flux-sienna-en":
                        lbl += " (Default)"
                    sort_key = (0 if is_en else 1, fam_rank, "" if cid == "flux-sienna-en" else vname.lower())
                    seen[cid] = (sort_key, lbl)
            except Exception as exc:
                last_exc = exc
        if not seen and last_exc is not None:
            raise last_exc
        out = [(cid, item[1]) for cid, item in sorted(seen.items(), key=lambda kv: kv[1][0])]
    return out or list_voices_for_engine(eng)


def fetch_tts_account_balance(
    engine: str,
    api_key: str = "",
    *,
    timeout: float = 6.0,
) -> dict[str, Any]:
    """Query live subscription/credit balance when supported by the provider's standard API key."""
    eng = (engine or "auto").strip().lower()
    billing_urls = {
        "cartesia": "https://play.cartesia.ai",
        "elevenlabs": "https://elevenlabs.io/app/subscription",
        "deepgram": "https://console.deepgram.com/",
        "openai": "https://platform.openai.com/settings/organization/billing/overview",
        "gemini": "https://aistudio.google.com/",
        "groq": "https://console.groq.com/settings/billing",
        "openrouter": "https://openrouter.ai/settings/credits",
    }
    b_url = billing_urls.get(eng, "")
    key = (api_key or "").strip()

    if eng == "system":
        return {
            "engine": eng,
            "supported": False,
            "ok": True,
            "summary": "Offline Windows SAPI 5 — Free (no API key or balance needed)",
            "detail": "",
            "billing_url": "",
        }
    if eng == "auto":
        return {
            "engine": eng,
            "supported": False,
            "ok": True,
            "summary": "Auto mode uses your ready voices in order (OpenAI → Gemini → Groq → Cartesia → ElevenLabs → Deepgram → System)",
            "detail": "",
            "billing_url": "",
        }
    if eng == "cartesia":
        return {
            "engine": eng,
            "supported": False,
            "ok": True,
            "summary": "Live balance unavailable on standard sk_car_ keys (Cartesia restricts billing endpoints to Admin keys) — view credits in Billing",
            "detail": "Leave Overages OFF in Subscription settings to keep a hard monthly cap.",
            "billing_url": b_url,
        }
    if eng in {"openai", "gemini", "groq"}:
        return {
            "engine": eng,
            "supported": False,
            "ok": True,
            "summary": f"{TTS_ENGINE_SHORT_LABELS.get(eng, eng.title())} standard API keys cannot read wallet balance — check your provider Billing portal",
            "detail": "",
            "billing_url": b_url,
        }
    if not key:
        return {
            "engine": eng,
            "supported": False,
            "ok": False,
            "summary": f"No {TTS_ENGINE_SHORT_LABELS.get(eng, eng.title())} API key saved yet",
            "detail": "",
            "billing_url": b_url,
        }

    if eng == "elevenlabs":
        try:
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": key},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                sub = json.loads(resp.read().decode("utf-8", errors="replace"))
            used = int(sub.get("character_count") or 0)
            lim = int(sub.get("character_limit") or 0)
            tier = str(sub.get("tier") or "free").strip()
            rem = max(0, lim - used)
            return {
                "engine": eng,
                "supported": True,
                "ok": True,
                "summary": f"ElevenLabs ({tier}): {rem:,} / {lim:,} chars remaining ({used:,} used)",
                "detail": str(sub.get("status") or ""),
                "billing_url": b_url,
            }
        except urllib.error.HTTPError as exc:
            return {
                "engine": eng,
                "supported": True,
                "ok": False,
                "summary": f"ElevenLabs balance check failed (HTTP {exc.code}) — verify key permissions or Billing",
                "detail": str(exc),
                "billing_url": b_url,
            }
        except Exception as exc:
            return {
                "engine": eng,
                "supported": True,
                "ok": False,
                "summary": f"ElevenLabs balance check failed: {exc}",
                "detail": str(exc),
                "billing_url": b_url,
            }

    if eng == "deepgram":
        try:
            headers = {"Authorization": f"Token {key}"}
            p_req = urllib.request.Request("https://api.deepgram.com/v1/projects", headers=headers, method="GET")
            with urllib.request.urlopen(p_req, timeout=timeout) as resp:
                pdata = json.loads(resp.read().decode("utf-8", errors="replace"))
            projects = pdata.get("projects") or []
            if not projects:
                return {
                    "engine": eng,
                    "supported": True,
                    "ok": False,
                    "summary": "Deepgram key returned no projects — check Deepgram Console",
                    "detail": "",
                    "billing_url": b_url,
                }
            pid = str(projects[0].get("project_id") or "").strip()
            pname = str(projects[0].get("name") or pid).strip()
            b_req = urllib.request.Request(
                f"https://api.deepgram.com/v1/projects/{pid}/balances",
                headers=headers,
                method="GET",
            )
            with urllib.request.urlopen(b_req, timeout=timeout) as resp:
                bdata = json.loads(resp.read().decode("utf-8", errors="replace"))
            balances = bdata.get("balances") or []
            total_usd = sum(float(b.get("amount") or 0.0) for b in balances if str(b.get("units") or "usd").lower() == "usd")
            if not balances:
                sum_txt = f"Deepgram ({pname}): no active credit balance rows"
            else:
                sum_txt = f"Deepgram ({pname}): ${total_usd:,.2f} USD remaining"
            return {
                "engine": eng,
                "supported": True,
                "ok": True,
                "summary": sum_txt,
                "detail": f"{len(balances)} balance item(s)",
                "billing_url": b_url,
            }
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                msg = "Deepgram key lacks billing:read permission (Audio works fine; check balance in Console)"
            else:
                msg = f"Deepgram balance check failed (HTTP {exc.code})"
            return {
                "engine": eng,
                "supported": True,
                "ok": False,
                "summary": msg,
                "detail": str(exc),
                "billing_url": b_url,
            }
        except Exception as exc:
            return {
                "engine": eng,
                "supported": True,
                "ok": False,
                "summary": f"Deepgram balance check failed: {exc}",
                "detail": str(exc),
                "billing_url": b_url,
            }

    if eng == "openrouter":
        from catalog_sync import fetch_openrouter_credits
        cred_res = fetch_openrouter_credits(key, timeout=timeout)
        if cred_res.get("ok"):
            rem = float(cred_res.get("remaining_usd", 0.0) or 0.0)
            tot = float(cred_res.get("total_credits", 0.0) or 0.0)
            used = float(cred_res.get("total_usage", 0.0) or 0.0)
            return {
                "engine": eng,
                "supported": True,
                "ok": True,
                "summary": f"OpenRouter: ${rem:,.2f} USD remaining (${used:,.2f} / ${tot:,.2f} used)",
                "detail": "",
                "billing_url": b_url,
            }
        return {
            "engine": eng,
            "supported": True,
            "ok": False,
            "summary": f"OpenRouter balance check failed: {cred_res.get('error', 'error')}",
            "detail": "",
            "billing_url": b_url,
        }

    return {
        "engine": eng,
        "supported": False,
        "ok": True,
        "summary": "Balance lookup not supported for this engine",
        "detail": "",
        "billing_url": b_url,
    }


def list_available_tts_voices() -> list[str]:
    """Return available TTS voice identifiers/names (OpenAI, Gemini, and installed SAPI 5 voices)."""
    voices = [label for _, label in OPENAI_TTS_VOICES]
    voices.extend(_list_sapi5_voices())
    return voices


def clean_text_for_speech(markdown_text: str) -> str:
    """Strip markdown formatting, code blocks, status banners, and image/patch tags for natural speech."""
    text = markdown_text or ""
    text = re.sub(r"\[IDLE_PATCH[^\]]*\].*?\[/IDLE_PATCH\]", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[IDLE_PATCH[^\]]*\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\[TOOL_OUTPUT[^\]]*\].*?\[/TOOL_OUTPUT\]", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[TOOL:[^\]]*\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[✓⚡⏸]\s*\[[^\]]+\]", " ", text)
    text = re.sub(r"\[GENERATE_IMAGE[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[WEATHER_MAP[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[PALACE_UI_SNAPSHOT[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[SAVE_MEMORY[^\]]*\].*?\[/SAVE_MEMORY\]", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\[SAVE_MEMORY\s+(?:[^\]"]|"[^"]*")*\]', "", text, flags=re.IGNORECASE)
    text = re.sub(r"```.*?```", " [code block omitted] ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?m)^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*$", " ", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#*_~>|`]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:4500]


def split_text_for_streaming_tts(
    text: str,
    *,
    first_chunk_max: int = 200,
    max_chunk_chars: int = 420,
) -> list[str]:
    """Split cleaned text along natural sentence boundaries for low-latency streaming playback."""
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]
    if not sentences:
        return [clean]

    chunks: list[str] = []
    cur = ""
    for sent in sentences:
        limit = first_chunk_max if not chunks else max_chunk_chars
        if len(sent) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
                limit = max_chunk_chars
            # Split long sentence along clauses/commas or word boundaries
            sub_parts = re.split(r"(?<=[,;:])\s+", sent)
            sub_cur = ""
            for sp in sub_parts:
                if not sub_cur:
                    if len(sp) <= limit:
                        sub_cur = sp
                    else:
                        words = sp.split()
                        w_cur = ""
                        for w in words:
                            cand = f"{w_cur} {w}".strip()
                            if len(cand) > limit and w_cur:
                                chunks.append(w_cur)
                                w_cur = w
                                limit = max_chunk_chars
                            else:
                                w_cur = cand
                        if w_cur:
                            sub_cur = w_cur
                elif len(sub_cur) + 1 + len(sp) <= limit:
                    sub_cur = f"{sub_cur} {sp}"
                else:
                    chunks.append(sub_cur)
                    limit = max_chunk_chars
                    sub_cur = sp
            if sub_cur:
                cur = sub_cur
            continue

        if not cur:
            cur = sent
        elif len(cur) + 1 + len(sent) <= limit:
            cur = f"{cur} {sent}"
        else:
            chunks.append(cur)
            cur = sent

    if cur:
        chunks.append(cur)
    return chunks


# --- Windows Native Streaming PCM Output (winmm waveOut) ---

_WAVE_FORMAT_PCM = 1
_WAVE_MAPPER = 0xFFFFFFFF
_WHDR_DONE = 0x00000001


class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class _WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", wintypes.DWORD),
        ("dwLoops", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


def _scale_pcm16_volume(pcm_bytes: bytes, volume_percent: int) -> bytes:
    vol = max(0, min(100, int(volume_percent)))
    if vol >= 100 or len(pcm_bytes) < 2:
        return pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)]
    even_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
    if vol <= 0:
        return b"\x00" * even_len
    samples = array("h")
    samples.frombytes(pcm_bytes[:even_len])
    factor = vol / 100.0
    for i, s in enumerate(samples):
        samples[i] = max(-32767, min(32767, int(s * factor)))
    return samples.tobytes()


def _configure_winmm_prototypes(winmm: Any) -> None:
    """Declare explicit 64-bit ctypes argtypes/restype for winmm.waveOut* calls."""
    try:
        if getattr(winmm, "_palace_prototypes_bound", False):
            return
        if hasattr(winmm, "waveOutOpen") and hasattr(winmm.waveOutOpen, "argtypes"):
            winmm.waveOutOpen.argtypes = [
                ctypes.POINTER(wintypes.HANDLE),
                wintypes.UINT,
                ctypes.POINTER(_WAVEFORMATEX),
                ctypes.c_size_t,
                ctypes.c_size_t,
                wintypes.DWORD,
            ]
            winmm.waveOutOpen.restype = wintypes.UINT
            winmm.waveOutPrepareHeader.argtypes = [wintypes.HANDLE, ctypes.POINTER(_WAVEHDR), wintypes.UINT]
            winmm.waveOutPrepareHeader.restype = wintypes.UINT
            winmm.waveOutWrite.argtypes = [wintypes.HANDLE, ctypes.POINTER(_WAVEHDR), wintypes.UINT]
            winmm.waveOutWrite.restype = wintypes.UINT
            winmm.waveOutUnprepareHeader.argtypes = [wintypes.HANDLE, ctypes.POINTER(_WAVEHDR), wintypes.UINT]
            winmm.waveOutUnprepareHeader.restype = wintypes.UINT
            winmm.waveOutReset.argtypes = [wintypes.HANDLE]
            winmm.waveOutReset.restype = wintypes.UINT
            winmm.waveOutClose.argtypes = [wintypes.HANDLE]
            winmm.waveOutClose.restype = wintypes.UINT
        winmm._palace_prototypes_bound = True
    except Exception:
        pass


class _WaveOutStream:
    """Low-latency 64-bit-safe Windows waveOut PCM streamer with live per-slice volume and stall recovery."""

    SLICE_BYTES = 4096  # default ~85ms at 24 kHz 16-bit mono
    MAX_INFLIGHT = 4    # ~340ms max hardware queue to eliminate underruns while keeping volume live

    @staticmethod
    def compute_slice_bytes(sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> int:
        sr = max(8000, int(sample_rate or 24000))
        block_align = max(2, int(channels or 1) * max(1, int(bits_per_sample or 16) // 8))
        raw_slice = int(sr * block_align * 0.085)  # ~85 ms per buffer (~340 ms across 4 inflight buffers)
        return max(2048, raw_slice - (raw_slice % block_align))

    def __init__(self, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16):
        if os.name != "nt" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            raise RuntimeError("Audio hardware playback disabled in offscreen/non-Windows environment.")
        self.winmm = ctypes.windll.winmm
        _configure_winmm_prototypes(self.winmm)
        self.hwo = wintypes.HANDLE()
        self.sample_rate = max(8000, int(sample_rate or 24000))
        ch = max(1, int(channels or 1))
        bps = max(8, int(bits_per_sample or 16))
        self.slice_bytes = self.compute_slice_bytes(self.sample_rate, ch, bps)
        block_align = max(1, ch * (bps // 8))
        wfx = _WAVEFORMATEX(
            _WAVE_FORMAT_PCM,
            ch,
            self.sample_rate,
            self.sample_rate * block_align,
            block_align,
            bps,
            0,
        )
        rc = self.winmm.waveOutOpen(ctypes.byref(self.hwo), _WAVE_MAPPER, ctypes.byref(wfx), 0, 0, 0)
        if rc != 0:
            raise OSError(f"waveOutOpen failed with code {rc}")
        self._inflight: list[tuple[ctypes.Array[ctypes.c_char], _WAVEHDR]] = []
        self._lock = threading.Lock()
        self._closed = False

    def _reap_done_locked(self) -> int:
        if not self.hwo.value:
            reaped = len(self._inflight)
            self._inflight.clear()
            return reaped
        remaining: list[tuple[ctypes.Array[ctypes.c_char], _WAVEHDR]] = []
        reaped = 0
        for buf, hdr in self._inflight:
            if hdr.dwFlags & _WHDR_DONE:
                reaped += 1
                try:
                    self.winmm.waveOutUnprepareHeader(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
                except Exception:
                    pass
            else:
                remaining.append((buf, hdr))
        self._inflight = remaining
        return reaped

    def write(
        self,
        pcm_bytes: bytes,
        cancel_event: threading.Event,
        *,
        apply_live_volume: bool = True,
        volume_getter: Callable[[], int] | None = None,
    ) -> bool:
        if not pcm_bytes or len(pcm_bytes) < 2 or cancel_event.is_set() or self._closed:
            return False
        even_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
        total_written = 0

        for pos in range(0, even_len, self.slice_bytes):
            raw_slice = pcm_bytes[pos : min(even_len, pos + self.slice_bytes)]
            if len(raw_slice) < 2:
                continue
            last_progress = time.monotonic()
            wrote_slice = False
            while not cancel_event.is_set():
                with self._lock:
                    if self._closed:
                        return total_written > 0
                    if self._reap_done_locked() > 0:
                        last_progress = time.monotonic()
                    if len(self._inflight) < self.MAX_INFLIGHT:
                        if apply_live_volume:
                            vol = volume_getter() if volume_getter is not None else get_live_volume()
                            payload = _scale_pcm16_volume(raw_slice, vol)
                        else:
                            payload = raw_slice
                        if not payload:
                            wrote_slice = True
                            break
                        buf = ctypes.create_string_buffer(payload, len(payload))
                        hdr = _WAVEHDR(ctypes.cast(buf, ctypes.c_void_p), len(payload), 0, 0, 0, 0, None, 0)
                        rc_prep = self.winmm.waveOutPrepareHeader(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
                        if rc_prep == 0:
                            rc_wr = self.winmm.waveOutWrite(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
                            if rc_wr == 0:
                                self._inflight.append((buf, hdr))
                                total_written += len(payload)
                                wrote_slice = True
                                try:
                                    slice_dur = len(payload) / float(max(1, self.sample_rate * 2))
                                    delay_sec = max(0.0, (len(self._inflight) - 1) * slice_dur)
                                    record_tts_pcm_telemetry(payload, self.sample_rate, delay_sec)
                                except Exception:
                                    pass
                                break
                            _log_voice_diagnostic(f"waveOutWrite failed rc={rc_wr}")
                            try:
                                self.winmm.waveOutUnprepareHeader(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
                            except Exception:
                                pass
                        else:
                            _log_voice_diagnostic(f"waveOutPrepareHeader failed rc={rc_prep}")
                        return False
                if (time.monotonic() - last_progress) > 3.0:
                    _log_voice_diagnostic("waveOutStream.write stalled >3.0s; resetting device handle")
                    self.stop()
                    return False
                time.sleep(0.012)
            if cancel_event.is_set() or not wrote_slice:
                return total_written > 0 and cancel_event.is_set()
        return total_written > 0

    def drain(self, cancel_event: threading.Event) -> None:
        last_progress = time.monotonic()
        while not cancel_event.is_set():
            with self._lock:
                if self._closed:
                    return
                if self._reap_done_locked() > 0:
                    last_progress = time.monotonic()
                if not self._inflight:
                    return
            if (time.monotonic() - last_progress) > 3.0:
                _log_voice_diagnostic("waveOutStream.drain stalled >3.0s; resetting handle")
                self.stop()
                return
            time.sleep(0.012)

    def stop(self) -> None:
        clear_tts_audio_telemetry()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            hval = self.hwo.value
            if hval:
                try:
                    self.winmm.waveOutReset(self.hwo)
                except Exception:
                    pass
                for _, hdr in self._inflight:
                    try:
                        self.winmm.waveOutUnprepareHeader(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
                    except Exception:
                        pass
                self._inflight.clear()
                try:
                    self.winmm.waveOutClose(self.hwo)
                except Exception:
                    pass
                self.hwo.value = None


def _decode_audio_payload(raw_bytes: bytes, mime_type: str = "") -> tuple[bytes, int]:
    """Decode WAV or raw PCM L16 payload into normalized (pcm16_mono_bytes, sample_rate)."""
    if not raw_bytes:
        return b"", 24000
    mime_low = (mime_type or "").lower()
    if raw_bytes[:4] == b"RIFF" or "wav" in mime_low:
        with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
            ch = max(1, wf.getnchannels())
            sw = wf.getsampwidth()
            sr = int(wf.getframerate() or 24000)
            frames = wf.readframes(wf.getnframes())
        if sw == 2 and ch == 1:
            return frames[: len(frames) - (len(frames) % 2)], sr
        fmt_name = "Int16" if sw == 2 else ("UInt8" if sw == 1 else "Int32")
        pcm16, _ = pcm_chunk_to_int16_mono_and_level(frames, fmt_name, ch, gain_percent=100)
        return pcm16, sr

    sr = 24000
    m = re.search(r"rate\s*=\s*(\d+)", mime_low)
    if m:
        try:
            sr = max(8000, min(48000, int(m.group(1))))
        except ValueError:
            sr = 24000
    even_len = len(raw_bytes) - (len(raw_bytes) % 2)
    return raw_bytes[:even_len], sr


def _stream_openai_pcm(
    chunk_text: str,
    *,
    api_key: str,
    voice: str,
    instructions: str,
    speed: float,
    cancel_event: threading.Event | None = None,
):
    """Yield even-aligned 24 kHz 16-bit mono PCM chunks from OpenAI gpt-4o-mini-tts (fallback tts-1)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=25.0, max_retries=0)
    v_name = _OPENAI_VOICE_IDS.get((voice or "coral").strip().lower(), "coral")
    sp = _clamp_speed(speed)
    attempts = [
        {"model": "gpt-4o-mini-tts", "voice": v_name, "input": chunk_text, "response_format": "pcm", "speed": sp, "instructions": instructions},
        {"model": "tts-1", "voice": v_name if v_name in {"alloy", "echo", "fable", "onyx", "nova", "shimmer"} else "nova", "input": chunk_text, "response_format": "pcm", "speed": sp},
    ]
    last_exc: Exception | None = None
    for kwargs in attempts:
        try:
            carry = b""
            with client.audio.speech.with_streaming_response.create(**kwargs) as resp:
                for raw_chunk in resp.iter_bytes(chunk_size=4096):
                    if cancel_event is not None and cancel_event.is_set():
                        return
                    if not raw_chunk:
                        continue
                    buf = carry + raw_chunk
                    usable = len(buf) - (len(buf) % 2)
                    if usable:
                        yield buf[:usable]
                    carry = buf[usable:]
            return
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc


def _synthesize_gemini_pcm(
    chunk_text: str,
    *,
    api_key: str,
    voice: str = "Kore",
    instructions: str = "",
) -> tuple[bytes, int, str]:
    """Synthesize a single chunk using Gemini Neural TTS and return (pcm16_mono_bytes, sample_rate, model_name)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=30000))
    gv = _GEMINI_VOICE_IDS.get((voice or "Kore").strip().lower(), "Kore")
    prompt = f"{instructions.strip()}\nRead aloud naturally:\n{chunk_text}".strip() if instructions else chunk_text
    last_exc: Exception | None = None
    for gm in ("gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts"):
        try:
            resp = client.models.generate_content(
                model=gm,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=gv)
                        )
                    ),
                ),
            )
            cands = getattr(resp, "candidates", None) or []
            if cands:
                parts = getattr(getattr(cands[0], "content", None), "parts", None) or []
                for part in parts:
                    inline = getattr(part, "inline_data", None)
                    raw_data = getattr(inline, "data", None) if inline is not None else None
                    if raw_data:
                        pcm, sr = _decode_audio_payload(raw_data, getattr(inline, "mime_type", "") or "")
                        if pcm:
                            return pcm, sr, gm
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"Gemini Neural TTS unavailable: {last_exc}")


def _split_short_tts_chunks(text: str, max_len: int = 190) -> list[str]:
    """Split text into <=max_len chunks at natural punctuation/whitespace for providers like Groq Orpheus."""
    clean = " ".join((text or "").split())
    if not clean:
        return []
    out: list[str] = []
    cur = clean
    while len(cur) > max_len:
        cut = -1
        for sep in (". ", "! ", "? ", "; ", ", ", " "):
            pos = cur.rfind(sep, 0, max_len + 1)
            if pos > 20:
                cut = pos + (1 if sep != " " else 0)
                break
        if cut <= 0:
            cut = max_len
        piece = cur[:cut].strip()
        if piece:
            out.append(piece)
        cur = cur[cut:].strip()
    if cur:
        out.append(cur)
    return out


def _synthesize_groq_orpheus_pcm(
    chunk_text: str,
    *,
    api_key: str,
    voice: str = "autumn",
    cancel_event: threading.Event | None = None,
) -> tuple[bytes, int]:
    """Synthesize a chunk via Groq canopylabs/orpheus-v1-english and return (pcm16_mono_bytes, sample_rate)."""
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
        timeout=25.0,
        max_retries=0,
    )
    gv = _GROQ_VOICE_IDS.get((voice or "autumn").strip().lower(), "autumn")
    combined_pcm = bytearray()
    out_sr = 24000
    for sub in _split_short_tts_chunks(chunk_text, max_len=190):
        if cancel_event is not None and cancel_event.is_set():
            break
        raw_buf = bytearray()
        with client.audio.speech.with_streaming_response.create(
            model="canopylabs/orpheus-v1-english",
            voice=gv,
            input=sub,
            response_format="wav",
        ) as resp:
            for piece in resp.iter_bytes(chunk_size=8192):
                if cancel_event is not None and cancel_event.is_set():
                    return b"", out_sr
                if piece:
                    raw_buf.extend(piece)
        if cancel_event is not None and cancel_event.is_set():
            break
        pcm, sr = _decode_audio_payload(bytes(raw_buf), "audio/wav")
        if pcm:
            combined_pcm.extend(pcm)
            out_sr = sr
    return bytes(combined_pcm), out_sr


def _synthesize_openrouter_audio_pcm(
    chunk_text: str,
    *,
    api_key: str,
    voice: str = "coral",
    cancel_event: threading.Event | None = None,
) -> tuple[bytes, int]:
    """Synthesize spoken audio via OpenRouter `openai/gpt-audio-mini` (`modalities: [text, audio]`) cleanly."""
    clean_key = (api_key or "").strip()
    if not clean_key:
        raise ValueError("openrouter: missing API key")
    ov = (voice or "coral").strip().lower()
    if ov not in _OPENAI_VOICE_IDS:
        ov = "coral"
    if cancel_event is not None and cancel_event.is_set():
        return b"", 24000
    body = json.dumps({
        "model": "openai/gpt-audio-mini",
        "modalities": ["text", "audio"],
        "audio": {"voice": ov, "format": "wav"},
        "messages": [
            {
                "role": "system",
                "content": "Read the user text aloud verbatim with natural warmth and pacing. Do not add commentary or extra words.",
            },
            {"role": "user", "content": str(chunk_text or "").strip()},
        ],
    }).encode("utf-8")
    req = urllib_request_req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {clean_key}",
            "HTTP-Referer": "https://fairybread.me",
            "X-Title": "Fairybread",
        },
        method="POST",
    )
    with urllib.request.urlopen(urllib_request_req, timeout=30.0) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    msg0 = (((payload.get("choices") or [{}])[0]).get("message") or {})
    aud = msg0.get("audio") or {}
    b64_data = str(aud.get("data") or "").strip()
    if not b64_data:
        raise RuntimeError("OpenRouter audio response did not contain wav audio payload")
    raw_bytes = base64.b64decode(b64_data)
    return _decode_audio_payload(raw_bytes, "audio/wav")


def _iter_http_pcm_stream(req: urllib.request.Request, *, cancel_event: threading.Event | None = None, timeout: float = 25.0):
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        carry = b""
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return
            raw_chunk = resp.read(4096)
            if not raw_chunk:
                break
            buf = carry + raw_chunk
            usable = len(buf) - (len(buf) % 2)
            if usable:
                yield buf[:usable]
            carry = buf[usable:]


def _stream_cartesia_pcm(
    chunk_text: str,
    *,
    api_key: str,
    voice_id: str,
    speed: float = 1.0,
    cancel_event: threading.Event | None = None,
):
    """Stream raw 44.1 kHz 16-bit mono PCM chunks from Cartesia Sonic TTS over HTTPS."""
    clean_key = (api_key or "").strip()
    if not clean_key:
        raise ValueError("cartesia: missing API key")
    vid = (voice_id or DEFAULT_VOICE_SETTINGS["cartesia_voice_id"]).strip()
    body = json.dumps({
        "model_id": "sonic-latest",
        "transcript": chunk_text,
        "voice": {"mode": "id", "id": vid},
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": CARTESIA_SAMPLE_RATE,
        },
        "generation_config": {
            "speed": _clamp_speed(speed),
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.cartesia.ai/tts/bytes",
        data=body,
        headers={
            "X-API-Key": clean_key,
            "Cartesia-Version": "2025-04-16",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    yield from _iter_http_pcm_stream(req, cancel_event=cancel_event)


def _stream_elevenlabs_pcm(
    chunk_text: str,
    *,
    api_key: str,
    voice_id: str,
    cancel_event: threading.Event | None = None,
):
    """Stream raw 24kHz 16-bit mono PCM chunks from ElevenLabs Flash/Multilingual TTS over HTTPS."""
    vid = (voice_id or DEFAULT_VOICE_SETTINGS["elevenlabs_voice_id"]).strip()
    body = json.dumps({
        "text": chunk_text,
        "model_id": "eleven_flash_v2_5",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream?output_format=pcm_24000",
        data=body,
        headers={
            "xi-api-key": api_key.strip(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    yield from _iter_http_pcm_stream(req, cancel_event=cancel_event)


def _stream_deepgram_pcm(
    chunk_text: str,
    *,
    api_key: str,
    voice_model: str,
    speed: float = 1.0,
    expressivity: int = 0,
    cancel_event: threading.Event | None = None,
):
    """Stream raw 24kHz 16-bit mono PCM chunks from Deepgram Flux (/v2/speak) or Aura (/v1/speak)."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Deepgram API key is missing.")
    vm = _normalize_deepgram_voice_model(voice_model)
    if vm.startswith("flux-"):
        try:
            spd_val = float(speed or 1.0)
        except (TypeError, ValueError):
            spd_val = 1.0
        spd = max(0.5, min(1.5, round(spd_val, 2)))
        expr = _clamp_deepgram_expressivity(expressivity)
        url = (
            f"https://api.deepgram.com/v2/speak?model={vm}&speed={spd:g}&expressivity={expr}"
            "&encoding=linear16&sample_rate=24000&container=none"
        )
    else:
        url = f"https://api.deepgram.com/v1/speak?model={vm}&encoding=linear16&sample_rate=24000&container=none"
    body = json.dumps({"text": chunk_text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Token {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    yield from _iter_http_pcm_stream(req, cancel_event=cancel_event)


def _speak_windows_sapi5(
    spoken: str,
    *,
    voice_name: str,
    volume_percent: int,
    speed: float,
    gen_token: int,
) -> bool:
    if os.name != "nt" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    global _ACTIVE_TTS_PROC, _LAST_TTS_ENGINE_USED
    tmp_txt = Path(tempfile.gettempdir()) / "fairybread_tts_utterance.txt"
    tmp_txt.write_text(spoken, encoding="utf-8")
    select_voice_cmd = ""
    if voice_name and voice_name != "System Default" and voice_name.lower() not in _OPENAI_VOICE_IDS and voice_name.lower() not in _GEMINI_VOICE_IDS:
        safe_v = voice_name.replace("'", "''")
        select_voice_cmd = f"try {{ $s.SelectVoice('{safe_v}') }} catch {{}}; "
    rate = max(-4, min(4, int(round((_clamp_speed(speed) - 1.0) * 10))))
    ps_cmd = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Volume = {max(0, min(100, int(volume_percent)))}; "
        f"$s.Rate = {rate}; "
        f"{select_voice_cmd}"
        f"$txt = Get-Content -LiteralPath '{tmp_txt}' -Raw -Encoding UTF8; "
        "$s.Speak($txt)"
    )
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    with _TTS_LOCK:
        if _SPEECH_GEN != gen_token:
            try:
                proc.terminate()
            except Exception:
                pass
            return False
        _ACTIVE_TTS_PROC = proc
        _LAST_TTS_ENGINE_USED = "system:sapi5"
    proc.wait()
    return True


def synthesize_speech_pcm(
    text: str,
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
    engine_override: str | None = None,
) -> tuple[bytes, int, str]:
    """Synchronously synthesize short/test text into (pcm16_mono_bytes, sample_rate, engine_used) using fallback chain."""
    spoken = clean_text_for_speech(text)
    if not spoken:
        raise ValueError("No speakable text provided.")
    cfg = load_voice_settings(config_path)
    store = credential_store or CredentialStore()
    engine = (engine_override or cfg.get("tts_engine") or "auto").strip().lower()
    speed = _clamp_speed(cfg.get("speech_speed", 1.0))
    style_instr = build_voice_style_instructions(
        str(cfg.get("voice_style") or "warm_american"),
        str(cfg.get("custom_style_prompt") or ""),
        speed,
    )

    order = {
        "auto": ["openai", "gemini", "groq", "openrouter"],
        "openai": ["openai", "gemini", "groq", "openrouter"],
        "gemini": ["gemini", "openai", "groq", "openrouter"],
        "groq": ["groq", "openai", "gemini", "openrouter"],
        "openrouter": ["openrouter", "openai", "gemini"],
        "cartesia": ["cartesia", "openai", "gemini", "openrouter"],
        "elevenlabs": ["elevenlabs", "openai", "gemini", "openrouter"],
        "deepgram": ["deepgram", "openai", "gemini", "openrouter"],
        "system": [],
    }.get(engine, ["openai", "gemini", "groq", "openrouter"])

    errors: list[str] = []
    for candidate in order:
        if candidate == "openai":
            oai_key = store.get_api_key("openai")
            if not oai_key:
                errors.append("openai: missing API key")
                continue
            try:
                buf = bytearray()
                for c_bytes in _stream_openai_pcm(
                    spoken,
                    api_key=oai_key,
                    voice=str(cfg.get("voice_name") or "coral"),
                    instructions=style_instr,
                    speed=speed,
                ):
                    buf.extend(c_bytes)
                if buf:
                    return bytes(buf), 24000, "openai:gpt-4o-mini-tts"
            except Exception as exc:
                errors.append(f"openai: {exc}")
        elif candidate == "gemini":
            gem_key = store.get_api_key("gemini")
            if not gem_key:
                errors.append("gemini: missing API key")
                continue
            try:
                pcm, sr, gm = _synthesize_gemini_pcm(
                    spoken,
                    api_key=gem_key,
                    voice=str(cfg.get("gemini_voice_name") or "Kore"),
                    instructions=style_instr,
                )
                if pcm:
                    return pcm, sr, f"gemini:{gm}"
            except Exception as exc:
                errors.append(f"gemini: {exc}")
        elif candidate == "groq":
            gr_key = store.get_api_key("groq")
            if not gr_key:
                errors.append("groq: missing API key")
                continue
            try:
                pcm, sr = _synthesize_groq_orpheus_pcm(
                    spoken,
                    api_key=gr_key,
                    voice=str(cfg.get("groq_voice_name") or "autumn"),
                )
                if pcm:
                    return pcm, sr, "groq:canopylabs/orpheus-v1-english"
            except Exception as exc:
                errors.append(f"groq: {exc}")
        elif candidate == "openrouter":
            or_key = store.get_api_key("openrouter")
            if not or_key:
                errors.append("openrouter: missing API key")
                continue
            try:
                pcm, sr = _synthesize_openrouter_audio_pcm(
                    spoken,
                    api_key=or_key,
                    voice=str(cfg.get("voice_name") or "coral"),
                )
                if pcm:
                    return pcm, sr, "openrouter:gpt-audio-mini"
            except Exception as exc:
                errors.append(f"openrouter: {exc}")
        elif candidate == "cartesia":
            ckey = store.get_api_key("cartesia")
            if not ckey:
                errors.append("cartesia: missing API key")
                continue
            try:
                buf = bytearray()
                for c_bytes in _stream_cartesia_pcm(
                    spoken,
                    api_key=ckey,
                    voice_id=str(cfg.get("cartesia_voice_id") or DEFAULT_VOICE_SETTINGS["cartesia_voice_id"]),
                    speed=speed,
                ):
                    buf.extend(c_bytes)
                if buf:
                    return bytes(buf), CARTESIA_SAMPLE_RATE, "cartesia:sonic-latest"
            except Exception as exc:
                errors.append(f"cartesia: {exc}")
        elif candidate == "elevenlabs":
            ekey = store.get_api_key("elevenlabs")
            if not ekey:
                errors.append("elevenlabs: missing API key")
                continue
            try:
                buf = bytearray()
                for c_bytes in _stream_elevenlabs_pcm(
                    spoken,
                    api_key=ekey,
                    voice_id=str(cfg.get("elevenlabs_voice_id") or DEFAULT_VOICE_SETTINGS["elevenlabs_voice_id"]),
                ):
                    buf.extend(c_bytes)
                if buf:
                    return bytes(buf), 24000, "elevenlabs:eleven_flash_v2_5"
            except Exception as exc:
                errors.append(f"elevenlabs: {exc}")
        elif candidate == "deepgram":
            dkey = store.get_api_key("deepgram")
            if not dkey:
                errors.append("deepgram: missing API key")
                continue
            try:
                dg_vm = _normalize_deepgram_voice_model(str(cfg.get("deepgram_voice_name") or ""))
                dg_expr = _clamp_deepgram_expressivity(cfg.get("deepgram_expressivity", 0))
                buf = bytearray()
                for c_bytes in _stream_deepgram_pcm(
                    spoken,
                    api_key=dkey,
                    voice_model=dg_vm,
                    speed=speed,
                    expressivity=dg_expr,
                ):
                    buf.extend(c_bytes)
                if buf:
                    return bytes(buf), 24000, f"deepgram:{dg_vm}"
            except Exception as exc:
                errors.append(f"deepgram: {exc}")

    raise RuntimeError("No neural TTS engine succeeded (" + "; ".join(errors or ["system mode selected"]) + ")")


def stop_speaking() -> None:
    """Immediately stop any active neural or system speech playback."""
    global _SPEECH_GEN, _ACTIVE_CANCEL_EVENT, _ACTIVE_WAVEOUT, _ACTIVE_TTS_PROC, _TTS_SPEAKING, _TTS_LAST_END_MONO
    clear_tts_audio_telemetry()
    with _TTS_LOCK:
        _SPEECH_GEN += 1
        was_speaking = _TTS_SPEAKING or (_ACTIVE_TTS_PROC is not None) or (_ACTIVE_WAVEOUT is not None)
        _TTS_SPEAKING = False
        if _ACTIVE_CANCEL_EVENT is not None:
            _ACTIVE_CANCEL_EVENT.set()
            _ACTIVE_CANCEL_EVENT = None
        if _ACTIVE_WAVEOUT is not None:
            try:
                _ACTIVE_WAVEOUT.stop()
            except Exception:
                pass
            _ACTIVE_WAVEOUT = None
        if _ACTIVE_TTS_PROC is not None:
            try:
                _ACTIVE_TTS_PROC.terminate()
            except Exception:
                pass
            _ACTIVE_TTS_PROC = None
        if was_speaking:
            _TTS_LAST_END_MONO = time.monotonic()


def _build_tts_candidate_order(
    primary_engine: str,
    fallback_engine: str,
    store: CredentialStore,
) -> list[str]:
    pri = (primary_engine or "auto").strip().lower()
    fb = (fallback_engine or "auto").strip().lower()
    all_ready = [
        eid
        for eid in ("openai", "gemini", "groq", "openrouter", "cartesia", "elevenlabs", "deepgram")
        if is_tts_engine_ready(eid, credential_store=store)
    ]
    order: list[str] = []
    if pri == "auto":
        for eid in ("openai", "gemini", "groq", "openrouter"):
            if eid not in order:
                order.append(eid)
        for eid in all_ready:
            if eid not in order:
                order.append(eid)
        if fb not in {"auto", "none"} and fb not in order:
            order.append(fb)
        if fb != "none" and "system" not in order:
            order.append("system")
        return order

    order.append(pri)
    if fb == "none":
        return order
    if fb != "auto":
        if fb not in order:
            order.append(fb)
        return order
    for eid in all_ready:
        if eid not in order:
            order.append(eid)
    if "system" not in order:
        order.append("system")
    return order


def speak_agent_response(
    text: str,
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
    on_engine_status: Callable[[str], None] | None = None,
    on_finished: Callable[[], None] | None = None,
    on_speech_meta: Callable[[dict[str, Any]], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> bool:
    """Speak an agent or Voice Companion response aloud with streaming human neural TTS and automatic fallbacks."""
    global _SPEECH_GEN, _ACTIVE_CANCEL_EVENT, _ACTIVE_WAVEOUT, _TTS_SPEAKING, _TTS_LAST_END_MONO, _LAST_TTS_ENGINE_USED

    stop_speaking()
    spoken = clean_text_for_speech(text)
    if not spoken:
        return False
    cfg = load_voice_settings(config_path)
    vol = get_live_volume(config_path)
    if vol == 0:
        return False

    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False

    store = credential_store or CredentialStore()
    engine = str(cfg.get("tts_engine") or "auto").strip().lower()
    fb_engine = str(cfg.get("tts_fallback_engine") or "auto").strip().lower()
    speed = _clamp_speed(cfg.get("speech_speed", 1.0))
    style_instr = build_voice_style_instructions(
        str(cfg.get("voice_style") or "warm_american"),
        str(cfg.get("custom_style_prompt") or ""),
        speed,
    )
    voice_name = str(cfg.get("voice_name") or "coral").strip()
    gemini_voice = str(cfg.get("gemini_voice_name") or "Kore").strip()
    groq_voice = str(cfg.get("groq_voice_name") or "autumn").strip()
    cartesia_vid = str(cfg.get("cartesia_voice_id") or DEFAULT_VOICE_SETTINGS["cartesia_voice_id"]).strip()
    eleven_vid = str(cfg.get("elevenlabs_voice_id") or DEFAULT_VOICE_SETTINGS["elevenlabs_voice_id"]).strip()
    deepgram_voice = _normalize_deepgram_voice_model(str(cfg.get("deepgram_voice_name") or ""))
    deepgram_expressivity = _clamp_deepgram_expressivity(cfg.get("deepgram_expressivity", 0))
    system_voice = str(cfg.get("system_voice_name") or "System Default").strip()

    cancel_ev = threading.Event()
    with _TTS_LOCK:
        _SPEECH_GEN += 1
        gen_token = _SPEECH_GEN
        _ACTIVE_CANCEL_EVENT = cancel_ev
        _TTS_SPEAKING = True

    def _run_playback():
        global _TTS_SPEAKING, _TTS_LAST_END_MONO, _ACTIVE_WAVEOUT, _LAST_TTS_ENGINE_USED
        stream: _WaveOutStream | None = None
        played_any = False
        meta_emitted = False
        errors: list[str] = []
        vol_getter = lambda _cfg_p=config_path: get_live_volume(_cfg_p)
        try:
            chunks = split_text_for_streaming_tts(spoken)
            if not chunks:
                return

            order = _build_tts_candidate_order(engine, fb_engine, store)
            primary_expected = engine if engine != "auto" else next(
                (c for c in order if is_tts_engine_ready(c, credential_store=store)),
                order[0] if order else "openai",
            )

            def _emit_meta(cand_id: str, v_label: str) -> None:
                nonlocal meta_emitted
                if meta_emitted:
                    return
                meta_emitted = True
                fell_back_flag = bool(errors) and (cand_id != primary_expected or engine != "auto")
                fb_reason_txt = errors[0] if (fell_back_flag and errors) else ""
                meta = {
                    "engine_id": cand_id,
                    "engine_label": TTS_ENGINE_SHORT_LABELS.get(cand_id, cand_id),
                    "voice_label": v_label,
                    "requested_engine": primary_expected,
                    "fell_back": fell_back_flag,
                    "fallback_reason": fb_reason_txt,
                }
                with _TTS_LOCK:
                    _LAST_TTS_STATE.update({
                        "engine_id": meta["engine_id"],
                        "engine_label": meta["engine_label"],
                        "voice_label": meta["voice_label"],
                        "requested_engine": meta["requested_engine"],
                        "fell_back": fell_back_flag,
                        "fallback_reason": fb_reason_txt,
                        "last_error": fb_reason_txt,
                        "updated_ts": time.time(),
                    })
                if on_speech_meta is not None:
                    try:
                        on_speech_meta(meta)
                    except Exception:
                        pass

            def _write_or_raise(pcm_bytes: bytes, cand_name: str) -> None:
                nonlocal played_any
                if not pcm_bytes or len(pcm_bytes) < 2:
                    return
                ok_w = stream.write(
                    pcm_bytes,
                    cancel_ev,
                    apply_live_volume=True,
                    volume_getter=vol_getter,
                )
                if not ok_w:
                    if cancel_ev.is_set():
                        return
                    raise OSError(f"{cand_name}: audio device write failed")
                played_any = True

            for candidate in order:
                if cancel_ev.is_set():
                    break

                if candidate == "openai":
                    oai_key = store.get_api_key("openai")
                    if not oai_key:
                        if engine == "openai":
                            errors.append("openai: missing API key")
                        continue
                    try:
                        for ch_txt in chunks:
                            if cancel_ev.is_set():
                                break
                            ch_pcm_bytes = 0
                            for pcm_piece in _stream_openai_pcm(
                                ch_txt,
                                api_key=oai_key,
                                voice=voice_name,
                                instructions=style_instr,
                                speed=speed,
                                cancel_event=cancel_ev,
                            ):
                                if cancel_ev.is_set():
                                    break
                                if not pcm_piece or len(pcm_piece) < 2:
                                    continue
                                if stream is None:
                                    stream = _WaveOutStream(sample_rate=24000, channels=1, bits_per_sample=16)
                                    with _TTS_LOCK:
                                        if _SPEECH_GEN != gen_token or cancel_ev.is_set():
                                            stream.stop()
                                            stream = None
                                            break
                                        _ACTIVE_WAVEOUT = stream
                                        _LAST_TTS_ENGINE_USED = f"openai:gpt-4o-mini-tts ({voice_name})"
                                    if on_engine_status is not None:
                                        try:
                                            on_engine_status(_LAST_TTS_ENGINE_USED)
                                        except Exception:
                                            pass
                                _write_or_raise(pcm_piece, "openai")
                                _emit_meta("openai", voice_name)
                                ch_pcm_bytes += len(pcm_piece)
                            if ch_pcm_bytes > 0:
                                try:
                                    from cost_service import emit_tts_cost
                                    emit_tts_cost("openai:gpt-4o-mini-tts", ch_pcm_bytes / 48000.0)
                                except Exception:
                                    pass
                        if not cancel_ev.is_set() and played_any:
                            stream.drain(cancel_ev)
                        if played_any:
                            break
                    except Exception as exc:
                        err_s = f"openai: {exc}"
                        errors.append(err_s)
                        _log_voice_diagnostic(err_s)
                        if stream is not None:
                            stream.stop()
                            stream = None
                        if played_any:
                            break
                        continue

                elif candidate == "gemini":
                    gem_key = store.get_api_key("gemini")
                    if not gem_key:
                        if engine == "gemini":
                            errors.append("gemini: missing API key")
                        continue
                    try:
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            fut = pool.submit(
                                _synthesize_gemini_pcm,
                                chunks[0],
                                api_key=gem_key,
                                voice=gemini_voice,
                                instructions=style_instr,
                            )
                            for idx in range(len(chunks)):
                                if cancel_ev.is_set():
                                    break
                                pcm, sr, gm = fut.result()
                                next_fut = None
                                if idx + 1 < len(chunks) and not cancel_ev.is_set():
                                    next_fut = pool.submit(
                                        _synthesize_gemini_pcm,
                                        chunks[idx + 1],
                                        api_key=gem_key,
                                        voice=gemini_voice,
                                        instructions=style_instr,
                                    )
                                if stream is None:
                                    stream = _WaveOutStream(sample_rate=sr, channels=1, bits_per_sample=16)
                                    with _TTS_LOCK:
                                        if _SPEECH_GEN != gen_token or cancel_ev.is_set():
                                            stream.stop()
                                            stream = None
                                            break
                                        _ACTIVE_WAVEOUT = stream
                                        _LAST_TTS_ENGINE_USED = f"gemini:{gm} ({gemini_voice})"
                                    if on_engine_status is not None:
                                        try:
                                            on_engine_status(_LAST_TTS_ENGINE_USED)
                                        except Exception:
                                            pass
                                _write_or_raise(pcm, "gemini")
                                _emit_meta("gemini", gemini_voice)
                                if pcm and played_any:
                                    try:
                                        from cost_service import emit_tts_cost
                                        emit_tts_cost(f"gemini:{gm}", len(pcm) / (float(sr or 24000) * 2.0))
                                    except Exception:
                                        pass
                                fut = next_fut
                        if stream is not None and not cancel_ev.is_set() and played_any:
                            stream.drain(cancel_ev)
                        if played_any:
                            break
                    except Exception as exc:
                        err_s = f"gemini: {exc}"
                        errors.append(err_s)
                        _log_voice_diagnostic(err_s)
                        if stream is not None:
                            stream.stop()
                            stream = None
                        if played_any:
                            break
                        continue

                elif candidate == "groq":
                    gr_key = store.get_api_key("groq")
                    if not gr_key:
                        if engine == "groq":
                            errors.append("groq: missing API key")
                        continue
                    try:
                        for ch_txt in chunks:
                            if cancel_ev.is_set():
                                break
                            pcm, sr = _synthesize_groq_orpheus_pcm(
                                ch_txt,
                                api_key=gr_key,
                                voice=groq_voice,
                                cancel_event=cancel_ev,
                            )
                            if not pcm:
                                continue
                            if stream is None:
                                stream = _WaveOutStream(sample_rate=sr, channels=1, bits_per_sample=16)
                                with _TTS_LOCK:
                                    if _SPEECH_GEN != gen_token or cancel_ev.is_set():
                                        stream.stop()
                                        stream = None
                                        break
                                    _ACTIVE_WAVEOUT = stream
                                    _LAST_TTS_ENGINE_USED = f"groq:orpheus ({groq_voice})"
                                if on_engine_status is not None:
                                    try:
                                        on_engine_status(_LAST_TTS_ENGINE_USED)
                                    except Exception:
                                        pass
                            _write_or_raise(pcm, "groq")
                            _emit_meta("groq", groq_voice)
                            try:
                                from cost_service import emit_tts_cost
                                emit_tts_cost("groq:canopylabs/orpheus-v1-english", len(pcm) / (float(sr or 24000) * 2.0), char_count=len(ch_txt))
                            except Exception:
                                pass
                        if stream is not None and not cancel_ev.is_set() and played_any:
                            stream.drain(cancel_ev)
                        if played_any:
                            break
                    except Exception as exc:
                        err_s = f"groq: {exc}"
                        errors.append(err_s)
                        _log_voice_diagnostic(err_s)
                        if stream is not None:
                            stream.stop()
                            stream = None
                        if played_any:
                            break
                        continue

                elif candidate == "openrouter":
                    or_key = store.get_api_key("openrouter")
                    if not or_key:
                        if engine == "openrouter":
                            errors.append("openrouter: missing API key")
                        continue
                    try:
                        or_voice = voice_name or "coral"
                        for ch_txt in chunks:
                            if cancel_ev.is_set():
                                break
                            pcm, sr = _synthesize_openrouter_audio_pcm(
                                ch_txt,
                                api_key=or_key,
                                voice=or_voice,
                                cancel_event=cancel_ev,
                            )
                            if not pcm:
                                continue
                            if stream is None:
                                stream = _WaveOutStream(sample_rate=sr, channels=1, bits_per_sample=16)
                                with _TTS_LOCK:
                                    if _SPEECH_GEN != gen_token or cancel_ev.is_set():
                                        stream.stop()
                                        stream = None
                                        break
                                    _ACTIVE_WAVEOUT = stream
                                    _LAST_TTS_ENGINE_USED = f"openrouter:gpt-audio-mini ({or_voice})"
                                if on_engine_status is not None:
                                    try:
                                        on_engine_status(_LAST_TTS_ENGINE_USED)
                                    except Exception:
                                        pass
                            _write_or_raise(pcm, "openrouter")
                            _emit_meta("openrouter", or_voice)
                            try:
                                from cost_service import emit_tts_cost
                                emit_tts_cost("openrouter:gpt-audio-mini", len(pcm) / (float(sr or 24000) * 2.0), char_count=len(ch_txt))
                            except Exception:
                                pass
                        if stream is not None and not cancel_ev.is_set() and played_any:
                            stream.drain(cancel_ev)
                        if played_any:
                            break
                    except Exception as exc:
                        err_s = f"openrouter: {exc}"
                        errors.append(err_s)
                        _log_voice_diagnostic(err_s)
                        if stream is not None:
                            stream.stop()
                            stream = None
                        if played_any:
                            break
                        continue

                elif candidate in {"cartesia", "elevenlabs", "deepgram"}:
                    ext_key = store.get_api_key(candidate)
                    if not ext_key:
                        if engine == candidate:
                            errors.append(f"{candidate}: missing API key")
                        continue
                    try:
                        if candidate == "cartesia":
                            v_disp = dict(CARTESIA_TTS_VOICES).get(cartesia_vid, "Sonic")
                            model_tag = "cartesia:sonic-latest"
                            cand_sr = CARTESIA_SAMPLE_RATE
                        elif candidate == "elevenlabs":
                            v_disp = dict(ELEVENLABS_TTS_VOICES).get(eleven_vid, "ElevenLabs")
                            model_tag = "elevenlabs:eleven_flash_v2_5"
                            cand_sr = 24000
                        else:
                            v_disp = dict(DEEPGRAM_TTS_VOICES).get(deepgram_voice, deepgram_voice)
                            model_tag = f"deepgram:{deepgram_voice}"
                            cand_sr = 24000
                        v_short = v_disp.split("—", 1)[0].strip() if "—" in v_disp else v_disp
                        for ch_txt in chunks:
                            if cancel_ev.is_set():
                                break
                            if candidate == "cartesia":
                                gen_pcm = _stream_cartesia_pcm(ch_txt, api_key=ext_key, voice_id=cartesia_vid, speed=speed, cancel_event=cancel_ev)
                            elif candidate == "elevenlabs":
                                gen_pcm = _stream_elevenlabs_pcm(ch_txt, api_key=ext_key, voice_id=eleven_vid, cancel_event=cancel_ev)
                            else:
                                gen_pcm = _stream_deepgram_pcm(
                                    ch_txt,
                                    api_key=ext_key,
                                    voice_model=deepgram_voice,
                                    speed=speed,
                                    expressivity=deepgram_expressivity,
                                    cancel_event=cancel_ev,
                                )
                            ch_pcm_bytes = 0
                            for pcm_piece in gen_pcm:
                                if cancel_ev.is_set():
                                    break
                                if not pcm_piece or len(pcm_piece) < 2:
                                    continue
                                if stream is None:
                                    stream = _WaveOutStream(sample_rate=cand_sr, channels=1, bits_per_sample=16)
                                    with _TTS_LOCK:
                                        if _SPEECH_GEN != gen_token or cancel_ev.is_set():
                                            stream.stop()
                                            stream = None
                                            break
                                        _ACTIVE_WAVEOUT = stream
                                        _LAST_TTS_ENGINE_USED = f"{model_tag} ({v_short})"
                                    if on_engine_status is not None:
                                        try:
                                            on_engine_status(_LAST_TTS_ENGINE_USED)
                                        except Exception:
                                            pass
                                _write_or_raise(pcm_piece, candidate)
                                _emit_meta(candidate, v_short)
                                ch_pcm_bytes += len(pcm_piece)
                            if ch_pcm_bytes > 0:
                                try:
                                    from cost_service import emit_tts_cost
                                    emit_tts_cost(model_tag, ch_pcm_bytes / (float(cand_sr) * 2.0), char_count=len(ch_txt))
                                except Exception:
                                    pass
                        if not cancel_ev.is_set() and played_any:
                            stream.drain(cancel_ev)
                        if played_any:
                            break
                    except Exception as exc:
                        err_s = f"{candidate}: {exc}"
                        errors.append(err_s)
                        _log_voice_diagnostic(err_s)
                        if stream is not None:
                            stream.stop()
                            stream = None
                        if played_any:
                            break
                        continue

                elif candidate == "system":
                    if on_engine_status is not None:
                        try:
                            on_engine_status("system:sapi5")
                        except Exception:
                            pass
                    if _speak_windows_sapi5(
                        spoken,
                        voice_name=system_voice,
                        volume_percent=get_live_volume(config_path),
                        speed=speed,
                        gen_token=gen_token,
                    ):
                        played_any = True
                        _emit_meta("system", system_voice)
                    else:
                        errors.append("system: SAPI5 playback failed")
                    break

            if not played_any and not cancel_ev.is_set():
                err_msg = "; ".join(errors) or "No working voice output engine succeeded."
                _log_voice_diagnostic(f"All TTS engines failed: {err_msg}")
                with _TTS_LOCK:
                    _LAST_TTS_STATE.update({
                        "engine_id": primary_expected,
                        "engine_label": TTS_ENGINE_SHORT_LABELS.get(primary_expected, primary_expected),
                        "voice_label": "",
                        "requested_engine": primary_expected,
                        "fell_back": False,
                        "fallback_reason": "",
                        "last_error": err_msg,
                        "updated_ts": time.time(),
                    })
                if on_error is not None:
                    try:
                        on_error(err_msg)
                    except Exception:
                        pass
        finally:
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
            with _TTS_LOCK:
                if _SPEECH_GEN == gen_token:
                    _ACTIVE_WAVEOUT = None
                    _ACTIVE_CANCEL_EVENT = None
                    _TTS_SPEAKING = False
                    _TTS_LAST_END_MONO = time.monotonic()
            if on_finished is not None:
                try:
                    on_finished()
                except Exception:
                    pass

    threading.Thread(target=_run_playback, daemon=True, name="FairybreadVoicePlayback").start()
    return True


def transcribe_audio_file(
    audio_path: Path,
    *,
    credential_store: CredentialStore | None = None,
) -> str:
    """Transcribe recorded microphone audio into text using Groq Whisper, OpenAI Whisper, or Gemini."""
    if not audio_path or not audio_path.exists() or audio_path.stat().st_size < 400:
        raise ValueError("No audio was recorded. Check your microphone in Settings → Voice & Audio.")
    store = credential_store or CredentialStore()

    audio_dur_sec = 0.0
    try:
        with wave.open(str(audio_path), "rb") as wf:
            nframes = wf.getnframes()
            fr = float(wf.getframerate() or 16000)
            audio_dur_sec = max(0.2, nframes / max(1.0, fr))
            frames = wf.readframes(nframes)
            _, lvl = pcm_chunk_to_int16_mono_and_level(frames, "Int16", wf.getnchannels(), gain_percent=100)
            if lvl < 2:
                raise ValueError(
                    "Microphone recorded silence (0% volume). Check that your mic is not muted or boost Microphone Gain in Settings → Voice & Audio."
                )
    except ValueError:
        raise
    except Exception:
        audio_dur_sec = max(0.5, max(0, audio_path.stat().st_size - 44) / 32000.0)

    def _emit_stt(eng_id: str) -> None:
        try:
            from cost_service import emit_stt_cost
            emit_stt_cost(eng_id, audio_dur_sec)
        except Exception:
            pass

    groq_key = store.get_api_key("groq")
    if groq_key:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
                timeout=25.0,
                max_retries=0,
            )
            with audio_path.open("rb") as fh:
                tr = client.audio.transcriptions.create(model="whisper-large-v3-turbo", file=fh)
            txt = (getattr(tr, "text", "") or "").strip()
            if txt:
                _emit_stt("groq:whisper-large-v3-turbo")
                return txt
        except Exception:
            pass

    oai_key = store.get_api_key("openai")
    if oai_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=oai_key, timeout=25.0, max_retries=0)
            with audio_path.open("rb") as fh:
                tr = client.audio.transcriptions.create(model="whisper-1", file=fh)
            txt = (getattr(tr, "text", "") or "").strip()
            if txt:
                _emit_stt("openai:whisper-1")
                return txt
        except Exception:
            pass

    gem_key = store.get_api_key("gemini")
    if gem_key:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=gem_key, http_options=types.HttpOptions(timeout=25000))
        raw_bytes = audio_path.read_bytes()
        for gm in ("gemini-4-hydrogen", "gemini-2.5-flash"):
            try:
                resp = client.models.generate_content(
                    model=gm,
                    contents=[
                        types.Part.from_bytes(data=raw_bytes, mime_type="audio/wav"),
                        "Transcribe the spoken words in this audio clip verbatim. Output only the transcribed text.",
                    ],
                )
                txt = (getattr(resp, "text", "") or "").strip()
                if txt:
                    _emit_stt(f"gemini:{gm}")
                    return txt
            except Exception:
                continue

    or_key = store.get_api_key("openrouter")
    if or_key:
        try:
            b64_wav = base64.b64encode(audio_path.read_bytes()).decode("ascii")
            body = json.dumps({
                "model": "openai/gpt-audio-mini",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe the spoken words in this audio clip verbatim. Output only the transcribed text."},
                        {"type": "input_audio", "input_audio": {"data": b64_wav, "format": "wav"}},
                    ],
                }],
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {or_key}",
                    "HTTP-Referer": "https://fairybread.me",
                    "X-Title": "Fairybread",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=25.0) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            txt = str((((payload.get("choices") or [{}])[0]).get("message") or {}).get("content") or "").strip()
            if txt:
                _emit_stt("openrouter:gpt-audio-mini")
                return txt
        except Exception:
            pass

    raise RuntimeError("Could not transcribe audio. Ensure Groq, OpenAI, Gemini, or OpenRouter has an active API key.")
