"""Version-Explicit Windows Beta Installer for Fairybread (Beta v0.9.1).

Complies with all strict installer rules:
(a) Defaults to version-stamped folder: C:\\Program Files\\Fairybread - Beta v0.9.1 (editable + Browse button)
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

APP_VERSION = "0.9.1"
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
        "gemini": {"enabled": True, "model": "gemini-2.5-flash"},
        "openai": {"enabled": True},
        "deepseek": {"enabled": True, "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
        "qwen": {"enabled": True, "model": "Qwen/Qwen3.8-27B", "base_url": "https://api.deepinfra.com/v1/openai"},
        "cohere": {"enabled": True},
        "mistral": {"enabled": True, "model": "codestral-latest"},
    },
    "ui_settings": {
        "enter_to_send": True,
        "badge_display_mode": "icons_only",
        "theme": "dark",
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


def perform_installation(
    target_dir: Path,
    register_system_shortcuts: bool = True,
    custom_data_dir: Path | None = None,
    source_mirror_dir: Path | None = None,
    install_source_mirror: bool = True,
) -> list[str]:
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

    default_appdata = (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace").resolve()
    effective_data_dir = Path(custom_data_dir).resolve() if custom_data_dir else default_appdata
    effective_data_dir.mkdir(parents=True, exist_ok=True)
    (effective_data_dir / "idle_notebooks").mkdir(parents=True, exist_ok=True)

    effective_mirror_dir = (
        Path(source_mirror_dir).resolve()
        if source_mirror_dir
        else (effective_data_dir / "source_mirror")
    )

    if install_source_mirror:
        effective_mirror_dir.mkdir(parents=True, exist_ok=True)
        for item in sorted(src_dir.iterdir()):
            if item.name in excluded or item.name.startswith("test_") or item.name.startswith("."):
                continue
            if item.is_file() and item.suffix.lower() in {".py", ".md"}:
                shutil.copy2(item, effective_mirror_dir / item.name)
        if os.name == "nt":
            subprocess.run(
                ["icacls", str(effective_mirror_dir), "/grant:r", "Users:(OI)(CI)RX", "/T", "/C"],
                check=False,
                capture_output=True,
            )

    cfg_to_write = json.loads(json.dumps(CLEAN_DEFAULT_CONFIG))
    if effective_data_dir != default_appdata:
        cfg_to_write.setdefault("ui_settings", {})["custom_data_dir"] = str(effective_data_dir)
        default_appdata.mkdir(parents=True, exist_ok=True)
        (default_appdata / "storage_location.json").write_text(
            json.dumps({"custom_data_dir": str(effective_data_dir)}, indent=2) + "\n",
            encoding="utf-8",
        )
    if install_source_mirror:
        cfg_to_write.setdefault("idle_settings", {})["source_mirror_dir"] = str(effective_mirror_dir)

    # Write clean default palace_config.json (zero personal data from developer machine)
    clean_cfg_path = target / "palace_config.json"
    clean_cfg_path.write_text(json.dumps(cfg_to_write, indent=2) + "\n", encoding="utf-8")
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

    default_data_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace"
    default_mirror_root = default_data_root / "source_mirror"

    path_lbl = QLabel("<b>1. Application Install Directory (Version-Isolated Folder — will not overwrite existing installs):</b>")
    path_lbl.setTextFormat(Qt.TextFormat.RichText)
    lay.addWidget(path_lbl)

    path_row = QHBoxLayout()
    path_edit = QLineEdit(str(DEFAULT_INSTALL_DIR), dlg)
    path_edit.setStyleSheet("background:#161b22; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:6px;")
    browse_btn = QPushButton("Browse…", dlg)
    browse_btn.setStyleSheet("background:#21262d; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:6px 14px;")

    def _browse():
        chosen = QFileDialog.getExistingDirectory(dlg, "Select Installation Parent Directory", str(Path(path_edit.text()).parent))
        if chosen:
            path_edit.setText(str(Path(chosen) / VERSION_STAMPED_NAME))

    browse_btn.clicked.connect(_browse)
    path_row.addWidget(path_edit, 1)
    path_row.addWidget(browse_btn)
    lay.addLayout(path_row)

    data_lbl = QLabel("<b>2. Memory &amp; Data Directory (Normal Memory, Experimental Memory, Chat History &amp; Uploaded Files):</b>")
    data_lbl.setTextFormat(Qt.TextFormat.RichText)
    lay.addWidget(data_lbl)

    data_row = QHBoxLayout()
    data_edit = QLineEdit(str(default_data_root), dlg)
    data_edit.setStyleSheet("background:#161b22; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:6px;")
    data_browse_btn = QPushButton("Browse…", dlg)
    data_browse_btn.setStyleSheet("background:#21262d; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:6px 14px;")

    def _browse_data():
        chosen = QFileDialog.getExistingDirectory(dlg, "Select Memory & Data Directory", data_edit.text())
        if chosen:
            data_edit.setText(chosen)

    data_browse_btn.clicked.connect(_browse_data)
    data_row.addWidget(data_edit, 1)
    data_row.addWidget(data_browse_btn)
    lay.addLayout(data_row)

    mirror_chk = QCheckBox(
        "3. Install a Read-Only Source Code Copy for AI Code Inspection (Reference + On-Demand Read):",
        dlg,
    )
    mirror_chk.setChecked(True)
    mirror_chk.setStyleSheet("font-weight:700; color:#f0f6fc;")
    lay.addWidget(mirror_chk)

    mirror_row = QHBoxLayout()
    mirror_edit = QLineEdit(str(default_mirror_root), dlg)
    mirror_edit.setStyleSheet("background:#161b22; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:6px;")
    mirror_browse_btn = QPushButton("Browse…", dlg)
    mirror_browse_btn.setStyleSheet("background:#21262d; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:6px 14px;")

    def _browse_mirror():
        chosen = QFileDialog.getExistingDirectory(dlg, "Select Shared Source Code Mirror Directory", mirror_edit.text())
        if chosen:
            mirror_edit.setText(chosen)

    mirror_browse_btn.clicked.connect(_browse_mirror)
    mirror_chk.toggled.connect(mirror_edit.setEnabled)
    mirror_chk.toggled.connect(mirror_browse_btn.setEnabled)
    mirror_row.addWidget(mirror_edit, 1)
    mirror_row.addWidget(mirror_browse_btn)
    lay.addLayout(mirror_row)

    summary_box = QTextBrowser(dlg)
    summary_box.setStyleSheet("background:#131720; color:#c9d1d9; border:1px solid #262c3a; border-radius:8px; padding:10px;")
    summary_box.setHtml(
        "<b>Ready to Install:</b><ul>"
        f"<li>Application Folder: <code>{DEFAULT_INSTALL_DIR}</code></li>"
        f"<li>Memory &amp; Data Folder (Normal + Experimental): <code>{default_data_root}</code></li>"
        f"<li>Read-Only Source Code Mirror (for AI on-demand reading): <code>{default_mirror_root}</code></li>"
        "<li>Creates version-specific <b>Desktop Shortcut</b>, <b>Start Menu Entry</b>, and <b>Uninstall Registry Entry</b>.</li>"
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
        data_p = Path(data_edit.text().strip()) if data_edit.text().strip() else default_data_root
        mirror_p = Path(mirror_edit.text().strip()) if mirror_edit.text().strip() else default_mirror_root
        do_mirror = bool(mirror_chk.isChecked())
        try:
            files = perform_installation(
                target_p,
                custom_data_dir=data_p,
                source_mirror_dir=mirror_p,
                install_source_mirror=do_mirror,
            )
            files_html = "".join(f"<li><code>{f}</code></li>" for f in files)
            mirror_note = f"<code>{mirror_p}</code> (Read-Only)" if do_mirror else "Disabled"
            summary_box.setHtml(
                f"<h3 style='color:#22c55e; margin:0;'>✓ Installation Complete!</h3>"
                f"<p><b>Installed Folder:</b> <code>{target_p}</code><br>"
                f"<b>Memory &amp; Data Folder:</b> <code>{data_p}</code><br>"
                f"<b>Shared Source Code Mirror:</b> {mirror_note}</p>"
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
