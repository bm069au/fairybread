r"""Fairybread Code Promotion Tool — Sandbox to Master & Git Pipeline.

Commands:
  python palace_promote.py --diff
      Shows diffs between agent sandbox staging and the master E:\Visual_studio\Palace repo.

  python palace_promote.py --promote
      Validates staging, creates a pre-promotion backup on E:, and copies reviewed files to E:.

  python palace_promote.py --git-push "commit message"
      Stages changes on E:, commits, and pushes to GitHub remotes.
"""

from __future__ import annotations

import argparse
import difflib
import filecmp
import os
import py_compile
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SOURCE_REPO_DIR = Path(r"E:\Visual_studio\Palace")
SANDBOX_STAGING_DIR = Path(r"C:\Palace_Idle_Sandbox\staging")
BACKUP_DIR = Path(r"E:\Visual_studio\Palace_Backups")
EXCLUDED_SANDBOX_FILES = {"ask_gpt_WORKING_BACKUP.py"}
FORBIDDEN_SECRET_FILES = {"key.txt", "capture.txt", "palace_config.json", "credentials.json", "ask_gpt_WORKING_BACKUP.py"}


def show_diff() -> int:
    """Compare staged files against master E: files and display differences."""
    if not SANDBOX_STAGING_DIR.exists():
        print(f"[Error] Sandbox staging directory not found: {SANDBOX_STAGING_DIR}")
        return 1

    staged_files = [
        p for p in sorted(SANDBOX_STAGING_DIR.glob("*.py"))
        if p.name not in EXCLUDED_SANDBOX_FILES
    ]
    if not staged_files:
        print("[Info] No Python files currently in sandbox staging.")
        return 0

    differences_found = 0
    print(f"=== Comparing Agent Sandbox ({SANDBOX_STAGING_DIR}) vs Master Repo ({SOURCE_REPO_DIR}) ===\n")

    for sf in staged_files:
        rf = SOURCE_REPO_DIR / sf.name
        if not rf.exists():
            print(f"[+] NEW FILE IN SANDBOX: {sf.name}")
            differences_found += 1
            continue

        if filecmp.cmp(sf, rf, shallow=False):
            continue

        differences_found += 1
        print(f"[*] MODIFIED: {sf.name}")
        staged_lines = sf.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        repo_lines = rf.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        diff = difflib.unified_diff(
            repo_lines,
            staged_lines,
            fromfile=f"E:/Visual_studio/Palace/{sf.name}",
            tofile=f"C:/Palace_Idle_Sandbox/staging/{sf.name}",
            n=3,
        )
        sys.stdout.writelines(diff)
        print("\n" + ("-" * 60) + "\n")

    if differences_found == 0:
        print("[OK] Agent sandbox and master E: repository are identical. No pending changes.")
    else:
        print(f"[Summary] Found {differences_found} file(s) with differences.")
    return 0


def promote_to_main() -> int:
    """Validate sandbox staging files and promote them into E: repository with a safe backup."""
    if not SANDBOX_STAGING_DIR.exists():
        print(f"[Error] Sandbox staging directory not found: {SANDBOX_STAGING_DIR}")
        return 1

    staged_files = [
        p for p in sorted(SANDBOX_STAGING_DIR.glob("*.py"))
        if p.name not in EXCLUDED_SANDBOX_FILES
    ]
    if not staged_files:
        print("[Error] No Python files found in staging to promote.")
        return 1

    print("[1/3] Running pre-promotion compilation checks...")
    compile_errors = []
    for sf in staged_files:
        try:
            py_compile.compile(str(sf), doraise=True)
        except py_compile.PyCompileError as exc:
            compile_errors.append(f"{sf.name}: {exc}")

    if compile_errors:
        print("[FAILED] Compilation errors detected in staged files. Refusing to promote:")
        for err in compile_errors:
            print(f"  - {err}")
        return 1
    print(f"  ✓ {len(staged_files)} files compiled cleanly.")

    # 2. Create backup of E: files
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    promo_backup = BACKUP_DIR / f"Pre_Promotion_Backup_{ts}"
    promo_backup.mkdir(parents=True, exist_ok=True)
    print(f"[2/3] Backing up current E: master repository to {promo_backup}...")
    for rf in SOURCE_REPO_DIR.glob("*.py"):
        shutil.copy2(rf, promo_backup / rf.name)
    print("  ✓ Backup complete.")

    # 3. Promote changed files to E:
    print(f"[3/3] Promoting verified files to master repo ({SOURCE_REPO_DIR})...")
    promoted_count = 0
    for sf in staged_files:
        rf = SOURCE_REPO_DIR / sf.name
        if not rf.exists() or not filecmp.cmp(sf, rf, shallow=False):
            shutil.copy2(sf, rf)
            print(f"  ✓ Promoted: {sf.name}")
            promoted_count += 1

    print(f"\n[SUCCESS] Promotion complete. {promoted_count} file(s) promoted to master E: repository.")
    print("You can now test on E: or run 'python palace_promote.py --git-push \"commit message\"'.")
    return 0


def push_to_git(commit_message: str) -> int:
    """Stage, commit, and push changes from master E: repository to GitHub remotes."""
    if not commit_message:
        commit_message = f"Fairybread update - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    print(f"=== Committing and Pushing E: Master Repo to GitHub ===")
    print(f"Message: {commit_message}")

    try:
        # Check git status
        subprocess.run(["git", "status", "-s"], cwd=str(SOURCE_REPO_DIR), check=True)
        # Selectively stage updated tracked files, verified .py modules, and .gitignore (never blind -A)
        subprocess.run(["git", "add", "-u"], cwd=str(SOURCE_REPO_DIR), check=True)
        to_stage = [
            p.name for p in sorted(SOURCE_REPO_DIR.glob("*.py"))
            if p.name not in FORBIDDEN_SECRET_FILES
        ]
        if (SOURCE_REPO_DIR / ".gitignore").exists():
            to_stage.append(".gitignore")
        if to_stage:
            subprocess.run(["git", "add", "--", *to_stage], cwd=str(SOURCE_REPO_DIR), check=True)
        cached_res = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(SOURCE_REPO_DIR),
            capture_output=True,
            text=True,
            check=True,
        )
        blocked = [
            f for f in (cached_res.stdout or "").splitlines()
            if f.strip() in FORBIDDEN_SECRET_FILES
            or f.strip().endswith((".db", ".jsonl", ".pyc"))
            or f.strip().startswith(("memory/", "dist/", "build/", ".vs/", ".idea/"))
        ]
        if blocked:
            print(f"[ABORTED] Refusing to commit secret/runtime files: {blocked}")
            return 1
        # Commit
        res = subprocess.run(["git", "commit", "-m", commit_message], cwd=str(SOURCE_REPO_DIR), capture_output=True, text=True)
        print(res.stdout)
        if res.returncode != 0 and "nothing to commit" in res.stdout:
            print("[Info] Working tree clean. Nothing to commit.")
            return 0

        # Push to origin
        print("Pushing to remote origin...")
        push_res = subprocess.run(["git", "push"], cwd=str(SOURCE_REPO_DIR), capture_output=True, text=True)
        print(push_res.stdout)
        if push_res.stderr:
            print(push_res.stderr)

        if push_res.returncode == 0:
            print("[SUCCESS] Pushed successfully to GitHub.")
        else:
            print("[Warning] Git push returned non-zero code. Check network or remote permissions.")
        return push_res.returncode
    except Exception as exc:
        print(f"[Error] Git command failed: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Fairybread Code Promotion & Git Distribution Tool")
    parser.add_argument("--diff", action="store_true", help="Show differences between sandbox staging and master E: repo")
    parser.add_argument("--promote", action="store_true", help="Promote staged files from sandbox to master E: repo")
    parser.add_argument("--git-push", type=str, nargs="?", const="", help="Commit master repo and push to GitHub")

    args = parser.parse_args()

    if args.diff:
        return show_diff()
    elif args.promote:
        return promote_to_main()
    elif args.git_push is not None:
        return push_to_git(args.git_push)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
