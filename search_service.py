"""3-Tier Hybrid & Sharded Web Search Engine for Fairybread (Default Light, Moderate /msearch, Deep /deepsearch)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import math
import re
import time
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse, request as urllib_request
from xml.etree import ElementTree as ET


SEARCH_DEPTH_CHOICES: list[tuple[str, str]] = [
    ("Default (Light — /search)", "default"),
    ("Moderate (/searchm)", "moderate"),
    ("Deep (/searchd)", "deep"),
]

_SLASH_SEARCH_RE = re.compile(
    r"^\s*/(searchd|deepsearch|deep|ds|searchm|msearch|ms|research|search|s|quick)\b\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)

_INLINE_COMMAND_RE = re.compile(
    r"(?:^|(?<=\s))/(autopatch|auto-patch|authpatch|code|tangent|fullrender|single|searchd|deepsearch|searchm|msearch|search)(?=\b|\s|$|[.,!?;:])",
    re.IGNORECASE,
)

_RESTORE_COMMAND_RE = re.compile(
    r"(?:^|(?<=\s))/restore(?:\s+(list|pin\s+v?\d+|v\d{1,4}|previous|prev|golden|baseline))?(?=\b|\s|$|[.,!?;:])",
    re.IGNORECASE,
)

_NATURAL_DEEP_SEARCH_RE = re.compile(
    r"\b(?:do\s+a\s+deep\s+search|deep\s+search|exhaustive\s+web\s+search|search\s+all\s+sites)\b",
    re.IGNORECASE,
)

_NATURAL_MOD_SEARCH_RE = re.compile(
    r"\b(?:do\s+a\s+moderate\s+search|moderate\s+search|search\s+the\s+web\s+for|search\s+online\s+for|look\s+up\s+online)\b",
    re.IGNORECASE,
)

_WEATHER_QUERY_RE = re.compile(
    r"\b(?:"
    r"weather|forecast|temperature|temp\b|temps|rain(?:fall|ing)?|humidity|"
    r"uv\s+index|wind\s+speed|bom\.gov|radar|storm(?:s|y)?|hail|thunderstorm|heatwave|muggy|freezing|outside\s+today"
    r")\b",
    re.IGNORECASE,
)

_AUTO_REALTIME_RE = re.compile(
    r"\b(?:"
    r"weather|forecast|temperature|rainfall|"
    r"latest\s+news|current\s+(?:price|rate|news|events|score|standings|weather|forecast)|"
    r"today'?s\s+(?:weather|forecast|news|score|price)|"
    r"right\s+now|what\s+is\s+the\s+(?:weather|temperature|exchange\s+rate|stock\s+price)"
    r")\b",
    re.IGNORECASE,
)

_NATURAL_AUTOPATCH_RE = re.compile(
    r"\b(?:"
    r"autopatch|authpatch|auto[\s-]+patch(?:es|ing)?|"
    r"(?:apply|deploy|push|run|execute)\s+(?:the\s+|this\s+|staged\s+|experimental\s+mode\s+)?patch(?:es)?|"
    r"deploy\s+and\s+(?:auto[\s-]?patch|authpatch|patch)|"
    r"apply\s+for\s+real|self[\s-]+deploy|self[\s-]+patch"
    r")\b",
    re.IGNORECASE,
)

_TERSE_CONFIRM_RE = re.compile(
    r"^\s*(?:apply|proceed|go(?:\s+ahead)?|do\s+it|deploy|yes|ok|approved?)\b",
    re.IGNORECASE,
)

_ORGANIC_AUTO_APPROVE_RE = re.compile(
    r"\b(?:"
    r"no\s+need\s+to\s+ask(?:\s+for)?(?:\s+my)?\s+approval|"
    r"don'?t\s+(?:need\s+to\s+)?ask(?:\s+for)?(?:\s+my)?\s+approval|"
    r"without\s+asking(?:\s+for)?\s+approval|"
    r"no\s+approval\s+(?:needed|required)|"
    r"(?:you\s+have|got)\s+(?:my\s+|the\s+)?(?:green\s+light|approval|go[- ]ahead)|"
    r"pre-?approved|"
    r"just\s+(?:do|fix|patch|apply|deploy|update|change|ship|run)\s+(?:it|them|this|that|everything|all(?:\s+of\s+(?:it|them|three))?)|"
    r"go\s+ahead\s+and\s+(?:fix|patch|apply|deploy|update|change|make|run|do)|"
    r"(?:handle|take\s+care\s+of)\s+(?:it|this|everything)\s+yourself|"
    r"do\s+(?:it|this)\s+yourself|"
    r"run\s+all\s+(?:three|of\s+(?:them|these|those))|"
    r"make\s+(?:those|these|the)\s+changes|"
    r"(?:put|push)\s+(?:it|this|them)\s+live"
    r")\b",
    re.IGNORECASE,
)

_FAIRYBREAD_SELF_TARGET_RE = re.compile(
    r"\b(?:"
    r"fairybread|palace|this\s+app|control\s+panel|settings\s+(?:tab|page|panel|dialog)|"
    r"autopatch|authpatch|image\s+(?:pipeline|renderer|engine)|graphics\s+engine|"
    r"orchestrator|synthesizer|dispatcher|provider_loader|palace_gui|palace_theme|"
    r"palace_config|idle_service|search_service|memory_service|context_service|attachment_service"
    r")\b",
    re.IGNORECASE,
)

_CODE_MODIFY_VERB_RE = re.compile(
    r"\b(?:fix|patch|update|change|add|remove|optimize|optimise|upgrade|improve|wire|implement|deploy|apply|refactor|enable|disable|build|make)\b",
    re.IGNORECASE,
)

_ORGANIC_DETAIL_CONCISE_RE = re.compile(
    r"\b(?:keep\s+it\s+(?:short|brief|concise)|short\s+answer|briefly|tl;?dr|one[- ]liner|quick\s+summary)\b",
    re.IGNORECASE,
)

_ORGANIC_DETAIL_HIGH_RE = re.compile(
    r"\b(?:in\s+full\s+detail|full\s+detail|deep\s+dive|explain\s+thoroughly|walk\s+me\s+through\s+everything)\b",
    re.IGNORECASE,
)


_READ_ONLY_ADVISORY_RE = re.compile(
    r"\b(?:"
    r"read[- ]only|advisory(?:\s+review)?|review\s+only|audit\s+only|report\s+only|"
    r"do\s+not\s+(?:edit|modify|patch|change|write)|don'?t\s+(?:edit|modify|patch|change|write)|"
    r"plan\s+first|without\s+editing"
    r")\b",
    re.IGNORECASE,
)


def detect_organic_turn_intents(text: str) -> dict[str, Any]:
    """Infer natural-language authorization, Fairybread self-modification intent, and detail preference."""
    raw = (text or "").strip()
    if not raw:
        return {"auto_approved": False, "self_code_change_intent": False, "output_detail_override": ""}
    att_marker = "\n\nATTACHED FILE EXCERPTS (user-provided reference material):"
    clean = raw.split(att_marker, 1)[0].strip()
    explicit_slash_autopatch = bool(re.search(r"(?:^|\s)/aut(?:o-?patch|hpatch)\b", clean, re.IGNORECASE))
    is_read_only_request = bool(_READ_ONLY_ADVISORY_RE.search(clean)) and not explicit_slash_autopatch
    auto_approved = False if is_read_only_request else bool(_ORGANIC_AUTO_APPROVE_RE.search(clean))
    self_code_change_intent = (
        False
        if is_read_only_request
        else bool(_FAIRYBREAD_SELF_TARGET_RE.search(clean) and _CODE_MODIFY_VERB_RE.search(clean))
    )
    if _ORGANIC_DETAIL_CONCISE_RE.search(clean):
        detail_ov = "concise"
    elif _ORGANIC_DETAIL_HIGH_RE.search(clean):
        detail_ov = "high"
    else:
        detail_ov = ""
    return {
        "auto_approved": auto_approved,
        "self_code_change_intent": self_code_change_intent,
        "output_detail_override": detail_ov,
    }


_NON_PATCH_ACTION_RE = re.compile(
    r"\b(?:"
    r"draw|paint|sketch|render|full\s*render|illustrat\w*|generate\s+(?:an?\s+)?image|"
    r"image|picture|photo|photograph|banner|wallpaper|weather|forecast|joke|humou?r|"
    r"search\s+(?:the\s+web|online|google)|write\s+(?:a|the)\s+(?:prompt|paragraph|essay|story)"
    r")\b",
    re.IGNORECASE,
)


def is_terse_patch_confirmation(text: str) -> bool:
    """Return True if the user message is a short confirmation synonym (Apply, Proceed, Go, Yes, OK) without non-patch action verbs."""
    clean = (text or "").strip()
    if not clean or len(clean) > 64:
        return False
    if _NON_PATCH_ACTION_RE.search(clean):
        return False
    return bool(_TERSE_CONFIRM_RE.search(clean))



def parse_turn_commands(
    question: str,
    ui_search_depth: str = "default",
) -> dict[str, Any]:
    """Parse inline slash switches (/autopatch, /code, /tangent, /fullrender, /search, /searchm, /searchd)
    anywhere in the user's message (preserving any ATTACHED FILE EXCERPTS tail).
    """
    raw = question or ""
    att_marker = "\n\nATTACHED FILE EXCERPTS (user-provided reference material):"
    if att_marker in raw:
        user_part, att_tail = raw.split(att_marker, 1)
        att_tail = att_marker + att_tail
    else:
        user_part, att_tail = raw, ""

    found_cmds: set[str] = set()
    restore_target = ""
    restore_targets: list[str] = []

    def _strip_restore(m: re.Match) -> str:
        nonlocal restore_target
        found_cmds.add("restore")
        arg = (m.group(1) or "").strip().lower()
        target_val = arg if arg else "previous"
        restore_targets.append(target_val)
        if not restore_target:
            restore_target = target_val
        return ""

    user_part = _RESTORE_COMMAND_RE.sub(_strip_restore, user_part)

    def _strip_cmd(m: re.Match) -> str:
        cmd_tok = m.group(1).lower()
        if cmd_tok in {"auto-patch", "authpatch"}:
            cmd_tok = "autopatch"
        found_cmds.add(cmd_tok)
        return ""

    cleaned_user = _INLINE_COMMAND_RE.sub(_strip_cmd, user_part).strip()
    cleaned_user = re.sub(r"[ \t]{2,}", " ", cleaned_user).strip(" ,;:-")
    if found_cmds:
        cleaned_user = re.sub(
            r"(?:\s+\b(?:and|then|with|to|please|now))+\s*$",
            "",
            cleaned_user,
            flags=re.IGNORECASE,
        ).strip(" ,;:-")
    if not cleaned_user and user_part.strip():
        cleaned_user = user_part.strip()

    autopatch = ("autopatch" in found_cmds) or bool(_NATURAL_AUTOPATCH_RE.search(cleaned_user))
    if autopatch:
        found_cmds.add("autopatch")
    include_code = autopatch or ("code" in found_cmds)
    tangent = "tangent" in found_cmds
    full_render = bool(found_cmds & {"fullrender", "single"})

    if found_cmds & {"searchd", "deepsearch"}:
        resolved_depth = "deep"
    elif found_cmds & {"searchm", "msearch"}:
        resolved_depth = "moderate"
    elif "search" in found_cmds:
        resolved_depth = "light"
    else:
        resolved_depth, cleaned_user = parse_search_command(cleaned_user, ui_search_depth)

    organic = detect_organic_turn_intents(user_part)
    final_q = (cleaned_user + att_tail) if att_tail else cleaned_user
    return {
        "cleaned_question": final_q,
        "search_depth": resolved_depth,
        "autopatch": autopatch,
        "include_code": include_code,
        "tangent": tangent,
        "full_render": full_render,
        "restore_target": restore_target,
        "multiple_restores": len(restore_targets) > 1,
        "commands": sorted(found_cmds),
        "auto_approved": organic["auto_approved"],
        "self_code_change_intent": organic["self_code_change_intent"],
        "output_detail_override": organic["output_detail_override"],
    }


def parse_search_command(
    question: str,
    ui_search_depth: str = "default",
) -> tuple[str, str]:
    """Return (resolved_depth, cleaned_question) where resolved_depth is 'none', 'light', 'moderate', or 'deep'."""
    raw = (question or "").strip()
    if not raw:
        return "none", ""

    m = _SLASH_SEARCH_RE.match(raw)
    if m:
        cmd = m.group(1).lower()
        rest = m.group(2).strip() or raw
        if cmd in {"searchd", "deepsearch", "deep", "ds"}:
            return "deep", rest
        if cmd in {"searchm", "msearch", "ms", "research"}:
            return "moderate", rest
        return "light", rest

    # Check inline /searchd, /searchm, /search anywhere in the text
    inline_m = re.search(r"(?:^|(?<=\s))/(searchd|deepsearch|searchm|msearch|search)\b", raw, re.IGNORECASE)
    if inline_m:
        icmd = inline_m.group(1).lower()
        cleaned = re.sub(r"(?:^|(?<=\s))/(?:searchd|deepsearch|searchm|msearch|search)\b\s*", "", raw, flags=re.IGNORECASE).strip() or raw
        if icmd in {"searchd", "deepsearch"}:
            return "deep", cleaned
        if icmd in {"searchm", "msearch"}:
            return "moderate", cleaned
        return "light", cleaned

    if _NATURAL_DEEP_SEARCH_RE.search(raw):
        return "deep", raw
    if _NATURAL_MOD_SEARCH_RE.search(raw):
        return "moderate", raw

    ui_mode = (ui_search_depth or "default").strip().lower()
    if ui_mode == "deep":
        return "deep", raw
    if ui_mode == "moderate":
        return "moderate", raw
    if ui_mode == "light":
        return "light", raw
    if ui_mode == "default" and (_WEATHER_QUERY_RE.search(raw) or _AUTO_REALTIME_RE.search(raw)):
        return "light", raw

    return "none", raw


@dataclass
class WebSearchHit:
    title: str
    url: str
    snippet: str
    source: str = "web"
    angle: str = "general"
    extracted_body: str = ""


@dataclass
class ShardedSearchBundle:
    depth: str
    base_query: str
    queries_executed: list[str]
    total_hits: int
    pages_fetched: int
    hits: list[WebSearchHit] = field(default_factory=list)
    agent_shards: dict[str, str] = field(default_factory=dict)
    shared_summary: str = ""


def _clean_html_to_text(raw_html: str, max_chars: int = 2400) -> str:
    txt = re.sub(r"<(script|style|nav|header|footer|noscript|svg)\b[^>]*>.*?</\1>", " ", raw_html or "", flags=re.IGNORECASE | re.DOTALL)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) > max_chars:
        txt = txt[:max_chars] + " …"
    return txt


def _get_deepseek_tools_api_key(credential_store=None) -> str:
    """Return stored DeepSeek API key for Search & Fetch tools (skips live vault lookup in offscreen unit tests unless injected)."""
    if credential_store is None and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return ""
    try:
        from credential_store import CredentialStore
        store = credential_store or CredentialStore()
        return (store.get_api_key("deepseek") or "").strip()
    except Exception:
        return ""


def _fetch_deepseek_markdown(
    url: str,
    max_chars: int = 2400,
    timeout: float = 6.5,
    *,
    api_key: str = "",
) -> str:
    """Fetch a webpage as clean Markdown via DeepSeek `POST /v1/tools/fetch` ($0.00075/success)."""
    clean_url = (url or "").strip()
    key = (api_key or "").strip() or _get_deepseek_tools_api_key()
    if not key or not clean_url.startswith(("http://", "https://")) or len(clean_url) > 8192:
        return ""
    try:
        body = json.dumps({"url": clean_url}).encode("utf-8")
        req = urllib_request.Request(
            "https://api.deepseek.com/v1/tools/fetch",
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=max(4.0, float(timeout))) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = str((payload.get("content") if isinstance(payload, dict) else "") or "").strip()
        content = re.sub(r"\s+", " ", content).strip()
        if len(content) > max_chars:
            content = content[:max_chars] + " …"
        return content
    except Exception:
        return ""


def _search_deepseek_api(
    query: str,
    max_results: int = 8,
    angle: str = "general",
    *,
    api_key: str = "",
) -> list[WebSearchHit]:
    """Query DeepSeek `POST /v1/tools/search` ($0.00075/success) for ranked web results."""
    clean_q = (query or "").strip()[:128]
    key = (api_key or "").strip() or _get_deepseek_tools_api_key()
    if not key or not clean_q:
        return []
    hits: list[WebSearchHit] = []
    try:
        body = json.dumps({
            "query": clean_q,
            "count": max(1, min(50, int(max_results or 8))),
            "need_content": False,
        }).encode("utf-8")
        req = urllib_request.Request(
            "https://api.deepseek.com/v1/tools/search",
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=7.5) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        results = (payload.get("results") if isinstance(payload, dict) else None) or []
        for item in results[:max_results]:
            if not isinstance(item, dict):
                continue
            link = str(item.get("url") or "").strip()
            if not link.startswith(("http://", "https://")):
                continue
            title = _clean_html_to_text(str(item.get("title") or link), 160)
            snip_raw = str(item.get("summary") or item.get("snippet") or "")
            snip = _clean_html_to_text(snip_raw, 360)
            hits.append(
                WebSearchHit(
                    title=title or link,
                    url=link,
                    snippet=snip,
                    source="deepseek",
                    angle=angle,
                )
            )
    except Exception:
        pass
    return hits


def fetch_page_clean_text(url: str, max_chars: int = 2400, timeout: float = 6.5) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    extracted = ""
    try:
        req = urllib_request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FairybreadResearch/1.0",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            },
        )
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            ctype = str(resp.headers.get("Content-Type") or "").lower()
            if any(b in ctype for b in ("image/", "video/", "audio/", "application/pdf", "application/zip")):
                return ""
            raw_bytes = resp.read(160_000)
            decoded = raw_bytes.decode("utf-8", errors="replace")
            extracted = _clean_html_to_text(decoded, max_chars=max_chars)
    except Exception:
        extracted = ""
    if len(extracted) >= 80:
        return extracted
    ds_md = _fetch_deepseek_markdown(url, max_chars=max_chars, timeout=timeout)
    return ds_md or extracted


_WMO_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

_WEATHER_STOPWORDS = {
    "what", "whats", "what's", "is", "are", "the", "a", "an", "current", "currently", "live",
    "today", "tonight", "now", "tomorrow", "weekend", "weather", "forecast", "forecasts",
    "for", "and", "in", "at", "of", "near", "around", "of", "area", "code", "postcode", "post",
    "zip", "suburb", "city", "town", "please", "tell", "me", "give", "show", "check", "get",
    "fetch", "display", "pull", "look", "looking", "see", "find", "know", "bring", "send",
    "want", "need", "can", "you", "could", "would", "will", "does", "should", "going",
    "doing", "expect", "acting", "behaving", "feeling", "feels", "heading", "happening",
    "gonna", "think", "thinking", "telling", "wondering",
    "outside", "there", "here", "right", "latest", "local", "this", "that", "with", "from",
    "about", "have", "has", "been", "coming", "next", "days", "day", "week", "outlook",
    "temperature", "temp", "temps", "like", "how", "radar", "map", "maps", "rain", "raining",
    "wind", "windy", "humidity", "hourly", "conditions", "condition", "climate", "report", "update",
    "morning", "afternoon", "evening", "night", "storm", "storms", "sunny", "cloudy", "cold",
    "hot", "warm", "cool", "degree", "degrees", "celsius", "fahrenheit", "chance", "precip",
    "precipitation", "sunrise", "sunset", "time", "hey", "hi", "hello", "its", "it's",
    "over", "across", "out", "my", "our", "your", "any", "some", "just", "also", "still",
    "expected", "expecting", "supposed", "home",
}

_WEATHER_REGION_HINTS: dict[str, tuple[str, ...]] = {
    "australia": ("au", "australia"),
    "au": ("au", "australia"),
    "oz": ("au", "australia"),
    "sa": ("south australia", "au"),
    "south australia": ("south australia", "au"),
    "nsw": ("new south wales", "au"),
    "new south wales": ("new south wales", "au"),
    "vic": ("victoria", "au"),
    "victoria": ("victoria", "au"),
    "qld": ("queensland", "au"),
    "queensland": ("queensland", "au"),
    "wa": ("western australia", "au"),
    "western australia": ("western australia", "au"),
    "tas": ("tasmania", "au"),
    "tasmania": ("tasmania", "au"),
    "nt": ("northern territory", "au"),
    "northern territory": ("northern territory", "au"),
    "act": ("australian capital territory", "au"),
    "nz": ("nz", "new zealand"),
    "new zealand": ("nz", "new zealand"),
    "uk": ("gb", "united kingdom"),
    "united kingdom": ("gb", "united kingdom"),
    "england": ("gb", "england", "united kingdom"),
    "usa": ("us", "united states"),
    "us": ("us", "united states"),
    "united states": ("us", "united states"),
    "canada": ("ca", "canada"),
    "ca": ("ca", "canada"),
}

_WEATHER_PLACE_PREP_RE = re.compile(
    r"\b(?:for|in|at|near|around|of|with|across|over)\s+([A-Za-z][A-Za-z'\-]*(?:[,\s]+[A-Za-z][A-Za-z'\-]*){0,4})",
    re.IGNORECASE,
)

_BEFORE_WEATHER_PLACE_RE = re.compile(
    r"\b([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})\s+(?:weather|forecast|temp(?:erature)?|rain|radar|climate|conditions)\b",
    re.IGNORECASE,
)


def _extract_weather_region_hints(raw: str) -> tuple[str, ...]:
    low = re.sub(r"[^a-z0-9\s]+", " ", (raw or "").lower())
    words = low.split()
    hints: list[str] = []
    for size in (2, 1):
        for i in range(len(words) - size + 1):
            phrase = " ".join(words[i : i + size])
            if phrase in _WEATHER_REGION_HINTS:
                for tok in _WEATHER_REGION_HINTS[phrase]:
                    if tok not in hints:
                        hints.append(tok)
    return tuple(hints)


def _clean_place_span(raw_span: str) -> str:
    tokens = [t for t in re.split(r"[,\s]+", (raw_span or "").strip()) if t]
    # Strip leading stopwords cleanly
    while tokens and tokens[0].lower() in _WEATHER_STOPWORDS:
        tokens.pop(0)
    # Trim at first trailing stopword after the place name starts
    collected: list[str] = []
    for tok in tokens:
        if tok.lower() in _WEATHER_STOPWORDS:
            break
        collected.append(tok)
    # Strip trailing country/state suffix if at least 1 city word precedes it (e.g. "Adelaide Australia" -> "Adelaide")
    while len(collected) >= 3 and " ".join(collected[-2:]).lower() in _WEATHER_REGION_HINTS:
        collected = collected[:-2]
    while len(collected) >= 2 and collected[-1].lower() in _WEATHER_REGION_HINTS:
        collected = collected[:-1]
    return " ".join(collected).strip()


def _extract_weather_place_candidates(raw: str) -> list[str]:
    """Extract clean place-name candidates regardless of English word order or trailing country/state qualifiers."""
    text = (raw or "").strip()
    if not text:
        return []
    candidate_names: list[str] = []
    seen_lower: set[str] = set()
    covered_tokens: set[str] = set()

    def _register(phrase: str) -> None:
        clean = phrase.strip()
        if len(clean) < 3 or clean.lower() in seen_lower or clean.lower() in _WEATHER_STOPWORDS:
            return
        seen_lower.add(clean.lower())
        candidate_names.append(clean)
        for tok in clean.split():
            covered_tokens.add(tok.lower())

    for m in _WEATHER_PLACE_PREP_RE.finditer(text):
        _register(_clean_place_span(m.group(1)))

    for m in _BEFORE_WEATHER_PLACE_RE.finditer(text):
        _register(_clean_place_span(m.group(1)))

    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", text)
    for w in words:
        low = w.lower()
        if low in _WEATHER_STOPWORDS or low in _WEATHER_REGION_HINTS or len(w) < 3 or low in covered_tokens or low in seen_lower:
            continue
        seen_lower.add(low)
        candidate_names.append(w)

    return candidate_names[:4]


def _pick_best_geocoding_result(
    cname: str,
    results: list[dict[str, Any]],
    region_hints: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    """Reject phonetic geocoder mismatches (like 'show' -> 'Shut') and rank valid matches."""
    q_norm = re.sub(r"[^a-z0-9]+", " ", (cname or "").lower()).strip()
    q_tokens = q_norm.split()
    if not q_norm or not isinstance(results, list):
        return None
    best_item: dict[str, Any] | None = None
    best_key = (0, 0, -1)
    for r in results:
        if not isinstance(r, dict):
            continue
        r_name = re.sub(r"[^a-z0-9]+", " ", str(r.get("name") or "").lower()).strip()
        if not r_name:
            continue
        r_tokens = r_name.split()
        if r_name == q_norm:
            score = 3
        elif (
            (len(q_norm) >= 4 and (r_name.startswith(q_norm) or q_norm.startswith(r_name)))
            or (q_tokens and all(tok in r_tokens for tok in q_tokens))
        ):
            score = 2
        else:
            score = 0
        if score <= 0:
            continue
        region_boost = 0
        if region_hints:
            hay = " ".join([
                str(r.get("country_code") or "").lower(),
                str(r.get("country") or "").lower(),
                str(r.get("admin1") or "").lower(),
            ])
            if any(re.search(rf"\b{re.escape(h)}\b", hay) for h in region_hints if h):
                region_boost = 1
        try:
            pop = int(r.get("population") or 0)
        except (TypeError, ValueError):
            pop = 0
        rank_key = (score, region_boost, pop)
        if rank_key > best_key:
            best_key = rank_key
            best_item = r
    return best_item


def _deg_to_compass(deg: float | int | None) -> str:
    if deg is None:
        return ""
    dirs = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    idx = int((float(deg) + 22.5) // 45.0) % 8
    return dirs[idx]


def is_weather_query(question: str) -> bool:
    return bool(_WEATHER_QUERY_RE.search(question or ""))


def resolve_saved_user_location(config_path: Path | None = None) -> str:
    """Return user's explicitly entered Home Location from Settings or Living Profile (never uses silent Geo-IP)."""
    try:
        from palace_config import CONFIG_PATH, load_ui_settings
        ui_cfg = load_ui_settings(config_path or CONFIG_PATH)
        hl = str(ui_cfg.get("home_location") or "").strip()
        if hl:
            return hl
    except Exception:
        pass
    if config_path is None:
        try:
            from memory_service import load_memory_summary
            ms_txt = str(load_memory_summary().get("text") or "").strip()
            if ms_txt:
                m_live = re.search(
                    r"\b(?:live(?:s)?\s+in|based\s+in|located\s+in|home(?:\s+city)?\s*:\s*)\s*([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)?)",
                    ms_txt,
                )
                if m_live:
                    return m_live.group(1).strip()
                m_pc = re.search(r"\bpostcode\s+(\d{4})\b", ms_txt, re.IGNORECASE)
                if m_pc:
                    return m_pc.group(1)
        except Exception:
            pass
    return ""


def fetch_live_weather_bundle(
    question: str,
    *,
    timeout: float = 5.0,
    allow_query_without_keyword: bool = False,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve postcodes/cities via free Zippopotam + Open-Meteo APIs (BOM ACCESS-G in AU) with UV/gusts/hourly."""
    raw = (question or "").strip()
    empty = {"text": "", "locations": [], "primary_location": None, "primary_weather": {}}
    if not raw or (not allow_query_without_keyword and not is_weather_query(raw)):
        return empty

    locations: list[dict[str, Any]] = []
    seen_coords: set[tuple[float, float]] = set()
    region_hints = _extract_weather_region_hints(raw)

    def _add_loc(label: str, lat: float, lon: float) -> None:
        key = (round(float(lat), 2), round(float(lon), 2))
        if key in seen_coords:
            return
        seen_coords.add(key)
        locations.append({"label": label, "lat": float(lat), "lon": float(lon)})

    def _resolve_postcodes_and_places(text_q: str, hints_tuple: tuple[str, ...]) -> None:
        # 1. Resolve 4-digit postcodes (Australian default via Zippopotam)
        for pc in re.findall(r"\b(\d{4})\b", text_q):
            if 200 <= int(pc) <= 9999:
                try:
                    req = urllib_request.Request(
                        f"https://api.zippopotam.us/au/{pc}",
                        headers={"User-Agent": "FairybreadWeather/1.0"},
                    )
                    with urllib_request.urlopen(req, timeout=timeout) as resp:
                        zdata = json.loads(resp.read().decode("utf-8"))
                    places = zdata.get("places") or []
                    if places:
                        p0 = places[0]
                        names = ", ".join(str(p.get("place name") or "") for p in places[:3] if p.get("place name"))
                        st_abbr = str(p0.get("state abbreviation") or "").strip()
                        lbl = f"{names} (Postcode {pc}{', ' + st_abbr if st_abbr else ''})"
                        _add_loc(lbl, float(p0["latitude"]), float(p0["longitude"]))
                except Exception:
                    pass

        # 2. Extract candidate place phrases / tokens
        c_names = _extract_weather_place_candidates(text_q)
        if allow_query_without_keyword and not c_names and not is_weather_query(text_q):
            cleaned_direct = _clean_place_span(text_q)
            if cleaned_direct:
                c_names = [cleaned_direct]

        for cname in c_names[:3]:
            variants = [cname]
            parts = cname.split()
            if len(parts) >= 2:
                comma_v = f"{' '.join(parts[:-1])}, {parts[-1]}"
                if comma_v not in variants:
                    variants.append(comma_v)
                if parts[0] not in variants:
                    variants.append(parts[0])
            for q_try in variants:
                try:
                    gurl = "https://geocoding-api.open-meteo.com/v1/search?" + urllib_parse.urlencode(
                        {"name": q_try, "count": 5, "language": "en", "format": "json"}
                    )
                    req = urllib_request.Request(gurl, headers={"User-Agent": "FairybreadWeather/1.0"})
                    with urllib_request.urlopen(req, timeout=timeout) as resp:
                        gdata = json.loads(resp.read().decode("utf-8"))
                    res = (gdata.get("results") or [])
                    top = _pick_best_geocoding_result(q_try.split(",")[0].strip(), res, region_hints=hints_tuple)
                    if top is not None:
                        lbl_parts = [str(top.get("name") or cname)]
                        if top.get("admin1"):
                            lbl_parts.append(str(top["admin1"]))
                        if top.get("country_code"):
                            lbl_parts.append(str(top["country_code"]))
                        _add_loc(", ".join(lbl_parts), float(top["latitude"]), float(top["longitude"]))
                        break
                except Exception:
                    pass

    _resolve_postcodes_and_places(raw, region_hints)

    # 3. If the user named no place ("Tell me the weather", "Will it rain today?"), fall back to user's saved Home Location
    if not locations and not _extract_weather_place_candidates(raw) and not re.findall(r"\b(\d{4})\b", raw):
        saved_loc = resolve_saved_user_location(config_path=config_path)
        if saved_loc:
            saved_hints = _extract_weather_region_hints(saved_loc)
            _resolve_postcodes_and_places(f"for {saved_loc}", saved_hints)

    if not locations:
        return empty

    blocks: list[str] = [
        "=== [LIVE WEATHER DATA — Open-Meteo / BOM ACCESS-G (Fetched Live Now)] ===",
        "Instructions: Answer using ONLY these verified live figures. State current conditions cleanly with a concise 3-day outlook table (or full 7-day forecast + UV/wind gusts/hourly rain if asked), then offer the 7-day breakdown if not already shown. Never invent file paths or pretend an external plugin is needed.",
    ]
    primary_weather: dict[str, Any] = {}
    for idx_loc, loc in enumerate(locations[:2]):
        try:
            furl = "https://api.open-meteo.com/v1/forecast?" + urllib_parse.urlencode({
                "latitude": f"{loc['lat']:.4f}",
                "longitude": f"{loc['lon']:.4f}",
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,cloud_cover",
                "hourly": "temperature_2m,precipitation_probability,weather_code,cloud_cover",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,uv_index_max,sunrise,sunset,wind_speed_10m_max,wind_gusts_10m_max",
                "timezone": "auto",
                "forecast_days": 7,
            })
            req = urllib_request.Request(furl, headers={"User-Agent": "FairybreadWeather/1.0"})
            with urllib_request.urlopen(req, timeout=timeout) as resp:
                wdata = json.loads(resp.read().decode("utf-8"))
            if idx_loc == 0:
                primary_weather = wdata
            cur = wdata.get("current") or {}
            tz_name = str(wdata.get("timezone") or "")
            wcode = int(cur.get("weather_code", -1)) if cur.get("weather_code") is not None else -1
            sky = _WMO_WEATHER_CODES.get(wcode, f"Code {wcode}")
            wdir = _deg_to_compass(cur.get("wind_direction_10m"))
            gusts = cur.get("wind_gusts_10m")
            gust_txt = f" (gusts {gusts} km/h)" if gusts is not None else ""
            blocks.append(
                f"\nLocation: {loc['label']} (Timezone: {tz_name}, Lat {loc['lat']:.3f}, Lon {loc['lon']:.3f})\n"
                f"Observed At: {cur.get('time', 'Now')}\n"
                f"Current: {cur.get('temperature_2m', '?')}°C (feels like {cur.get('apparent_temperature', '?')}°C), "
                f"{sky}, Humidity {cur.get('relative_humidity_2m', '?')}%, "
                f"Wind {cur.get('wind_speed_10m', '?')} km/h {wdir}{gust_txt}, Precip {cur.get('precipitation', 0)} mm"
            )
            hourly = wdata.get("hourly") or {}
            h_times = hourly.get("time") or []
            h_temps = hourly.get("temperature_2m") or []
            h_probs = hourly.get("precipitation_probability") or []
            cur_time_str = str(cur.get("time") or "")[:13]
            if h_times:
                start_h = 0
                for hi_idx, ht in enumerate(h_times):
                    if str(ht)[:13] >= cur_time_str:
                        start_h = hi_idx
                        break
                h_slice = []
                for j in range(start_h, min(len(h_times), start_h + 12), 2):
                    hh = str(h_times[j])[-5:]
                    tt = h_temps[j] if j < len(h_temps) else "?"
                    pp = h_probs[j] if j < len(h_probs) else "?"
                    h_slice.append(f"{hh}: {tt}°C ({pp}% rain)")
                if h_slice:
                    blocks.append("Next 12h Hourly: " + " | ".join(h_slice))
            daily = wdata.get("daily") or {}
            dates = daily.get("time") or []
            tmax = daily.get("temperature_2m_max") or []
            tmin = daily.get("temperature_2m_min") or []
            pcodes = daily.get("weather_code") or []
            pprob = daily.get("precipitation_probability_max") or []
            psum = daily.get("precipitation_sum") or []
            uv_max = daily.get("uv_index_max") or []
            sun_rise = daily.get("sunrise") or []
            sun_set = daily.get("sunset") or []
            if dates:
                day_lines = ["7-Day Forecast:"]
                for idx, dt in enumerate(dates[:7]):
                    dc = int(pcodes[idx]) if idx < len(pcodes) and pcodes[idx] is not None else -1
                    dsky = _WMO_WEATHER_CODES.get(dc, "")
                    hi = tmax[idx] if idx < len(tmax) else "?"
                    lo = tmin[idx] if idx < len(tmin) else "?"
                    pr = pprob[idx] if idx < len(pprob) else "?"
                    mm = psum[idx] if idx < len(psum) else 0
                    uv = uv_max[idx] if idx < len(uv_max) and uv_max[idx] is not None else None
                    uv_part = f", Max UV {uv}" if uv is not None else ""
                    sun_part = ""
                    if idx == 0 and idx < len(sun_rise) and idx < len(sun_set):
                        sr = str(sun_rise[0])[-5:]
                        ss = str(sun_set[0])[-5:]
                        if sr and ss:
                            sun_part = f", Sunrise {sr} / Sunset {ss}"
                    day_lines.append(f"  - {dt}: {lo}°C – {hi}°C, {dsky}, Rain {pr}% ({mm} mm){uv_part}{sun_part}")
                blocks.append("\n".join(day_lines))
        except Exception:
            continue

    txt = "\n".join(blocks) if len(blocks) > 2 else ""
    return {
        "text": txt,
        "locations": locations,
        "primary_location": locations[0] if locations else None,
        "primary_weather": primary_weather,
    }


def fetch_live_weather_context(question: str, *, timeout: float = 5.0) -> str:
    """Resolve postcodes/cities via free Zippopotam + Open-Meteo APIs (BOM ACCESS-G in AU) with zero scraping."""
    return str(fetch_live_weather_bundle(question, timeout=timeout).get("text") or "")


_RAINVIEWER_META_CACHE: tuple[float, dict[str, Any]] | None = None
_REGIONAL_WEATHER_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _lat_lon_to_tile_xy(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_c = max(-85.0511, min(85.0511, float(lat)))
    n = 2.0 ** int(zoom)
    xtile = (float(lon) + 180.0) / 360.0 * n
    lat_rad = math.radians(lat_c)
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def _tile_xy_to_lat_lon(fx: float, fy: float, zoom: int) -> tuple[float, float]:
    n = 2.0 ** int(zoom)
    lon = (float(fx) / n) * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * float(fy) / n)))
    return math.degrees(lat_rad), lon


_AU_REGIONAL_WEATHER_STATIONS: tuple[tuple[str, float, float], ...] = (
    # South Australia / Mildura
    ("Port Lincoln", -34.726, 135.858),
    ("Whyalla", -33.036, 137.560),
    ("Port Pirie", -33.186, 138.017),
    ("Kadina", -33.962, 137.714),
    ("Kingscote", -35.656, 137.638),
    ("Gawler", -34.598, 138.745),
    ("Victor Harbor", -35.552, 138.623),
    ("Murray Bridge", -35.119, 139.276),
    ("Renmark", -34.175, 140.744),
    ("Mildura", -34.185, 142.163),
    ("Keith", -36.099, 140.354),
    # Victoria / Melbourne
    ("Geelong", -38.149, 144.362),
    ("Ballarat", -37.562, 143.850),
    ("Bendigo", -36.757, 144.279),
    ("Shepparton", -36.380, 145.399),
    ("Warrnambool", -38.382, 142.488),
    ("Traralgon", -38.196, 146.540),
    # NSW / Sydney / Canberra
    ("Wollongong", -34.428, 150.893),
    ("Newcastle", -32.928, 151.782),
    ("Katoomba", -33.715, 150.312),
    ("Goulburn", -34.755, 149.719),
    ("Canberra", -35.281, 149.130),
    ("Wagga Wagga", -35.108, 147.359),
    ("Nowra", -34.872, 150.603),
    # Queensland / Brisbane
    ("Gold Coast", -28.017, 153.400),
    ("Sunshine Coast", -26.650, 153.067),
    ("Toowoomba", -27.559, 151.951),
    ("Gympie", -26.190, 152.666),
    ("Warwick", -28.215, 152.035),
    ("Byron Bay", -28.647, 153.602),
    # WA / Perth
    ("Mandurah", -32.527, 115.722),
    ("Bunbury", -33.327, 115.641),
    ("Geraldton", -28.777, 114.614),
    ("Northam", -31.653, 116.666),
    ("Albany", -35.027, 117.884),
    # Tasmania / Hobart
    ("Launceston", -41.433, 147.144),
    ("Devonport", -41.179, 146.359),
    ("Burnie", -41.052, 145.906),
    ("Swansea", -42.125, 148.075),
    # NT / Darwin
    ("Katherine", -14.465, 132.263),
    ("Jabiru", -12.671, 132.834),
)


def _regional_weather_points_for(
    lat: float,
    lon: float,
    fx: float,
    fy: float,
    cx: int,
    cy: int,
    dx_list: list[int],
    dy_list: list[int],
    map_y_off: int,
    zoom: int,
) -> list[dict[str, Any]]:
    """Select well-spaced regional points visible inside the current map viewport."""
    min_x, max_x = 34, 734
    min_y, max_y = 48, 430
    x0 = cx + dx_list[0]
    y0 = cy + dy_list[0]

    candidates: list[dict[str, Any]] = []
    for st_name, slat, slon in _AU_REGIONAL_WEATHER_STATIONS:
        dist_deg = math.hypot(slat - lat, slon - lon)
        if dist_deg < 0.25 or dist_deg > 5.0:
            continue
        sfx, sfy = _lat_lon_to_tile_xy(slat, slon, zoom)
        spx = int(round((sfx - x0) * 256))
        spy = int(round((sfy - y0) * 256)) + map_y_off
        if min_x <= spx <= max_x and min_y <= spy <= max_y:
            candidates.append({"name": st_name, "lat": slat, "lon": slon, "px": spx, "py": spy})

    if len(candidates) < 5:
        grid_offsets = [
            ("N", 0.0, -0.58),
            ("NE", 0.72, -0.45),
            ("E", 0.88, 0.04),
            ("SE", 0.72, 0.48),
            ("S", 0.0, 0.56),
            ("SW", -0.72, 0.48),
            ("W", -0.88, 0.04),
            ("NW", -0.72, -0.45),
        ]
        for dir_lbl, tfx_off, tfy_off in grid_offsets:
            g_fx = fx + tfx_off
            g_fy = fy + tfy_off
            spx = int(round((g_fx - x0) * 256))
            spy = int(round((g_fy - y0) * 256)) + map_y_off
            if not (min_x <= spx <= max_x and min_y <= spy <= max_y):
                continue
            glat, glon = _tile_xy_to_lat_lon(g_fx, g_fy, zoom)
            if any(math.hypot(c["px"] - spx, c["py"] - spy) < 62 for c in candidates):
                continue
            candidates.append({"name": dir_lbl, "lat": round(glat, 3), "lon": round(glon, 3), "px": spx, "py": spy})

    # De-duplicate closely spaced stations (keep nicely distributed points, max 9)
    chosen: list[dict[str, Any]] = []
    pin_x = int(round((fx - x0) * 256))
    pin_y = int(round((fy - y0) * 256)) + map_y_off
    for item in candidates:
        if math.hypot(item["px"] - pin_x, item["py"] - pin_y) < 58:
            continue
        if any(abs(item["px"] - c["px"]) < 92 and abs(item["py"] - c["py"]) < 34 for c in chosen):
            continue
        chosen.append(item)
        if len(chosen) >= 9:
            break
    return chosen


_BITMAP_FONT_5X7: dict[str, tuple[str, ...]] = {
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".####", "#....", "#....", "#..##", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": ("..###", "...#.", "...#.", "...#.", "#..#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", ".#.#.", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#...#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#..##", "#.#.#", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "..##.", ".#...", "#....", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("#...#", "#...#", "#...#", "#####", "....#", "....#", "....#"),
    "5": ("#####", "#....", "#....", "####.", "....#", "....#", "####."),
    "6": (".###.", "#....", "####.", "#...#", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    ",": (".....", ".....", ".....", ".....", ".....", "..#..", ".#..."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    "/": ("....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."),
    "-": (".....", ".....", ".....", ".###.", ".....", ".....", "....."),
    "%": ("##..#", "##.#.", "...#.", "..#..", ".#...", ".#.##", "#..##"),
    "(": ("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": (".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "|": ("..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "'": ("..#..", "..#..", ".#...", ".....", ".....", ".....", "....."),
    "°": (".##..", "#..#.", ".##..", ".....", ".....", ".....", "....."),
    "·": (".....", ".....", ".....", "..#..", ".....", ".....", "....."),
    "?": (".###.", "#...#", "....#", "..##.", "..#..", ".....", "..#.."),
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
}


def _draw_qimage_bitmap_text(painter: Any, x: int, y: int, text: str, color: Any, scale: int = 1) -> None:
    """Thread-safe pure-pixel HUD text renderer via QPainter.fillRect (no QFont / no QGuiApplication required)."""
    s = max(1, int(scale))
    cur_x = int(x)
    clean = (text or "").replace("—", "-").replace("–", "-")
    for raw_ch in clean:
        ch = raw_ch.upper()
        glyph = _BITMAP_FONT_5X7.get(ch)
        if glyph is None:
            cur_x += 6 * s
            continue
        for ry, row in enumerate(glyph):
            for cx_px, pixel in enumerate(row):
                if pixel == "#":
                    painter.fillRect(cur_x + cx_px * s, int(y) + ry * s, s, s, color)
        cur_x += 6 * s


def _short_sky_label(wcode: int) -> str:
    if wcode == 0:
        return "Clear"
    if wcode == 1:
        return "Mostly clear"
    if wcode == 2:
        return "Partly cldy"
    if wcode == 3:
        return "Overcast"
    if wcode in (45, 48):
        return "Fog"
    if wcode in (51, 53, 55):
        return "Drizzle"
    if wcode in (61, 63, 65):
        return "Rain"
    if wcode in (71, 73, 75):
        return "Snow"
    if wcode in (80, 81, 82):
        return "Showers"
    if wcode in (95, 96, 99):
        return "Storm"
    return "Mixed"


def _temp_badge_color(temp_val: Any) -> tuple[int, int, int]:
    try:
        t = float(temp_val)
    except (TypeError, ValueError):
        return (148, 163, 184)
    if t >= 33.0:
        return (239, 68, 68)
    if t >= 26.0:
        return (249, 115, 22)
    if t >= 19.0:
        return (250, 204, 21)
    if t >= 12.0:
        return (56, 189, 248)
    return (147, 197, 253)


def _uv_badge_color(uv_val: Any) -> tuple[int, int, int]:
    try:
        u = float(uv_val)
    except (TypeError, ValueError):
        return (156, 163, 175)
    if u >= 11.0:
        return (192, 132, 252)
    if u >= 8.0:
        return (248, 113, 113)
    if u >= 6.0:
        return (251, 146, 60)
    if u >= 3.0:
        return (250, 204, 21)
    return (74, 222, 128)


def _draw_pil_weather_icon(draw: Any, cx: int, cy: int, wcode: int, scale: float = 1.0) -> None:
    """Draw a crisp vector weather icon centered at (cx, cy) without relying on color emoji fonts."""
    s = float(scale)

    def _sun(sx: float, sy: float, r: float) -> None:
        sun_col = (251, 191, 36, 255)
        ray_col = (253, 224, 71, 225)
        for k in range(8):
            ang = k * (math.pi / 4.0)
            x1 = sx + math.cos(ang) * (r + 2.0 * s)
            y1 = sy + math.sin(ang) * (r + 2.0 * s)
            x2 = sx + math.cos(ang) * (r + 4.8 * s)
            y2 = sy + math.sin(ang) * (r + 4.8 * s)
            draw.line((x1, y1, x2, y2), fill=ray_col, width=max(1, int(round(1.6 * s))))
        draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=sun_col)

    def _cloud(qx: float, qy: float, cw: float, fill_col: tuple[int, int, int, int]) -> None:
        r1 = cw * 0.24
        r2 = cw * 0.30
        r3 = cw * 0.22
        draw.ellipse((qx - cw * 0.44, qy - r1 * 0.6, qx - cw * 0.44 + r1 * 2, qy - r1 * 0.6 + r1 * 2), fill=fill_col)
        draw.ellipse((qx - cw * 0.20, qy - r2 * 1.15, qx - cw * 0.20 + r2 * 2, qy - r2 * 1.15 + r2 * 2), fill=fill_col)
        draw.ellipse((qx + cw * 0.04, qy - r3 * 0.5, qx + cw * 0.04 + r3 * 2, qy - r3 * 0.5 + r3 * 2), fill=fill_col)
        draw.rounded_rectangle((qx - cw * 0.45, qy - cw * 0.02, qx + cw * 0.46, qy + cw * 0.28), radius=max(2, int(4 * s)), fill=fill_col)

    if wcode == 0:
        _sun(cx, cy, 6.2 * s)
    elif wcode == 1:
        _sun(cx - 2.0 * s, cy - 1.5 * s, 5.4 * s)
        _cloud(cx + 3.0 * s, cy + 3.5 * s, 14.0 * s, (226, 232, 240, 225))
    elif wcode == 2:
        _sun(cx + 4.2 * s, cy - 3.2 * s, 4.6 * s)
        _cloud(cx - 1.0 * s, cy + 2.0 * s, 18.0 * s, (203, 213, 225, 240))
    elif wcode in (3, 45, 48):
        c_col = (148, 163, 184, 240) if wcode == 3 else (156, 163, 175, 215)
        _cloud(cx, cy - (1.0 * s if wcode in (45, 48) else 0.0), 21.0 * s, c_col)
        if wcode in (45, 48):
            for fy_i in (6.5, 9.5):
                draw.line((cx - 8 * s, cy + fy_i * s, cx + 8 * s, cy + fy_i * s), fill=(203, 213, 225, 210), width=max(1, int(1.5 * s)))
    elif wcode in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        _cloud(cx, cy - 2.5 * s, 20.0 * s, (148, 163, 184, 240))
        drops = (-5.5, 0.0, 5.5) if wcode in (61, 63, 65, 80, 81, 82) else (-3.5, 3.5)
        dcol = (56, 189, 248, 255)
        for dx_d in drops:
            rx = cx + dx_d * s
            draw.line((rx, cy + 4.0 * s, rx - 2.2 * s, cy + 9.2 * s), fill=dcol, width=max(1, int(1.8 * s)))
    elif wcode in (71, 73, 75):
        _cloud(cx, cy - 2.5 * s, 20.0 * s, (203, 213, 225, 240))
        for dx_d in (-5.5, 0.0, 5.5):
            rx = cx + dx_d * s
            ry = cy + 7.0 * s
            draw.ellipse((rx - 1.6 * s, ry - 1.6 * s, rx + 1.6 * s, ry + 1.6 * s), fill=(241, 245, 249, 255))
    elif wcode in (95, 96, 99):
        _cloud(cx, cy - 2.8 * s, 20.0 * s, (100, 116, 139, 245))
        bolt = [
            (cx + 1.0 * s, cy + 2.0 * s),
            (cx - 2.5 * s, cy + 6.8 * s),
            (cx + 0.8 * s, cy + 6.8 * s),
            (cx - 1.6 * s, cy + 12.0 * s),
        ]
        draw.line(bolt, fill=(250, 204, 21, 255), width=max(1, int(2.0 * s)))
    else:
        _sun(cx, cy, 5.0 * s)


def _draw_pil_wind_arrow(
    draw: Any,
    x: int,
    y: int,
    wind_deg: float | int | None,
    *,
    length: int = 12,
    color: tuple[int, int, int, int] = (56, 189, 248, 235),
) -> None:
    """Draw a vector arrow showing the direction wind is blowing TOWARD (meteorological deg + 180)."""
    if wind_deg is None:
        return
    try:
        flow_rad = math.radians((float(wind_deg) + 180.0) % 360.0)
    except (TypeError, ValueError):
        return
    ux = math.sin(flow_rad)
    uy = -math.cos(flow_rad)
    half = length / 2.0
    x1, y1 = x - ux * half, y - uy * half
    x2, y2 = x + ux * half, y + uy * half
    draw.line((x1, y1, x2, y2), fill=color, width=2)
    px, py = -uy, ux
    head = 4.2
    back = 4.5
    p_left = (x2 - ux * back + px * head * 0.65, y2 - uy * back + py * head * 0.65)
    p_right = (x2 - ux * back - px * head * 0.65, y2 - uy * back - py * head * 0.65)
    draw.polygon([(x2, y2), p_left, p_right], fill=color)


def _parse_forecast_days_for_card(daily: dict[str, Any]) -> list[dict[str, Any]]:
    dates = daily.get("time") or []
    if not dates:
        return []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    pcodes = daily.get("weather_code") or []
    pprob = daily.get("precipitation_probability_max") or []
    psum = daily.get("precipitation_sum") or []
    uv_max = daily.get("uv_index_max") or []
    days: list[dict[str, Any]] = []
    for idx, dt_s in enumerate(dates[:7]):
        try:
            d_obj = datetime.strptime(str(dt_s)[:10], "%Y-%m-%d")
            day_lbl = f"{'Today' if idx == 0 else d_obj.strftime('%a')} {d_obj.day}"
        except ValueError:
            day_lbl = str(dt_s)[:10]
        dc = int(pcodes[idx]) if idx < len(pcodes) and pcodes[idx] is not None else 0
        hi = tmax[idx] if idx < len(tmax) and tmax[idx] is not None else None
        lo = tmin[idx] if idx < len(tmin) and tmin[idx] is not None else None
        pr = pprob[idx] if idx < len(pprob) and pprob[idx] is not None else 0
        mm = psum[idx] if idx < len(psum) and psum[idx] is not None else 0.0
        uv = uv_max[idx] if idx < len(uv_max) and uv_max[idx] is not None else None
        days.append({
            "label": day_lbl,
            "code": dc,
            "sky": _short_sky_label(dc),
            "hi": hi,
            "lo": lo,
            "rain_prob": pr,
            "rain_mm": mm,
            "uv": uv,
        })
    return days


def _draw_qt_weather_icon(painter: Any, cx: int, cy: int, wcode: int, scale: float = 1.0) -> None:
    """Draw a crisp antialiased vector weather icon on a QPainter without color emoji dependencies."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPen, QPolygonF

    s = float(scale)

    def _sun(sx: float, sy: float, r: float) -> None:
        painter.setPen(QPen(QColor(253, 224, 71, 225), max(1.2, 1.6 * s)))
        for k in range(8):
            ang = k * (math.pi / 4.0)
            x1 = sx + math.cos(ang) * (r + 2.0 * s)
            y1 = sy + math.sin(ang) * (r + 2.0 * s)
            x2 = sx + math.cos(ang) * (r + 4.8 * s)
            y2 = sy + math.sin(ang) * (r + 4.8 * s)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(251, 191, 36, 255))
        painter.drawEllipse(QPointF(sx, sy), r, r)

    def _cloud(qx: float, qy: float, cw: float, qcol: QColor) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qcol)
        r1, r2, r3 = cw * 0.24, cw * 0.30, cw * 0.22
        painter.drawEllipse(QPointF(qx - cw * 0.20, qy - r1 * 0.1 + 2 * s), r1, r1)
        painter.drawEllipse(QPointF(qx + cw * 0.10, qy - r2 * 0.2), r2, r2)
        painter.drawEllipse(QPointF(qx + cw * 0.26, qy + r3 * 0.1 + 1 * s), r3, r3)
        painter.drawRoundedRect(
            int(round(qx - cw * 0.45)),
            int(round(qy - cw * 0.02)),
            int(round(cw * 0.91)),
            int(round(cw * 0.30)),
            max(2, int(4 * s)),
            max(2, int(4 * s)),
        )

    if wcode == 0:
        _sun(cx, cy, 6.2 * s)
    elif wcode == 1:
        _sun(cx - 2.0 * s, cy - 1.5 * s, 5.4 * s)
        _cloud(cx + 3.0 * s, cy + 3.5 * s, 14.0 * s, QColor(226, 232, 240, 225))
    elif wcode == 2:
        _sun(cx + 4.2 * s, cy - 3.2 * s, 4.6 * s)
        _cloud(cx - 1.0 * s, cy + 2.0 * s, 18.0 * s, QColor(203, 213, 225, 240))
    elif wcode in (3, 45, 48):
        c_col = QColor(148, 163, 184, 240) if wcode == 3 else QColor(156, 163, 175, 215)
        _cloud(cx, cy - (1.0 * s if wcode in (45, 48) else 0.0), 21.0 * s, c_col)
        if wcode in (45, 48):
            painter.setPen(QPen(QColor(203, 213, 225, 210), max(1.0, 1.5 * s)))
            for fy_i in (6.5, 9.5):
                painter.drawLine(QPointF(cx - 8 * s, cy + fy_i * s), QPointF(cx + 8 * s, cy + fy_i * s))
    elif wcode in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        _cloud(cx, cy - 2.5 * s, 20.0 * s, QColor(148, 163, 184, 240))
        drops = (-5.5, 0.0, 5.5) if wcode in (61, 63, 65, 80, 81, 82) else (-3.5, 3.5)
        painter.setPen(QPen(QColor(56, 189, 248, 255), max(1.2, 1.8 * s)))
        for dx_d in drops:
            rx = cx + dx_d * s
            painter.drawLine(QPointF(rx, cy + 4.0 * s), QPointF(rx - 2.2 * s, cy + 9.2 * s))
    elif wcode in (71, 73, 75):
        _cloud(cx, cy - 2.5 * s, 20.0 * s, QColor(203, 213, 225, 240))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(241, 245, 249, 255))
        for dx_d in (-5.5, 0.0, 5.5):
            painter.drawEllipse(QPointF(cx + dx_d * s, cy + 7.0 * s), 1.6 * s, 1.6 * s)
    elif wcode in (95, 96, 99):
        _cloud(cx, cy - 2.8 * s, 20.0 * s, QColor(100, 116, 139, 245))
        painter.setPen(QPen(QColor(250, 204, 21, 255), max(1.4, 2.0 * s)))
        bolt = QPolygonF([
            QPointF(cx + 1.0 * s, cy + 2.0 * s),
            QPointF(cx - 2.5 * s, cy + 6.8 * s),
            QPointF(cx + 0.8 * s, cy + 6.8 * s),
            QPointF(cx - 1.6 * s, cy + 12.0 * s),
        ])
        painter.drawPolyline(bolt)
    else:
        _sun(cx, cy, 5.0 * s)


def _draw_qt_wind_arrow(
    painter: Any,
    x: int,
    y: int,
    wind_deg: float | int | None,
    *,
    length: int = 12,
    qcolor: Any = None,
) -> None:
    """Draw a vector arrow showing the direction wind is blowing TOWARD (meteorological deg + 180)."""
    if wind_deg is None:
        return
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPen, QPolygonF

    try:
        flow_rad = math.radians((float(wind_deg) + 180.0) % 360.0)
    except (TypeError, ValueError):
        return
    col = qcolor if qcolor is not None else QColor(56, 189, 248, 235)
    ux = math.sin(flow_rad)
    uy = -math.cos(flow_rad)
    half = length / 2.0
    x1, y1 = x - ux * half, y - uy * half
    x2, y2 = x + ux * half, y + uy * half
    painter.setPen(QPen(col, 1.6))
    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    px, py = -uy, ux
    head = 4.2
    back = 4.5
    poly = QPolygonF([
        QPointF(x2, y2),
        QPointF(x2 - ux * back + px * head * 0.65, y2 - uy * back + py * head * 0.65),
        QPointF(x2 - ux * back - px * head * 0.65, y2 - uy * back - py * head * 0.65),
    ])
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(col)
    painter.drawPolygon(poly)


def render_live_weather_map_png(
    location: dict[str, Any],
    weather_data: dict[str, Any] | None = None,
    *,
    out_dir: Path | None = None,
    cache_dir: Path | None = None,
    timeout: float = 5.0,
) -> Path | None:
    """Stitch dark base map + live RainViewer radar + regional weather stations + 7-day forecast card (100% API-key-free)."""
    global _RAINVIEWER_META_CACHE, _REGIONAL_WEATHER_CACHE
    use_pil = True
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        use_pil = False
        try:
            from PySide6.QtGui import QColor, QImage, QPainter, QPen
        except Exception:
            return None

    try:
        lat = float(location.get("lat"))
        lon = float(location.get("lon"))
    except (TypeError, ValueError):
        return None
    label = str(location.get("label") or f"{lat:.2f}, {lon:.2f}").strip()

    try:
        from palace_config import get_appdata_root
        eff_cache = Path(cache_dir) if cache_dir is not None else (get_appdata_root() / "cache" / "map_tiles")
    except Exception:
        eff_cache = Path(cache_dir) if cache_dir is not None else Path("cache/map_tiles")
    eff_cache.mkdir(parents=True, exist_ok=True)
    for _old_glob in ("carto_dark_*.png", "osm_dark2_*.png"):
        for _legacy in eff_cache.glob(_old_glob):
            try:
                _legacy.unlink()
            except OSError:
                pass

    if out_dir is None:
        try:
            from palace_theme import get_generated_images_dir
            eff_out = get_generated_images_dir()
        except Exception:
            eff_out = eff_cache.parent
    else:
        eff_out = Path(out_dir)
    eff_out.mkdir(parents=True, exist_ok=True)

    cur = ((weather_data or {}).get("current") or {}) if isinstance(weather_data, dict) else {}
    daily = ((weather_data or {}).get("daily") or {}) if isinstance(weather_data, dict) else {}
    hourly = ((weather_data or {}).get("hourly") or {}) if isinstance(weather_data, dict) else {}
    forecast_days = _parse_forecast_days_for_card(daily)
    has_forecast_strip = bool(forecast_days)
    canvas_h = 640 if has_forecast_strip else 512
    header_h = 38
    map_top = header_h
    map_bottom = 458 if has_forecast_strip else 482
    map_mid_y = (map_top + map_bottom) // 2

    zoom = 7
    n_tiles = 1 << zoom
    fx, fy = _lat_lon_to_tile_xy(lat, lon, zoom)
    cx = int(math.floor(fx))
    cy = int(math.floor(fy))
    px_in_center = int(round((fx - cx) * 256))
    py_in_center = int(round((fy - cy) * 256))

    dx_list = [-1, 0, 1]
    dy_list = [-1, 0] if py_in_center < 128 else [0, 1]
    if py_in_center < 96:
        dy_list = [-1, 0]
    raw_pin_py = ((0 if dy_list[0] == 0 else 1) * 256) + py_in_center
    # Shift vertical tile grid cleanly so tiles cover [map_top .. map_bottom] while centering the target pin
    min_y_off = map_bottom - 512
    max_y_off = map_top
    map_y_off = max(min_y_off, min(max_y_off, map_mid_y - raw_pin_py))
    pin_px = (1 * 256) + px_in_center
    pin_py = raw_pin_py + map_y_off

    regional_pts = _regional_weather_points_for(lat, lon, fx, fy, cx, cy, dx_list, dy_list, map_y_off, zoom)

    _CARTO_API_KEY_SHA_PREFIX = "cc3f31364a73"

    def _fetch_bytes(url: str) -> bytes:
        req = urllib_request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FairybreadWeather/1.2"},
        )
        with urllib_request.urlopen(req, timeout=float(timeout)) as resp:
            return resp.read(2_000_000)

    radar_host = "https://tilecache.rainviewer.com"
    radar_path = ""
    radar_ts = 0
    now_mono = time.monotonic()
    rv_data: dict[str, Any] | None = None
    if _RAINVIEWER_META_CACHE is not None and (now_mono - _RAINVIEWER_META_CACHE[0]) <= 300.0:
        rv_data = _RAINVIEWER_META_CACHE[1]
    else:
        try:
            rv_raw = _fetch_bytes("https://api.rainviewer.com/public/weather-maps.json")
            loaded = json.loads(rv_raw.decode("utf-8", errors="replace"))
            if isinstance(loaded, dict):
                rv_data = loaded
                _RAINVIEWER_META_CACHE = (now_mono, loaded)
        except Exception:
            rv_data = _RAINVIEWER_META_CACHE[1] if _RAINVIEWER_META_CACHE else None

    if isinstance(rv_data, dict):
        radar_host = str(rv_data.get("host") or radar_host).rstrip("/")
        past = ((rv_data.get("radar") or {}).get("past") or [])
        if past and isinstance(past[-1], dict):
            radar_path = str(past[-1].get("path") or "")
            radar_ts = int(past[-1].get("time") or 0)

    def _is_valid_base_tile(raw_b: bytes) -> bool:
        if len(raw_b) <= 100:
            return False
        if hashlib.sha256(raw_b).hexdigest().startswith(_CARTO_API_KEY_SHA_PREFIX):
            return False
        return True

    def _fetch_base_bytes(gx: int, gy: int) -> bytes:
        if gy < 0 or gy >= n_tiles:
            return b""
        wx = gx % n_tiles
        tile_fp = eff_cache / f"esri_dark2_{zoom}_{wx}_{gy}.png"
        if tile_fp.is_file():
            try:
                cached = tile_fp.read_bytes()
                if _is_valid_base_tile(cached):
                    return cached
            except OSError:
                pass
        url_esri = f"https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{zoom}/{gy}/{wx}"
        try:
            raw_b = _fetch_bytes(url_esri)
            if _is_valid_base_tile(raw_b):
                try:
                    tile_fp.write_bytes(raw_b)
                except OSError:
                    pass
                return raw_b
        except Exception:
            pass
        url_osm = f"https://tile.openstreetmap.org/{zoom}/{wx}/{gy}.png"
        try:
            raw_b = _fetch_bytes(url_osm)
            if _is_valid_base_tile(raw_b):
                return raw_b
        except Exception:
            pass
        return b""

    def _fetch_ref_bytes(gx: int, gy: int) -> bytes:
        if gy < 0 or gy >= n_tiles:
            return b""
        wx = gx % n_tiles
        ref_fp = eff_cache / f"esri_ref2_{zoom}_{wx}_{gy}.png"
        if ref_fp.is_file():
            try:
                cached = ref_fp.read_bytes()
                if _is_valid_base_tile(cached):
                    return cached
            except OSError:
                pass
        url = f"https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{zoom}/{gy}/{wx}"
        try:
            raw_b = _fetch_bytes(url)
            if _is_valid_base_tile(raw_b):
                try:
                    ref_fp.write_bytes(raw_b)
                except OSError:
                    pass
                return raw_b
        except Exception:
            pass
        return b""

    def _fetch_radar_bytes(gx: int, gy: int) -> bytes:
        if not radar_path or gy < 0 or gy >= n_tiles:
            return b""
        wx = gx % n_tiles
        url = f"{radar_host}{radar_path}/256/{zoom}/{wx}/{gy}/2/1_1.png"
        try:
            return _fetch_bytes(url)
        except Exception:
            return b""

    def _fetch_regional_weather() -> list[dict[str, Any]]:
        if not regional_pts:
            return []
        cache_k = f"{lat:.2f},{lon:.2f},{zoom}"
        cached_reg = _REGIONAL_WEATHER_CACHE.get(cache_k)
        if cached_reg is not None and (time.monotonic() - cached_reg[0]) <= 300.0:
            return cached_reg[1]
        try:
            rurl = "https://api.open-meteo.com/v1/forecast?" + urllib_parse.urlencode({
                "latitude": ",".join(f"{pt['lat']:.3f}" for pt in regional_pts),
                "longitude": ",".join(f"{pt['lon']:.3f}" for pt in regional_pts),
                "current": "temperature_2m,weather_code,wind_speed_10m,wind_direction_10m,cloud_cover,precipitation",
                "timezone": "auto",
            })
            raw_j = _fetch_bytes(rurl)
            parsed = json.loads(raw_j.decode("utf-8", errors="replace"))
            if isinstance(parsed, dict) and len(regional_pts) == 1:
                parsed = [parsed]
            if not isinstance(parsed, list):
                return []
            enriched: list[dict[str, Any]] = []
            for pt, wrow in zip(regional_pts, parsed):
                if not isinstance(wrow, dict):
                    continue
                rc = wrow.get("current") or {}
                if rc.get("temperature_2m") is None:
                    continue
                enriched.append({**pt, **rc})
            if enriched:
                if len(_REGIONAL_WEATHER_CACHE) >= 32:
                    _REGIONAL_WEATHER_CACHE.clear()
                _REGIONAL_WEATHER_CACHE[cache_k] = (time.monotonic(), enriched)
            return enriched
        except Exception:
            return cached_reg[1] if cached_reg is not None else []

    wcode = int(cur.get("weather_code", -1)) if cur.get("weather_code") is not None else -1
    sky = _WMO_WEATHER_CODES.get(wcode, "")
    temp = cur.get("temperature_2m", "?")
    feels = cur.get("apparent_temperature", "?")
    wind = cur.get("wind_speed_10m", "?")
    wind_deg = cur.get("wind_direction_10m")
    wind_dir = _deg_to_compass(wind_deg)
    gusts = cur.get("wind_gusts_10m")
    hum = cur.get("relative_humidity_2m", "?")
    precip_now = cur.get("precipitation")
    uv0 = (daily.get("uv_index_max") or [None])[0]
    hi0 = (daily.get("temperature_2m_max") or [None])[0]
    lo0 = (daily.get("temperature_2m_min") or [None])[0]
    sun_r0 = str((daily.get("sunrise") or [""])[0])[-5:]
    sun_s0 = str((daily.get("sunset") or [""])[0])[-5:]

    short_lbl = label.split("(")[0].strip()[:26].rstrip(" ,") or label[:26].rstrip(" ,")
    city_only = short_lbl.split(",")[0].strip() or short_lbl
    lohi_txt = f"  ·  L {lo0}° / H {hi0}°" if (lo0 is not None and hi0 is not None) else ""
    hdr_row1 = f"{short_lbl}  ·  {temp}°C (feels {feels}°C)  {sky}{lohi_txt}".strip()
    gust_part = f" (gusts {gusts})" if gusts is not None else ""
    wind_part = f"Wind {wind} km/h {wind_dir}{gust_part}".strip()
    sun_part = f"  ·  Sun {sun_r0}-{sun_s0}" if (sun_r0 and sun_s0) else ""
    rain_now_part = f"  ·  Rain {precip_now}mm" if precip_now is not None else ""
    hdr_row2 = f"{wind_part}  ·  RH {hum}%{rain_now_part}{sun_part}"

    ts_txt = (
        datetime.fromtimestamp(radar_ts, tz=timezone.utc).strftime("Radar %H:%M UTC")
        if radar_ts > 0
        else (f"Forecast {cur.get('time', 'Live')}" if cur.get("time") else "Live Radar")
    )
    attr_txt = f"{ts_txt} | ArcGIS Dark · RainViewer · Open-Meteo/BOM"
    legend_cols = [(56, 189, 248), (34, 197, 94), (250, 204, 21), (249, 115, 22), (239, 68, 68)]

    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", short_lbl)[:24] or "weather"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_fp = eff_out / f"weather_radar_{safe_slug}_{stamp}.png"

    base_loaded = 0
    radar_loaded = 0

    tile_jobs = [
        (row_i, col_i, cx + dx, cy + dy)
        for row_i, dy in enumerate(dy_list)
        for col_i, dx in enumerate(dx_list)
    ]
    base_tiles: dict[tuple[int, int], bytes] = {}
    ref_tiles: dict[tuple[int, int], bytes] = {}
    radar_tiles: dict[tuple[int, int], bytes] = {}
    regional_weather: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=10) as _tile_pool:
        base_futs = {
            _tile_pool.submit(_fetch_base_bytes, gx, gy): (row_i, col_i)
            for row_i, col_i, gx, gy in tile_jobs
        }
        ref_futs = {
            _tile_pool.submit(_fetch_ref_bytes, gx, gy): (row_i, col_i)
            for row_i, col_i, gx, gy in tile_jobs
        }
        radar_futs = (
            {
                _tile_pool.submit(_fetch_radar_bytes, gx, gy): (row_i, col_i)
                for row_i, col_i, gx, gy in tile_jobs
            }
            if radar_path
            else {}
        )
        reg_fut = _tile_pool.submit(_fetch_regional_weather)
        for fut in as_completed(base_futs):
            rc = base_futs[fut]
            try:
                base_tiles[rc] = fut.result() or b""
            except Exception:
                base_tiles[rc] = b""
        for fut in as_completed(ref_futs):
            rc = ref_futs[fut]
            try:
                ref_tiles[rc] = fut.result() or b""
            except Exception:
                ref_tiles[rc] = b""
        for fut in as_completed(radar_futs):
            rc = radar_futs[fut]
            try:
                radar_tiles[rc] = fut.result() or b""
            except Exception:
                radar_tiles[rc] = b""
        try:
            regional_weather = reg_fut.result() or []
        except Exception:
            regional_weather = []

    if use_pil:
        def _load_pil_font(sz: int, bold: bool = False):
            candidates = (
                ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf")
                if bold
                else ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf")
            )
            for fp_f in candidates:
                try:
                    return ImageFont.truetype(fp_f, size=sz)
                except Exception:
                    continue
            return ImageFont.load_default()

        font_hdr = _load_pil_font(12, bold=True)
        font_sub = _load_pil_font(11, bold=False)
        font_pin = _load_pil_font(11, bold=True)
        font_sm = _load_pil_font(10, bold=False)
        font_sm_b = _load_pil_font(10, bold=True)

        canvas = Image.new("RGBA", (768, canvas_h), (11, 15, 22, 255))
        map_layer = Image.new("RGBA", (768, canvas_h), (0, 0, 0, 0))
        for row_i, col_i, _gx, _gy in tile_jobs:
            px, py = col_i * 256, row_i * 256 + map_y_off
            raw_b = base_tiles.get((row_i, col_i), b"")
            if raw_b:
                try:
                    base_im = Image.open(io.BytesIO(raw_b)).convert("RGBA")
                    map_layer.alpha_composite(base_im, (px, py))
                    base_loaded += 1
                except Exception:
                    pass
            raw_ref = ref_tiles.get((row_i, col_i), b"")
            if raw_ref:
                try:
                    ref_im = Image.open(io.BytesIO(raw_ref)).convert("RGBA")
                    map_layer.alpha_composite(ref_im, (px, py))
                except Exception:
                    pass
            raw_r = radar_tiles.get((row_i, col_i), b"")
            if raw_r:
                try:
                    im = Image.open(io.BytesIO(raw_r)).convert("RGBA")
                    r, g, b, a = im.split()
                    a = a.point(lambda v: int(v * 0.72))
                    map_layer.alpha_composite(Image.merge("RGBA", (r, g, b, a)), (px, py))
                    radar_loaded += 1
                except Exception:
                    pass
        if base_loaded == 0 and radar_loaded == 0:
            return None

        # Crop map strictly to [map_top .. map_bottom] so it never bleeds into header/forecast panels
        map_crop = map_layer.crop((0, map_top, 768, map_bottom))
        canvas.alpha_composite(map_crop, (0, map_top))
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Soft cloud cover halos from regional Open-Meteo cloud_cover data
        cloud_overlay = Image.new("RGBA", (768, canvas_h), (0, 0, 0, 0))
        cdraw = ImageDraw.Draw(cloud_overlay, "RGBA")
        cloud_samples = list(regional_weather)
        if cur.get("cloud_cover") is not None:
            cloud_samples.append({"px": pin_px, "py": pin_py, "cloud_cover": cur.get("cloud_cover")})
        for pt in cloud_samples:
            try:
                cc = float(pt.get("cloud_cover") or 0.0)
            except (TypeError, ValueError):
                cc = 0.0
            if cc >= 20.0:
                px_c, py_c = int(pt["px"]), int(pt["py"])
                alpha_c = min(46, int(cc * 0.45))
                cdraw.ellipse((px_c - 64, py_c - 44, px_c + 64, py_c + 44), fill=(186, 200, 220, alpha_c))
        canvas.alpha_composite(cloud_overlay.crop((0, map_top, 768, map_bottom)), (0, map_top))
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Track occupied rectangles so badges never collide with each other or the primary city label
        placed_rects: list[tuple[int, int, int, int]] = [
            (pin_px - 34, pin_py - 22, pin_px + 34, pin_py + 22),  # primary pin + map label zone
            (0, map_bottom - 26, 768, map_bottom),                   # map legend bar
        ]

        def _overlaps(rx1: int, ry1: int, rx2: int, ry2: int) -> bool:
            for ax1, ay1, ax2, ay2 in placed_rects:
                if rx1 < ax2 + 4 and rx2 + 4 > ax1 and ry1 < ay2 + 4 and ry2 + 4 > ay1:
                    return True
            return False

        # Draw primary target pin + wind vector arrow + offset pill ABOVE-RIGHT so base map "Adelaide" stays readable
        draw.ellipse((pin_px - 12, pin_py - 12, pin_px + 12, pin_py + 12), fill=(34, 197, 94, 65), outline=(34, 197, 94, 235), width=2)
        draw.ellipse((pin_px - 4, pin_py - 4, pin_px + 4, pin_py + 4), fill=(255, 255, 255, 255), outline=(13, 17, 23, 255), width=1)
        if wind_deg is not None:
            _draw_pil_wind_arrow(draw, pin_px, pin_py, wind_deg, length=24, color=(56, 189, 248, 220))

        main_badge_txt = f"{city_only} · {temp}°C" if temp != "?" else short_lbl
        try:
            pb = draw.textbbox((0, 0), main_badge_txt, font=font_pin)
            lbl_w = max(78, (pb[2] - pb[0]) + 18)
        except Exception:
            lbl_w = max(84, int(len(main_badge_txt) * 6.8) + 18)
        bx = max(8, min(768 - lbl_w - 8, pin_px + 16))
        by = max(map_top + 6, pin_py - 42)
        if by + 22 > map_bottom - 28:
            by = map_top + 8
        draw.line((pin_px + 5, pin_py - 5, bx + 6, by + 21), fill=(59, 130, 246, 200), width=1)
        draw.rounded_rectangle((bx, by, bx + lbl_w, by + 22), radius=5, fill=(13, 17, 23, 236), outline=(59, 130, 246, 235), width=1)
        draw.text((bx + 9, by + 4), main_badge_txt, font=font_pin, fill=(240, 246, 252, 255))
        placed_rects.append((bx, by, bx + lbl_w, by + 22))

        # Draw surrounding regional temperature / wind badges
        for reg in regional_weather:
            rpx, rpy = int(reg["px"]), int(reg["py"])
            r_temp = reg.get("temperature_2m")
            if r_temp is None:
                continue
            r_name = str(reg.get("name") or "")
            t_str = f"{round(float(r_temp))}°" if isinstance(r_temp, (int, float)) else f"{r_temp}°"
            r_lbl = f"{r_name} {t_str}" if r_name not in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"} else f"{t_str}"
            try:
                tb = draw.textbbox((0, 0), r_lbl, font=font_sm_b)
                tw = (tb[2] - tb[0])
            except Exception:
                tw = len(r_lbl) * 6
            pill_w = tw + 30
            pill_h = 20
            rx1 = max(6, min(768 - pill_w - 6, rpx - pill_w // 2))
            ry1 = max(map_top + 4, min(map_bottom - 28 - pill_h, rpy - pill_h // 2))
            rx2, ry2 = rx1 + pill_w, ry1 + pill_h
            if _overlaps(rx1, ry1, rx2, ry2):
                continue
            placed_rects.append((rx1, ry1, rx2, ry2))
            t_col = _temp_badge_color(r_temp)
            draw.rounded_rectangle((rx1, ry1, rx2, ry2), radius=5, fill=(13, 17, 23, 218), outline=(51, 65, 85, 220), width=1)
            draw.ellipse((rx1 + 5, ry1 + 6, rx1 + 12, ry1 + 13), fill=(*t_col, 255))
            draw.text((rx1 + 15, ry1 + 3), r_lbl, font=font_sm_b, fill=(226, 232, 240, 255))
            _draw_pil_wind_arrow(draw, rx2 - 8, ry1 + 10, reg.get("wind_direction_10m"), length=9, color=(125, 211, 252, 230))

        # Top HUD Telemetry Header (0..header_h)
        draw.rectangle((0, 0, 768, header_h), fill=(11, 15, 22, 244))
        draw.line((0, header_h - 1, 768, header_h - 1), fill=(30, 41, 59, 255), width=1)
        draw.text((10, 4), hdr_row1[:92], font=font_hdr, fill=(248, 250, 252, 255))
        draw.text((10, 21), hdr_row2[:98], font=font_sm, fill=(148, 163, 184, 255))
        if uv0 is not None:
            uv_col = _uv_badge_color(uv0)
            uv_pill_txt = f"UV {uv0}"
            draw.rounded_rectangle((690, 6, 758, 30), radius=5, fill=(22, 27, 36, 255), outline=(*uv_col, 230), width=1)
            draw.text((700, 11), uv_pill_txt, font=font_pin, fill=(*uv_col, 255))

        # Rain radar attribution / legend strip inside bottom of map pane
        bar_y = map_bottom - 22
        draw.rectangle((0, bar_y, 768, map_bottom), fill=(11, 15, 22, 218))
        draw.text((10, bar_y + 4), "Rain:", font=font_sm, fill=(156, 163, 175, 255))
        for i, lc in enumerate(legend_cols):
            lx = 42 + i * 14
            draw.rectangle((lx, bar_y + 6, lx + 11, bar_y + 15), fill=(*lc, 235))
        draw.text((120, bar_y + 4), attr_txt[:108], font=font_sm, fill=(156, 163, 175, 255))

        if has_forecast_strip:
            # Next 12h Hourly Bar (458..488)
            draw.rectangle((0, 458, 768, 488), fill=(15, 20, 29, 255))
            draw.line((0, 458, 768, 458), fill=(33, 41, 56, 255), width=1)
            draw.line((0, 487, 768, 487), fill=(26, 33, 46, 255), width=1)
            h_times = hourly.get("time") or []
            h_temps = hourly.get("temperature_2m") or []
            h_probs = hourly.get("precipitation_probability") or []
            cur_ts_str = str(cur.get("time") or "")[:13]
            h_start = 0
            for hi_i, hts in enumerate(h_times):
                if str(hts)[:13] >= cur_ts_str:
                    h_start = hi_i
                    break
            h_items: list[str] = []
            for j in range(h_start, min(len(h_times), h_start + 12), 2):
                hh = str(h_times[j])[-5:]
                tt = h_temps[j] if j < len(h_temps) and h_temps[j] is not None else "?"
                pp = h_probs[j] if j < len(h_probs) and h_probs[j] is not None else 0
                tt_s = f"{round(float(tt))}°" if isinstance(tt, (int, float)) else f"{tt}°"
                h_items.append(f"{hh}  {tt_s} ({pp}%)")
            hourly_txt = ("Next 12h:   " + "   |   ".join(h_items)) if h_items else f"7-Day Outlook — {city_only}"
            draw.text((12, 466), hourly_txt[:118], font=font_sm_b, fill=(203, 213, 225, 255))

            # 7-Day Visual Forecast Cards (490..636)
            draw.rectangle((0, 488, 768, 640), fill=(11, 15, 22, 255))
            hi_vals = [float(d["hi"]) for d in forecast_days if d.get("hi") is not None]
            lo_vals = [float(d["lo"]) for d in forecast_days if d.get("lo") is not None]
            wk_max = max(hi_vals) if hi_vals else 30.0
            wk_min = min(lo_vals) if lo_vals else 10.0
            wk_span = max(2.0, wk_max - wk_min)

            card_w = 101
            card_gap = 6
            start_x = 12
            card_y1, card_y2 = 493, 633
            for d_idx, d_item in enumerate(forecast_days[:7]):
                cx1 = start_x + d_idx * (card_w + card_gap)
                cx2 = cx1 + card_w
                ccx = (cx1 + cx2) // 2
                border_col = (59, 130, 246, 220) if d_idx == 0 else (38, 48, 66, 230)
                bg_col = (20, 27, 38, 255) if d_idx == 0 else (16, 21, 30, 255)
                draw.rounded_rectangle((cx1, card_y1, cx2, card_y2), radius=7, fill=bg_col, outline=border_col, width=1)

                # Day title
                day_t = d_item["label"]
                try:
                    db = draw.textbbox((0, 0), day_t, font=font_pin)
                    draw.text((ccx - (db[2] - db[0]) // 2, card_y1 + 6), day_t, font=font_pin, fill=(248, 250, 252, 255))
                except Exception:
                    draw.text((cx1 + 10, card_y1 + 6), day_t, font=font_pin, fill=(248, 250, 252, 255))

                # Vector weather icon
                _draw_pil_weather_icon(draw, ccx, card_y1 + 38, int(d_item.get("code", 0)), scale=1.05)

                # Short sky label
                sky_s = str(d_item.get("sky") or "")
                try:
                    sb = draw.textbbox((0, 0), sky_s, font=font_sm)
                    draw.text((ccx - (sb[2] - sb[0]) // 2, card_y1 + 56), sky_s, font=font_sm, fill=(148, 163, 184, 255))
                except Exception:
                    draw.text((cx1 + 8, card_y1 + 56), sky_s, font=font_sm, fill=(148, 163, 184, 255))

                # Min / Max temperatures + week-relative temp bar
                lo_v, hi_v = d_item.get("lo"), d_item.get("hi")
                lo_s = f"{round(float(lo_v))}°" if isinstance(lo_v, (int, float)) else "?°"
                hi_s = f"{round(float(hi_v))}°" if isinstance(hi_v, (int, float)) else "?°"
                draw.text((cx1 + 10, card_y1 + 74), lo_s, font=font_pin, fill=(125, 211, 252, 255))
                try:
                    hb = draw.textbbox((0, 0), hi_s, font=font_pin)
                    draw.text((cx2 - 10 - (hb[2] - hb[0]), card_y1 + 74), hi_s, font=font_pin, fill=(251, 146, 60, 255))
                except Exception:
                    draw.text((cx2 - 34, card_y1 + 74), hi_s, font=font_pin, fill=(251, 146, 60, 255))

                bar_x1, bar_x2, bar_y_t = cx1 + 10, cx2 - 10, card_y1 + 93
                draw.rounded_rectangle((bar_x1, bar_y_t, bar_x2, bar_y_t + 5), radius=2, fill=(30, 41, 59, 255))
                if isinstance(lo_v, (int, float)) and isinstance(hi_v, (int, float)):
                    f1 = max(0.0, min(1.0, (float(lo_v) - wk_min) / wk_span))
                    f2 = max(f1 + 0.08, min(1.0, (float(hi_v) - wk_min) / wk_span))
                    bx_l = int(bar_x1 + f1 * (bar_x2 - bar_x1))
                    bx_r = max(bx_l + 6, int(bar_x1 + f2 * (bar_x2 - bar_x1)))
                    draw.rounded_rectangle((bx_l, bar_y_t, bx_r, bar_y_t + 5), radius=2, fill=(*_temp_badge_color(hi_v), 255))

                # Rain % & mm + UV
                pr = int(d_item.get("rain_prob") or 0)
                mm = float(d_item.get("rain_mm") or 0.0)
                rain_col = (56, 189, 248, 255) if pr >= 20 else (148, 163, 184, 255)
                rain_txt = f"Rain {pr}%" if mm <= 0.0 else f"{pr}% · {mm:.1f}mm"
                try:
                    rb = draw.textbbox((0, 0), rain_txt, font=font_sm)
                    draw.text((ccx - (rb[2] - rb[0]) // 2, card_y1 + 104), rain_txt, font=font_sm, fill=rain_col)
                except Exception:
                    draw.text((cx1 + 8, card_y1 + 104), rain_txt, font=font_sm, fill=rain_col)

                uv_d = d_item.get("uv")
                if uv_d is not None:
                    uv_dt = f"UV {float(uv_d):.1f}".rstrip("0").rstrip(".")
                    uv_dc = (*_uv_badge_color(uv_d), 240)
                    try:
                        ub = draw.textbbox((0, 0), uv_dt, font=font_sm)
                        draw.text((ccx - (ub[2] - ub[0]) // 2, card_y1 + 120), uv_dt, font=font_sm, fill=uv_dc)
                    except Exception:
                        draw.text((cx1 + 8, card_y1 + 120), uv_dt, font=font_sm, fill=uv_dc)

        canvas.save(str(out_fp), format="PNG")
    else:
        can_use_qfont = False
        try:
            from PySide6.QtCore import QRect, Qt
            from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QGuiApplication
            if (
                QGuiApplication.instance() is not None
                and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
            ):
                fams = QFontDatabase.families()
                can_use_qfont = bool(fams)
        except Exception:
            can_use_qfont = False

        qcanvas = QImage(768, canvas_h, QImage.Format.Format_ARGB32_Premultiplied)
        qcanvas.fill(QColor(11, 15, 22, 255))
        painter = QPainter(qcanvas)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.save()
            painter.setClipRect(0, map_top, 768, map_bottom - map_top)
            for row_i, col_i, _gx, _gy in tile_jobs:
                px, py = col_i * 256, row_i * 256 + map_y_off
                raw_b = base_tiles.get((row_i, col_i), b"")
                if raw_b:
                    qim = QImage.fromData(raw_b)
                    if not qim.isNull():
                        painter.setOpacity(1.0)
                        painter.drawImage(px, py, qim)
                        base_loaded += 1
                raw_ref = ref_tiles.get((row_i, col_i), b"")
                if raw_ref:
                    qref = QImage.fromData(raw_ref)
                    if not qref.isNull():
                        painter.setOpacity(1.0)
                        painter.drawImage(px, py, qref)
                raw_r = radar_tiles.get((row_i, col_i), b"")
                if raw_r:
                    qrad = QImage.fromData(raw_r)
                    if not qrad.isNull():
                        painter.setOpacity(0.72)
                        painter.drawImage(px, py, qrad)
                        radar_loaded += 1
            if base_loaded == 0 and radar_loaded == 0:
                painter.restore()
                return None

            painter.setOpacity(1.0)
            # Soft cloud cover halos from Open-Meteo cloud_cover data
            cloud_samples = list(regional_weather)
            if cur.get("cloud_cover") is not None:
                cloud_samples.append({"px": pin_px, "py": pin_py, "cloud_cover": cur.get("cloud_cover")})
            for pt in cloud_samples:
                try:
                    cc = float(pt.get("cloud_cover") or 0.0)
                except (TypeError, ValueError):
                    cc = 0.0
                if cc >= 20.0:
                    alpha_c = min(46, int(cc * 0.45))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(186, 200, 220, alpha_c))
                    painter.drawEllipse(int(pt["px"]) - 64, int(pt["py"]) - 44, 128, 88)

            placed_rects: list[tuple[int, int, int, int]] = [
                (pin_px - 34, pin_py - 22, pin_px + 34, pin_py + 22),
                (0, map_bottom - 26, 768, map_bottom),
            ]

            def _qt_overlaps(rx1: int, ry1: int, rx2: int, ry2: int) -> bool:
                for ax1, ay1, ax2, ay2 in placed_rects:
                    if rx1 < ax2 + 4 and rx2 + 4 > ax1 and ry1 < ay2 + 4 and ry2 + 4 > ay1:
                        return True
                return False

            # Primary target pin + wind vector + offset badge ABOVE-RIGHT (keeps base map city label readable)
            painter.setPen(QPen(QColor(34, 197, 94, 235), 2))
            painter.setBrush(QColor(34, 197, 94, 65))
            painter.drawEllipse(pin_px - 12, pin_py - 12, 24, 24)
            painter.setPen(QPen(QColor(13, 17, 23, 255), 1))
            painter.setBrush(QColor(255, 255, 255, 255))
            painter.drawEllipse(pin_px - 4, pin_py - 4, 8, 8)
            if wind_deg is not None:
                _draw_qt_wind_arrow(painter, pin_px, pin_py, wind_deg, length=24, qcolor=QColor(56, 189, 248, 225))

            main_badge_txt = f"{city_only} · {temp}°C" if temp != "?" else short_lbl
            font_hdr_q = QFont("Segoe UI", 9, QFont.Weight.Bold) if can_use_qfont else None
            font_sub_q = QFont("Segoe UI", 8) if can_use_qfont else None
            font_pin_q = QFont("Segoe UI", 8, QFont.Weight.DemiBold) if can_use_qfont else None
            font_sm_b_q = QFont("Segoe UI", 8, QFont.Weight.DemiBold) if can_use_qfont else None
            lbl_w = (QFontMetrics(font_pin_q).horizontalAdvance(main_badge_txt) + 18) if can_use_qfont else (len(main_badge_txt) * 6 + 16)
            lbl_w = max(78, int(lbl_w))
            bx = max(8, min(768 - lbl_w - 8, pin_px + 16))
            by = max(map_top + 6, pin_py - 42)
            if by + 22 > map_bottom - 28:
                by = map_top + 8

            painter.setPen(QPen(QColor(59, 130, 246, 200), 1))
            painter.drawLine(pin_px + 5, pin_py - 5, bx + 6, by + 21)
            painter.setPen(QPen(QColor(59, 130, 246, 235), 1))
            painter.setBrush(QColor(13, 17, 23, 236))
            painter.drawRoundedRect(bx, by, lbl_w, 22, 5.0, 5.0)
            placed_rects.append((bx, by, bx + lbl_w, by + 22))
            fg_light = QColor(248, 250, 252, 255)
            fg_muted = QColor(148, 163, 184, 255)
            if can_use_qfont and font_pin_q is not None:
                painter.setFont(font_pin_q)
                painter.setPen(fg_light)
                painter.drawText(QRect(bx, by, lbl_w, 22), Qt.AlignmentFlag.AlignCenter, main_badge_txt)
            else:
                _draw_qimage_bitmap_text(painter, bx + 7, by + 7, main_badge_txt, fg_light, scale=1)

            # Surrounding regional town/station badges with temp dot + wind arrow
            for reg in regional_weather:
                rpx, rpy = int(reg["px"]), int(reg["py"])
                r_temp = reg.get("temperature_2m")
                if r_temp is None:
                    continue
                r_name = str(reg.get("name") or "")
                t_str = f"{round(float(r_temp))}°" if isinstance(r_temp, (int, float)) else f"{r_temp}°"
                r_lbl = f"{r_name} {t_str}" if r_name not in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"} else f"{t_str}"
                tw = QFontMetrics(font_sm_b_q).horizontalAdvance(r_lbl) if (can_use_qfont and font_sm_b_q is not None) else (len(r_lbl) * 6)
                pill_w = int(tw) + 32
                pill_h = 20
                rx1 = max(6, min(768 - pill_w - 6, rpx - pill_w // 2))
                ry1 = max(map_top + 4, min(map_bottom - 28 - pill_h, rpy - pill_h // 2))
                rx2, ry2 = rx1 + pill_w, ry1 + pill_h
                if _qt_overlaps(rx1, ry1, rx2, ry2):
                    continue
                placed_rects.append((rx1, ry1, rx2, ry2))
                t_col = _temp_badge_color(r_temp)
                painter.setPen(QPen(QColor(51, 65, 85, 220), 1))
                painter.setBrush(QColor(13, 17, 23, 218))
                painter.drawRoundedRect(rx1, ry1, pill_w, pill_h, 5.0, 5.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(*t_col, 255))
                painter.drawEllipse(rx1 + 5, ry1 + 6, 7, 7)
                if can_use_qfont and font_sm_b_q is not None:
                    painter.setFont(font_sm_b_q)
                    painter.setPen(QColor(226, 232, 240, 255))
                    painter.drawText(QRect(rx1 + 15, ry1, int(tw) + 4, pill_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, r_lbl)
                else:
                    _draw_qimage_bitmap_text(painter, rx1 + 15, ry1 + 6, r_lbl, QColor(226, 232, 240, 255), scale=1)
                _draw_qt_wind_arrow(painter, rx2 - 9, ry1 + 10, reg.get("wind_direction_10m"), length=9, qcolor=QColor(125, 211, 252, 230))

            # Legend bar inside bottom of map pane
            bar_y = map_bottom - 22
            painter.fillRect(0, bar_y, 768, 22, QColor(11, 15, 22, 220))
            for i, lc in enumerate(legend_cols):
                painter.fillRect(42 + i * 14, bar_y + 6, 11, 9, QColor(*lc, 235))
            if can_use_qfont and font_sub_q is not None:
                painter.setFont(font_sub_q)
                painter.setPen(fg_muted)
                painter.drawText(QRect(10, bar_y, 32, 22), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Rain:")
                painter.drawText(QRect(120, bar_y, 640, 22), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, attr_txt[:108])
            else:
                _draw_qimage_bitmap_text(painter, 10, bar_y + 7, "Rain:", fg_muted, scale=1)
                _draw_qimage_bitmap_text(painter, 120, bar_y + 7, attr_txt[:102], fg_muted, scale=1)
            painter.restore()

            # Top Telemetry Header (0..header_h)
            painter.fillRect(0, 0, 768, header_h, QColor(11, 15, 22, 244))
            painter.setPen(QPen(QColor(30, 41, 59, 255), 1))
            painter.drawLine(0, header_h - 1, 768, header_h - 1)
            if can_use_qfont and font_hdr_q is not None and font_sub_q is not None:
                painter.setFont(font_hdr_q)
                painter.setPen(fg_light)
                painter.drawText(QRect(10, 2, 675, 19), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, hdr_row1[:92])
                painter.setFont(font_sub_q)
                painter.setPen(fg_muted)
                painter.drawText(QRect(10, 19, 675, 17), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, hdr_row2[:98])
            else:
                _draw_qimage_bitmap_text(painter, 10, 6, hdr_row1[:108], fg_light, scale=1)
                _draw_qimage_bitmap_text(painter, 10, 22, hdr_row2[:108], fg_muted, scale=1)
            if uv0 is not None:
                uv_col = _uv_badge_color(uv0)
                uv_pill_txt = f"UV {uv0}"
                painter.setPen(QPen(QColor(*uv_col, 230), 1))
                painter.setBrush(QColor(22, 27, 36, 255))
                painter.drawRoundedRect(690, 6, 68, 24, 5.0, 5.0)
                if can_use_qfont and font_pin_q is not None:
                    painter.setFont(font_pin_q)
                    painter.setPen(QColor(*uv_col, 255))
                    painter.drawText(QRect(690, 6, 68, 24), Qt.AlignmentFlag.AlignCenter, uv_pill_txt)
                else:
                    _draw_qimage_bitmap_text(painter, 698, 14, uv_pill_txt, QColor(*uv_col, 255), scale=1)

            if has_forecast_strip:
                # Next 12h Hourly Bar (458..488)
                painter.fillRect(0, 458, 768, 30, QColor(15, 20, 29, 255))
                painter.setPen(QPen(QColor(33, 41, 56, 255), 1))
                painter.drawLine(0, 458, 768, 458)
                painter.drawLine(0, 487, 768, 487)
                h_times = hourly.get("time") or []
                h_temps = hourly.get("temperature_2m") or []
                h_probs = hourly.get("precipitation_probability") or []
                cur_ts_str = str(cur.get("time") or "")[:13]
                h_start = 0
                for hi_i, hts in enumerate(h_times):
                    if str(hts)[:13] >= cur_ts_str:
                        h_start = hi_i
                        break
                h_items: list[str] = []
                for j in range(h_start, min(len(h_times), h_start + 12), 2):
                    hh = str(h_times[j])[-5:]
                    tt = h_temps[j] if j < len(h_temps) and h_temps[j] is not None else "?"
                    pp = h_probs[j] if j < len(h_probs) and h_probs[j] is not None else 0
                    tt_s = f"{round(float(tt))}°" if isinstance(tt, (int, float)) else f"{tt}°"
                    h_items.append(f"{hh}  {tt_s} ({pp}%)")
                hourly_txt = ("Next 12h:   " + "   |   ".join(h_items)) if h_items else f"7-Day Outlook — {city_only}"
                if can_use_qfont and font_sm_b_q is not None:
                    painter.setFont(font_sm_b_q)
                    painter.setPen(QColor(203, 213, 225, 255))
                    painter.drawText(QRect(12, 458, 744, 30), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, hourly_txt[:118])
                else:
                    _draw_qimage_bitmap_text(painter, 12, 469, hourly_txt[:118], QColor(203, 213, 225, 255), scale=1)

                # 7-Day Visual Forecast Cards (488..640)
                painter.fillRect(0, 488, 768, 152, QColor(11, 15, 22, 255))
                hi_vals = [float(d["hi"]) for d in forecast_days if d.get("hi") is not None]
                lo_vals = [float(d["lo"]) for d in forecast_days if d.get("lo") is not None]
                wk_max = max(hi_vals) if hi_vals else 30.0
                wk_min = min(lo_vals) if lo_vals else 10.0
                wk_span = max(2.0, wk_max - wk_min)

                card_w = 101
                card_gap = 6
                start_x = 12
                card_y1 = 493
                card_h = 140
                for d_idx, d_item in enumerate(forecast_days[:7]):
                    cx1 = start_x + d_idx * (card_w + card_gap)
                    ccx = cx1 + card_w // 2
                    b_col = QColor(59, 130, 246, 220) if d_idx == 0 else QColor(38, 48, 66, 230)
                    bg_c = QColor(20, 27, 38, 255) if d_idx == 0 else QColor(16, 21, 30, 255)
                    painter.setPen(QPen(b_col, 1))
                    painter.setBrush(bg_c)
                    painter.drawRoundedRect(cx1, card_y1, card_w, card_h, 7.0, 7.0)

                    day_t = d_item["label"]
                    sky_s = str(d_item.get("sky") or "")
                    lo_v, hi_v = d_item.get("lo"), d_item.get("hi")
                    lo_s = f"{round(float(lo_v))}°" if isinstance(lo_v, (int, float)) else "?°"
                    hi_s = f"{round(float(hi_v))}°" if isinstance(hi_v, (int, float)) else "?°"

                    if can_use_qfont and font_pin_q is not None and font_sub_q is not None:
                        painter.setFont(font_pin_q)
                        painter.setPen(fg_light)
                        painter.drawText(QRect(cx1 + 4, card_y1 + 4, card_w - 8, 18), Qt.AlignmentFlag.AlignCenter, day_t)
                    else:
                        _draw_qimage_bitmap_text(painter, cx1 + 10, card_y1 + 8, day_t, fg_light, scale=1)

                    _draw_qt_weather_icon(painter, ccx, card_y1 + 38, int(d_item.get("code", 0)), scale=1.05)

                    if can_use_qfont and font_sub_q is not None:
                        painter.setFont(font_sub_q)
                        painter.setPen(fg_muted)
                        painter.drawText(QRect(cx1 + 4, card_y1 + 55, card_w - 8, 16), Qt.AlignmentFlag.AlignCenter, sky_s)
                        painter.setFont(font_pin_q)
                        painter.setPen(QColor(125, 211, 252, 255))
                        painter.drawText(QRect(cx1 + 10, card_y1 + 72, 38, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lo_s)
                        painter.setPen(QColor(251, 146, 60, 255))
                        painter.drawText(QRect(cx1 + card_w - 48, card_y1 + 72, 38, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, hi_s)
                    else:
                        _draw_qimage_bitmap_text(painter, cx1 + 8, card_y1 + 58, sky_s, fg_muted, scale=1)
                        _draw_qimage_bitmap_text(painter, cx1 + 10, card_y1 + 76, lo_s, QColor(125, 211, 252, 255), scale=1)
                        _draw_qimage_bitmap_text(painter, cx1 + card_w - 30, card_y1 + 76, hi_s, QColor(251, 146, 60, 255), scale=1)

                    bar_x1 = cx1 + 10
                    bar_w = card_w - 20
                    bar_y_t = card_y1 + 94
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(30, 41, 59, 255))
                    painter.drawRoundedRect(bar_x1, bar_y_t, bar_w, 5, 2.0, 2.0)
                    if isinstance(lo_v, (int, float)) and isinstance(hi_v, (int, float)):
                        f1 = max(0.0, min(1.0, (float(lo_v) - wk_min) / wk_span))
                        f2 = max(f1 + 0.08, min(1.0, (float(hi_v) - wk_min) / wk_span))
                        bx_l = int(bar_x1 + f1 * bar_w)
                        bx_r = max(bx_l + 6, int(bar_x1 + f2 * bar_w))
                        painter.setBrush(QColor(*_temp_badge_color(hi_v), 255))
                        painter.drawRoundedRect(bx_l, bar_y_t, bx_r - bx_l, 5, 2.0, 2.0)

                    pr = int(d_item.get("rain_prob") or 0)
                    mm = float(d_item.get("rain_mm") or 0.0)
                    rain_col = QColor(56, 189, 248, 255) if pr >= 20 else fg_muted
                    rain_txt = f"Rain {pr}%" if mm <= 0.0 else f"{pr}% · {mm:.1f}mm"
                    uv_d = d_item.get("uv")
                    uv_dt = (f"UV {float(uv_d):.1f}".rstrip("0").rstrip(".")) if uv_d is not None else ""
                    uv_dc = QColor(*_uv_badge_color(uv_d), 240) if uv_d is not None else fg_muted

                    if can_use_qfont and font_sub_q is not None:
                        painter.setFont(font_sub_q)
                        painter.setPen(rain_col)
                        painter.drawText(QRect(cx1 + 4, card_y1 + 103, card_w - 8, 16), Qt.AlignmentFlag.AlignCenter, rain_txt)
                        if uv_dt:
                            painter.setPen(uv_dc)
                            painter.drawText(QRect(cx1 + 4, card_y1 + 119, card_w - 8, 16), Qt.AlignmentFlag.AlignCenter, uv_dt)
                    else:
                        _draw_qimage_bitmap_text(painter, cx1 + 8, card_y1 + 106, rain_txt, rain_col, scale=1)
                        if uv_dt:
                            _draw_qimage_bitmap_text(painter, cx1 + 8, card_y1 + 122, uv_dt, uv_dc, scale=1)
        finally:
            painter.end()
        if not qcanvas.save(str(out_fp), "PNG"):
            return None
    return out_fp if out_fp.is_file() else None


def _search_bing_rss(query: str, max_results: int = 8, angle: str = "general") -> list[WebSearchHit]:
    """Query Bing RSS feed (reliable XML web search without anti-bot HTML CAPTCHAs)."""
    hits: list[WebSearchHit] = []
    try:
        url = "https://www.bing.com/search?" + urllib_parse.urlencode({"q": query, "format": "rss"})
        req = urllib_request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FairybreadResearch/1.0"},
        )
        with urllib_request.urlopen(req, timeout=7.0) as resp:
            xml_bytes = resp.read(220_000)
        root = ET.fromstring(xml_bytes.decode("utf-8", errors="replace"))
        for item in root.findall(".//item")[:max_results]:
            title = _clean_html_to_text(item.findtext("title") or "", 160)
            link = (item.findtext("link") or "").strip()
            desc = _clean_html_to_text(item.findtext("description") or "", 320)
            if not link.startswith(("http://", "https://")):
                continue
            hits.append(
                WebSearchHit(
                    title=title or link,
                    url=link,
                    snippet=desc,
                    source="bing",
                    angle=angle,
                )
            )
    except Exception:
        pass
    return hits


def _search_duckduckgo_html(query: str, max_results: int = 8, angle: str = "general") -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    try:
        url = "https://html.duckduckgo.com/html/?" + urllib_parse.urlencode({"q": query})
        req = urllib_request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FairybreadResearch/1.0"},
        )
        with urllib_request.urlopen(req, timeout=7.0) as resp:
            if getattr(resp, "status", 200) != 200:
                return _search_bing_rss(query, max_results=max_results, angle=angle)
            page = resp.read(180_000).decode("utf-8", errors="replace")
        blocks = re.findall(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<a[^>]+class="result__snippet"[^>]*>(.*?)</a>)?',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for href, raw_title, raw_snip in blocks[:max_results]:
            real_url = html.unescape(href)
            if "uddg=" in real_url:
                parsed = urllib_parse.parse_qs(urllib_parse.urlparse(real_url).query)
                if parsed.get("uddg"):
                    real_url = parsed["uddg"][0]
            if not real_url.startswith(("http://", "https://")):
                continue
            hits.append(
                WebSearchHit(
                    title=_clean_html_to_text(raw_title, 160),
                    url=real_url,
                    snippet=_clean_html_to_text(raw_snip or "", 320),
                    source="web",
                    angle=angle,
                )
            )
    except Exception:
        pass
    if not hits:
        return _search_bing_rss(query, max_results=max_results, angle=angle)
    return hits


def _search_wikipedia_api(query: str, max_results: int = 4, angle: str = "reference") -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    try:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "utf8": "1",
            "format": "json",
            "srlimit": str(max_results),
        }
        url = "https://en.wikipedia.org/w/api.php?" + urllib_parse.urlencode(params)
        req = urllib_request.Request(url, headers={"User-Agent": "FairybreadResearch/1.0"})
        with urllib_request.urlopen(req, timeout=6.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("query", {}).get("search", [])[:max_results]:
            title = str(item.get("title") or "")
            page_url = f"https://en.wikipedia.org/wiki/{urllib_parse.quote(title.replace(' ', '_'))}"
            hits.append(
                WebSearchHit(
                    title=f"{title} (Wikipedia)",
                    url=page_url,
                    snippet=_clean_html_to_text(str(item.get("snippet") or ""), 320),
                    source="wikipedia",
                    angle=angle,
                )
            )
    except Exception:
        pass
    return hits


def _search_hn_algolia(query: str, max_results: int = 5, angle: str = "community") -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    try:
        params = {"query": query, "tags": "story", "hitsPerPage": str(max_results)}
        url = "https://hn.algolia.com/api/v1/search?" + urllib_parse.urlencode(params)
        req = urllib_request.Request(url, headers={"User-Agent": "FairybreadResearch/1.0"})
        with urllib_request.urlopen(req, timeout=6.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("hits", [])[:max_results]:
            title = str(item.get("title") or "")
            target_url = str(item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID', '')}")
            pts = item.get("points", 0)
            cmts = item.get("num_comments", 0)
            hits.append(
                WebSearchHit(
                    title=title,
                    url=target_url,
                    snippet=f"HackerNews discussion ({pts} points, {cmts} comments)",
                    source="hackernews",
                    angle=angle,
                )
            )
    except Exception:
        pass
    return hits


def build_query_angles(base_query: str, depth: str) -> list[tuple[str, str]]:
    clean = re.sub(r"\s+", " ", (base_query or "").strip())[:140]
    if depth == "light":
        return [("primary", clean)]
    if depth == "moderate":
        return [
            ("primary", clean),
            ("technical", f"{clean} documentation architecture implementation"),
            ("community", f"{clean} review comparison issues"),
        ]
    # Deep search: 5 orthogonal research angles
    return [
        ("primary", clean),
        ("technical", f"{clean} technical specification documentation github"),
        ("architecture", f"{clean} guide best practices benchmarks"),
        ("contrarian", f"{clean} limitations problems failure modes edge cases"),
        ("community", f"{clean} discussion alternatives experience"),
    ]


def run_multi_tier_search(
    question: str,
    depth: str = "light",
    active_providers: list[str] | None = None,
) -> ShardedSearchBundle:
    """Execute a 3-tier web search ('light', 'moderate', or 'deep') with URL deduplication,
    optional full-page extraction, and non-overlapping per-agent shard assignment.
    """
    norm_depth = (depth or "light").strip().lower()
    if norm_depth not in {"light", "moderate", "deep"}:
        norm_depth = "light"

    angles = build_query_angles(question, norm_depth)
    raw_hits: list[WebSearchHit] = []
    ds_search_key = _get_deepseek_tools_api_key()

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = []
        if ds_search_key and angles:
            futs.append(ex.submit(_search_deepseek_api, angles[0][1], 8, "primary", api_key=ds_search_key))
        if angles:
            futs.append(ex.submit(_search_bing_rss, angles[0][1], 8, "primary"))
        for angle_name, q_str in angles:
            per_q_max = 8 if norm_depth == "light" else (7 if norm_depth == "moderate" else 8)
            futs.append(ex.submit(_search_duckduckgo_html, q_str, per_q_max, angle_name))
        futs.append(ex.submit(_search_wikipedia_api, question[:100], 3 if norm_depth == "light" else 5, "reference"))
        if norm_depth in {"moderate", "deep"}:
            futs.append(ex.submit(_search_hn_algolia, question[:100], 4 if norm_depth == "moderate" else 6, "community"))
        for f in as_completed(futs):
            try:
                raw_hits.extend(f.result() or [])
            except Exception:
                pass

    # Deduplicate by normalized URL
    deduped: list[WebSearchHit] = []
    seen_urls: set[str] = set()
    for h in raw_hits:
        u_key = h.url.rstrip("/").lower()
        if not u_key or u_key in seen_urls:
            continue
        seen_urls.add(u_key)
        deduped.append(h)

    max_total = 8 if norm_depth == "light" else (16 if norm_depth == "moderate" else 28)
    deduped = deduped[:max_total]

    # Full-page extraction for Moderate (top 6 pages) and Deep (top 16 pages)
    pages_to_fetch = 0 if norm_depth == "light" else (6 if norm_depth == "moderate" else 16)
    fetched_count = 0
    if pages_to_fetch > 0 and deduped:
        target_slice = deduped[:pages_to_fetch]
        with ThreadPoolExecutor(max_workers=8) as ex:
            url_to_fut = {
                ex.submit(fetch_page_clean_text, h.url, 2000 if norm_depth == "moderate" else 2400): h
                for h in target_slice
            }
            for fut in as_completed(url_to_fut):
                hit_obj = url_to_fut[fut]
                try:
                    body = fut.result() or ""
                    if body:
                        hit_obj.extracted_body = body
                        fetched_count += 1
                except Exception:
                    pass

    def _format_hit(idx: int, h: WebSearchHit) -> str:
        line = f"[{idx}] {h.title} ({h.angle}) — {h.url}\n    Snippet: {h.snippet}"
        if h.extracted_body:
            line += f"\n    Extracted Page Content: {h.extracted_body}"
        return line

    shared_lines = [
        f"=== WEB SEARCH EVIDENCE DOSSIER (Depth: {norm_depth.upper()} | Unique Sites: {len(deduped)} | Full Pages Extracted: {fetched_count}) ==="
    ]
    for i, h in enumerate(deduped, 1):
        shared_lines.append(_format_hit(i, h))
    shared_summary = "\n\n".join(shared_lines)

    # Sharded assignment across active council providers so in Moderate/Deep mode each AI gets a distinct slice!
    providers = list(active_providers or [])
    agent_shards: dict[str, str] = {}
    if len(providers) <= 1 or norm_depth == "light" or len(deduped) <= 4:
        for p in providers:
            agent_shards[p] = shared_summary
    else:
        n_prov = len(providers)
        for p_idx, p_name in enumerate(providers):
            my_hits = [h for i, h in enumerate(deduped) if i % n_prov == p_idx]
            if not my_hits:
                my_hits = deduped[:3]
            shard_lines = [
                f"=== SHARDED WEB SEARCH SLICE FOR {p_name.upper()} (Depth: {norm_depth.upper()} | Your Assigned Sites: {len(my_hits)} of {len(deduped)} total) ===",
                "Note: Other council peers are simultaneously analyzing the remaining non-overlapping websites. Cite your assigned URLs clearly so the Synthesizer can merge all slices.",
            ]
            for i, h in enumerate(my_hits, 1):
                shard_lines.append(_format_hit(i, h))
            agent_shards[p_name] = "\n\n".join(shard_lines)

    return ShardedSearchBundle(
        depth=norm_depth,
        base_query=question,
        queries_executed=[q for _, q in angles],
        total_hits=len(deduped),
        pages_fetched=fetched_count,
        hits=deduped,
        agent_shards=agent_shards,
        shared_summary=shared_summary,
    )
