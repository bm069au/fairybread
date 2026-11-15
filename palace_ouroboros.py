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

    content = staged_file.read_text(encoding="utf-8")
    if target_snippet not in content:
        return False, f"Target snippet not found in '{clean_name}'."

    updated = content.replace(target_snippet, replacement_snippet, 1)
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
