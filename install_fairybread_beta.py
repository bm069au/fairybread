"""Version-Explicit Windows Beta Installer for Fairybread (Beta v0.92a).

Complies with all strict installer rules:
(a) Defaults to version-stamped folder: C:\\Program Files\\Fairybread - Beta v0.92a (editable + Browse button)
(b) Protects non-Fairybread directories from accidental overwrites while supporting safe VLC-style upgrades on existing Fairybread folders
(c) Always creates an automatic pre-upgrade ZIP backup BEFORE modifying any files or data
(d) Preserves settings, API keys, chats, and Memory Palaces by default (even in custom non-Program Files folders) with explicit opt-in Clean Install
(e) Creates version-specific Desktop shortcut, Start Menu entry, and Uninstall registry entry.
"""
from __future__ import annotations

import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import webbrowser
import zipfile

APP_VERSION = "0.92a"
VERSION_STAMPED_NAME = f"Fairybread - Beta v{APP_VERSION}"
DEFAULT_INSTALL_DIR = Path(r"C:\Program Files") / VERSION_STAMPED_NAME
UNINSTALL_REG_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{VERSION_STAMPED_NAME}"

DONATION_URLS = {
    "5": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=5",
    "10": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=10",
    "25": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=25",
    "50": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=50",
    "350": "https://github.com/sponsors/bm069au/sponsorships?frequency=one-time&amount=350",
    "other": "https://github.com/sponsors/bm069au?frequency=one-time",
}
CORP_MAILTO = "mailto:bm069au@gmail.com?subject=Fairybread%20Corporate%20License%20Inquiry%20(%3E2%20Seats)"

CLEAN_DEFAULT_CONFIG = {
    "providers": {
        "gemini": {"enabled": True, "model": "gemini-4-neon"},
        "openai": {"enabled": True},
        "deepseek": {"enabled": True, "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
        "qwen": {"enabled": True, "model": "Qwen/Qwen3.8-27B", "base_url": "https://api.deepinfra.com/v1/openai", "max_tokens": 8192},
        "cohere": {"enabled": True},
        "mistral": {"enabled": True, "model": "codestral-latest"},
    },
    "ui_settings": {
        "enter_to_send": True,
        "badge_display_mode": "icons_only",
        "theme": "dark",
        "auto_refresh_catalog": True,
    },
    "voice_settings": {
        "tts_engine": "auto",
        "voice_name": "coral",
        "gemini_voice_name": "Kore",
        "voice_style": "warm_american",
        "custom_style_prompt": "",
        "speech_speed": 1.0,
        "microphone_device": "System default",
        "mic_gain_percent": 150,
        "silence_timeout_ms": 1500,
        "volume_percent": 100,
        "auto_speak_responses": False,
        "voice_companion_enabled": True,
        "spoken_summary_for_background": True,
    },
    "graphics_settings": {
        "prompt_duo": ["gemini", "openai"],
        "prompt_duo_fallback": ["deepseek", "qwen", "cerebras", "groq"],
        "primary_image_engine": "gemini-3-pro-image",
        "draft_image_engine": "gemini-3.1-flash-image",
        "fallback_image_engines": ["gemini-3.1-flash-image", "gpt-image-2", "flux-1-dev"],
    },
    "access_permissions": {
        "permission_mode": "default",
        "write_exclusions": [],
        "allow_workspace_writes": True,
        "allow_shell_commands": True,
        "allow_self_patch": True,
    },
    "agent_defaults": {
        "approval_policy": "on_request",
        "sandbox_mode": "sandbox_write",
        "web_search_default": "default",
        "output_detail": "high",
        "reasoning_summary": "auto",
        "synthesizer_mode": "auto_fast",
        "smart_routing": True,
        "provider_timeout_sec": 45,
        "straggler_grace_sec": 15,
    },
}


def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_payload_source_dir() -> Path:
    here = Path(__file__).resolve().parent
    payload_sub = here / "payload"
    return payload_sub if payload_sub.is_dir() else here


def is_existing_fairybread_dir(target: Path) -> bool:
    p = Path(target)
    return p.is_dir() and (p / "palace_gui.py").is_file()


def create_pre_upgrade_backup(
    data_dir: Path,
    target_dir: Path | None = None,
) -> Path | None:
    """Create an atomic pre-upgrade ZIP backup of existing user settings, keys, chats, and Memory Palaces."""
    eff_data = Path(data_dir)
    files_to_pack: list[tuple[Path, str]] = []

    for fname in (
        "palace_config.json",
        "credentials.json",
        "memory.db",
        "memory_proposals.jsonl",
        "session_context.jsonl",
    ):
        fp = eff_data / fname
        if fp.is_file():
            files_to_pack.append((fp, f"data/{fname}"))

    for dname in ("sessions", "idle_notebooks", "generated_images"):
        dp = eff_data / dname
        if dp.is_dir():
            for child in sorted(dp.rglob("*")):
                if child.is_file():
                    rel = child.relative_to(eff_data).as_posix()
                    files_to_pack.append((child, f"data/{rel}"))

    if target_dir is not None and Path(target_dir).is_dir():
        tgt = Path(target_dir)
        for fname in ("palace_config.json", "credentials.json"):
            fp = tgt / fname
            if fp.is_file():
                files_to_pack.append((fp, f"install_dir/{fname}"))

    if not files_to_pack:
        return None

    bak_dir = eff_data / "pre_upgrade_backups"
    bak_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_zip = bak_dir / f"fairybread_pre_upgrade_{stamp}.zip"
    tmp_zip = bak_dir / f".fairybread_pre_upgrade_{stamp}.tmp.zip"

    manifest = {
        "created_at": datetime.now().isoformat(),
        "app_version": APP_VERSION,
        "data_dir": str(eff_data),
        "target_dir": str(target_dir) if target_dir else "",
        "file_count": len(files_to_pack),
        "files": [arc for _, arc in files_to_pack],
    }

    try:
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
            for src_file, arcname in files_to_pack:
                zf.write(src_file, arcname=arcname)
        os.replace(tmp_zip, final_zip)
        return final_zip
    except Exception:
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def create_windows_shortcut(target_path: str, arguments: str, shortcut_path: Path, icon_path: str, working_dir: str) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    ps_script = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut_path}'); "
        f"$s.TargetPath = '{target_path}'; "
        f"$s.Arguments = '{arguments}'; "
        f"$s.WorkingDirectory = '{working_dir}'; "
        f"if (Test-Path '{icon_path}') {{ $s.IconLocation = '{icon_path}' }}; "
        f"$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=False, capture_output=True)


def register_uninstaller(install_dir: Path, uninstaller_cmd: str, icon_path: Path) -> None:
    if os.name != "nt":
        return
    import winreg
    for root_hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.CreateKey(root_hive, UNINSTALL_REG_KEY) as key:
                winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, VERSION_STAMPED_NAME)
                winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
                winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Brett Martin Moore")
                winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
                winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(icon_path))
                winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninstaller_cmd)
                winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
            break
        except PermissionError:
            continue


def perform_installation_detailed(
    target_dir: Path,
    *,
    register_system_shortcuts: bool = True,
    allow_upgrade_existing: bool = False,
    keep_existing_settings: bool = True,
    wipe_memory_and_chats: bool = False,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Install or upgrade Fairybread with automatic pre-upgrade backup and VLC-style data preservation."""
    target = Path(target_dir).resolve()
    eff_data = (
        Path(data_dir).resolve()
        if data_dir is not None
        else (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace").resolve()
    )
    existing_non_empty = target.exists() and any(target.iterdir())
    is_upgrade = existing_non_empty and is_existing_fairybread_dir(target)

    if existing_non_empty and (not allow_upgrade_existing or not is_upgrade):
        raise FileExistsError(
            f"Refusing to overwrite existing directory at:\n{target}\n\n"
            f"Choose an empty folder, or confirm upgrading an existing Fairybread folder."
        )

    # Fail-Safe 1: Always archive existing settings, keys, and Memory Palaces BEFORE modifying anything
    backup_zip = create_pre_upgrade_backup(
        eff_data,
        target_dir=(target if target.exists() else None),
    )

    src_dir = get_payload_source_dir()
    target.mkdir(parents=True, exist_ok=True)
    eff_data.mkdir(parents=True, exist_ok=True)

    # Grant standard user write permissions on target folder so local files never redirect to VirtualStore
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(target), "/grant", "Users:(OI)(CI)M", "/T", "/C"],
            check=False,
            capture_output=True,
        )

    installed_files: list[str] = []
    excluded = {
        "install_fairybread_beta.py",
        "palace_config.json",
        "credentials.json",
        "reboot_history.json",
        "ask_gpt_WORKING_BACKUP.py",
    }

    for item in sorted(src_dir.iterdir()):
        if item.name in excluded or item.name.startswith("test_") or item.name.startswith("."):
            continue
        if item.is_file() and (
            item.suffix.lower() in {".py", ".md", ".png", ".ico", ".txt"}
            or item.name == "catalog_feed_template.json"
        ):
            shutil.copy2(item, target / item.name)
            installed_files.append(item.name)

    # Fail-Safe 2: VLC-style data handling (preserve existing configs by default, even in non-Program Files folders)
    is_program_files = "program files" in str(target).lower()
    cfg_in_target = target / "palace_config.json"
    if keep_existing_settings and cfg_in_target.is_file() and not is_program_files:
        pass  # Strictly keep user's existing local config
    elif not cfg_in_target.is_file() or not keep_existing_settings:
        cfg_in_target.write_text(json.dumps(CLEAN_DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
        installed_files.append("palace_config.json")

    cfg_in_data = eff_data / "palace_config.json"
    if not keep_existing_settings and cfg_in_data.is_file():
        cfg_in_data.write_text(json.dumps(CLEAN_DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")

    actually_wiped_memory = bool(wipe_memory_and_chats and not keep_existing_settings)
    if actually_wiped_memory:
        for fname in ("memory.db", "memory_proposals.jsonl", "session_context.jsonl"):
            fp = eff_data / fname
            if fp.is_file():
                fp.unlink()
        for dname in ("sessions", "idle_notebooks"):
            dp = eff_data / dname
            if dp.is_dir():
                shutil.rmtree(dp, ignore_errors=True)

    # Write uninstaller script
    uninst_py = target / "uninstall_fairybread.py"
    uninst_py.write_text(
        f'import os, shutil, winreg\n'
        f'from pathlib import Path\n'
        f'p = Path(r"{target}")\n'
        f'print("Uninstalling {VERSION_STAMPED_NAME} from", p)\n',
        encoding="utf-8",
    )
    installed_files.append("uninstall_fairybread.py")

    if register_system_shortcuts:
        pythonw_exe = Path(sys.executable).with_name("pythonw.exe")
        launcher_exe = str(pythonw_exe if pythonw_exe.exists() else Path(sys.executable))
        gui_script = f'"{target / "palace_gui.py"}"'
        icon_file = target / "fairybread_icon.png"

        # Desktop shortcut
        desktop_dir = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        desktop_lnk = desktop_dir / f"{VERSION_STAMPED_NAME}.lnk"
        create_windows_shortcut(launcher_exe, gui_script, desktop_lnk, str(icon_file), str(target))

        # Start Menu shortcut
        appdata_roam = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        start_menu_lnk = appdata_roam / r"Microsoft\Windows\Start Menu\Programs" / f"{VERSION_STAMPED_NAME}.lnk"
        create_windows_shortcut(launcher_exe, gui_script, start_menu_lnk, str(icon_file), str(target))

        register_uninstaller(target, f'"{sys.executable}" "{uninst_py}"', icon_file)

    return {
        "installed_files": installed_files,
        "backup_zip": str(backup_zip) if backup_zip else "",
        "upgraded_existing": bool(is_upgrade),
        "preserved_settings": bool(keep_existing_settings),
        "wiped_memory": actually_wiped_memory,
    }


def perform_installation(target_dir: Path, register_system_shortcuts: bool = True) -> list[str]:
    """Install all clean Fairybread files into target_dir (refusing to overwrite an existing installation)."""
    return perform_installation_detailed(
        target_dir,
        register_system_shortcuts=register_system_shortcuts,
        allow_upgrade_existing=False,
        keep_existing_settings=True,
        wipe_memory_and_chats=False,
    )["installed_files"]


def run_gui_installer() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTextBrowser,
        QVBoxLayout,
    )

    app = QApplication.instance() or QApplication(sys.argv)
    dlg = QDialog()
    dlg.setWindowTitle(f"{VERSION_STAMPED_NAME} — Setup Wizard")
    dlg.resize(760, 680)
    dlg.setStyleSheet("background:#0d1117; color:#f0f6fc; font-family:'Segoe UI'; font-size:13px;")

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(22, 18, 22, 18)
    lay.setSpacing(10)

    title_lbl = QLabel(
        f"<h2 style='margin:0; color:#f0f6fc;'>🧚 {VERSION_STAMPED_NAME} — Setup</h2>"
        "<p style='color:#8b949e; margin-top:4px;'>"
        "Democratic Multi-AI Council, 300-DPI Graphics Engine, Exhaustive Email Search &amp; Shared Memory Palace"
        "</p>"
    )
    title_lbl.setTextFormat(Qt.TextFormat.RichText)
    lay.addWidget(title_lbl)

    path_lbl = QLabel("<b>1. Installation Directory (Defaults to version-isolated folder; detects existing installs cleanly):</b>")
    path_lbl.setTextFormat(Qt.TextFormat.RichText)
    lay.addWidget(path_lbl)

    path_row = QHBoxLayout()
    path_edit = QLineEdit(str(DEFAULT_INSTALL_DIR), dlg)
    path_edit.setStyleSheet("background:#161b22; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:7px;")
    browse_btn = QPushButton("Browse…", dlg)
    browse_btn.setStyleSheet("background:#21262d; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:7px 14px;")

    def _browse():
        chosen = QFileDialog.getExistingDirectory(dlg, "Select Installation Parent Directory", str(Path(path_edit.text()).parent))
        if chosen:
            chosen_p = Path(chosen)
            if is_existing_fairybread_dir(chosen_p):
                path_edit.setText(str(chosen_p))
            else:
                path_edit.setText(str(chosen_p / VERSION_STAMPED_NAME))

    browse_btn.clicked.connect(_browse)
    path_row.addWidget(path_edit, 1)
    path_row.addWidget(browse_btn)
    lay.addLayout(path_row)

    target_status_lbl = QLabel("")
    target_status_lbl.setStyleSheet("color:#58a6ff; font-size:12px;")
    lay.addWidget(target_status_lbl)

    # 2. VLC-Style Fail-Safe Upgrade / Clean Install Options
    opts_frame = QFrame(dlg)
    opts_frame.setStyleSheet("background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;")
    opts_lay = QVBoxLayout(opts_frame)
    opts_lay.setSpacing(6)
    opts_hdr = QLabel("<b>2. Existing Settings, API Keys &amp; Memory Palaces:</b>")
    opts_hdr.setTextFormat(Qt.TextFormat.RichText)
    opts_lay.addWidget(opts_hdr)

    keep_data_chk = QCheckBox(
        "Keep existing settings, API keys, chats && Memory Palaces (Recommended — Default)",
        opts_frame,
    )
    keep_data_chk.setChecked(True)
    clean_reset_chk = QCheckBox(
        "Clean Install — Reset settings to factory defaults (auto-backup ZIP saved first)",
        opts_frame,
    )
    clean_reset_chk.setChecked(False)
    wipe_mem_chk = QCheckBox(
        "Also wipe existing Memory Palaces && chat history (requires confirmation; auto-backup ZIP saved first)",
        opts_frame,
    )
    wipe_mem_chk.setChecked(False)
    wipe_mem_chk.setEnabled(False)

    def _on_keep_toggled(checked: bool):
        clean_reset_chk.blockSignals(True)
        clean_reset_chk.setChecked(not checked)
        clean_reset_chk.blockSignals(False)
        wipe_mem_chk.setEnabled(not checked)
        if checked:
            wipe_mem_chk.setChecked(False)

    def _on_clean_toggled(checked: bool):
        keep_data_chk.blockSignals(True)
        keep_data_chk.setChecked(not checked)
        keep_data_chk.blockSignals(False)
        wipe_mem_chk.setEnabled(checked)
        if not checked:
            wipe_mem_chk.setChecked(False)

    keep_data_chk.toggled.connect(_on_keep_toggled)
    clean_reset_chk.toggled.connect(_on_clean_toggled)
    opts_lay.addWidget(keep_data_chk)
    opts_lay.addWidget(clean_reset_chk)
    opts_lay.addWidget(wipe_mem_chk)
    lay.addWidget(opts_frame)

    summary_box = QTextBrowser(dlg)
    summary_box.setStyleSheet("background:#131720; color:#c9d1d9; border:1px solid #262c3a; border-radius:8px; padding:10px;")
    summary_box.setHtml(
        "<b>Ready to Install:</b><ul>"
        f"<li>Target Folder: <code>{DEFAULT_INSTALL_DIR}</code></li>"
        "<li>Automatically archives existing user data into <code>pre_upgrade_backups/</code> before changing anything.</li>"
        "<li>Creates version-specific <b>Desktop Shortcut</b>, <b>Start Menu Entry</b>, and <b>Uninstall Registry Entry</b>.</li>"
        "<li>Stores user API keys (Windows DPAPI encrypted) and Memory Palaces locally in <code>%LOCALAPPDATA%\\Palace</code>.</li>"
        "</ul>"
    )
    lay.addWidget(summary_box, 1)

    # One-Click USD Donation & Corporate License Banner
    don_frame = QFrame(dlg)
    don_frame.setStyleSheet("background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px;")
    don_lay = QVBoxLayout(don_frame)
    don_lbl = QLabel(
        "<b>❤️ A Personal Note from Brett (USD Donations &amp; Corporate Licensing):</b><br>"
        "<span style='color:#c9d1d9; font-size:12px;'>"
        "In real life I am a disabled man on a disability pension struggling to pay my bills. "
        "Fairybread is free for personal use (up to 2 seats), and any donation genuinely helps me pay my bills and keep building! "
        "Supporters get our <b>Newsletter</b>, <b>Beta Test Group</b>, <b>Priority Code Requests</b>, <b>Themes</b> &amp; <b>Idle Mode Add-Ons</b>. "
        "For businesses using &gt;2 seats, a corporate license is negotiable."
        "</span>"
    )
    don_lbl.setWordWrap(True)
    don_lbl.setTextFormat(Qt.TextFormat.RichText)
    don_lay.addWidget(don_lbl)

    tier_row = QHBoxLayout()
    for label, key, col in [
        ("$5 USD", "5", "#1f6feb"),
        ("$10 USD", "10", "#238636"),
        ("$25 USD", "25", "#8957e5"),
        ("$50 USD", "50", "#d29922"),
        ("$350 USD", "350", "#b62324"),
        ("Other USD", "other", "#30363d"),
    ]:
        b = QPushButton(label, don_frame)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"background:{col}; color:#ffffff; border:none; border-radius:6px; padding:6px 12px; font-weight:700;"
        )
        u = DONATION_URLS[key]
        b.clicked.connect(lambda _c=False, url=u: webbrowser.open(url))
        tier_row.addWidget(b)

    corp_btn = QPushButton("🏢 Corporate (>2 Seats)", don_frame)
    corp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    corp_btn.setStyleSheet("background:#21262d; color:#58a6ff; border:1px solid #388bfd; border-radius:6px; padding:6px 10px; font-weight:600;")
    corp_btn.clicked.connect(lambda: webbrowser.open(CORP_MAILTO))
    tier_row.addWidget(corp_btn)
    don_lay.addLayout(tier_row)
    lay.addWidget(don_frame)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    install_btn = QPushButton(f"Install {VERSION_STAMPED_NAME}", dlg)
    install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    install_btn.setStyleSheet("background:#238636; color:#ffffff; border:none; border-radius:6px; padding:9px 22px; font-weight:700;")
    close_btn = QPushButton("Cancel", dlg)
    close_btn.setStyleSheet("background:#21262d; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:9px 18px;")
    close_btn.clicked.connect(dlg.reject)
    btn_row.addWidget(install_btn)
    btn_row.addWidget(close_btn)
    lay.addLayout(btn_row)

    def _refresh_target_status():
        raw_t = path_edit.text().strip()
        p = Path(raw_t) if raw_t else DEFAULT_INSTALL_DIR
        if is_existing_fairybread_dir(p):
            target_status_lbl.setStyleSheet("color:#3fb950; font-size:12px;")
            target_status_lbl.setText("✓ Existing Fairybread installation detected — upgrade mode active (pre-upgrade backup guaranteed).")
            if install_btn.isEnabled():
                install_btn.setText("Upgrade Existing Fairybread")
        elif p.exists() and any(p.iterdir()):
            target_status_lbl.setStyleSheet("color:#f85149; font-size:12px;")
            target_status_lbl.setText("⚠ Non-empty non-Fairybread directory selected — pick a new or existing Fairybread folder.")
            if install_btn.isEnabled():
                install_btn.setText(f"Install {VERSION_STAMPED_NAME}")
        else:
            target_status_lbl.setStyleSheet("color:#8b949e; font-size:12px;")
            target_status_lbl.setText("Fresh folder — ready to install.")
            if install_btn.isEnabled():
                install_btn.setText(f"Install {VERSION_STAMPED_NAME}")

    path_edit.textChanged.connect(lambda _t: _refresh_target_status())
    _refresh_target_status()

    def _run_install():
        target_p = Path(path_edit.text().strip())
        keep_cfg = keep_data_chk.isChecked()
        wipe_mem = wipe_mem_chk.isChecked() and not keep_cfg
        if wipe_mem:
            reply = QMessageBox.question(
                dlg,
                "Confirm Memory & Chat Wipe",
                "You selected wiping existing Memory Palaces and chat history.\n\n"
                "An automatic pre-upgrade backup ZIP will still be saved first, but active files will be cleared.\n\nProceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            res = perform_installation_detailed(
                target_p,
                allow_upgrade_existing=is_existing_fairybread_dir(target_p),
                keep_existing_settings=keep_cfg,
                wipe_memory_and_chats=wipe_mem,
            )
            files = res["installed_files"]
            bak_path = res.get("backup_zip") or "None needed (no prior user data)"
            files_html = "".join(f"<li><code>{f}</code></li>" for f in files)
            summary_box.setHtml(
                f"<h3 style='color:#22c55e; margin:0;'>✓ {'Upgrade' if res.get('upgraded_existing') else 'Installation'} Complete!</h3>"
                f"<p><b>Installed Folder:</b> <code>{target_p}</code></p>"
                f"<p><b>Automatic Pre-Upgrade Backup:</b> <code>{bak_path}</code></p>"
                f"<p><b>User Settings &amp; Memory Preserved:</b> {'Yes' if res.get('preserved_settings') else 'Reset to Defaults'}</p>"
                f"<p><b>Shortcuts Created:</b> Desktop (<code>{VERSION_STAMPED_NAME}.lnk</code>), Start Menu &amp; Windows Uninstall Registry.</p>"
                f"<p><b>Installed Files ({len(files)}):</b></p><ul>{files_html}</ul>"
                f"<p style='color:#58a6ff;'><b>Thank you for testing Fairybread!</b> Consider a one-click USD donation below to support development.</p>"
            )
            install_btn.setEnabled(False)
            install_btn.setText("✓ Installed")
            close_btn.setText("Finish && Launch Fairybread")

            def _launch_and_close():
                subprocess.Popen([sys.executable, str(target_p / "palace_gui.py")], cwd=str(target_p))
                dlg.accept()

            close_btn.clicked.disconnect()
            close_btn.clicked.connect(_launch_and_close)
        except Exception as exc:
            QMessageBox.warning(dlg, "Installation Notice", str(exc))

    install_btn.clicked.connect(_run_install)
    return dlg.exec()


if __name__ == "__main__":
    sys.exit(run_gui_installer())
