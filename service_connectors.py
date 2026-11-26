"""DPAPI-Backed App & Service API Connectors (Jellyfin, TMDB, Plex, Home Assistant, GitHub, Brave Search & Custom REST APIs).

All service API keys are stored encrypted in the local Windows DPAPI CredentialStore under `service:<service_id>`
and are NEVER injected into cloud LLM prompts. Fairybread executes service requests locally and returns sanitized results.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from credential_store import CredentialStore
from palace_config import CONFIG_PATH, _read_raw_config, _write_raw_config


AUTH_STYLE_CHOICES: list[tuple[str, str]] = [
    ("jellyfin", 'Jellyfin / Emby Header (X-Emby-Token & MediaBrowser Token)'),
    ("bearer", 'Bearer Token (Authorization: Bearer <key>)'),
    ("x_api_key", 'X-Api-Key Header (X-Api-Key: <key>)'),
    ("x_plex_token", 'Plex Header (X-Plex-Token: <key>)'),
    ("x_subscription_token", 'Brave Header (X-Subscription-Token: <key>)'),
    ("tmdb", 'TMDB (Bearer v4 Token or ?api_key= v3 Key)'),
    ("query_api_key", 'URL Query Parameter (?api_key=<key>)'),
]

SERVICE_CONNECTOR_CATALOG: dict[str, dict[str, Any]] = {
    "jellyfin": {
        "display_name": "🎬 Jellyfin Media Server",
        "default_base_url": "http://localhost:8096",
        "auth_style": "jellyfin",
        "key_url": "http://localhost:8096/web/index.html#/dashboard/keys",
        "test_path": "/System/Info",
        "is_custom": False,
        "description": (
            "Local Jellyfin media server — inspect server status, libraries, shows/movies/episodes, "
            "missing NFO metadata, or trigger library scans (Dashboard → Advanced → API Keys → + New API Key)."
        ),
    },
    "tmdb": {
        "display_name": "🎞️ TMDB (The Movie Database)",
        "default_base_url": "https://api.themoviedb.org/3",
        "auth_style": "tmdb",
        "key_url": "https://www.themoviedb.org/settings/api",
        "test_path": "/configuration",
        "is_custom": False,
        "description": "Canonical TV & movie metadata lookup (episode titles, air dates, plots, and TMDB/IMDB IDs for NFO files).",
    },
    "plex": {
        "display_name": "📺 Plex Media Server",
        "default_base_url": "http://localhost:32400",
        "auth_style": "x_plex_token",
        "key_url": "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/",
        "test_path": "/identity",
        "is_custom": False,
        "description": "Local Plex media server library inspection and refresh (X-Plex-Token).",
    },
    "home_assistant": {
        "display_name": "🏠 Home Assistant",
        "default_base_url": "http://homeassistant.local:8123",
        "auth_style": "bearer",
        "key_url": "http://homeassistant.local:8123/profile/security",
        "test_path": "/api/",
        "is_custom": False,
        "description": "Local Home Assistant smart-home states, sensors, and automation service calls (Long-Lived Access Token).",
    },
    "github": {
        "display_name": "🐙 GitHub API (Personal Access Token)",
        "default_base_url": "https://api.github.com",
        "auth_style": "bearer",
        "key_url": "https://github.com/settings/tokens",
        "test_path": "/user",
        "is_custom": False,
        "description": "GitHub REST API for repository, issue, pull request, and release inspection.",
    },
    "brave_search": {
        "display_name": "🔎 Brave Search API",
        "default_base_url": "https://api.search.brave.com",
        "auth_style": "x_subscription_token",
        "key_url": "https://api-dashboard.search.brave.com/app/keys",
        "test_path": "/res/v1/web/search?q=Fairybread&count=1",
        "is_custom": False,
        "description": "Optional commercial web search API index (X-Subscription-Token).",
    },
    "custom_1": {
        "display_name": "⚙ Custom Service 1 (Sonarr / Radarr / Local API)",
        "default_base_url": "http://localhost:8989",
        "auth_style": "x_api_key",
        "key_url": "",
        "test_path": "/",
        "is_custom": True,
        "description": "Custom local or web REST API slot 1 (set your own Name, Base URL, Auth style, and API key).",
    },
    "custom_2": {
        "display_name": "⚙ Custom Service 2",
        "default_base_url": "http://localhost:7878",
        "auth_style": "x_api_key",
        "key_url": "",
        "test_path": "/",
        "is_custom": True,
        "description": "Custom local or web REST API slot 2 (set your own Name, Base URL, Auth style, and API key).",
    },
    "custom_3": {
        "display_name": "⚙ Custom Service 3",
        "default_base_url": "http://localhost:8080",
        "auth_style": "bearer",
        "key_url": "",
        "test_path": "/",
        "is_custom": True,
        "description": "Custom local or web REST API slot 3 (set your own Name, Base URL, Auth style, and API key).",
    },
}


def get_service_cred_key(service_id: str) -> str:
    clean = str(service_id or "").strip().lower()
    return f"service:{clean}"


def load_service_connectors_config(config_path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    raw = _read_raw_config(config_path)
    saved = raw.get("service_connectors") if isinstance(raw.get("service_connectors"), dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for sid, meta in SERVICE_CONNECTOR_CATALOG.items():
        entry = saved.get(sid) if isinstance(saved.get(sid), dict) else {}
        out[sid] = {
            "enabled": bool(entry.get("enabled", True)),
            "base_url": str(entry.get("base_url") or meta["default_base_url"]).strip().rstrip("/"),
            "custom_name": str(entry.get("custom_name") or "").strip(),
            "auth_style": str(entry.get("auth_style") or meta["auth_style"]).strip().lower(),
        }
    return out


def save_service_connector_config(
    service_id: str,
    *,
    enabled: bool = True,
    base_url: str = "",
    custom_name: str = "",
    auth_style: str = "",
    config_path: Path = CONFIG_PATH,
) -> None:
    sid = str(service_id or "").strip().lower()
    if sid not in SERVICE_CONNECTOR_CATALOG:
        return
    meta = SERVICE_CONNECTOR_CATALOG[sid]
    raw = _read_raw_config(config_path)
    sec = raw.get("service_connectors")
    if not isinstance(sec, dict):
        sec = {}
    sec[sid] = {
        "enabled": bool(enabled),
        "base_url": str(base_url or meta["default_base_url"]).strip().rstrip("/"),
        "custom_name": str(custom_name or "").strip(),
        "auth_style": str(auth_style or meta["auth_style"]).strip().lower(),
    }
    raw["service_connectors"] = sec
    _write_raw_config(raw, config_path)


def is_service_connector_configured(
    service_id: str,
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
) -> bool:
    sid = str(service_id or "").strip().lower()
    if sid not in SERVICE_CONNECTOR_CATALOG:
        return False
    cfgs = load_service_connectors_config(config_path)
    entry = cfgs.get(sid, {})
    if not entry.get("enabled", True) or not entry.get("base_url"):
        return False
    store = credential_store or CredentialStore()
    return bool((store.get_api_key(get_service_cred_key(sid)) or "").strip())


def list_active_service_connectors(
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
) -> list[dict[str, Any]]:
    store = credential_store or CredentialStore()
    cfgs = load_service_connectors_config(config_path)
    active: list[dict[str, Any]] = []
    for sid, meta in SERVICE_CONNECTOR_CATALOG.items():
        entry = cfgs.get(sid, {})
        if not entry.get("enabled", True):
            continue
        has_k = bool((store.get_api_key(get_service_cred_key(sid)) or "").strip())
        if not has_k:
            continue
        disp = entry.get("custom_name") or meta["display_name"]
        active.append({
            "service_id": sid,
            "display_name": disp,
            "base_url": entry.get("base_url") or meta["default_base_url"],
            "auth_style": entry.get("auth_style") or meta["auth_style"],
            "description": meta["description"],
        })
    return active


def _build_service_request(
    service_id: str,
    *,
    method: str = "GET",
    path: str = "/",
    query_params: dict[str, Any] | None = None,
    json_body: Any = None,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
) -> urllib_request.Request:
    sid = str(service_id or "").strip().lower()
    if sid not in SERVICE_CONNECTOR_CATALOG:
        raise ValueError(f"Unknown service connector '{service_id}'.")
    meta = SERVICE_CONNECTOR_CATALOG[sid]
    cfgs = load_service_connectors_config(config_path)
    entry = cfgs.get(sid, {})
    base_url = str(entry.get("base_url") or meta["default_base_url"]).strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError(f"Service '{sid}' Base URL must start with http:// or https://.")
    store = credential_store or CredentialStore()
    api_key = (store.get_api_key(get_service_cred_key(sid)) or "").strip()
    if not api_key:
        raise ValueError(f"No API key configured for '{meta['display_name']}'. Add it in Options → Providers → Option 3.")

    clean_path = str(path or "/").strip()
    if not clean_path.startswith("/"):
        clean_path = "/" + clean_path
    full_url = base_url + clean_path

    params = dict(query_params or {})
    auth_style = str(entry.get("auth_style") or meta["auth_style"]).strip().lower()
    headers: dict[str, str] = {
        "User-Agent": "Fairybread/0.95",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.5",
    }

    if auth_style == "jellyfin":
        headers["X-Emby-Token"] = api_key
        headers["Authorization"] = (
            f'MediaBrowser Client="Fairybread", Device="WindowsPC", '
            f'DeviceId="FairybreadDesktop", Version="0.95", Token="{api_key}"'
        )
    elif auth_style == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_style == "x_api_key":
        headers["X-Api-Key"] = api_key
    elif auth_style == "x_plex_token":
        headers["X-Plex-Token"] = api_key
    elif auth_style == "x_subscription_token":
        headers["X-Subscription-Token"] = api_key
    elif auth_style == "tmdb":
        if len(api_key) > 45 or "." in api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            params["api_key"] = api_key
    elif auth_style == "query_api_key":
        params["api_key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    if params:
        sep = "&" if "?" in full_url else "?"
        full_url = full_url + sep + urllib_parse.urlencode(params)

    data_bytes = None
    if json_body is not None:
        data_bytes = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    return urllib_request.Request(full_url, data=data_bytes, headers=headers, method=method.upper())


def call_service_connector(
    service_id: str,
    *,
    method: str = "GET",
    path: str = "/",
    query_params: dict[str, Any] | None = None,
    json_body: Any = None,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Execute a local HTTP request against a configured service connector using its DPAPI-stored API key."""
    try:
        req = _build_service_request(
            service_id,
            method=method,
            path=path,
            query_params=query_params,
            json_body=json_body,
            config_path=config_path,
            credential_store=credential_store,
        )
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            raw = resp.read(512_000).decode("utf-8", errors="replace")
        parsed: Any = None
        if raw.strip().startswith(("{", "[")):
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
        return {
            "ok": 200 <= status < 300,
            "status_code": status,
            "data": parsed,
            "text": raw[:12_000],
            "error": "",
        }
    except urllib_error.HTTPError as exc:
        body_txt = ""
        try:
            body_txt = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            pass
        return {
            "ok": False,
            "status_code": int(exc.code),
            "data": None,
            "text": body_txt,
            "error": f"HTTP {exc.code}: {exc.reason} {body_txt[:240]}".strip(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": 0,
            "data": None,
            "text": "",
            "error": str(exc),
        }


def test_service_connector(
    service_id: str,
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Test connectivity and authentication for a configured service connector."""
    sid = str(service_id or "").strip().lower()
    if sid not in SERVICE_CONNECTOR_CATALOG:
        return {"ok": False, "summary": f"Unknown service '{service_id}'."}
    meta = SERVICE_CONNECTOR_CATALOG[sid]
    cfgs = load_service_connectors_config(config_path)
    entry = cfgs.get(sid, {})
    disp = entry.get("custom_name") or meta["display_name"]
    base_url = entry.get("base_url") or meta["default_base_url"]

    if sid == "jellyfin":
        info_res = call_service_connector(
            "jellyfin",
            method="GET",
            path="/System/Info",
            config_path=config_path,
            credential_store=credential_store,
            timeout=timeout,
        )
        if not info_res["ok"]:
            return {
                "ok": False,
                "summary": f"Jellyfin test failed at {base_url}: {info_res['error'] or 'Check server URL and API key.'}",
            }
        data = info_res.get("data") if isinstance(info_res.get("data"), dict) else {}
        srv_name = str(data.get("ServerName") or "Jellyfin").strip()
        ver = str(data.get("Version") or "?").strip()
        vf_res = call_service_connector(
            "jellyfin",
            method="GET",
            path="/Library/VirtualFolders",
            config_path=config_path,
            credential_store=credential_store,
            timeout=timeout,
        )
        libs: list[str] = []
        if vf_res["ok"] and isinstance(vf_res.get("data"), list):
            for item in vf_res["data"]:
                if isinstance(item, dict) and item.get("Name"):
                    libs.append(str(item["Name"]))
        lib_note = f" · Libraries ({len(libs)}): {', '.join(libs[:8])}" if libs else ""
        return {
            "ok": True,
            "summary": f"✓ Connected to Jellyfin v{ver} ({srv_name}) at {base_url}{lib_note}",
        }

    test_path = str(meta.get("test_path") or "/")
    res = call_service_connector(
        sid,
        method="GET",
        path=test_path,
        config_path=config_path,
        credential_store=credential_store,
        timeout=timeout,
    )
    if res["ok"]:
        return {"ok": True, "summary": f"✓ Connected to {disp} at {base_url} (HTTP {res['status_code']})"}
    return {"ok": False, "summary": f"Connection failed for {disp} at {base_url}: {res['error']}"}


def jellyfin_get_status(
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
) -> str:
    """Return a structured plain-text summary of the local Jellyfin server and its configured libraries."""
    info_res = call_service_connector(
        "jellyfin",
        method="GET",
        path="/System/Info",
        config_path=config_path,
        credential_store=credential_store,
    )
    if not info_res["ok"]:
        return f"[JELLYFIN ERROR]: {info_res['error']}"
    info = info_res.get("data") if isinstance(info_res.get("data"), dict) else {}
    vf_res = call_service_connector(
        "jellyfin",
        method="GET",
        path="/Library/VirtualFolders",
        config_path=config_path,
        credential_store=credential_store,
    )
    counts_res = call_service_connector(
        "jellyfin",
        method="GET",
        path="/Items/Counts",
        config_path=config_path,
        credential_store=credential_store,
    )
    counts = counts_res.get("data") if (counts_res["ok"] and isinstance(counts_res.get("data"), dict)) else {}
    lines = [
        f"[JELLYFIN SERVER STATUS]:",
        f"- Server Name: {info.get('ServerName', 'Jellyfin')}",
        f"- Version: {info.get('Version', '?')} (OS: {info.get('OperatingSystemDisplayName') or info.get('OperatingSystem', '?')})",
    ]
    if counts:
        lines.append(
            f"- Item Counts: Movies={counts.get('MovieCount', 0)}, Series={counts.get('SeriesCount', 0)}, "
            f"Episodes={counts.get('EpisodeCount', 0)}, Songs={counts.get('SongCount', 0)}"
        )
    if vf_res["ok"] and isinstance(vf_res.get("data"), list):
        lines.append("- Configured Libraries:")
        for vf in vf_res["data"]:
            if not isinstance(vf, dict):
                continue
            locs = ", ".join(str(x) for x in (vf.get("Locations") or []))
            lines.append(f"  * {vf.get('Name', '?')} (Type: {vf.get('CollectionType', 'mixed')} | Folders: {locs})")
    return "\n".join(lines)


def jellyfin_search_items(
    query: str,
    *,
    limit: int = 25,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
) -> str:
    """Search Jellyfin items (or fetch recent additions when query is 'recent'/'latest')."""
    clean_q = (query or "").strip()
    is_recent = clean_q.lower() in {"", "recent", "latest", "new", "all"}
    params: dict[str, Any] = {
        "Recursive": "true",
        "IncludeItemTypes": "Series,Movie,Season,Episode",
        "Fields": "Path,ProductionYear,Overview,ProviderIds",
        "Limit": str(max(1, min(100, int(limit or 25)))),
    }
    if is_recent:
        params["SortBy"] = "DateCreated"
        params["SortOrder"] = "Descending"
    else:
        params["SearchTerm"] = clean_q

    res = call_service_connector(
        "jellyfin",
        method="GET",
        path="/Items",
        query_params=params,
        config_path=config_path,
        credential_store=credential_store,
    )
    if not res["ok"]:
        return f"[JELLYFIN SEARCH ERROR]: {res['error']}"
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    items = data.get("Items") if isinstance(data.get("Items"), list) else []
    total = data.get("TotalRecordCount", len(items))
    header = (
        f"[JELLYFIN RECENT ITEMS (Showing {len(items)} of {total} total)]:"
        if is_recent
        else f"[JELLYFIN SEARCH RESULTS for '{clean_q}' (Showing {len(items)} of {total} matches)]:"
    )
    if not items:
        return f"{header}\nNo matching items found in Jellyfin."
    lines = [header]
    for idx, it in enumerate(items, 1):
        if not isinstance(it, dict):
            continue
        name = str(it.get("Name") or "Untitled")
        itype = str(it.get("Type") or "Item")
        year = it.get("ProductionYear")
        series_name = str(it.get("SeriesName") or "").strip()
        path_s = str(it.get("Path") or "").strip()
        pids = it.get("ProviderIds") if isinstance(it.get("ProviderIds"), dict) else {}
        pid_str = ", ".join(f"{k}={v}" for k, v in pids.items()) if pids else "none"
        label = f"{series_name} — {name}" if series_name else name
        yr_txt = f" ({year})" if year else ""
        lines.append(f"{idx}. [{itype}] {label}{yr_txt} | External IDs: {pid_str}" + (f" | Path: {path_s}" if path_s else ""))
    return "\n".join(lines)


def jellyfin_refresh_library(
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
) -> str:
    """Trigger a full Jellyfin library scan (`POST /Library/Refresh`)."""
    res = call_service_connector(
        "jellyfin",
        method="POST",
        path="/Library/Refresh",
        config_path=config_path,
        credential_store=credential_store,
    )
    if res["ok"]:
        return "[JELLYFIN REFRESH RESULT]: ✓ Successfully triggered Jellyfin library scan/refresh."
    return f"[JELLYFIN REFRESH ERROR]: {res['error']}"


def format_service_connectors_status_for_prompt(
    *,
    config_path: Path = CONFIG_PATH,
    credential_store: CredentialStore | None = None,
) -> str:
    """Return a prompt block informing Council AIs which local/web service APIs are active (never exposes keys)."""
    active = list_active_service_connectors(config_path=config_path, credential_store=credential_store)
    if not active:
        return (
            "=== [FAIRYBREAD APP & SERVICE API CONNECTORS] ===\n"
            "- No App/Service API connectors (such as Jellyfin, TMDB, Plex, or Home Assistant) have an API key saved yet.\n"
            "- If the user asks to connect Jellyfin or another external app API key, tell them to open "
            "`Tools → Options (Alt+F12) → Providers → AI Keys & Models` and scroll to "
            "`Option 3 — App & Service API Keys (Jellyfin, Media & Custom APIs)` to paste their key into the Windows DPAPI vault."
        )
    lines = [
        "=== [FAIRYBREAD APP & SERVICE API CONNECTORS — LIVE LOCAL TOOLS] ===",
        "The following user service APIs are authenticated in Fairybread's local Windows DPAPI vault (raw keys are kept private and injected locally by Fairybread):",
    ]
    for item in active:
        lines.append(f"- {item['display_name']} (`{item['service_id']}` at `{item['base_url']}`): {item['description']}")
    if any(x["service_id"] == "jellyfin" for x in active):
        lines.extend([
            "Jellyfin Silent Action Tags (put tag on its own line; Fairybread runs it locally and hands you the result to summarize in plain English):",
            "  * Check server info, item counts & library folders: `[JELLYFIN_STATUS]`",
            "  * Search shows/movies/episodes (or `query=\"recent\"` for newest additions): `[JELLYFIN_SEARCH query=\"...\"]`",
            "  * Trigger a Jellyfin library scan/refresh: `[JELLYFIN_REFRESH]`",
        ])
    lines.append(
        'Generic Service REST Call Tag (works for any configured service above): '
        '`[SERVICE_API service="<service_id>" method="GET" path="/endpoint"]`'
    )
    return "\n".join(lines)
