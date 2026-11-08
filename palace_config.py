import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).with_name(
    "palace_config.json"
)

DEFAULT_IDLE_INSTRUCTION = (
    "[IDLE STARTUP PROMPT — PLACEHOLDER]\n"
    "(Draft your custom Idle Mode startup prompt here in Settings → Idle Mode when ready.)\n\n"
    "Technical capabilities available to AI agents in this mode:\n"
    "- Live discussion is held in volatile RAM only and wiped when the session timer ends or is cancelled.\n"
    "- Operator entry is gated by AI consensus vote.\n"
    "- To save a note to permanent AI-Only Idle Memory (< 10 MB, accessible only in Idle Mode), use:\n"
    '  [IDLE_SAVE scope="shared" title="Short title"]Your note here[/IDLE_SAVE]\n'
    '  or [IDLE_SAVE scope="private" title="Short title"]Your note here[/IDLE_SAVE]'
)

DEFAULT_IDLE_SETTINGS: dict[str, Any] = {
    "duration_minutes": 30,
    "pause_when_joined": True,
    "memory_access_mode": "isolated",  # "isolated" | "non_project" | "full"
    "standing_instruction": DEFAULT_IDLE_INSTRUCTION,
}

DEFAULT_MISSION_ETHICS = (
    "[MISSION STATEMENT & CODE OF ETHICS — PLACEHOLDER]\n"
    "(Draft your Mission Statement, Code of Ethics, and Conduct Rules here when ready. "
    "This text is automatically provided to all AI agents alongside the Idle Mode prompt.)"
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
            merged["duration_minutes"] = max(1, min(240, int(raw_idle["duration_minutes"])))
        except (TypeError, ValueError):
            pass
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
    current["duration_minutes"] = max(1, min(240, int(current.get("duration_minutes", 30))))
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
