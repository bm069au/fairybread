"""Complete Atomic ZIP Backup & Restore Service for Fairybread ('All of It' — Settings, Sessions, Memory Palace, Idle Palace, Themes & Images)."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
import zipfile

from palace_config import CONFIG_PATH


BACKUP_FORMAT_VERSION = 1


def _get_machine_fingerprint() -> str:
    """Return a non-sensitive hash of the current machine/user so cross-machine restores know whether DPAPI keys are valid."""
    raw_id = f"{os.environ.get('COMPUTERNAME', '')}:{os.environ.get('USERNAME', '')}"
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                mguid, _ = winreg.QueryValueEx(key, "MachineGuid")
                raw_id = f"{mguid}:{os.environ.get('USERNAME', '')}"
        except Exception:
            pass
    return hashlib.sha256(raw_id.encode("utf-8", errors="replace")).hexdigest()[:24]


def get_palace_appdata_root(custom_root: Path | None = None) -> Path:
    if custom_root is not None:
        return Path(custom_root)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace"


def create_full_backup_zip(
    dest_zip_path: Path,
    *,
    config_path: Path = CONFIG_PATH,
    appdata_root: Path | None = None,
    include_generated_images: bool = True,
    include_credentials: bool = True,
) -> dict[str, Any]:
    """Create an atomic, SHA-256 checksummed ZIP archive of all Fairybread settings, conversations,
    SQLite FTS5 durable memory (via online .backup API), memory proposals, Shared Idle Palace,
    Agent Mail, custom themes, and optionally generated images and DPAPI credentials.
    """
    root = get_palace_appdata_root(appdata_root)
    dest_zip = Path(dest_zip_path)
    dest_zip.parent.mkdir(parents=True, exist_ok=True)

    manifest_files: dict[str, dict[str, Any]] = {}
    tmp_zip = dest_zip.with_suffix(".zip.tmp")

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        stage_dir = Path(tmp_dir_str)

        def _stage_file(src: Path, arc_rel: str) -> None:
            if not src.exists() or not src.is_file():
                return
            data = src.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            target = stage_dir / arc_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest_files[arc_rel] = {"size": len(data), "sha256": sha}

        # 1. Main config file (palace_config.json)
        if Path(config_path).exists():
            _stage_file(Path(config_path), "config/palace_config.json")

        # 2. SQLite FTS5 durable memory database (using online WAL-safe .backup() API)
        mem_db = root / "memory.db"
        if mem_db.exists():
            try:
                from memory_service import SQLiteMemoryIndex
                staged_db = stage_dir / "appdata/memory.db"
                SQLiteMemoryIndex(mem_db).backup_to_file(staged_db)
                if staged_db.exists():
                    data = staged_db.read_bytes()
                    manifest_files["appdata/memory.db"] = {
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
            except Exception:
                _stage_file(mem_db, "appdata/memory.db")

        # 3. All JSON / JSONL state files in %LOCALAPPDATA%\Palace
        top_files = [
            "conversations.json",
            "session_context.jsonl",
            "memory_proposals.jsonl",
            "memory_promotions_audit.jsonl",
            "email_uid_cache.json",
        ]
        if include_credentials:
            top_files.append("credentials.json")
        for fname in top_files:
            _stage_file(root / fname, f"appdata/{fname}")

        # 4. Subdirectories: sessions/, idle_notebooks/, idle_palace/, mailbox/, themes/, generated_images/
        subdirs = ["sessions", "idle_notebooks", "idle_palace", "mailbox", "themes"]
        if include_generated_images:
            subdirs.append("generated_images")
        for sdir in subdirs:
            dpath = root / sdir
            if dpath.is_dir():
                for fp in sorted(dpath.rglob("*")):
                    if fp.is_file():
                        rel = fp.relative_to(root).as_posix()
                        _stage_file(fp, f"appdata/{rel}")

        # 5. Also include C:\Palace_Idle_Sandbox\ai_idle_memory.json & agent_mailbox.json if present
        sandbox_root = Path(r"C:\Palace_Idle_Sandbox")
        if sandbox_root.is_dir():
            for sb_file in ("ai_idle_memory.json", "agent_mailbox.json"):
                _stage_file(sandbox_root / sb_file, f"sandbox/{sb_file}")

        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at": datetime.now().astimezone().isoformat(),
            "machine_fingerprint": _get_machine_fingerprint(),
            "file_count": len(manifest_files),
            "files": manifest_files,
        }
        manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        (stage_dir / "manifest.json").write_bytes(manifest_bytes)

        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fp in sorted(stage_dir.rglob("*")):
                if fp.is_file():
                    zf.write(fp, fp.relative_to(stage_dir).as_posix())

    os.replace(tmp_zip, dest_zip)
    return manifest


def restore_full_backup_zip(
    src_zip_path: Path,
    *,
    config_path: Path = CONFIG_PATH,
    appdata_root: Path | None = None,
) -> dict[str, Any]:
    """Verify SHA-256 manifest checksums and atomically restore all Settings, Conversations,
    Memory Palace, Shared Idle Palace, Agent Mail, and Themes from a Fairybread backup ZIP.
    """
    src_zip = Path(src_zip_path)
    if not src_zip.exists():
        raise FileNotFoundError(f"Backup archive not found: {src_zip}")

    root = get_palace_appdata_root(appdata_root)
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        extract_dir = Path(tmp_dir_str)
        with zipfile.ZipFile(src_zip, "r") as zf:
            zf.extractall(extract_dir)

        manifest_path = extract_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("Invalid backup archive: missing manifest.json.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files_meta: dict[str, dict[str, Any]] = manifest.get("files", {})

        # 1. Verify SHA-256 integrity of every file BEFORE modifying live disk state
        for arc_rel, meta in files_meta.items():
            fp = extract_dir / arc_rel
            if not fp.exists():
                raise ValueError(f"Corrupt backup archive: missing file {arc_rel}")
            actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
            if actual_sha != meta.get("sha256"):
                raise ValueError(f"Checksum mismatch in backup archive for {arc_rel}")

        same_machine = manifest.get("machine_fingerprint") == _get_machine_fingerprint()
        restored_count = 0
        skipped_credentials = False

        # 2. Restore files atomically
        for arc_rel in files_meta:
            src_fp = extract_dir / arc_rel
            if arc_rel == "config/palace_config.json":
                target = Path(config_path)
            elif arc_rel == "appdata/credentials.json" and not same_machine:
                skipped_credentials = True
                continue
            elif arc_rel.startswith("appdata/"):
                sub_rel = arc_rel[len("appdata/") :]
                target = root / sub_rel
            elif arc_rel.startswith("sandbox/"):
                sub_rel = arc_rel[len("sandbox/") :]
                target = Path(r"C:\Palace_Idle_Sandbox") / sub_rel
            else:
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_target = target.with_suffix(target.suffix + ".restore_tmp")
            shutil.copy2(src_fp, tmp_target)
            os.replace(tmp_target, target)
            restored_count += 1

        return {
            "restored_files": restored_count,
            "same_machine": same_machine,
            "skipped_credentials": skipped_credentials,
            "created_at": manifest.get("created_at", ""),
        }
