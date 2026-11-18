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
from pathlib import Path

from palace_ouroboros import (
    EDITABLE_PALACE_FILES,
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


def _stop_existing_palace_gui() -> None:
    """Stop any running `pythonw.exe` / `python.exe` executing `palace_gui.py`."""
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%palace_gui.py%'\" | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=10)


def _launch_palace_on_interactive_desktop() -> None:
    """Trigger the interactive desktop scheduled task (`LaunchPalaceDesktop`) so the window opens on WinSta0\\Default."""
    res = subprocess.run(
        ["schtasks", "/Run", "/TN", "LaunchPalaceDesktop"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if res.returncode != 0:
        # Fallback direct spawn if scheduled task is not present
        bat = LIVE_DIR / "Run_Palace_Live.bat"
        if bat.exists():
            subprocess.Popen(["cmd.exe", "/c", str(bat)], cwd=str(LIVE_DIR))


def perform_hot_reboot(
    *,
    reason: str = "ouroboros_self_upgrade",
    diff_summary: str = "Staged Palace self-improvement applied.",
    session_id: str = "legacy",
    resumption_prompt: str = "",
    skip_tests: bool = False,
) -> tuple[bool, str]:
    # 1. Preflight Gate (L3)
    print("[Watchdog] Running Preflight Gate (py_compile + unittest)...")
    test_res = validate_staged_palace(run_unit_tests=not skip_tests)
    if not test_res.get("passed"):
        msg = f"Preflight gate failed — aborting hot-reboot:\n{json.dumps(test_res, indent=2)}"
        print(f"[Watchdog] {msg}", file=sys.stderr)
        return False, msg

    # 2. Ensure golden baseline v0001 exists and backup current live files to last_known_good/
    try:
        ensure_golden_baseline_edition()
    except Exception:
        pass
    backup_live_to_last_known_good()

    # 3. Write atomic handoff with Circuit Breaker check (L4 & L6)
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
        print(f"[Watchdog] {handoff_msg}", file=sys.stderr)
        return False, handoff_msg

    # 4. Stop old Palace window & atomically swap allowlisted files from staging/ -> Live & Repo
    print("[Watchdog] Stopping previous Palace instance and swapping staged files...")
    _stop_existing_palace_gui()
    time.sleep(0.6)

    source_mirror_dir = SANDBOX_ROOT / "source_mirror"
    source_mirror_dir.mkdir(parents=True, exist_ok=True)
    for fname in EDITABLE_PALACE_FILES:
        staged_f = STAGING_DIR / fname
        if staged_f.exists():
            if LIVE_DIR.exists():
                shutil.copy2(staged_f, LIVE_DIR / fname)
            if SOURCE_REPO_DIR.exists():
                shutil.copy2(staged_f, SOURCE_REPO_DIR / fname)
            shutil.copy2(staged_f, source_mirror_dir / fname)

    # 5. Record pre-launch timestamp and launch new Palace window on interactive desktop
    launch_ts = time.time()
    _launch_palace_on_interactive_desktop()

    # 6. Wait up to 10 seconds for READY heartbeat (L5)
    print("[Watchdog] Waiting for READY heartbeat from upgraded PalaceWindow...")
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
                    print(f"[Watchdog] {msg}")
                    return True, msg
            except Exception:
                pass
        time.sleep(0.4)

    # 7. Automatic Zero-Touch Rollback on Timeout/Crash!
    print("[Watchdog] ERROR: READY heartbeat timed out! Rolling back to last_known_good...", file=sys.stderr)
    _stop_existing_palace_gui()
    rollback_to_last_known_good()
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
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
