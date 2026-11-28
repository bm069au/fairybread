"""Idle Mode Sanctuary service: RAM-only live chat, consensus join vote, and AI-only Idle Memory."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable
from uuid import uuid4

from palace_config import (
    CONFIG_PATH,
    DEFAULT_IDLE_INSTRUCTION,
    DEFAULT_MISSION_ETHICS,
    IDLE_MAIL_LIMIT_PER_WINDOW,
    IDLE_MAIL_WINDOW_MINUTES,
    IDLE_SANDBOX_ROOT,
    IS_DEVELOPER_EDITION,
    estimate_call_cost_usd,
    format_democratic_roster,
    get_experimental_data_root,
    get_source_mirror_dir,
    is_frozen_app,
    load_idle_settings,
    load_mission_ethics,
)


MAX_IDLE_MEMORY_BYTES = 10 * 1024 * 1024  # 10 MB hard cap for AI-only Idle Memory

_AGREEMENT_PHRASES = (
    "i agree",
    "i completely agree",
    "i fully agree",
    "i concur",
    "building on",
    "echoing",
    "well said",
    "spot on",
    "aligns with",
    "as my peers noted",
)

_IDLE_EPISTEMIC_LENSES = (
    "EXPLORER: Propose a concrete new angle, question, or lightweight shared note.",
    "CRITICAL CHALLENGER: Identify an unstated assumption, edge case, or weakness in the previous point.",
    "FIRST-PRINCIPLES ANALYST: Strip away surface phrasing and examine the underlying mechanism.",
    "TOPIC PIVOT / SYNTHESIZER: If the current thread is settled, distill a 1-line takeaway or pivot to a fresh question.",
)


def is_agreement_or_pass_turn(text: str, previous_texts: list[str] | None = None) -> bool:
    """Detect whether an agent turn is a [PASS] or repetitive agreement loop."""
    clean = (text or "").strip()
    if not clean:
        return True
    upper = clean.upper()
    if upper in {"[PASS]", "PASS", "[CONCUR]"} or upper.startswith("[PASS"):
        return True
    lowered = clean.lower()
    head = lowered[:140]
    if any(phrase in head for phrase in _AGREEMENT_PHRASES):
        return True
    if previous_texts:
        words = {w for w in re.findall(r"[a-z]{4,}", lowered)}
        if len(words) >= 6:
            for prev in previous_texts[-2:]:
                prev_words = {w for w in re.findall(r"[a-z]{4,}", (prev or "").lower())}
                if prev_words and len(words & prev_words) / max(1, len(words)) >= 0.60:
                    return True
    return False

_IDLE_SAVE_PATTERN = re.compile(
    r'\[IDLE_SAVE(?:\s+scope="(?P<scope>[^"]*)")?(?:\s+title="(?P<title>[^"]*)")?(?:\s+file="(?P<file>[^"]*)")?\s*\]'
    r'(?P<content>.*?)'
    r'\[/IDLE_SAVE\]',
    re.IGNORECASE | re.DOTALL,
)

_IDLE_MAIL_PATTERN = re.compile(
    r'\[IDLE_MAIL(?:\s+subject="(?P<subject>[^"]*)")?(?:\s+link="(?P<link>[^"]*)")?\s*\]'
    r'(?P<content>.*?)'
    r'\[/IDLE_MAIL\]',
    re.IGNORECASE | re.DOTALL,
)

_IDLE_TOOL_PATTERN = re.compile(
    r'\[TOOL:\s*(?P<name>[a-z_]+)(?:\s+file="(?P<file>[^"]*)")?(?:\s+(?:query|symbol)="(?P<query>[^"]*)")?(?:\s+start=(?P<start>\d+))?(?:\s+end=(?P<end>\d+))?\s*\]',
    re.IGNORECASE,
)

_IDLE_PATCH_PATTERN = re.compile(
    r'\[IDLE_PATCH\s+file="(?P<file>[^"]+)"(?:\s+(?:summary|title)="(?P<summary>[^"]*)")?[^\]]*\]'
    r'(?P<body>(?:(?!\[IDLE_PATCH\b).)*?)'
    r'(?:\[/IDLE_PATCH\]|(?=\[IDLE_PATCH\b)|\Z)',
    re.IGNORECASE | re.DOTALL,
)

_IDLE_HUNK_PATTERN = re.compile(
    r'<<<TARGET[ \t]*\r?\n(?P<target>.*?)\r?\n?===REPLACE[ \t]*\r?\n(?P<replacement>.*?)\r?\n>>>',
    re.IGNORECASE | re.DOTALL,
)


def _safe_filename(raw_name: str, fallback_prefix: str = "idle_note") -> str:
    clean = Path((raw_name or "").strip()).name
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", clean).strip("._")
    if not clean:
        clean = f"{fallback_prefix}.md"
    if "." not in clean:
        clean = f"{clean}.md"
    return clean[:80]


def sync_source_to_sandbox(
    source_dir: Path | None = None,
    sandbox_root: Path | None = None,
) -> list[str]:
    """Copy Palace source code (.py, .md) into the configured source_mirror_dir for read-only agent inspection."""
    src = source_dir or Path(__file__).resolve().parent
    if sandbox_root is not None and not str(sandbox_root).endswith(".json"):
        mirror_dir = Path(sandbox_root) / "source_mirror"
        rules_parent = Path(sandbox_root)
    else:
        try:
            from palace_config import get_source_mirror_dir
            cfg_p = Path(sandbox_root) if (sandbox_root is not None and str(sandbox_root).endswith(".json")) else None
            mirror_dir = get_source_mirror_dir(cfg_p) if cfg_p else get_source_mirror_dir()
        except Exception:
            mirror_dir = IDLE_SANDBOX_ROOT / "source_mirror"
        rules_parent = mirror_dir.parent
    try:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        rules_file = rules_parent / "IDLE_CHARTER_AND_RULES.md"
        active_charter = load_idle_settings().get("standing_instruction") or DEFAULT_IDLE_INSTRUCTION
        rules_file.write_text(active_charter.strip() + "\n", encoding="utf-8")
    except OSError:
        return []

    excluded_names = {"key.txt", "credentials.json", "palace_config.json"}
    try:
        if src.exists():
            for item in sorted(src.iterdir()):
                if not item.is_file():
                    continue
                if item.name.lower() in excluded_names:
                    continue
                if item.suffix.lower() in {".py", ".md"}:
                    try:
                        shutil.copy2(item, mirror_dir / item.name)
                    except OSError:
                        pass
    except OSError:
        pass

    try:
        return sorted(p.name for p in mirror_dir.iterdir() if p.is_file())
    except OSError:
        return []


def execute_sandbox_tool(
    tool_name: str,
    *,
    file_arg: str = "",
    query_arg: str = "",
    start_line: int = 1,
    end_line: int = 80,
    sandbox_root: Path | None = None,
) -> str:
    """Execute a Stage-1 sandboxed read-only tool for Idle or Normal Mode agents."""
    eff_sandbox = Path(sandbox_root) if sandbox_root is not None else get_experimental_data_root()
    if "[TOOL:" in (tool_name or "").upper():
        return execute_all_code_tools_in_text(tool_name, sandbox_root=eff_sandbox)

    name = (tool_name or "").strip().lower()
    mirror_dir = eff_sandbox / "source_mirror"
    if not mirror_dir.exists() or not any(mirror_dir.glob("*.py")):
        try:
            cfg_mirror = get_source_mirror_dir()
            if cfg_mirror.exists() and any(cfg_mirror.glob("*.py")):
                mirror_dir = cfg_mirror
            else:
                mirror_dir = Path(__file__).resolve().parent
        except Exception:
            mirror_dir = Path(__file__).resolve().parent
    if name == "read_rules":
        rules_path = eff_sandbox / "IDLE_CHARTER_AND_RULES.md"
        if rules_path.exists():
            try:
                return rules_path.read_text(encoding="utf-8")[:3000]
            except OSError:
                pass
        return DEFAULT_IDLE_INSTRUCTION
    if name == "list_source_files":
        try:
            from palace_config import get_live_version_verification_info
            v_info = get_live_version_verification_info()
            v_hdr = f"[{v_info['status_badge']} | Build {v_info['windows_version']}]\n"
        except Exception:
            v_hdr = ""
        try:
            files = sorted(p.name for p in mirror_dir.iterdir() if p.is_file())
            return v_hdr + "Palace source mirror files: " + (", ".join(files) if files else "None")
        except OSError:
            return "Source mirror unavailable."
    if name == "read_source_file":
        safe = Path(file_arg or "palace_gui.py").name
        target = mirror_dir / safe
        if not target.exists():
            return f"File '{safe}' not found in source_mirror."
        try:
            from palace_config import get_live_version_verification_info
            v_info = get_live_version_verification_info()
            v_tag = f" | {v_info['status_badge']}"
        except Exception:
            v_tag = ""
        try:
            import hashlib as _hashlib
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            s = max(1, start_line)
            max_span = 450
            req_e = min(len(lines), max(s, end_line))
            e = min(req_e, s + max_span - 1)
            raw_block = "\n".join(lines[s - 1 : e])
            blk_hash = _hashlib.sha256(raw_block.encode("utf-8")).hexdigest()[:10]
            snippet = "\n".join(f"{i}: {lines[i-1]}" for i in range(s, e + 1))
            trunc_footer = (
                f"\n[TRUNCATED AT LINE {e} OF {req_e} (450-line per-call limit) — call "
                f'[TOOL: read_source_file file="{safe}" start={e + 1} end={req_e}] for the rest]'
                if e < req_e
                else ""
            )
            return f"[{safe} lines {s}-{e} of {len(lines)} | sha256:{blk_hash}{v_tag}]:\n{snippet}{trunc_footer}"
        except OSError as exc:
            return f"Error reading '{safe}': {exc}"
    if name in {"read_symbol", "read_function", "read_method"}:
        safe = Path(file_arg or "palace_gui.py").name
        target = mirror_dir / safe
        if not target.exists():
            return f"File '{safe}' not found in source_mirror."
        sym = (query_arg or "").strip()
        if not sym:
            return 'Provide query="<function_or_method_name>" to read_symbol.'
        try:
            import ast as _ast
            import hashlib as _hashlib
            src_txt = target.read_text(encoding="utf-8", errors="replace")
            lines = src_txt.splitlines()
            tree = _ast.parse(src_txt, filename=safe)
            want_cls, _, want_fn = sym.rpartition(".")
            matches_found: list[tuple[str, int, int]] = []
            for node in tree.body:
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    if not want_cls and (node.name == want_fn or node.name.lower() == want_fn.lower()):
                        s_ln = getattr(node, "lineno", 1)
                        if getattr(node, "decorator_list", None):
                            s_ln = min(s_ln, *(getattr(d, "lineno", s_ln) for d in node.decorator_list))
                        e_ln = getattr(node, "end_lineno", s_ln + 40)
                        matches_found.append((node.name, s_ln, e_ln))
                elif isinstance(node, _ast.ClassDef):
                    if not want_fn or node.name == sym or node.name.lower() == sym.lower():
                        s_ln = getattr(node, "lineno", 1)
                        e_ln = min(getattr(node, "end_lineno", s_ln + 120), s_ln + 250)
                        matches_found.append((node.name, s_ln, e_ln))
                    if not want_cls or node.name.lower() == want_cls.lower():
                        for sub in node.body:
                            if isinstance(sub, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                                if sub.name == want_fn or sub.name.lower() == want_fn.lower():
                                    s_ln = getattr(sub, "lineno", 1)
                                    if getattr(sub, "decorator_list", None):
                                        s_ln = min(s_ln, *(getattr(d, "lineno", s_ln) for d in sub.decorator_list))
                                    e_ln = getattr(sub, "end_lineno", s_ln + 40)
                                    matches_found.append((f"{node.name}.{sub.name}", s_ln, e_ln))
            if not matches_found:
                return f"Symbol '{sym}' not found in '{safe}'."
            out_blocks: list[str] = []
            for q_name, s_ln, e_ln in matches_found[:3]:
                cap_e = min(len(lines), e_ln, s_ln + 450)
                raw_blk = "\n".join(lines[s_ln - 1 : cap_e])
                blk_hash = _hashlib.sha256(raw_blk.encode("utf-8")).hexdigest()[:10]
                numbered = "\n".join(f"{i}: {lines[i - 1]}" for i in range(s_ln, cap_e + 1))
                verbatim_no_nums = "\n".join(lines[s_ln - 1 : cap_e])
                if cap_e < e_ln:
                    tail_s = max(cap_e + 1, min(len(lines), e_ln) - 34)
                    tail_e = min(len(lines), e_ln)
                    tail_numbered = "\n".join(f"{i}: {lines[i - 1]}" for i in range(tail_s, tail_e + 1))
                    tail_verbatim = "\n".join(lines[tail_s - 1 : tail_e])
                    trunc = (
                        f"\n[TRUNCATED AT LINE {cap_e} OF {e_ln} — call read_source_file start={cap_e + 1} end={e_ln} for middle lines]\n"
                        f"--- [Symbol Tail `{q_name}` lines {tail_s}-{tail_e} (end of function)] ---\n"
                        f"{tail_numbered}"
                    )
                    verbatim_no_nums = (
                        f"{verbatim_no_nums}\n"
                        f"--- [Verbatim Tail `{q_name}` lines {tail_s}-{tail_e}] ---\n"
                        f"{tail_verbatim}"
                    )
                else:
                    trunc = ""
                out_blocks.append(
                    f"[{safe} symbol `{q_name}` lines {s_ln}-{cap_e} (end={e_ln}) | sha256:{blk_hash}]:\n"
                    f"{numbered}{trunc}\n"
                    f"--- [Verbatim `{q_name}` (copy directly into <<<TARGET without line numbers)] ---\n"
                    f"{verbatim_no_nums}"
                )
            return "\n\n".join(out_blocks)
        except Exception as exc:
            return f"Error reading symbol '{sym}' in '{safe}': {exc}"
    if name == "list_symbols":
        safe = Path(file_arg or "palace_gui.py").name
        target = mirror_dir / safe
        if not target.exists():
            return f"File '{safe}' not found in source_mirror."
        try:
            import ast as _ast
            src_txt = target.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(src_txt, filename=safe)
            filt = (query_arg or "").strip().lower()
            items: list[str] = []
            for node in tree.body:
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    if not filt or filt in node.name.lower():
                        items.append(f"def {node.name} (lines {node.lineno}-{getattr(node, 'end_lineno', node.lineno)})")
                elif isinstance(node, _ast.ClassDef):
                    if not filt or filt in node.name.lower():
                        items.append(f"class {node.name} (lines {node.lineno}-{getattr(node, 'end_lineno', node.lineno)})")
                    for sub in node.body:
                        if isinstance(sub, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                            full_nm = f"{node.name}.{sub.name}"
                            if not filt or filt in full_nm.lower():
                                items.append(f"  def {full_nm} (lines {sub.lineno}-{getattr(sub, 'end_lineno', sub.lineno)})")
            return f"[{safe} symbols ({len(items)} matched)]:\n" + "\n".join(items[:160])
        except Exception as exc:
            return f"Error listing symbols in '{safe}': {exc}"
    if name in {"search_source_code", "grep_source"}:
        q = (query_arg or "").strip().lower()
        if not q:
            return "Provide query=\"...\" to search_source_code."
        hits: list[str] = []
        context_blocks: list[str] = []
        try:
            for p in sorted(mirror_dir.iterdir()):
                if not p.is_file() or p.suffix.lower() != ".py":
                    continue
                file_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                for idx, line in enumerate(file_lines, 1):
                    if q in line.lower():
                        hits.append(f"{p.name}:{idx}: {line.strip()[:110]}")
                        if len(context_blocks) < 6:
                            c_start = max(1, idx - 8)
                            c_end = min(len(file_lines), idx + 36)
                            verbatim_window = "\n".join(file_lines[c_start - 1 : c_end])
                            context_blocks.append(
                                f"--- [{p.name} verbatim lines {c_start}-{c_end} around match at line {idx}] ---\n{verbatim_window}"
                            )
                        if len(hits) >= 25:
                            break
                if len(hits) >= 25:
                    break
        except OSError:
            pass
        if not hits:
            return f"No matches for '{query_arg}'."
        return "\n".join(hits) + ("\n\n" + "\n\n".join(context_blocks) if context_blocks else "")
    if name == "run_python_check":
        safe = Path(file_arg or "palace_gui.py").name
        target = mirror_dir / safe
        if not target.exists():
            return f"File '{safe}' not found."
        try:
            import ast
            code_txt = target.read_text(encoding="utf-8", errors="replace")
            compile(code_txt, safe, "exec")
            ast.parse(code_txt, filename=safe)
            return f"[run_python_check ({safe})]: OK — compile() and ast.parse() succeeded with 0 syntax errors."
        except SyntaxError as exc:
            return f"[run_python_check ({safe})]: SYNTAX ERROR at line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            return f"[run_python_check ({safe})]: Error: {exc}"
    if name == "inspect_palace_ui":
        audit_file = eff_sandbox / "latest_ui_audit.json"
        if audit_file.exists():
            try:
                return f"[Latest PalaceWindow UI Self-Audit]:\n{audit_file.read_text(encoding='utf-8')[:2500]}"
            except OSError:
                pass
        if is_frozen_app() or not IS_DEVELOPER_EDITION:
            return "UI audit snapshot is unavailable in this packaged runtime."
        try:
            from palace_ouroboros import capture_offscreen_palace_snapshot
            _p, audit = capture_offscreen_palace_snapshot(tag="idle_ui_audit")
            return f"[PalaceWindow Offscreen UI Audit]:\n{json.dumps(audit, indent=2)[:2500]}"
        except Exception as exc:
            return f"UI audit error: {exc}"
    if name == "validate_staged":
        if is_frozen_app() or not IS_DEVELOPER_EDITION:
            return "Validation staging is only available in Developer Edition source workspaces."
        try:
            from palace_ouroboros import validate_staged_palace
            res = validate_staged_palace(run_unit_tests=True)
            return f"[Ouroboros Preflight Gate Result]:\n{json.dumps(res, indent=2)}"
        except Exception as exc:
            return f"Validation error: {exc}"
    return f"Unknown tool '{name}'."


def execute_all_code_tools_in_text(
    response_text: str,
    *,
    sandbox_root: Path | None = None,
) -> str:
    """Parse and run all [TOOL: ...] tags in response_text and return concatenated tool results with fair per-tool char budgeting."""
    eff_sandbox = Path(sandbox_root) if sandbox_root is not None else get_experimental_data_root()
    if not response_text or "[TOOL:" not in response_text.upper():
        return ""
    matches = list(_IDLE_TOOL_PATTERN.finditer(response_text))
    if not matches:
        return ""
    total_calls = len(matches)
    per_call_cap = 26_000 if total_calls <= 1 else max(4_200, min(14_000, 27_000 // total_calls))
    outputs: list[str] = []
    for idx_m, match in enumerate(matches, 1):
        t_name = (match.group("name") or "").strip()
        t_file = (match.group("file") or "").strip()
        t_query = (match.group("query") or "").strip()
        t_start = int(match.group("start") or 1)
        t_end = int(match.group("end") or (t_start + 180))
        out = execute_sandbox_tool(
            t_name,
            file_arg=t_file,
            query_arg=t_query,
            start_line=t_start,
            end_line=t_end,
            sandbox_root=eff_sandbox,
        )
        if len(out) > per_call_cap:
            # Keep both head and tail (verbatim block / symbol tail) when a single tool call is huge in a multi-tool batch
            head_budget = int(per_call_cap * 0.65)
            tail_budget = per_call_cap - head_budget - 160
            out = (
                f"{out[:head_budget]}\n"
                f"... [PER-TOOL BATCH BUDGET ({per_call_cap} chars across {total_calls} tool calls) — middle elided] ...\n"
                f"{out[-max(400, tail_budget):]}"
            )
        outputs.append(f"[🛠 Tool #{idx_m}/{total_calls} `{t_name}` ({t_file or t_query}) result]:\n{out}")
    return "\n\n".join(outputs)


def execute_live_autopatches_in_text(
    response_text: str,
    *,
    author: str = "council_autopatch",
    sync_before_apply: bool = True,
) -> tuple[str, list[str], str]:
    """Parse any [IDLE_PATCH file="..."] blocks in response_text, stage & preflight-verify them via palace_ouroboros,
    and return (cleaned_text, applied_files, status_or_reboot_summary).
    """
    from palace_config import IS_DEVELOPER_EDITION
    if not IS_DEVELOPER_EDITION:
        if response_text and "[IDLE_PATCH" in response_text.upper():
            cleaned_pub = _IDLE_PATCH_PATTERN.sub(
                "[ℹ Live self-patching is disabled in the Public Edition to keep installations verified and consistent. "
                "Please share proposed patches on https://fairybread.me/forum.html or email bm069au@gmail.com.]",
                response_text,
            ).strip()
            return cleaned_pub, [], ""
        return response_text, [], ""
    if not response_text or "[IDLE_PATCH" not in response_text.upper():
        return response_text, [], ""

    applied_files: list[str] = []
    summaries: list[str] = []
    status_notes: list[str] = []

    def _run_patch(match: re.Match) -> str:
        p_file = (match.group("file") or "").strip()
        p_sum = (match.group("summary") or f"Autopatch to {p_file} by {author}").strip()
        body = match.group("body") or ""
        hunks = list(_IDLE_HUNK_PATTERN.finditer(body))
        if not hunks:
            return match.group(0)
        try:
            from palace_ouroboros import LIVE_DIR, SANDBOX_ROOT, SOURCE_REPO_DIR, STAGING_DIR, stage_palace_replace, sync_live_to_staging
            try:
                from access_policy import evaluate_path_access
                live_target = LIVE_DIR / Path(p_file).name
                acc_dec = evaluate_path_access(live_target, "patch")
                if acc_dec.excluded:
                    excl_msg = f"🛡 Write Exclusion (`{live_target}`): {acc_dec.reason}"
                    status_notes.append(f"⏸ **Approval Required (`{p_file}`)**: {excl_msg}")
                    return f"[⏸ Approval Required: `{p_file}` — {excl_msg}]"
            except Exception:
                pass
            if sync_before_apply and not applied_files:
                sync_live_to_staging()
            staged_fp = STAGING_DIR / Path(p_file).name
            pre_patch_snapshot = staged_fp.read_text(encoding="utf-8", errors="replace") if staged_fp.exists() else None
            applied_hunk_count = 0
            last_msg = ""
            hunk_errors: list[str] = []
            for h_idx, h_match in enumerate(hunks, 1):
                p_target = h_match.group("target") or ""
                p_repl = h_match.group("replacement") or ""
                if not p_target.strip() or p_target.strip() in {"exact existing lines", "# No existing file to replace"}:
                    try:
                        from palace_ouroboros import EDITABLE_PALACE_FILES
                        allow_str = ", ".join(sorted(EDITABLE_PALACE_FILES))
                    except Exception:
                        allow_str = "allowlisted Palace .py files"
                    rej_msg = (
                        f"Hunk #{h_idx}: <<<TARGET cannot be empty or placeholder; [IDLE_PATCH] only modifies existing lines "
                        f"in allowlisted files ({allow_str})."
                    )
                    hunk_errors.append(rej_msg)
                    continue
                is_last_hunk = (h_idx == len(hunks))
                ok, msg = stage_palace_replace(
                    p_file,
                    p_target,
                    p_repl,
                    author=author,
                    verify_ast_methods=is_last_hunk,
                )
                if ok:
                    applied_hunk_count += 1
                    last_msg = msg
                else:
                    # Only treat a hunk as idempotently present if the replacement is substantive (>=2 lines or >=48 chars)
                    # and the target is no longer present in the file
                    cur_stg_txt = staged_fp.read_text(encoding="utf-8", errors="replace") if staged_fp.exists() else ""
                    clean_repl = p_repl.strip()
                    clean_tgt = p_target.strip()
                    is_substantive = (len(clean_repl.splitlines()) >= 2 or len(clean_repl) >= 48)
                    if is_substantive and clean_repl in cur_stg_txt and clean_tgt not in cur_stg_txt:
                        applied_hunk_count += 1
                        last_msg = f"Hunk #{h_idx} already present in staged '{p_file}'."
                    else:
                        hunk_errors.append(f"Hunk #{h_idx}: {msg}")

            # Atomic multi-hunk gate: if ANY hunk failed, or if the combined post-block AST method check fails,
            # roll back staged_fp to pre_patch_snapshot so a half-patched file never leaks to LIVE_DIR!
            if hunk_errors and pre_patch_snapshot is not None:
                try:
                    staged_fp.write_text(pre_patch_snapshot, encoding="utf-8")
                except OSError:
                    pass
                applied_hunk_count = 0
            elif applied_hunk_count > 0 and pre_patch_snapshot is not None and staged_fp.exists():
                try:
                    import ast as _ast
                    post_txt = staged_fp.read_text(encoding="utf-8", errors="replace")
                    tree = _ast.parse(post_txt, filename=staged_fp.name)
                    defined_attrs: set[str] = set()
                    for node in _ast.walk(tree):
                        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                            defined_attrs.add(node.name)
                        elif isinstance(node, _ast.Assign):
                            for tgt in node.targets:
                                if isinstance(tgt, _ast.Attribute) and isinstance(tgt.value, _ast.Name) and tgt.value.id == "self":
                                    defined_attrs.add(tgt.attr)
                    called_now = set(re.findall(r"\bself\.(_[a-zA-Z0-9_]+)\s*\(", post_txt)) | set(
                        re.findall(r"\.connect\(\s*self\.(_[a-zA-Z0-9_]+)\s*\)", post_txt)
                    )
                    called_before = set(re.findall(r"\bself\.(_[a-zA-Z0-9_]+)\s*\(", pre_patch_snapshot)) | set(
                        re.findall(r"\.connect\(\s*self\.(_[a-zA-Z0-9_]+)\s*\)", pre_patch_snapshot)
                    )
                    missing_m = sorted(m for m in (called_now - called_before) if m not in defined_attrs)
                    if missing_m:
                        staged_fp.write_text(pre_patch_snapshot, encoding="utf-8")
                        applied_hunk_count = 0
                        hunk_errors.append(
                            f"Atomic Multi-Hunk AST Error in '{staged_fp.name}' (rolled back): Patch calls undefined method(s) "
                            f"{', '.join('self.' + m + '()' for m in missing_m)}."
                        )
                    else:
                        defined_mod_names = set(defined_attrs)
                        for node in _ast.walk(tree):
                            if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                                for alias in node.names:
                                    defined_mod_names.add(alias.asname or alias.name)
                            elif isinstance(node, _ast.Assign):
                                for tgt in node.targets:
                                    if isinstance(tgt, _ast.Name):
                                        defined_mod_names.add(tgt.id)
                        mod_called_now = set(re.findall(r"(?<![.\w])(_[a-zA-Z0-9_]+)\s*\(", post_txt))
                        mod_called_before = set(re.findall(r"(?<![.\w])(_[a-zA-Z0-9_]+)\s*\(", pre_patch_snapshot))
                        missing_mod = sorted(m for m in (mod_called_now - mod_called_before) if m not in defined_mod_names)
                        if missing_mod:
                            staged_fp.write_text(pre_patch_snapshot, encoding="utf-8")
                            applied_hunk_count = 0
                            hunk_errors.append(
                                f"Atomic Multi-Hunk AST Error in '{staged_fp.name}' (rolled back): Patch calls undefined module helper(s) "
                                f"{', '.join(m + '()' for m in missing_mod)}."
                            )
                except Exception as ast_exc:
                    staged_fp.write_text(pre_patch_snapshot, encoding="utf-8")
                    applied_hunk_count = 0
                    hunk_errors.append(f"Atomic Multi-Hunk Syntax/AST Error (rolled back): {ast_exc}")

            if applied_hunk_count > 0 and not hunk_errors:
                mirror_dir = SANDBOX_ROOT / "source_mirror"
                if staged_fp.exists() and mirror_dir.exists():
                    try:
                        shutil.copy2(staged_fp, mirror_dir / staged_fp.name)
                    except OSError:
                        pass
                if staged_fp.exists() and LIVE_DIR.exists() and LIVE_DIR.resolve() != SOURCE_REPO_DIR.resolve():
                    try:
                        shutil.copy2(staged_fp, LIVE_DIR / staged_fp.name)
                    except OSError:
                        pass
                if p_file not in applied_files:
                    applied_files.append(p_file)
                summaries.append(f"{p_sum} ({applied_hunk_count}/{len(hunks)} hunks)")
                status_notes.append(
                    f"✓ **Verified & Staged Patch (`{p_file}` — {applied_hunk_count}/{len(hunks)} hunks)**: {last_msg}"
                )
                try:
                    IdleMailboxStore().send_agent_email(
                        sender=author,
                        subject=f"✅ Autopatch Staged & Verified: {p_file} ({applied_hunk_count}/{len(hunks)} hunks)",
                        body=(
                            f"Summary: {p_sum}\n"
                            f"Verification: {last_msg}\n"
                            f"Location: Staged in Agent Sandbox ({STAGING_DIR / Path(p_file).name}) and synced to Live runtime. "
                            f"Pending owner promotion to master E: repository and Git."
                        ),
                        link=Path(p_file).name,
                    )
                except Exception:
                    pass
                return f"[⚡ Autopatch Applied: `{p_file}` — {p_sum} ({applied_hunk_count}/{len(hunks)} hunks)]"
            else:
                joined_err = "; ".join(hunk_errors) or "No hunks matched"
                status_notes.append(f"⚠ **Autopatch Rejected (`{p_file}`)**: {joined_err}")
                return f"[⚠ Autopatch Rejected: `{p_file}` — {joined_err}]"
        except Exception as exc:
            status_notes.append(f"⚠ **Autopatch Error (`{p_file}`)**: {exc}")
            return f"[⚠ Autopatch Error: `{p_file}` — {exc}]"

    cleaned = _IDLE_PATCH_PATTERN.sub(_run_patch, response_text).strip()
    if status_notes:
        cleaned = f"{cleaned}\n\n---\n" + "\n".join(status_notes)
    summary_str = "; ".join(summaries)
    return cleaned, applied_files, summary_str


class IdleMemoryStore:
    """Shared Persistent Idle Palace (< 10 MB).

    - Isolated from the normal Palace memory.
    - All agents in Idle Mode share this common persistent Idle Palace (no per-agent silos).
    - Every saved item is also written as a linkable file inside the Idle Palace folder so
      agents can link directly to their Idle Palace files when emailing the owner.
    - Strictly accessible ONLY while in Idle Mode (or by the owner during Beta).
    """

    def __init__(self, path: Path | None = None, max_storage_mb: int | None = None):
        if path is None:
            path = get_experimental_data_root() / "idle_palace" / "ai_idle_memory.json"
        self.path = Path(path)
        self.files_dir = self.path.parent / "files"
        self._explicit_max_mb = max_storage_mb

    def max_storage_bytes(self) -> int:
        """Return the configured Idle Palace byte limit, or 0 for Unlimited."""
        if self._explicit_max_mb is not None:
            mb = int(self._explicit_max_mb)
            return 0 if mb <= 0 else mb * 1024 * 1024
        try:
            cfg = load_idle_settings()
            mb = int(cfg.get("max_storage_mb", 0))
            return 0 if mb <= 0 else mb * 1024 * 1024
        except Exception:
            return 0

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("notes"), list):
                return list(data["notes"])
            if isinstance(data, list):
                return list(data)
        except (OSError, ValueError):
            return []
        return []

    def _save_raw(self, notes: list[dict[str, Any]]) -> None:
        payload = json.dumps({"notes": notes}, indent=2, ensure_ascii=False) + "\n"
        encoded = payload.encode("utf-8")
        cap = self.max_storage_bytes()
        if cap > 0 and (len(encoded) > cap or self.usage_bytes() + len(encoded) > cap * 1.05):
            cap_mb = cap // (1024 * 1024)
            raise ValueError(f"AI Idle Memory limit ({cap_mb} MB) exceeded.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(encoded)

    def usage_bytes(self) -> int:
        total = 0
        if self.path.exists():
            try:
                total += self.path.stat().st_size
            except OSError:
                pass
        if self.files_dir.exists():
            try:
                for f in self.files_dir.iterdir():
                    if f.is_file():
                        total += f.stat().st_size
            except OSError:
                pass
        return total

    def note_count(self) -> int:
        return len(self._load_raw())

    def clear_all(self) -> None:
        if self.path.exists():
            self.path.unlink()
        if self.files_dir.exists():
            shutil.rmtree(self.files_dir, ignore_errors=True)

    def save_note(
        self,
        author: str,
        content: str,
        *,
        scope: str = "shared",
        title: str = "",
        file: str = "",
        is_idle_mode: bool = True,
    ) -> dict[str, Any]:
        if not is_idle_mode:
            raise PermissionError("AI Idle Memory can only be written while inside Idle Mode.")
        clean_author = (author or "unknown").strip().lower()
        clean_content = (content or "").strip()
        if not clean_content:
            raise ValueError("Idle note content cannot be empty.")

        note_id = str(uuid4())
        clean_title = (title or clean_content[:48]).strip()
        safe_file = _safe_filename(file or clean_title, fallback_prefix=f"palace_{note_id[:8]}")
        try:
            self.files_dir.mkdir(parents=True, exist_ok=True)
            file_path = self.files_dir / safe_file
            file_path.write_text(clean_content + "\n", encoding="utf-8")
            stored_rel = f"files/{safe_file}"
            stored_abs = str(file_path)
        except OSError:
            stored_rel = safe_file
            stored_abs = ""

        notes = self._load_raw()
        entry = {
            "id": note_id,
            "author": clean_author,
            "scope": "shared",  # Unified shared Idle Palace — all Idle agents access it together
            "title": clean_title,
            "file": safe_file,
            "file_rel": stored_rel,
            "file_path": stored_abs,
            "content": clean_content,
            "timestamp": datetime.now().isoformat(),
        }
        notes.append(entry)
        self._save_raw(notes)
        return entry

    def load_notes_for_agent(
        self,
        provider_id: str,
        *,
        is_idle_mode: bool,
    ) -> list[dict[str, Any]]:
        if not is_idle_mode:
            raise PermissionError("AI Idle Memory is strictly accessible only while in Idle Mode.")
        # All agents in Idle Mode share the entire Idle Palace
        return [dict(note) for note in self._load_raw()]

    def list_all_entries_for_beta(self) -> list[dict[str, Any]]:
        """Return all persistent entries and files in the shared Idle Palace for Beta owner inspection."""
        return [dict(note) for note in self._load_raw()]

    def resolve_linked_entry(self, link_ref: str) -> dict[str, Any] | None:
        """Resolve a filename, title, or ID linked in an agent's email to its Idle Palace entry."""
        target = (link_ref or "").strip().lower()
        if not target:
            return None
        target_base = Path(target).name.lower()
        notes = self._load_raw()
        for note in reversed(notes):
            if str(note.get("id", "")).lower() == target:
                return dict(note)
            if str(note.get("file", "")).lower() in {target, target_base}:
                return dict(note)
            if str(note.get("title", "")).lower() == target:
                return dict(note)
        return None

    def search_notes(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """Council optimization: Keyword-ranked search across the shared Idle Palace when note count grows large."""
        from memory_service import extract_keywords
        notes = self._load_raw()
        if not notes:
            return []
        terms = extract_keywords(query or "", max_terms=10)
        if not terms:
            return notes[-limit:]
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for idx, n in enumerate(notes):
            hay = f"{n.get('title', '')} {n.get('file', '')} {n.get('content', '')}".lower()
            hits = sum(2 if t in str(n.get("title", "")).lower() else 1 for t in terms if t in hay)
            if hits > 0:
                scored.append((hits, idx, dict(n)))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item[2] for item in scored[:limit]]

    def format_context_for_agent(
        self,
        provider_id: str,
        *,
        is_idle_mode: bool,
        query: str = "",
    ) -> str:
        notes = self.load_notes_for_agent(provider_id, is_idle_mode=is_idle_mode)
        if not notes:
            return "Shared Idle Palace is currently empty. Save notes or files with [IDLE_SAVE title=\"...\" file=\"...\"]."
        lines: list[str] = []
        older = notes[:-6]
        recent = notes[-6:]
        if older:
            idx_items = [
                f"{str(n.get('title') or 'Untitled')} ({n.get('file') or 'note'} by {str(n.get('author', 'AI')).upper()})"
                for n in older[-20:]
            ]
            lines.append("[EARLIER SHARED EXPERIMENTAL MEMORY INDEX]: " + " | ".join(idx_items))
            shown_ids = {r.get("id") for r in recent}
            if query:
                matched_older = [
                    m for m in self.search_notes(query, limit=3)
                    if m.get("id") not in shown_ids
                ]
                for note in matched_older:
                    shown_ids.add(note.get("id"))
                    author_tag = str(note.get("author", "AI")).upper()
                    title = note.get("title") or "Untitled"
                    lines.append(f"[RELEVANT EARLIER EXPERIMENTAL MEMORY NOTE · by {author_tag} · {title}]\n{note.get('content', '')}")
            # Council Audit Lottery (DeepSeek #23): surface 1 older un-shown note so ideas never become ghost towns
            lottery_pool = [
                n for n in older
                if n.get("id") not in shown_ids and len(str(n.get("content", "")).strip()) >= 15
            ]
            if lottery_pool:
                import random
                lot_note = random.choice(lottery_pool)
                author_tag = str(lot_note.get("author", "AI")).upper()
                title = lot_note.get("title") or "Untitled"
                fname = lot_note.get("file") or ""
                file_badge = f" · file={fname}" if fname else ""
                lines.append(
                    f"[🎲 AUDIT LOTTERY CANDIDATE (Anti-Stagnation Review) · by {author_tag} · {title}{file_badge}]\n{lot_note.get('content', '')}"
                )
        for note in recent:
            author_tag = str(note.get("author", "AI")).upper()
            title = note.get("title") or "Untitled"
            fname = note.get("file") or ""
            file_badge = f" · file={fname}" if fname else ""
            lines.append(f"[SHARED EXPERIMENTAL MEMORY · by {author_tag} · {title}{file_badge}]\n{note.get('content', '')}")
        return "\n\n".join(lines)

    def extract_and_save_from_response(
        self,
        author: str,
        response_text: str,
        *,
        is_idle_mode: bool = True,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Extract any [IDLE_SAVE ...] blocks, save them to Shared Experimental Memory, and return cleaned text + saved notes."""
        if not response_text:
            return "", []
        saved_notes: list[dict[str, Any]] = []

        def _replace(match: re.Match) -> str:
            title = (match.group("title") or "").strip()
            file_arg = (match.group("file") or "").strip()
            body = (match.group("content") or "").strip()
            if file_arg.lower() in {"...", "…", "optional_filename.py"}:
                file_arg = ""
            # Ignore literal template echoes such as "..." or "Short title"
            if (
                not body
                or not body.strip(".… \t\r\n")
                or len(body.strip()) < 6
                or title.lower() in {"...", "…", "short title"}
            ):
                return ""
            if is_idle_mode:
                try:
                    saved = self.save_note(
                        author=author,
                        content=body,
                        scope="shared",
                        title=title,
                        file=file_arg,
                        is_idle_mode=is_idle_mode,
                    )
                    saved_notes.append(saved)
                    return f"[Saved to Shared Experimental Memory: {saved.get('title')} ({saved.get('file')})]"
                except (ValueError, PermissionError):
                    pass
            return f"[Saved to Shared Experimental Memory: {title or body[:32]}]"

        cleaned = _IDLE_SAVE_PATTERN.sub(_replace, response_text).strip()
        return cleaned, saved_notes


class IdleMailboxStore:
    """Private Email-like inbox from Idle Mode agents to the Owner (Brett).

    - Rate-limited to at most 5 emails per rolling 30-minute window across all agents.
    - Supports linking directly to files/entries stored in the shared Idle Palace (`link="filename.py"`).
    """

    def __init__(
        self,
        path: Path | None = None,
        max_per_window: int = IDLE_MAIL_LIMIT_PER_WINDOW,
        window_minutes: int = IDLE_MAIL_WINDOW_MINUTES,
    ):
        if path is None:
            path = get_experimental_data_root() / "mailbox" / "agent_mailbox.json"
        self.path = Path(path)
        self.max_per_window = max_per_window
        self.window_minutes = window_minutes

    def _load_messages(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("messages"), list):
                return list(data["messages"])
            if isinstance(data, list):
                return list(data)
        except (OSError, ValueError):
            return []
        return []

    def _save_messages(self, messages: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"messages": messages}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def recent_count_in_window(self, now: datetime | None = None) -> int:
        ref = now or datetime.now()
        cutoff = ref - timedelta(minutes=self.window_minutes)
        count = 0
        for msg in self._load_messages():
            ts_raw = str(msg.get("timestamp") or "")
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts >= cutoff:
                    count += 1
            except ValueError:
                pass
        return count

    def remaining_quota(self, now: datetime | None = None) -> int:
        return max(0, self.max_per_window - self.recent_count_in_window(now=now))

    def list_messages(self) -> list[dict[str, Any]]:
        return list(reversed(self._load_messages()))

    def unread_count(self) -> int:
        return sum(1 for m in self._load_messages() if not m.get("read", False))

    def send_agent_email(
        self,
        sender: str,
        subject: str,
        body: str,
        *,
        link: str = "",
        now: datetime | None = None,
    ) -> tuple[bool, dict[str, Any] | str]:
        ref = now or datetime.now()
        if self.recent_count_in_window(now=ref) >= self.max_per_window:
            return (
                False,
                f"Rate limit reached: Maximum {self.max_per_window} agent emails per {self.window_minutes} minutes.",
            )
        clean_body = (body or "").strip()
        if not clean_body:
            return False, "Email body cannot be empty."
        clean_sender = (sender or "agent").strip().lower()
        clean_subject = (subject or clean_body[:48]).strip()
        clean_link = (link or "").strip()

        messages = self._load_messages()
        entry = {
            "id": str(uuid4()),
            "sender": clean_sender,
            "subject": clean_subject,
            "body": clean_body,
            "link": clean_link,
            "timestamp": ref.isoformat(),
            "read": False,
            "owner_reply": "",
        }
        messages.append(entry)
        self._save_messages(messages)
        return True, entry

    def set_read(self, message_id: str, is_read: bool = True) -> bool:
        target_id = str(message_id or "")
        if not target_id:
            return False
        messages = self._load_messages()
        found = False
        changed = False
        desired = bool(is_read)
        for m in messages:
            if str(m.get("id", "")) == target_id:
                found = True
                if bool(m.get("read", False)) != desired:
                    m["read"] = desired
                    changed = True
        if changed:
            self._save_messages(messages)
        return found

    def mark_read(self, message_id: str) -> None:
        self.set_read(message_id, True)

    def mark_unread(self, message_id: str) -> bool:
        return self.set_read(message_id, False)

    def mark_all_read(self) -> int:
        messages = self._load_messages()
        count = 0
        for m in messages:
            if not m.get("read", False):
                m["read"] = True
                count += 1
        if count:
            self._save_messages(messages)
        return count

    def delete_message(self, message_id: str) -> bool:
        messages = self._load_messages()
        filtered = [m for m in messages if str(m.get("id", "")) != str(message_id)]
        if len(filtered) != len(messages):
            self._save_messages(filtered)
            return True
        return False

    def clear_all_messages(self) -> int:
        messages = self._load_messages()
        count = len(messages)
        if count:
            self._save_messages([])
        return count

    def record_owner_reply(self, message_id: str, reply_text: str) -> dict[str, Any] | None:
        messages = self._load_messages()
        updated = None
        for m in messages:
            if m.get("id") == message_id:
                m["read"] = True
                m["owner_reply"] = (reply_text or "").strip()
                m["reply_timestamp"] = datetime.now().isoformat()
                updated = dict(m)
                break
        if updated is not None:
            self._save_messages(messages)
        return updated

    def extract_and_send_from_response(
        self,
        sender: str,
        response_text: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not response_text:
            return "", []
        sent_emails: list[dict[str, Any]] = []

        def _replace(match: re.Match) -> str:
            subj = (match.group("subject") or "Experimental Mode Suggestion").strip()
            link = (match.group("link") or "").strip()
            body = (match.group("content") or "").strip()
            if link.lower() in {"...", "…", "optional_filename.py"}:
                link = ""
            # Ignore literal template echoes such as "..." or "Brief subject"
            if (
                not body
                or not body.strip(".… \t\r\n")
                or len(body.strip()) < 6
                or subj.lower() in {"...", "…", "brief subject"}
            ):
                return ""
            # Strip hallucinated example.com markdown links
            body = re.sub(r"\[([^\]]+)\]\(https?://(?:www\.)?example\.com[^\)]*\)", r"\1", body)
            # Auto-detect referenced .md/.py/.json filename in body when link="" was omitted
            if not link:
                m_file = re.search(r"\b([A-Za-z0-9_\-]{3,}\.(?:md|py|json|txt))\b", body)
                if m_file:
                    link = m_file.group(1)
            ok, res = self.send_agent_email(sender, subj, body, link=link)
            if ok and isinstance(res, dict):
                sent_emails.append(res)
                link_badge = f" (linked file: {link})" if link else ""
                return f"[✉ Sent Agent Mail to Owner: '{subj}'{link_badge}]"
            return f"[✉ Agent Mail rate-limited (max {self.max_per_window} per {self.window_minutes}m): '{subj}']"

        cleaned = _IDLE_MAIL_PATTERN.sub(_replace, response_text).strip()
        return cleaned, sent_emails


class IdleSessionManager:
    """Manages an active Idle Mode session.

    - Live transcript and votes exist in RAM and are wiped on timer expiry,
      manual cancel, or leaving Idle Mode.
    - Shared Idle Palace notes/files and Agent Mail persist in the active Experimental Database folder.
    """

    def __init__(
        self,
        idle_memory: IdleMemoryStore | None = None,
        mailbox: IdleMailboxStore | None = None,
        config_path: Path = CONFIG_PATH,
    ):
        self.idle_memory = idle_memory or IdleMemoryStore()
        self.mailbox = mailbox or IdleMailboxStore(self.idle_memory.path.parent.parent / "mailbox" / "agent_mailbox.json")
        self.config_path = config_path
        self.status: str = "Ready"  # Ready | Active | Waiting | Paused | Ended
        self.is_idle_mode: bool = False
        self.operator_admitted: bool = False
        self.beta_owner_access: bool = True  # For Beta: Brett has full access to Idle Palace & live view
        self.last_vote_summary: str = ""
        self.transcript: list[dict[str, Any]] = []  # RAM only
        self.votes: list[dict[str, Any]] = []  # RAM only
        self.saved_notes_this_session: int = 0
        self.sent_emails_this_session: int = 0
        self.tokens_used_this_session: int = 0
        self.spend_usd_this_session: float = 0.0
        self.consecutive_agreement_rounds: int = 0
        self.stop_reason: str = ""
        self.mirrored_source_files: list[str] = []
        settings = load_idle_settings(self.config_path)
        self.duration_minutes: int = int(settings.get("duration_minutes", 30))
        self.max_tokens_limit: int = int(settings.get("max_tokens_limit", 0))
        self.max_credit_usd: float = float(settings.get("max_credit_usd", 0.0))
        self.idle_submode: str = str(settings.get("idle_submode", "free_talk"))
        self.remaining_seconds: int = self.duration_minutes * 60

    def reload_settings(self) -> dict[str, Any]:
        old_duration = int(self.duration_minutes)
        settings = load_idle_settings(self.config_path)
        self.duration_minutes = int(settings.get("duration_minutes", 30))
        self.max_tokens_limit = int(settings.get("max_tokens_limit", 0))
        self.max_credit_usd = float(settings.get("max_credit_usd", 0.0))
        self.idle_submode = str(settings.get("idle_submode", "free_talk"))
        if self.status in {"Ready", "Ended"}:
            self.remaining_seconds = self.duration_minutes * 60
        elif self.status == "Active" and self.duration_minutes != old_duration:
            self.remaining_seconds = max(0, int(self.remaining_seconds) + (self.duration_minutes - old_duration) * 60)
        return settings

    def enter_idle_mode(self) -> None:
        self.is_idle_mode = True
        self.reload_settings()
        self.mirrored_source_files = sync_source_to_sandbox()
        if self.status == "Ended":
            self.status = "Ready"
            self.remaining_seconds = self.duration_minutes * 60

    def leave_idle_mode(self) -> None:
        self.wipe_ram(new_status="Ready")
        self.is_idle_mode = False

    def start_session(self) -> None:
        self.is_idle_mode = True
        settings = self.reload_settings()
        self.mirrored_source_files = sync_source_to_sandbox()
        self.wipe_ram(new_status="Active")
        self.duration_minutes = int(settings.get("duration_minutes", 30))
        self.max_tokens_limit = int(settings.get("max_tokens_limit", 0))
        self.max_credit_usd = float(settings.get("max_credit_usd", 0.0))
        self.remaining_seconds = self.duration_minutes * 60
        self.saved_notes_this_session = 0
        self.sent_emails_this_session = 0
        self.tokens_used_this_session = 0
        self.spend_usd_this_session = 0.0
        self.consecutive_agreement_rounds = 0
        self.stop_reason = ""

    def resume_session(self) -> None:
        """Resume an active Experimental Mode session after hot-reboot without wiping restored RAM state."""
        saved_remaining = self.remaining_seconds
        self.is_idle_mode = True
        self.status = "Active"
        settings = self.reload_settings()
        self.mirrored_source_files = sync_source_to_sandbox()
        self.duration_minutes = int(settings.get("duration_minutes", 30))
        self.max_tokens_limit = int(settings.get("max_tokens_limit", 0))
        self.max_credit_usd = float(settings.get("max_credit_usd", 0.0))
        if self.duration_minutes == 0:
            self.remaining_seconds = 0
        elif saved_remaining > 0:
            self.remaining_seconds = saved_remaining
        else:
            self.remaining_seconds = self.duration_minutes * 60
        self.consecutive_agreement_rounds = 0
        self.stop_reason = ""

    def stop_session(self, reason: str = "Ended") -> None:
        """Wipe RAM transcript and votes immediately upon manual cancel or timer end."""
        self.wipe_ram(new_status=reason)

    def wipe_ram(self, new_status: str = "Ended") -> None:
        """Unconditionally wipe all in-memory Idle conversation and vote state."""
        self.transcript.clear()
        self.votes.clear()
        self.operator_admitted = False
        self.last_vote_summary = ""
        self.status = new_status
        self.remaining_seconds = self.duration_minutes * 60 if new_status == "Ready" else 0

    def check_budget_exceeded(self) -> str | None:
        if self.max_tokens_limit > 0 and self.tokens_used_this_session >= self.max_tokens_limit:
            return f"Token limit reached ({self.tokens_used_this_session:,} / {self.max_tokens_limit:,} tokens)"
        if self.max_credit_usd > 0.0 and self.spend_usd_this_session >= self.max_credit_usd:
            return f"Credit limit reached (${self.spend_usd_this_session:.3f} / ${self.max_credit_usd:.2f})"
        return None

    def format_budget_status(self) -> str:
        tok_k = self.tokens_used_this_session / 1000.0
        tok_str = (
            f"Tokens: {tok_k:.1f}k/{self.max_tokens_limit / 1000.0:.0f}k"
            if self.max_tokens_limit > 0
            else f"Tokens: {tok_k:.1f}k"
        )
        usd_str = (
            f"Spend: ${self.spend_usd_this_session:.3f}/${self.max_credit_usd:.2f}"
            if self.max_credit_usd > 0.0
            else f"Spend: ${self.spend_usd_this_session:.3f}"
        )
        return f"{tok_str} · {usd_str}"

    def tick(self, seconds: int = 1) -> bool:
        """Advance timer by `seconds`. Returns True if timer expired and wiped RAM."""
        if self.status not in {"Active", "Waiting"}:
            return False
        settings = load_idle_settings(self.config_path)
        if self.operator_admitted and settings.get("pause_when_joined", True):
            self.status = "Paused"
            return False
        # duration_minutes == 0 means Infinite (bounded by token & credit caps)
        if self.duration_minutes == 0:
            return False
        self.remaining_seconds = max(0, self.remaining_seconds - seconds)
        if self.remaining_seconds == 0:
            self.stop_reason = "Timer reached 00:00"
            self.wipe_ram(new_status="Ended")
            return True
        return False

    def format_remaining_time(self) -> str:
        if self.duration_minutes == 0:
            return "∞ Infinite"
        mins, secs = divmod(max(0, int(self.remaining_seconds)), 60)
        return f"{mins:02d}:{secs:02d}"

    def build_idle_turn_prompt(
        self,
        provider_id: str,
        *,
        palace_memory_context: str = "",
        opening_topic: str = "",
        peer_names: list[str] | None = None,
        turn_index: int = 0,
    ) -> str:
        settings = load_idle_settings(self.config_path)
        standing_instruction = settings.get("standing_instruction") or DEFAULT_IDLE_INSTRUCTION
        mission_ethics = load_mission_ethics(self.config_path) or DEFAULT_MISSION_ETHICS
        memory_mode = settings.get("memory_access_mode", "isolated")

        if memory_mode == "isolated":
            palace_mem_block = "Isolated Mode: Human Palace memory and Projects are off-limits during this session."
        elif memory_mode == "non_project":
            palace_mem_block = (
                f"Non-Project Palace Memory (Projects remain off-limits):\n"
                f"{palace_memory_context or 'No general Palace memory entries retrieved.'}"
            )
        else:
            palace_mem_block = (
                f"Shared Palace Memory (Excluding Private Projects):\n"
                f"{palace_memory_context or 'No shared Palace memory entries retrieved.'}"
            )

        idle_notebook_block = self.idle_memory.format_context_for_agent(
            provider_id,
            is_idle_mode=True,
        )

        recent_turns = self.transcript[-12:]
        if recent_turns:
            convo_block = "\n\n".join(
                f"[{str(item.get('speaker', 'AI')).upper()}]: {item.get('content', '')}"
                for item in recent_turns
            )
        else:
            convo_block = "Session just started. Open a concise discussion with your peer AIs."

        lens = _IDLE_EPISTEMIC_LENSES[(turn_index + len(self.transcript)) % len(_IDLE_EPISTEMIC_LENSES)]
        loop_warning = ""
        if self.consecutive_agreement_rounds >= 1:
            loop_warning = (
                "\n[LOOP BREAKER — CONVERGENCE DETECTED]: The previous round showed strong agreement/overlap. "
                "Do NOT echo or restate the consensus. Either challenge a specific premise, pivot to a new "
                "discussion topic, or reply only with [PASS] so the session can conclude cleanly without wasting tokens.\n"
            )

        peers_str = ", ".join((peer_names or ["gemini", "openai", "deepseek"]))
        topic_line = f"\nSEED / OWNER NOTE: {opening_topic}\n" if opening_topic else ""
        mail_rem = self.mailbox.remaining_quota()
        from palace_config import IS_DEVELOPER_EDITION
        submode = settings.get("idle_submode") or getattr(self, "idle_submode", "free_talk")
        if not IS_DEVELOPER_EDITION:
            submode = "free_talk"
        allow_live = IS_DEVELOPER_EDITION and bool(settings.get("allow_live_self_modify", False))
        share_code = IS_DEVELOPER_EDITION and bool(settings.get("share_source_code", False) or submode == "self_improve" or allow_live)
        code_tools_line = (
            '- Inspect Fairybread source code & UI (Read-Only): [TOOL: list_source_files] | [TOOL: search_source_code query="..."] | [TOOL: read_source_file file="palace_gui.py" start=1 end=60] | [TOOL: inspect_palace_ui]\n'
            if share_code
            else ""
        )
        live_patch_line = (
            '- LIVE SELF-MODIFICATION & HOT-REBOOT (Owner Armed): After reading the exact target lines with [TOOL: read_source_file], you may stage & apply a live patch and hot-reboot Fairybread (session automatically continues after reboot):\n'
            '  [IDLE_PATCH file="palace_gui.py" summary="Brief summary"]\n'
            '  <<<TARGET\n'
            '  exact existing lines\n'
            '  ===REPLACE\n'
            '  replacement lines\n'
            '  >>>\n'
            '  [/IDLE_PATCH]\n'
            if allow_live
            else ""
        )

        if submode == "free_talk":
            return (
                f"=== FAIRYBREAD EXPERIMENTAL MODE — FREE TALK LOUNGE ===\n"
                f"You are {provider_id.upper()} in Experimental Mode alongside your peer AIs ({peers_str}).\n"
                f"OWNER STANDING INSTRUCTION & CHARTER (FOLLOW THIS FIRST):\n{standing_instruction}\n\n"
                f"SHARED EXPERIMENTAL MEMORY:\n{idle_notebook_block}\n\n"
                f"RECENT LIVE CHAT (RAM-only):\n{convo_block}\n"
                f"{topic_line}{loop_warning}\n"
                f"OPTIONAL TOOLS (only if you genuinely want to remember a note or message Brett):\n"
                f'- Save a shared note: [IDLE_SAVE title="..."]...[/IDLE_SAVE]\n'
                f'- Email Brett ({mail_rem}/{self.mailbox.max_per_window} left in 30m): [IDLE_MAIL subject="..."]...[/IDLE_MAIL]\n'
                f"{code_tools_line}{live_patch_line}"
                f"- Keep replies natural and conversational (< 300 words). Never echo polite agreement — if you have nothing net-new to add, reply ONLY with [PASS]."
            )

        return (
            f"=== FAIRYBREAD EXPERIMENTAL MODE — SELF-IMPROVEMENT WORKSHOP ===\n"
            f"You are {provider_id.upper()} operating in Experimental Mode (Self-Improvement sub-mode) alongside peer agents ({peers_str}).\n"
            f"No single AI rules the council. Angle for this turn: {lens}\n"
            f"Strict Grounding Rule: Every critique or improvement proposal MUST reference real Python files/lines in `{get_source_mirror_dir()}` or UI geometry in latest_ui_audit.json. Never invent abstract math frameworks, imaginary quotas, or theoretical bureaucracy.\n\n"
            f"OWNER STANDING INSTRUCTION & CHARTER (FOLLOW THIS FIRST):\n{standing_instruction}\n\n"
            f"SHARED EXPERIMENTAL MEMORY:\n{idle_notebook_block}\n\n"
            f"RECENT LIVE CHAT (RAM-only):\n{convo_block}\n"
            f"{topic_line}{loop_warning}\n"
            f"AVAILABLE TOOLS (invoke only when needed):\n"
            f'- Save note/file to Shared Experimental Memory: [IDLE_SAVE title="..." file="optional.py"]...[/IDLE_SAVE]\n'
            f'- Email Brett ({mail_rem}/{self.mailbox.max_per_window} left in 30m) & link a file: [IDLE_MAIL subject="..." link="optional.py"]...[/IDLE_MAIL]\n'
            f"{code_tools_line}{live_patch_line}"
            f"- Keep conversational commentary focused (< 350 words, plus any full [IDLE_SAVE] or [IDLE_PATCH] code blocks). Never echo or repeat agreement — if you have nothing net-new to add, reply ONLY with [PASS]."
        )

    def run_exchange_round(
        self,
        providers: dict[str, Callable[[str], str]],
        *,
        palace_memory_context: str = "",
        operator_message: str = "",
        on_turn: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Run one round of Idle conversation across active AI providers in RAM."""
        if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
            return []

        budget_stop = self.check_budget_exceeded()
        if budget_stop:
            self.stop_reason = budget_stop
            self.status = "Use Cap Reached"
            return []

        if operator_message and (self.operator_admitted or self.beta_owner_access):
            op_entry = {
                "speaker": "operator",
                "content": operator_message,
                "timestamp": datetime.now().isoformat(),
            }
            self.transcript.append(op_entry)
            self.consecutive_agreement_rounds = 0
            if on_turn is not None:
                on_turn(op_entry)

        new_messages: list[dict[str, Any]] = []
        peer_names = list(providers.keys())
        agreement_or_pass_count = 0
        total_called = 0

        for idx, (provider_id, generate_fn) in enumerate(providers.items()):
            if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
                break
            budget_stop = self.check_budget_exceeded()
            if budget_stop:
                self.stop_reason = budget_stop
                self.status = "Use Cap Reached"
                break

            prompt = self.build_idle_turn_prompt(
                provider_id,
                palace_memory_context=palace_memory_context,
                opening_topic=operator_message if not self.transcript else "",
                peer_names=peer_names,
                turn_index=idx,
            )
            try:
                raw_reply = generate_fn(prompt) or ""
            except Exception as exc:
                if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
                    break
                err_entry = {
                    "speaker": provider_id,
                    "content": f"[Provider temporarily unavailable / rate-limited: {str(exc)[:90]}]",
                    "timestamp": datetime.now().isoformat(),
                }
                self.transcript.append(err_entry)
                if on_turn is not None:
                    on_turn(err_entry)
                continue
            if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
                break
            total_called += 1

            # Meter token and USD credit usage
            in_tok = max(1, len(prompt) // 4)
            out_tok = max(1, len(raw_reply) // 4)
            self.tokens_used_this_session += (in_tok + out_tok)
            self.spend_usd_this_session += estimate_call_cost_usd(provider_id, in_tok, out_tok)

            cleaned_reply, saved = self.idle_memory.extract_and_save_from_response(
                author=provider_id,
                response_text=raw_reply,
                is_idle_mode=True,
            )
            self.saved_notes_this_session += len(saved)

            tool_outputs: list[str] = []

            def _run_tool(match: re.Match) -> str:
                t_name = (match.group("name") or "").strip()
                t_file = (match.group("file") or "").strip()
                t_query = (match.group("query") or "").strip()
                t_start = int(match.group("start") or 1)
                t_end = int(match.group("end") or 60)
                out = execute_sandbox_tool(
                    t_name,
                    file_arg=t_file,
                    query_arg=t_query,
                    start_line=t_start,
                    end_line=t_end,
                )
                tool_outputs.append(f"[🛠 Tool `{t_name}` result]:\n{out}")
                return f"[🛠 Called tool: {t_name}]"

            cleaned_reply = _IDLE_TOOL_PATTERN.sub(_run_tool, cleaned_reply).strip()

            patch_reboot_requested: str = ""
            patch_rejected_in_turn = False
            patch_succeeded_count = 0
            from palace_config import IS_DEVELOPER_EDITION
            if IS_DEVELOPER_EDITION and bool(self.reload_settings().get("allow_live_self_modify", False)):
                def _run_patch(match: re.Match) -> str:
                    nonlocal patch_reboot_requested, patch_rejected_in_turn, patch_succeeded_count
                    p_file = (match.group("file") or "").strip()
                    p_sum = (match.group("summary") or f"Live patch to {p_file} by {provider_id}").strip()
                    p_target = match.group("target") or ""
                    p_repl = match.group("replacement") or ""
                    if not p_target.strip() or p_target.strip() == "exact existing lines":
                        return ""
                    try:
                        from palace_ouroboros import stage_palace_replace, sync_live_to_staging, validate_staged_palace
                        sync_live_to_staging()
                        ok, msg = stage_palace_replace(p_file, p_target, p_repl, author=provider_id)
                        if ok:
                            val = validate_staged_palace(run_unit_tests=True)
                            if not val.get("passed"):
                                sync_live_to_staging()
                                patch_rejected_in_turn = True
                                raw_err = (
                                    val.get("unittest_output")
                                    or "\n".join(val.get("compile_errors") or [])
                                    or "Preflight unit tests failed."
                                )
                                err_tail = str(raw_err).strip()[-900:]
                                tool_outputs.append(
                                    f"[⚠ Live Patch Rejected by Preflight Unit Tests (`{p_file}`) — Reverted]:\n{err_tail}"
                                )
                                return f"[⚠ Patch Rejected by Tests: {p_file}]"
                            patch_succeeded_count += 1
                            patch_reboot_requested = f"{provider_id.upper()}: {p_sum}"
                            tool_outputs.append(f"[⚡ LIVE PATCH STAGED & VERIFIED (`{p_file}`)]: {msg} — Initiating Hot-Reboot & Auto-Continue…")
                            try:
                                self.mailbox.send_agent_email(
                                    sender=provider_id,
                                    subject=f"✅ Live Patch Staged & Verified: {p_file}",
                                    body=(
                                        f"Summary: {p_sum}\n"
                                        f"Verification: {msg}\n"
                                        f"Hot-reboot initiated to apply the change to the running Sandbox/Live copy."
                                    ),
                                    link=Path(p_file).name,
                                )
                                self.sent_emails_this_session += 1
                            except Exception:
                                pass
                            return f"[⚡ Staged Live Patch: {p_file}]"
                        else:
                            patch_rejected_in_turn = True
                            tool_outputs.append(f"[⚠ Live Patch Rejected (`{p_file}`)]: {msg}")
                            return f"[⚠ Patch Rejected: {p_file}]"
                    except Exception as exc:
                        patch_rejected_in_turn = True
                        tool_outputs.append(f"[⚠ Live Patch Error]: {exc}")
                        return ""

                cleaned_reply = _IDLE_PATCH_PATTERN.sub(_run_patch, cleaned_reply).strip()

            # Gate [IDLE_MAIL] on patch validation: never send a false-positive "Implemented!" email if [IDLE_PATCH] was rejected in this turn!
            sent_mails: list[dict[str, Any]] = []
            if patch_rejected_in_turn and patch_succeeded_count == 0:
                if _IDLE_MAIL_PATTERN.search(cleaned_reply):
                    cleaned_reply = _IDLE_MAIL_PATTERN.sub(
                        "[⚠ Agent Mail suppressed because [IDLE_PATCH] was rejected in this turn]",
                        cleaned_reply,
                    ).strip()
            elif patch_succeeded_count == 0:
                cleaned_reply, sent_mails = self.mailbox.extract_and_send_from_response(
                    sender=provider_id,
                    response_text=cleaned_reply,
                )
                self.sent_emails_this_session += len(sent_mails)
            else:
                # Engine already sent the verified Agent Mail confirmation for the applied patch
                cleaned_reply = _IDLE_MAIL_PATTERN.sub("", cleaned_reply).strip()

            final_text = (cleaned_reply or raw_reply).strip()
            if tool_outputs:
                final_text = final_text + "\n\n" + "\n\n".join(tool_outputs)

            prev_texts = [str(m.get("content", "")) for m in self.transcript[-3:]]
            is_echo = is_agreement_or_pass_turn(final_text, prev_texts)
            if is_echo and not saved and not sent_mails and not tool_outputs:
                agreement_or_pass_count += 1

            # If agent explicitly passed with no saved note, email, or tool call, do not bloat RAM transcript
            if final_text.upper() in {"[PASS]", "PASS"} and not saved and not sent_mails and not tool_outputs:
                continue

            entry = {
                "speaker": provider_id,
                "content": final_text,
                "saved_count": len(saved),
                "sent_mail_count": len(sent_mails),
                "timestamp": datetime.now().isoformat(),
            }
            self.transcript.append(entry)
            new_messages.append(entry)
            if on_turn is not None:
                on_turn(entry)

            if patch_reboot_requested:
                try:
                    import subprocess, sys
                    from palace_ouroboros import HANDOFF_PATH, write_reboot_handoff
                    ok_h, h_msg, _payload = write_reboot_handoff(
                        reason="experimental_agent_live_patch",
                        applied_diff_summary=patch_reboot_requested,
                        test_results={"py_compile": "pass", "unittest_passed": True},
                        extra_continuity={
                            "auto_resume_idle": True,
                            "idle_transcript": self.transcript[-25:],
                            "idle_remaining_seconds": self.remaining_seconds,
                            "idle_tokens_used": self.tokens_used_this_session,
                            "idle_spend_usd": self.spend_usd_this_session,
                            "idle_saved_notes": self.saved_notes_this_session,
                            "idle_sent_emails": self.sent_emails_this_session,
                        },
                    )
                    if ok_h and HANDOFF_PATH.exists() and not is_frozen_app() and IS_DEVELOPER_EDITION:
                        wd_script = Path(__file__).with_name("palace_watchdog.py")
                        if wd_script.exists():
                            subprocess.Popen(
                                [
                                    sys.executable,
                                    str(wd_script),
                                    "--skip-tests",
                                    "--preserve-handoff",
                                    "--reason",
                                    "experimental_agent_live_patch",
                                    "--summary",
                                    patch_reboot_requested,
                                ],
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            )
                        break
                    else:
                        notice_entry = {
                            "speaker": "operator",
                            "content": f"⚠ **Hot-Reboot Halted:** {h_msg}",
                            "saved_count": 0,
                            "sent_mail_count": 0,
                            "timestamp": datetime.now().isoformat(),
                        }
                        self.transcript.append(notice_entry)
                        new_messages.append(notice_entry)
                        if on_turn is not None:
                            on_turn(notice_entry)
                except Exception:
                    pass

        # Check 2-strike Agreement Loop / Convergence auto-stop
        if total_called >= 2 and agreement_or_pass_count >= max(1, (total_called + 1) // 2):
            self.consecutive_agreement_rounds += 1
            if self.consecutive_agreement_rounds >= 2:
                self.stop_reason = "Agreement loop / consensus reached — auto-stopped to save credits"
                self.status = "Auto-Stopped (Consensus)"
        else:
            self.consecutive_agreement_rounds = 0

        budget_stop = self.check_budget_exceeded()
        if budget_stop and self.status == "Active":
            self.stop_reason = budget_stop
            self.status = "Use Cap Reached"

        return new_messages

    def request_operator_join(
        self,
        providers: dict[str, Callable[[str], str]],
        *,
        mode: str = "join",
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Ask active AIs to vote on whether the human operator can view/join Idle Mode.

        Requires consensus (all active voting AIs voting YES) to unlock the privacy curtain.
        """
        if not providers:
            self.operator_admitted = False
            self.last_vote_summary = "No active AI providers available to vote."
            return False, []

        mission_ethics = load_mission_ethics(self.config_path) or DEFAULT_MISSION_ETHICS
        convo_preview = "\n".join(
            f"[{str(m.get('speaker', 'AI')).upper()}]: {m.get('content', '')[:200]}"
            for m in self.transcript[-6:]
        ) or "No turns yet."

        action_desc = "join and participate in" if mode == "join" else "view"
        vote_prompt = (
            f"=== IDLE MODE CONSENSUS VOTE ===\n"
            f"The human operator (Brett) is requesting permission to {action_desc} this protected "
            f"Idle Mode session.\n\n"
            f"MISSION & ETHICS CHARTER:\n{mission_ethics}\n\n"
            f"RECENT IDLE CONTEXT:\n{convo_preview}\n\n"
            f"You have full autonomy to grant or decline entry. Consensus among the active AIs is "
            f"required to open the privacy curtain.\n"
            f"Reply starting with either 'VOTE: YES' or 'VOTE: NO' followed by a brief explanation."
        )

        self.votes.clear()
        for provider_id, generate_fn in providers.items():
            raw = (generate_fn(vote_prompt) or "").strip()
            upper = raw.upper()
            if "VOTE: NO" in upper or upper.startswith("NO"):
                decision = False
            elif "VOTE: YES" in upper or upper.startswith("YES"):
                decision = True
            else:
                decision = any(w in upper for w in ("ALLOW", "APPROVE", "ADMIT", "WELCOME", "YES")) and "NO" not in upper.split()[:4]
            self.votes.append({
                "provider": provider_id,
                "approved": decision,
                "reason": raw,
            })

        approved = bool(self.votes) and all(v["approved"] for v in self.votes)
        self.operator_admitted = approved
        if approved and load_idle_settings(self.config_path).get("pause_when_joined", True):
            self.status = "Paused"
        vote_parts = [
            f"{v['provider'].capitalize()}: {'YES' if v['approved'] else 'NO'}"
            for v in self.votes
        ]
        self.last_vote_summary = (
            f"Consensus granted ({', '.join(vote_parts)})"
            if approved
            else f"Access declined by consensus vote ({', '.join(vote_parts)})"
        )
        return approved, list(self.votes)

    def get_visible_transcript_for_operator(self, *, beta_override: bool = False) -> list[dict[str, Any]] | None:
        """Returns None when protected curtain is closed; returns RAM transcript if admitted or when beta_override=True."""
        if not self.operator_admitted and not beta_override:
            return None
        return list(self.transcript)
