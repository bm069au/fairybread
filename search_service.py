"""3-Tier Hybrid & Sharded Web Search Engine for Fairybread (Default Light, Moderate /msearch, Deep /deepsearch)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    r"\b(?:weather|forecast|temperature|temp\b|rain(?:fall|ing)?|humidity|uv\s+index|wind\s+speed|bom\.gov)\b",
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


def fetch_page_clean_text(url: str, max_chars: int = 2400, timeout: float = 6.5) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
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
            return _clean_html_to_text(decoded, max_chars=max_chars)
    except Exception:
        return ""


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
    "for", "and", "in", "at", "of", "near", "around", "area", "code", "postcode", "post",
    "zip", "suburb", "city", "town", "please", "tell", "me", "give", "show", "check", "get",
    "fetch", "display", "pull", "look", "looking", "see", "find", "know", "bring", "send",
    "want", "need", "can", "you", "could", "would", "will", "does", "should", "going",
    "outside", "there", "here", "right", "latest", "local", "this", "that", "with", "from",
    "about", "have", "has", "been", "coming", "next", "days", "day", "week", "outlook",
    "temperature", "temp", "temps", "like", "how", "radar", "map", "maps", "rain", "raining",
    "wind", "windy", "humidity", "hourly", "conditions", "condition", "report", "update",
    "morning", "afternoon", "evening", "night", "storm", "storms", "sunny", "cloudy", "cold",
    "hot", "warm", "cool", "degree", "degrees", "celsius", "fahrenheit", "chance", "precip",
    "precipitation", "sunrise", "sunset", "time", "hey", "hi", "hello", "its", "it's",
    "over", "across", "out", "my", "our", "your", "any", "some", "just", "also", "still",
    "expected", "expecting", "supposed",
}

_WEATHER_PLACE_PREP_RE = re.compile(
    r"\b(?:for|in|at|near|around|of)\s+([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,3})",
    re.IGNORECASE,
)


def _extract_weather_place_candidates(raw: str) -> list[str]:
    """Extract clean place-name candidates, preferring preposition-anchored spans (e.g. 'for Port Adelaide')."""
    text = (raw or "").strip()
    if not text:
        return []
    candidate_names: list[str] = []
    seen_lower: set[str] = set()
    covered_tokens: set[str] = set()

    for m in _WEATHER_PLACE_PREP_RE.finditer(text):
        span_words = m.group(1).split()
        collected: list[str] = []
        started = False
        for tok in span_words:
            low = tok.lower()
            if low in _WEATHER_STOPWORDS:
                if not started:
                    continue
                break
            started = True
            collected.append(tok)
        phrase = " ".join(collected).strip()
        if len(phrase) >= 3 and phrase.lower() not in seen_lower:
            seen_lower.add(phrase.lower())
            candidate_names.append(phrase)
            for tok in collected:
                covered_tokens.add(tok.lower())

    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", text)
    for w in words:
        low = w.lower()
        if low in _WEATHER_STOPWORDS or len(w) < 3 or low in covered_tokens or low in seen_lower:
            continue
        seen_lower.add(low)
        candidate_names.append(w)

    return candidate_names[:3]


def _pick_best_geocoding_result(cname: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Reject phonetic geocoder mismatches (like 'show' -> 'Shut') and rank valid matches."""
    q_norm = re.sub(r"[^a-z0-9]+", " ", (cname or "").lower()).strip()
    q_tokens = q_norm.split()
    if not q_norm or not isinstance(results, list):
        return None
    best_item: dict[str, Any] | None = None
    best_key = (0, -1)
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
        try:
            pop = int(r.get("population") or 0)
        except (TypeError, ValueError):
            pop = 0
        rank_key = (score, pop)
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


def fetch_live_weather_bundle(question: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Resolve postcodes/cities via free Zippopotam + Open-Meteo APIs (BOM ACCESS-G in AU) with UV/gusts/hourly."""
    raw = (question or "").strip()
    empty = {"text": "", "locations": [], "primary_location": None, "primary_weather": {}}
    if not raw or not is_weather_query(raw):
        return empty

    locations: list[dict[str, Any]] = []
    seen_coords: set[tuple[float, float]] = set()

    def _add_loc(label: str, lat: float, lon: float) -> None:
        key = (round(float(lat), 2), round(float(lon), 2))
        if key in seen_coords:
            return
        seen_coords.add(key)
        locations.append({"label": label, "lat": float(lat), "lon": float(lon)})

    # 1. Resolve 4-digit postcodes (Australian default via Zippopotam)
    for pc in re.findall(r"\b(\d{4})\b", raw):
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

    # 2. Extract candidate place phrases / tokens (preposition-anchored first, mismatch-guarded)
    candidate_names = _extract_weather_place_candidates(raw)

    for cname in candidate_names[:3]:
        try:
            gurl = "https://geocoding-api.open-meteo.com/v1/search?" + urllib_parse.urlencode(
                {"name": cname, "count": 5, "language": "en", "format": "json"}
            )
            req = urllib_request.Request(gurl, headers={"User-Agent": "FairybreadWeather/1.0"})
            with urllib_request.urlopen(req, timeout=timeout) as resp:
                gdata = json.loads(resp.read().decode("utf-8"))
            res = (gdata.get("results") or [])
            top = _pick_best_geocoding_result(cname, res)
            if top is not None:
                lbl_parts = [str(top.get("name") or cname)]
                if top.get("admin1"):
                    lbl_parts.append(str(top["admin1"]))
                if top.get("country_code"):
                    lbl_parts.append(str(top["country_code"]))
                _add_loc(", ".join(lbl_parts), float(top["latitude"]), float(top["longitude"]))
        except Exception:
            pass

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
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation",
                "hourly": "temperature_2m,precipitation_probability,weather_code",
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


def _lat_lon_to_tile_xy(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_c = max(-85.0511, min(85.0511, float(lat)))
    n = 2.0 ** int(zoom)
    xtile = (float(lon) + 180.0) / 360.0 * n
    lat_rad = math.radians(lat_c)
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


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


def render_live_weather_map_png(
    location: dict[str, Any],
    weather_data: dict[str, Any] | None = None,
    *,
    out_dir: Path | None = None,
    cache_dir: Path | None = None,
    timeout: float = 5.0,
) -> Path | None:
    """Stitch a CartoDB Dark Matter base map + live RainViewer z=7 radar overlay + HUD via Pillow (or Qt fallback)."""
    global _RAINVIEWER_META_CACHE
    use_pil = True
    try:
        from PIL import Image, ImageDraw
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

    if out_dir is None:
        try:
            from palace_theme import get_generated_images_dir
            eff_out = get_generated_images_dir()
        except Exception:
            eff_out = eff_cache.parent
    else:
        eff_out = Path(out_dir)
    eff_out.mkdir(parents=True, exist_ok=True)

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
    pin_px = (1 * 256) + px_in_center
    pin_py = ((0 if dy_list[0] == 0 else 1) * 256) + py_in_center

    def _fetch_bytes(url: str) -> bytes:
        req = urllib_request.Request(url, headers={"User-Agent": "FairybreadWeatherMap/1.0"})
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

    def _fetch_base_bytes(gx: int, gy: int) -> bytes:
        if gy < 0 or gy >= n_tiles:
            return b""
        wx = gx % n_tiles
        tile_fp = eff_cache / f"carto_dark_{zoom}_{wx}_{gy}.png"
        if tile_fp.is_file() and tile_fp.stat().st_size > 100:
            try:
                return tile_fp.read_bytes()
            except OSError:
                pass
        url = f"https://a.basemaps.cartocdn.com/dark_all/{zoom}/{wx}/{gy}.png"
        try:
            raw_b = _fetch_bytes(url)
            if len(raw_b) > 100:
                tile_fp.write_bytes(raw_b)
            return raw_b
        except Exception:
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

    cur = ((weather_data or {}).get("current") or {}) if isinstance(weather_data, dict) else {}
    daily = ((weather_data or {}).get("daily") or {}) if isinstance(weather_data, dict) else {}
    wcode = int(cur.get("weather_code", -1)) if cur.get("weather_code") is not None else -1
    sky = _WMO_WEATHER_CODES.get(wcode, "")
    temp = cur.get("temperature_2m", "?")
    feels = cur.get("apparent_temperature", "?")
    wind = cur.get("wind_speed_10m", "?")
    hum = cur.get("relative_humidity_2m", "?")
    uv0 = (daily.get("uv_index_max") or [None])[0]
    uv_txt = f" | UV {uv0}" if uv0 is not None else ""
    short_lbl = label.split("(")[0].strip()[:26] or label[:26]
    top_txt = f"{short_lbl} · {temp}C (feels {feels}C) {sky} · Wind {wind} km/h · RH {hum}%{uv_txt}"
    ts_txt = (
        datetime.fromtimestamp(radar_ts, tz=timezone.utc).strftime("Radar %H:%M UTC")
        if radar_ts > 0
        else (f"Forecast {cur.get('time', 'Live')}" if cur.get("time") else "Live Radar")
    )
    attr_txt = f"{ts_txt}  |  Base: CARTO/OSM · Radar: RainViewer · Data: Open-Meteo/BOM"
    legend_cols = [(56, 189, 248), (34, 197, 94), (250, 204, 21), (249, 115, 22), (239, 68, 68)]
    lbl_w = max(70, len(short_lbl) * 6 + 14)
    bx = max(6, min(768 - lbl_w - 6, pin_px + 10))
    by = max(40, min(468, pin_py - 22))
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
    radar_tiles: dict[tuple[int, int], bytes] = {}
    with ThreadPoolExecutor(max_workers=6) as _tile_pool:
        base_futs = {
            _tile_pool.submit(_fetch_base_bytes, gx, gy): (row_i, col_i)
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
        for fut in as_completed(base_futs):
            rc = base_futs[fut]
            try:
                base_tiles[rc] = fut.result() or b""
            except Exception:
                base_tiles[rc] = b""
        for fut in as_completed(radar_futs):
            rc = radar_futs[fut]
            try:
                radar_tiles[rc] = fut.result() or b""
            except Exception:
                radar_tiles[rc] = b""

    if use_pil:
        canvas = Image.new("RGBA", (768, 512), (13, 17, 23, 255))
        for row_i, col_i, _gx, _gy in tile_jobs:
            px, py = col_i * 256, row_i * 256
            raw_b = base_tiles.get((row_i, col_i), b"")
            if raw_b:
                try:
                    base_im = Image.open(io.BytesIO(raw_b)).convert("RGBA")
                    canvas.alpha_composite(base_im, (px, py))
                    base_loaded += 1
                except Exception:
                    pass
            raw_r = radar_tiles.get((row_i, col_i), b"")
            if raw_r:
                try:
                    im = Image.open(io.BytesIO(raw_r)).convert("RGBA")
                    r, g, b, a = im.split()
                    a = a.point(lambda v: int(v * 0.72))
                    canvas.alpha_composite(Image.merge("RGBA", (r, g, b, a)), (px, py))
                    radar_loaded += 1
                except Exception:
                    pass
        if base_loaded == 0 and radar_loaded == 0:
            return None
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.ellipse((pin_px - 11, pin_py - 11, pin_px + 11, pin_py + 11), fill=(34, 197, 94, 70), outline=(34, 197, 94, 220), width=2)
        draw.ellipse((pin_px - 4, pin_py - 4, pin_px + 4, pin_py + 4), fill=(255, 255, 255, 255), outline=(13, 17, 23, 255), width=1)
        draw.rounded_rectangle((bx, by, bx + lbl_w, by + 18), radius=4, fill=(13, 17, 23, 215), outline=(59, 130, 246, 220), width=1)
        draw.text((bx + 6, by + 3), short_lbl, fill=(240, 246, 252, 255))
        draw.rectangle((0, 0, 768, 30), fill=(13, 17, 23, 225))
        draw.text((10, 8), top_txt[:118], fill=(240, 246, 252, 255))
        draw.rectangle((0, 484, 768, 512), fill=(13, 17, 23, 225))
        draw.text((10, 492), "Rain:", fill=(139, 148, 158, 255))
        for i, lc in enumerate(legend_cols):
            lx = 48 + i * 16
            draw.rectangle((lx, 494, lx + 13, 502), fill=(*lc, 235))
        draw.text((140, 492), attr_txt[:104], fill=(139, 148, 158, 255))
        canvas.save(str(out_fp), format="PNG")
    else:
        can_use_qfont = False
        try:
            from PySide6.QtCore import QRect, QThread
            from PySide6.QtGui import QFont, QGuiApplication
            _app = QGuiApplication.instance()
            if _app is not None and QThread.currentThread() == _app.thread():
                can_use_qfont = True
        except Exception:
            can_use_qfont = False

        qcanvas = QImage(768, 512, QImage.Format.Format_ARGB32_Premultiplied)
        qcanvas.fill(QColor(13, 17, 23, 255))
        painter = QPainter(qcanvas)
        try:
            for row_i, col_i, _gx, _gy in tile_jobs:
                px, py = col_i * 256, row_i * 256
                raw_b = base_tiles.get((row_i, col_i), b"")
                if raw_b:
                    qim = QImage.fromData(raw_b)
                    if not qim.isNull():
                        painter.setOpacity(1.0)
                        painter.drawImage(px, py, qim)
                        base_loaded += 1
                raw_r = radar_tiles.get((row_i, col_i), b"")
                if raw_r:
                    qrad = QImage.fromData(raw_r)
                    if not qrad.isNull():
                        painter.setOpacity(0.72)
                        painter.drawImage(px, py, qrad)
                        radar_loaded += 1
            if base_loaded == 0 and radar_loaded == 0:
                return None
            painter.setOpacity(1.0)
            painter.setPen(QPen(QColor(34, 197, 94, 220), 2))
            painter.setBrush(QColor(34, 197, 94, 70))
            painter.drawEllipse(pin_px - 11, pin_py - 11, 22, 22)
            painter.setPen(QPen(QColor(13, 17, 23, 255), 1))
            painter.setBrush(QColor(255, 255, 255, 255))
            painter.drawEllipse(pin_px - 4, pin_py - 4, 8, 8)
            painter.setPen(QPen(QColor(59, 130, 246, 220), 1))
            painter.setBrush(QColor(13, 17, 23, 215))
            painter.drawRoundedRect(bx, by, lbl_w, 18, 4.0, 4.0)
            painter.fillRect(0, 0, 768, 30, QColor(13, 17, 23, 225))
            painter.fillRect(0, 484, 768, 28, QColor(13, 17, 23, 225))
            for i, lc in enumerate(legend_cols):
                painter.fillRect(48 + i * 16, 494, 13, 8, QColor(*lc, 235))
            fg_light = QColor(240, 246, 252, 255)
            fg_muted = QColor(139, 148, 158, 255)
            if can_use_qfont:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(fg_light)
                painter.drawText(QRect(bx + 6, by + 1, lbl_w - 8, 16), 0x81, short_lbl)
                painter.drawText(QRect(10, 4, 748, 22), 0x81, top_txt[:118])
                painter.setPen(fg_muted)
                painter.drawText(QRect(10, 488, 36, 20), 0x81, "Rain:")
                painter.drawText(QRect(140, 488, 620, 20), 0x81, attr_txt[:104])
            else:
                _draw_qimage_bitmap_text(painter, bx + 6, by + 6, short_lbl, fg_light, scale=1)
                _draw_qimage_bitmap_text(painter, 10, 11, top_txt[:118], fg_light, scale=1)
                _draw_qimage_bitmap_text(painter, 10, 495, "Rain:", fg_muted, scale=1)
                _draw_qimage_bitmap_text(painter, 140, 495, attr_txt[:102], fg_muted, scale=1)
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

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = []
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
