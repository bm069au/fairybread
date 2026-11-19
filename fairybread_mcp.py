"""Universal MCP (Model Context Protocol) Server & One-Click External Agent Bridge for Fairybread.

Allows Google Antigravity, Anthropic Claude Desktop / Claude Code, OpenAI ChatGPT Desktop / Codex CLI,
and Cursor/Windsurf to query the Fairybread 6-AI Council, generate high-resolution 300-DPI images/banners,
run exhaustive EvidenceBench-style email searches, and query the Shared Memory Palace.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from palace_config import CONFIG_PATH, _read_raw_config, _write_raw_config


DEFAULT_BRIDGE_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "allow_council_query": True,
    "allow_image_generation": True,
    "allow_email_search": True,
    "allow_memory_search": True,
    "allow_code_self_upgrade": False,  # Locked by default unless operator explicitly enables
}


def load_bridge_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    raw = _read_raw_config(config_path)
    saved = raw.get("external_agent_bridge", {})
    merged = dict(DEFAULT_BRIDGE_SETTINGS)
    if isinstance(saved, dict):
        merged.update(saved)
    return merged


def save_bridge_settings(
    settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    raw = _read_raw_config(config_path)
    merged = load_bridge_settings(config_path)
    for k in DEFAULT_BRIDGE_SETTINGS:
        if k in settings:
            merged[k] = bool(settings[k])
    raw["external_agent_bridge"] = merged
    _write_raw_config(raw, config_path)
    return merged


def get_mcp_script_path() -> Path:
    live_path = Path(r"C:\Palace_Live\fairybread_mcp.py")
    if live_path.exists():
        return live_path
    return Path(__file__).resolve()


def get_mcp_server_entry() -> dict[str, Any]:
    return {
        "command": sys.executable,
        "args": [str(get_mcp_script_path())],
    }


def install_antigravity_bridge() -> tuple[bool, str]:
    """Install the Fairybread skill and MCP configuration for Google Antigravity."""
    try:
        home = Path.home()
        skill_dir = home / ".gemini" / "config" / "skills" / "fairybread-council"
        skill_dir.mkdir(parents=True, exist_ok=True)
        mcp_script = get_mcp_script_path()
        skill_md = f"""---
name: fairybread-council
description: Connect to the local Fairybread Multi-AI Council, High-Resolution 300-DPI Image Engine, Shared Memory Palace, and Exhaustive Email Search.
---

# Fairybread Multi-AI Council & Graphics Bridge

Use this skill whenever the user asks to consult their Fairybread council, generate high-resolution images/banners/prints via Fairybread, search their email via Fairybread, or inspect their Shared Memory Palace.

## CLI / JSON-RPC Tool Invocation
Run the local bridge script via Python:
```powershell
"{sys.executable}" "{mcp_script}" --cli <tool_name> '<json_args>'
```

### Available Tools:
1. `fairybread_ask_council`: `{{"question": "...", "rounds": 2}}`
2. `fairybread_generate_image`: `{{"prompt": "...", "title": "...", "size": "1024x1024", "quality": "high"}}`
3. `fairybread_search_email`: `{{"query": "from:...", "max_fetch_limit": 500}}`
4. `fairybread_search_memory`: `{{"query": "..."}}`
5. `fairybread_status`: `{{}}`
"""
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        return True, f"Installed Google Antigravity skill at {skill_dir / 'SKILL.md'}"
    except Exception as exc:
        return False, f"Could not install Antigravity bridge: {exc}"


def install_claude_desktop_bridge() -> tuple[bool, str]:
    """Register Fairybread as a local MCP server in Anthropic Claude Desktop (%APPDATA%\\Claude\\claude_desktop_config.json)."""
    try:
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        claude_dir = appdata / "Claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = claude_dir / "claude_desktop_config.json"
        existing: dict[str, Any] = {}
        if cfg_file.exists():
            try:
                existing = json.loads(cfg_file.read_text(encoding="utf-8"))
            except ValueError:
                existing = {}
        mcp_servers = existing.setdefault("mcpServers", {})
        mcp_servers["fairybread"] = get_mcp_server_entry()
        cfg_file.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        return True, f"Registered 'fairybread' MCP server in {cfg_file}"
    except Exception as exc:
        return False, f"Could not update Claude Desktop config: {exc}"


def get_mcp_json_snippet() -> str:
    return json.dumps({"mcpServers": {"fairybread": get_mcp_server_entry()}}, indent=2)


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


def execute_bridge_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    cfg = load_bridge_settings()
    if not cfg.get("enabled", True):
        return {"error": "External Agent Bridge is disabled in Fairybread Settings."}

    if tool_name == "fairybread_status":
        from palace_config import load_enabled_provider_names
        return {
            "status": "READY",
            "enabled_providers": load_enabled_provider_names(),
            "bridge_settings": cfg,
        }

    if tool_name == "fairybread_ask_council":
        if not cfg.get("allow_council_query", True):
            return {"error": "Council queries from external agents are disabled in Fairybread Settings."}
        from palace_cli import build_configured_palace
        palace = build_configured_palace()
        q = str(arguments.get("question", "")).strip()
        rounds = max(1, min(2, int(arguments.get("rounds", 2))))
        res = palace.run(q, max_rounds=rounds)
        return {
            "final_answer": res.final_answer,
            "contributors": res.contributors,
        }

    if tool_name == "fairybread_generate_image":
        if not cfg.get("allow_image_generation", True):
            return {"error": "Image generation from external agents is disabled in Fairybread Settings."}
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance() or QGuiApplication([])
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
    """Standard JSON-RPC 2.0 stdio MCP server loop for Claude Desktop, Antigravity, ChatGPT Desktop, and Cursor."""
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
                    "serverInfo": {"name": "fairybread-mcp", "version": "0.9.1e"},
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

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--cli":
        t_name = sys.argv[2]
        t_args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
        print(json.dumps(execute_bridge_tool(t_name, t_args), indent=2))
    else:
        run_stdio_mcp_server()
