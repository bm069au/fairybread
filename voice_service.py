"""Live Voice Mode, Microphone Dictation (QAudioSource PCM), Streaming Human Neural TTS & Transcriber for Fairybread."""
from __future__ import annotations

from array import array
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import io
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable
import wave

from credential_store import CredentialStore
from palace_config import CONFIG_PATH, _read_raw_config, _write_raw_config


TTS_ENGINES: list[tuple[str, str]] = [
    ("auto", "Auto — Best Human Voice (OpenAI → Gemini → System)"),
    ("openai", "OpenAI Neural (gpt-4o-mini-tts · Streaming)"),
    ("gemini", "Gemini Neural (gemini-3.8-flash-lite-tts)"),
    ("system", "Windows System Fallback (SAPI 5 · Offline)"),
]

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

DEFAULT_VOICE_SETTINGS: dict[str, Any] = {
    "tts_engine": "auto",
    "voice_name": "coral",
    "gemini_voice_name": "Kore",
    "voice_style": "warm_american",
    "custom_style_prompt": "",
    "speech_speed": 1.0,
    "microphone_device": "System default",
    "mic_gain_percent": 150,
    "silence_timeout_ms": 1500,
    "volume_percent": 100,
    "auto_speak_responses": False,
    "voice_companion_enabled": True,
    "spoken_summary_for_background": True,
}

_WAVE_BAR_CHARS = "▁▂▃▄▅▆▇█"
_OPENAI_VOICE_IDS = {vid.lower(): vid for vid, _ in OPENAI_TTS_VOICES}
_GEMINI_VOICE_IDS = {vid.lower(): vid for vid, _ in GEMINI_TTS_VOICES}
_VALID_ENGINES = {eid for eid, _ in TTS_ENGINES}

_TTS_LOCK = threading.RLock()
_SPEECH_GEN = 0
_ACTIVE_CANCEL_EVENT: threading.Event | None = None
_ACTIVE_WAVEOUT: _WaveOutStream | None = None
_ACTIVE_TTS_PROC: subprocess.Popen | None = None
_TTS_SPEAKING = False
_TTS_LAST_END_MONO = 0.0
_LAST_TTS_ENGINE_USED = ""


def _clamp_speed(raw_speed: Any) -> float:
    try:
        val = float(raw_speed)
    except (TypeError, ValueError):
        val = 1.0
    if math.isnan(val) or math.isinf(val):
        val = 1.0
    return round(max(0.80, min(1.30, val)), 2)


def load_voice_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("voice_settings", {})
    if not isinstance(raw, dict):
        raw = {}
    merged = dict(DEFAULT_VOICE_SETTINGS)

    engine = str(raw.get("tts_engine") or DEFAULT_VOICE_SETTINGS["tts_engine"]).strip().lower()
    merged["tts_engine"] = engine if engine in _VALID_ENGINES else "auto"

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
    if "auto_speak_responses" in raw:
        merged["auto_speak_responses"] = bool(raw["auto_speak_responses"])
    if "voice_companion_enabled" in raw:
        merged["voice_companion_enabled"] = bool(raw["voice_companion_enabled"])
    if "spoken_summary_for_background" in raw:
        merged["spoken_summary_for_background"] = bool(raw["spoken_summary_for_background"])
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

    voice = str(current.get("voice_name") or "coral").strip() or "coral"
    if voice.lower() == "system default" and current["tts_engine"] == "auto":
        voice = "coral"
    current["voice_name"] = _OPENAI_VOICE_IDS.get(voice.lower(), voice)

    gvoice = str(current.get("gemini_voice_name") or "Kore").strip() or "Kore"
    current["gemini_voice_name"] = _GEMINI_VOICE_IDS.get(gvoice.lower(), gvoice)

    style = str(current.get("voice_style") or "warm_american").strip().lower()
    current["voice_style"] = style if style in VOICE_STYLE_PRESETS else "warm_american"
    current["custom_style_prompt"] = str(current.get("custom_style_prompt") or "").strip()[:280]
    current["speech_speed"] = _clamp_speed(current.get("speech_speed", 1.0))

    current["mic_gain_percent"] = max(50, min(400, int(current.get("mic_gain_percent", 150))))
    current["silence_timeout_ms"] = max(700, min(4000, int(current.get("silence_timeout_ms", 1500))))
    current["volume_percent"] = max(0, min(100, int(current.get("volume_percent", 100))))
    current["auto_speak_responses"] = bool(current.get("auto_speak_responses", False))
    current["voice_companion_enabled"] = bool(current.get("voice_companion_enabled", True))
    current["spoken_summary_for_background"] = bool(current.get("spoken_summary_for_background", True))

    data["voice_settings"] = current
    _write_raw_config(data, config_path)
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
    ):
        self.config_path = config_path
        self.live_mode = bool(live_mode)
        self.on_level = on_level
        self.on_utterance_ready = on_utterance_ready

        self._audio_source = None
        self._io_device = None
        self._timer = None
        self._sample_rate = 16000
        self._channels = 1
        self._sample_format_name = "Int16"
        self._gain_percent = 150
        self._silence_timeout_ms = 1500

        self._pcm_buffer = bytearray()
        self._level_history: list[int] = [10, 20, 15, 25, 15, 10]
        self._speech_detected = False
        self._speech_ticks = 0
        self._last_voice_ts = 0.0
        self._started_ts = 0.0
        self.active = False

    def start(self, parent_widget=None) -> tuple[bool, str]:
        from PySide6.QtCore import QTimer
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource

        v_cfg = load_voice_settings(self.config_path)
        self._gain_percent = int(v_cfg.get("mic_gain_percent", 150))
        self._silence_timeout_ms = int(v_cfg.get("silence_timeout_ms", 1500))
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
        self._speech_detected = False
        self._speech_ticks = 0
        self._started_ts = time.monotonic()
        self._last_voice_ts = self._started_ts

        self._audio_source = QAudioSource(dev, fmt, parent_widget)
        self._io_device = self._audio_source.start()
        if self._io_device is None:
            return False, f"Could not open microphone: {dev.description()}"

        self.active = True
        self._timer = QTimer(parent_widget)
        self._timer.setInterval(55)
        self._timer.timeout.connect(self._poll_audio)
        self._timer.start()
        return True, dev.description()

    def _poll_audio(self) -> None:
        if not self.active or self._io_device is None:
            return
        try:
            raw = bytes(self._io_device.readAll())
        except Exception:
            raw = b""

        # Anti-echo gate in Live Voice Mode: discard speaker spill while Fairybread is talking
        if self.live_mode and is_speaking(cooldown_sec=0.35):
            self._pcm_buffer.clear()
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

    def stop(self, filename: str = "fairybread_voice_input.wav") -> Path | None:
        """Stop capturing and return the recorded WAV file path (if any audio was captured)."""
        self.active = False
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        if self._io_device is not None and not (self.live_mode and is_speaking(cooldown_sec=0.35)):
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
    if eng == "system":
        items = [("System Default", "System Default (Windows SAPI 5)")]
        for v in _list_sapi5_voices():
            items.append((v, v))
        return items
    return list(OPENAI_TTS_VOICES)


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
    text = re.sub(r"\[PALACE_UI_SNAPSHOT[^\]]*\]", "", text, flags=re.IGNORECASE)
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


class _WaveOutStream:
    """Low-latency 64-bit-safe Windows waveOut PCM streamer supporting instant stop()."""

    def __init__(self, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16):
        if os.name != "nt" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            raise RuntimeError("Audio hardware playback disabled in offscreen/non-Windows environment.")
        self.winmm = ctypes.windll.winmm
        self.hwo = wintypes.HANDLE()
        block_align = channels * (bits_per_sample // 8)
        wfx = _WAVEFORMATEX(
            _WAVE_FORMAT_PCM,
            channels,
            int(sample_rate or 24000),
            int(sample_rate or 24000) * block_align,
            block_align,
            bits_per_sample,
            0,
        )
        rc = self.winmm.waveOutOpen(ctypes.byref(self.hwo), _WAVE_MAPPER, ctypes.byref(wfx), 0, 0, 0)
        if rc != 0:
            raise OSError(f"waveOutOpen failed with code {rc}")
        self._inflight: list[tuple[ctypes.Array[ctypes.c_char], _WAVEHDR]] = []
        self._lock = threading.Lock()
        self._closed = False

    def _reap_done_locked(self) -> None:
        if not self.hwo.value:
            self._inflight.clear()
            return
        remaining: list[tuple[ctypes.Array[ctypes.c_char], _WAVEHDR]] = []
        for buf, hdr in self._inflight:
            if hdr.dwFlags & _WHDR_DONE:
                try:
                    self.winmm.waveOutUnprepareHeader(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
                except Exception:
                    pass
            else:
                remaining.append((buf, hdr))
        self._inflight = remaining

    def write(self, pcm_bytes: bytes, cancel_event: threading.Event) -> bool:
        if not pcm_bytes or len(pcm_bytes) < 2 or cancel_event.is_set() or self._closed:
            return False
        even_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
        payload = pcm_bytes[:even_len]

        while not cancel_event.is_set():
            with self._lock:
                if self._closed:
                    return False
                self._reap_done_locked()
                if len(self._inflight) < 6:
                    buf = ctypes.create_string_buffer(payload, len(payload))
                    hdr = _WAVEHDR(ctypes.cast(buf, ctypes.c_void_p), len(payload), 0, 0, 0, 0, None, 0)
                    if self.winmm.waveOutPrepareHeader(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr)) == 0:
                        if self.winmm.waveOutWrite(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr)) == 0:
                            self._inflight.append((buf, hdr))
                            return True
                        try:
                            self.winmm.waveOutUnprepareHeader(self.hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
                        except Exception:
                            pass
                    return False
            time.sleep(0.015)
        return False

    def drain(self, cancel_event: threading.Event) -> None:
        while not cancel_event.is_set():
            with self._lock:
                if self._closed:
                    return
                self._reap_done_locked()
                if not self._inflight:
                    return
            time.sleep(0.015)

    def stop(self) -> None:
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

    client = OpenAI(api_key=api_key, timeout=25.0)
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
    style_instr = build_voice_style_instructions(
        str(cfg.get("voice_style") or "warm_american"),
        str(cfg.get("custom_style_prompt") or ""),
        float(cfg.get("speech_speed", 1.0)),
    )
    speed = _clamp_speed(cfg.get("speech_speed", 1.0))

    order = {
        "auto": ["openai", "gemini"],
        "openai": ["openai", "gemini"],
        "gemini": ["gemini", "openai"],
        "system": [],
    }.get(engine, ["openai", "gemini"])

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

    raise RuntimeError("No neural TTS engine succeeded (" + "; ".join(errors or ["system mode selected"]) + ")")


def stop_speaking() -> None:
    """Immediately stop any active neural or system speech playback."""
    global _SPEECH_GEN, _ACTIVE_CANCEL_EVENT, _ACTIVE_WAVEOUT, _ACTIVE_TTS_PROC, _TTS_SPEAKING, _TTS_LAST_END_MONO
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


def speak_agent_response(
    text: str,
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
    on_engine_status: Callable[[str], None] | None = None,
    on_finished: Callable[[], None] | None = None,
) -> bool:
    """Speak an agent or Voice Companion response aloud with streaming human neural TTS and automatic fallbacks."""
    global _SPEECH_GEN, _ACTIVE_CANCEL_EVENT, _ACTIVE_WAVEOUT, _TTS_SPEAKING, _TTS_LAST_END_MONO, _LAST_TTS_ENGINE_USED

    stop_speaking()
    spoken = clean_text_for_speech(text)
    if not spoken:
        return False
    cfg = load_voice_settings(config_path)
    vol = max(0, min(100, int(cfg.get("volume_percent", 100))))
    if vol == 0:
        return False

    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False

    store = credential_store or CredentialStore()
    engine = str(cfg.get("tts_engine") or "auto").strip().lower()
    style_instr = build_voice_style_instructions(
        str(cfg.get("voice_style") or "warm_american"),
        str(cfg.get("custom_style_prompt") or ""),
        float(cfg.get("speech_speed", 1.0)),
    )
    speed = _clamp_speed(cfg.get("speech_speed", 1.0))
    voice_name = str(cfg.get("voice_name") or "coral").strip()
    gemini_voice = str(cfg.get("gemini_voice_name") or "Kore").strip()

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
        try:
            chunks = split_text_for_streaming_tts(spoken)
            if not chunks:
                return

            order = {
                "auto": ["openai", "gemini", "system"],
                "openai": ["openai", "gemini", "system"],
                "gemini": ["gemini", "openai", "system"],
                "system": ["system"],
            }.get(engine, ["openai", "gemini", "system"])

            for candidate in order:
                if cancel_ev.is_set():
                    break
                if candidate == "openai":
                    oai_key = store.get_api_key("openai")
                    if not oai_key:
                        continue
                    try:
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
                                stream.write(_scale_pcm16_volume(pcm_piece, vol), cancel_ev)
                                ch_pcm_bytes += len(pcm_piece)
                                played_any = True
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
                    except Exception:
                        if stream is not None:
                            stream.stop()
                            stream = None
                        if played_any:
                            break
                        continue

                elif candidate == "gemini":
                    gem_key = store.get_api_key("gemini")
                    if not gem_key:
                        continue
                    try:
                        # Pipeline chunk i+1 while playing chunk i
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
                                scaled = _scale_pcm16_volume(pcm, vol)
                                ch_played = False
                                for pos in range(0, len(scaled), 16384):
                                    if cancel_ev.is_set():
                                        break
                                    stream.write(scaled[pos : pos + 16384], cancel_ev)
                                    played_any = True
                                    ch_played = True
                                if ch_played and pcm:
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
                    except Exception:
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
                        voice_name=voice_name,
                        volume_percent=vol,
                        speed=speed,
                        gen_token=gen_token,
                    ):
                        played_any = True
                    break
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

            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
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

            client = OpenAI(api_key=oai_key)
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

        client = genai.Client(api_key=gem_key)
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

    raise RuntimeError("Could not transcribe audio. Ensure Groq, OpenAI, or Gemini has an active API key.")
