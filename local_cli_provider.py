"""Local CLI provider & external AI platform detector for Fairybread Council Member mode.

Wraps external CLI tools (OpenAI Codex CLI, Google Antigravity CLI, xAI Grok Build CLI,
and Anthropic Claude Code CLI) as AIProvider instances while enforcing FAIRYBREAD_MCP_DEPTH
recursion guards so MCP Foreman calls and Council Member calls can never loop.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from typing import Any

from providers import AIProvider, ProviderResponse


def _grok_extra_paths(home_dir: Path | None = None) -> list[Path]:
    home = home_dir or Path.home()
    return [
        home / ".grok" / "bin" / "grok.exe",
        home / ".grok" / "bin" / "grok",
    ]


def _extra_cli_paths(
    platform_key: str,
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> list[Path]:
    home = home_dir or Path.home()
    if appdata_dir is not None:
        appdata = appdata_dir
    elif home_dir is not None:
        appdata = home_dir / "AppData" / "Roaming"
    else:
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))

    key = (platform_key or "").strip().lower()
    if key == "grok":
        return [
            *_grok_extra_paths(home),
            home / ".local" / "bin" / "grok.exe",
            home / ".local" / "bin" / "grok",
        ]
    if key == "claude":
        return [
            home / ".local" / "bin" / "claude.exe",
            home / ".local" / "bin" / "claude",
            appdata / "npm" / "claude.cmd",
            appdata / "npm" / "claude.exe",
        ]
    if key == "codex":
        return [
            appdata / "npm" / "codex.cmd",
            appdata / "npm" / "codex.exe",
            home / ".local" / "bin" / "codex.exe",
        ]
    if key == "antigravity":
        return [
            appdata / "npm" / "agy.cmd",
            home / ".local" / "bin" / "agy.exe",
            home / ".local" / "bin" / "agy.cmd",
        ]
    return []


EXTERNAL_CLI_SPECS: dict[str, dict[str, Any]] = {
    "codex": {
        "provider_key": "codex_cli",
        "display": "Codex CLI (ChatGPT)",
        "short": "Codex CLI",
        "binary": "codex",
        "default_extra_paths": [],
        "install_hint": "Install OpenAI Codex CLI (npm i -g @openai/codex) & run codex login",
    },
    "antigravity": {
        "provider_key": "antigravity_cli",
        "display": "Antigravity CLI",
        "short": "Antigravity",
        "binary": "agy",
        "default_extra_paths": [],
        "install_hint": "Install Antigravity CLI (agy) or pip install google-antigravity",
    },
    "grok": {
        "provider_key": "grok_cli",
        "display": "Grok CLI (xAI)",
        "short": "Grok CLI",
        "binary": "grok",
        "default_extra_paths": _grok_extra_paths(),
        "install_hint": "Run: irm https://x.ai/cli/install.ps1 | iex",
    },
    "claude": {
        "provider_key": "claude_cli",
        "display": "Claude CLI",
        "short": "Claude CLI",
        "binary": "claude",
        "default_extra_paths": [],
        "install_hint": "Install Claude Code CLI (npm i -g @anthropic-ai/claude-code) & run claude login",
    },
}

CLI_PROVIDER_TO_PLATFORM: dict[str, str] = {
    spec["provider_key"]: platform_key
    for platform_key, spec in EXTERNAL_CLI_SPECS.items()
}
PLATFORM_TO_CLI_PROVIDER: dict[str, str] = {
    v: k for k, v in CLI_PROVIDER_TO_PLATFORM.items()
}


def get_mcp_depth() -> int:
    try:
        return int(os.environ.get("FAIRYBREAD_MCP_DEPTH", "0") or "0")
    except ValueError:
        return 0


def find_cli_binary(
    platform_key: str,
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> str | None:
    """Locate the local CLI executable (or SDK marker for Antigravity) if installed."""
    key = (platform_key or "").strip().lower()
    spec = EXTERNAL_CLI_SPECS.get(key)
    if spec is None:
        return None

    binary_name = str(spec.get("binary") or "").strip()
    if binary_name:
        found = shutil.which(binary_name)
        if found:
            return found

    extra_paths = _extra_cli_paths(key, home_dir=home_dir, appdata_dir=appdata_dir)
    if not extra_paths:
        extra_paths = list(spec.get("default_extra_paths") or [])
    for candidate in extra_paths:
        p = Path(candidate)
        if p.is_file():
            return str(p)

    if key == "antigravity":
        try:
            if importlib.util.find_spec("google.antigravity") is not None:
                return "python-sdk:google.antigravity"
        except (ImportError, ValueError, ModuleNotFoundError):
            pass

    return None


def _platform_config_path(platform_key: str, home: Path, appdata: Path) -> tuple[Path, str]:
    if platform_key == "codex":
        return home / ".codex" / "config.toml", "toml"
    if platform_key == "antigravity":
        return home / ".gemini" / "config" / "mcp_config.json", "json"
    if platform_key == "grok":
        return home / ".grok" / "config.toml", "toml"
    if platform_key == "claude":
        return appdata / "Claude" / "claude_desktop_config.json", "json"
    raise ValueError(f"Unsupported external platform: {platform_key}")


def _is_fairybread_in_config(config_path: Path, fmt: str) -> bool:
    if not config_path.is_file():
        return False
    try:
        text = config_path.read_text(encoding="utf-8")
        if fmt == "toml":
            parsed = tomllib.loads(text)
            servers = parsed.get("mcp_servers")
            return isinstance(servers, dict) and "fairybread" in servers
        parsed = json.loads(text)
        servers = parsed.get("mcpServers")
        return isinstance(servers, dict) and "fairybread" in servers
    except Exception:
        return False


def detect_external_platforms(
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Inspect config paths and local CLI availability for all supported platforms without mutating files."""
    home = home_dir or Path.home()
    appdata = appdata_dir or Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    out: dict[str, dict[str, Any]] = {}
    for pk, spec in EXTERNAL_CLI_SPECS.items():
        cfg_path, fmt = _platform_config_path(pk, home, appdata)
        cli_path = find_cli_binary(pk, home_dir=home, appdata_dir=appdata)
        out[pk] = {
            "platform": pk,
            "provider_key": spec["provider_key"],
            "display": spec["display"],
            "short": spec["short"],
            "config_path": cfg_path,
            "config_format": fmt,
            "config_dir_exists": cfg_path.parent.is_dir(),
            "config_file_exists": cfg_path.is_file(),
            "mcp_linked": _is_fairybread_in_config(cfg_path, fmt),
            "cli_path": cli_path,
            "cli_available": bool(cli_path),
            "install_hint": spec["install_hint"],
        }
    return out


def _extract_text_from_json_obj(obj: Any) -> str:
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, list):
        parts = [_extract_text_from_json_obj(item) for item in obj]
        return "\n".join(p for p in parts if p).strip()
    if isinstance(obj, dict):
        for field in ("result", "response", "final_answer", "text", "content", "message"):
            if field in obj and obj[field]:
                val = _extract_text_from_json_obj(obj[field])
                if val:
                    return val
    return ""


class LocalCLIProvider(AIProvider):
    """Run a locally installed external AI CLI cleanly as a Fairybread council provider."""

    def __init__(
        self,
        platform_key: str,
        cli_path: str | None = None,
        timeout_sec: int = 0,
        handshake_sec: int = 15,
    ) -> None:
        key = (platform_key or "").strip().lower()
        if key not in EXTERNAL_CLI_SPECS:
            raise ValueError(f"Unsupported local CLI platform: {platform_key}")
        self.platform_key = key
        self.spec = EXTERNAL_CLI_SPECS[key]
        self.provider_name = str(self.spec["provider_key"])
        self.cli_path = cli_path or find_cli_binary(key)
        self.timeout_sec = 0 if int(timeout_sec or 0) <= 0 else max(10, int(timeout_sec))
        self.handshake_sec = max(5, int(handshake_sec or 15))

    def build_command(self, prompt: str) -> list[str]:
        exe = self.cli_path or find_cli_binary(self.platform_key) or str(self.spec["binary"])
        if self.platform_key == "codex":
            return [exe, "exec", "--skip-git-repo-check", prompt]
        if self.platform_key == "grok":
            return [exe, "--no-auto-update", "-p", prompt, "--output-format", "json"]
        if self.platform_key == "claude":
            return [exe, "-p", prompt]
        if self.platform_key == "antigravity":
            return [exe, "-p", prompt]
        raise ValueError(f"Unsupported local CLI platform: {self.platform_key}")

    def parse_output(self, stdout: str) -> str:
        raw = (stdout or "").strip()
        if not raw:
            return ""
        # Try single JSON payload first (especially for Grok --output-format json)
        try:
            parsed = json.loads(raw)
            extracted = _extract_text_from_json_obj(parsed)
            if extracted:
                return extracted
        except ValueError:
            pass

        # Fallback: check newline-delimited JSON event streams
        if "\n" in raw or raw.startswith("{"):
            chunks: list[str] = []
            json_lines = 0
            for line in raw.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    evt = json.loads(stripped)
                    json_lines += 1
                    piece = _extract_text_from_json_obj(evt)
                    if piece:
                        chunks.append(piece)
                except ValueError:
                    continue
            if json_lines > 0 and chunks:
                return "\n".join(chunks).strip()

        return raw

    def generate(self, prompt: str) -> ProviderResponse:
        if get_mcp_depth() >= 1:
            raise RuntimeError("Blocked local CLI call inside an MCP-originated turn to prevent recursion.")

        exe = self.cli_path or find_cli_binary(self.platform_key)
        if not exe:
            raise RuntimeError(
                f"{self.spec['display']} CLI is not installed. {self.spec['install_hint']}"
            )
        if exe == "python-sdk:google.antigravity":
            raise RuntimeError(
                "Antigravity Python SDK found without the 'agy' CLI executable; install the 'agy' CLI to run synchronous Council Member turns."
            )

        cmd = self.build_command(prompt)
        cmd[0] = exe
        env = dict(os.environ)
        env["FAIRYBREAD_MCP_DEPTH"] = str(max(1, get_mcp_depth() + 1))

        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": None if self.timeout_sec <= 0 else self.timeout_sec,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sum(len(str(a)) + 1 for a in cmd) > 28000:
                if self.platform_key == "codex":
                    cmd = [exe, "exec", "--skip-git-repo-check", "-"]
                    kwargs["input"] = prompt
                elif self.platform_key == "claude":
                    cmd = [exe, "-p"]
                    kwargs["input"] = prompt
                else:
                    raise RuntimeError(
                        f"{self.spec['display']} prompt ({len(prompt)} chars) exceeds Windows CreateProcess command-line limit."
                    )

        try:
            proc = subprocess.run(cmd, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{self.spec['display']} timed out after {self.timeout_sec}s.") from exc
        except OSError as exc:
            raise RuntimeError(f"{self.spec['display']} process failed: {exc}") from exc
        parsed = self.parse_output(proc.stdout or "")
        if proc.returncode != 0:
            err_detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()[:320]
            raise RuntimeError(f"{self.spec['display']} failed: {err_detail}")
        if not parsed:
            raise RuntimeError(f"{self.spec['display']} returned an empty response.")

        return ProviderResponse(
            text=parsed,
            model=f"{self.platform_key}-cli",
            provider=self.provider_name,
        )
