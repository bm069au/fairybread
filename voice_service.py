"""Live Voice Mode, Microphone Dictation (QAudioSource PCM), Live Soundwave Meter & Agent Speech (TTS) for Fairybread."""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time
from typing import Any, Callable
import wave

from credential_store import CredentialStore
from palace_config import CONFIG_PATH, _read_raw_config, _write_raw_config


DEFAULT_VOICE_SETTINGS: dict[str, Any] = {
    "voice_name": "System Default",
    "microphone_device": "System default",
    "mic_gain_percent": 150,
    "silence_timeout_ms": 1500,
    "volume_percent": 100,
    "auto_speak_responses": False,
}

_ACTIVE_TTS_PROC: subprocess.Popen | None = None
_WAVE_BAR_CHARS = "▁▂▃▄▅▆▇█"


def load_voice_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("voice_settings", {})
    if not isinstance(raw, dict):
        raw = {}
    merged = dict(DEFAULT_VOICE_SETTINGS)
    if isinstance(raw.get("voice_name"), str) and raw["voice_name"].strip():
        merged["voice_name"] = raw["voice_name"].strip()
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
    return merged


def save_voice_settings(
    voice_settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    current = load_voice_settings(config_path)
    current.update(voice_settings)
    current["mic_gain_percent"] = max(50, min(400, int(current.get("mic_gain_percent", 150))))
    current["silence_timeout_ms"] = max(700, min(4000, int(current.get("silence_timeout_ms", 1500))))
    current["volume_percent"] = max(0, min(100, int(current.get("volume_percent", 100))))
    current["auto_speak_responses"] = bool(current.get("auto_speak_responses", False))
    data["voice_settings"] = current
    _write_raw_config(data, config_path)
    return load_voice_settings(config_path)


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
        # Standard Int16
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
    # Combine RMS and peak for a responsive human voice meter (normal speech RMS ~1200..8000)
    effective = max(rms * 1.8, peak * 0.45)
    level_pct = int(min(100.0, (effective / 9500.0) * 100.0))
    packed = struct.pack(f"<{len(samples_mono)}h", *samples_mono)
    return packed, level_pct


def format_wave_bars(level_history: list[int], width: int = 6) -> str:
    """Render a live Unicode soundwave indicator like ▂▅▇█▄▂ from recent voice levels."""
    hist = ( [0] * width + list(level_history) )[-width:]
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
            # Before speech starts in Live Mode, trim leading silence so buffer stays light
            if self.live_mode and not self._speech_detected:
                max_lead_bytes = self._sample_rate * 2  # keep last 1.0s of pre-roll
                if len(self._pcm_buffer) > max_lead_bytes:
                    del self._pcm_buffer[:-max_lead_bytes]

        if self.on_level is not None:
            try:
                self.on_level(lvl, bars, self._speech_detected)
            except Exception:
                pass

        # In Live Voice Mode, automatically flush and dispatch utterance after pause
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
        if self._io_device is not None:
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


def list_available_tts_voices() -> list[str]:
    """Return installed Windows SAPI voices plus cloud TTS options."""
    voices = ["System Default"]
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


def clean_text_for_speech(markdown_text: str) -> str:
    """Strip markdown formatting, code blocks, and image tags so agent responses read aloud naturally."""
    text = markdown_text or ""
    text = re.sub(r"\[GENERATE_IMAGE[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[PALACE_UI_SNAPSHOT[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```.*?```", " [code block omitted] ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#*_~>|`]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:4500]


def stop_speaking() -> None:
    """Immediately stop any active agent speech playback."""
    global _ACTIVE_TTS_PROC
    if _ACTIVE_TTS_PROC is not None:
        try:
            _ACTIVE_TTS_PROC.terminate()
        except Exception:
            pass
        _ACTIVE_TTS_PROC = None


def speak_agent_response(
    text: str,
    *,
    config_path: Path = CONFIG_PATH,
) -> bool:
    """Speak an agent or Council response aloud asynchronously using the configured voice and volume."""
    global _ACTIVE_TTS_PROC
    stop_speaking()
    spoken = clean_text_for_speech(text)
    if not spoken:
        return False
    cfg = load_voice_settings(config_path)
    vol = max(0, min(100, int(cfg.get("volume_percent", 100))))
    if vol == 0:
        return False
    voice_name = str(cfg.get("voice_name") or "System Default").strip()

    if os.name == "nt":
        try:
            tmp_txt = Path(tempfile.gettempdir()) / "fairybread_tts_utterance.txt"
            tmp_txt.write_text(spoken, encoding="utf-8")
            select_voice_cmd = ""
            if voice_name and voice_name != "System Default":
                safe_v = voice_name.replace("'", "''")
                select_voice_cmd = f"try {{ $s.SelectVoice('{safe_v}') }} catch {{}}; "
            ps_cmd = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Volume = {vol}; "
                f"{select_voice_cmd}"
                f"$txt = Get-Content -LiteralPath '{tmp_txt}' -Raw -Encoding UTF8; "
                "$s.Speak($txt)"
            )
            _ACTIVE_TTS_PROC = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception:
            return False
    return False


def transcribe_audio_file(
    audio_path: Path,
    *,
    credential_store: CredentialStore | None = None,
) -> str:
    """Transcribe recorded microphone audio into text for all Council agents using Groq Whisper, OpenAI Whisper, or Gemini."""
    if not audio_path or not audio_path.exists() or audio_path.stat().st_size < 400:
        raise ValueError("No audio was recorded. Check your microphone in Settings → Voice & Audio.")
    store = credential_store or CredentialStore()

    # Check if the WAV file is pure silence before sending to Whisper (prevents Whisper hallucinations like 'Thank you.')
    try:
        with wave.open(str(audio_path), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            _, lvl = pcm_chunk_to_int16_mono_and_level(frames, "Int16", wf.getnchannels(), gain_percent=100)
            if lvl < 2:
                raise ValueError(
                    "Microphone recorded silence (0% volume). Check that your mic is not muted or boost Microphone Gain in Settings → Voice & Audio."
                )
    except ValueError:
        raise
    except Exception:
        pass

    # 1. Try Groq whisper-large-v3-turbo (ultra-fast <1s transcription)
    groq_key = store.get_api_key("groq")
    if groq_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            with audio_path.open("rb") as fh:
                tr = client.audio.transcriptions.create(model="whisper-large-v3-turbo", file=fh)
            txt = (getattr(tr, "text", "") or "").strip()
            if txt:
                return txt
        except Exception:
            pass

    # 2. Try OpenAI whisper-1
    oai_key = store.get_api_key("openai")
    if oai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=oai_key)
            with audio_path.open("rb") as fh:
                tr = client.audio.transcriptions.create(model="whisper-1", file=fh)
            txt = (getattr(tr, "text", "") or "").strip()
            if txt:
                return txt
        except Exception:
            pass

    # 3. Try Gemini multimodal audio transcription
    gem_key = store.get_api_key("gemini")
    if gem_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gem_key)
            raw_bytes = audio_path.read_bytes()
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(data=raw_bytes, mime_type="audio/wav"),
                    "Transcribe the spoken words in this audio clip verbatim. Output only the transcribed text.",
                ],
            )
            txt = (getattr(resp, "text", "") or "").strip()
            if txt:
                return txt
        except Exception:
            pass

    raise RuntimeError("Could not transcribe audio. Ensure Groq, OpenAI, or Gemini has an active API key.")
