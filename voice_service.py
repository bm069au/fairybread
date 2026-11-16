"""Voice Input (Microphone Dictation for All Council Agents) and Voice Output (Agent Response TTS) for Fairybread."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from credential_store import CredentialStore
from palace_config import CONFIG_PATH, _read_raw_config, _write_raw_config


DEFAULT_VOICE_SETTINGS: dict[str, Any] = {
    "voice_name": "System Default",
    "microphone_device": "System default",
    "volume_percent": 100,
    "auto_speak_responses": False,
}

_ACTIVE_TTS_PROC: subprocess.Popen | None = None


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
    if not audio_path.exists() or audio_path.stat().st_size < 200:
        raise ValueError("No audio was recorded. Check your microphone selection in Settings.")
    store = credential_store or CredentialStore()

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
