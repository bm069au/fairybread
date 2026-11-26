"""Microsoft-guidelines-compliant Windows uninstaller for Fairybread."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any

_TOML_HEADER_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")
_MOVEFILE_DELAY_UNTIL_REBOOT = 0x4


def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _is_forbidden_drive(path: Path) -> bool:
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    return resolved.upper().startswith("M:")


def _is_unsafe_delete_root(path: Path) -> bool:
    try:
        res = path.resolve()
    except Exception:
        return True
    if _is_forbidden_drive(res):
        return True
    if len(res.parts) <= 2:
        # e.g., C:\ or C:\Users or C:\Windows or C:\Program Files
        return True
    low = str(res).lower().rstrip("\\")
    forbidden_exact = {
        str(Path(os.environ.get("LOCALAPPDATA", "")).resolve()).lower(),
        str(Path(os.environ.get("APPDATA", "")).resolve()).lower(),
        str(Path(os.environ.get("USERPROFILE", "")).resolve()).lower(),
        r"c:\program files",
        r"c:\program files (x86)",
        r"c:\windows",
    }
    return low in forbidden_exact


def _normalize_path_str(raw: str | Path) -> str:
    try:
        s = str(Path(raw).resolve())
    except Exception:
        s = str(raw)
    return s.replace("/", "\\").rstrip("\\").lower()


def _iter_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)


def _entry_references_dir(entry: Any, norm_dir: str) -> bool:
    if not norm_dir:
        return False
    for s in _iter_strings(entry):
        s_norm = s.replace("/", "\\").lower()
        if norm_dir in s_norm:
            return True
    return False


def _strip_toml_server_blocks(text: str, server_name: str = "fairybread") -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    removed = False
    target = server_name.strip().lower()

    for line in lines:
        m = _TOML_HEADER_RE.match(line.rstrip("\r\n"))
        if m:
            raw_hdr = m.group(1)
            parts = [seg.strip().strip("\"'").lower() for seg in raw_hdr.split(".")]
            if len(parts) >= 2 and parts[0] == "mcp_servers" and parts[1] == target:
                skipping = True
                removed = True
                continue
            skipping = False
        if not skipping:
            kept.append(line)

    return "".join(kept), removed


def load_install_manifest(install_dir: Path | None = None) -> dict[str, Any]:
    """Load install_manifest.json or synthesize safe defaults from install_dir."""
    eff_dir = Path(install_dir or Path(__file__).resolve().parent).resolve()
    manifest_fp = eff_dir / "install_manifest.json"
    data: dict[str, Any] = {}
    if manifest_fp.is_file():
        try:
            loaded = json.loads(manifest_fp.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}

    name = str(data.get("version_stamped_name") or eff_dir.name or "Fairybread").strip()
    reg_key = str(
        data.get("reg_key") or rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{name}"
    ).strip()
    reg_hive = str(data.get("reg_hive") or "").strip().upper()

    default_data_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace"
    data_dir_raw = str(data.get("data_dir") or "").strip()
    cfg_fp = eff_dir / "palace_config.json"
    if cfg_fp.is_file():
        try:
            cfg = json.loads(cfg_fp.read_text(encoding="utf-8"))
            custom_d = str((cfg.get("ui_settings") or {}).get("custom_data_dir") or "").strip()
            if custom_d and not custom_d.upper().startswith("M:"):
                data_dir_raw = custom_d
        except Exception:
            pass

    eff_data_dir = Path(data_dir_raw) if data_dir_raw else default_data_dir
    if _is_forbidden_drive(eff_data_dir):
        eff_data_dir = default_data_dir

    shortcuts: list[str] = []
    for raw_lnk in data.get("shortcuts") or []:
        if isinstance(raw_lnk, str) and raw_lnk.strip():
            shortcuts.append(raw_lnk.strip())

    # Always include standard per-user/public shortcut paths for this exact version name as fallbacks
    user_prof = Path(os.environ.get("USERPROFILE", str(Path.home())))
    appdata_roam = Path(os.environ.get("APPDATA", str(user_prof / "AppData" / "Roaming")))
    pub_dir = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    prog_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    fallback_lnks = [
        user_prof / "Desktop" / f"{name}.lnk",
        appdata_roam / r"Microsoft\Windows\Start Menu\Programs" / f"{name}.lnk",
        pub_dir / "Desktop" / f"{name}.lnk",
        prog_data / r"Microsoft\Windows\Start Menu\Programs" / f"{name}.lnk",
    ]
    seen_lnk = {s.lower() for s in shortcuts}
    for lnk in fallback_lnks:
        s = str(lnk)
        if s.lower() not in seen_lnk:
            seen_lnk.add(s.lower())
            shortcuts.append(s)

    return {
        "app_version": str(data.get("app_version") or "").strip(),
        "version_stamped_name": name,
        "install_dir": str(eff_dir),
        "data_dir": str(eff_data_dir),
        "shortcuts": shortcuts,
        "reg_hive": reg_hive,
        "reg_key": reg_key,
    }


def ensure_elevated_if_needed(install_dir: Path, reg_hive: str = "") -> bool:
    """Relaunch elevated via UAC when uninstalling Program Files or HKLM installs; return True if relaunched."""
    if os.name != "nt" or is_admin():
        return False
    needs_admin = ("program files" in str(install_dir).lower()) or (reg_hive.upper() == "HKLM")
    if not needs_admin:
        return False
    args = [f'"{Path(__file__).resolve()}"'] + [f'"{a}"' for a in sys.argv[1:]]
    if "--install-dir" not in sys.argv:
        args.extend(["--install-dir", f'"{install_dir}"'])
    params = " ".join(args)
    rc = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        params,
        tempfile.gettempdir(),
        1,
    )
    if int(rc) > 32:
        return True
    raise PermissionError("Administrator privileges are required to uninstall from Program Files.")


def stop_running_fairybread_in_dir(install_dir: Path) -> int:
    """Terminate only Python processes launched from inside install_dir."""
    if os.name != "nt":
        return 0
    norm_dir = str(Path(install_dir).resolve()).replace("'", "''").lower()
    cur_pid = int(os.getpid())
    par_pid = int(os.getppid()) if hasattr(os, "getppid") else -1
    ps_cmd = (
        f"$dir = '{norm_dir}'; $ex1 = {cur_pid}; $ex2 = {par_pid}; $stopped = 0; "
        "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
        "Where-Object { $_.ProcessId -ne $ex1 -and $_.ProcessId -ne $ex2 -and $_.CommandLine -and $_.CommandLine.ToLower().Contains($dir) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stopped++ }; "
        "Write-Output $stopped"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return int((res.stdout or "0").strip().splitlines()[-1])
    except Exception:
        return 0


def find_other_fairybread_installs(exclude_dir: Path) -> list[dict[str, str]]:
    """Return other Fairybread Uninstall entries pointing to different InstallLocation folders."""
    if os.name != "nt":
        return []
    import winreg

    norm_self = _normalize_path_str(exclude_dir)
    others: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    uninstall_root = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    flags_list = [winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0), winreg.KEY_READ]
    for hive, hive_name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        for access in flags_list:
            try:
                with winreg.OpenKey(hive, uninstall_root, 0, access) as root_k:
                    idx = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(root_k, idx)
                        except OSError:
                            break
                        idx += 1
                        if "fairybread" not in sub_name.lower():
                            continue
                        dedup_k = f"{hive_name}\\{sub_name.lower()}"
                        if dedup_k in seen_keys:
                            continue
                        seen_keys.add(dedup_k)
                        try:
                            with winreg.OpenKey(root_k, sub_name, 0, access) as sub_k:
                                dname, _ = winreg.QueryValueEx(sub_k, "DisplayName")
                                iloc, _ = winreg.QueryValueEx(sub_k, "InstallLocation")
                                if _normalize_path_str(str(iloc)) != norm_self:
                                    others.append({
                                        "hive": hive_name,
                                        "name": str(dname),
                                        "install_location": str(iloc),
                                    })
                        except OSError:
                            continue
                break
            except OSError:
                continue
    return others


def cleanup_mcp_entries_for_dir(
    install_dir: Path,
    *,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
) -> list[str]:
    """Remove only External Agent Bridge (MCP) entries that reference install_dir."""
    home = Path(home_dir) if home_dir is not None else Path.home()
    appdata = (
        Path(appdata_dir)
        if appdata_dir is not None
        else Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    )
    norm_dir = _normalize_path_str(install_dir)
    cleaned: list[str] = []

    json_targets = [
        (home / ".gemini" / "config" / "mcp_config.json", True),
        (appdata / "Claude" / "claude_desktop_config.json", False),
    ]
    for cfg_path, remove_agy_skill in json_targets:
        if not cfg_path.is_file():
            continue
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(loaded, dict):
            continue
        servers = loaded.get("mcpServers")
        if not isinstance(servers, dict) or "fairybread" not in servers:
            continue
        if not _entry_references_dir(servers["fairybread"], norm_dir):
            continue
        servers.pop("fairybread", None)
        cfg_path.write_text(json.dumps(loaded, indent=2) + "\n", encoding="utf-8")
        cleaned.append(str(cfg_path))
        if remove_agy_skill:
            skill_md = home / ".gemini" / "config" / "skills" / "fairybread-council" / "SKILL.md"
            if skill_md.is_file():
                try:
                    skill_md.unlink()
                    cleaned.append(str(skill_md))
                    if skill_md.parent.is_dir() and not any(skill_md.parent.iterdir()):
                        skill_md.parent.rmdir()
                except OSError:
                    pass

    for toml_path in (home / ".codex" / "config.toml", home / ".grok" / "config.toml"):
        if not toml_path.is_file():
            continue
        try:
            raw = toml_path.read_text(encoding="utf-8")
            parsed = tomllib.loads(raw) if raw.strip() else {}
        except Exception:
            continue
        entry = (parsed.get("mcp_servers") or {}).get("fairybread")
        if not entry or not _entry_references_dir(entry, norm_dir):
            continue
        new_text, removed = _strip_toml_server_blocks(raw, server_name="fairybread")
        if not removed:
            continue
        final_text = (new_text.rstrip() + "\n") if new_text.strip() else ""
        try:
            if final_text:
                tomllib.loads(final_text)
        except Exception:
            continue
        toml_path.write_text(final_text, encoding="utf-8")
        cleaned.append(str(toml_path))

    return cleaned


def _remove_uninstall_registry_key(reg_key: str) -> list[str]:
    if os.name != "nt" or not reg_key:
        return []
    import winreg

    removed: list[str] = []
    wow64 = getattr(winreg, "KEY_WOW64_64KEY", 0)
    for hive, hive_name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        try:
            if hasattr(winreg, "DeleteKeyEx"):
                winreg.DeleteKeyEx(hive, reg_key, wow64, 0)
            else:
                winreg.DeleteKey(hive, reg_key)
            removed.append(f"{hive_name}\\{reg_key}")
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return removed


def _queue_reboot_delete(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.MoveFileExW(str(path), None, _MOVEFILE_DELAY_UNTIL_REBOOT)
    except Exception:
        pass


def _spawn_delayed_self_delete(install_dir: Path) -> bool:
    """Spawn a detached shell command outside install_dir to remove uninstall_fairybread.py and install_dir."""
    if os.name != "nt":
        return False
    # Queue locked files/dirs bottom-up for reboot deletion as fail-safe
    for child in sorted(install_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        _queue_reboot_delete(child)
    _queue_reboot_delete(install_dir)

    safe_dir = str(install_dir.resolve()).replace('"', '""')
    cmd = f'ping -n 3 127.0.0.1 >nul & rmdir /s /q "{safe_dir}"'
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", cmd],
            cwd=tempfile.gettempdir(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        return True
    except Exception:
        return False


def perform_uninstall(
    install_dir: Path,
    *,
    purge_user_data: bool = False,
    cleanup_mcp: bool = True,
    remove_registry: bool = True,
    stop_processes: bool = True,
    schedule_self_delete: bool = True,
    home_dir: Path | None = None,
    appdata_dir: Path | None = None,
    data_dir_override: Path | None = None,
) -> dict[str, Any]:
    """Perform clean Microsoft-compliant uninstall of Fairybread in install_dir."""
    target = Path(install_dir).resolve()
    manifest = load_install_manifest(target)
    errors: list[str] = []

    if _is_unsafe_delete_root(target):
        raise ValueError(f"Refusing to uninstall unsafe directory path: {target}")

    if stop_processes:
        stop_running_fairybread_in_dir(target)

    removed_shortcuts: list[str] = []
    for raw_lnk in manifest["shortcuts"]:
        lnk_p = Path(raw_lnk)
        if _is_forbidden_drive(lnk_p):
            continue
        if lnk_p.is_file():
            try:
                lnk_p.unlink()
                removed_shortcuts.append(str(lnk_p))
            except OSError as exc:
                errors.append(f"Shortcut {lnk_p}: {exc}")

    cleaned_mcp: list[str] = []
    if cleanup_mcp:
        try:
            cleaned_mcp = cleanup_mcp_entries_for_dir(
                target,
                home_dir=home_dir,
                appdata_dir=appdata_dir,
            )
        except Exception as exc:
            errors.append(f"MCP cleanup: {exc}")

    removed_reg: list[str] = []
    if remove_registry:
        removed_reg = _remove_uninstall_registry_key(manifest["reg_key"])

    purged_user_data = False
    eff_data = Path(data_dir_override).resolve() if data_dir_override is not None else Path(manifest["data_dir"]).resolve()
    if purge_user_data:
        if _is_forbidden_drive(eff_data) or _is_unsafe_delete_root(eff_data):
            errors.append(f"Refused to delete protected or unsafe user data path: {eff_data}")
        elif eff_data.exists() and eff_data.is_dir():
            shutil.rmtree(eff_data, ignore_errors=True)
            purged_user_data = not eff_data.exists()

    removed_files: list[str] = []
    self_file = Path(__file__).resolve()
    running_inside_target = (self_file.parent == target) and schedule_self_delete

    if target.is_dir():
        # Remove subdirectories first (including __pycache__), then files
        for item in sorted(target.iterdir(), key=lambda p: p.name):
            if _is_forbidden_drive(item):
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                removed_files.append(item.name)
            elif item.is_file():
                if running_inside_target and item.resolve() == self_file:
                    continue
                try:
                    item.unlink()
                    removed_files.append(item.name)
                except OSError as exc:
                    errors.append(f"Delete {item.name}: {exc}")

    scheduled_delete = False
    removed_dir = False
    if target.is_dir():
        if not any(target.iterdir()):
            try:
                os.chdir(tempfile.gettempdir())
                target.rmdir()
                removed_dir = True
            except OSError:
                pass
        if not removed_dir:
            if running_inside_target:
                scheduled_delete = _spawn_delayed_self_delete(target)
            elif not schedule_self_delete:
                shutil.rmtree(target, ignore_errors=True)
                removed_dir = not target.exists()
            else:
                scheduled_delete = _spawn_delayed_self_delete(target)
    else:
        removed_dir = True

    return {
        "install_dir": str(target),
        "version_stamped_name": manifest["version_stamped_name"],
        "data_dir": str(eff_data),
        "removed_files": removed_files,
        "removed_shortcuts": removed_shortcuts,
        "removed_registry_keys": removed_reg,
        "cleaned_mcp_configs": cleaned_mcp,
        "purged_user_data": purged_user_data,
        "removed_install_dir": removed_dir,
        "scheduled_self_delete": scheduled_delete,
        "errors": errors,
    }


def _win32_message_box(title: str, text: str, flags: int = 0) -> int:
    if os.name != "nt":
        return 1
    return int(ctypes.windll.user32.MessageBoxW(None, text, title, flags))


def _run_interactive_uninstall(install_dir: Path) -> int:
    manifest = load_install_manifest(install_dir)
    app_name = manifest["version_stamped_name"]
    data_dir = manifest["data_dir"]
    other_installs = find_other_fairybread_installs(install_dir)

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QDialog,
            QFrame,
            QHBoxLayout,
            QLabel,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
        )
    except Exception:
        # Native Win32 confirmation fallback if PySide6 is unavailable
        # MB_YESNO (0x4) | MB_ICONQUESTION (0x20) -> IDYES == 6
        ans = _win32_message_box(
            f"Uninstall {app_name}",
            f"Uninstall {app_name} from:\n{install_dir}\n\n"
            f"Your settings, API keys, and Memory Palaces in:\n{data_dir}\nwill be kept.",
            0x4 | 0x20,
        )
        if ans != 6:
            return 0
        res = perform_uninstall(install_dir, purge_user_data=False, cleanup_mcp=True)
        _win32_message_box(
            f"{app_name} Uninstalled",
            f"Removed {len(res['removed_files'])} program items and cleaned Windows shortcuts/registry.",
            0x40,
        )
        return 0 if not res["errors"] else 1

    app = QApplication.instance() or QApplication(sys.argv)
    dlg = QDialog()
    dlg.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
    dlg.setWindowFlag(Qt.WindowType.WindowTitleHint, True)
    dlg.setWindowFlag(Qt.WindowType.WindowSystemMenuHint, True)
    dlg.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
    dlg.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
    dlg.setWindowTitle(f"Uninstall {app_name}")
    dlg.resize(560, 360)
    dlg.setStyleSheet("background:#0d1117; color:#f0f6fc; font-family:'Segoe UI'; font-size:13px;")

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(12)

    hdr = QLabel(f"<h3 style='margin:0; color:#f0f6fc;'>Uninstall {app_name}</h3>")
    hdr.setTextFormat(Qt.TextFormat.RichText)
    lay.addWidget(hdr)

    info = QLabel(
        f"This will remove <b>{app_name}</b> program files from:<br>"
        f"<code>{install_dir}</code><br>"
        "along with its Desktop / Start Menu shortcuts and Windows Installed Apps entry."
    )
    info.setWordWrap(True)
    info.setTextFormat(Qt.TextFormat.RichText)
    info.setStyleSheet("color:#c9d1d9;")
    lay.addWidget(info)

    opts_card = QFrame(dlg)
    opts_card.setObjectName("uninstallOptsCard")
    opts_card.setStyleSheet("QFrame#uninstallOptsCard { background:#131720; border:1px solid #262c3a; border-radius:8px; }")
    oc_lay = QVBoxLayout(opts_card)
    oc_lay.setContentsMargins(12, 10, 12, 10)
    oc_lay.setSpacing(8)

    mcp_chk = QCheckBox("Remove External Agent Bridge (MCP) links pointing to this folder", opts_card)
    mcp_chk.setChecked(True)
    oc_lay.addWidget(mcp_chk)

    purge_chk = QCheckBox(
        f"Also delete all local user data (settings, encrypted API keys, chats & Memory Palaces in {data_dir})",
        opts_card,
    )
    purge_chk.setChecked(False)
    oc_lay.addWidget(purge_chk)

    if other_installs:
        names = ", ".join(o["name"] for o in other_installs[:3])
        warn = QLabel(
            f"⚠ Note: Other Fairybread versions are still installed ({names}) and share {data_dir}."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#eab308; font-size:12px;")
        oc_lay.addWidget(warn)

    lay.addWidget(opts_card)
    lay.addStretch(1)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    uninst_btn = QPushButton("Uninstall", dlg)
    uninst_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    uninst_btn.setStyleSheet("background:#da3633; color:#ffffff; border:none; border-radius:6px; padding:8px 20px; font-weight:700;")
    cancel_btn = QPushButton("Cancel", dlg)
    cancel_btn.setStyleSheet("background:#21262d; color:#f0f6fc; border:1px solid #30363d; border-radius:6px; padding:8px 18px;")
    cancel_btn.clicked.connect(dlg.reject)
    btn_row.addWidget(uninst_btn)
    btn_row.addWidget(cancel_btn)
    lay.addLayout(btn_row)

    exit_code = [0]

    def _do_uninstall():
        if purge_chk.isChecked():
            warn_extra = (
                f"\n\nWARNING: Other Fairybread versions ({', '.join(o['name'] for o in other_installs)}) still share this data folder!"
                if other_installs
                else ""
            )
            rep = QMessageBox.warning(
                dlg,
                "Confirm Deleting User Data",
                f"Permanently delete ALL settings, encrypted API keys, chats, and Memory Palaces in:\n{data_dir}?{warn_extra}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if rep != QMessageBox.StandardButton.Yes:
                return
        res = perform_uninstall(
            install_dir,
            purge_user_data=purge_chk.isChecked(),
            cleanup_mcp=mcp_chk.isChecked(),
        )
        exit_code[0] = 0 if not res["errors"] else 1
        QMessageBox.information(
            dlg,
            f"{app_name} Uninstalled",
            f"{app_name} has been removed cleanly.\n\n"
            + ("Local user data was also removed." if res["purged_user_data"] else f"Your local user data in {data_dir} was preserved."),
        )
        dlg.accept()

    uninst_btn.clicked.connect(_do_uninstall)
    dlg.exec()
    return exit_code[0]


def main(argv: list[str] | None = None, *, skip_elevation: bool = False) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])
    normalized_args = ["--quiet" if a.lower() in {"/s", "-s", "--silent"} else a for a in raw_args]

    parser = argparse.ArgumentParser(description="Uninstall Fairybread cleanly")
    parser.add_argument("--quiet", action="store_true", help="Run silently without GUI prompts")
    parser.add_argument("--purge-data", action="store_true", help="Also remove local user data/Memory Palace")
    parser.add_argument("--keep-mcp", action="store_true", help="Do not remove MCP bridge entries")
    parser.add_argument("--install-dir", type=str, default="", help="Installation directory override")
    ns = parser.parse_args(normalized_args)

    install_dir = Path(ns.install_dir).resolve() if ns.install_dir else Path(__file__).resolve().parent
    manifest = load_install_manifest(install_dir)

    if not skip_elevation:
        try:
            if ensure_elevated_if_needed(install_dir, manifest.get("reg_hive", "")):
                return 0
        except PermissionError as exc:
            if not ns.quiet:
                _win32_message_box("Administrator Privileges Required", str(exc), 0x10)
            return 1

    if ns.quiet:
        res = perform_uninstall(
            install_dir,
            purge_user_data=ns.purge_data,
            cleanup_mcp=(not ns.keep_mcp),
        )
        return 0 if not res["errors"] else 1
    return _run_interactive_uninstall(install_dir)


if __name__ == "__main__":
    sys.exit(main())
