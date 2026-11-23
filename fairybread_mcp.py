"""Universal MCP (Model Context Protocol) Server & Bidirectional Agent Bridge for Fairybread.

Supports two mutually interlocked roles per external AI platform:
- Foreman Mode: ChatGPT Desktop / Codex CLI, Google Antigravity, xAI Grok (CLI / Bot),
  Claude Desktop / Code, and Cursor/Windsurf drive Fairybread over JSON-RPC stdio MCP.
- Council Member Mode: Local CLIs (codex, agy, grok, claude) participate inside
  Fairybread's own Council via LocalCLIProvider.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any

from local_cli_provider import (
    EXTERNAL_CLI_SPECS,
    find_cli_binary,
    get_mcp_depth,
)
from palace_config import (
    CONFIG_PATH,
    FAIRYBREAD_VERSION,
    _read_raw_config,
    _write_raw_config,
    get_app_install_dir,
    is_frozen_app,
)


EXTERNAL_PLATFORMS: tuple[str, ...] = ("codex", "antigravity", "grok", "claude")
PLATFORM_MODES: tuple[str, ...] = ("off", "foreman", "council")

DEFAULT_PLATFORM_MODES: dict[str, str] = {pk: "off" for pk in EXTERNAL_PLATFORMS}

DEFAULT_BRIDGE_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "allow_council_query": True,
    "allow_image_generation": True,
    "allow_email_search": True,
    "allow_memory_search": True,
    "platforms": dict(DEFAULT_PLATFORM_MODES),
}

_TOML_HEADER_RE = re.compile(r"^\s*\[{1,2}\s*([^\]]+?)\s*\]{1,2}\s*(?:#.*)?$")


def _normalize_platform_mode(val: Any) -> str:
    clean = str(val or "off").strip().lower()
    return clean if clean in PLATFORM_MODES else "off"


def load_bridge_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    raw = _read_raw_config(config_path)
    saved = raw.get("external_agent_bridge", {})
    merged: dict[str, Any] = {
        "enabled": bool(DEFAULT_BRIDGE_SETTINGS["enabled"]),
        "allow_council_query": bool(DEFAULT_BRIDGE_SETTINGS["allow_council_query"]),
        "allow_image_generation": bool(DEFAULT_BRIDGE_SETTINGS["allow_image_generation"]),
        "allow_email_search": bool(DEFAULT_BRIDGE_SETTINGS["allow_email_search"]),
        "allow_memory_search": bool(DEFAULT_BRIDGE_SETTINGS["allow_memory_search"]),
        "platforms": dict(DEFAULT_PLATFORM_MODES),
    }
    if isinstance(saved, dict):
        for key in (
            "enabled",
            "allow_council_query",
            "allow_image_generation",
            "allow_email_search",
            "allow_memory_search",
        ):
            if key in saved:
                merged[key] = bool(saved[key])
        raw_platforms = saved.get("platforms")
        if isinstance(raw_platforms, dict):
            for pk in EXTERNAL_PLATFORMS:
                if pk in raw_platforms:
                    merged["platforms"][pk] = _normalize_platform_mode(raw_platforms[pk])
    return merged


def save_bridge_settings(
    settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    raw = _read_raw_config(config_path)
    merged = load_bridge_settings(config_path)
    for k in (
        "enabled",
        "allow_council_query",
        "allow_image_generation",
        "allow_email_search",
        "allow_memory_search",
    ):
        if k in settings:
            merged[k] = bool(settings[k])
    if isinstance(settings.get("platforms"), dict):
        plat_out = dict(merged.get("platforms") or DEFAULT_PLATFORM_MODES)
        for pk in EXTERNAL_PLATFORMS:
            if pk in settings["platforms"]:
                plat_out[pk] = _normalize_platform_mode(settings["platforms"][pk])
        merged["platforms"] = plat_out
    raw["external_agent_bridge"] = merged
    _write_raw_config(raw, config_path)
    return merged


def get_council_cli_platforms(config_path: Path = CONFIG_PATH) -> list[str]:
    cfg = load_bridge_settings(config_path)
    plats = cfg.get("platforms") or {}
    return [pk for pk in EXTERNAL_PLATFORMS if plats.get(pk) == "council"]


def resolve_console_python_executable(exe: str | None = None) -> str:
    """Resolve pythonw.exe (windowless GUI host) to console python.exe so stdio MCP pipes work."""
    p = Path(exe or sys.executable)
    if p.name.lower() == "pythonw.exe":
        sibling = p.with_name("python.exe")
        if sibling.exists():
            return str(sibling)
        which_py = shutil.which("python")
        if which_py:
            return which_py
    return str(p)


def get_mcp_script_path() -> Path:
    if is_frozen_app():
        mcp_exe = get_app_install_dir() / "FairybreadMCP.exe"
        if mcp_exe.is_file():
            return mcp_exe
    return Path(__file__).resolve()


def get_mcp_server_entry(
    python_exe: str | None = None,
    script_path: Path | None = None,
) -> dict[str, Any]:
    if python_exe is None and script_path is None and is_frozen_app():
        mcp_exe = get_app_install_dir() / "FairybreadMCP.exe"
        if mcp_exe.is_file():
            return {"command": str(mcp_exe), "args": []}
    return {
        "command": resolve_console_python_executable(python_exe),
        "args": [str(script_path or get_mcp_script_path())],
    }


def _norm_dir_match(raw: str | Path) -> str:
    try:
        s = str(Path(raw).resolve())
    except Exception:
        s = str(raw)
    return s.replace("/", "\\").rstrip("\\").lower()


def _entry_points_into_dir(entry: Any, norm_dir: str) -> bool:
    if not norm_dir:
        return False
    if isinstance(entry, str):
        return norm_dir in entry.replace("/", "\\").lower()
    if isinstance(entry, dict):
        return any(_entry_points_into_dir(v, norm_dir) for v in entry.values())
    if isinstance(entry, (list, tuple)):
        return any(_entry_points_into_dir(v, norm_dir) for v in entry)
    return False


def cleanup_external_mcp_for_dir(
    install_dir: str | Path,
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
    server_name: str = "fairybread",
) -> list[str]:
    """Remove external MCP bridge entries only when they point inside install_dir."""
    norm_dir = _norm_dir_match(install_dir)
    home, appdata = _resolve_roots(home_dir, appdata_dir)
    cleaned: list[str] = []

    ag_mcp_cfg, ag_skill_md = _antigravity_paths(home)
    for cfg_path, remove_skill in (
        (ag_mcp_cfg, True),
        (_claude_config_path(appdata), False),
    ):
        if not cfg_path.is_file():
            continue
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
        if not isinstance(servers, dict) or server_name not in servers:
            continue
        if not _entry_points_into_dir(servers[server_name], norm_dir):
            continue
        servers.pop(server_name, None)
        cfg_path.write_text(json.dumps(loaded, indent=2) + "\n", encoding="utf-8")
        cleaned.append(str(cfg_path))
        if remove_skill:
            skill_md = ag_skill_md
            if skill_md.is_file():
                try:
                    skill_md.unlink()
                    cleaned.append(str(skill_md))
                except OSError:
                    pass

    for toml_path in (_codex_config_path(home), _grok_config_path(home)):
        if not toml_path.is_file():
            continue
        try:
            raw = toml_path.read_text(encoding="utf-8")
            parsed = tomllib.loads(raw) if raw.strip() else {}
        except Exception:
            continue
        entry = (parsed.get("mcp_servers") or {}).get(server_name)
        if not entry or not _entry_points_into_dir(entry, norm_dir):
            continue
        ok, _ = remove_toml_mcp_server(toml_path, server_name=server_name)
        if ok:
            cleaned.append(str(toml_path))

    return cleaned


def _backup_config_file(path: Path) -> None:
    if path.is_file():
        bak = path.with_name(path.name + ".fairybread.bak")
        try:
            shutil.copy2(path, bak)
        except OSError:
            pass


def _toml_quote_path(val: str) -> str:
    if "'" not in val and "\n" not in val and "\r" not in val:
        return f"'{val}'"
    return json.dumps(val)


def _strip_toml_server_blocks(text: str, server_name: str = "fairybread") -> tuple[str, bool]:
    """Remove [mcp_servers.<server_name>] and nested sub-tables while preserving all other TOML lines."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    removed = False
    target = server_name.strip().lower()

    for line in lines:
        m = _TOML_HEADER_RE.match(line.rstrip("\r\n"))
        if m:
            raw_hdr = m.group(1)
            parts = [seg.strip().strip("\"'").lower() for seg in raw_hdr.split(".")]
            if len(parts) >= 2 and parts[0] == "mcp_servers" and parts[1] == target:
                skipping = True
                removed = True
                continue
            skipping = False
        if not skipping:
            kept.append(line)

    result = "".join(kept)
    return result, removed


def _format_toml_server_block(entry: dict[str, Any], server_name: str = "fairybread") -> str:
    cmd = _toml_quote_path(str(entry.get("command") or resolve_console_python_executable()))
    raw_args = entry.get("args") or []
    args_list = ", ".join(_toml_quote_path(str(a)) for a in raw_args)
    lines = [
        f"[mcp_servers.{server_name}]",
        f"command = {cmd}",
        f"args = [{args_list}]",
    ]
    env_map = entry.get("env")
    if isinstance(env_map, dict) and env_map:
        lines.append(f"[mcp_servers.{server_name}.env]")
        for ek, ev in env_map.items():
            lines.append(f"{ek} = {_toml_quote_path(str(ev))}")
    return "\n".join(lines) + "\n"


def merge_toml_mcp_server(
    toml_path: Path,
    entry: dict[str, Any],
    server_name: str = "fairybread",
) -> tuple[bool, str]:
    try:
        existing = toml_path.read_text(encoding="utf-8") if toml_path.is_file() else ""
        if existing.strip():
            try:
                tomllib.loads(existing)
            except tomllib.TOMLDecodeError as exc:
                return False, f"Existing TOML in {toml_path} is invalid ({exc}); left untouched."

        cleaned, _ = _strip_toml_server_blocks(existing, server_name=server_name)
        block = _format_toml_server_block(entry, server_name=server_name)
        if cleaned.strip():
            new_text = cleaned.rstrip() + "\n\n" + block
        else:
            new_text = block

        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            return False, f"Refused to write invalid TOML ({exc}); left untouched."

        _backup_config_file(toml_path)
        toml_path.parent.mkdir(parents=True, exist_ok=True)
        toml_path.write_text(new_text, encoding="utf-8")
        return True, f"Linked '{server_name}' MCP server in {toml_path}"
    except Exception as exc:
        return False, f"Could not update {toml_path}: {exc}"


def remove_toml_mcp_server(
    toml_path: Path,
    server_name: str = "fairybread",
) -> tuple[bool, str]:
    if not toml_path.is_file():
        return True, f"No {toml_path.name} present; '{server_name}' is already unlinked."
    try:
        existing = toml_path.read_text(encoding="utf-8")
        if existing.strip():
            try:
                tomllib.loads(existing)
            except tomllib.TOMLDecodeError as exc:
                return False, f"Existing TOML in {toml_path} is invalid ({exc}); left untouched."

        cleaned, removed = _strip_toml_server_blocks(existing, server_name=server_name)
        if not removed:
            return True, f"'{server_name}' was not registered in {toml_path}."

        new_text = (cleaned.rstrip() + "\n") if cleaned.strip() else ""
        if new_text:
            try:
                tomllib.loads(new_text)
            except tomllib.TOMLDecodeError as exc:
                return False, f"Refused to write invalid TOML ({exc}); left untouched."

        _backup_config_file(toml_path)
        toml_path.write_text(new_text, encoding="utf-8")
        return True, f"Removed '{server_name}' MCP server from {toml_path}"
    except Exception as exc:
        return False, f"Could not update {toml_path}: {exc}"


def merge_json_mcp_server(
    json_path: Path,
    entry: dict[str, Any],
    server_name: str = "fairybread",
) -> tuple[bool, str]:
    try:
        data: dict[str, Any] = {}
        if json_path.is_file():
            raw_text = json_path.read_text(encoding="utf-8")
            if raw_text.strip():
                try:
                    loaded = json.loads(raw_text)
                except ValueError as exc:
                    return False, f"Existing JSON in {json_path} is malformed ({exc}); left untouched."
                if not isinstance(loaded, dict):
                    return False, f"Existing JSON in {json_path} is not a JSON object; left untouched."
                data = loaded

        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            return False, f"Existing 'mcpServers' in {json_path} is not an object; left untouched."
        servers[server_name] = entry

        _backup_config_file(json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return True, f"Linked '{server_name}' MCP server in {json_path}"
    except Exception as exc:
        return False, f"Could not update {json_path}: {exc}"


def remove_json_mcp_server(
    json_path: Path,
    server_name: str = "fairybread",
) -> tuple[bool, str]:
    if not json_path.is_file():
        return True, f"No {json_path.name} present; '{server_name}' is already unlinked."
    try:
        raw_text = json_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return True, f"'{server_name}' was not registered in {json_path}."
        try:
            loaded = json.loads(raw_text)
        except ValueError as exc:
            return False, f"Existing JSON in {json_path} is malformed ({exc}); left untouched."
        if not isinstance(loaded, dict):
            return False, f"Existing JSON in {json_path} is not a JSON object; left untouched."

        servers = loaded.get("mcpServers")
        if not isinstance(servers, dict) or server_name not in servers:
            return True, f"'{server_name}' was not registered in {json_path}."

        _backup_config_file(json_path)
        servers.pop(server_name, None)
        json_path.write_text(json.dumps(loaded, indent=2) + "\n", encoding="utf-8")
        return True, f"Removed '{server_name}' MCP server from {json_path}"
    except Exception as exc:
        return False, f"Could not update {json_path}: {exc}"


def _resolve_roots(home_dir: Path | None = None, appdata_dir: Path | None = None) -> tuple[Path, Path]:
    home = home_dir or Path.home()
    appdata = appdata_dir or Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    return home, appdata


def _antigravity_paths(home: Path) -> tuple[Path, Path]:
    return (
        home / ".gemini" / "config" / "mcp_config.json",
        home / ".gemini" / "config" / "skills" / "fairybread-council" / "SKILL.md",
    )


def _codex_config_path(home: Path) -> Path:
    return home / ".codex" / "config.toml"


def _grok_config_path(home: Path) -> Path:
    return home / ".grok" / "config.toml"


def _claude_config_path(appdata: Path) -> Path:
    return appdata / "Claude" / "claude_desktop_config.json"


def is_mcp_server_registered(
    platform_key: str,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> bool:
    home, appdata = _resolve_roots(home_dir, appdata_dir)
    key = (platform_key or "").strip().lower()
    if key == "codex":
        cfg_path, fmt = _codex_config_path(home), "toml"
    elif key == "antigravity":
        cfg_path, _ = _antigravity_paths(home)
        fmt = "json"
    elif key == "grok":
        cfg_path, fmt = _grok_config_path(home), "toml"
    elif key == "claude":
        cfg_path, fmt = _claude_config_path(appdata), "json"
    else:
        return False

    if not cfg_path.is_file():
        return False
    try:
        text = cfg_path.read_text(encoding="utf-8")
        if fmt == "toml":
            parsed = tomllib.loads(text)
            servers = parsed.get("mcp_servers")
            return isinstance(servers, dict) and "fairybread" in servers
        parsed = json.loads(text)
        servers = parsed.get("mcpServers")
        return isinstance(servers, dict) and "fairybread" in servers
    except Exception:
        return False


def install_antigravity_bridge(
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
    entry: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Register Fairybread MCP server in Antigravity mcp_config.json and write the companion SKILL.md."""
    try:
        home, _ = _resolve_roots(home_dir, appdata_dir)
        mcp_cfg, skill_file = _antigravity_paths(home)
        server_entry = entry or get_mcp_server_entry()

        ok, msg = merge_json_mcp_server(mcp_cfg, server_entry, server_name="fairybread")
        if not ok:
            return False, msg

        console_py = str(server_entry.get("command") or resolve_console_python_executable())
        mcp_script = str((server_entry.get("args") or [str(get_mcp_script_path())])[0])
        skill_dir = skill_file.parent
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = f"""---
name: fairybread-council
description: Connect to the local Fairybread Multi-AI Council, High-Resolution 300-DPI Image Engine, Shared Memory Palace, and Exhaustive Email Search.
---

# Fairybread Multi-AI Council & Graphics Bridge

Use this skill whenever the user asks to consult their Fairybread council, generate high-resolution images/banners/prints via Fairybread, search their email via Fairybread, or inspect their Shared Memory Palace.

## Native MCP Tools (Configured in mcp_config.json)
Prefer the native MCP tools on server `fairybread`:
- `fairybread_ask_council`
- `fairybread_generate_image`
- `fairybread_search_email`
- `fairybread_search_memory`
- `fairybread_status`

## Fallback CLI Invocation
```powershell
"{console_py}" "{mcp_script}" --cli <tool_name> '<json_args>'
```
"""
        skill_file.write_text(skill_md, encoding="utf-8")
        return True, f"Linked Antigravity MCP ({mcp_cfg}) and skill ({skill_file})"
    except Exception as exc:
        return False, f"Could not install Antigravity bridge: {exc}"


def uninstall_antigravity_bridge(
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> tuple[bool, str]:
    home, _ = _resolve_roots(home_dir, appdata_dir)
    mcp_cfg, skill_file = _antigravity_paths(home)
    ok, msg = remove_json_mcp_server(mcp_cfg, server_name="fairybread")
    if not ok:
        return False, msg
    try:
        if skill_file.is_file():
            skill_file.unlink()
        if skill_file.parent.is_dir() and not any(skill_file.parent.iterdir()):
            skill_file.parent.rmdir()
    except OSError as exc:
        return False, f"Removed MCP config, but could not remove {skill_file}: {exc}"
    return True, f"Unlinked Antigravity MCP ({mcp_cfg}) and removed skill."


def install_codex_bridge(
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
    entry: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Register Fairybread as a stdio MCP server in ChatGPT Desktop / Codex CLI config.toml."""
    home, _ = _resolve_roots(home_dir, appdata_dir)
    cfg = _codex_config_path(home)
    server_entry = entry or get_mcp_server_entry()
    ok, msg = merge_toml_mcp_server(cfg, server_entry, server_name="fairybread")
    if not ok:
        return False, msg
    return True, f"Linked ChatGPT Desktop / Codex MCP in {cfg}. Restart ChatGPT Desktop and use Codex or Work mode."


def uninstall_codex_bridge(
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> tuple[bool, str]:
    home, _ = _resolve_roots(home_dir, appdata_dir)
    return remove_toml_mcp_server(_codex_config_path(home), server_name="fairybread")


def install_grok_bridge(
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
    entry: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Register Fairybread as a stdio MCP server in ~/.grok/config.toml (Grok Build CLI / Grok Bot)."""
    home, _ = _resolve_roots(home_dir, appdata_dir)
    cfg = _grok_config_path(home)
    server_entry = entry or get_mcp_server_entry()
    ok, msg = merge_toml_mcp_server(cfg, server_entry, server_name="fairybread")
    if not ok:
        return False, msg
    return True, f"Linked Grok MCP in {cfg}."


def uninstall_grok_bridge(
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> tuple[bool, str]:
    home, _ = _resolve_roots(home_dir, appdata_dir)
    return remove_toml_mcp_server(_grok_config_path(home), server_name="fairybread")


def install_claude_desktop_bridge(
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
    entry: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Register Fairybread as a local MCP server in Anthropic Claude Desktop."""
    _, appdata = _resolve_roots(home_dir, appdata_dir)
    cfg = _claude_config_path(appdata)
    server_entry = entry or get_mcp_server_entry()
    ok, msg = merge_json_mcp_server(cfg, server_entry, server_name="fairybread")
    if not ok:
        return False, msg
    return True, f"Linked Claude Desktop MCP in {cfg}. Restart Claude Desktop to activate."


def uninstall_claude_desktop_bridge(
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> tuple[bool, str]:
    _, appdata = _resolve_roots(home_dir, appdata_dir)
    return remove_json_mcp_server(_claude_config_path(appdata), server_name="fairybread")


def link_platform_foreman(
    platform_key: str,
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
    entry: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    key = (platform_key or "").strip().lower()
    if key == "codex":
        return install_codex_bridge(home_dir=home_dir, appdata_dir=appdata_dir, entry=entry)
    if key == "antigravity":
        return install_antigravity_bridge(home_dir=home_dir, appdata_dir=appdata_dir, entry=entry)
    if key == "grok":
        return install_grok_bridge(home_dir=home_dir, appdata_dir=appdata_dir, entry=entry)
    if key == "claude":
        return install_claude_desktop_bridge(home_dir=home_dir, appdata_dir=appdata_dir, entry=entry)
    return False, f"Unknown platform: {platform_key}"


def unlink_platform_foreman(
    platform_key: str,
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> tuple[bool, str]:
    key = (platform_key or "").strip().lower()
    if key == "codex":
        return uninstall_codex_bridge(home_dir=home_dir, appdata_dir=appdata_dir)
    if key == "antigravity":
        return uninstall_antigravity_bridge(home_dir=home_dir, appdata_dir=appdata_dir)
    if key == "grok":
        return uninstall_grok_bridge(home_dir=home_dir, appdata_dir=appdata_dir)
    if key == "claude":
        return uninstall_claude_desktop_bridge(home_dir=home_dir, appdata_dir=appdata_dir)
    return False, f"Unknown platform: {platform_key}"


def get_mcp_json_snippet(
    python_exe: str | None = None,
    script_path: Path | None = None,
) -> str:
    return json.dumps(
        {"mcpServers": {"fairybread": get_mcp_server_entry(python_exe=python_exe, script_path=script_path)}},
        indent=2,
    )


def get_toml_mcp_snippet(
    python_exe: str | None = None,
    script_path: Path | None = None,
    server_name: str = "fairybread",
) -> str:
    entry = get_mcp_server_entry(python_exe=python_exe, script_path=script_path)
    return _format_toml_server_block(entry, server_name=server_name)


def get_platform_copy_snippet(
    platform_key: str,
    python_exe: str | None = None,
    script_path: Path | None = None,
) -> str:
    key = (platform_key or "").strip().lower()
    if key in ("codex", "grok"):
        return get_toml_mcp_snippet(python_exe=python_exe, script_path=script_path)
    return get_mcp_json_snippet(python_exe=python_exe, script_path=script_path)


MCP_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "fairybread_ask_council",
        "description": "Ask the local Fairybread multi-AI council a question and return the synthesized consensus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question or task for the Fairybread council."},
                "rounds": {"type": "integer", "description": "Number of deliberation rounds (1 or 2).", "default": 2},
            },
            "required": ["question"],
        },
    },
    {
        "name": "fairybread_generate_image",
        "description": "Generate a high-resolution 300-DPI PNG image, social banner, or wallpaper using Fairybread's frontier image pipeline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Detailed visual prompt."},
                "title": {"type": "string", "description": "Short image title.", "default": "fairybread_image"},
                "size": {"type": "string", "description": "Preset (youtube_banner, facebook_group, print_8x10, 1024x1024, etc.).", "default": "1024x1024"},
                "quality": {"type": "string", "description": "high (default) or low/fast.", "default": "high"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "fairybread_search_email",
        "description": "Run an exhaustive zero-truncation email search across the user's configured mailbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'from:amazon', 'unread', 'invoice')."},
                "max_fetch_limit": {"type": "integer", "description": "Max emails to retrieve (default 500).", "default": 500},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fairybread_search_memory",
        "description": "Search the local Fairybread Shared Memory Palace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for the Memory Palace."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fairybread_status",
        "description": "Return the status of the local Fairybread installation, enabled council AIs, and bridge permissions.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def execute_bridge_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    cfg = load_bridge_settings(config_path)
    if not cfg.get("enabled", True):
        return {"error": "External Agent Bridge is disabled in Fairybread Settings."}

    depth = get_mcp_depth()
    if depth >= 1 and tool_name != "fairybread_status":
        return {"error": "Re-entrant Fairybread MCP call blocked (FAIRYBREAD_MCP_DEPTH >= 1) to prevent feedback loops."}

    if tool_name == "fairybread_status":
        from palace_config import load_enabled_provider_names

        active_cli = [
            f"{pk}_cli" for pk in get_council_cli_platforms(config_path) if find_cli_binary(pk)
        ]
        return {
            "status": "READY",
            "version": FAIRYBREAD_VERSION,
            "enabled_providers": load_enabled_provider_names(config_path=config_path) + active_cli,
            "bridge_settings": cfg,
            "mcp_depth": depth,
        }

    if tool_name == "fairybread_ask_council":
        if not cfg.get("allow_council_query", True):
            return {"error": "Council queries from external agents are disabled in Fairybread Settings."}
        from palace_cli import build_configured_palace

        prev_depth = os.environ.get("FAIRYBREAD_MCP_DEPTH")
        os.environ["FAIRYBREAD_MCP_DEPTH"] = str(max(1, depth + 1))
        try:
            palace = build_configured_palace(exclude_local_cli_providers=True, config_path=config_path)
            q = str(arguments.get("question", "")).strip()
            rounds = max(1, min(2, int(arguments.get("rounds", 2))))
            res = palace.run(q, max_rounds=rounds)
            return {
                "final_answer": res.final_answer,
                "contributors": res.contributors,
            }
        finally:
            if prev_depth is None:
                os.environ.pop("FAIRYBREAD_MCP_DEPTH", None)
            else:
                os.environ["FAIRYBREAD_MCP_DEPTH"] = prev_depth

    if tool_name == "fairybread_generate_image":
        if not cfg.get("allow_image_generation", True):
            return {"error": "Image generation from external agents is disabled in Fairybread Settings."}
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.instance() or QGuiApplication([])
        from palace_theme import generate_ai_image_to_png, get_image_engine_badge

        p = generate_ai_image_to_png(
            prompt=str(arguments.get("prompt", "")),
            title=str(arguments.get("title", "fairybread_image")),
            size=str(arguments.get("size", "1024x1024")),
            quality=str(arguments.get("quality", "high")),
            allow_network=True,
        )
        if p and p.exists():
            return {"image_path": str(p), "engine": get_image_engine_badge(p)}
        return {"error": "Image generation failed or no image provider keys configured."}

    if tool_name == "fairybread_search_email":
        if not cfg.get("allow_email_search", True):
            return {"error": "Email search from external agents is disabled in Fairybread Settings."}
        from email_service import exhaustive_search_emails

        res = exhaustive_search_emails(
            str(arguments.get("query", "")),
            max_fetch_limit=int(arguments.get("max_fetch_limit", 500)),
        )
        return {
            "succeeded": res.succeeded,
            "total_matched": res.total_matched,
            "analyzed_count": res.analyzed_count,
            "folder_searched": res.folder_searched,
            "formatted": res.format_for_council_prompt(),
            "error": res.error,
        }

    if tool_name == "fairybread_search_memory":
        if not cfg.get("allow_memory_search", True):
            return {"error": "Memory search from external agents is disabled in Fairybread Settings."}
        from memory_service import MemoryService

        ms = MemoryService()
        mres = ms.search(str(arguments.get("query", "")))
        return {"succeeded": mres.succeeded, "context": mres.context, "error": mres.error}

    return {"error": f"Unknown Fairybread MCP tool: {tool_name}"}


def run_stdio_mcp_server() -> None:
    """Standard JSON-RPC 2.0 stdio MCP server loop with stdout isolation."""
    real_stdout = sys.stdout
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fairybread-mcp", "version": FAIRYBREAD_VERSION},
                },
            }
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": MCP_TOOLS_SCHEMA},
            }
        elif method == "tools/call":
            t_name = str(params.get("name", ""))
            t_args = params.get("arguments") or {}
            with contextlib.redirect_stdout(sys.stderr):
                out = execute_bridge_tool(t_name, t_args)
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(out, indent=2)}],
                    "isError": "error" in out and bool(out["error"]),
                },
            }
        elif req_id is not None:
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        else:
            continue

        real_stdout.write(json.dumps(resp) + "\n")
        real_stdout.flush()


def test_mcp_bridge_live(
    script_path: Path | None = None,
    timeout_sec: float = 12.0,
) -> tuple[bool, str]:
    """Spawn Fairybread MCP server (python.exe fairybread_mcp.py or frozen FairybreadMCP.exe) over stdio pipes."""
    use_frozen_exe = False
    frozen_exe = get_app_install_dir() / "FairybreadMCP.exe"
    if script_path is None and is_frozen_app() and frozen_exe.is_file():
        use_frozen_exe = True
        cmd = [str(frozen_exe)]
        py_exe = str(frozen_exe)
    else:
        py_exe = resolve_console_python_executable()
        mcp_script = Path(script_path or get_mcp_script_path())
        if not mcp_script.is_file():
            return False, f"MCP script not found: {mcp_script}"
        cmd = [py_exe, str(mcp_script)]

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "self-test", "version": "1.0"}},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "fairybread_status", "arguments": {}},
        },
    ]
    # Note: notifications/initialized has no id so it produces no reply; avoid duplicate id by omitting id on notification
    requests[1] = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    payload = "\n".join(json.dumps(r) for r in requests) + "\n"

    env = dict(os.environ)
    env["FAIRYBREAD_MCP_DEPTH"] = "0"
    env.setdefault("PYTHONUNBUFFERED", "1")

    kwargs: dict[str, Any] = {
        "input": payload,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout_sec,
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        return False, f"MCP self-test timed out after {timeout_sec:.0f}s."
    except Exception as exc:
        return False, f"Could not launch MCP server '{cmd[0]}': {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or f"exit code {proc.returncode}").strip()[:280]
        return False, f"MCP server exited with code {proc.returncode}: {err}"

    responses: dict[int, dict[str, Any]] = {}
    for raw_line in (proc.stdout or "").splitlines():
        clean = raw_line.strip()
        if not clean:
            continue
        try:
            obj = json.loads(clean)
        except ValueError as exc:
            return False, f"Corrupt non-JSON stdout from MCP server ({exc}): {clean[:120]}"
        if isinstance(obj, dict) and obj.get("id") is not None:
            responses[int(obj["id"])] = obj

    init_res = responses.get(1, {}).get("result") or {}
    if not init_res.get("protocolVersion"):
        return False, "MCP handshake failed: initialize returned no protocolVersion."

    tools = (responses.get(2, {}).get("result") or {}).get("tools") or []
    if len(tools) < 5:
        return False, f"MCP tools/list expected >= 5 tools, got {len(tools)}."

    status_call = responses.get(3, {}).get("result") or {}
    content_items = status_call.get("content") or []
    if not content_items:
        return False, "MCP fairybread_status returned empty content."
    try:
        status_json = json.loads(content_items[0].get("text", "{}"))
    except ValueError as exc:
        return False, f"MCP fairybread_status payload was not valid JSON: {exc}"

    if status_call.get("isError"):
        return False, f"MCP bridge disabled or errored: {status_json.get('error', 'unknown error')}"
    if status_json.get("status") != "READY":
        return False, f"MCP bridge status was '{status_json.get('status')}', expected READY."

    provs = status_json.get("enabled_providers") or []
    return True, f"MCP stdio verified ({Path(py_exe).name}): {len(tools)} tools ready, {len(provs)} AI(s) active."


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--cleanup-install-dir":
        removed = cleanup_external_mcp_for_dir(sys.argv[2])
        print(json.dumps({"removed": removed}, indent=2))
    elif len(sys.argv) >= 3 and sys.argv[1] == "--cli":
        t_name = sys.argv[2]
        t_args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
        print(json.dumps(execute_bridge_tool(t_name, t_args), indent=2))
    else:
        run_stdio_mcp_server()
