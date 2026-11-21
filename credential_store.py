import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading
from typing import Optional


VAULT_CREDENTIALS_PATH = Path(r"E:\Palace_Vault\credentials.json")
_DPAPI_PREFIX = "dpapi:"
_DPAPI_ENTROPY = b"Fairybread.Palace.CredentialVault.v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01

_IDLE_VAULT_LOCKED = False
_KNOWN_SECRET_STRINGS: set[str] = set()


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _make_blob(raw: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    return _DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))), buf


def dpapi_encrypt(plaintext: str) -> str:
    """Encrypt string using Windows DPAPI (CryptProtectData) with CRYPTPROTECT_UI_FORBIDDEN (silent, per-user)."""
    clean = (plaintext or "").strip()
    if not clean:
        return ""
    if clean.startswith(_DPAPI_PREFIX):
        return clean
    if os.name != "nt":
        return clean

    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob, _in_buf = _make_blob(clean.encode("utf-8"))
        ent_blob, _ent_buf = _make_blob(_DPAPI_ENTROPY)
        out_blob = _DATA_BLOB()

        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            ctypes.byref(ent_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok or not out_blob.pbData:
            raise RuntimeError("Windows DPAPI CryptProtectData failed; refusing to store plaintext API key.")
        try:
            encrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
        return _DPAPI_PREFIX + base64.b64encode(encrypted_bytes).decode("ascii")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Windows DPAPI encryption failed; refusing to store plaintext API key: {exc}") from exc


def dpapi_decrypt(stored: str) -> str:
    """Decrypt a `dpapi:<base64>` string using Windows DPAPI (CryptUnprotectData)."""
    clean = (stored or "").strip()
    if not clean:
        return ""
    if not clean.startswith(_DPAPI_PREFIX):
        return clean
    if os.name != "nt":
        return clean[len(_DPAPI_PREFIX):]

    try:
        raw_cipher = base64.b64decode(clean[len(_DPAPI_PREFIX):])
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob, _in_buf = _make_blob(raw_cipher)
        ent_blob, _ent_buf = _make_blob(_DPAPI_ENTROPY)
        out_blob = _DATA_BLOB()

        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            ctypes.byref(ent_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok or not out_blob.pbData:
            return ""
        try:
            decrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
        return decrypted_bytes.decode("utf-8")
    except Exception:
        return ""


def set_idle_vault_lock(locked: bool) -> None:
    """When True, background worker threads are blocked from reading raw keys directly via CredentialStore."""
    global _IDLE_VAULT_LOCKED
    _IDLE_VAULT_LOCKED = bool(locked)


def redact_secrets(text: str) -> str:
    """Scrub any known API key substrings before text is written to logs, Idle Palace, or UI."""
    if not text or not _KNOWN_SECRET_STRINGS:
        return text
    out = text
    for secret in list(_KNOWN_SECRET_STRINGS):
        if len(secret) >= 8 and secret in out:
            out = out.replace(secret, "[REDACTED_API_KEY]")
    return out


def _default_local_credentials_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA environment variable is not available.")
    return Path(local_app_data) / "Palace" / "credentials.json"


class CredentialStore:
    def __init__(self, path: Optional[Path] = None):
        self._explicit_path = path is not None
        if path is None:
            local_path = _default_local_credentials_path()
            try:
                if local_path.exists():
                    path = local_path
                elif VAULT_CREDENTIALS_PATH.exists():
                    path = VAULT_CREDENTIALS_PATH
                else:
                    path = local_path
            except OSError:
                path = local_path

        self.path = path

    def _resolve_readable_path(self) -> Path:
        if self._explicit_path:
            return self.path
        try:
            if self.path.exists():
                return self.path
        except OSError:
            pass
        local_path = _default_local_credentials_path()
        return local_path

    def get_api_key(self, provider_name: str) -> Optional[str]:
        if _IDLE_VAULT_LOCKED and threading.current_thread() is not threading.main_thread():
            raise PermissionError("CredentialStore access is locked on background threads during Idle Mode.")

        target_path = self._resolve_readable_path()
        try:
            if not target_path.exists():
                return None
        except OSError:
            return None

        try:
            data = json.loads(
                target_path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Unable to read Palace credentials: {exc}"
            ) from exc

        providers = data.get("providers", {})
        provider = providers.get(provider_name, {})
        raw_val = provider.get("api_key")
        if not raw_val:
            return None

        raw_str = str(raw_val).strip()
        # Transparently migrate legacy plaintext keys on disk into DPAPI ciphertext
        if raw_str and not raw_str.startswith(_DPAPI_PREFIX) and os.name == "nt":
            try:
                encrypted = dpapi_encrypt(raw_str)
            except RuntimeError:
                encrypted = ""
            if encrypted.startswith(_DPAPI_PREFIX):
                provider["api_key"] = encrypted
                try:
                    payload = json.dumps(data, indent=2) + "\n"
                    target_path.write_text(payload, encoding="utf-8")
                    if not self._explicit_path and VAULT_CREDENTIALS_PATH.parent.exists():
                        VAULT_CREDENTIALS_PATH.write_text(payload, encoding="utf-8")
                except OSError:
                    pass
            plaintext = raw_str
        else:
            plaintext = dpapi_decrypt(raw_str)

        if not plaintext:
            return None
        if len(plaintext) >= 8:
            _KNOWN_SECRET_STRINGS.add(plaintext)
        return plaintext

    def has_api_key(self, provider_name: str) -> bool:
        try:
            return bool(self.get_api_key(provider_name))
        except PermissionError:
            return False

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        normalized_name = provider_name.strip().lower()
        if not normalized_name:
            raise ValueError("Provider name cannot be empty.")

        clean_key = api_key.strip()
        if len(clean_key) >= 8:
            _KNOWN_SECRET_STRINGS.add(clean_key)

        target_path = self._resolve_readable_path()
        data: dict = {"providers": {}}
        try:
            if target_path.exists():
                loaded = json.loads(
                    target_path.read_text(encoding="utf-8")
                )
                if isinstance(loaded, dict):
                    data = loaded
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Unable to read Palace credentials: {exc}"
            ) from exc

        providers = data.setdefault("providers", {})
        # Also encrypt any remaining legacy plaintext keys in the file at save time
        for _pname, pentry in providers.items():
            if isinstance(pentry, dict) and isinstance(pentry.get("api_key"), str):
                existing = pentry["api_key"].strip()
                if existing and not existing.startswith(_DPAPI_PREFIX):
                    pentry["api_key"] = dpapi_encrypt(existing)

        entry = providers.setdefault(normalized_name, {})
        entry["api_key"] = dpapi_encrypt(clean_key) if clean_key else ""

        payload = json.dumps(data, indent=2) + "\n"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(payload, encoding="utf-8")

        if not self._explicit_path:
            try:
                if VAULT_CREDENTIALS_PATH.parent.exists():
                    VAULT_CREDENTIALS_PATH.write_text(payload, encoding="utf-8")
            except OSError:
                pass
