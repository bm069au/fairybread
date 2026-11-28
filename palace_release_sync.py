r"""Fairybread End-of-Day & Major Update Master Release Sync Pipeline (`palace_release_sync.py`).

One command to ensure we NEVER miss a local folder, website file, installer binary, or GitHub Release:
  python palace_release_sync.py [--version 0.95h] [--build-installers] [--publish-github-release] [--notes "Summary"]

What this script does automatically in sequence:
1. Reads or bumps `FAIRYBREAD_VERSION` in `palace_config.py` (and computes the 4-part Windows version `0.95.8.0`).
2. Updates all version references across:
   - `palace_config.py` (`FAIRYBREAD_VERSION`)
   - `fairybread_setup.iss` (`AppDispVer`, `AppWinVer`, `OutputExeBase`)
   - `README.md` & `USER_GUIDE.md`
   - `docs/index.html` (all download button hrefs, labels, version badges, and cache-busting `?v=` query strings)
   - `docs/app.js` (`currentSiteVersion = 'v...'`)
   - `test_palace_gui.py` & `test_pipeline_and_autopatch.py` version assertions
3. Compiles (`py_compile`) every `.py` module and syncs all source files + `assets/avatars/` + `theme_assets/` identically across:
   - Master Repository: `E:\Visual_studio\Palace`
   - Live Runtime: `C:\Palace_Live`
   - Agent Sandbox Source Mirror: `C:\Palace_Idle_Sandbox\source_mirror`
   - Agent Sandbox Staging: `C:\Palace_Idle_Sandbox\staging`
4. When `--build-installers` is passed:
   - Runs `build_release.py` to compile the 64-bit Windows Setup `.exe` (Public & Developer) and `.msix`, plus `SHA256SUMS.txt`, `SHA256SUMS.txt.sig`, and `dist/verify.html`.
   - Copies the freshly generated `dist/verify.html` to `docs/verify.html` so `https://fairybread.me/verify.html` always has the exact SHA-256 hashes of the new installers.
5. Commits and pushes all updated source, docs, and website files (`docs/*`) to `origin/main` on GitHub.
6. When `--publish-github-release` is passed:
   - Publishes or updates the official GitHub Release tag (`v<VERSION>`) on `bm069au/fairybread` via `gh release create` with the built `.exe` / `.msix` / `SHA256SUMS` assets attached so the website's `releases/latest/download/...` link works immediately.
"""
from __future__ import annotations

import argparse
import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"E:\Visual_studio\Palace")
LIVE_DIR = Path(r"C:\Palace_Live")
SANDBOX_ROOT = Path(r"C:\Palace_Idle_Sandbox")
MIRROR_DIR = SANDBOX_ROOT / "source_mirror"
STAGING_DIR = SANDBOX_ROOT / "staging"

EXCLUDED_FILES = {
    "key.txt",
    "capture.txt",
    "palace_config.json",
    "credentials.json",
    "ask_gpt_WORKING_BACKUP.py",
}


def version_to_windows_4part(version_str: str) -> str:
    clean = str(version_str or "").strip().lstrip("vV")
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?([a-z])?$", clean, re.IGNORECASE)
    if not m:
        return "0.95.0.0"
    major = int(m.group(1))
    minor = int(m.group(2))
    patch_raw = m.group(3)
    letter = (m.group(4) or "").lower()
    letter_num = (ord(letter) - ord("a") + 1) if letter else 0
    if patch_raw is None:
        return f"{major}.{minor}.{letter_num}.0"
    return f"{major}.{minor}.{int(patch_raw)}.{letter_num}"


def get_current_version() -> str:
    cfg_txt = (ROOT / "palace_config.py").read_text(encoding="utf-8")
    m = re.search(r'FAIRYBREAD_VERSION\s*=\s*"([^"]+)"', cfg_txt)
    if not m:
        raise RuntimeError("Could not find FAIRYBREAD_VERSION in palace_config.py")
    return m.group(1).strip()


def update_all_version_references(ver: str) -> str:
    ver = ver.strip().lstrip("vV")
    win_ver = version_to_windows_4part(ver)
    print(f"[1/6] Synchronizing version references to v{ver} ({win_ver})...")

    # 1. palace_config.py
    p_cfg = ROOT / "palace_config.py"
    txt = p_cfg.read_text(encoding="utf-8")
    txt = re.sub(r'FAIRYBREAD_VERSION\s*=\s*"[^"]+"', f'FAIRYBREAD_VERSION = "{ver}"', txt)
    p_cfg.write_text(txt, encoding="utf-8")

    # 2. fairybread_setup.iss
    p_iss = ROOT / "fairybread_setup.iss"
    if p_iss.is_file():
        iss = p_iss.read_text(encoding="utf-8")
        iss = re.sub(r'#define AppDispVer\s+"[^"]+"', f'#define AppDispVer "{ver}"', iss)
        iss = re.sub(r'#define AppWinVer\s+"[^"]+"', f'#define AppWinVer "{win_ver}"', iss)
        iss = re.sub(
            r'#define OutputExeBase\s+"Fairybread_v[^"]+_Win_x64_Setup"',
            f'#define OutputExeBase "Fairybread_v{ver}_Win_x64_Setup"',
            iss,
        )
        p_iss.write_text(iss, encoding="utf-8")

    # 3. README.md & USER_GUIDE.md
    p_readme = ROOT / "README.md"
    if p_readme.is_file():
        rm = p_readme.read_text(encoding="utf-8")
        rm = re.sub(r"Latest — v0\.95[a-z]?", f"Latest — v{ver}", rm)
        rm = re.sub(r"Fairybread_v0\.95[a-z]?_Win_x64_Setup\.exe", f"Fairybread_v{ver}_Win_x64_Setup.exe", rm)
        rm = re.sub(r"## Key Technical Highlights \(`v0\.95[a-z]?`\)", f"## Key Technical Highlights (`v{ver}`)", rm)
        p_readme.write_text(rm, encoding="utf-8")

    p_ug = ROOT / "USER_GUIDE.md"
    if p_ug.is_file():
        ug = p_ug.read_text(encoding="utf-8")
        ug = re.sub(
            r"# Fairybread \(Beta v0\.95[a-z]?\) — User Guide & Setup Handbook",
            f"# Fairybread (Beta v{ver}) — User Guide & Setup Handbook",
            ug,
        )
        p_ug.write_text(ug, encoding="utf-8")

    # 4. Website: docs/index.html & docs/app.js
    p_idx = ROOT / "docs" / "index.html"
    if p_idx.is_file():
        idx = p_idx.read_text(encoding="utf-8")
        idx = re.sub(r"styles\.css\?v=0\.95[a-z]?", f"styles.css?v={ver}", idx)
        idx = re.sub(r"app\.js\?v=0\.95[a-z]?", f"app.js?v={ver}", idx)
        idx = re.sub(
            r'(<span class="brand-tag dynamic-version-tag">)v0\.95[a-z]?(</span>)',
            rf"\g<1>v{ver}\2",
            idx,
        )
        idx = re.sub(
            r"Fairybread_v0\.95[a-z]?_Win_x64_Setup\.exe",
            f"Fairybread_v{ver}_Win_x64_Setup.exe",
            idx,
        )
        idx = re.sub(r"⬇ Download v0\.95[a-z]? \(Win_x64\)", f"⬇ Download v{ver} (Win_x64)", idx)
        idx = re.sub(r"⬇ Download Fairybread v0\.95[a-z]?", f"⬇ Download Fairybread v{ver}", idx)
        p_idx.write_text(idx, encoding="utf-8")

    p_js = ROOT / "docs" / "app.js"
    if p_js.is_file():
        js = p_js.read_text(encoding="utf-8")
        js = re.sub(r"const currentSiteVersion = 'v0\.95[a-z]?';", f"const currentSiteVersion = 'v{ver}';", js)
        p_js.write_text(js, encoding="utf-8")

    # 5. Test assertions
    p_tg = ROOT / "test_palace_gui.py"
    if p_tg.is_file():
        tg = p_tg.read_text(encoding="utf-8")
        tg = re.sub(r"self\.assertEqual\(FAIRYBREAD_VERSION,\s*'0\.95[a-z]?'\)", f"self.assertEqual(FAIRYBREAD_VERSION, '{ver}')", tg)
        p_tg.write_text(tg, encoding="utf-8")

    p_tp = ROOT / "test_pipeline_and_autopatch.py"
    if p_tp.is_file():
        tp = p_tp.read_text(encoding="utf-8")
        tp = re.sub(
            r'self\.assertEqual\(FAIRYBREAD_WINDOWS_VERSION,\s*"0\.95\.\d+\.0"\)',
            f'self.assertEqual(FAIRYBREAD_WINDOWS_VERSION, "{win_ver}")',
            tp,
        )
        tp = re.sub(r'self\.assertIn\(\'AppDispVer "0\.95[a-z]?"\', iss\)', f'self.assertIn(\'AppDispVer "{ver}"\', iss)', tp)
        tp = re.sub(r'self\.assertIn\(\'AppWinVer "0\.95\.\d+\.0"\', iss\)', f'self.assertIn(\'AppWinVer "{win_ver}"\', iss)', tp)
        p_tp.write_text(tp, encoding="utf-8")

    return win_ver


def sync_local_directories() -> None:
    print("[2/6] Compiling & syncing Master (E:), Live (C:\\Palace_Live), and Sandbox (C:\\Palace_Idle_Sandbox)...")
    for src_f in sorted(ROOT.glob("*")):
        if not src_f.is_file() or src_f.name in EXCLUDED_FILES:
            continue
        if src_f.suffix == ".py":
            py_compile.compile(str(src_f), doraise=True)
        if src_f.suffix in (".py", ".md", ".iss", ".txt", ".ico", ".png", ".json"):
            for dst_root in (LIVE_DIR, MIRROR_DIR, STAGING_DIR):
                if dst_root.exists():
                    shutil.copy2(src_f, dst_root / src_f.name)

    for subdir in ("assets/avatars", "theme_assets", "docs"):
        s_sub = ROOT / subdir
        if s_sub.is_dir():
            for dst_root in (LIVE_DIR, MIRROR_DIR, STAGING_DIR):
                if dst_root.exists():
                    d_sub = dst_root / subdir
                    d_sub.mkdir(parents=True, exist_ok=True)
                    for f in s_sub.glob("*"):
                        if f.is_file():
                            shutil.copy2(f, d_sub / f.name)
    print("  ✓ All 4 local directories are 100% synchronized.")


def build_installers_and_sync_verify_html() -> list[Path]:
    print("[3/6] Building 64-bit Windows Setup.exe & .msix packages via build_release.py...")
    subprocess.run([sys.executable, str(ROOT / "build_release.py")], cwd=str(ROOT), check=True)
    dist_verify = ROOT / "dist" / "verify.html"
    docs_verify = ROOT / "docs" / "verify.html"
    if dist_verify.is_file():
        shutil.copy2(dist_verify, docs_verify)
        print("  ✓ Copied dist/verify.html -> docs/verify.html.")
    ver = get_current_version()
    dist_dir = ROOT / "dist"
    expected = [
        dist_dir / f"Fairybread_v{ver}_Win_x64_Setup.exe",
        dist_dir / f"Fairybread_Developer_v{ver}_Win_x64_Setup.exe",
        dist_dir / f"Fairybread_v{ver}_Win_x64_StoreUpload.msix",
        dist_dir / "SHA256SUMS.txt",
        dist_dir / "SHA256SUMS.txt.sig",
        dist_dir / "verify.html",
    ]
    return [p for p in expected if p.is_file()]


def commit_and_push_git(ver: str, notes: str) -> None:
    print("[4/6] Staging, committing, and pushing source + website (docs/) to GitHub...")
    subprocess.run(["git", "add", "-u"], cwd=str(ROOT), check=True)
    subprocess.run(
        ["git", "add", "docs/", "assets/avatars/", "theme_assets/", "fairybread_setup.iss", "palace_release_sync.py"],
        cwd=str(ROOT),
        check=True,
    )
    msg = notes.strip() or f"Release v{ver}: Sync codebase, website (docs/), and installer metadata"
    res = subprocess.run(["git", "commit", "-m", msg], cwd=str(ROOT), capture_output=True, text=True)
    if res.stdout:
        print(res.stdout.strip())
    subprocess.run(["git", "push", "origin", "main"], cwd=str(ROOT), check=True)
    print("  ✓ Pushed to origin/main.")


def publish_github_release(ver: str, assets: list[Path], notes: str) -> None:
    tag = f"v{ver}"
    title = f"Fairybread Beta v{ver} (Win_x64)"
    print(f"[5/6] Publishing GitHub Release {tag} ({title}) with {len(assets)} asset(s)...")
    rel_notes = notes.strip() or f"Fairybread Beta v{ver} (Win_x64) Official Release. See CHANGELOG.md for full details."
    # Check if release tag already exists
    chk = subprocess.run(["gh", "release", "view", tag, "--repo", "bm069au/fairybread"], cwd=str(ROOT), capture_output=True, text=True)
    if chk.returncode == 0:
        if assets:
            subprocess.run(
                ["gh", "release", "upload", tag, "--clobber", *[str(a) for a in assets], "--repo", "bm069au/fairybread"],
                cwd=str(ROOT),
                check=True,
            )
        print(f"  ✓ Updated existing GitHub Release {tag}.")
    else:
        cmd = [
            "gh",
            "release",
            "create",
            tag,
            *[str(a) for a in assets],
            "--title",
            title,
            "--notes",
            rel_notes,
            "--latest",
            "--repo",
            "bm069au/fairybread",
        ]
        subprocess.run(cmd, cwd=str(ROOT), check=True)
        print(f"  ✓ Published new latest GitHub Release {tag}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fairybread End-of-Day Master Release & Website Sync Pipeline")
    parser.add_argument("--version", type=str, default="", help="Target version string (e.g. 0.95h). Defaults to current FAIRYBREAD_VERSION.")
    parser.add_argument("--build-installers", action="store_true", help="Compile Setup.exe & .msix packages via build_release.py and update docs/verify.html")
    parser.add_argument("--publish-github-release", action="store_true", help="Create/update the official GitHub Release tag and upload Setup.exe binaries")
    parser.add_argument("--notes", type=str, default="", help="Commit / release notes summary")
    args = parser.parse_args()

    ver = (args.version or get_current_version()).strip().lstrip("vV")
    update_all_version_references(ver)
    sync_local_directories()

    built_assets: list[Path] = []
    if args.build_installers:
        built_assets = build_installers_and_sync_verify_html()
        sync_local_directories()

    commit_and_push_git(ver, args.notes)

    if args.publish_github_release:
        if not built_assets:
            dist_dir = ROOT / "dist"
            built_assets = [
                p
                for p in (
                    dist_dir / f"Fairybread_v{ver}_Win_x64_Setup.exe",
                    dist_dir / f"Fairybread_Developer_v{ver}_Win_x64_Setup.exe",
                    dist_dir / f"Fairybread_v{ver}_Win_x64_StoreUpload.msix",
                    dist_dir / "SHA256SUMS.txt",
                    dist_dir / "SHA256SUMS.txt.sig",
                    dist_dir / "verify.html",
                )
                if p.is_file()
            ]
        publish_github_release(ver, built_assets, args.notes)

    print(f"\n[6/6] COMPLETE — Fairybread v{ver} is synced across all local folders, website (docs/), and GitHub!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
