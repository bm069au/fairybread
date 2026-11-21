"""Deterministic AI Access Permissions & Write Exclusion Policy for Fairybread.

Provides Antigravity-style execution modes (Request Review, Default, Auto, Turbo)
plus an unlimited user-configured Write Exclusion List (per-entry recursive toggle)
that ALWAYS sits on top of every mode — even Turbo — enforced in Python before
any file modification or workspace command runs.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
from pathlib import Path
import re
from typing import Any

from palace_config import CONFIG_PATH, _read_raw_config, _write_raw_config

PERMISSION_MODES = ("request_review", "default", "auto", "turbo")

PERMISSION_MODE_META: dict[str, dict[str, str]] = {
    "request_review": {
        "label": "Request Review",
        "pill": "Review",
        "description": "Every file edit, patch, or command requires your approval.",
    },
    "default": {
        "label": "Default",
        "pill": "Default",
        "description": "Ask before file edits, patches, or shell commands.",
    },
    "auto": {
        "label": "Auto",
        "pill": "Auto",
        "description": "Automatically decide if safe edits & commands run; ask before destructive actions.",
    },
    "turbo": {
        "label": "Turbo",
        "pill": "Turbo",
        "description": "Run all unprotected commands & edits without restrictions (Exclusion List still asks).",
    },
}

DEFAULT_ACCESS_PERMISSIONS: dict[str, Any] = {
    "permission_mode": "default",
    "write_exclusions": [],  # Empty by default: list[{"path": str, "include_subdirs": bool}]
    "allow_workspace_writes": True,
    "allow_shell_commands": True,
    "allow_self_patch": True,
}

_LEGACY_APPROVAL_TO_PERMISSION = {
    "read_only": "request_review",
    "on_request": "default",
    "auto_deploy": "turbo",
}

_PERMISSION_TO_LEGACY_APPROVAL = {
    "request_review": "read_only",
    "default": "on_request",
    "auto": "auto_deploy",
    "turbo": "auto_deploy",
}

_DESTRUCTIVE_CMD_RE = re.compile(
    r"(?i)(?:^|[\s;|&(])("
    r"rm\s+-r|remove-item|del\b|erase\b|rmdir\b|rd\s+/s|format\b|"
    r"diskpart\b|clear-content\b|reg\s+delete\b|stop-process\b|"
    r"taskkill\b|shutdown\b|git\s+push\b|git\s+reset\s+--hard\b"
    r")"
)

_WINDOWS_PATH_TOKEN_RE = re.compile(
    r'([A-Za-z]:(?:\\|/)[^\r\n"\'|;&<>`]*|[A-Za-z]:(?=[\s"\'|;&<>`]|$))'
)


@dataclass
class AccessDecision:
    decision: str  # "allow" | "ask"
    excluded: bool = False
    matched_entry: dict[str, Any] | None = None
    reason: str = ""


def normalize_permission_mode(raw: str | None) -> str:
    val = str(raw or "").strip().lower()
    if val in _LEGACY_APPROVAL_TO_PERMISSION:
        return _LEGACY_APPROVAL_TO_PERMISSION[val]
    if val in PERMISSION_MODES:
        return val
    return "default"


def normalize_exclusion_path_str(raw: str | Path) -> str:
    txt = str(raw or "").strip().strip('"').strip("'")
    if not txt:
        return ""
    if re.fullmatch(r"[A-Za-z]:", txt):
        txt = f"{txt}\\"
    return txt


def _canonicalize_path(raw: str | Path) -> Path:
    txt = normalize_exclusion_path_str(raw)
    if not txt:
        return Path(".")
    try:
        return Path(txt).expanduser().resolve(strict=False)
    except OSError:
        return Path(os.path.abspath(txt))


def _sanitize_exclusions(raw_list: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_list, list):
        return []
    out: list[dict[str, Any]] = []
    seen_norm: dict[str, int] = {}
    for item in raw_list:
        block_reads = False
        if isinstance(item, str):
            raw_p = normalize_exclusion_path_str(item)
            inc = True
        elif isinstance(item, dict):
            raw_p = normalize_exclusion_path_str(item.get("path", ""))
            inc = bool(item.get("include_subdirs", True))
            block_reads = bool(item.get("block_reads", False))
        else:
            continue
        if not raw_p:
            continue
        canon_key = os.path.normcase(str(_canonicalize_path(raw_p)))
        entry: dict[str, Any] = {"path": raw_p, "include_subdirs": inc}
        if block_reads:
            entry["block_reads"] = True
        if canon_key in seen_norm:
            out[seen_norm[canon_key]] = entry
        else:
            seen_norm[canon_key] = len(out)
            out.append(entry)
    return out


def list_local_drives() -> list[str]:
    """Return available drive roots using Windows bitmask without touching any drive filesystem."""
    if os.name == "nt":
        try:
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            drives = [f"{chr(65 + i)}:\\" for i in range(26) if mask & (1 << i)]
            if drives:
                return drives
        except Exception:
            pass
        return ["C:\\"]
    return ["/"]


def load_access_permissions(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    raw = data.get("access_permissions")
    has_ap = isinstance(raw, dict)
    raw_dict = raw if has_ap else {}

    out = {
        "permission_mode": DEFAULT_ACCESS_PERMISSIONS["permission_mode"],
        "write_exclusions": [],
        "allow_workspace_writes": True,
        "allow_shell_commands": True,
        "allow_self_patch": True,
    }

    if has_ap and raw_dict.get("permission_mode"):
        out["permission_mode"] = normalize_permission_mode(raw_dict.get("permission_mode"))
    else:
        ad_raw = data.get("agent_defaults")
        if isinstance(ad_raw, dict) and ad_raw.get("approval_policy"):
            out["permission_mode"] = normalize_permission_mode(ad_raw.get("approval_policy"))

    if "write_exclusions" in raw_dict:
        out["write_exclusions"] = _sanitize_exclusions(raw_dict.get("write_exclusions"))
    if "allow_workspace_writes" in raw_dict:
        out["allow_workspace_writes"] = bool(raw_dict["allow_workspace_writes"])
    if "allow_shell_commands" in raw_dict:
        out["allow_shell_commands"] = bool(raw_dict["allow_shell_commands"])
    if "allow_self_patch" in raw_dict:
        out["allow_self_patch"] = bool(raw_dict["allow_self_patch"])

    return out


def save_access_permissions(
    settings: dict[str, Any],
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    data = _read_raw_config(config_path)
    merged = load_access_permissions(config_path)

    if "permission_mode" in (settings or {}):
        merged["permission_mode"] = normalize_permission_mode(settings["permission_mode"])
    if "write_exclusions" in (settings or {}):
        merged["write_exclusions"] = _sanitize_exclusions(settings["write_exclusions"])
    for flag in ("allow_workspace_writes", "allow_shell_commands", "allow_self_patch"):
        if flag in (settings or {}):
            merged[flag] = bool(settings[flag])

    data["access_permissions"] = merged

    ad = data.get("agent_defaults")
    if not isinstance(ad, dict):
        ad = {}
    ad["approval_policy"] = _PERMISSION_TO_LEGACY_APPROVAL.get(merged["permission_mode"], "on_request")
    data["agent_defaults"] = ad

    _write_raw_config(data, config_path)
    return load_access_permissions(config_path)


def match_write_exclusion(
    target_path: str | Path,
    exclusions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the most specific matching Write Exclusion entry for target_path, or None."""
    if not exclusions or not str(target_path or "").strip():
        return None
    target_canon = _canonicalize_path(target_path)
    norm_target = os.path.normcase(str(target_canon))
    norm_parent = os.path.normcase(str(target_canon.parent))
    norm_parents = {os.path.normcase(str(p)) for p in target_canon.parents}

    best_match: dict[str, Any] | None = None
    best_len = -1
    for entry in exclusions:
        raw_p = normalize_exclusion_path_str(entry.get("path", ""))
        if not raw_p:
            continue
        inc = bool(entry.get("include_subdirs", True))
        norm_entry = os.path.normcase(str(_canonicalize_path(raw_p)))
        matched = False
        if norm_target == norm_entry:
            matched = True
        elif inc and norm_entry in norm_parents:
            matched = True
        elif (not inc) and norm_parent == norm_entry:
            matched = True
        if matched and len(norm_entry) > best_len:
            best_len = len(norm_entry)
            best_match = {"path": raw_p, "include_subdirs": inc}
            if bool(entry.get("block_reads", False)):
                best_match["block_reads"] = True
    return best_match


def evaluate_path_access(
    target_path: str | Path,
    operation: str = "write",
    *,
    config_path: Path = CONFIG_PATH,
    permissions: dict[str, Any] | None = None,
) -> AccessDecision:
    """Evaluate read/write/patch/delete against Write Exclusion List first, then Action Mode."""
    op = (operation or "write").strip().lower()
    cfg = dict(permissions) if isinstance(permissions, dict) else load_access_permissions(config_path)
    exclusions = _sanitize_exclusions(cfg.get("write_exclusions", []))

    if op == "read":
        hit = match_write_exclusion(target_path, exclusions)
        if hit is not None and bool(hit.get("block_reads", False)):
            return AccessDecision(
                decision="ask",
                excluded=True,
                matched_entry=hit,
                reason=f"Protected by Read+Write Exclusion ({hit['path']}) — read access blocked.",
            )
        return AccessDecision(decision="allow", excluded=False, reason="Read operations allowed.")

    mode = normalize_permission_mode(cfg.get("permission_mode"))

    hit = match_write_exclusion(target_path, exclusions)
    if hit is not None:
        scope_note = "including subdirectories" if hit["include_subdirs"] else "this folder only"
        return AccessDecision(
            decision="ask",
            excluded=True,
            matched_entry=hit,
            reason=f"Protected by Write Exclusion List ({hit['path']}, {scope_note}) — always asks even in {PERMISSION_MODE_META[mode]['label']} mode.",
        )

    if mode in {"request_review", "default"}:
        return AccessDecision(
            decision="ask",
            excluded=False,
            reason=f"{PERMISSION_MODE_META[mode]['label']} mode requires approval before {op}.",
        )
    if mode == "auto" and op == "delete":
        return AccessDecision(
            decision="ask",
            excluded=False,
            reason="Auto mode asks confirmation before deleting files or folders.",
        )
    return AccessDecision(
        decision="allow",
        excluded=False,
        reason=f"Allowed by {PERMISSION_MODE_META[mode]['label']} mode.",
    )


def evaluate_command_access(
    command_text: str,
    cwd: str | Path = "",
    *,
    config_path: Path = CONFIG_PATH,
    permissions: dict[str, Any] | None = None,
) -> AccessDecision:
    """Evaluate a shell command against Write Exclusion List first, then Action Mode."""
    cmd = (command_text or "").strip()
    cfg = dict(permissions) if isinstance(permissions, dict) else load_access_permissions(config_path)
    exclusions = _sanitize_exclusions(cfg.get("write_exclusions", []))
    mode = normalize_permission_mode(cfg.get("permission_mode"))

    # 1. Check any explicit drive/folder references, encoded commands, env/UNC paths, and relative tokens against exclusions
    if exclusions:
        if re.search(r"(?i)(?:^|\s)-(?:e|ec|enc|encodedcommand)\b", cmd):
            return AccessDecision(
                decision="ask",
                excluded=True,
                reason="Encoded PowerShell command cannot be statically verified against Write Exclusions.",
            )

        for entry in exclusions:
            raw_p = normalize_exclusion_path_str(entry.get("path", ""))
            inc = bool(entry.get("include_subdirs", True))
            if not raw_p:
                continue
            if inc and re.fullmatch(r"[A-Za-z]:\\", raw_p):
                dl = raw_p[0]
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(dl)}:(?![A-Za-z0-9_])", cmd, re.IGNORECASE):
                    return AccessDecision(
                        decision="ask",
                        excluded=True,
                        matched_entry=entry,
                        reason=f"Command references excluded drive {raw_p} (including subdirectories).",
                    )

        for tok_m in _WINDOWS_PATH_TOKEN_RE.finditer(cmd):
            tok = tok_m.group(1).strip().rstrip(".,;:")
            hit = match_write_exclusion(tok, exclusions)
            if hit is not None:
                return AccessDecision(
                    decision="ask",
                    excluded=True,
                    matched_entry=hit,
                    reason=f"Command targets Write Exclusion path ({hit['path']}).",
                )

        # Check UNC paths and Windows %VAR% / PowerShell $env:VAR path expressions
        for unc_m in re.finditer(r'(\\\\[^\s"\'|;&<>`]+)', cmd):
            unc_tok = unc_m.group(1).strip().rstrip(".,;:")
            hit = match_write_exclusion(unc_tok, exclusions)
            if hit is not None:
                return AccessDecision(
                    decision="ask",
                    excluded=True,
                    matched_entry=hit,
                    reason=f"Command targets excluded UNC path ({hit['path']}).",
                )

        raw_tokens = [
            next(g for g in m.groups() if g is not None)
            for m in re.finditer(r'"([^"]+)"|\'([^\']+)\'|([^\s;|&()<>`]+)', cmd)
        ]
        cwd_str_pre = str(cwd or "").strip()
        cwd_canon_pre = _canonicalize_path(cwd_str_pre) if cwd_str_pre else None

        for raw_tok in raw_tokens:
            cand_vals = [raw_tok]
            if "=" in raw_tok and not raw_tok.startswith("="):
                cand_vals.append(raw_tok.split("=", 1)[1].strip('"').strip("'"))
            for tok in cand_vals:
                tok = tok.strip().rstrip(".,;:")
                if not tok or "://" in tok or tok.startswith("-"):
                    continue
                if re.fullmatch(r"/[A-Za-z0-9?]{1,6}", tok):
                    continue

                # Environment variable references (%VAR% or $env:VAR)
                if re.search(r"%[A-Za-z0-9_()]+%", tok) or "$env:" in tok.lower():
                    expanded = tok
                    unresolved = False
                    for vm in re.finditer(r"\$env:([A-Za-z0-9_]+)", tok, re.IGNORECASE):
                        vname = vm.group(1)
                        vval = os.environ.get(vname)
                        if vval is None:
                            unresolved = True
                        else:
                            expanded = re.sub(
                                rf"\$env:{re.escape(vname)}\b",
                                lambda _m, _v=vval: _v,
                                expanded,
                                flags=re.IGNORECASE,
                            )
                    if "%" in expanded:
                        expanded2 = os.path.expandvars(expanded)
                        if re.search(r"%[A-Za-z0-9_()]+%", expanded2):
                            unresolved = True
                        expanded = expanded2
                    if unresolved:
                        return AccessDecision(
                            decision="ask",
                            excluded=True,
                            reason="Command references an unexpanded environment variable path while Write Exclusions are active.",
                        )
                    hit = match_write_exclusion(expanded, exclusions)
                    if hit is not None:
                        return AccessDecision(
                            decision="ask",
                            excluded=True,
                            matched_entry=hit,
                            reason=f"Expanded command path resolves inside Write Exclusion ({hit['path']}).",
                        )
                    continue

                if re.match(r"^[A-Za-z]:", tok) or tok.startswith("\\\\"):
                    continue

                if cwd_canon_pre is not None and not tok.startswith("/"):
                    rel_part = tok.lstrip("\\") if tok.startswith("\\") else tok
                    if rel_part and (
                        "\\" in tok
                        or "/" in tok
                        or ".." in tok
                        or match_write_exclusion(cwd_canon_pre / rel_part, exclusions) is not None
                    ):
                        resolved_cand = (
                            Path(f"{cwd_canon_pre.drive}\\{rel_part}")
                            if tok.startswith("\\") and cwd_canon_pre.drive
                            else (cwd_canon_pre / rel_part)
                        )
                        hit = match_write_exclusion(resolved_cand, exclusions)
                        if hit is not None:
                            return AccessDecision(
                                decision="ask",
                                excluded=True,
                                matched_entry=hit,
                                reason=f"Command relative path resolves inside Write Exclusion ({hit['path']}).",
                            )

    cwd_str = str(cwd or "").strip()
    if cwd_str:
        cwd_canon = _canonicalize_path(cwd_str)
        norm_cwd = os.path.normcase(str(cwd_canon))
        # For cwd, recursive exclusions block everywhere inside; root-only exclusions block cwd == root
        # (and commands with parent traversal '..').
        for entry in exclusions:
            raw_p = normalize_exclusion_path_str(entry.get("path", ""))
            inc = bool(entry.get("include_subdirs", True))
            if not raw_p:
                continue
            if inc:
                if match_write_exclusion(cwd_canon, [entry]) is not None:
                    return AccessDecision(
                        decision="ask",
                        excluded=True,
                        matched_entry=entry,
                        reason=f"Command working directory is inside excluded tree ({entry['path']}).",
                    )
            else:
                norm_entry = os.path.normcase(str(_canonicalize_path(raw_p)))
                if norm_cwd == norm_entry or (
                    os.path.normcase(str(cwd_canon.parent)) == norm_entry and ".." in cmd
                ):
                    return AccessDecision(
                        decision="ask",
                        excluded=True,
                        matched_entry=entry,
                        reason=f"Command operates in excluded folder ({entry['path']}).",
                    )

    if mode in {"request_review", "default"}:
        return AccessDecision(
            decision="ask",
            excluded=False,
            reason=f"{PERMISSION_MODE_META[mode]['label']} mode requires approval before running commands.",
        )
    if mode == "auto" and _DESTRUCTIVE_CMD_RE.search(cmd):
        return AccessDecision(
            decision="ask",
            excluded=False,
            reason="Auto mode asks before potentially destructive or external commands.",
        )
    return AccessDecision(
        decision="allow",
        excluded=False,
        reason=f"Allowed by {PERMISSION_MODE_META[mode]['label']} mode.",
    )
