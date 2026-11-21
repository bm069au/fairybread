"""Complete Atomic ZIP Backup & Restore Service for Fairybread ('All of It' — Settings, API Keys, Sessions, Memory Palace, Idle Palace, Themes & Images) with AES-256-GCM Password Lock."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
import zipfile

from credential_store import CredentialStore, dpapi_decrypt, dpapi_encrypt
from palace_config import CONFIG_PATH, get_palace_data_root


BACKUP_FORMAT_VERSION = 2
_PBKDF2_ITERATIONS = 600_000


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
    return get_palace_data_root(CONFIG_PATH)


def encrypt_vault_payload(payload_dict: dict[str, Any], password: str) -> bytes:
    """Encrypt a dictionary of sensitive settings & API keys with PBKDF2-HMAC-SHA256 + AES-256-GCM."""
    clean_pw = (password or "").strip()
    if not clean_pw:
        raise ValueError("A non-empty backup password is required to lock API keys.")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", clean_pw.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=32)
    plaintext = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, b"Fairybread.BackupVault.v2")
    envelope = {
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": _PBKDF2_ITERATIONS,
        "cipher": "AES-256-GCM",
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    return (json.dumps(envelope, indent=2) + "\n").encode("utf-8")


def decrypt_vault_payload(vault_bytes: bytes, password: str) -> dict[str, Any]:
    """Decrypt a password-locked AES-256-GCM backup vault, raising PermissionError on bad password."""
    clean_pw = (password or "").strip()
    if not clean_pw:
        raise PermissionError("This backup contains password-protected API keys. Please enter the backup password.")
    try:
        envelope = json.loads(vault_bytes.decode("utf-8"))
        salt = base64.b64decode(envelope["salt"])
        nonce = base64.b64decode(envelope["nonce"])
        ciphertext = base64.b64decode(envelope["ciphertext"])
        iters = int(envelope.get("iterations", _PBKDF2_ITERATIONS))
    except Exception as exc:
        raise ValueError(f"Damaged encrypted backup vault: {exc}") from exc

    key = hashlib.pbkdf2_hmac("sha256", clean_pw.encode("utf-8"), salt, iters, dklen=32)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, b"Fairybread.BackupVault.v2")
        data = json.loads(plaintext.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        raise PermissionError("Incorrect backup password — could not unlock API keys vault.") from exc


def inspect_backup_zip(src_zip_path: Path) -> dict[str, Any]:
    """Inspect a backup ZIP's manifest without extracting or modifying live files."""
    src_zip = Path(src_zip_path)
    if not src_zip.exists():
        raise FileNotFoundError(f"Backup archive not found: {src_zip}")
    with zipfile.ZipFile(src_zip, "r") as zf:
        if "manifest.json" not in zf.namelist():
            raise ValueError("Invalid backup archive: missing manifest.json.")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        return manifest if isinstance(manifest, dict) else {}


def _extract_decrypted_api_keys(cred_file: Path) -> dict[str, str]:
    """Read credentials.json (or live CredentialStore) and decrypt all DPAPI keys in memory."""
    decrypted_keys: dict[str, str] = {}
    store = CredentialStore(path=cred_file if cred_file.exists() else None)
    target = cred_file if cred_file.exists() else store._resolve_readable_path()
    if not target.exists():
        return decrypted_keys
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        providers = raw.get("providers", {}) if isinstance(raw, dict) else {}
        for pname, pentry in providers.items():
            if isinstance(pentry, dict) and pentry.get("api_key"):
                val = str(pentry["api_key"]).strip()
                plain = dpapi_decrypt(val) if val.startswith("dpapi:") else val
                if plain:
                    decrypted_keys[str(pname)] = plain
    except Exception:
        pass
    return decrypted_keys


def create_full_backup_zip(
    dest_zip_path: Path,
    *,
    config_path: Path = CONFIG_PATH,
    appdata_root: Path | None = None,
    include_memory: bool = True,
    include_settings: bool = True,
    include_generated_images: bool = True,
    include_credentials: bool = True,
    backup_password: str = "",
) -> dict[str, Any]:
    """Create an atomic, SHA-256 checksummed ZIP archive of Fairybread Palace Memory, Conversations,
    Uploaded Files, Generated Images, and (optionally password-locked AES-256-GCM) Settings & API Keys.
    """
    root = get_palace_appdata_root(appdata_root)
    dest_zip = Path(dest_zip_path)
    dest_zip.parent.mkdir(parents=True, exist_ok=True)

    manifest_files: dict[str, dict[str, Any]] = {}
    tmp_zip = dest_zip.with_suffix(".zip.tmp")
    clean_pw = (backup_password or "").strip()
    is_password_locked = False

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        stage_dir = Path(tmp_dir_str)

        def _stage_bytes(data: bytes, arc_rel: str) -> None:
            sha = hashlib.sha256(data).hexdigest()
            target = stage_dir / arc_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest_files[arc_rel] = {"size": len(data), "sha256": sha}

        def _stage_file(src: Path, arc_rel: str) -> None:
            if not src.exists() or not src.is_file():
                return
            _stage_bytes(src.read_bytes(), arc_rel)

        # 1. Settings & API Keys (Password-Locked AES-256-GCM Vault when password is given)
        if include_settings:
            cfg_dict: dict[str, Any] = {}
            if Path(config_path).exists():
                try:
                    cfg_dict = json.loads(Path(config_path).read_text(encoding="utf-8"))
                except Exception:
                    cfg_dict = {}
                _stage_file(Path(config_path), "config/palace_config.json")

            if include_credentials:
                cred_file = root / "credentials.json"
                if clean_pw:
                    api_keys = _extract_decrypted_api_keys(cred_file)
                    email_plain_pw = ""
                    email_cfg = cfg_dict.get("email_settings", {}) if isinstance(cfg_dict, dict) else {}
                    if isinstance(email_cfg, dict) and email_cfg.get("password_dpapi"):
                        email_plain_pw = dpapi_decrypt(str(email_cfg["password_dpapi"]))
                    vault_payload = {
                        "api_keys": api_keys,
                        "email_password": email_plain_pw,
                        "config_snapshot": cfg_dict,
                    }
                    enc_bytes = encrypt_vault_payload(vault_payload, clean_pw)
                    _stage_bytes(enc_bytes, "vault/credentials.vault.enc")
                    is_password_locked = True
                else:
                    _stage_file(cred_file, "appdata/credentials.json")

            # Custom themes
            themes_dir = root / "themes"
            if themes_dir.is_dir():
                for fp in sorted(themes_dir.rglob("*")):
                    if fp.is_file():
                        rel = fp.relative_to(root).as_posix()
                        _stage_file(fp, f"appdata/{rel}")

        # 2. Palace Memory, Conversations, Uploaded Files, Idle Palace & Generated Images
        if include_memory:
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

            mem_top_files = [
                "conversations.json",
                "session_context.jsonl",
                "memory_proposals.jsonl",
                "memory_promotions_audit.jsonl",
                "email_uid_cache.json",
            ]
            for fname in mem_top_files:
                _stage_file(root / fname, f"appdata/{fname}")

            subdirs = ["sessions", "uploaded_files", "idle_notebooks", "idle_palace", "mailbox"]
            if include_generated_images:
                subdirs.append("generated_images")
            for sdir in subdirs:
                dpath = root / sdir
                if dpath.is_dir():
                    for fp in sorted(dpath.rglob("*")):
                        if fp.is_file():
                            rel = fp.relative_to(root).as_posix()
                            _stage_file(fp, f"appdata/{rel}")

            sandbox_root = Path(r"C:\Palace_Idle_Sandbox")
            if sandbox_root.is_dir():
                for sb_file in ("ai_idle_memory.json", "agent_mailbox.json"):
                    _stage_file(sandbox_root / sb_file, f"sandbox/{sb_file}")
                sb_files_dir = sandbox_root / "files"
                if sb_files_dir.is_dir():
                    for fp in sorted(sb_files_dir.rglob("*")):
                        if fp.is_file():
                            rel = fp.relative_to(sandbox_root).as_posix()
                            _stage_file(fp, f"sandbox/{rel}")

        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at": datetime.now().astimezone().isoformat(),
            "machine_fingerprint": _get_machine_fingerprint(),
            "password_protected": is_password_locked,
            "included_memory": bool(include_memory),
            "included_settings": bool(include_settings),
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


def _safe_resolve_under(base_dir: Path, rel_path: str, *, label: str) -> Path:
    """Resolve `rel_path` strictly inside `base_dir` to block ZipSlip / path traversal."""
    clean_rel = (rel_path or "").replace("\\", "/").lstrip("/")
    if not clean_rel or rel_path.startswith(("/", "\\")) or ":" in rel_path.split("/")[0]:
        raise ValueError(f"Unsafe path in {label}: {rel_path}")
    base_resolved = base_dir.resolve()
    candidate = (base_resolved / clean_rel).resolve()
    if not candidate.is_relative_to(base_resolved):
        raise ValueError(f"Unsafe path traversal in {label}: {rel_path}")
    return candidate


def restore_full_backup_zip(
    src_zip_path: Path,
    *,
    config_path: Path = CONFIG_PATH,
    appdata_root: Path | None = None,
    backup_password: str = "",
    restore_memory: bool = True,
    restore_settings: bool = True,
) -> dict[str, Any]:
    """Verify SHA-256 manifest checksums, unlock AES-256-GCM password-protected API keys (if present)
    and re-seal them into local Windows DPAPI, and atomically restore selected components.
    """
    src_zip = Path(src_zip_path)
    if not src_zip.exists():
        raise FileNotFoundError(f"Backup archive not found: {src_zip}")

    root = get_palace_appdata_root(appdata_root)
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        extract_dir = Path(tmp_dir_str)
        with zipfile.ZipFile(src_zip, "r") as zf:
            for member in zf.infolist():
                if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError(f"Unsafe symlink in backup archive: {member.filename}")
                if not member.filename:
                    continue
                _safe_resolve_under(extract_dir, member.filename, label="backup archive")
            zf.extractall(extract_dir)

        manifest_path = extract_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("Invalid backup archive: missing manifest.json.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files_meta: dict[str, dict[str, Any]] = manifest.get("files", {})

        # 1. Verify SHA-256 integrity of every file BEFORE modifying live disk state
        for arc_rel, meta in files_meta.items():
            fp = _safe_resolve_under(extract_dir, str(arc_rel), label="backup manifest")
            if not fp.exists():
                raise ValueError(f"Corrupt backup archive: missing file {arc_rel}")
            actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
            if actual_sha != meta.get("sha256"):
                raise ValueError(f"Checksum mismatch in backup archive for {arc_rel}")

        # 2. If restoring settings and a password-locked vault is present, verify password FIRST
        vault_rel = "vault/credentials.vault.enc"
        unlocked_vault: dict[str, Any] | None = None
        if restore_settings and vault_rel in files_meta:
            vault_fp = _safe_resolve_under(extract_dir, vault_rel, label="backup vault")
            unlocked_vault = decrypt_vault_payload(vault_fp.read_bytes(), backup_password)

        same_machine = manifest.get("machine_fingerprint") == _get_machine_fingerprint()
        restored_count = 0
        restored_keys_count = 0
        skipped_credentials = False

        # 3. Restore files atomically
        for arc_rel in files_meta:
            if arc_rel == vault_rel:
                continue
            src_fp = _safe_resolve_under(extract_dir, str(arc_rel), label="backup manifest")
            is_setting_item = (
                arc_rel == "config/palace_config.json"
                or arc_rel == "appdata/credentials.json"
                or arc_rel.startswith("appdata/themes/")
            )
            if is_setting_item and not restore_settings:
                continue
            if not is_setting_item and not restore_memory:
                continue

            if arc_rel == "config/palace_config.json":
                target = Path(config_path)
            elif arc_rel == "appdata/credentials.json" and not same_machine:
                skipped_credentials = True
                continue
            elif arc_rel.startswith("appdata/"):
                sub_rel = arc_rel[len("appdata/") :]
                target = _safe_resolve_under(root, sub_rel, label="appdata restore target")
            elif arc_rel.startswith("sandbox/"):
                sub_rel = arc_rel[len("sandbox/") :]
                target = _safe_resolve_under(Path(r"C:\Palace_Idle_Sandbox"), sub_rel, label="sandbox restore target")
            else:
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_target = target.with_suffix(target.suffix + ".restore_tmp")
            shutil.copy2(src_fp, tmp_target)
            os.replace(tmp_target, target)
            restored_count += 1

        # 4. Re-encrypt unlocked API keys into local machine's Windows DPAPI
        if unlocked_vault is not None:
            api_keys = unlocked_vault.get("api_keys", {})
            if isinstance(api_keys, dict) and api_keys:
                cred_store = CredentialStore(path=root / "credentials.json")
                for pname, plain_key in api_keys.items():
                    if plain_key:
                        cred_store.set_api_key(str(pname), str(plain_key))
                        restored_keys_count += 1
                restored_count += 1
            email_pw = str(unlocked_vault.get("email_password") or "").strip()
            if email_pw and Path(config_path).exists():
                try:
                    cfg_data = json.loads(Path(config_path).read_text(encoding="utf-8"))
                    if isinstance(cfg_data, dict) and isinstance(cfg_data.get("email_settings"), dict):
                        cfg_data["email_settings"]["password_dpapi"] = dpapi_encrypt(email_pw)
                        Path(config_path).write_text(json.dumps(cfg_data, indent=2) + "\n", encoding="utf-8")
                except Exception:
                    pass

        return {
            "restored_files": restored_count,
            "restored_keys_count": restored_keys_count,
            "password_unlocked": unlocked_vault is not None,
            "same_machine": same_machine,
            "skipped_credentials": skipped_credentials,
            "created_at": manifest.get("created_at", ""),
        }
