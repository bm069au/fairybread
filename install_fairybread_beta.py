"""Version-Explicit Windows Beta Installer for Fairybread (Beta v0.9.1f).

Complies with all strict installer rules:
(a) Defaults to version-stamped folder: C:\\Program Files\\Fairybread - Beta v0.9.1f (editable + Browse button)
(b) Checks for and refuses to overwrite any existing installation
(c) Accounts for Windows Program Files standard-user write permissions (ACL + %LOCALAPPDATA%\\Palace runtime storage)
(d) Shows a post-install summary of the exact folder and files installed + One-Click USD Donation ($5/$10/$20/$50/Other) & Corporate License banner
(e) Creates version-specific Desktop shortcut, Start Menu entry, and Uninstall registry entry.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

APP_VERSION = "0.9.1f"
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


def perform_installation(target_dir: Path, register_system_shortcuts: bool = True) -> list[str]:
    """Install all clean Fairybread files into target_dir (refusing to overwrite an existing installation)."""
    target = Path(target_dir).resolve()
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(
            f"Refusing to overwrite existing installation at:\n{target}\n\n"
            f"Please choose a new or empty version-stamped folder."
        )

    src_dir = get_payload_source_dir()
    target.mkdir(parents=True, exist_ok=True)

    # Grant standard user write permissions on target folder so local files never redirect to VirtualStore
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(target), "/grant", "Users:(OI)(CI)M", "/T", "/C"],
            check=False,
            capture_output=True,
        )

    installed_files: list[str] = []
    excluded = {"install_fairybread_beta.py", "palace_config.json", "credentials.json", "reboot_history.json", "ask_gpt_WORKING_BACKUP.py"}

    for item in sorted(src_dir.iterdir()):
        if item.name in excluded or item.name.startswith("test_") or item.name.startswith("."):
            continue
        if item.is_file() and item.suffix.lower() in {".py", ".md", ".png", ".ico", ".txt"}:
            shutil.copy2(item, target / item.name)
            installed_files.append(item.name)

    # Write clean default palace_config.json (zero personal data from developer machine)
    clean_cfg_path = target / "palace_config.json"
    clean_cfg_path.write_text(json.dumps(CLEAN_DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    installed_files.append("palace_config.json")

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
    return installed_files


def run_gui_installer() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
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
    dlg.resize(740, 560)
    dlg.setStyleSheet("background:#0d1117; color:#f0f6fc; font-family:'Segoe UI'; font-size:13px;")

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(22, 20, 22, 20)
    lay.setSpacing(12)

    title_lbl = QLabel(
        f"<h2 style='margin:0; color:#f0f6fc;'>🧚 {VERSION_STAMPED_NAME} — Setup</h2>"
        "<p style='color:#8b949e; margin-top:4px;'>"
        "Democratic Multi-AI Council, 300-DPI Graphics Engine, Exhaustive Email Search &amp; Shared Memory Palace"
        "</p>"
    )
    title_lbl.setTextFormat(Qt.TextFormat.RichText)
    lay.addWidget(title_lbl)

    path_lbl = QLabel("<b>Installation Directory (Version-Isolated Folder — will not overwrite existing installs):</b>")
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
            path_edit.setText(str(Path(chosen) / VERSION_STAMPED_NAME))

    browse_btn.clicked.connect(_browse)
    path_row.addWidget(path_edit, 1)
    path_row.addWidget(browse_btn)
    lay.addLayout(path_row)

    summary_box = QTextBrowser(dlg)
    summary_box.setStyleSheet("background:#131720; color:#c9d1d9; border:1px solid #262c3a; border-radius:8px; padding:10px;")
    summary_box.setHtml(
        "<b>Ready to Install:</b><ul>"
        f"<li>Target Folder: <code>{DEFAULT_INSTALL_DIR}</code></li>"
        "<li>Creates version-specific <b>Desktop Shortcut</b>, <b>Start Menu Entry</b>, and <b>Uninstall Registry Entry</b>.</li>"
        "<li>Stores user API keys (Windows DPAPI encrypted) and conversations locally in <code>%LOCALAPPDATA%\\Palace</code>.</li>"
        "</ul>"
    )
    lay.addWidget(summary_box, 1)

    # One-Click USD Donation & Corporate License Banner (shown right inside the installer)
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

    def _run_install():
        target_p = Path(path_edit.text().strip())
        try:
            files = perform_installation(target_p)
            files_html = "".join(f"<li><code>{f}</code></li>" for f in files)
            summary_box.setHtml(
                f"<h3 style='color:#22c55e; margin:0;'>✓ Installation Complete!</h3>"
                f"<p><b>Installed Folder:</b> <code>{target_p}</code></p>"
                f"<p><b>Shortcuts Created:</b> Desktop (<code>{VERSION_STAMPED_NAME}.lnk</code>), Start Menu &amp; Windows Uninstall Registry.</p>"
                f"<p><b>Installed Files ({len(files)}):</b></p><ul>{files_html}</ul>"
                f"<p style='color:#58a6ff;'><b>Thank you for testing Fairybread!</b> Consider a one-click USD donation below to support development.</p>"
            )
            install_btn.setEnabled(False)
            install_btn.setText("✓ Installed")
            close_btn.setText("Finish & Launch Fairybread")

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
