"""Antigravity-style Workspace File & Command Tools for Fairybread.

Provides [FILE_LIST], [FILE_READ], [FILE_WRITE], [FILE_PATCH], and [RUN_CMD]
for working across user projects (e.g. C:, E:, G:), strictly gated through
access_policy.py so the Write Exclusion List always overrides Turbo/Auto.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import uuid4

from access_policy import (
    evaluate_command_access,
    evaluate_path_access,
    load_access_permissions,
    normalize_exclusion_path_str,
)
from palace_config import CONFIG_PATH

_KV_ATTR_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:"([^"]*)"|(\d+))')

_FILE_LIST_TAG_RE = re.compile(r"\[FILE_LIST\b([^\]]*)\]", re.IGNORECASE)
_FILE_READ_TAG_RE = re.compile(r"\[FILE_READ\b([^\]]*)\]", re.IGNORECASE)

_FILE_WRITE_BLOCK_RE = re.compile(
    r'\[FILE_WRITE\b([^\]]*)\]\s*\r?\n?<<<CONTENT\r?\n(?P<content>.*?)\r?\n?>>>\s*(?:\[/FILE_WRITE\])?',
    re.DOTALL | re.IGNORECASE,
)

_FILE_PATCH_BLOCK_RE = re.compile(
    r'\[FILE_PATCH\b([^\]]*)\]\s*\r?\n?<<<TARGET\r?\n(?P<target>.*?)\r?\n===REPLACE\r?\n(?P<replacement>.*?)\r?\n?>>>\s*(?:\[/FILE_PATCH\])?',
    re.DOTALL | re.IGNORECASE,
)

_RUN_CMD_BLOCK_RE = re.compile(
    r'\[RUN_CMD\b([^\]]*)\]\s*\r?\n?(?P<command>.*?)\r?\n?\[/RUN_CMD\]',
    re.DOTALL | re.IGNORECASE,
)


def _parse_attrs(attr_str: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, s_val, i_val in _KV_ATTR_RE.findall(attr_str or ""):
        out[k.lower()] = s_val if s_val != "" or i_val == "" else i_val
    return out


def _resolve_target_path(raw_path: str, project_folder: str = "") -> Path:
    clean = normalize_exclusion_path_str(raw_path)
    if not clean:
        clean = str(project_folder or ".")
    p = Path(clean).expanduser()
    if not p.is_absolute() and project_folder:
        p = Path(project_folder).expanduser() / p
    try:
        return p.resolve(strict=False)
    except OSError:
        return p


def execute_readonly_workspace_tools_in_text(
    response_text: str,
    *,
    project_folder: str = "",
) -> str:
    """Execute read-only [FILE_LIST] and [FILE_READ] requests and return formatted results."""
    if not response_text or ("[FILE_LIST" not in response_text.upper() and "[FILE_READ" not in response_text.upper()):
        return ""

    outputs: list[str] = []

    for m in _FILE_LIST_TAG_RE.finditer(response_text):
        attrs = _parse_attrs(m.group(1))
        raw_p = attrs.get("path") or project_folder or "."
        target = _resolve_target_path(raw_p, project_folder)
        if not target.exists() or not target.is_dir():
            outputs.append(f"[📁 FILE_LIST `{target}`]: Directory not found.")
            continue
        try:
            entries = sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            lines = [
                f"{'[DIR] ' if e.is_dir() else '[FILE]'} {e.name}"
                for e in entries[:120]
            ]
            more = f"\n... (+{len(entries) - 120} more)" if len(entries) > 120 else ""
            outputs.append(f"[📁 FILE_LIST `{target}` ({len(entries)} items)]:\n" + "\n".join(lines) + more)
        except OSError as exc:
            outputs.append(f"[📁 FILE_LIST `{target}`]: Error: {exc}")

    for m in _FILE_READ_TAG_RE.finditer(response_text):
        attrs = _parse_attrs(m.group(1))
        raw_p = attrs.get("path", "")
        if not raw_p:
            outputs.append("[📄 FILE_READ]: Missing path=\"...\" attribute.")
            continue
        target = _resolve_target_path(raw_p, project_folder)
        if not target.exists() or not target.is_file():
            outputs.append(f"[📄 FILE_READ `{target}`]: File not found.")
            continue
        try:
            start_ln = max(1, int(attrs.get("start") or 1))
        except ValueError:
            start_ln = 1
        try:
            end_ln = max(start_ln, int(attrs.get("end") or (start_ln + 119)))
        except ValueError:
            end_ln = start_ln + 119
        end_ln = min(end_ln, start_ln + 199)
        try:
            all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            e_clip = min(len(all_lines), end_ln)
            snippet = "\n".join(f"{i}: {all_lines[i - 1]}" for i in range(start_ln, e_clip + 1))
            outputs.append(
                f"[📄 FILE_READ `{target}` lines {start_ln}-{e_clip} of {len(all_lines)}]:\n{snippet[:8000]}"
            )
        except OSError as exc:
            outputs.append(f"[📄 FILE_READ `{target}`]: Error: {exc}")

    return "\n\n".join(outputs)


def execute_approved_action(action: dict[str, Any]) -> tuple[bool, str]:
    """Execute one approved workspace action dict (`file_write`, `file_patch`, or `run_cmd`)."""
    kind = str(action.get("kind") or "").strip().lower()
    payload = action.get("payload") or {}

    if kind == "file_write":
        target = Path(str(action.get("path") or ""))
        content = str(payload.get("content") or "")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return True, f"Wrote {len(content)} chars to `{target}`."
        except OSError as exc:
            return False, f"Failed writing `{target}`: {exc}"

    if kind == "file_patch":
        target = Path(str(action.get("path") or ""))
        old_txt = str(payload.get("target") or "")
        new_txt = str(payload.get("replacement") or "")
        if not target.exists() or not target.is_file():
            return False, f"Target file not found for patch: `{target}`."
        if not old_txt:
            return False, f"Empty <<<TARGET block for `{target}`."
        try:
            cur_txt = target.read_text(encoding="utf-8", errors="replace")
            if old_txt not in cur_txt:
                norm_cur = cur_txt.replace("\r\n", "\n")
                norm_old = old_txt.replace("\r\n", "\n")
                if norm_old not in norm_cur:
                    return False, f"<<<TARGET text not found in `{target}`."
                updated = norm_cur.replace(norm_old, new_txt.replace("\r\n", "\n"), 1)
                if "\r\n" in cur_txt:
                    updated = updated.replace("\n", "\r\n")
            else:
                updated = cur_txt.replace(old_txt, new_txt, 1)
            target.write_text(updated, encoding="utf-8")
            return True, f"Patched `{target}` cleanly."
        except OSError as exc:
            return False, f"Failed patching `{target}`: {exc}"

    if kind == "run_cmd":
        cmd = str(payload.get("command") or "").strip()
        cwd_str = str(action.get("cwd") or "").strip()
        if not cmd:
            return False, "Empty command block."
        cwd_path = Path(cwd_str) if cwd_str and Path(cwd_str).is_dir() else None
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                cwd=str(cwd_path) if cwd_path else None,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            combined = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
            if len(combined) > 4000:
                combined = combined[:4000] + "\n...[truncated]"
            ok = proc.returncode == 0
            header = f"Command exited with code {proc.returncode}."
            return ok, f"{header}\n{combined}".strip()
        except Exception as exc:
            return False, f"Command error: {exc}"

    return False, f"Unsupported action kind '{kind}'."


def process_workspace_actions_in_text(
    response_text: str,
    *,
    project_folder: str = "",
    config_path: Path = CONFIG_PATH,
    permissions: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Evaluate [FILE_WRITE], [FILE_PATCH], and [RUN_CMD] blocks via access_policy.

    Returns (executed_actions, pending_actions, formatted_status_md).
    """
    text = response_text or ""
    upper = text.upper()
    if "[FILE_WRITE" not in upper and "[FILE_PATCH" not in upper and "[RUN_CMD" not in upper:
        return [], [], ""

    cfg = dict(permissions) if isinstance(permissions, dict) else load_access_permissions(config_path)
    allow_writes = bool(cfg.get("allow_workspace_writes", True))
    allow_shell = bool(cfg.get("allow_shell_commands", True))

    candidates: list[tuple[int, dict[str, Any]]] = []

    for m in _FILE_WRITE_BLOCK_RE.finditer(text):
        attrs = _parse_attrs(m.group(1))
        target = _resolve_target_path(attrs.get("path", ""), project_folder)
        summary = (attrs.get("summary") or f"Write {target.name}").strip()
        content = m.group("content")
        candidates.append((
            m.start(),
            {
                "id": str(uuid4()),
                "kind": "file_write",
                "path": str(target),
                "cwd": str(target.parent),
                "summary": summary,
                "preview": f"Write `{target}` ({len(content)} chars)",
                "payload": {"content": content},
            },
        ))

    for m in _FILE_PATCH_BLOCK_RE.finditer(text):
        attrs = _parse_attrs(m.group(1))
        target = _resolve_target_path(attrs.get("path", ""), project_folder)
        summary = (attrs.get("summary") or f"Patch {target.name}").strip()
        old_t = m.group("target")
        new_t = m.group("replacement")
        candidates.append((
            m.start(),
            {
                "id": str(uuid4()),
                "kind": "file_patch",
                "path": str(target),
                "cwd": str(target.parent),
                "summary": summary,
                "preview": f"Patch `{target}` (-{len(old_t.splitlines())} / +{len(new_t.splitlines())} lines)",
                "payload": {"target": old_t, "replacement": new_t},
            },
        ))

    for m in _RUN_CMD_BLOCK_RE.finditer(text):
        attrs = _parse_attrs(m.group(1))
        cmd = (m.group("command") or "").strip()
        raw_cwd = attrs.get("cwd") or project_folder or ""
        cwd_p = str(_resolve_target_path(raw_cwd, project_folder)) if raw_cwd else ""
        summary = (attrs.get("summary") or "Run workspace command").strip()
        candidates.append((
            m.start(),
            {
                "id": str(uuid4()),
                "kind": "run_cmd",
                "path": cwd_p,
                "cwd": cwd_p,
                "summary": summary,
                "preview": f"Run `{cmd[:140]}`" + (f" (in `{cwd_p}`)" if cwd_p else ""),
                "payload": {"command": cmd},
            },
        ))

    candidates.sort(key=lambda item: item[0])

    executed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    md_lines: list[str] = []

    for _pos, act in candidates:
        kind = act["kind"]
        if kind in {"file_write", "file_patch"}:
            dec = evaluate_path_access(act["path"], "patch" if kind == "file_patch" else "write", permissions=cfg)
            if not allow_writes:
                act["excluded"] = dec.excluded
                act["reason"] = (
                    dec.reason
                    if dec.excluded
                    else "Project File Editing is disabled in AI Access Permissions — approve once or enable it in Settings."
                )
                pending.append(act)
                md_lines.append(f"⏸ **Pending Approval (`{act['preview']}`)**: {act['reason']}")
                continue
        else:
            dec = evaluate_command_access(act["payload"]["command"], cwd=act["cwd"], permissions=cfg)
            if not allow_shell:
                act["excluded"] = dec.excluded
                act["reason"] = (
                    dec.reason
                    if dec.excluded
                    else "Terminal / Shell Commands are disabled in AI Access Permissions — approve once or enable it in Settings."
                )
                pending.append(act)
                md_lines.append(f"⏸ **Pending Approval (`{act['preview']}`)**: {act['reason']}")
                continue

        if dec.decision == "allow":
            ok, res_msg = execute_approved_action(act)
            act["succeeded"] = ok
            act["output"] = res_msg
            executed.append(act)
            icon = "✓" if ok else "⚠"
            md_lines.append(f"{icon} **{act['summary']}**: {res_msg}")
        else:
            act["excluded"] = dec.excluded
            act["reason"] = dec.reason
            pending.append(act)
            tag = "🛡 Write Exclusion" if dec.excluded else "⏸ Approval Required"
            md_lines.append(f"**{tag} (`{act['preview']}`)**: {dec.reason}")

    return executed, pending, "\n".join(md_lines)
