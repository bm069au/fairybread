r"""Immutable Palace Watchdog & Hot-Reboot Launcher (`palace_watchdog.py`).

Strictly outside `EDITABLE_PALACE_FILES`:
1. Validates staged files in `C:\Palace_Idle_Sandbox\staging` (`py_compile` + `unittest`).
2. Backs up `C:\Palace_Live` to `C:\Palace_Idle_Sandbox\last_known_good`.
3. Writes `reboot_handoff.json` atomically (enforcing the 3-reboots-in-120s Circuit Breaker).
4. Closes any running `palace_gui.py` process, deploys the staged files to `C:\Palace_Live` and `E:\Visual_studio\Palace`,
   and launches the newly upgraded Palace window onto the interactive desktop via `LaunchPalaceDesktop`.
5. Waits up to 10 seconds for `palace_ready_heartbeat.json`. If the new window fails to signal `READY`,
   automatically rolls back to `last_known_good` and relaunches!
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from palace_ouroboros import (
    EDITABLE_PALACE_FILES,
    HANDOFF_PATH,
    LIVE_DIR,
    READY_HEARTBEAT_PATH,
    SANDBOX_ROOT,
    SOURCE_REPO_DIR,
    STAGING_DIR,
    backup_live_to_last_known_good,
    create_code_edition_snapshot,
    ensure_golden_baseline_edition,
    rollback_to_last_known_good,
    validate_staged_palace,
    write_crash_report,
    write_reboot_handoff,
)

WATCHDOG_LOG_PATH = SANDBOX_ROOT / "watchdog_last.log"


def _log(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(msg, file=stream)
    try:
        SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        with WATCHDOG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except OSError:
        pass


def _stop_existing_palace_gui() -> None:
    """Stop any running `pythonw.exe` / `python.exe` executing `palace_gui.py`."""
    cur_pid = int(os.getpid())
    parent_pid = int(os.getppid()) if hasattr(os, "getppid") else -1
    ps_cmd = (
        f"$ex1 = {cur_pid}; $ex2 = {parent_pid}; $me = $PID; "
        "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%' AND CommandLine LIKE '%palace_gui.py%'\" | "
        "Where-Object { $_.ProcessId -ne $me -and $_.ProcessId -ne $ex1 -and $_.ProcessId -ne $ex2 } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log(f"[Watchdog] Warning stopping existing Palace process: {exc}", err=True)


def _launch_palace_on_interactive_desktop() -> None:
    """Launch the active PalaceWindow instance onto the desktop."""
    if LIVE_DIR.resolve() == Path(r"C:\Palace_Live").resolve():
        try:
            res = subprocess.run(
                ["schtasks", "/Run", "/TN", "LaunchPalaceDesktop"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                return
        except (subprocess.TimeoutExpired, OSError) as exc:
            _log(f"[Watchdog] Warning running LaunchPalaceDesktop task: {exc}", err=True)
    bat = LIVE_DIR / "Run_Palace_Live.bat"
    if bat.exists():
        subprocess.Popen(["cmd.exe", "/c", str(bat)], cwd=str(LIVE_DIR))
        return
    pythonw_exe = Path(sys.executable).with_name("pythonw.exe")
    launcher = str(pythonw_exe if pythonw_exe.exists() else Path(sys.executable))
    gui_py = LIVE_DIR / "palace_gui.py"
    if gui_py.exists():
        subprocess.Popen([launcher, str(gui_py)], cwd=str(LIVE_DIR))


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    raw = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with open(tmp, "wb") as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def perform_hot_reboot(
    *,
    reason: str = "ouroboros_self_upgrade",
    diff_summary: str = "Staged Palace self-improvement applied.",
    session_id: str = "legacy",
    resumption_prompt: str = "",
    skip_tests: bool = False,
    preserve_existing_handoff: bool = False,
) -> tuple[bool, str]:
    # 0. Sync any newer files from SOURCE_REPO_DIR (E:\Visual_studio\Palace) into STAGING_DIR first
    # so direct repo edits are never overwritten by older staging files!
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    if SOURCE_REPO_DIR.exists():
        for fname in EDITABLE_PALACE_FILES:
            repo_f = SOURCE_REPO_DIR / fname
            staged_f = STAGING_DIR / fname
            if repo_f.exists() and (not staged_f.exists() or repo_f.stat().st_mtime >= staged_f.stat().st_mtime):
                shutil.copy2(repo_f, staged_f)

    # 1. Preflight Gate (L3)
    try:
        WATCHDOG_LOG_PATH.write_text("", encoding="utf-8")
    except OSError:
        pass
    _log("[Watchdog] Running Preflight Gate (py_compile + unittest)...")
    try:
        test_res = validate_staged_palace(run_unit_tests=not skip_tests)
    except Exception as exc:
        msg = f"Preflight gate crashed — aborting hot-reboot: {exc}"
        _log(f"[Watchdog] {msg}", err=True)
        return False, msg
    if not test_res.get("passed"):
        msg = f"Preflight gate failed — aborting hot-reboot:\n{json.dumps(test_res, indent=2)}"
        _log(f"[Watchdog] {msg}", err=True)
        return False, msg

    # 2. Ensure golden baseline v0001 exists and backup current live files to last_known_good/
    try:
        ensure_golden_baseline_edition()
    except Exception:
        pass
    backup_live_to_last_known_good()

    # 3. Write atomic handoff with Circuit Breaker check (L4 & L6), preserving pre-written Experimental continuity
    preserved_handoff = False
    if HANDOFF_PATH.exists():
        try:
            existing = json.loads(HANDOFF_PATH.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and not existing.get("consumed", True):
                cont = existing.get("continuity") or {}
                rec_ts = list((existing.get("reboot") or {}).get("recent_reboot_timestamps") or [])
                latest_ts = float(rec_ts[-1]) if rec_ts else 0.0
                recent_auto_idle = bool(cont.get("auto_resume_idle")) and (time.time() - latest_ts) <= 60.0
                if preserve_existing_handoff or recent_auto_idle:
                    existing.setdefault("reboot", {})
                    if not (skip_tests and existing["reboot"].get("test_results")):
                        existing["reboot"]["test_results"] = {
                            "py_compile": test_res.get("py_compile"),
                            "unittest_passed": test_res.get("unittest_passed"),
                        }
                    _atomic_write_json(HANDOFF_PATH, existing)
                    preserved_handoff = True
        except Exception:
            preserved_handoff = False

    if not preserved_handoff:
        ok_handoff, handoff_msg, _payload = write_reboot_handoff(
            reason=reason,
            applied_diff_summary=diff_summary,
            test_results={
                "py_compile": test_res.get("py_compile"),
                "unittest_passed": test_res.get("unittest_passed"),
            },
            session_id=session_id,
            resumption_prompt=resumption_prompt,
        )
        if not ok_handoff:
            _log(f"[Watchdog] {handoff_msg}", err=True)
            return False, handoff_msg

    # 4. Stop old Palace window & atomically swap allowlisted files from staging/ -> Live & Repo
    if not LIVE_DIR.exists():
        msg = f"Live directory missing: {LIVE_DIR}"
        _log(f"[Watchdog] {msg}", err=True)
        return False, msg
    _log("[Watchdog] Stopping previous Palace instance and swapping staged files...")
    _stop_existing_palace_gui()
    time.sleep(0.6)

    source_mirror_dir = SANDBOX_ROOT / "source_mirror"
    source_mirror_dir.mkdir(parents=True, exist_ok=True)
    for fname in EDITABLE_PALACE_FILES:
        staged_f = STAGING_DIR / fname
        if staged_f.exists():
            shutil.copy2(staged_f, LIVE_DIR / fname)
            # Only copy to SOURCE_REPO_DIR if we are in a standalone single-folder install.
            # In owner dev mode, master E:\Visual_studio\Palace is protected from auto-reboot overwrites.
            if SOURCE_REPO_DIR.exists() and SOURCE_REPO_DIR.resolve() == LIVE_DIR.resolve():
                shutil.copy2(staged_f, SOURCE_REPO_DIR / fname)
            shutil.copy2(staged_f, source_mirror_dir / fname)

    # 5. Record pre-launch timestamp and launch new Palace window on interactive desktop
    launch_ts = time.time()
    _launch_palace_on_interactive_desktop()

    # 6. Wait up to 10 seconds for READY heartbeat (L5)
    _log("[Watchdog] Waiting for READY heartbeat from upgraded PalaceWindow...")
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if READY_HEARTBEAT_PATH.exists():
            try:
                hb = json.loads(READY_HEARTBEAT_PATH.read_text(encoding="utf-8"))
                if float(hb.get("timestamp", 0)) >= launch_ts - 0.5 and hb.get("status") == "READY":
                    try:
                        create_code_edition_snapshot(
                            author=reason,
                            summary=diff_summary,
                            source_dir=LIVE_DIR if LIVE_DIR.exists() else SOURCE_REPO_DIR,
                        )
                    except Exception:
                        pass
                    msg = f"SUCCESS: Upgraded Palace process (PID {hb.get('pid')}) verified READY on desktop!"
                    _log(f"[Watchdog] {msg}")
                    return True, msg
            except Exception:
                pass
        time.sleep(0.4)

    # 7. Automatic Zero-Touch Rollback on Timeout/Crash!
    _log("[Watchdog] ERROR: READY heartbeat timed out! Rolling back to last_known_good...", err=True)
    _stop_existing_palace_gui()
    rollback_to_last_known_good()
    rollback_reason = f"Startup failed READY heartbeat within 10s — rolled back to last_known_good ({diff_summary})"
    if HANDOFF_PATH.exists():
        try:
            hd = json.loads(HANDOFF_PATH.read_text(encoding="utf-8"))
            if isinstance(hd, dict) and not hd.get("consumed", True):
                hd.setdefault("reboot", {})
                hd["reboot"]["rolled_back"] = True
                hd["reboot"]["rollback_reason"] = rollback_reason
                _atomic_write_json(HANDOFF_PATH, hd)
        except Exception:
            pass
    try:
        write_crash_report(
            trigger="boot_timeout_or_startup_crash",
            exc_type="StartupTimeoutError",
            exc_message=f"Upgraded Palace window failed to emit READY heartbeat within 10s ({diff_summary})",
            traceback_str="Startup failed before READY heartbeat. Watchdog automatically rolled back to last_known_good.",
        )
    except Exception:
        pass
    _launch_palace_on_interactive_desktop()
    return False, "Upgrade failed READY heartbeat within 10s — rolled back to last_known_good automatically."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Palace Ouroboros Watchdog & Hot-Reboot")
    parser.add_argument("--reason", type=str, default="ouroboros_self_upgrade")
    parser.add_argument("--summary", type=str, default="Staged Palace upgrade applied and verified.")
    parser.add_argument("--session", type=str, default="legacy")
    parser.add_argument("--resumption-prompt", type=str, default="")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument(
        "--preserve-handoff",
        action="store_true",
        help="Preserve pre-written unconsumed reboot_handoff.json continuity (Experimental Mode auto-resume)",
    )
    parser.add_argument("--auto-rollback", action="store_true", help="Immediately roll back to last_known_good after a runtime crash")
    args = parser.parse_args(argv)

    if args.auto_rollback:
        print("[Watchdog] Runtime crash detected — executing Zero-Touch Auto-Rollback to last_known_good...")
        _stop_existing_palace_gui()
        time.sleep(0.5)
        rollback_to_last_known_good()
        _launch_palace_on_interactive_desktop()
        return 0

    ok, _msg = perform_hot_reboot(
        reason=args.reason,
        diff_summary=args.summary,
        session_id=args.session,
        resumption_prompt=args.resumption_prompt,
        skip_tests=args.skip_tests,
        preserve_existing_handoff=args.preserve_handoff,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
