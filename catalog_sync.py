"""Live model catalog, pricing rate auto-sync, and verified release update checker for Fairybread.

Fetches a static data-only JSON manifest (default: https://fairybread.me/feed/catalog.json)
using zero telemetry, strict schema validation, ETag + 6-hour local caching, and offline fallback.
App code updates require explicit user click and SHA-256 verification before launch.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from palace_config import (
    CONFIG_PATH,
    FAIRYBREAD_VERSION,
    PROVIDER_CATALOG,
    get_appdata_root,
    get_palace_data_root,
    is_msix_packaged,
    load_ui_settings,
)


DEFAULT_CATALOG_FEED_URL = "https://fairybread.me/feed/catalog.json"
DEFAULT_RELEASES_URL = "https://github.com/bm069au/fairybread/releases/latest"
CATALOG_SCHEMA_VERSION = 1
CACHE_TTL_SECONDS = 6 * 3600

_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?([a-z]*)\s*$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_version_tuple(version_str: str) -> tuple[int, int, int, str]:
    """Parse Fairybread version strings ('0.9.1', 'v0.9.1g', '0.9.2a') into a sortable tuple."""
    clean = str(version_str or "").strip()
    m = _VERSION_RE.match(clean)
    if not m:
        return (0, 0, 0, clean.lower())
    major = int(m.group(1) or 0)
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    suffix = str(m.group(4) or "").lower()
    return (major, minor, patch, suffix)


def compare_versions(v_a: str, v_b: str) -> int:
    """Return -1 if v_a < v_b, 0 if equal, 1 if v_a > v_b."""
    ta = parse_version_tuple(v_a)
    tb = parse_version_tuple(v_b)
    if ta < tb:
        return -1
    if ta > tb:
        return 1
    return 0


def _valid_float(val: Any, *, max_val: float) -> float | None:
    if isinstance(val, bool):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f) or f < 0.0 or f > max_val:
        return None
    return f


def validate_catalog_payload(payload: Any) -> dict[str, Any]:
    """Strictly sanitize an untrusted remote catalog dict into whitelisted data fields only."""
    if not isinstance(payload, dict):
        return {}

    try:
        schema_ver = int(payload.get("schema_version", CATALOG_SCHEMA_VERSION))
    except (TypeError, ValueError):
        schema_ver = CATALOG_SCHEMA_VERSION

    updated_at = str(payload.get("updated_at") or "").strip()[:64]
    latest_ver = str(payload.get("latest_app_version") or "").strip()[:32]
    summary = str(payload.get("release_summary") or "").strip()[:600]

    dl_raw = str(payload.get("download_url") or "").strip()
    download_url = dl_raw if dl_raw.startswith("https://") else ""

    rel_raw = str(payload.get("release_page_url") or "").strip()
    release_page_url = rel_raw if rel_raw.startswith("https://") else DEFAULT_RELEASES_URL

    sha_raw = str(payload.get("installer_sha256") or "").strip().lower()
    installer_sha256 = sha_raw if _SHA256_RE.match(sha_raw) else ""

    token_rates: dict[str, tuple[float, float]] = {}
    raw_token_rates = payload.get("model_token_rates_per_1m")
    if isinstance(raw_token_rates, dict):
        for k, pair in raw_token_rates.items():
            key = str(k or "").strip().lower()
            if not key or not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            r_in = _valid_float(pair[0], max_val=10_000.0)
            r_out = _valid_float(pair[1], max_val=10_000.0)
            if r_in is not None and r_out is not None:
                token_rates[key] = (r_in, r_out)

    def _sanitize_scalar_rates(section_key: str) -> dict[str, float]:
        out: dict[str, float] = {}
        raw_sec = payload.get(section_key)
        if isinstance(raw_sec, dict):
            for k, val in raw_sec.items():
                key = str(k or "").strip().lower()
                fval = _valid_float(val, max_val=1_000.0)
                if key and fval is not None:
                    out[key] = fval
        return out

    prov_updates: dict[str, dict[str, Any]] = {}
    raw_provs = payload.get("provider_catalog_updates")
    if isinstance(raw_provs, dict):
        for p_key, p_val in raw_provs.items():
            pk = str(p_key or "").strip().lower()
            if not pk or not isinstance(p_val, dict):
                continue
            cleaned_p: dict[str, Any] = {}
            if isinstance(p_val.get("default_model"), str) and p_val["default_model"].strip():
                cleaned_p["default_model"] = p_val["default_model"].strip()[:120]
            if isinstance(p_val.get("suggested_models"), list):
                models: list[str] = []
                seen: set[str] = set()
                for item in p_val["suggested_models"]:
                    m = str(item or "").strip()[:120]
                    if m and m not in seen:
                        seen.add(m)
                        models.append(m)
                if models:
                    cleaned_p["suggested_models"] = models
            kurl = str(p_val.get("key_url") or "").strip()
            if kurl.startswith("https://"):
                cleaned_p["key_url"] = kurl
            if isinstance(p_val.get("billing_note"), str) and p_val["billing_note"].strip():
                cleaned_p["billing_note"] = p_val["billing_note"].strip()[:240]
            if cleaned_p:
                prov_updates[pk] = cleaned_p

    return {
        "schema_version": schema_ver,
        "updated_at": updated_at,
        "latest_app_version": latest_ver,
        "release_summary": summary,
        "download_url": download_url,
        "release_page_url": release_page_url,
        "installer_sha256": installer_sha256,
        "model_token_rates_per_1m": token_rates,
        "tts_cost_per_minute_usd": _sanitize_scalar_rates("tts_cost_per_minute_usd"),
        "stt_cost_per_minute_usd": _sanitize_scalar_rates("stt_cost_per_minute_usd"),
        "image_cost_per_render_usd": _sanitize_scalar_rates("image_cost_per_render_usd"),
        "provider_catalog_updates": prov_updates,
    }


def apply_catalog_overrides(catalog: dict[str, Any]) -> dict[str, int]:
    """Apply validated pricing rates and catalog models in memory (never touches user config files)."""
    clean = validate_catalog_payload(catalog)
    if not clean:
        return {"rates_updated": 0, "providers_updated": 0}

    import cost_service

    rates_updated = 0
    for k, pair in (clean.get("model_token_rates_per_1m") or {}).items():
        cost_service.MODEL_TOKEN_RATES_PER_1M[k] = pair
        rates_updated += 1
    for k, val in (clean.get("tts_cost_per_minute_usd") or {}).items():
        cost_service.TTS_COST_PER_MINUTE_USD[k] = val
        rates_updated += 1
    for k, val in (clean.get("stt_cost_per_minute_usd") or {}).items():
        cost_service.STT_COST_PER_MINUTE_USD[k] = val
        rates_updated += 1
    for k, val in (clean.get("image_cost_per_render_usd") or {}).items():
        cost_service.IMAGE_COST_PER_RENDER_USD[k] = val
        rates_updated += 1

    providers_updated = 0
    for pk, upd in (clean.get("provider_catalog_updates") or {}).items():
        if pk not in PROVIDER_CATALOG or not isinstance(upd, dict):
            continue
        target = PROVIDER_CATALOG[pk]
        changed = False
        for field in ("default_model", "suggested_models", "key_url", "billing_note"):
            if field in upd:
                target[field] = list(upd[field]) if isinstance(upd[field], list) else upd[field]
                changed = True
        if changed:
            providers_updated += 1

    return {"rates_updated": rates_updated, "providers_updated": providers_updated}


def export_bundled_catalog_json(
    *,
    download_url: str = "",
    installer_sha256: str = "",
    release_summary: str = "",
) -> str:
    """Export a clean catalog.json manifest from Fairybread's bundled pricing and provider defaults."""
    import cost_service

    provs_out: dict[str, dict[str, Any]] = {}
    for pk, meta in PROVIDER_CATALOG.items():
        provs_out[pk] = {
            "default_model": str(meta.get("default_model") or ""),
            "suggested_models": list(meta.get("suggested_models") or []),
            "key_url": str(meta.get("key_url") or ""),
            "billing_note": str(meta.get("billing_note") or ""),
        }

    doc = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_app_version": FAIRYBREAD_VERSION,
        "release_summary": release_summary or f"Fairybread Beta v{FAIRYBREAD_VERSION}",
        "download_url": download_url,
        "release_page_url": DEFAULT_RELEASES_URL,
        "installer_sha256": installer_sha256,
        "model_token_rates_per_1m": {
            k: [v[0], v[1]] for k, v in cost_service.MODEL_TOKEN_RATES_PER_1M.items()
        },
        "tts_cost_per_minute_usd": dict(cost_service.TTS_COST_PER_MINUTE_USD),
        "stt_cost_per_minute_usd": dict(cost_service.STT_COST_PER_MINUTE_USD),
        "image_cost_per_render_usd": dict(cost_service.IMAGE_COST_PER_RENDER_USD),
        "provider_catalog_updates": provs_out,
    }
    return json.dumps(doc, indent=2) + "\n"


def _default_fetcher(url: str, etag: str, timeout_sec: float) -> tuple[int, dict[str, Any] | None, str]:
    if not str(url or "").startswith("https://"):
        raise ValueError("Catalog feed URL must use https://")
    headers = {"User-Agent": "Fairybread", "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib_request.Request(url, headers=headers, method="GET")
    try:
        with urllib_request.urlopen(req, timeout=timeout_sec) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            new_etag = str(resp.headers.get("ETag") or etag or "").strip()
            raw_bytes = resp.read(2 * 1024 * 1024)
            data = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Catalog root must be a JSON object")
            return status, data, new_etag
    except urllib_error.HTTPError as exc:
        if exc.code == 304:
            return 304, None, etag
        raise


def _read_cache(cache_file: Path) -> dict[str, Any]:
    if not cache_file.is_file():
        return {}
    try:
        parsed = json.loads(cache_file.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _write_cache(cache_file: Path, *, fetched_at: float, etag: str, payload: dict[str, Any]) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "fetched_at": float(fetched_at),
                    "etag": str(etag or ""),
                    "payload": payload,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, cache_file)
    except OSError:
        pass


def sync_remote_catalog(
    *,
    config_path: Path = CONFIG_PATH,
    cache_path: Path | None = None,
    feed_url: str = DEFAULT_CATALOG_FEED_URL,
    current_version: str = FAIRYBREAD_VERSION,
    force: bool = False,
    timeout_sec: float = 3.0,
    fetcher: Callable[[str, str, float], tuple[int, dict[str, Any] | None, str]] | None = None,
) -> dict[str, Any]:
    """Refresh live model rates/lists and check for newer app releases without blocking or failing offline."""
    ui_cfg = load_ui_settings(config_path)
    if not force and not ui_cfg.get("auto_refresh_catalog", True):
        return {
            "ok": True,
            "skipped": True,
            "source": "disabled",
            "current_version": current_version,
            "latest_app_version": "",
            "update_available": False,
            "has_newer_version": False,
            "release_summary": "",
            "download_url": "",
            "release_page_url": DEFAULT_RELEASES_URL,
            "installer_sha256": "",
            "updated_at": "",
            "rates_updated": 0,
            "providers_updated": 0,
            "error": "",
        }

    cache_file = cache_path or (get_palace_data_root(config_path) / "remote_catalog_cache.json")
    cached = _read_cache(cache_file)
    cached_payload = validate_catalog_payload(cached.get("payload")) if cached.get("payload") else {}
    try:
        fetched_at = float(cached.get("fetched_at") or 0.0)
    except (TypeError, ValueError):
        fetched_at = 0.0
    etag = str(cached.get("etag") or "").strip()

    now = time.time()
    source = "offline_fallback"
    active_payload: dict[str, Any] = cached_payload
    err_msg = ""

    if not force and cached_payload and (now - fetched_at) < CACHE_TTL_SECONDS:
        source = "cache"
    else:
        fn = fetcher or _default_fetcher
        try:
            status, net_data, new_etag = fn(feed_url, etag, float(timeout_sec))
            if status == 304 and cached_payload:
                source = "not_modified"
                active_payload = cached_payload
                _write_cache(cache_file, fetched_at=now, etag=new_etag or etag, payload=cached_payload)
            elif status == 200 and isinstance(net_data, dict):
                clean = validate_catalog_payload(net_data)
                if clean:
                    source = "network"
                    active_payload = clean
                    _write_cache(cache_file, fetched_at=now, etag=new_etag, payload=clean)
                else:
                    err_msg = "Remote catalog payload was invalid."
            else:
                err_msg = f"Unexpected catalog response status: {status}"
        except Exception as exc:
            err_msg = str(exc)

    applied = apply_catalog_overrides(active_payload) if active_payload else {"rates_updated": 0, "providers_updated": 0}
    store_managed = bool(is_msix_packaged())
    latest_ver = str(active_payload.get("latest_app_version") or "").strip()
    dismissed = str(ui_cfg.get("dismissed_update_version") or "").strip()
    has_newer = (False if store_managed else (bool(latest_ver) and compare_versions(latest_ver, current_version) > 0))
    is_dismissed = bool(has_newer and dismissed and compare_versions(latest_ver, dismissed) == 0)
    update_available = False if store_managed else bool(has_newer and (force or not is_dismissed))

    return {
        "ok": source != "offline_fallback" or bool(cached_payload),
        "skipped": False,
        "source": source,
        "current_version": current_version,
        "latest_app_version": "" if store_managed else latest_ver,
        "has_newer_version": has_newer,
        "update_available": update_available,
        "store_managed_updates": store_managed,
        "release_summary": "" if store_managed else str(active_payload.get("release_summary") or ""),
        "download_url": "" if store_managed else str(active_payload.get("download_url") or ""),
        "release_page_url": str(active_payload.get("release_page_url") or DEFAULT_RELEASES_URL),
        "installer_sha256": "" if store_managed else str(active_payload.get("installer_sha256") or ""),
        "updated_at": str(active_payload.get("updated_at") or ""),
        "rates_updated": applied["rates_updated"],
        "providers_updated": applied["providers_updated"],
        "error": err_msg,
    }


def _default_downloader(url: str, dest_part: Path, timeout_sec: float) -> None:
    req = urllib_request.Request(url, headers={"User-Agent": "Fairybread"}, method="GET")
    with urllib_request.urlopen(req, timeout=timeout_sec) as resp, dest_part.open("wb") as out_f:
        shutil.copyfileobj(resp, out_f, length=65536)


def _safe_filename_from_url(url: str) -> str:
    parsed = urllib_parse.urlparse(url)
    leaf = Path(urllib_parse.unquote(parsed.path)).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", leaf)
    return cleaned or "Fairybread_Installer_Setup.exe"


def download_and_verify_installer(
    download_url: str,
    dest_dir: Path,
    expected_sha256: str = "",
    *,
    timeout_sec: float = 45.0,
    downloader: Callable[[str, Path, float], None] | None = None,
) -> tuple[bool, str, Path | None]:
    """Download an https:// release archive to dest_dir, verify SHA-256, and remove unverified files."""
    clean_url = str(download_url or "").strip()
    if not clean_url.startswith("https://"):
        return False, "Download URL must start with https://", None

    exp_sha = str(expected_sha256 or "").strip().lower()
    if exp_sha and not _SHA256_RE.match(exp_sha):
        return False, "Expected SHA-256 checksum in manifest is invalid.", None

    dest_root = Path(dest_dir)
    dest_root.mkdir(parents=True, exist_ok=True)
    final_name = _safe_filename_from_url(clean_url)
    final_path = dest_root / final_name
    part_path = dest_root / f".{final_name}.part"

    try:
        if part_path.exists():
            part_path.unlink()
        dl_fn = downloader or _default_downloader
        dl_fn(clean_url, part_path, float(timeout_sec))
        if not part_path.is_file() or part_path.stat().st_size == 0:
            if part_path.exists():
                part_path.unlink()
            return False, "Downloaded installer file was empty.", None

        h = hashlib.sha256()
        with part_path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        actual_sha = h.hexdigest().lower()

        if exp_sha and actual_sha != exp_sha:
            part_path.unlink(missing_ok=True)
            return (
                False,
                f"SHA-256 mismatch (expected {exp_sha[:12]}…, got {actual_sha[:12]}…); file removed.",
                None,
            )

        os.replace(part_path, final_path)
        sha_note = f" (SHA-256 verified: {actual_sha[:12]}…)" if exp_sha else f" (SHA-256: {actual_sha[:12]}…)"
        return True, f"Downloaded to {final_path}{sha_note}", final_path
    except Exception as exc:
        try:
            part_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"Download failed: {exc}", None


def fetch_openrouter_credits(api_key: str, *, timeout: float = 6.0) -> dict[str, Any]:
    """Query OpenRouter remaining prepaid credits cleanly."""
    clean_key = str(api_key or "").strip()
    if not clean_key:
        return {"ok": False, "error": "Missing OpenRouter API key."}
    req = urllib_request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={
            "Authorization": f"Bearer {clean_key}",
            "Accept": "application/json",
            "User-Agent": "Fairybread",
        },
        method="GET",
    )
    try:
        with urllib_request.urlopen(req, timeout=float(timeout)) as resp:
            raw = json.loads(resp.read(262144).decode("utf-8", errors="replace"))
        data = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else (raw if isinstance(raw, dict) else {})
        total_credits = float(data.get("total_credits", 0.0) or 0.0)
        total_usage = float(data.get("total_usage", 0.0) or 0.0)
        remaining = max(0.0, total_credits - total_usage)
        return {
            "ok": True,
            "total_credits": round(total_credits, 6),
            "total_usage": round(total_usage, 6),
            "remaining_usd": round(remaining, 6),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def fetch_openrouter_live_catalog(
    *,
    timeout: float = 8.0,
    cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch OpenRouter's live /api/v1/models list and cache it locally."""
    eff_cache = Path(cache_path) if cache_path is not None else (get_appdata_root() / "openrouter_models_cache.json")
    try:
        req = urllib_request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Accept": "application/json", "User-Agent": "Fairybread"},
            method="GET",
        )
        with urllib_request.urlopen(req, timeout=float(timeout)) as resp:
            payload = json.loads(resp.read(8 * 1024 * 1024).decode("utf-8", errors="replace"))
        items = payload.get("data") if isinstance(payload, dict) else []
        if isinstance(items, list) and items:
            eff_cache.parent.mkdir(parents=True, exist_ok=True)
            eff_cache.write_text(json.dumps({"data": items}, ensure_ascii=False), encoding="utf-8")
            return [m for m in items if isinstance(m, dict)]
    except Exception:
        pass
    if eff_cache.is_file():
        try:
            cached = json.loads(eff_cache.read_text(encoding="utf-8", errors="replace"))
            items = cached.get("data") if isinstance(cached, dict) else []
            if isinstance(items, list):
                return [m for m in items if isinstance(m, dict)]
        except Exception:
            pass
    return []
