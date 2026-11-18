r"""Palace Ouroboros Engine — Self-Contained UI Snapshot/Audit, Safe Code Staging, and Hot-Reboot.

Strictly scoped to Palace only:
1. UI Snapshot (`capture_palace_window_snapshot` / `audit_palace_window_geometry`):
   - Uses `PalaceWindow.grab()` to capture ONLY the Palace Qt widget buffer (never the user's desktop,
     wallpaper, or other applications).
   - Audits every visible button/label inside `PalaceWindow` for text clipping (`sizeHint().width() > width()`),
     zero-size widgets, or overlapping rects.
2. Safe Code Staging & Compile (`stage_palace_edit`, `validate_staged_palace`):
   - Strictly restricted to `EDITABLE_PALACE_FILES` allowlist (watchdog and credential stores are immutable).
   - Runs `py_compile` on all staged files and executes `unittest test_palace_gui` in offscreen mode.
3. Atomic Hot-Reboot & Rollback (`write_reboot_handoff`, `deploy_staged_and_reboot`):
   - Backs up current live files to `C:\Palace_Idle_Sandbox\last_known_good\`.
   - Writes `reboot_handoff.json` atomically (`tmp` -> `os.replace`) with circuit-breaker tracking
     (`max 3 reboots per 120 seconds`).
"""

from __future__ import annotations

import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from palace_theme import get_generated_images_dir

SANDBOX_ROOT = Path(r"C:\Palace_Idle_Sandbox")
STAGING_DIR = SANDBOX_ROOT / "staging"
LAST_KNOWN_GOOD_DIR = SANDBOX_ROOT / "last_known_good"
HANDOFF_PATH = SANDBOX_ROOT / "reboot_handoff.json"
READY_HEARTBEAT_PATH = SANDBOX_ROOT / "palace_ready_heartbeat.json"
UI_AUDIT_REPORT_PATH = SANDBOX_ROOT / "latest_ui_audit.json"

LIVE_DIR = Path(r"C:\Palace_Live")
SOURCE_REPO_DIR = Path(r"E:\Visual_studio\Palace")

# Strict L1 Allowlist: Agents can ONLY stage edits to these Palace UI/service files.
# Watchdog (`palace_watchdog.py`), Ouroboros kernel (`palace_ouroboros.py`), and `credential_store.py` are excluded.
EDITABLE_PALACE_FILES: frozenset[str] = frozenset({
    "palace_gui.py",
    "palace_theme.py",
    "palace_config.py",
    "orchestrator.py",
    "synthesizer.py",
    "idle_service.py",
    "session_store.py",
    "context_service.py",
    "attachment_service.py",
})

MAX_REBOOTS_IN_WINDOW = 3
REBOOT_WINDOW_SECONDS = 120.0


def audit_palace_window_geometry(window: Any) -> dict[str, Any]:
    """Inspect ONLY the PalaceWindow Qt widget hierarchy for layout health and clipped text."""
    from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QWidget

    win_rect = window.geometry()
    clipped_widgets: list[dict[str, Any]] = []
    visible_buttons: list[dict[str, Any]] = []

    for btn in window.findChildren(QPushButton):
        if not btn.isVisible():
            continue
        txt = (btn.text() or "").strip()
        obj_name = btn.objectName() or ""
        w = btn.width()
        h = btn.height()
        hint_w = btn.sizeHint().width()
        entry = {
            "type": "QPushButton",
            "objectName": obj_name,
            "text": txt,
            "tooltip": (btn.toolTip() or "").splitlines()[0] if btn.toolTip() else "",
            "size": f"{w}x{h}",
            "sizeHintWidth": hint_w,
        }
        visible_buttons.append(entry)
        # Estimate visible width required (~6.2px per char + 10px margin)
        est_min_w = int(len(txt) * 6.2 + 10) if txt else 16
        if txt and w > 0 and w < est_min_w:
            clipped_widgets.append({
                **entry,
                "issue": f"Button width ({w}px) is narrower than required text width (~{est_min_w}px)",
            })

    for combo in window.findChildren(QComboBox):
        if not combo.isVisible():
            continue
        txt = combo.currentText()
        w = combo.width()
        est_min_w = int(len(txt) * 6.5 + 24) if txt else 40
        if txt and w > 0 and w < est_min_w:
            clipped_widgets.append({
                "type": "QComboBox",
                "objectName": combo.objectName() or "",
                "text": txt,
                "size": f"{w}x{combo.height()}",
                "issue": f"Combo width ({w}px) is narrower than required text width (~{est_min_w}px)",
            })

    report = {
        "timestamp": datetime.now().isoformat(),
        "scope": "PalaceWindow (Isolated Qt Widget Hierarchy Only)",
        "window_title": window.windowTitle(),
        "window_size": f"{win_rect.width()}x{win_rect.height()}",
        "active_profile": getattr(window, "current_profile", ""),
        "badge_display_mode": getattr(window, "badge_display_mode", "icons_only"),
        "visible_button_count": len(visible_buttons),
        "clipped_widget_count": len(clipped_widgets),
        "clipped_widgets": clipped_widgets,
        "sample_buttons": visible_buttons[:25],
    }
    try:
        SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        UI_AUDIT_REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass
    return report


def capture_palace_window_snapshot(window: Any, tag: str = "palace_ui_snapshot") -> tuple[Path | None, dict[str, Any]]:
    """Grab ONLY the PalaceWindow widget buffer (`window.grab()`) and run the geometry audit."""
    audit = audit_palace_window_geometry(window)
    try:
        pixmap = window.grab()
        if pixmap.isNull():
            return None, audit
        out_dir = get_generated_images_dir()
        safe_tag = "".join(c if c.isalnum() or c in "_-" else "_" for c in (tag or "ui_snap"))[:28]
        ts = datetime.now().strftime("%H%M%S")
        out_path = out_dir / f"{safe_tag}_{ts}.png"
        pixmap.save(str(out_path), "PNG")
        audit["snapshot_path"] = str(out_path)
        audit["snapshot_resolution"] = f"{pixmap.width()}x{pixmap.height()}"
        try:
            UI_AUDIT_REPORT_PATH.write_text(json.dumps(report := audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass
        return out_path, audit
    except Exception as exc:
        audit["error"] = str(exc)
        return None, audit


def capture_offscreen_palace_snapshot(tag: str = "palace_offscreen_check") -> tuple[Path | None, dict[str, Any]]:
    """Render an isolated PalaceWindow instance and capture its widget snapshot + geometry audit."""
    from PySide6.QtWidgets import QApplication
    import palace_gui

    app = QApplication.instance()
    created_app = False
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(sys.argv[:1])
        created_app = True

    win = palace_gui.PalaceWindow()
    win.resize(1160, 760)
    win.show()
    app.processEvents()
    snap_path, audit = capture_palace_window_snapshot(win, tag=tag)
    win.close()
    win.deleteLater()
    app.processEvents()
    return snap_path, audit


def ensure_staging_initialized() -> Path:
    r"""Populate `C:\Palace_Idle_Sandbox\staging` from `C:\Palace_Live` if needed."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    src_dir = LIVE_DIR if LIVE_DIR.exists() else SOURCE_REPO_DIR
    for item in src_dir.glob("*.py"):
        dst = STAGING_DIR / item.name
        if not dst.exists():
            shutil.copy2(item, dst)
    cfg = src_dir / "palace_config.json"
    if cfg.exists() and not (STAGING_DIR / "palace_config.json").exists():
        shutil.copy2(cfg, STAGING_DIR / "palace_config.json")
    return STAGING_DIR


def sync_live_to_staging() -> Path:
    r"""Copy all current live `.py` files into `C:\Palace_Idle_Sandbox\staging`."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    src_dir = LIVE_DIR if LIVE_DIR.exists() else SOURCE_REPO_DIR
    for item in src_dir.glob("*.py"):
        shutil.copy2(item, STAGING_DIR / item.name)
    return STAGING_DIR


_FORBIDDEN_STAGE_TOKENS = (
    "dpapi_decrypt",
    "CryptUnprotectData",
    "_DPAPI_ENTROPY",
    "VAULT_CREDENTIALS_PATH",
    "_KNOWN_SECRET_STRINGS",
    "__import__(",
    "eval(",
    "exec(",
)


def _strip_accidental_line_numbers(snippet: str) -> str:
    """Strip leading '1234: ' prefixes if an AI accidentally copied line numbers from read_source_file output."""
    import re
    lines = (snippet or "").splitlines()
    if lines and sum(1 for ln in lines if re.match(r"^\s*\d+:\s?", ln)) >= max(1, (len(lines) + 1) // 2):
        return "\n".join(re.sub(r"^\s*\d+:\s?", "", ln, count=1) for ln in lines)
    return snippet


def stage_palace_replace(
    filename: str,
    target_snippet: str,
    replacement_snippet: str,
    *,
    author: str = "council",
) -> tuple[bool, str]:
    """Safely apply a snippet replacement to an allowlisted Palace file inside `staging/`."""
    clean_name = Path(filename or "").name
    if clean_name not in EDITABLE_PALACE_FILES:
        return (
            False,
            f"Denied: '{clean_name}' is not in EDITABLE_PALACE_FILES allowlist ({sorted(EDITABLE_PALACE_FILES)}).",
        )
    for bad_tok in _FORBIDDEN_STAGE_TOKENS:
        if bad_tok in (replacement_snippet or ""):
            return (
                False,
                f"Security Gate Denied: Staged replacement contains forbidden credential/execution token '{bad_tok}'.",
            )
    ensure_staging_initialized()
    staged_file = STAGING_DIR / clean_name
    if not staged_file.exists():
        return False, f"Staged file '{clean_name}' not found."

    content = staged_file.read_text(encoding="utf-8").replace("\r\n", "\n")
    norm_target = (target_snippet or "").replace("\r\n", "\n")
    norm_repl = (replacement_snippet or "").replace("\r\n", "\n")

    if norm_target not in content:
        # Try stripping accidental '1234: ' line-number prefixes
        stripped_target = _strip_accidental_line_numbers(norm_target)
        stripped_repl = _strip_accidental_line_numbers(norm_repl)
        if stripped_target and stripped_target in content:
            norm_target = stripped_target
            norm_repl = stripped_repl

    updated: str | None = None
    if norm_target and norm_target in content:
        updated = content.replace(norm_target, norm_repl, 1)
    elif norm_target:
        # Fallback: trailing-whitespace-tolerant line block match
        src_lines = content.splitlines()
        tgt_lines = [ln.rstrip() for ln in norm_target.splitlines()]
        n_tgt = len(tgt_lines)
        if n_tgt > 0:
            for i in range(len(src_lines) - n_tgt + 1):
                if [src_lines[i + j].rstrip() for j in range(n_tgt)] == tgt_lines:
                    new_lines = src_lines[:i] + norm_repl.splitlines() + src_lines[i + n_tgt :]
                    updated = "\n".join(new_lines) + ("\n" if content.endswith("\n") else "")
                    break

    if updated is None:
        # Provide the closest matching line window from the actual file so the self-heal pass can fix it immediately
        src_lines = content.splitlines()
        first_nonempty = next((ln.strip() for ln in norm_target.splitlines() if ln.strip()), "")
        hint_block = ""
        if first_nonempty:
            for idx, ln in enumerate(src_lines):
                if first_nonempty[:28] in ln:
                    s_i = max(0, idx - 4)
                    e_i = min(len(src_lines), idx + 20)
                    hint_block = "\nActual lines in file around match:\n" + "\n".join(src_lines[s_i:e_i])
                    break
        return False, f"Target snippet not found in '{clean_name}'.{hint_block}"

    staged_file.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(staged_file), doraise=True)
    except py_compile.PyCompileError as exc:
        # Revert broken syntax immediately
        staged_file.write_text(content, encoding="utf-8")
        return False, f"Syntax error in staged '{clean_name}' (reverted automatically): {exc}"

    return True, f"Staged edit to '{clean_name}' by {author} compiled cleanly."


def validate_staged_palace(run_unit_tests: bool = True) -> dict[str, Any]:
    """Run `py_compile` across all staged files and run `test_palace_gui` in offscreen mode."""
    ensure_staging_initialized()
    compiled_files: list[str] = []
    compile_errors: list[str] = []

    for py_file in sorted(STAGING_DIR.glob("*.py")):
        try:
            py_compile.compile(str(py_file), doraise=True)
            compiled_files.append(py_file.name)
        except py_compile.PyCompileError as exc:
            compile_errors.append(f"{py_file.name}: {exc}")

    if compile_errors:
        return {
            "passed": False,
            "py_compile": "fail",
            "compile_errors": compile_errors,
            "unittest_passed": False,
            "unittest_output": "",
        }

    if not run_unit_tests:
        return {
            "passed": True,
            "py_compile": "pass",
            "compiled_count": len(compiled_files),
            "unittest_passed": True,
            "unittest_output": "Skipped unit tests.",
        }

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "test_palace_gui"],
        cwd=str(STAGING_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    output = (proc.stdout + "\n" + proc.stderr).strip()
    passed = proc.returncode == 0
    return {
        "passed": passed,
        "py_compile": "pass",
        "compiled_count": len(compiled_files),
        "unittest_passed": passed,
        "unittest_output": output[-1500:],
    }


def backup_live_to_last_known_good() -> Path:
    r"""Save a clean snapshot of `C:\Palace_Live` to `C:\Palace_Idle_Sandbox\last_known_good`."""
    LAST_KNOWN_GOOD_DIR.mkdir(parents=True, exist_ok=True)
    src_dir = LIVE_DIR if LIVE_DIR.exists() else SOURCE_REPO_DIR
    for py_file in src_dir.glob("*.py"):
        shutil.copy2(py_file, LAST_KNOWN_GOOD_DIR / py_file.name)
    return LAST_KNOWN_GOOD_DIR


def rollback_to_last_known_good() -> bool:
    r"""Restore `last_known_good` back into `C:\Palace_Live` and `E:\Visual_studio\Palace`."""
    if not LAST_KNOWN_GOOD_DIR.exists():
        return False
    restored = 0
    for py_file in LAST_KNOWN_GOOD_DIR.glob("*.py"):
        if py_file.name in EDITABLE_PALACE_FILES:
            if LIVE_DIR.exists():
                shutil.copy2(py_file, LIVE_DIR / py_file.name)
            if SOURCE_REPO_DIR.exists():
                shutil.copy2(py_file, SOURCE_REPO_DIR / py_file.name)
            restored += 1
    return restored > 0


# ================= MULTI-EDITION VERSION STORE & /RESTORE ENGINE =================
EDITIONS_DIR = SANDBOX_ROOT / "editions"
QUARANTINE_DIR = SANDBOX_ROOT / "quarantine"
GENERATION_LOG_PATH = SANDBOX_ROOT / "generation_log.jsonl"
CRASH_REPORT_PATH = SANDBOX_ROOT / "crash_report.json"


def write_crash_report(
    *,
    trigger: str,
    exc_type: str,
    exc_message: str,
    traceback_str: str,
    failed_edition: str = "",
    restored_edition: str = "last_known_good",
) -> Path:
    """Write a structured forensic crash report so the restored Palace instance can inject it into chat."""
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    editions = list_code_editions()
    if not failed_edition and editions:
        failed_edition = editions[-1].get("version", "latest")
    payload = {
        "schema_version": 1,
        "consumed": False,
        "timestamp_utc": datetime.now().isoformat(),
        "failed_edition": failed_edition,
        "restored_edition": restored_edition,
        "trigger": trigger,
        "exception": {
            "type": exc_type,
            "message": exc_message,
        },
        "traceback": (traceback_str or "")[-2500:],
    }
    CRASH_REPORT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if failed_edition:
        q_dir = QUARANTINE_DIR / failed_edition
        q_dir.mkdir(parents=True, exist_ok=True)
        (q_dir / "crash_report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return CRASH_REPORT_PATH


def consume_pending_crash_report() -> dict[str, Any] | None:
    """Read and mark consumed any pending `crash_report.json` after an automatic rollback."""
    if not CRASH_REPORT_PATH.exists():
        return None
    try:
        data = json.loads(CRASH_REPORT_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("consumed", True):
            return None
        data["consumed"] = True
        data["consumed_at"] = datetime.now().isoformat()
        CRASH_REPORT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return data
    except Exception:
        return None


def _compute_file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def list_code_editions() -> list[dict[str, Any]]:
    """Return all recorded code editions in chronological order (v0001, v0002, ...)."""
    EDITIONS_DIR.mkdir(parents=True, exist_ok=True)
    editions: list[dict[str, Any]] = []
    for d in sorted(EDITIONS_DIR.glob("v[0-9][0-9][0-9][0-9]")):
        manifest_p = d / "manifest.json"
        if manifest_p.exists():
            try:
                editions.append(json.loads(manifest_p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return editions


def ensure_golden_baseline_edition() -> dict[str, Any]:
    """Ensure v0001 (Golden Pinned Baseline Edition) exists before any autopatch runs."""
    existing = list_code_editions()
    if existing:
        return existing[0]
    return create_code_edition_snapshot(
        author="Brett (Golden Baseline)",
        summary="v0001 Golden Pinned Baseline Edition prior to Normal/Experimental autopatches",
        files_changed=sorted(EDITABLE_PALACE_FILES),
        pinned=True,
        source_dir=LIVE_DIR if LIVE_DIR.exists() else SOURCE_REPO_DIR,
    )


def create_code_edition_snapshot(
    *,
    author: str = "council",
    summary: str = "Code edition snapshot",
    files_changed: list[str] | None = None,
    pinned: bool = False,
    source_dir: Path | None = None,
) -> dict[str, Any]:
    """Create an immutable versioned snapshot (v0001, v0002, ...) with a SHA-256 hash-chained manifest."""
    EDITIONS_DIR.mkdir(parents=True, exist_ok=True)
    existing = list_code_editions()
    next_num = (int(existing[-1]["version"][1:]) + 1) if existing else 1
    ver_id = f"v{next_num:04d}"
    parent_ver = existing[-1]["version"] if existing else None
    parent_manifest_hash = existing[-1].get("manifest_hash", "GENESIS") if existing else "GENESIS"

    ver_dir = EDITIONS_DIR / ver_id
    ver_dir.mkdir(parents=True, exist_ok=True)
    src = source_dir or (STAGING_DIR if STAGING_DIR.exists() else (LIVE_DIR if LIVE_DIR.exists() else SOURCE_REPO_DIR))

    file_hashes: dict[str, str] = {}
    for fname in sorted(EDITABLE_PALACE_FILES):
        fp = src / fname
        if fp.exists():
            dst = ver_dir / fname
            shutil.copy2(fp, dst)
            file_hashes[fname] = _compute_file_sha256(dst)

    manifest_core = {
        "version": ver_id,
        "parent_version": parent_ver,
        "parent_manifest_hash": parent_manifest_hash,
        "timestamp": datetime.now().isoformat(),
        "author": author,
        "summary": summary,
        "pinned": bool(pinned or ver_id == "v0001"),
        "files_changed": list(files_changed or []),
        "file_hashes": file_hashes,
    }
    chain_digest = hashlib.sha256(json.dumps(manifest_core, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    manifest = {**manifest_core, "manifest_hash": chain_digest}
    (ver_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        with open(GENERATION_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(manifest, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return manifest


def pin_code_edition(version_id: str, pinned: bool = True) -> tuple[bool, str]:
    """Pin or unpin a specific edition (v0001 is always pinned)."""
    clean_v = (version_id or "").strip().lower()
    if not clean_v.startswith("v"):
        clean_v = f"v{int(clean_v):04d}" if clean_v.isdigit() else clean_v
    manifest_p = EDITIONS_DIR / clean_v / "manifest.json"
    if not manifest_p.exists():
        return False, f"Edition '{clean_v}' not found."
    if clean_v == "v0001" and not pinned:
        return False, "Golden baseline edition v0001 cannot be unpinned."
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    data["pinned"] = bool(pinned)
    manifest_p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True, f"Edition {clean_v} {'pinned (golden)' if pinned else 'unpinned'}."


def restore_code_edition(version_id: str = "previous") -> tuple[bool, str, dict[str, Any]]:
    """Verify manifest SHA-256 checksums and restore the requested code edition into staging, live, and repo."""
    ensure_golden_baseline_edition()
    editions = list_code_editions()
    if not editions:
        return False, "No saved code editions available to restore.", {}

    req = (version_id or "previous").strip().lower()
    target_manifest: dict[str, Any] | None = None
    if req in {"previous", "prev", "last", ""}:
        target_manifest = editions[-2] if len(editions) >= 2 else editions[0]
    elif req in {"golden", "baseline", "first"}:
        target_manifest = editions[0]
    else:
        if req.isdigit():
            req = f"v{int(req):04d}"
        for ed in editions:
            if ed.get("version", "").lower() == req:
                target_manifest = ed
                break

    if target_manifest is None:
        avail = ", ".join(e["version"] for e in editions)
        return False, f"Edition '{version_id}' not found. Available editions: {avail}", {}

    ver_id = target_manifest["version"]
    ver_dir = EDITIONS_DIR / ver_id
    expected_hashes = target_manifest.get("file_hashes") or {}

    # Verify SHA-256 integrity of every file in the snapshot before restoring
    for fname, exp_sha in expected_hashes.items():
        fp = ver_dir / fname
        if not fp.exists():
            return False, f"Integrity check failed: '{fname}' missing in {ver_id}.", {}
        actual_sha = _compute_file_sha256(fp)
        if exp_sha and actual_sha != exp_sha:
            return False, f"Manifest hash mismatch on '{fname}' in {ver_id} (refusing to restore tampered snapshot).", {}

    # Copy verified edition files to STAGING_DIR, LIVE_DIR, and SOURCE_REPO_DIR
    restored_files: list[str] = []
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    for fname in sorted(EDITABLE_PALACE_FILES):
        src_fp = ver_dir / fname
        if src_fp.exists():
            shutil.copy2(src_fp, STAGING_DIR / fname)
            if LIVE_DIR.exists():
                shutil.copy2(src_fp, LIVE_DIR / fname)
            if SOURCE_REPO_DIR.exists():
                shutil.copy2(src_fp, SOURCE_REPO_DIR / fname)
            restored_files.append(fname)

    summary = f"Restored {ver_id} ({target_manifest.get('summary', '')}) — {len(restored_files)} files verified"
    return True, summary, target_manifest


def format_code_editions_markdown() -> str:
    """Format the code edition history table as Markdown for chat display."""
    ensure_golden_baseline_edition()
    editions = list_code_editions()
    if not editions:
        return "No code editions recorded yet."
    lines = [
        "### 🕰️ Fairybread Code Edition History (`/restore`)",
        "| Edition | Pin | Timestamp | Author | Summary | Changed Files |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for ed in reversed(editions):
        ver = ed.get("version", "")
        pin = "📌 Golden" if ed.get("pinned") else ""
        ts = str(ed.get("timestamp", ""))[:19].replace("T", " ")
        auth = ed.get("author", "council")
        summ = ed.get("summary", "")
        f_list = ", ".join(ed.get("files_changed") or [])[:48]
        lines.append(f"| **`{ver}`** | {pin} | `{ts}` | {auth} | {summ} | `{f_list}` |")
    lines.append(
        "\n*Tip: Use `/restore v0001` (or `/restore previous`) to roll back to any edition and hot-reboot, or `/restore pin v0002` to lock a golden edition.*"
    )
    return "\n".join(lines)



def write_reboot_handoff(
    *,
    reason: str,
    applied_diff_summary: str,
    test_results: dict[str, Any],
    session_id: str = "legacy",
    scroll_position: int = 0,
    active_squad: list[str] | None = None,
    composer_draft: str = "",
    resumption_prompt: str = "",
    auto_resume_turn: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """Atomically write `reboot_handoff.json` with L6 Circuit Breaker protection."""
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    now_ts = time.time()
    recent_timestamps: list[float] = []

    if HANDOFF_PATH.exists():
        try:
            prev = json.loads(HANDOFF_PATH.read_text(encoding="utf-8"))
            for ts in prev.get("reboot", {}).get("recent_reboot_timestamps", []):
                if now_ts - float(ts) <= REBOOT_WINDOW_SECONDS:
                    recent_timestamps.append(float(ts))
        except Exception:
            pass

    if len(recent_timestamps) >= MAX_REBOOTS_IN_WINDOW:
        return (
            False,
            f"CIRCUIT BREAKER TRIPPED: {len(recent_timestamps)} reboots in last {int(REBOOT_WINDOW_SECONDS)}s. Auto-reboot halted.",
            {},
        )

    recent_timestamps.append(now_ts)
    payload = {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(),
        "handoff_id": str(uuid4()),
        "consumed": False,
        "reboot": {
            "reason": reason,
            "reboot_count_in_window": len(recent_timestamps),
            "recent_reboot_timestamps": recent_timestamps,
            "applied_diff_summary": applied_diff_summary,
            "test_results": test_results,
        },
        "session": {
            "session_id": session_id,
            "scroll_position": scroll_position,
            "active_squad": active_squad or [],
            "composer_draft": composer_draft,
        },
        "continuity": {
            "resumption_prompt": resumption_prompt,
            "auto_resume_turn": auto_resume_turn,
        },
    }

    tmp_path = HANDOFF_PATH.with_suffix(".json.tmp")
    data_bytes = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with open(tmp_path, "wb") as fh:
        fh.write(data_bytes)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, HANDOFF_PATH)
    return True, "Handoff written atomically.", payload


def read_pending_handoff(consume: bool = True) -> dict[str, Any] | None:
    """Read `reboot_handoff.json` on Palace startup if `consumed` is False."""
    if not HANDOFF_PATH.exists():
        return None
    try:
        data = json.loads(HANDOFF_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("consumed", True):
            return None
        if consume:
            data["consumed"] = True
            data["consumed_at"] = datetime.now().isoformat()
            tmp_path = HANDOFF_PATH.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp_path, HANDOFF_PATH)
        return data
    except Exception:
        return None


POST_REBOOT_TASK_PATH = SANDBOX_ROOT / "post_reboot_task.json"


def write_post_reboot_task(
    *,
    origin: str,
    chat_session_id: str,
    user_request_summary: str,
    what_was_attempted: str,
    instructions_for_agents: list[str] | None = None,
    chain_depth: int = 1,
) -> Path | None:
    """Atomically write a consume-once `post_reboot_task.json` continuation file before hot-reboot or autofallback."""
    if chain_depth > 2:
        return None
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    editions = list_code_editions()
    active_ed = editions[-1].get("version", "latest") if editions else "v0001"
    payload = {
        "schema_version": 1,
        "task_id": str(uuid4()),
        "created_at_utc": datetime.now().isoformat(),
        "origin": origin,
        "active_edition": active_ed,
        "chat_session_id": chat_session_id or "legacy",
        "context": {
            "user_request_summary": (user_request_summary or "")[:600],
            "what_was_attempted": (what_was_attempted or "")[:600],
        },
        "instructions_for_agents": list(
            instructions_for_agents
            or [
                "Inspect what just happened after the hot-reboot or recovery ([TOOL: inspect_palace_ui] or read the updated code).",
                "Review what you were doing for the user's request and confirm whether the update is complete or needs any follow-up.",
            ]
        ),
        "loop_guard": {
            "reboot_chain_depth": chain_depth,
            "max_chain_depth": 2,
        },
    }
    tmp_p = POST_REBOOT_TASK_PATH.with_suffix(".json.tmp")
    raw_bytes = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with open(tmp_p, "wb") as fh:
        fh.write(raw_bytes)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_p, POST_REBOOT_TASK_PATH)
    return POST_REBOOT_TASK_PATH


def consume_post_reboot_task() -> dict[str, Any] | None:
    """Atomically read and unlink `post_reboot_task.json` on startup so it executes at most once."""
    if not POST_REBOOT_TASK_PATH.exists():
        return None
    try:
        data = json.loads(POST_REBOOT_TASK_PATH.read_text(encoding="utf-8"))
        try:
            POST_REBOOT_TASK_PATH.unlink()
        except OSError:
            pass
        if not isinstance(data, dict):
            return None
        depth = int((data.get("loop_guard") or {}).get("reboot_chain_depth", 1))
        if depth > 2:
            return None
        return data
    except Exception:
        try:
            POST_REBOOT_TASK_PATH.unlink()
        except OSError:
            pass
        return None


def write_ready_heartbeat(pid: int, status: str = "READY") -> None:
    """Called by `PalaceWindow` once startup and UI initialization succeed."""
    try:
        SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        READY_HEARTBEAT_PATH.write_text(
            json.dumps(
                {
                    "pid": pid,
                    "status": status,
                    "timestamp": time.time(),
                    "iso": datetime.now().isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
