"""3-Tier Hybrid & Sharded Web Search Engine for Fairybread (Default Light, Moderate /msearch, Deep /deepsearch)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import html
import json
import re
from typing import Any
from urllib import parse as urllib_parse, request as urllib_request


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
    r"(?:^|(?<=\s))/(autopatch|code|tangent|fullrender|single|searchd|deepsearch|searchm|msearch|search)(?=\b|\s|$|[.,!?;:])",
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

_NATURAL_AUTOPATCH_RE = re.compile(
    r"\b(?:autopatch|auto[\s-]+patch(?:es|ing)?|apply\s+(?:the\s+|experimental\s+mode\s+)?patch(?:es)?|apply\s+for\s+real|self[\s-]+deploy)\b",
    re.IGNORECASE,
)

_TERSE_CONFIRM_RE = re.compile(
    r"^\s*(?:apply|proceed|go(?:\s+ahead)?|do\s+it|deploy|yes|ok|approved?)\b",
    re.IGNORECASE,
)


def is_terse_patch_confirmation(text: str) -> bool:
    """Return True if the user message starts with or is a concise confirmation synonym (Apply, Proceed, Go, Do it, etc.)."""
    clean = (text or "").strip()
    if not clean:
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

    def _strip_restore(m: re.Match) -> str:
        nonlocal restore_target
        found_cmds.add("restore")
        arg = (m.group(1) or "").strip().lower()
        restore_target = arg if arg else "previous"
        return ""

    user_part = _RESTORE_COMMAND_RE.sub(_strip_restore, user_part)

    def _strip_cmd(m: re.Match) -> str:
        found_cmds.add(m.group(1).lower())
        return ""

    cleaned_user = _INLINE_COMMAND_RE.sub(_strip_cmd, user_part).strip()
    cleaned_user = re.sub(r"[ \t]{2,}", " ", cleaned_user).strip(" ,")
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

    final_q = (cleaned_user + att_tail) if att_tail else cleaned_user
    return {
        "cleaned_question": final_q,
        "search_depth": resolved_depth,
        "autopatch": autopatch,
        "include_code": include_code,
        "tangent": tangent,
        "full_render": full_render,
        "restore_target": restore_target,
        "commands": sorted(found_cmds),
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


def _search_duckduckgo_html(query: str, max_results: int = 8, angle: str = "general") -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    try:
        url = "https://html.duckduckgo.com/html/?" + urllib_parse.urlencode({"q": query})
        req = urllib_request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FairybreadResearch/1.0"},
        )
        with urllib_request.urlopen(req, timeout=7.0) as resp:
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

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = []
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
