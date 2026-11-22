"""Free Cryptographic Integrity Signing & Verification Service (SHA-256 + Ed25519) for Fairybread."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import sys
from typing import Any

from palace_config import FAIRYBREAD_VERSION, get_app_install_dir, is_frozen_app

# Embedded official release Ed25519 public key (raw 32 bytes base64); updated by build_release.py from local signing keypair
FAIRYBREAD_EMBEDDED_PUBLIC_KEY_B64 = ""


def get_local_signing_key_dir() -> Path:
    """Private Ed25519 signing keys are stored STRICTLY outside the git repository under %LOCALAPPDATA%."""
    d = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace_Signing"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def _load_public_key_b64(app_dir: Path | None = None, explicit_public_b64: str = "") -> str:
    if explicit_public_b64 and explicit_public_b64.strip():
        return explicit_public_b64.strip()
    if FAIRYBREAD_EMBEDDED_PUBLIC_KEY_B64.strip():
        return FAIRYBREAD_EMBEDDED_PUBLIC_KEY_B64.strip()
    if app_dir is not None:
        pk_file = Path(app_dir) / "integrity_public_key.txt"
        if pk_file.is_file():
            txt = pk_file.read_text(encoding="utf-8", errors="replace").strip()
            if txt:
                return txt
    local_pub = get_local_signing_key_dir() / "fairybread_ed25519_public.b64"
    if local_pub.is_file():
        return local_pub.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def get_or_create_signing_keypair(key_dir: Path | None = None) -> tuple[bytes, str]:
    """Return (private_pkcs8_pem_bytes, raw_public_key_base64), generating an Ed25519 pair once if absent."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    eff_dir = Path(key_dir) if key_dir is not None else get_local_signing_key_dir()
    eff_dir.mkdir(parents=True, exist_ok=True)
    priv_fp = eff_dir / "fairybread_ed25519_private.pem"
    pub_fp = eff_dir / "fairybread_ed25519_public.b64"

    if priv_fp.is_file():
        priv_pem = priv_fp.read_bytes()
        priv_obj = serialization.load_pem_private_key(priv_pem, password=None)
    else:
        priv_obj = Ed25519PrivateKey.generate()
        priv_pem = priv_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        priv_fp.write_bytes(priv_pem)

    raw_pub = priv_obj.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(raw_pub).decode("ascii")
    pub_fp.write_text(pub_b64 + "\n", encoding="utf-8")
    return priv_pem, pub_b64


def sign_bytes(data: bytes, private_pem: bytes) -> str:
    from cryptography.hazmat.primitives import serialization

    priv_obj = serialization.load_pem_private_key(private_pem, password=None)
    sig = priv_obj.sign(data)
    return base64.b64encode(sig).decode("ascii")


def verify_bytes(data: bytes, sig_b64: str, public_b64: str) -> bool:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        raw_pub = base64.b64decode(public_b64.strip())
        sig = base64.b64decode(sig_b64.strip())
        pub_obj = Ed25519PublicKey.from_public_bytes(raw_pub)
        pub_obj.verify(sig, data)
        return True
    except Exception:
        return False


def _canonical_manifest_bytes(payload: dict[str, Any]) -> bytes:
    clean = {k: v for k, v in payload.items() if k != "ed25519_signature"}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def build_integrity_manifest(
    app_dir: Path,
    version: str = FAIRYBREAD_VERSION,
    private_pem: bytes | None = None,
    public_b64: str = "",
) -> dict[str, Any]:
    """Hash all installed/staged files in app_dir (excluding runtime logs/manifests) and sign with Ed25519."""
    eff_dir = Path(app_dir).resolve()
    if private_pem is None:
        private_pem, derived_pub = get_or_create_signing_keypair()
        if not public_b64:
            public_b64 = derived_pub

    file_hashes: dict[str, str] = {}
    skip_names = {"integrity_manifest.json", "integrity_public_key.txt"}
    for fp in sorted(eff_dir.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(eff_dir).as_posix()
        if rel in skip_names or rel.startswith("__pycache__/") or rel.endswith(".pyc"):
            continue
        # Note: optional source/ may be toggled independently by Inno Setup components -> track separately
        if rel.startswith("source/"):
            continue
        file_hashes[rel] = sha256_file(fp)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "product": "Fairybread",
        "version": version,
        "created_at": datetime.now().astimezone().isoformat(),
        "public_key_b64": public_b64,
        "file_count": len(file_hashes),
        "files": file_hashes,
    }
    manifest["ed25519_signature"] = sign_bytes(_canonical_manifest_bytes(manifest), private_pem)
    (eff_dir / "integrity_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if public_b64:
        (eff_dir / "integrity_public_key.txt").write_text(public_b64 + "\n", encoding="utf-8")
    return manifest


def write_signed_sha256_sums(
    dist_dir: Path,
    artifact_paths: list[Path],
    private_pem: bytes | None = None,
    public_b64: str = "",
) -> tuple[Path, Path]:
    """Write dist/SHA256SUMS.txt + detached Ed25519 signature dist/SHA256SUMS.txt.sig."""
    eff_dist = Path(dist_dir).resolve()
    eff_dist.mkdir(parents=True, exist_ok=True)
    if private_pem is None:
        private_pem, derived_pub = get_or_create_signing_keypair()
        if not public_b64:
            public_b64 = derived_pub

    lines: list[str] = [
        f"# Fairybread Release Checksums (v{FAIRYBREAD_VERSION})",
        f"# Ed25519 Public Key (Base64): {public_b64}",
    ]
    for ap in artifact_paths:
        p = Path(ap)
        if p.is_file():
            lines.append(f"{sha256_file(p)} *{p.name}")
    sums_text = "\n".join(lines) + "\n"
    sums_bytes = sums_text.encode("utf-8")
    sig_b64 = sign_bytes(sums_bytes, private_pem)

    sums_fp = eff_dist / "SHA256SUMS.txt"
    sig_fp = eff_dist / "SHA256SUMS.txt.sig"
    sums_fp.write_bytes(sums_bytes)
    sig_fp.write_text(sig_b64 + "\n", encoding="utf-8")
    return sums_fp, sig_fp


def write_client_verify_html(
    dest_html: Path,
    artifact_paths: list[Path],
    *,
    version: str = FAIRYBREAD_VERSION,
    public_b64: str = "",
) -> Path:
    """Generate a self-contained static Web Crypto SHA-256 drag-and-drop verifier for fairybread.me/verify.html."""
    entries: list[dict[str, Any]] = []
    for ap in artifact_paths:
        p = Path(ap)
        if p.is_file():
            entries.append({
                "name": p.name,
                "sha256": sha256_file(p),
                "size": p.stat().st_size,
            })
    catalog_json = json.dumps(entries, indent=2)
    pub_escaped = html.escape(public_b64 or "not-published")
    ver_escaped = html.escape(version)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verify Official Fairybread Download (SHA-256)</title>
<style>
  body {{ font-family: "Segoe UI", system-ui, sans-serif; background:#0d1117; color:#f0f6fc; max-width:780px; margin:40px auto; padding:0 20px; }}
  h1 {{ font-size:24px; margin-bottom:6px; }}
  .muted {{ color:#8b949e; font-size:14px; }}
  .drop {{ border:2px dashed #30363d; border-radius:12px; padding:36px 20px; text-align:center; background:#161b22; margin:24px 0; cursor:pointer; }}
  .drop.drag {{ border-color:#58a6ff; background:#132238; }}
  .ok {{ background:#0f291e; border:1px solid #2ea043; color:#7ee787; padding:14px; border-radius:8px; margin-top:16px; }}
  .bad {{ background:#2c1517; border:1px solid #f85149; color:#ff7b72; padding:14px; border-radius:8px; margin-top:16px; }}
  code, pre {{ background:#161b22; border:1px solid #262c3a; border-radius:6px; padding:2px 6px; font-family:Consolas, monospace; font-size:12.5px; word-break:break-all; }}
  table {{ width:100%; border-collapse:collapse; margin-top:18px; font-size:13px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #21262d; }}
</style>
</head>
<body>
  <h1>🛡 Verify Your Fairybread Download (v{ver_escaped})</h1>
  <p class="muted">100% local verification in your browser using Web Crypto SHA-256 — nothing is uploaded anywhere.</p>
  <div id="dropZone" class="drop">
    <strong>Drop your downloaded <code>.exe</code> or <code>.msix</code> here</strong><br><br>
    <input type="file" id="fileInput">
  </div>
  <div id="result"></div>
  <h3>Official v{ver_escaped} Release SHA-256 Hashes</h3>
  <p class="muted">Ed25519 Public Key: <code>{pub_escaped}</code></p>
  <table>
    <thead><tr><th>File</th><th>Official SHA-256</th></tr></thead>
    <tbody id="hashTable"></tbody>
  </table>
<script>
const OFFICIAL = {catalog_json};
const tbody = document.getElementById('hashTable');
for (const item of OFFICIAL) {{
  const tr = document.createElement('tr');
  tr.innerHTML = `<td><code>${{item.name}}</code></td><td><code>${{item.sha256}}</code></td>`;
  tbody.appendChild(tr);
}}
async function checkFile(file) {{
  const res = document.getElementById('result');
  res.innerHTML = '<p class="muted">Hashing file locally…</p>';
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', buf);
  const hex = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('').toLowerCase();
  const match = OFFICIAL.find(o => o.sha256 === hex);
  if (match) {{
    res.innerHTML = `<div class="ok"><strong>✓ VERIFIED OFFICIAL FAIRYBREAD RELEASE</strong><br>Matches <code>${{match.name}}</code><br>SHA-256: <code>${{hex}}</code></div>`;
  }} else {{
    res.innerHTML = `<div class="bad"><strong>⚠ UNRECOGNIZED OR MODIFIED FILE</strong><br>Your file's SHA-256 did not match any official v{ver_escaped} build.<br>Computed SHA-256: <code>${{hex}}</code></div>`;
  }}
}}
const dz = document.getElementById('dropZone');
const fi = document.getElementById('fileInput');
fi.addEventListener('change', e => {{ if (e.target.files[0]) checkFile(e.target.files[0]); }});
dz.addEventListener('dragover', e => {{ e.preventDefault(); dz.classList.add('drag'); }});
dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
dz.addEventListener('drop', e => {{ e.preventDefault(); dz.classList.remove('drag'); if (e.dataTransfer.files[0]) checkFile(e.dataTransfer.files[0]); }});
</script>
</body>
</html>
"""
    Path(dest_html).write_text(html_doc, encoding="utf-8")
    return Path(dest_html)


def verify_installation_integrity(
    app_dir: Path | None = None,
    public_b64: str = "",
) -> dict[str, Any]:
    """Verify signed integrity_manifest.json (if present) and report live executable SHA-256."""
    eff_dir = Path(app_dir).resolve() if app_dir is not None else get_app_install_dir().resolve()
    running_target = (eff_dir / "Fairybread.exe") if is_frozen_app() else (eff_dir / "palace_gui.py")
    if not running_target.is_file():
        running_target = Path(sys.executable).resolve() if hasattr(os, "path") else running_target
    running_sha = sha256_file(running_target) if running_target.is_file() else ""

    manifest_fp = eff_dir / "integrity_manifest.json"
    if not manifest_fp.is_file():
        return {
            "ok": True,
            "status": "dev_unpacked",
            "app_dir": str(eff_dir),
            "running_file": running_target.name,
            "running_sha256": running_sha,
            "signature_valid": None,
            "checked_files": 0,
            "mismatches": [],
            "missing_files": [],
            "message": (
                "Running in development source mode (signed integrity_manifest.json is included in compiled releases).\n"
                f"Active file ({running_target.name}) SHA-256:\n{running_sha}"
            ),
        }

    try:
        manifest = json.loads(manifest_fp.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "status": "corrupt_manifest",
            "app_dir": str(eff_dir),
            "running_file": running_target.name,
            "running_sha256": running_sha,
            "signature_valid": False,
            "checked_files": 0,
            "mismatches": [],
            "missing_files": [],
            "message": f"Integrity manifest could not be parsed: {exc}",
        }

    pub = _load_public_key_b64(eff_dir, explicit_public_b64=public_b64) or str(manifest.get("public_key_b64") or "")
    sig = str(manifest.get("ed25519_signature") or "")
    sig_ok = bool(pub and sig and verify_bytes(_canonical_manifest_bytes(manifest), sig, pub))

    files_map = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    mismatches: list[str] = []
    missing_files: list[str] = []
    checked = 0
    for rel, expected_sha in files_map.items():
        fp = (eff_dir / str(rel)).resolve()
        if not fp.is_relative_to(eff_dir) or not fp.is_file():
            missing_files.append(str(rel))
            continue
        checked += 1
        actual = sha256_file(fp)
        if actual != str(expected_sha).lower():
            mismatches.append(str(rel))

    overall_ok = bool(sig_ok and not mismatches and not missing_files)
    status = "verified" if overall_ok else ("signature_invalid" if not sig_ok else "tampered_or_incomplete")
    if overall_ok:
        msg = (
            f"✓ Verified Ed25519 signature and SHA-256 hashes across {checked} installed file(s).\n"
            f"Running ({running_target.name}) SHA-256:\n{running_sha}"
        )
    else:
        msg = (
            f"⚠ Integrity check reported issues (signature_valid={sig_ok}, "
            f"mismatches={len(mismatches)}, missing={len(missing_files)}).\n"
            f"Running ({running_target.name}) SHA-256:\n{running_sha}"
        )
    return {
        "ok": overall_ok,
        "status": status,
        "app_dir": str(eff_dir),
        "running_file": running_target.name,
        "running_sha256": running_sha,
        "signature_valid": sig_ok,
        "checked_files": checked,
        "mismatches": mismatches,
        "missing_files": missing_files,
        "message": msg,
    }
