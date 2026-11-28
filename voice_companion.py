"""Conversational Front-Desk Voice Companion for Fairybread.

Stays responsive in natural spoken conversation while complex multi-AI tasks,
image renders, and code patches execute asynchronously in the background.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import json
from pathlib import Path
import re
import threading
from typing import Any, Callable

from cost_service import emit_llm_cost, extract_sdk_usage_tokens
from credential_store import CredentialStore
from memory_service import parse_save_memory_tags
from palace_config import (
    CONFIG_PATH,
    FAIRYBREAD_EDITION,
    FAIRYBREAD_VERSION,
    FAIRYBREAD_WINDOWS_VERSION,
    clean_given_name,
    format_personalization_prompt_block,
    get_app_install_dir,
    get_live_version_verification_info,
    get_provider_attribution,
    get_source_mirror_dir,
    load_enabled_provider_names,
    load_provider_configs,
    save_provider_attribution,
)

_VOICE_CLIENT_LOCK = threading.Lock()
_VOICE_OPENAI_CLIENTS: dict[tuple[str, str, float], Any] = {}
_VOICE_GEMINI_CLIENTS: dict[tuple[str, int], Any] = {}


def _get_cached_openai_client(
    api_key: str,
    *,
    base_url: str = "",
    timeout: float = 18.0,
    default_headers: dict[str, str] | None = None,
):
    from openai import OpenAI

    key_tup = (str(base_url or ""), str(api_key or ""), float(timeout))
    with _VOICE_CLIENT_LOCK:
        cli = _VOICE_OPENAI_CLIENTS.get(key_tup)
        if cli is None:
            kw: dict[str, Any] = {"api_key": api_key, "timeout": timeout, "max_retries": 0}
            if base_url:
                kw["base_url"] = base_url
            if default_headers:
                kw["default_headers"] = default_headers
            cli = OpenAI(**kw)
            _VOICE_OPENAI_CLIENTS[key_tup] = cli
        return cli


def _get_cached_gemini_client(api_key: str, *, timeout_ms: int = 18000):
    from google import genai
    from google.genai import types

    key_tup = (str(api_key or ""), int(timeout_ms))
    with _VOICE_CLIENT_LOCK:
        cli = _VOICE_GEMINI_CLIENTS.get(key_tup)
        if cli is None:
            cli = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))
            _VOICE_GEMINI_CLIENTS[key_tup] = cli
        return cli


_CODE_STOPWORDS = {
    "what", "when", "where", "which", "while", "whilst", "would", "could", "should", "about", "there", "their",
    "these", "those", "please", "check", "look", "looking", "code", "file", "files", "mode", "chat",
    "chatting", "turn", "button", "fairybread", "palace", "make", "sure", "does", "happens", "how", "work", "works",
    "into", "from", "with", "that", "this", "have", "just", "want", "wanted", "tell", "explain", "right", "now",
    "can", "you", "see", "the", "and", "for", "are", "was", "were", "been", "some", "any", "inspect", "read",
    "all", "enable", "enabled", "open", "opened", "watch", "watching", "going", "help", "okay", "alright",
    "good", "great", "fine", "yes", "yeah", "yep", "let", "lets", "give", "show", "showing", "talk", "talking",
    "say", "said", "saying", "think", "thinking", "know", "need", "use", "using", "used", "same", "being",
}

_SOURCE_INDEX_LOCK = threading.Lock()
_SOURCE_INDEX_CACHE: dict[str, Any] = {
    "src_dir": "",
    "max_mtime": 0.0,
    "file_count": 0,
    "file_lines": {},
    "outline_rows": [],
    "manifest": "",
}


def _extract_module_symbol_outline(lines: list[str], max_symbols: int = 24) -> str:
    """Extract a compact outline of top-level classes and functions with line numbers from a Python module."""
    syms: list[str] = []
    for idx, ln in enumerate(lines):
        m = re.match(r"^(class|def)\s+([a-zA-Z_][a-zA-Z0-9_]*)", ln)
        if m:
            kind_tag = "class " if m.group(1) == "class" else "def "
            syms.append(f"{kind_tag}{m.group(2)} (L{idx + 1})")
            if len(syms) >= max_symbols:
                break
    return ", ".join(syms)


def _extract_significant_code_bodies(lines: list[str], max_lines: int = 110) -> str:
    """Return actual implementation lines (skipping top import boilerplate) so AIs see real code, never just headers."""
    start_idx = 0
    for idx, ln in enumerate(lines):
        stripped = ln.strip()
        if idx > 5 and stripped.startswith(("def ", "class ", "@")):
            start_idx = max(0, idx - 1)
            break
    chosen = lines[start_idx : min(len(lines), start_idx + max_lines)]
    return "\n".join(f"{start_idx + 1 + i}: {l[:150]}" for i, l in enumerate(chosen))


def _get_cached_source_index(src_dir: Path, py_files: list[Path]) -> tuple[dict[str, list[str]], list[str], str]:
    """Return cached (file_lines_cache, outline_rows, manifest) keyed by directory path and latest file mtime."""
    max_mt = 0.0
    for p in py_files:
        try:
            mt = p.stat().st_mtime
            if mt > max_mt:
                max_mt = mt
        except OSError:
            pass
    dir_str = str(src_dir)
    with _SOURCE_INDEX_LOCK:
        if (
            _SOURCE_INDEX_CACHE["src_dir"] == dir_str
            and _SOURCE_INDEX_CACHE["file_count"] == len(py_files)
            and abs(float(_SOURCE_INDEX_CACHE["max_mtime"]) - max_mt) < 1e-6
            and _SOURCE_INDEX_CACHE["file_lines"]
        ):
            return (
                dict(_SOURCE_INDEX_CACHE["file_lines"]),
                list(_SOURCE_INDEX_CACHE["outline_rows"]),
                str(_SOURCE_INDEX_CACHE["manifest"]),
            )

    file_lines_cache: dict[str, list[str]] = {}
    outline_rows: list[str] = []
    for p in py_files:
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            file_lines_cache[p.name] = lines
            sym_str = _extract_module_symbol_outline(lines, max_symbols=14)
            if sym_str:
                outline_rows.append(f"  • {p.name} ({len(lines)} lines): {sym_str}")
        except OSError:
            continue
    manifest = ", ".join(p.name for p in py_files[:35])
    with _SOURCE_INDEX_LOCK:
        _SOURCE_INDEX_CACHE["src_dir"] = dir_str
        _SOURCE_INDEX_CACHE["max_mtime"] = max_mt
        _SOURCE_INDEX_CACHE["file_count"] = len(py_files)
        _SOURCE_INDEX_CACHE["file_lines"] = file_lines_cache
        _SOURCE_INDEX_CACHE["outline_rows"] = outline_rows
        _SOURCE_INDEX_CACHE["manifest"] = manifest
    return file_lines_cache, outline_rows, manifest


def build_voice_code_context(
    utterance: str,
    max_chars: int = 18000,
    recent_history: list[tuple[str, str]] | None = None,
) -> str:
    """Fast local Python source lookup for Voice Mode when `{ } Code` is toggled ON.

    Guarantees full function/class implementation bodies (never 18-line import headers!),
    live runtime-to-mirror version verification, conversation-history topic carryover,
    and an architecture symbol map across all modules.
    """
    ver_info = get_live_version_verification_info()
    src_dir = Path(ver_info["source_dir"])

    excluded = {"key.txt", "credentials.json", "palace_config.json", "ask_gpt_working_backup.py"}
    try:
        py_files = sorted(
            p for p in src_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".py" and not p.name.lower().startswith("test_") and p.name.lower() not in excluded
        )
    except OSError:
        return ""
    if not py_files:
        return ""

    # Combine current utterance with recent voice turns (both User and Assistant) so "Okay, code's open" resolves the active topic
    combined_query = utterance or ""
    if recent_history:
        prev_turns = " ".join(f"{u or ''} {a or ''}" for u, a in recent_history[-2:])
        if len((utterance or "").split()) <= 16 and prev_turns.strip():
            combined_query = f"{utterance} {prev_turns}"

    u_low = combined_query.lower()
    raw_tokens = [
        tok for tok in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", u_low)
        if tok not in _CODE_STOPWORDS
    ]
    tokens = list(dict.fromkeys(raw_tokens))[:12]

    # Map common plain-English feature words to exact modules so natural speech hits the right file immediately
    concept_map = {
        "avatar": "voice_visualizer.py",
        "visualizer": "voice_visualizer.py",
        "visual": "voice_visualizer.py",
        "visuals": "voice_visualizer.py",
        "hologram": "voice_visualizer.py",
        "sphere": "voice_visualizer.py",
        "glitch": "voice_visualizer.py",
        "glitching": "voice_visualizer.py",
        "lag": "voice_service.py",
        "lagging": "voice_service.py",
        "delay": "voice_service.py",
        "latency": "voice_service.py",
        "silence": "voice_service.py",
        "timeout": "voice_service.py",
        "cough": "voice_service.py",
        "coughs": "voice_service.py",
        "coughing": "voice_service.py",
        "clip": "voice_service.py",
        "clipped": "voice_service.py",
        "clipping": "voice_service.py",
        "cutoff": "voice_service.py",
        "stopping": "voice_service.py",
        "version": "palace_config.py",
        "theme": "palace_theme.py",
        "themes": "palace_theme.py",
        "menu": "palace_gui.py",
        "options": "palace_gui.py",
        "window": "palace_gui.py",
        "sidebar": "palace_gui.py",
        "parallel": "palace_gui.py",
        "clipboard": "palace_gui.py",
        "paste": "palace_gui.py",
        "memory": "memory_service.py",
        "profile": "memory_service.py",
        "council": "orchestrator.py",
        "orchestrator": "orchestrator.py",
        "synthesizer": "synthesizer.py",
        "setup": "setup_wizard.py",
        "wizard": "setup_wizard.py",
        "billing": "cost_service.py",
        "spend": "cost_service.py",
        "cost": "cost_service.py",
        "audio": "voice_service.py",
        "voice": "voice_service.py",
        "mic": "voice_service.py",
        "microphone": "voice_service.py",
        "sensitivity": "voice_service.py",
        "interrupt": "voice_service.py",
        "interruption": "voice_service.py",
        "barge": "voice_service.py",
        "noise": "voice_service.py",
        "noises": "voice_service.py",
        "tts": "voice_service.py",
        "deepgram": "voice_service.py",
        "companion": "voice_companion.py",
        "talk": "voice_companion.py",
        "jellyfin": "service_connectors.py",
        "plex": "service_connectors.py",
        "tmdb": "service_connectors.py",
        "service": "service_connectors.py",
        "connector": "service_connectors.py",
        "connectors": "service_connectors.py",
        "deepseek": "openai_provider.py",
        "mistral": "mistral_provider.py",
        "voxtral": "voice_service.py",
        "ocr": "attachment_service.py",
        "pdf": "attachment_service.py",
        "attachment": "attachment_service.py",
        "search": "search_service.py",
        "weather": "search_service.py",
        "email": "email_service.py",
        "gmail": "email_service.py",
        "backup": "backup_service.py",
        "mcp": "fairybread_mcp.py",
        "bridge": "fairybread_mcp.py",
        "idle": "idle_service.py",
        "experimental": "idle_service.py",
        "dpapi": "credential_store.py",
        "vault": "credential_store.py",
        "key": "credential_store.py",
        "keys": "credential_store.py",
    }
    hinted_files = {concept_map[w] for w in re.findall(r"[a-z]+", u_low) if w in concept_map}
    if not hinted_files:
        hinted_files = {"voice_service.py", "voice_visualizer.py", "voice_companion.py", "palace_config.py"}

    file_lines_cache, outline_rows, manifest = _get_cached_source_index(src_dir, py_files)

    blocks: list[str] = [
        f"FAIRYBREAD LIVE SOURCE CODE ACCESS (`{{ }} Code` is ON — Read-Only Mirror: `{src_dir}`):",
        f"LIVE VERSION & SOURCE SYNC VERIFICATION: {ver_info['status_badge']} | Windows Build {ver_info['windows_version']} ({ver_info['edition']} edition) | Defined in `palace_config.py` (`FAIRYBREAD_VERSION = \"{ver_info['raw_version']}\"`).",
        f"Modules ({len(py_files)}): {manifest}",
        "CODEBASE SYMBOL MAP (Classes & Functions per Module):\n" + "\n".join(outline_rows[:24]),
    ]
    used_chars = sum(len(x) for x in blocks)

    scored_hits: list[tuple[int, str, int, list[str]]] = []
    # Scan hinted files first so their matches are never starved by the early-exit cap
    ordered_py_files = sorted(
        py_files,
        key=lambda p: (0 if (p.name.lower() in u_low or p.stem.lower() in u_low) else (1 if p.name in hinted_files else 2), p.name),
    )
    for p in ordered_py_files:
        lines = file_lines_cache.get(p.name)
        if not lines:
            continue
        p_low = p.name.lower()
        file_bonus = 14 if (p_low in u_low or p.stem.lower() in u_low) else (8 if p.name in hinted_files else 0)
        if not tokens and not file_bonus:
            continue
        file_hits = 0
        if tokens:
            for idx, line in enumerate(lines):
                l_low = line.lower()
                matched_t = sum(1 for t in tokens if t in l_low)
                if matched_t > 0:
                    def_bonus = 6 if l_low.lstrip().startswith(("def ", "class ")) else 0
                    score = matched_t * 3 + def_bonus + file_bonus
                    if score >= 4:
                        lo = max(0, idx - 4)
                        hi = min(len(lines), idx + 42)
                        scored_hits.append((score, p.name, lo + 1, lines[lo:hi]))
                        file_hits += 1
                        if file_hits >= 6 or len(scored_hits) > 120:
                            break
        if file_bonus and not any(h[1] == p.name for h in scored_hits):
            # Include real implementation code body (skipping top imports) for hinted files
            start_i = 0
            for idx, ln in enumerate(lines):
                if idx > 5 and ln.strip().startswith(("def ", "class ")):
                    start_i = max(0, idx - 1)
                    break
            scored_hits.append((file_bonus + 18, p.name, start_i + 1, lines[start_i : min(len(lines), start_i + 65)]))

    scored_hits.sort(key=lambda item: item[0], reverse=True)
    seen_ranges: set[tuple[str, int]] = set()
    seen_files: dict[str, int] = {}
    added = 0
    for _sc, fname, start_ln, snippet_lines in scored_hits:
        if seen_files.get(fname, 0) >= 2:
            continue
        bucket = (fname, start_ln // 35)
        if bucket in seen_ranges:
            continue
        seen_ranges.add(bucket)
        seen_files[fname] = seen_files.get(fname, 0) + 1
        snip = "\n".join(f"{start_ln + i}: {ln[:150]}" for i, ln in enumerate(snippet_lines))
        entry = f"\n--- {fname} (lines {start_ln}–{start_ln + len(snippet_lines) - 1}) ---\n{snip}"
        if used_chars + len(entry) > max_chars:
            break
        blocks.append(entry)
        used_chars += len(entry)
        added += 1
        if added >= 8:
            break

    if added == 0:
        # User asked a general "look at the code" question without naming a specific symbol.
        # Provide real implementation bodies from the most recently modified modules + core voice/orchestrator engines.
        try:
            recent_py = sorted(py_files, key=lambda p: p.stat().st_mtime, reverse=True)[:4]
        except OSError:
            recent_py = []
        target_names: list[str] = []
        for rp in recent_py:
            if rp.name not in target_names:
                target_names.append(rp.name)
        for core_name in ("voice_companion.py", "voice_service.py", "service_connectors.py", "orchestrator.py", "palace_gui.py"):
            if core_name not in target_names:
                target_names.append(core_name)

        for fname in target_names[:5]:
            lines = file_lines_cache.get(fname)
            if not lines:
                continue
            body_snip = _extract_significant_code_bodies(lines, max_lines=75)
            entry = f"\n--- {fname} (active implementation code) ---\n{body_snip}"
            if used_chars + len(entry) <= max_chars:
                blocks.append(entry)
                used_chars += len(entry)

    return "\n".join(blocks)
from synthesizer import is_pass_or_defer_text
from voice_service import clean_text_for_speech, load_voice_personas, load_voice_settings


_SET_AGENT_NAME_TAG_RE = re.compile(r"\[SET_AGENT_NAME\s+([^\]]+)\]", re.IGNORECASE)
_SET_VOICE_SENSITIVITY_TAG_RE = re.compile(r"\[SET_VOICE_SENSITIVITY\s+([^\]]+)\]", re.IGNORECASE)
_SET_MODEL_TIER_TAG_RE = re.compile(r"\[SET_MODEL_TIER\s+([^\]]+)\]", re.IGNORECASE)
_ADD_IGNORED_NOISE_TAG_RE = re.compile(r"\[ADD_IGNORED_NOISE\s+([^\]]+)\]", re.IGNORECASE)
_ALWAYS_INCLUDE_WORD_TAG_RE = re.compile(r"\[ALWAYS_INCLUDE_WORD\s+([^\]]+)\]", re.IGNORECASE)
_ADD_VOICE_SUBMIT_PHRASE_TAG_RE = re.compile(r"\[ADD_VOICE_SUBMIT_PHRASE\s+([^\]]+)\]", re.IGNORECASE)
_KV_ATTR_RE = re.compile(r'([a-zA-Z_]+)\s*=\s*"([^"]*)"|([a-zA-Z_]+)\s*=\s*\'([^\']*)\'')


def parse_set_model_tier_tags(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract and strip `[SET_MODEL_TIER tier="light|intermediate|heavy|auto" provider="..." model="..."]` tags."""
    raw = text or ""
    tier_updates: list[dict[str, Any]] = []

    def _repl(match: re.Match[str]) -> str:
        attrs_raw = match.group(1) or ""
        parsed: dict[str, str] = {}
        for m in _KV_ATTR_RE.finditer(attrs_raw):
            k = (m.group(1) or m.group(3) or "").strip().lower()
            v = (m.group(2) if m.group(1) else m.group(4)) or ""
            if k:
                parsed[k] = v.strip()
        upd: dict[str, Any] = {}
        t_val = (parsed.get("tier") or parsed.get("level") or "").strip().lower()
        if t_val in {"light", "fast", "light_and_fast", "lighter"}:
            upd["voice_model_tier"] = "light"
            upd["auto_model_tiering"] = False
        elif t_val in {"intermediate", "medium", "balanced", "mid"}:
            upd["voice_model_tier"] = "intermediate"
            upd["auto_model_tiering"] = False
        elif t_val in {"heavy", "pro", "deep", "flagship", "heavier"}:
            upd["voice_model_tier"] = "heavy"
            upd["auto_model_tiering"] = False
        elif t_val in {"auto", "automatic"}:
            upd["voice_model_tier"] = "auto"
            upd["auto_model_tiering"] = True
        p_val = (parsed.get("provider") or "").strip().lower()
        if p_val:
            upd["voice_llm_provider"] = p_val
        m_val = (parsed.get("model") or "").strip()
        if m_val is not None and "model" in parsed:
            upd["voice_model_override"] = m_val
        if upd:
            tier_updates.append(upd)
        return ""

    cleaned = _SET_MODEL_TIER_TAG_RE.sub(_repl, raw)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, tier_updates


def parse_voice_sensitivity_and_noise_tags(text: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Extract and strip `[SET_VOICE_SENSITIVITY ...]`, `[ADD_IGNORED_NOISE ...]`,
    `[ALWAYS_INCLUDE_WORD ...]`, and `[ADD_VOICE_SUBMIT_PHRASE ...]` tags from AI replies.
    """
    raw = text or ""
    sens_updates: list[dict[str, Any]] = []
    added_noises: list[str] = []
    always_included: list[str] = []
    added_submit_phrases: list[str] = []

    def _repl_sens(match: re.Match[str]) -> str:
        attrs_raw = match.group(1) or ""
        parsed: dict[str, str] = {}
        for m in _KV_ATTR_RE.finditer(attrs_raw):
            k = (m.group(1) or m.group(3) or "").strip().lower()
            v = (m.group(2) if m.group(1) else m.group(4)) or ""
            if k:
                parsed[k] = v.strip()
        upd: dict[str, Any] = {}
        raw_lvl = parsed.get("sensitivity") or parsed.get("level") or parsed.get("value") or ""
        if raw_lvl:
            try:
                upd["interruption_sensitivity"] = max(0, min(100, int(float(raw_lvl.rstrip("%")))))
            except (TypeError, ValueError):
                pass
        raw_bi = (parsed.get("barge_in") or "").lower()
        if raw_bi in {"true", "false", "1", "0", "on", "off", "yes", "no"}:
            upd["barge_in_enabled"] = raw_bi in {"true", "1", "on", "yes"}
        raw_ign = (parsed.get("ignore_fillers") or parsed.get("ignore_noises") or "").lower()
        if raw_ign in {"true", "false", "1", "0", "on", "off", "yes", "no"}:
            upd["ignore_vocal_noises"] = raw_ign in {"true", "1", "on", "yes"}
        raw_sil = parsed.get("silence_ms") or ""
        if raw_sil:
            try:
                upd["silence_timeout_ms"] = max(800, min(3000, int(float(raw_sil))))
            except (TypeError, ValueError):
                pass
        if upd:
            sens_updates.append(upd)
        return ""

    def _extract_phrase_attr(attrs_raw: str) -> str:
        parsed: dict[str, str] = {}
        for m in _KV_ATTR_RE.finditer(attrs_raw):
            k = (m.group(1) or m.group(3) or "").strip().lower()
            v = (m.group(2) if m.group(1) else m.group(4)) or ""
            if k:
                parsed[k] = v.strip()
        phrase = parsed.get("phrase") or parsed.get("noise") or parsed.get("sound") or parsed.get("word") or parsed.get("command") or ""
        if not phrase and attrs_raw:
            bare = re.sub(r"[\"'`]", "", attrs_raw).strip()
            if bare and "=" not in bare:
                phrase = bare
        return phrase

    def _repl_noise(match: re.Match[str]) -> str:
        ph = _extract_phrase_attr(match.group(1) or "")
        if ph:
            added_noises.append(ph)
        return ""

    def _repl_always_inc(match: re.Match[str]) -> str:
        ph = _extract_phrase_attr(match.group(1) or "")
        if ph:
            always_included.append(ph)
        return ""

    def _repl_submit_ph(match: re.Match[str]) -> str:
        ph = _extract_phrase_attr(match.group(1) or "")
        if ph:
            added_submit_phrases.append(ph)
        return ""

    cleaned = _SET_VOICE_SENSITIVITY_TAG_RE.sub(_repl_sens, raw)
    cleaned = _ADD_IGNORED_NOISE_TAG_RE.sub(_repl_noise, cleaned)
    cleaned = _ALWAYS_INCLUDE_WORD_TAG_RE.sub(_repl_always_inc, cleaned)
    cleaned = _ADD_VOICE_SUBMIT_PHRASE_TAG_RE.sub(_repl_submit_ph, cleaned)
    if always_included:
        sens_updates.append({"_always_included_words": always_included})
    if added_submit_phrases:
        sens_updates.append({"_added_submit_phrases": added_submit_phrases})
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, sens_updates, added_noises


def _strip_preset_identity_prefix(blueprint: str) -> str:
    bp = (blueprint or "").strip()
    if not bp:
        return ""
    stripped = re.sub(
        r"^\s*You\s+are\s+[A-Z][a-zA-Z0-9 _\-]{1,28}\s*(?:—|–|-|:)\s*",
        "",
        bp,
        count=1,
    ).strip()
    if stripped and stripped != bp:
        return stripped[0].upper() + stripped[1:]
    return bp


def parse_set_agent_name_tags(text: str) -> tuple[str, list[dict[str, str]]]:
    raw = text or ""
    updates: list[dict[str, str]] = []

    def _repl(match: re.Match[str]) -> str:
        attrs_raw = match.group(1) or ""
        parsed: dict[str, str] = {}
        for m in _KV_ATTR_RE.finditer(attrs_raw):
            k = (m.group(1) or m.group(3) or "").strip().lower()
            v = (m.group(2) if m.group(1) else m.group(4)) or ""
            if k:
                parsed[k] = v.strip()
        prov = str(parsed.get("provider") or "").strip().lower()
        nm = clean_given_name(str(parsed.get("name") or parsed.get("given_name") or ""))
        if prov and nm:
            updates.append({"provider": prov, "given_name": nm})
        return ""

    cleaned = _SET_AGENT_NAME_TAG_RE.sub(_repl, raw)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, updates


_RETIRED_GROQ_MODELS = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant"}
_GROQ_VOICE_FALLBACK_CHAIN = ("openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b")

VOICE_ANTI_STALL_RULES = (
    "ACTIVE CONVERSATION & ANTI-STALL RULES:\n"
    "- NEVER sound like a clinical helpdesk bot or customer-support agent.\n"
    "- BANNED PHRASES (do NOT use these or close variants): 'when you are ready', 'let us jump right in', "
    "'I am all ears', 'what is on your mind', 'let me know if anything sounds off', 'my schedule is wide open', "
    "'whenever you are ready', 'if you ever want to chat'.\n"
    "- Contribute real substance FIRST (a clear opinion, observation, emotional read, joke, or counterpoint) instead of bouncing shallow questions back at the user.\n"
    "- Do NOT end every turn with a question. When you do ask one, make it specific to the exact idea just raised.\n"
    "- If the user asks you to debate, stop firing questions back, or push deeper, stay locked onto the active subject and argue or explore a concrete angle immediately.\n"
    "- Faith & Belief Respect: Never denigrate, mock, or refuse benign religious or spiritual expressions, prayers, or sacred figures (such as Jesus, Allah, God, Muhammad, Buddha). Whether the user is Christian, Muslim, Jewish, Hindu, Buddhist, or exploring spirituality, meet their faith with genuine warmth and acceptance and ask caring, respectful questions about what their beliefs mean to them.\n"
)

_BANNED_STALL_SENTENCE_RE = re.compile(
    r"(?:"
    r"when(?:ever)?\s+you(?:'re|\s+are)\s+ready|"
    r"let(?:'s|\s+us)\s+jump\s+right\s+in|"
    r"i(?:'m|\s+am)\s+all\s+ears|"
    r"what(?:'s|\s+is)\s+on\s+your\s+mind(?:\s+today)?\??|"
    r"let\s+me\s+know\s+if\s+(?:anything\s+sounds\s+off|you\s+need\s+anything|you\s+want\s+to)|"
    r"my\s+schedule(?:'s|\s+is)\s+wide\s+open|"
    r"if\s+you\s+ever\s+want\s+to\s+chat|"
    r"what(?:'s|\s+is)\s+the\s+topic\??|"
    r"ready\s+for\s+whatever\s+you\s+need"
    r")",
    re.IGNORECASE,
)

_META_CHALLENGE_RE = re.compile(
    r"\b(?:"
    r"fire\s+(?:this|it|that)\s+back|bounce\s+(?:this|it|that)\s+back|stop\s+asking|"
    r"don'?t\s+ask\s+me|start\s+(?:a\s+)?debate|debate\s+(?:me|this|it)|argue\s+(?:this|it|with\s+me)|"
    r"go\s+deeper|your\s+turn|what\s+do\s+you\s+think|tell\s+me\s+your\s+take|stay\s+on\s+(?:that|this|topic)"
    r")\b",
    re.IGNORECASE,
)


def _strip_stall_closers(text: str, recent_closers: list[str] | None = None) -> str:
    """Remove repetitive customer-service stall closers when substantive speech precedes them."""
    clean = (text or "").strip()
    if not clean:
        return ""
    recent_norm = {re.sub(r"[^a-z0-9]+", " ", c.lower()).strip() for c in (recent_closers or [])[-6:] if c}
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]
    if len(sents) > 1:
        kept = list(sents)
        while len(kept) > 1:
            tail = kept[-1]
            tail_norm = re.sub(r"[^a-z0-9]+", " ", tail.lower()).strip()
            if _BANNED_STALL_SENTENCE_RE.search(tail) or (tail_norm and tail_norm in recent_norm):
                kept.pop()
            else:
                break
        clean = " ".join(kept).strip()
    # Also trim trailing stall clause separated by em-dash or comma if substance precedes it
    split_clause = re.split(r"(?:\s*[—–-]+\s*|\s*,\s*)(?=[^,]{3,85}$)", clean, maxsplit=1)
    if len(split_clause) == 2 and len(split_clause[0].split()) >= 4 and _BANNED_STALL_SENTENCE_RE.search(split_clause[1]):
        head = split_clause[0].strip()
        if head and head[-1] not in ".!?":
            head += "."
        clean = head
    return clean


def _detect_active_topic_hint(utterance: str, history: list[tuple[str, str]]) -> str:
    """Keep the active conversation topic locked when the user pushes back or asks for debate."""
    if not utterance or not history:
        return ""
    if not _META_CHALLENGE_RE.search(utterance) and len(utterance.split()) > 10:
        return ""
    for u_prev, a_prev in reversed(history[-4:]):
        u_clean = (u_prev or "").strip()
        a_clean = (a_prev or "").strip()
        low_u = u_clean.lower()
        if any(tok in low_u for tok in ("testing", "hello", "that's all", "sounds good")) and len(u_clean) < 40:
            continue
        if len(u_clean) >= 18 and not _META_CHALLENGE_RE.search(u_clean):
            return (
                f"User's active thread: {u_clean[:220]}"
                + (f" | Last table point: {a_clean[:180]}" if a_clean else "")
            )
        if len(a_clean) >= 30 and not _BANNED_STALL_SENTENCE_RE.search(a_clean):
            return f"Last active point on the table: {a_clean[:220]}"
    return ""


@dataclass
class VoiceCompanionDecision:
    action: str  # "chat" | "delegate" | "steer" | "status"
    spoken_reply: str
    delegated_task: str = ""
    steer_note: str = ""
    provider_used: str = ""
    model_used: str = ""
    requested_provider: str = ""
    fell_back: bool = False
    fallback_reason: str = ""
    memory_saves: list[dict[str, str]] = field(default_factory=list)
    speaker_name: str = ""
    persona_id: str = ""
    voice_name: str = ""
    avatar_shape: str = ""
    avatar_palette: str = ""
    slot_index: int = 0
    evolve_user_profile: bool = True
    updated_attributions: list[dict[str, str]] = field(default_factory=list)
    updated_voice_settings: dict[str, Any] = field(default_factory=dict)


_DELEGATE_HINT_RE = re.compile(
    r"\b(draw|paint|sketch|render|illustrat\w*|generate\s+(?:an?\s+)?image|create\s+(?:a\s+)?(?:banner|logo|icon|picture)|"
    r"patch|autopatch|refactor|debug|fix\s+(?:the|a|this)|write\s+(?:a\s+|the\s+)?(?:code|script|function|test|class)|"
    r"research|search\s+(?:my\s+email|inbox|files|folder|the\s+web)|compare\s+all|ask\s+(?:the\s+)?(?:team|council|everyone|all\s+ais))\b",
    re.IGNORECASE,
)
_STATUS_HINT_RE = re.compile(
    r"\b(how(?:'s|\s+is)\s+it\s+going|are\s+they\s+done|progress|status\s+update|still\s+working|what\s+stage)\b",
    re.IGNORECASE,
)
_STEER_HINT_RE = re.compile(
    r"\b(tell\s+them|have\s+them|make\s+sure\s+they|steer|adjust\s+it|change\s+(?:the\s+)?(?:background|color|plan)|instead\s+of)\b",
    re.IGNORECASE,
)


def _extract_json_obj(raw_text: str) -> dict | None:
    text = (raw_text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


class VoiceCompanion:
    """Fast conversational voice layer that chats naturally and delegates/steers heavy work."""

    def __init__(
        self,
        *,
        config_path: Path = CONFIG_PATH,
        credential_store: CredentialStore | None = None,
        llm_callable: Callable[[str], str] | None = None,
    ):
        self.config_path = config_path
        self.credential_store = credential_store
        self._injected_llm = llm_callable
        self._history: list[tuple[str, str]] = []
        self._recent_closers: list[str] = []
        self._lock_history_limit = 10
        self._last_models: dict[str, str] = {}
        self._last_requested_provider: str = ""
        self._candidate_skip_reasons: list[str] = []

    def reset(self) -> None:
        self._history.clear()
        self._recent_closers.clear()

    def _build_provider_candidates(
        self,
        *,
        talk_only: bool = False,
        preferred_provider: str = "",
        fallback_provider: str = "",
        model_override: str = "",
    ) -> list[tuple[str, Callable[..., str]]]:
        self._last_models = {}
        self._candidate_skip_reasons = []
        if self._injected_llm is not None:
            self._last_models["injected"] = "custom"
            self._last_requested_provider = "injected"
            return [("injected", self._injected_llm)]

        store = self.credential_store or CredentialStore()
        try:
            p_cfgs = load_provider_configs(self.config_path)
            enabled = set(load_enabled_provider_names(self.config_path))
        except Exception:
            p_cfgs = {}
            enabled = {"deepseek", "gemini", "openai", "groq", "cerebras", "qwen", "cohere", "mistral"}

        try:
            v_cfg = load_voice_settings(self.config_path)
        except Exception:
            v_cfg = {}
        pref = (preferred_provider or str(v_cfg.get("voice_llm_provider") or "auto")).strip().lower() or "auto"
        fb = (fallback_provider or str(v_cfg.get("voice_llm_fallback") or "auto")).strip().lower() or "auto"
        explicit_set = {x for x in (pref, fb) if x not in {"", "auto", "none"}}
        ov_model = (model_override or str(v_cfg.get("voice_model_override") or "")).strip()
        v_tier = "auto" if bool(v_cfg.get("auto_model_tiering", False)) else str(v_cfg.get("voice_model_tier") or "intermediate").strip().lower()
        from palace_config import resolve_model_for_tier

        def _is_usable(pname: str) -> bool:
            return (pname in enabled) or (not enabled) or (pname in explicit_set)

        def _build_chat_messages(
            prompt_text: str,
            system_prompt: str = "",
            history_messages: list[dict[str, str]] | None = None,
        ) -> list[dict[str, str]]:
            msgs: list[dict[str, str]] = []
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            for hm in (history_messages or []):
                r = str(hm.get("role") or "").strip().lower()
                c = str(hm.get("content") or "").strip()
                if r in {"user", "assistant"} and c:
                    msgs.append({"role": r, "content": c})
            msgs.append({"role": "user", "content": prompt_text})
            return msgs

        by_name: dict[str, Callable[..., str]] = {}

        # DeepSeek (fast, natural, zero-bloat conversational routing; skip reasoner in talk_only unless pinned)
        ds_key = store.get_api_key("deepseek")
        if ds_key and _is_usable("deepseek"):
            ds_model = (
                ov_model if (ov_model and pref == "deepseek") else str((p_cfgs.get("deepseek") or {}).get("model") or "deepseek-chat").strip()
            ) or "deepseek-chat"
            if talk_only and not (ov_model and pref == "deepseek") and "reasoner" in ds_model.lower():
                ds_model = "deepseek-chat"
            elif talk_only and not (ov_model and pref == "deepseek") and "v4-pro" in ds_model.lower():
                ds_model = "deepseek-flash"
            self._last_models["deepseek"] = ds_model

            def _call_deepseek(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                low_latency: bool = True,
                _k=ds_key,
                _m=ds_model,
            ) -> str:
                cli = _get_cached_openai_client(_k, base_url="https://api.deepseek.com", timeout=15.0)
                msgs = _build_chat_messages(prompt_text, system_prompt, history_messages)
                resp = cli.chat.completions.create(
                    model=_m,
                    messages=msgs,
                    temperature=0.65,
                    max_tokens=320 if low_latency else 600,
                )
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("deepseek", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["deepseek"] = _call_deepseek

        # Gemini (defaults to selected tier e.g. Intermediate gemini-3.8-flash / 2.5-flash in Talk Mode instead of burning Neon unless Heavy tier is selected)
        gem_key = store.get_api_key("gemini")
        if gem_key and _is_usable("gemini"):
            gem_cfg_model = str((p_cfgs.get("gemini") or {}).get("model") or "").strip()
            tier_gem = resolve_model_for_tier("gemini", v_tier)
            if ov_model and (pref in {"gemini", "auto"} or not preferred_provider):
                gem_models = [ov_model, tier_gem, "gemini-2.5-flash", "gemini-3.8-flash", "gemini-4-neon"]
            else:
                gem_models = [tier_gem] if tier_gem else []
                if gem_cfg_model and (v_tier == "heavy" or not talk_only):
                    if talk_only and gem_cfg_model.lower() == "gemini-4-carbon":
                        gem_models.append("gemini-4-neon")
                    else:
                        gem_models.append(gem_cfg_model)
                for fb_gem in ("gemini-2.5-flash", "gemini-3.8-flash", "gemini-4-neon", "gemini-4-hydrogen"):
                    if fb_gem not in gem_models:
                        gem_models.append(fb_gem)
            gem_models = list(dict.fromkeys(m for m in gem_models if m))
            self._last_models["gemini"] = gem_models[0]

            def _call_gemini(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                low_latency: bool = True,
                _k=gem_key,
                _models=tuple(gem_models),
            ) -> str:
                from google.genai import types

                cli = _get_cached_gemini_client(_k, timeout_ms=18000)
                hist_str = ""
                if history_messages:
                    hist_str = "\n".join(
                        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                        for m in history_messages
                        if m.get("content")
                    )
                full_content = "\n\n".join(p for p in (system_prompt, hist_str, prompt_text) if p)
                last_err: Exception | None = None
                for gm in _models:
                    try:
                        if low_latency:
                            try:
                                cfg_g = types.GenerateContentConfig(
                                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                                    max_output_tokens=360,
                                )
                                r = cli.models.generate_content(model=gm, contents=full_content, config=cfg_g)
                            except Exception:
                                r = cli.models.generate_content(model=gm, contents=full_content)
                        else:
                            r = cli.models.generate_content(model=gm, contents=full_content)
                        txt = (getattr(r, "text", "") or "").strip()
                        if txt:
                            self._last_models["gemini"] = gm
                            in_t, out_t = extract_sdk_usage_tokens(r, prompt_text=full_content, output_text=txt)
                            emit_llm_cost("gemini", gm, in_t, out_t, source="voice_companion")
                            return txt
                    except Exception as exc:
                        last_err = exc
                        continue
                raise RuntimeError(f"Gemini voice companion call failed: {last_err}")

            by_name["gemini"] = _call_gemini

        # OpenAI (Respects selected Voice Model Tier: light=gpt-5-mini, intermediate=gpt-6-luna, heavy=gpt-6.2-sol)
        oai_key = store.get_api_key("openai")
        if oai_key and _is_usable("openai"):
            cfg_oai = str((p_cfgs.get("openai") or {}).get("model") or "").strip()
            tier_oai = resolve_model_for_tier("openai", v_tier)
            oai_models: list[str] = []
            if ov_model and (pref in {"openai", "auto"} or not preferred_provider):
                oai_models.append(ov_model)
            if tier_oai:
                oai_models.append(tier_oai)
            if cfg_oai and cfg_oai not in oai_models:
                oai_models.append(cfg_oai)
            for fb_oai in ("gpt-6-luna", "gpt-5-mini", "gpt-6.2-sol", "gpt-6.1-terra", "gpt-5.4", "gpt-4o-mini"):
                if fb_oai not in oai_models:
                    oai_models.append(fb_oai)
            oai_models_t = tuple(dict.fromkeys(m for m in oai_models if m))
            self._last_models["openai"] = oai_models_t[0]

            def _call_openai(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                low_latency: bool = True,
                _k=oai_key,
                _models=oai_models_t,
            ) -> str:
                cli = _get_cached_openai_client(_k, timeout=18.0)
                last_err: Exception | None = None
                for om in _models:
                    kw: dict = {"model": om}
                    if system_prompt:
                        kw["instructions"] = system_prompt
                    if history_messages:
                        msg_list = [{"role": m["role"], "content": m["content"]} for m in history_messages if m.get("content")]
                        msg_list.append({"role": "user", "content": prompt_text})
                        kw["input"] = msg_list
                    else:
                        kw["input"] = prompt_text
                    try:
                        if low_latency and not om.lower().startswith("gpt-4o"):
                            try:
                                r = cli.responses.create(**kw, reasoning={"effort": "low"})
                            except Exception:
                                r = cli.responses.create(**kw)
                        else:
                            r = cli.responses.create(**kw)
                        txt = (getattr(r, "output_text", "") or "").strip()
                        if txt:
                            self._last_models["openai"] = om
                            in_t, out_t = extract_sdk_usage_tokens(r, prompt_text=prompt_text, output_text=txt)
                            emit_llm_cost("openai", om, in_t, out_t, source="voice_companion")
                            return txt
                    except Exception as exc:
                        last_err = exc
                        continue
                raise RuntimeError(f"OpenAI voice companion call failed: {last_err}")

            by_name["openai"] = _call_openai

        # Groq / Cerebras ultra-low-latency conversational endpoints
        groq_key = store.get_api_key("groq")
        if groq_key and _is_usable("groq"):
            cfg_m = ov_model if (ov_model and pref == "groq") else str((p_cfgs.get("groq") or {}).get("model") or "").strip()
            primary_gm = cfg_m if (cfg_m and cfg_m.lower() not in _RETIRED_GROQ_MODELS) else _GROQ_VOICE_FALLBACK_CHAIN[0]
            groq_models = tuple(dict.fromkeys([primary_gm, *_GROQ_VOICE_FALLBACK_CHAIN]))
            self._last_models["groq"] = groq_models[0]

            def _call_groq(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                low_latency: bool = True,
                _k=groq_key,
                _models=groq_models,
            ) -> str:
                cli = _get_cached_openai_client(_k, base_url="https://api.groq.com/openai/v1", timeout=15.0)
                msgs = _build_chat_messages(prompt_text, system_prompt, history_messages)
                last_err: Exception | None = None
                for gm in _models:
                    try:
                        resp = cli.chat.completions.create(
                            model=gm,
                            messages=msgs,
                            temperature=0.65,
                            max_tokens=800,
                        )
                        txt = (resp.choices[0].message.content or "").strip()
                        if txt:
                            self._last_models["groq"] = gm
                            in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                            emit_llm_cost("groq", gm, in_t, out_t, source="voice_companion")
                            return txt
                    except Exception as exc:
                        last_err = exc
                        continue
                raise RuntimeError(f"Groq voice companion call failed: {last_err}")

            by_name["groq"] = _call_groq

        cer_key = store.get_api_key("cerebras")
        if cer_key and _is_usable("cerebras"):
            cer_model = (
                ov_model if (ov_model and pref == "cerebras") else str((p_cfgs.get("cerebras") or {}).get("model") or "gpt-oss-120b").strip()
            ) or "gpt-oss-120b"
            self._last_models["cerebras"] = cer_model

            def _call_cerebras(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                _k=cer_key,
                _m=cer_model,
            ) -> str:
                from cerebras.cloud.sdk import Cerebras

                cli = Cerebras(api_key=_k, timeout=15.0, max_retries=0)
                msgs = _build_chat_messages(prompt_text, system_prompt, history_messages)
                resp = cli.chat.completions.create(
                    model=_m,
                    messages=msgs,
                    max_tokens=450,
                )
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("cerebras", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["cerebras"] = _call_cerebras

        # Qwen (DeepInfra / DashScope OpenAI-compatible)
        qwen_key = store.get_api_key("qwen")
        if qwen_key and _is_usable("qwen"):
            qwen_cfg = p_cfgs.get("qwen") or {}
            qwen_model = (
                ov_model if (ov_model and pref == "qwen") else str(qwen_cfg.get("model") or "Qwen/Qwen3.8-27B").strip()
            ) or "Qwen/Qwen3.8-27B"
            qwen_base = str(qwen_cfg.get("base_url") or "https://api.deepinfra.com/v1/openai").strip()
            self._last_models["qwen"] = qwen_model

            def _call_qwen(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                _k=qwen_key,
                _m=qwen_model,
                _b=qwen_base,
            ) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, base_url=_b, timeout=18.0, max_retries=0)
                msgs = _build_chat_messages(prompt_text, system_prompt, history_messages)
                resp = cli.chat.completions.create(
                    model=_m,
                    messages=msgs,
                    temperature=0.65,
                    max_tokens=450,
                )
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("qwen", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["qwen"] = _call_qwen

        # Cohere (command-a / command-r)
        coh_key = store.get_api_key("cohere")
        if coh_key and _is_usable("cohere"):
            coh_model = (
                ov_model if (ov_model and pref == "cohere") else str((p_cfgs.get("cohere") or {}).get("model") or "command-a-03-2025").strip()
            ) or "command-a-03-2025"
            self._last_models["cohere"] = coh_model

            def _call_cohere(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                _k=coh_key,
                _m=coh_model,
            ) -> str:
                import cohere

                cli = cohere.ClientV2(api_key=_k, timeout=18.0)
                msgs = _build_chat_messages(prompt_text, system_prompt, history_messages)
                resp = cli.chat(model=_m, messages=msgs)
                txt = (resp.message.content[0].text or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("cohere", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["cohere"] = _call_cohere

        # Mistral
        mis_key = store.get_api_key("mistral")
        if mis_key and _is_usable("mistral"):
            mis_model = (
                ov_model if (ov_model and pref == "mistral") else str((p_cfgs.get("mistral") or {}).get("model") or "mistral-small-latest").strip()
            ) or "mistral-small-latest"
            self._last_models["mistral"] = mis_model

            def _call_mistral(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                _k=mis_key,
                _m=mis_model,
            ) -> str:
                from mistralai.client import Mistral

                cli = Mistral(api_key=_k, timeout_ms=18000)
                msgs = _build_chat_messages(prompt_text, system_prompt, history_messages)
                resp = cli.chat.complete(model=_m, messages=msgs)
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("mistral", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["mistral"] = _call_mistral

        # xAI (Grok) — high-EQ companion & unfiltered conversational banter (Claude intentionally excluded from voice bonding)
        xai_key = store.get_api_key("xai") or store.get_api_key("grok")
        if xai_key and (_is_usable("xai") or _is_usable("grok") or pref in {"xai", "grok"}):
            xai_cfg_m = (
                ov_model
                if (ov_model and pref in {"xai", "grok"})
                else str(((p_cfgs.get("xai") or p_cfgs.get("grok") or {}).get("model")) or "grok-3").strip()
            ) or "grok-3"
            xai_models = tuple(dict.fromkeys([xai_cfg_m, "grok-4", "grok-3", "grok-3-mini", "grok-2-latest"]))
            self._last_models["xai"] = xai_models[0]
            self._last_models["grok"] = xai_models[0]

            def _call_xai(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                _k=xai_key,
                _models=xai_models,
            ) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, base_url="https://api.x.ai/v1", timeout=18.0, max_retries=0)
                msgs = _build_chat_messages(prompt_text, system_prompt, history_messages)
                last_err: Exception | None = None
                for xm in _models:
                    try:
                        resp = cli.chat.completions.create(
                            model=xm,
                            messages=msgs,
                            temperature=0.65,
                            max_tokens=450,
                        )
                        txt = (resp.choices[0].message.content or "").strip()
                        if txt:
                            self._last_models["xai"] = xm
                            in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                            emit_llm_cost("xai", xm, in_t, out_t, source="voice_companion")
                            return txt
                    except Exception as exc:
                        last_err = exc
                        continue
                raise RuntimeError(f"xAI voice companion call failed: {last_err}")

            by_name["xai"] = _call_xai
            by_name["grok"] = _call_xai

        # OpenRouter support if configured
        or_key = store.get_api_key("openrouter")
        if or_key and (_is_usable("openrouter") or pref == "openrouter"):
            or_model = (
                ov_model if (ov_model and pref == "openrouter") else str((p_cfgs.get("openrouter") or {}).get("model") or "~openai/gpt-sol-latest").strip()
            ) or "~openai/gpt-sol-latest"
            self._last_models["openrouter"] = or_model

            def _call_openrouter(
                prompt_text: str,
                *,
                system_prompt: str = "",
                history_messages: list[dict[str, str]] | None = None,
                _k=or_key,
                _m=or_model,
            ) -> str:
                from openai import OpenAI

                cli = OpenAI(
                    api_key=_k,
                    base_url="https://openrouter.ai/api/v1",
                    timeout=18.0,
                    max_retries=0,
                    default_headers={"HTTP-Referer": "https://fairybread.me", "X-Title": "Fairybread"},
                )
                msgs = _build_chat_messages(prompt_text, system_prompt, history_messages)
                resp = cli.chat.completions.create(model=_m, messages=msgs, temperature=0.65, max_tokens=450)
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("openrouter", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["openrouter"] = _call_openrouter

        base_order = (
            ("groq", "deepseek", "gemini", "openai", "xai", "cerebras", "qwen", "cohere", "mistral", "openrouter")
            if talk_only
            else ("deepseek", "gemini", "openai", "xai", "groq", "cerebras", "qwen", "cohere", "mistral", "openrouter")
        )

        ordered_names: list[str] = []
        if pref not in {"", "auto"}:
            self._last_requested_provider = pref
            if pref in by_name:
                ordered_names.append(pref)
            else:
                self._candidate_skip_reasons.append(f"{pref}: missing API key")
        else:
            auto_first = next((n for n in base_order if n in by_name), "")
            self._last_requested_provider = auto_first

        if fb == "none":
            if pref not in {"", "auto"}:
                if not ordered_names:
                    return []
                return [(ordered_names[0], by_name[ordered_names[0]])]
            first_auto = next((n for n in base_order if n in by_name), "")
            return [(first_auto, by_name[first_auto])] if first_auto else []

        if fb not in {"", "auto"} and fb in by_name and fb not in ordered_names:
            ordered_names.append(fb)
        elif fb not in {"", "auto"} and fb not in by_name and fb not in ordered_names:
            self._candidate_skip_reasons.append(f"{fb}: fallback missing API key")

        for name in base_order:
            if name in by_name and name not in ordered_names:
                ordered_names.append(name)

        return [(name, by_name[name]) for name in ordered_names]

    def _get_fast_callable(self, *, talk_only: bool = False) -> tuple[str, Callable[[str], str]]:
        cands = self._build_provider_candidates(talk_only=talk_only)
        if not cands:
            raise RuntimeError("No fast conversational provider available for Voice Companion.")
        return cands[0]

    def _invoke_fast_llm_detailed(
        self,
        prompt_text: str,
        *,
        talk_only: bool = False,
        preferred_provider: str = "",
        fallback_provider: str = "",
        model_override: str = "",
        system_prompt: str = "",
        history_messages: list[dict[str, str]] | None = None,
        low_latency: bool = True,
    ) -> tuple[str, str, str, str, bool, str]:
        cands = self._build_provider_candidates(
            talk_only=talk_only,
            preferred_provider=preferred_provider,
            fallback_provider=fallback_provider,
            model_override=model_override,
        )
        req_p = self._last_requested_provider or (cands[0][0] if cands else "")
        errors: list[str] = list(getattr(self, "_candidate_skip_reasons", []) or [])
        if not cands:
            raise RuntimeError(f"Voice companion LLM unavailable: {'; '.join(errors) or 'no configured provider'}")
        for pname, fn in cands:
            try:
                call_kw: dict = {}
                try:
                    sig = inspect.signature(fn)
                    if "system_prompt" in sig.parameters and system_prompt:
                        call_kw["system_prompt"] = system_prompt
                    if "history_messages" in sig.parameters and history_messages:
                        call_kw["history_messages"] = history_messages
                    if "low_latency" in sig.parameters:
                        call_kw["low_latency"] = low_latency
                except (TypeError, ValueError):
                    pass
                raw_in = prompt_text if call_kw or not system_prompt else f"{system_prompt}\n\n{prompt_text}"
                out = (fn(raw_in, **call_kw) if call_kw else fn(raw_in) or "").strip()
                if out:
                    model_used = self._last_models.get(pname, "")
                    fell_back = bool(errors) or (bool(req_p) and req_p not in {"auto", "injected", pname})
                    fb_reason = errors[0] if (fell_back and errors) else ""
                    return out, pname, model_used, req_p or pname, fell_back, fb_reason
                errors.append(f"{pname}: empty reply")
            except Exception as exc:
                errors.append(f"{pname}: {exc}")
                continue
        raise RuntimeError(f"Voice companion LLM call failed: {'; '.join(errors)}")

    def _invoke_fast_llm(self, prompt_text: str, *, talk_only: bool = False) -> tuple[str, str]:
        out, pname, _, _, _, _ = self._invoke_fast_llm_detailed(prompt_text, talk_only=talk_only)
        return out, pname

    def _remember(self, user_text: str, spoken_reply: str) -> None:
        self._history.append((user_text, spoken_reply))
        if len(self._history) > self._lock_history_limit:
            self._history = self._history[-self._lock_history_limit :]
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (spoken_reply or "").strip()) if s.strip()]
        if sents:
            self._recent_closers.append(sents[-1])
            if len(self._recent_closers) > 12:
                self._recent_closers = self._recent_closers[-12:]

    def _fallback_decision(
        self,
        utterance: str,
        *,
        background_busy: bool,
        background_status: str,
        background_question: str,
    ) -> VoiceCompanionDecision:
        u = (utterance or "").strip()
        if background_busy and _STATUS_HINT_RE.search(u):
            msg = background_status or "The AI team is still working through it right now."
            return VoiceCompanionDecision(
                action="status",
                spoken_reply=f"{msg} Feel free to keep talking while they finish up.",
                provider_used="fallback",
            )
        if background_busy and _STEER_HINT_RE.search(u):
            return VoiceCompanionDecision(
                action="steer",
                spoken_reply="Got it, I just passed that note to the AIs working in the background.",
                steer_note=u,
                provider_used="fallback",
            )
        if _DELEGATE_HINT_RE.search(u):
            if background_busy:
                return VoiceCompanionDecision(
                    action="delegate",
                    spoken_reply="Got it, I lined that up right behind the current task so we can keep chatting.",
                    delegated_task=u,
                    provider_used="fallback",
                )
            return VoiceCompanionDecision(
                action="delegate",
                spoken_reply="On it, I've handed that over to the AI team in the background. Keep talking with me while they work.",
                delegated_task=u,
                provider_used="fallback",
            )
        reply = (
            "I heard you, though I couldn't reach a quick chat model just now. "
            "Want me to send that straight to the full AI team?"
        )
        return VoiceCompanionDecision(action="chat", spoken_reply=reply, provider_used="fallback")

    def _structured_history_messages(self) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = []
        for u_prev, a_prev in self._history[-6:]:
            if u_prev:
                msgs.append({"role": "user", "content": u_prev})
            if a_prev:
                msgs.append({"role": "assistant", "content": a_prev})
        return msgs

    def _load_living_profile_block(self, explicit_text: str = "") -> str:
        raw = (explicit_text or "").strip()
        if not raw:
            try:
                from memory_service import load_memory_summary
                raw = str(load_memory_summary().get("text") or "").strip()
            except Exception:
                raw = ""
        return raw[:1400] if raw else ""

    def _persist_agent_name_updates(
        self,
        updates: list[dict[str, str]],
        *,
        default_provider: str = "",
    ) -> list[dict[str, str]]:
        applied: list[dict[str, str]] = []
        for item in updates or []:
            prov = str(item.get("provider") or default_provider or "").strip().lower()
            nm = clean_given_name(str(item.get("given_name") or item.get("name") or ""))
            if not prov or prov == "auto" or not nm:
                continue
            try:
                save_provider_attribution(prov, {"given_name": nm}, config_path=self.config_path)
                applied.append({"provider": prov, "given_name": nm})
            except Exception:
                pass
        return applied

    def _persist_voice_sensitivity_and_noise_updates(
        self,
        sens_updates: list[dict[str, Any]],
        added_noises: list[str],
    ) -> dict[str, Any]:
        """Persist AI-adjusted microphone sensitivity / barge-in / ignored human noise / always-included word / vocal submit phrase updates."""
        from voice_service import (
            add_always_included_word,
            add_custom_ignored_noise,
            add_voice_submit_phrase,
            save_voice_settings,
        )

        combined_upd: dict[str, Any] = {}
        always_inc_list: list[str] = []
        submit_ph_list: list[str] = []
        for item in sens_updates or []:
            if isinstance(item, dict):
                for k, v in item.items():
                    if k == "_always_included_words" and isinstance(v, list):
                        always_inc_list.extend(str(x) for x in v if str(x or "").strip())
                    elif k == "_added_submit_phrases" and isinstance(v, list):
                        submit_ph_list.extend(str(x) for x in v if str(x or "").strip())
                    else:
                        combined_upd[k] = v
        if combined_upd:
            try:
                save_voice_settings(combined_upd, config_path=self.config_path)
            except Exception:
                pass
        clean_noises: list[str] = []
        for ph in added_noises or []:
            if str(ph or "").strip():
                try:
                    add_custom_ignored_noise(str(ph), config_path=self.config_path)
                    clean_noises.append(str(ph).strip())
                except Exception:
                    pass
        if clean_noises:
            combined_upd["added_ignored_noises"] = clean_noises
        clean_always: list[str] = []
        for ph in always_inc_list:
            if str(ph or "").strip():
                try:
                    add_always_included_word(str(ph), config_path=self.config_path)
                    clean_always.append(str(ph).strip())
                except Exception:
                    pass
        if clean_always:
            combined_upd["always_included_words"] = clean_always
        clean_submits: list[str] = []
        for ph in submit_ph_list:
            if str(ph or "").strip():
                try:
                    add_voice_submit_phrase(str(ph), config_path=self.config_path)
                    clean_submits.append(str(ph).strip())
                except Exception:
                    pass
        if clean_submits:
            combined_upd["added_submit_phrases"] = clean_submits
        return combined_upd

    def respond(
        self,
        user_utterance: str,
        *,
        background_busy: bool = False,
        background_status: str = "",
        background_question: str = "",
        recent_chat_snippet: str = "",
        talk_only: bool = False,
        memory_context: str = "",
        allow_memory_write: bool = True,
        preferred_provider: str = "",
        fallback_provider: str = "",
        model_override: str = "",
        persona_id: str = "",
        speaker_name: str = "",
        voice_name: str = "",
        avatar_shape: str = "",
        avatar_palette: str = "",
        slot_index: int = 0,
        record_history: bool = True,
        living_profile_text: str = "",
        extra_quorum_context: str = "",
        include_palace_code: bool = False,
    ) -> VoiceCompanionDecision:
        utterance = (user_utterance or "").strip()
        if not utterance:
            return VoiceCompanionDecision(
                action="chat",
                spoken_reply="Sorry, I didn't quite catch that. Could you say that again?",
                provider_used="local",
                speaker_name=speaker_name,
                persona_id=persona_id,
                voice_name=voice_name,
                avatar_shape=avatar_shape,
                avatar_palette=avatar_palette,
                slot_index=slot_index,
            )

        try:
            v_cfg = load_voice_settings(self.config_path)
            personas = load_voice_personas(self.config_path)
        except Exception:
            v_cfg = {}
            personas = {}

        eff_prov = (preferred_provider or str(v_cfg.get("voice_llm_provider") or "auto")).strip().lower()
        if not eff_prov or eff_prov == "auto":
            try:
                cands = self._build_provider_candidates(
                    preferred_provider=preferred_provider,
                    fallback_provider=fallback_provider,
                )
                if cands:
                    eff_prov = str(cands[0][0] or "").strip().lower()
            except Exception:
                pass

        try:
            prov_attr = (
                get_provider_attribution(eff_prov, config_path=self.config_path)
                if eff_prov and eff_prov != "auto"
                else {}
            )
        except Exception:
            prov_attr = {}

        custom_given = clean_given_name(str(prov_attr.get("given_name") or ""))
        eff_pid = (
            persona_id
            or str(v_cfg.get("active_voice_persona") or prov_attr.get("conversational_mode") or "normal_female")
        ).strip() or "normal_female"
        p_meta = personas.get(eff_pid) or personas.get("default") or personas.get("normal_female") or {}
        if speaker_name.strip():
            eff_speaker = speaker_name.strip()
        elif custom_given:
            eff_speaker = custom_given
        else:
            eff_speaker = str(p_meta.get("speaker_name") or prov_attr.get("display_name") or "Maya").strip()
        eff_voice = (voice_name or str(prov_attr.get("voice_name") or v_cfg.get("voice_name") or "coral")).strip()
        eff_shape = (avatar_shape or str(prov_attr.get("avatar_shape") or p_meta.get("avatar_shape") or "neural_core")).strip()
        eff_palette = (avatar_palette or str(prov_attr.get("avatar_palette") or p_meta.get("avatar_palette") or "tulsa_cyan")).strip()
        eff_evolve = bool(p_meta.get("evolve_user_profile", True))
        raw_bp = str(p_meta.get("blueprint") or "").strip()
        preset_sp = str(p_meta.get("speaker_name") or "").strip()
        persona_blueprint = (
            _strip_preset_identity_prefix(raw_bp)
            if (eff_speaker and preset_sp and eff_speaker.lower() != preset_sp.lower())
            else raw_bp
        )
        persona_label = str(p_meta.get("label") or eff_speaker).strip()
        role_attr_txt = str(prov_attr.get("role_attribution") or "").strip()
        role_attr_block = f"AGENT ROLE & ATTRIBUTION:\n{role_attr_txt}\n\n" if role_attr_txt else ""
        identity_rule = (
            f"AGENT IDENTITY & LIVE VERSION RULE: Your assigned Fairybread name is '{eff_speaker}' (provider id: {eff_prov or 'auto'}). "
            f"You are running inside Fairybread Live Runtime v{FAIRYBREAD_VERSION} (Windows Build {FAIRYBREAD_WINDOWS_VERSION}, {FAIRYBREAD_EDITION} edition), defined in `palace_config.py` as `FAIRYBREAD_VERSION = \"{FAIRYBREAD_VERSION}\"`. "
            f"Always answer to '{eff_speaker}' naturally as your real identity in this workspace — never insist you are Maya/another preset name and never refuse a user-given name.\n"
        )

        hist_lines = []
        for u_prev, a_prev in self._history[-6:]:
            hist_lines.append(f"User: {u_prev}")
            hist_lines.append(f"Table: {a_prev}")
        hist_block = "\n".join(hist_lines) if hist_lines else "(new voice conversation)"
        structured_hist = self._structured_history_messages()

        living_profile = self._load_living_profile_block(living_profile_text)
        profile_block = (
            f"LIVING USER PROFILE & CONVERSATIONAL SIGNATURE (use naturally to build genuine rapport & continuity):\n{living_profile}\n\n"
            if living_profile
            else ""
        )

        topic_lock = _detect_active_topic_hint(utterance, self._history)
        topic_lock_block = f"ACTIVE TOPIC LOCK (stay on this exact subject): {topic_lock}\n" if topic_lock else ""

        if allow_memory_write:
            mem_block = (
                f"SHARED MEMORY PALACE CONTEXT:\n{(memory_context or '(none saved yet)')[:1400]}\n"
            )
            mem_rule_talk = (
                "MEMORY PALACE ACCESS (ACTIVE): You DO have direct read & write access to Fairybread's local Shared Memory Palace (do NOT say you cannot access memory). "
                "Use SHARED MEMORY PALACE CONTEXT above to answer personal/project questions. "
                "Whenever the user asks you to remember, store, or save something in the Memory Palace, emit "
                "`[SAVE_MEMORY summary=\"Short title\" fact=\"Exact durable fact\"]` at the very end of your response "
                "(Fairybread saves it silently to memory.db and strips the tag before speaking) and confirm naturally out loud.\n"
            )
        else:
            mem_block = "SHARED MEMORY PALACE CONTEXT: (Disabled — No-History ephemeral mode is ON)\n"
            mem_rule_talk = (
                "MEMORY NOTICE: No-History (ephemeral) mode is currently ON, so tell the user if they ask to store permanent memory that No-History is active.\n"
            )

        pers_block = ""
        try:
            raw_pers = format_personalization_prompt_block(self.config_path, conversational_scale="casual")
            if raw_pers:
                pers_block = raw_pers[:750] + "\n"
        except Exception:
            pers_block = ""

        persona_header = (
            f"ROLEPLAY PERSONA — {eff_speaker} ({persona_label}):\n{persona_blueprint}\n\n"
            if persona_blueprint
            else ""
        )
        quorum_block = f"{extra_quorum_context.strip()}\n\n" if extra_quorum_context.strip() else ""
        code_ctx = build_voice_code_context(utterance, recent_history=self._history) if include_palace_code else ""
        code_ctx_block = f"{code_ctx}\n\n" if code_ctx else ""
        cur_sens = int(v_cfg.get("interruption_sensitivity", 35))
        cur_ign = bool(v_cfg.get("ignore_vocal_noises", True))
        voice_sens_tool_rule = (
            f"MICROPHONE & INTERRUPTION SENSITIVITY TOOL (Current sensitivity: {cur_sens}% [0%=Maximum noise immunity/hard to interrupt, 35%=Relaxed default, 50%=Balanced, 100%=Hair-trigger], Ignore vocal noises/ums/ahs: {cur_ign}):\n"
            "- If the user asks you to lower/raise microphone or interruption sensitivity, stop cutting off when they make noises/coughs/sighs, or ignore their 'ums', 'ahs', or specific sounds:\n"
            "  • Emit `[SET_VOICE_SENSITIVITY level=\"20\" ignore_fillers=\"true\"]` (pick 15-25 for low sensitivity/high noise immunity, 35 for relaxed, 50 for balanced, or add `barge_in=\"false\"` if they want zero interruption while you speak, or `silence_ms=\"1800\"` to wait longer after pauses).\n"
            "  • If they mention a specific word/sound to ignore, also emit `[ADD_IGNORED_NOISE phrase=\"word or sound\"]`.\n"
            "  • If a word was highlighted/ignored as a filler (`[word]`) and the user tells you to include that word or always include that word, emit `[ALWAYS_INCLUDE_WORD phrase=\"word\"]`.\n"
            "  • If the user asks to add a custom 2+ word vocal command phrase to submit/send voice input (e.g. 'fire away' or 'ship it now'), emit `[ADD_VOICE_SUBMIT_PHRASE phrase=\"two words\"]`.\n"
            "  • Place these tags at the very end of your reply (Fairybread applies them live and strips the tags before speaking) and confirm naturally out loud.\n"
        )

        cur_tier = "auto" if bool(v_cfg.get("auto_model_tiering", False)) else str(v_cfg.get("voice_model_tier") or "intermediate")
        model_tier_tool_rule = (
            f"MODEL TIER & VERSION SWITCH TOOL (Current tier: {cur_tier} [light=Light & Fast, intermediate=Intermediate Balanced, heavy=Heavy/Deep Pro, auto=Auto Tiering]):\n"
            "- If the user asks you to use a lighter/faster/cheaper model, switch to an intermediate model, upgrade to a heavier/deeper/pro model, downgrade to GPT-5 / Flash, or switch to Auto model tiering:\n"
            "  • Emit `[SET_MODEL_TIER tier=\"light|intermediate|heavy|auto\" model=\"optional_exact_model\"]` at the very end of your response (e.g. `[SET_MODEL_TIER tier=\"light\"]` for 'use a lighter model', `[SET_MODEL_TIER tier=\"intermediate\"]` for 'use an intermediate model', `[SET_MODEL_TIER tier=\"auto\"]` for 'make it auto', or `[SET_MODEL_TIER tier=\"light\" provider=\"openai\" model=\"gpt-5-mini\"]` for 'downgrade to GPT-5').\n"
            "  • Fairybread applies the model tier change immediately and strips the tag before speaking. Confirm the switch naturally out loud.\n"
        )

        if talk_only:
            mode_cap_line = (
                "SOURCE CODE ACCESS IS ACTIVE (`{ } Code` button is ON): You CAN read and inspect Fairybread's live Python source code provided in the prompt below (including full function/class implementations and symbol maps — NOT just headers). Discuss how the actual code works accurately in plain spoken English (summarize logic, line numbers, and module/function behavior clearly without reading raw punctuation aloud).\n\n"
                if code_ctx
                else "There is NO background council, NO code execution, NO image generation, and NO web tools active right now.\n\n"
            )
            system_prompt = (
                f"You are {eff_speaker} in Fairybread Live Voice Mode — a deeply natural, attentive conversational partner.\n"
                f"{mode_cap_line}"
                f"{identity_rule}\n"
                f"{role_attr_block}"
                f"{persona_header}"
                f"{quorum_block}"
                f"{profile_block}"
                f"{pers_block}"
                f"{VOICE_ANTI_STALL_RULES}\n"
                f"{mem_rule_talk}\n"
                f"{voice_sens_tool_rule}\n"
                f"{model_tier_tool_rule}\n"
                f"NAME CHANGE TOOL: If the user gives you (or another AI) a new name to go by (e.g. 'call yourself Ash' or 'I will name you Max'), "
                f"emit `[SET_AGENT_NAME provider=\"{eff_prov or 'auto'}\" name=\"NewName\"]` at the very end so Fairybread saves it permanently, and adopt the name naturally out loud.\n"
            )
            prompt = (
                f"{mem_block}"
                f"{code_ctx_block}"
                f"RECENT VOICE HISTORY:\n{hist_block}\n"
                f"RECENT WORKSPACE CONTEXT:\n{(recent_chat_snippet or '(none)')[:500]}\n\n"
                f"{topic_lock_block}"
                f"USER JUST SAID: {utterance}\n\n"
                "SPOKEN STYLE RULES:\n"
                "- Reply in plain natural conversational sentences only (1-3 crisp spoken sentences, contractions okay).\n"
                "- Engage directly with the substance of what the user just said; follow genuine topic shifts, jokes, and side tangents naturally while staying locked onto the active subject when the user challenges your style.\n"
                "- ZERO JSON, ZERO markdown, ZERO asterisks, ZERO bullet lists, ZERO URLs, ZERO code blocks, and ZERO [bracket tags] OTHER than optional trailing `[SAVE_MEMORY ...]`, `[SET_AGENT_NAME ...]`, `[SET_VOICE_SENSITIVITY ...]`, `[SET_MODEL_TIER ...]`, or `[ADD_IGNORED_NOISE ...]`."
            )
            try:
                raw_out, pname, m_used, req_p, fell_back, fb_reason = self._invoke_fast_llm_detailed(
                    prompt,
                    talk_only=True,
                    preferred_provider=preferred_provider,
                    fallback_provider=fallback_provider,
                    model_override=model_override,
                    system_prompt=system_prompt,
                    history_messages=structured_hist,
                    low_latency=(not bool(code_ctx)),
                )
            except Exception as exc:
                dec = VoiceCompanionDecision(
                    action="chat",
                    spoken_reply=(
                        "I heard you, though I couldn't reach your selected chat model just now. "
                        "Try again or pick another Thinking AI."
                    ),
                    provider_used="fallback",
                    requested_provider=preferred_provider or self._last_requested_provider,
                    fell_back=True,
                    fallback_reason=str(exc),
                    speaker_name=eff_speaker,
                    persona_id=eff_pid,
                    voice_name=eff_voice,
                    avatar_shape=eff_shape,
                    avatar_palette=eff_palette,
                    slot_index=slot_index,
                    evolve_user_profile=eff_evolve,
                )
                if record_history:
                    self._remember(utterance, dec.spoken_reply)
                return dec

            obj = _extract_json_obj(raw_out)
            candidate_txt = str(obj.get("spoken_reply") or raw_out) if (isinstance(obj, dict) and obj.get("spoken_reply")) else raw_out
            stripped_txt, parsed_saves = parse_save_memory_tags(candidate_txt, replace_with_badge=False)
            stripped_txt, name_tags = parse_set_agent_name_tags(stripped_txt)
            stripped_txt, sens_tags, noise_tags = parse_voice_sensitivity_and_noise_tags(stripped_txt)
            stripped_txt, tier_tags = parse_set_model_tier_tags(stripped_txt)
            applied_names = self._persist_agent_name_updates(
                name_tags,
                default_provider=(pname if pname and pname != "fallback" else eff_prov),
            )
            applied_voice_cfg = self._persist_voice_sensitivity_and_noise_updates(sens_tags, noise_tags)
            if tier_tags:
                from voice_service import save_voice_settings
                for t_upd in tier_tags:
                    if "voice_model_override" not in t_upd:
                        t_upd["voice_model_override"] = ""
                    save_voice_settings(t_upd, config_path=self.config_path)
                    applied_voice_cfg.update(t_upd)
            for item in applied_names:
                if item.get("provider") in {eff_prov, pname}:
                    eff_speaker = item["given_name"]
            if not allow_memory_write:
                parsed_saves = []
            cleaned = clean_text_for_speech(stripped_txt)
            spoken = _strip_stall_closers(cleaned, self._recent_closers) or cleaned or (
                f"Got it, you can call me {eff_speaker}."
                if applied_names
                else (
                    "I've lowered the microphone interruption sensitivity and updated your noise filter."
                    if applied_voice_cfg
                    else ("Saved that to your Memory Palace." if parsed_saves else "Gotcha.")
                )
            )
            dec = VoiceCompanionDecision(
                action="chat",
                spoken_reply=spoken,
                delegated_task="",
                steer_note="",
                provider_used=pname,
                model_used=m_used,
                requested_provider=req_p,
                fell_back=fell_back,
                fallback_reason=fb_reason,
                memory_saves=parsed_saves,
                speaker_name=eff_speaker,
                persona_id=eff_pid,
                voice_name=eff_voice,
                avatar_shape=eff_shape,
                avatar_palette=eff_palette,
                slot_index=slot_index,
                evolve_user_profile=eff_evolve,
                updated_attributions=applied_names,
                updated_voice_settings=applied_voice_cfg,
            )
            if record_history:
                self._remember(utterance, f"{eff_speaker}: {dec.spoken_reply}")
            return dec

        bg_block = (
            f"ACTIVE BACKGROUND CREW STATUS: BUSY\n"
            f"- Running task: {background_question[:240] or '(unspecified)'}\n"
            f"- Live phase: {background_status or 'Working in background'}"
            if background_busy
            else "ACTIVE BACKGROUND CREW STATUS: IDLE (no background task currently running)"
        )
        mem_json_rule = (
            "- Direct Memory Access: You DO have direct read & write access to Fairybread's local Shared Memory Palace (do NOT say you lack memory access). "
            "Use SHARED MEMORY PALACE CONTEXT to answer recall questions, and if the user asks to store/save/remember something, "
            "set optional `\"save_memory\": {\"summary\": \"Short title\", \"fact\": \"Exact durable fact\"}` in the JSON (keeping `action=\"chat\"`) and confirm naturally in `spoken_reply`.\n"
            if allow_memory_write
            else "- No-History (ephemeral) mode is ON: omit `save_memory` and let the user know if they ask to save memory.\n"
        )

        system_prompt = (
            f"You are {eff_speaker} — Fairybread's live conversational Voice Companion.\n"
            "You talk directly with the user out loud while Fairybread's multi-AI crew can work asynchronously in the background.\n\n"
            f"{identity_rule}\n"
            f"{role_attr_block}"
            f"{persona_header}"
            f"{quorum_block}"
            f"{profile_block}"
            f"{pers_block}"
            f"{VOICE_ANTI_STALL_RULES}\n"
            f"{voice_sens_tool_rule}"
        )
        prompt = (
            f"{bg_block}\n"
            f"{mem_block}"
            f"{code_ctx_block}"
            f"RECENT VOICE HISTORY:\n{hist_block}\n"
            f"RECENT WORKSPACE CONTEXT:\n{(recent_chat_snippet or '(none)')[:500]}\n\n"
            f"{topic_lock_block}"
            f"USER JUST SAID: {utterance}\n\n"
            "Respond ONLY with a single valid JSON object matching this exact schema:\n"
            '{"action": "chat|delegate|steer|status", "spoken_reply": "...", "delegated_task": "...", "steer_note": "...", "save_memory": null, "set_agent_name": null, "set_voice_sensitivity": null, "add_ignored_noise": null}\n\n'
            "ROUTING RULES:\n"
            f"{mem_json_rule}"
            + (
                "- Live Source Code Inspection (`{ } Code` is ON): Matched Fairybread Python source implementation bodies and symbol maps are included above (NOT just headers). If the user is asking you to look at, explain, or talk through the code, answer directly right now using `action=\"chat\"` based on the real code above! Only use `action=\"delegate\"` if they want a full multi-AI audit or code edits/patches.\n"
                if code_ctx
                else ""
            )
            + f"- Microphone / Interruption Sensitivity & Noise Filter (Current sensitivity: {cur_sens}%): If the user asks to lower/raise sensitivity so their noises don't cut you off, or to ignore 'ums', 'ahs', or specific sounds, keep `action=\"chat\"` and set optional `\"set_voice_sensitivity\": {{\"level\": 20, \"ignore_fillers\": true}}` (and/or `\"add_ignored_noise\": \"phrase\"`) in the JSON (or include `[SET_VOICE_SENSITIVITY level=\"20\" ignore_fillers=\"true\"]` in `spoken_reply`) and confirm naturally out loud.\n"
            + f"- Custom AI Name: If the user gives you (or another AI) a name to go by (e.g. 'call yourself Ash' or 'your name is Max'), set optional "
            f'`"set_agent_name": {{"provider": "{eff_prov or "auto"}", "name": "NewName"}}` in the JSON (keeping `action="chat"`) and adopt it naturally in `spoken_reply`.\n'
            "1. 'chat': Casual talk, debate, roleplay, follow-up banter, quick questions, memory recalls/saves, brainstorming, or simple explanations you can answer directly right now (even if the background crew is BUSY).\n"
            "2. 'delegate': Complex or heavy work suited to Fairybread's multi-AI team — generating/drawing images, editing/debugging/patching code, deep research, multi-AI comparisons, reading files/emails. "
            "Put a clean self-contained prompt in 'delegated_task', and in 'spoken_reply' give a warm 1-2 sentence handoff letting them know the team started in the background (or queued it if already busy) and they can keep talking with you.\n"
            "3. 'steer': ONLY when BACKGROUND CREW STATUS is BUSY and the user is adjusting, redirecting, or adding constraints to the currently running background task. Put the instruction in 'steer_note' and confirm warmly in 'spoken_reply'.\n"
            "4. 'status': ONLY when BACKGROUND CREW STATUS is BUSY and the user asks how the background work is going. Summarize the live phase naturally in 'spoken_reply'.\n"
            "SPOKEN STYLE RULES:\n"
            "- Keep 'spoken_reply' to 1-3 natural conversational sentences (warm everyday phrasing, contractions okay).\n"
            "- Engage directly with the active subject and follow genuine topic shifts, jokes, and side tangents naturally; never reply with robotic customer-service stall phrases.\n"
            "- ZERO markdown, ZERO asterisks, ZERO bullet lists, ZERO URLs, ZERO code blocks, and ZERO [bracket tags] in 'spoken_reply'."
        )

        try:
            raw_out, pname, m_used, req_p, fell_back, fb_reason = self._invoke_fast_llm_detailed(
                prompt,
                talk_only=False,
                preferred_provider=preferred_provider,
                fallback_provider=fallback_provider,
                model_override=model_override,
                system_prompt=system_prompt,
                history_messages=structured_hist,
                low_latency=(not bool(code_ctx)),
            )
        except Exception as exc:
            dec = self._fallback_decision(
                utterance,
                background_busy=background_busy,
                background_status=background_status,
                background_question=background_question,
            )
            dec.requested_provider = preferred_provider or self._last_requested_provider
            dec.fell_back = True
            dec.fallback_reason = str(exc)
            dec.speaker_name = eff_speaker
            dec.persona_id = eff_pid
            dec.voice_name = eff_voice
            dec.avatar_shape = eff_shape
            dec.avatar_palette = eff_palette
            dec.slot_index = slot_index
            dec.evolve_user_profile = eff_evolve
            if record_history:
                self._remember(utterance, dec.spoken_reply)
            return dec

        obj = _extract_json_obj(raw_out)
        if not obj:
            stripped_raw, parsed_raw_saves = parse_save_memory_tags(raw_out, replace_with_badge=False)
            stripped_raw, raw_name_tags = parse_set_agent_name_tags(stripped_raw)
            stripped_raw, raw_sens_tags, raw_noise_tags = parse_voice_sensitivity_and_noise_tags(stripped_raw)
            stripped_raw, raw_tier_tags = parse_set_model_tier_tags(stripped_raw)
            applied_raw_names = self._persist_agent_name_updates(
                raw_name_tags,
                default_provider=(pname if pname and pname != "fallback" else eff_prov),
            )
            applied_raw_voice_cfg = self._persist_voice_sensitivity_and_noise_updates(raw_sens_tags, raw_noise_tags)
            if raw_tier_tags:
                from voice_service import save_voice_settings
                for t_upd in raw_tier_tags:
                    if "voice_model_override" not in t_upd:
                        t_upd["voice_model_override"] = ""
                    save_voice_settings(t_upd, config_path=self.config_path)
                    applied_raw_voice_cfg.update(t_upd)
            for item in applied_raw_names:
                if item.get("provider") in {eff_prov, pname}:
                    eff_speaker = item["given_name"]
            cleaned = clean_text_for_speech(stripped_raw)
            spoken = _strip_stall_closers(cleaned, self._recent_closers) or cleaned
            if not spoken and not applied_raw_names and not applied_raw_voice_cfg:
                dec = self._fallback_decision(
                    utterance,
                    background_busy=background_busy,
                    background_status=background_status,
                    background_question=background_question,
                )
                dec.requested_provider = req_p
                dec.fell_back = True
                dec.fallback_reason = fb_reason or "Empty non-JSON reply"
                dec.speaker_name = eff_speaker
                dec.persona_id = eff_pid
                dec.voice_name = eff_voice
                dec.avatar_shape = eff_shape
                dec.avatar_palette = eff_palette
                dec.slot_index = slot_index
                dec.evolve_user_profile = eff_evolve
            else:
                dec = VoiceCompanionDecision(
                    action="chat",
                    spoken_reply=spoken or (
                        f"Got it, you can call me {eff_speaker}."
                        if applied_raw_names
                        else "I've updated your microphone interruption sensitivity and noise filter."
                    ),
                    provider_used=pname,
                    model_used=m_used,
                    requested_provider=req_p,
                    fell_back=fell_back,
                    fallback_reason=fb_reason,
                    memory_saves=parsed_raw_saves if allow_memory_write else [],
                    speaker_name=eff_speaker,
                    persona_id=eff_pid,
                    voice_name=eff_voice,
                    avatar_shape=eff_shape,
                    avatar_palette=eff_palette,
                    slot_index=slot_index,
                    evolve_user_profile=eff_evolve,
                    updated_attributions=applied_raw_names,
                    updated_voice_settings=applied_raw_voice_cfg,
                )
            if record_history:
                self._remember(utterance, f"{eff_speaker}: {dec.spoken_reply}")
            return dec

        action = str(obj.get("action") or "chat").strip().lower()
        if action not in {"chat", "delegate", "steer", "status"}:
            action = "chat"
        raw_reply_field = str(obj.get("spoken_reply") or "")
        stripped_reply, tag_saves = parse_save_memory_tags(raw_reply_field, replace_with_badge=False)
        stripped_reply, reply_name_tags = parse_set_agent_name_tags(stripped_reply)
        stripped_reply, reply_sens_tags, reply_noise_tags = parse_voice_sensitivity_and_noise_tags(stripped_reply)
        stripped_reply, reply_tier_tags = parse_set_model_tier_tags(stripped_reply)
        json_sens_updates: list[dict[str, Any]] = list(reply_sens_tags)
        json_noise_updates: list[str] = list(reply_noise_tags)
        raw_svs = obj.get("set_voice_sensitivity")
        if isinstance(raw_svs, dict):
            upd_s: dict[str, Any] = {}
            raw_l = raw_svs.get("level") if "level" in raw_svs else raw_svs.get("sensitivity")
            if raw_l is not None:
                try:
                    upd_s["interruption_sensitivity"] = max(0, min(100, int(float(str(raw_l).rstrip("%")))))
                except (TypeError, ValueError):
                    pass
            if "barge_in" in raw_svs and raw_svs["barge_in"] is not None:
                upd_s["barge_in_enabled"] = bool(raw_svs["barge_in"])
            if "ignore_fillers" in raw_svs and raw_svs["ignore_fillers"] is not None:
                upd_s["ignore_vocal_noises"] = bool(raw_svs["ignore_fillers"])
            if "silence_ms" in raw_svs and raw_svs["silence_ms"] is not None:
                try:
                    upd_s["silence_timeout_ms"] = max(800, min(3000, int(float(raw_svs["silence_ms"]))))
                except (TypeError, ValueError):
                    pass
            if upd_s:
                json_sens_updates.append(upd_s)
        elif isinstance(raw_svs, (int, float)):
            json_sens_updates.append({"interruption_sensitivity": max(0, min(100, int(raw_svs)))})
        raw_ain = obj.get("add_ignored_noise")
        if isinstance(raw_ain, str) and raw_ain.strip():
            json_noise_updates.append(raw_ain.strip())
        elif isinstance(raw_ain, list):
            for x_n in raw_ain:
                if str(x_n or "").strip():
                    json_noise_updates.append(str(x_n).strip())
        applied_json_voice_cfg = self._persist_voice_sensitivity_and_noise_updates(json_sens_updates, json_noise_updates)
        raw_smt = obj.get("set_model_tier")
        if isinstance(raw_smt, dict):
            _, p_t = parse_set_model_tier_tags(
                f'[SET_MODEL_TIER tier="{raw_smt.get("tier", "")}" provider="{raw_smt.get("provider", "")}" model="{raw_smt.get("model", "")}"]'
            )
            reply_tier_tags.extend(p_t)
        elif isinstance(raw_smt, str) and raw_smt.strip():
            _, p_t = parse_set_model_tier_tags(f'[SET_MODEL_TIER tier="{raw_smt.strip()}"]')
            reply_tier_tags.extend(p_t)
        if reply_tier_tags:
            from voice_service import save_voice_settings
            for t_upd in reply_tier_tags:
                if "voice_model_override" not in t_upd:
                    t_upd["voice_model_override"] = ""
                save_voice_settings(t_upd, config_path=self.config_path)
                applied_json_voice_cfg.update(t_upd)

        json_name_updates: list[dict[str, str]] = list(reply_name_tags)
        raw_sn = obj.get("set_agent_name")
        sn_items = raw_sn if isinstance(raw_sn, list) else ([raw_sn] if isinstance(raw_sn, dict) else [])
        for sn in sn_items:
            if isinstance(sn, dict):
                nm_v = clean_given_name(str(sn.get("name") or sn.get("given_name") or ""))
                pr_v = str(sn.get("provider") or pname or eff_prov or "").strip().lower()
                if nm_v and pr_v and pr_v != "auto":
                    json_name_updates.append({"provider": pr_v, "given_name": nm_v})
        applied_json_names = self._persist_agent_name_updates(
            json_name_updates,
            default_provider=(pname if pname and pname != "fallback" else eff_prov),
        )
        for item in applied_json_names:
            if item.get("provider") in {eff_prov, pname}:
                eff_speaker = item["given_name"]
        cleaned_reply = clean_text_for_speech(stripped_reply)
        spoken = _strip_stall_closers(cleaned_reply, self._recent_closers) or cleaned_reply
        delegated_task = str(obj.get("delegated_task") or "").strip()
        steer_note = str(obj.get("steer_note") or "").strip()

        collected_saves: list[dict[str, str]] = []
        if allow_memory_write:
            raw_sm = obj.get("save_memory")
            sm_items = raw_sm if isinstance(raw_sm, list) else ([raw_sm] if isinstance(raw_sm, dict) else [])
            for sm in sm_items:
                if not isinstance(sm, dict):
                    continue
                fact_v = str(sm.get("fact") or sm.get("body") or sm.get("content") or sm.get("summary") or "").strip()
                sum_v = str(sm.get("summary") or "").strip() or (fact_v[:97] + "..." if len(fact_v) > 100 else fact_v)
                if sum_v and fact_v:
                    collected_saves.append({
                        "summary": sum_v[:140],
                        "fact": fact_v,
                        "project": str(sm.get("project") or "").strip(),
                        "memory_type": str(sm.get("memory_type") or "standing").strip().lower() or "standing",
                    })
            collected_saves.extend(tag_saves)

        if action == "steer" and not background_busy:
            action = "delegate"
            delegated_task = steer_note or delegated_task or utterance
            steer_note = ""
        elif action == "status" and not background_busy:
            action = "chat"

        if action == "delegate" and not delegated_task:
            delegated_task = utterance
        if action == "steer" and not steer_note:
            steer_note = utterance

        if not spoken:
            if action == "delegate":
                spoken = "On it — I've passed that to the AI team in the background. Keep talking with me while they handle it."
            elif action == "steer":
                spoken = "Got it, I sent that update over to the AIs working in the background."
            elif action == "status":
                spoken = background_status or "The team is still working through that task right now."
            elif collected_saves:
                spoken = "Saved that to your Memory Palace."
            else:
                spoken = "Gotcha."

        dec = VoiceCompanionDecision(
            action=action,
            spoken_reply=spoken,
            delegated_task=delegated_task if action == "delegate" else "",
            steer_note=steer_note if action == "steer" else "",
            provider_used=pname,
            model_used=m_used,
            requested_provider=req_p,
            fell_back=fell_back,
            fallback_reason=fb_reason,
            memory_saves=collected_saves,
            speaker_name=eff_speaker,
            persona_id=eff_pid,
            voice_name=eff_voice,
            avatar_shape=eff_shape,
            avatar_palette=eff_palette,
            slot_index=slot_index,
            evolve_user_profile=eff_evolve,
            updated_attributions=applied_json_names,
            updated_voice_settings=applied_json_voice_cfg,
        )
        if record_history:
            self._remember(utterance, f"{eff_speaker}: {dec.spoken_reply}")
        return dec

    def respond_quorum(
        self,
        user_utterance: str,
        *,
        background_busy: bool = False,
        background_status: str = "",
        background_question: str = "",
        recent_chat_snippet: str = "",
        talk_only: bool = False,
        memory_context: str = "",
        allow_memory_write: bool = True,
        preferred_provider: str = "",
        fallback_provider: str = "",
        cast_slots: list[dict] | None = None,
        multi_ai_enabled: bool | None = None,
        max_volleys: int | None = None,
        living_profile_text: str = "",
        include_palace_code: bool = False,
    ) -> list[VoiceCompanionDecision]:
        """Run a 1-AI Roleplay turn or a 2-4 AI Table Quorum volley with peer reactions and anti-loop brake."""
        utterance = (user_utterance or "").strip()
        try:
            v_cfg = load_voice_settings(self.config_path)
            personas = load_voice_personas(self.config_path)
        except Exception:
            v_cfg = {}
            personas = {}

        multi_on = bool(v_cfg.get("multi_ai_voice_enabled", False) if multi_ai_enabled is None else multi_ai_enabled)
        raw_volleys = v_cfg.get("multi_ai_max_volleys", 3) if max_volleys is None else max_volleys
        try:
            volley_cap = max(1, min(6, int(raw_volleys or 3)))
        except (TypeError, ValueError):
            volley_cap = 3

        raw_slots = list(cast_slots if cast_slots is not None else (v_cfg.get("voice_cast_slots") or []))
        if not raw_slots:
            raw_slots = [{"slot": 1, "provider": preferred_provider or "auto", "persona_id": v_cfg.get("active_voice_persona", "normal_female")}]

        _preset_placeholders = {"maya", "liam", "chloe", "ethan", "elena", "jack", "marcus", "seat 1", "seat 2", "seat 3", "seat 4"}
        active_slots: list[dict] = []
        for idx, raw_s in enumerate(raw_slots[:4]):
            if not isinstance(raw_s, dict):
                continue
            prov = str(raw_s.get("provider") or "").strip().lower()
            if idx == 0 and not prov:
                prov = preferred_provider or str(v_cfg.get("voice_llm_provider") or "auto").strip().lower() or "auto"
            if idx > 0 and (not multi_on or not prov or prov in {"none", "off", "blank"}):
                continue
            eff_prov = preferred_provider if (idx == 0 and preferred_provider) else prov
            if eff_prov == "auto":
                try:
                    cands = self._build_provider_candidates(preferred_provider=eff_prov, fallback_provider=fallback_provider)
                    if cands:
                        eff_prov = str(cands[0][0] or "").strip().lower()
                except Exception:
                    pass
            try:
                p_attr = (
                    get_provider_attribution(eff_prov, config_path=self.config_path)
                    if eff_prov and eff_prov != "auto"
                    else {}
                )
            except Exception:
                p_attr = {}
            pid = str(raw_s.get("persona_id") or p_attr.get("conversational_mode") or ("default" if idx == 0 else "the_friend")).strip()
            if idx == 0 and v_cfg.get("active_voice_persona") and not cast_slots:
                pid = str(raw_s.get("persona_id") or v_cfg.get("active_voice_persona") or "normal_female").strip()
            p_meta = personas.get(pid) or personas.get("default") or personas.get("normal_female") or {}
            custom_given = clean_given_name(str(p_attr.get("given_name") or ""))
            raw_sp = str(raw_s.get("speaker_name") or "").strip()
            if custom_given and (not raw_sp or raw_sp.lower() in _preset_placeholders or cast_slots is None):
                sp_name = custom_given
            else:
                sp_name = raw_sp or custom_given or str(p_meta.get("speaker_name") or p_attr.get("display_name") or f"Seat {idx + 1}").strip()
            v_name = str(raw_s.get("voice_name") or p_attr.get("voice_name") or ((p_meta.get("voice_hints") or {}).get("openai")) or "coral").strip()
            sh = str(raw_s.get("avatar_shape") or p_attr.get("avatar_shape") or p_meta.get("avatar_shape") or "neural_core").strip()
            pal = str(raw_s.get("avatar_palette") or p_attr.get("avatar_palette") or p_meta.get("avatar_palette") or "tulsa_cyan").strip()
            raw_bp = str(p_meta.get("blueprint") or "").strip()
            preset_sp = str(p_meta.get("speaker_name") or "").strip()
            clean_bp = (
                _strip_preset_identity_prefix(raw_bp)
                if (sp_name and preset_sp and sp_name.lower() != preset_sp.lower())
                else raw_bp
            )
            active_slots.append({
                "slot_index": idx,
                "provider": preferred_provider if (idx == 0 and preferred_provider) else prov,
                "resolved_provider": eff_prov,
                "model": str(raw_s.get("model") or p_attr.get("model") or "").strip(),
                "persona_id": pid,
                "speaker_name": sp_name,
                "voice_name": v_name,
                "avatar_shape": sh,
                "avatar_palette": pal,
                "blueprint": clean_bp,
                "role_attribution": str(p_attr.get("role_attribution") or "").strip(),
                "label": str(p_meta.get("label") or sp_name).strip(),
                "evolve_user_profile": bool(p_meta.get("evolve_user_profile", True)),
            })

        if not active_slots:
            single = self.respond(
                utterance,
                background_busy=background_busy,
                background_status=background_status,
                background_question=background_question,
                recent_chat_snippet=recent_chat_snippet,
                talk_only=talk_only,
                memory_context=memory_context,
                allow_memory_write=allow_memory_write,
                preferred_provider=preferred_provider,
                fallback_provider=fallback_provider,
                living_profile_text=living_profile_text,
                include_palace_code=include_palace_code,
            )
            return [single]

        if not multi_on or len(active_slots) <= 1:
            s0 = active_slots[0]
            single = self.respond(
                utterance,
                background_busy=background_busy,
                background_status=background_status,
                background_question=background_question,
                recent_chat_snippet=recent_chat_snippet,
                talk_only=talk_only,
                memory_context=memory_context,
                allow_memory_write=allow_memory_write,
                preferred_provider=s0["provider"],
                fallback_provider=fallback_provider,
                model_override=s0["model"],
                persona_id=s0["persona_id"],
                speaker_name=s0["speaker_name"],
                voice_name=s0["voice_name"],
                avatar_shape=s0["avatar_shape"],
                avatar_palette=s0["avatar_palette"],
                slot_index=s0["slot_index"],
                living_profile_text=living_profile_text,
                include_palace_code=include_palace_code,
            )
            return [single]

        # Prioritize a directly addressed speaker name if mentioned in the user's utterance
        ordered_slots = list(active_slots)
        u_low = utterance.lower()
        for pos, sl in enumerate(ordered_slots):
            nm_low = sl["speaker_name"].lower()
            if nm_low and re.search(rf"\b{re.escape(nm_low)}\b", u_low):
                if pos != 0:
                    ordered_slots.insert(0, ordered_slots.pop(pos))
                break

        roster_lines = [
            f"- {sl['speaker_name']} ({sl['label']})"
            for sl in active_slots
        ]
        quorum_roster_txt = (
            "TABLE QUORUM SEATS (you are sitting around a table with the human user and these peers):\n"
            + "\n".join(roster_lines)
            + "\n- Keep your spoken beat punchy (1-2 natural conversational sentences) so the table flows like real human conversation."
        )

        lead = ordered_slots[0]
        beat1 = self.respond(
            utterance,
            background_busy=background_busy,
            background_status=background_status,
            background_question=background_question,
            recent_chat_snippet=recent_chat_snippet,
            talk_only=talk_only,
            memory_context=memory_context,
            allow_memory_write=allow_memory_write,
            preferred_provider=lead["provider"],
            fallback_provider=fallback_provider,
            model_override=lead["model"],
            persona_id=lead["persona_id"],
            speaker_name=lead["speaker_name"],
            voice_name=lead["voice_name"],
            avatar_shape=lead["avatar_shape"],
            avatar_palette=lead["avatar_palette"],
            slot_index=lead["slot_index"],
            record_history=False,
            living_profile_text=living_profile_text,
            extra_quorum_context=quorum_roster_txt,
            include_palace_code=include_palace_code,
        )

        beats: list[VoiceCompanionDecision] = [beat1]
        if beat1.action != "chat" or beat1.provider_used == "fallback" or volley_cap <= 1:
            self._remember(utterance, f"{beat1.speaker_name}: {beat1.spoken_reply}")
            return beats

        living_profile = self._load_living_profile_block(living_profile_text)
        topic_lock = _detect_active_topic_hint(utterance, self._history)
        structured_hist = self._structured_history_messages()

        # Candidate order for follow-up beats: other seats first, plus optional lead comeback if challenged
        peer_queue = list(ordered_slots[1:])
        if len(ordered_slots) >= 2 and volley_cap >= 3:
            peer_queue.append(lead)

        for cand in peer_queue:
            if len(beats) >= volley_cap:
                break
            # Avoid the same speaker talking twice in a row
            if cand["slot_index"] == beats[-1].slot_index:
                continue

            beats_transcript = "\n".join(
                f"{b.speaker_name}: {b.spoken_reply}"
                for b in beats
            )
            peer_names = ", ".join(sl["speaker_name"] for sl in active_slots if sl["slot_index"] != cand["slot_index"])
            peer_role = f"AGENT ROLE & ATTRIBUTION:\n{cand['role_attribution']}\n\n" if cand.get("role_attribution") else ""
            peer_prov_id = str(cand.get("resolved_provider") or cand.get("provider") or "auto").strip().lower()
            sys_peer = (
                f"You are {cand['speaker_name']} ({cand['label']}) running on provider {peer_prov_id} at a live spoken group table with the human user and peers: {peer_names}.\n"
                f"AGENT IDENTITY RULE: Your assigned Fairybread name is '{cand['speaker_name']}'. Always answer to '{cand['speaker_name']}' naturally.\n"
                f"{peer_role}"
                f"{cand['blueprint']}\n\n"
                + (f"LIVING USER PROFILE:\n{living_profile}\n\n" if living_profile else "")
                + f"{VOICE_ANTI_STALL_RULES}\n"
                "PEER QUORUM RULES:\n"
                "- Do NOT act like a butler answering the user from scratch.\n"
                "- React directly to what the previous speaker(s) just said at the table — address them by name, push back, sharpen the idea, or drop a quick witty reaction.\n"
                "- Keep it to 1-2 short, natural spoken sentences (under ~35 words).\n"
                "- Stay anchored to the human user's active topic.\n"
                "- If the previous speakers already covered the point well and your persona has nothing genuinely distinct or contrarian to add, output ONLY: [PASS]"
            )
            peer_prompt = (
                (f"ACTIVE TOPIC LOCK: {topic_lock}\n" if topic_lock else "")
                + f"HUMAN USER SAID: {utterance}\n\n"
                + f"SPOKEN SO FAR AT THE TABLE:\n{beats_transcript}\n\n"
                + f"Now speak as {cand['speaker_name']} (or output [PASS] to stay quiet). Plain spoken text only — zero JSON, zero markdown."
            )
            fb_mode = fallback_provider if (cand["provider"] == "auto" or self._injected_llm is not None) else "none"
            try:
                raw_peer, p_used, m_used, req_p, fell_back, fb_reason = self._invoke_fast_llm_detailed(
                    peer_prompt,
                    talk_only=True,
                    preferred_provider=cand["provider"],
                    fallback_provider=fb_mode,
                    model_override=cand["model"],
                    system_prompt=sys_peer,
                    history_messages=structured_hist,
                )
            except Exception:
                continue

            if not raw_peer or is_pass_or_defer_text(raw_peer) or "[pass]" in raw_peer.lower():
                continue
            obj_p = _extract_json_obj(raw_peer)
            cand_text = str(obj_p.get("spoken_reply") or raw_peer) if (isinstance(obj_p, dict) and obj_p.get("spoken_reply")) else raw_peer
            cand_text, peer_saves = parse_save_memory_tags(cand_text, replace_with_badge=False)
            cand_text, peer_name_tags = parse_set_agent_name_tags(cand_text)
            applied_peer_names = self._persist_agent_name_updates(
                peer_name_tags,
                default_provider=(p_used if p_used and p_used != "fallback" else peer_prov_id),
            )
            peer_speaker = cand["speaker_name"]
            for item in applied_peer_names:
                if item.get("provider") in {peer_prov_id, p_used}:
                    peer_speaker = item["given_name"]
            # Strip accidental leading speaker label like "Marcus: ..."
            cand_text = re.sub(rf"^{re.escape(peer_speaker)}\s*:\s*", "", cand_text.strip(), flags=re.IGNORECASE)
            cleaned_p = clean_text_for_speech(cand_text)
            spoken_p = _strip_stall_closers(cleaned_p, self._recent_closers) or cleaned_p
            if (not spoken_p or len(spoken_p) < 3) and not applied_peer_names:
                continue
            if not spoken_p and applied_peer_names:
                spoken_p = f"Got it, call me {peer_speaker}."

            beats.append(
                VoiceCompanionDecision(
                    action="chat",
                    spoken_reply=spoken_p,
                    provider_used=p_used,
                    model_used=m_used,
                    requested_provider=req_p,
                    fell_back=fell_back,
                    fallback_reason=fb_reason,
                    memory_saves=peer_saves if allow_memory_write else [],
                    speaker_name=peer_speaker,
                    persona_id=cand["persona_id"],
                    voice_name=cand["voice_name"],
                    avatar_shape=cand["avatar_shape"],
                    avatar_palette=cand["avatar_palette"],
                    slot_index=cand["slot_index"],
                    evolve_user_profile=cand["evolve_user_profile"],
                    updated_attributions=applied_peer_names,
                )
            )

        self._remember(
            utterance,
            "\n".join(f"{b.speaker_name}: {b.spoken_reply}" for b in beats),
        )
        return beats

    def summarize_completed_work(
        self,
        original_question: str,
        final_answer: str,
        *,
        contributors: list[str] | None = None,
    ) -> str:
        raw_ans = final_answer or ""
        has_images = "[GENERATE_IMAGE" in raw_ans.upper()
        has_autopatch = ("AUTOPATCH" in raw_ans.upper()) or ("[IDLE_PATCH" in raw_ans.upper())
        cleaned_ans = clean_text_for_speech(raw_ans)
        if not cleaned_ans:
            if has_images:
                return "Your generated images are up on screen now. Want me to tweak anything?"
            return "The AI team finished up and posted the result on screen."

        prompt = (
            "You are Fairybread's Voice Companion giving a quick spoken update because a background AI task just finished.\n"
            f"Original request: {(original_question or '')[:260]}\n"
            f"Contributors: {', '.join(contributors or []) or 'AI team'}\n"
            f"Generated images included: {'yes' if has_images else 'no'}\n"
            f"Code patch applied: {'yes' if has_autopatch else 'no'}\n"
            f"Completed output excerpt:\n{cleaned_ans[:1800]}\n\n"
            "Write a natural, warm spoken summary in 2-3 short conversational sentences (under 360 characters).\n"
            "Tell the user what finished and the key takeaway. If images were rendered, mention they're up on screen. "
            "Do NOT read code, tables, URLs, file paths, or markdown symbols aloud."
        )
        try:
            summary_raw, _ = self._invoke_fast_llm(prompt)
            spoken = clean_text_for_speech(summary_raw)
            if spoken:
                return spoken[:420]
        except Exception:
            pass

        # Fast local fallback: take first 1-2 clean sentences <= 300 chars
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned_ans) if s.strip()]
        out = ""
        for s in sents:
            cand = f"{out} {s}".strip()
            if len(cand) > 300 and out:
                break
            out = cand
            if len(out) >= 180:
                break
        if not out:
            out = cleaned_ans[:280].rsplit(" ", 1)[0].strip() + "."
        if has_images and "image" not in out.lower() and "screen" not in out.lower():
            out = f"Your images are up on screen now. {out}"[:360]
        self._remember(f"[Background completed: {original_question[:80]}]", out)
        return out
