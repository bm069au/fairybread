"""Reproducible Release Build Pipeline for Fairybread (64-bit .exe + Inno Setup .exe + Microsoft Store .msix + Ed25519 Integrity)."""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from integrity_service import (
    build_integrity_manifest,
    get_or_create_signing_keypair,
    write_client_verify_html,
    write_signed_sha256_sums,
)
from palace_config import FAIRYBREAD_VERSION, FAIRYBREAD_WINDOWS_VERSION

PUBLIC_APP_ID = "{B7F4E2A1-6C3D-4B89-9E51-FA18B4EAD001}"
DEV_APP_ID = "{B7F4E2A1-6C3D-4B89-9E51-FA18B4EAD002}"

DEV_ONLY_FILES = {
    "palace_ouroboros.py",
    "palace_watchdog.py",
    "palace_promote.py",
    "build_release.py",
    "palace_launcher.py",
    "ask_gpt_working_backup.py",
}

FORBIDDEN_STAGE_FILES = {
    "key.txt",
    "capture.txt",
    "palace_config.json",
    "credentials.json",
    "fairybread.spec",
    "memory_assistant.spec",
    "install_fairybread_beta.py",
    "uninstall_fairybread.py",
}

DOC_AND_ASSET_FILES = (
    "USER_GUIDE.md",
    "LICENSE.md",
    "PRIVACY.md",
    "CHANGELOG.md",
    "README.md",
    "fairybread_icon.ico",
    "fairybread_icon.png",
)


def find_iscc_exe() -> Path:
    candidates = [
        shutil.which("ISCC"),
        r"C:\Users\moore\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for cand in candidates:
        if cand and Path(cand).is_file():
            return Path(cand)
    raise FileNotFoundError("Inno Setup 6 (ISCC.exe) not found. Install JRSoftware.InnoSetup.")


def find_makeappx_exe() -> Path:
    which_m = shutil.which("makeappx")
    if which_m and Path(which_m).is_file():
        return Path(which_m)
    hits = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\10.*\x64\makeappx.exe"))
    if hits:
        return Path(hits[-1])
    raise FileNotFoundError("Windows SDK makeappx.exe not found.")


def _write_pe_version_file(
    dest_path: Path,
    *,
    win_ver: str,
    disp_ver: str,
    product_name: str,
    internal_name: str,
    original_filename: str,
    file_desc: str,
) -> Path:
    parts = [int(x) for x in win_ver.split(".")]
    while len(parts) < 4:
        parts.append(0)
    tup = f"({parts[0]}, {parts[1]}, {parts[2]}, {parts[3]})"
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tup},
    prodvers={tup},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'Brett Martin Moore'),
            StringStruct(u'FileDescription', u'{file_desc}'),
            StringStruct(u'FileVersion', u'{win_ver}'),
            StringStruct(u'InternalName', u'{internal_name}'),
            StringStruct(u'LegalCopyright', u'Copyright (c) 2026 Brett Martin Moore. All Rights Reserved.'),
            StringStruct(u'OriginalFilename', u'{original_filename}'),
            StringStruct(u'ProductName', u'{product_name}'),
            StringStruct(u'ProductVersion', u'{disp_ver}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    dest_path.write_text(content, encoding="utf-8")
    return dest_path


def stage_clean_source(edition: str, stage_dir: Path, *, public_key_b64: str) -> Path:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    is_public = (edition == "public")

    for fp in sorted(ROOT.glob("*.py")):
        low = fp.name.lower()
        if low.startswith("test_") or low in FORBIDDEN_STAGE_FILES:
            continue
        if is_public and low in DEV_ONLY_FILES:
            continue
        txt = fp.read_text(encoding="utf-8", errors="replace")
        if is_public and fp.name == "palace_config.py":
            txt = txt.replace('FAIRYBREAD_EDITION = "developer"', 'FAIRYBREAD_EDITION = "public"', 1)
        if fp.name == "integrity_service.py" and public_key_b64:
            txt = txt.replace(
                'FAIRYBREAD_EMBEDDED_PUBLIC_KEY_B64 = ""',
                f'FAIRYBREAD_EMBEDDED_PUBLIC_KEY_B64 = "{public_key_b64}"',
                1,
            )
        (stage_dir / fp.name).write_text(txt, encoding="utf-8")

    for doc in DOC_AND_ASSET_FILES:
        src = ROOT / doc
        if src.is_file():
            shutil.copy2(src, stage_dir / doc)

    return stage_dir


def write_pyinstaller_spec(
    *,
    edition: str,
    stage_dir: Path,
    spec_path: Path,
    gui_ver_file: Path,
    mcp_ver_file: Path,
) -> Path:
    icon_fp = str((stage_dir / "fairybread_icon.ico").resolve()).replace("\\", "\\\\")
    stage_posix = stage_dir.as_posix()
    gui_script = (stage_dir / "palace_gui.py").as_posix()
    mcp_script = (stage_dir / "fairybread_mcp.py").as_posix()
    gui_vf = gui_ver_file.as_posix()
    mcp_vf = mcp_ver_file.as_posix()

    datas_lines = []
    for asset in DOC_AND_ASSET_FILES:
        ap = stage_dir / asset
        if ap.is_file():
            datas_lines.append(f"    (r'{ap}', '.'),")
    datas_block = "\n".join(datas_lines)

    excludes = [
        "tkinter",
        "_tkinter",
        "matplotlib",
        "scipy",
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQml",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtSensors",
        "PySide6.QtPositioning",
        "PySide6.QtLocation",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtSerialPort",
        "PySide6.QtWebSockets",
        "PySide6.QtSql",
        "PySide6.QtTest",
    ]
    excludes_str = ", ".join(repr(x) for x in excludes)

    hidden = [
        "setup_wizard",
        "voice_visualizer",
        "cerebras.cloud.sdk",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        "pypdf",
        "docx",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "websockets",
        "google.genai",
        "openai",
        "cohere",
        "mistralai",
        "groq",
        "httpx",
        "numpy",
    ]
    hidden_str = ", ".join(repr(x) for x in hidden)

    spec_src = f"""# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

common_datas = [
{datas_block}
]
common_excludes = [{excludes_str}]
common_hidden = [{hidden_str}]

gui_a = Analysis(
    [r'{gui_script}'],
    pathex=[r'{stage_dir}'],
    binaries=[],
    datas=common_datas,
    hiddenimports=common_hidden,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=common_excludes,
    noarchive=False,
)
mcp_a = Analysis(
    [r'{mcp_script}'],
    pathex=[r'{stage_dir}'],
    binaries=[],
    datas=[],
    hiddenimports=common_hidden,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=common_excludes,
    noarchive=False,
)

MERGE(
    (gui_a, 'Fairybread', 'Fairybread'),
    (mcp_a, 'FairybreadMCP', 'FairybreadMCP'),
)

gui_pyz = PYZ(gui_a.pure, gui_a.zipped_data, cipher=block_cipher)
gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name='Fairybread',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=r'{stage_dir / "fairybread_icon.ico"}',
    version=r'{gui_ver_file}',
)

mcp_pyz = PYZ(mcp_a.pure, mcp_a.zipped_data, cipher=block_cipher)
mcp_exe = EXE(
    mcp_pyz,
    mcp_a.scripts,
    [],
    exclude_binaries=True,
    name='FairybreadMCP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=r'{stage_dir / "fairybread_icon.ico"}',
    version=r'{mcp_ver_file}',
)

coll = COLLECT(
    gui_exe,
    gui_a.binaries,
    gui_a.datas,
    mcp_exe,
    mcp_a.binaries,
    mcp_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Fairybread',
)
"""
    spec_path.write_text(spec_src, encoding="utf-8")
    return spec_path


def compile_pyinstaller_edition(
    *,
    edition: str,
    venv_pyinstaller: Path,
    private_pem: bytes,
    public_key_b64: str,
) -> tuple[Path, Path]:
    stage_dir = ROOT / "build" / f"stage_{edition}"
    stage_clean_source(edition, stage_dir, public_key_b64=public_key_b64)

    prod_name = "Fairybread Developer" if edition == "developer" else "Fairybread"
    gui_vf = _write_pe_version_file(
        ROOT / "build" / f"ver_gui_{edition}.txt",
        win_ver=FAIRYBREAD_WINDOWS_VERSION,
        disp_ver=FAIRYBREAD_VERSION,
        product_name=prod_name,
        internal_name="Fairybread",
        original_filename="Fairybread.exe",
        file_desc=f"{prod_name} Multi-AI Workspace",
    )
    mcp_vf = _write_pe_version_file(
        ROOT / "build" / f"ver_mcp_{edition}.txt",
        win_ver=FAIRYBREAD_WINDOWS_VERSION,
        disp_ver=FAIRYBREAD_VERSION,
        product_name=prod_name,
        internal_name="FairybreadMCP",
        original_filename="FairybreadMCP.exe",
        file_desc=f"{prod_name} MCP Stdio Bridge",
    )

    spec_fp = ROOT / "build" / f"fairybread_{edition}.spec"
    write_pyinstaller_spec(
        edition=edition,
        stage_dir=stage_dir,
        spec_path=spec_fp,
        gui_ver_file=gui_vf,
        mcp_ver_file=mcp_vf,
    )

    dist_out = ROOT / "build" / f"pyi_{edition}"
    work_out = ROOT / "build" / f"pyi_work_{edition}"
    for d in (dist_out, work_out):
        if d.exists():
            shutil.rmtree(d)

    cmd = [
        str(venv_pyinstaller),
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_out),
        "--workpath",
        str(work_out),
        str(spec_fp),
    ]
    print(f"[Build:{edition}] Running PyInstaller -> {dist_out / 'Fairybread'}")
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    app_dir = dist_out / "Fairybread"
    # Copy readable top-level docs/icons beside Fairybread.exe for direct access & clean uninstallers
    for doc in ("USER_GUIDE.md", "LICENSE.md", "PRIVACY.md", "CHANGELOG.md", "fairybread_icon.ico", "fairybread_icon.png"):
        src_doc = stage_dir / doc
        if src_doc.is_file():
            shutil.copy2(src_doc, app_dir / doc)

    # Generate Ed25519 signed integrity manifest inside app_dir BEFORE Inno / MSIX packing
    manifest = build_integrity_manifest(
        app_dir,
        version=FAIRYBREAD_VERSION,
        private_pem=private_pem,
        public_b64=public_key_b64,
    )
    print(f"[Build:{edition}] Signed integrity_manifest.json ({manifest['file_count']} files).")
    return app_dir, stage_dir


def compile_inno_setup(
    *,
    iscc_exe: Path,
    edition: str,
    app_dir: Path,
    stage_dir: Path,
    dist_dir: Path,
) -> Path:
    is_dev = (edition == "developer")
    out_base = (
        f"Fairybread_Developer_v{FAIRYBREAD_VERSION}_Win_x64_Setup"
        if is_dev
        else f"Fairybread_v{FAIRYBREAD_VERSION}_Win_x64_Setup"
    )
    defines = {
        "AppEdition": "Developer" if is_dev else "Public",
        "AppName": "Fairybread Developer" if is_dev else "Fairybread",
        "AppDirName": "Fairybread Developer" if is_dev else "Fairybread",
        "AppIdGuid": DEV_APP_ID if is_dev else PUBLIC_APP_ID,
        "AppDispVer": FAIRYBREAD_VERSION,
        "AppWinVer": FAIRYBREAD_WINDOWS_VERSION,
        "DefaultIncludeSource": "1" if is_dev else "0",
        "PyDistDir": str(app_dir.resolve()),
        "SourceStageDir": str(stage_dir.resolve()),
        "OutputDirPath": str(dist_dir.resolve()),
        "OutputExeBase": out_base,
    }
    cmd = [str(iscc_exe)] + [f"/D{k}={v}" for k, v in defines.items()] + [str(ROOT / "fairybread_setup.iss")]
    print(f"[InnoSetup:{edition}] Compiling {out_base}.exe ...")
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    out_exe = dist_dir / f"{out_base}.exe"
    if not out_exe.is_file():
        raise FileNotFoundError(f"Expected installer missing: {out_exe}")
    return out_exe


def _generate_msix_tile_assets(src_png: Path, assets_dir: Path, python_exe: Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    # Run with .build_venv Python so Pillow is guaranteed present even if outer Python lacks Pillow
    script = f"""
from PIL import Image
src = Image.open(r'''{src_png}''').convert('RGBA')

def make_square(size, out_name):
    bg = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    pad = max(1, int(round(size * 0.06)))
    inner = size - 2 * pad
    im = src.copy()
    im.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    x = (size - im.width) // 2
    y = (size - im.height) // 2
    bg.paste(im, (x, y), im)
    bg.save(r'''{assets_dir}''' + '/' + out_name, format='PNG')

def make_wide(w, h, out_name):
    bg = Image.new('RGBA', (w, h), (13, 17, 23, 255))
    inner = int(round(h * 0.72))
    im = src.copy()
    im.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    x = (w - im.width) // 2
    y = (h - im.height) // 2
    bg.paste(im, (x, y), im)
    bg.save(r'''{assets_dir}''' + '/' + out_name, format='PNG')

make_square(50, 'StoreLogo.png')
make_square(44, 'Square44x44Logo.png')
make_square(24, 'Square44x44Logo.targetsize-24_altform-unplated.png')
make_square(71, 'Square71x71Logo.png')
make_square(150, 'Square150x150Logo.png')
make_square(310, 'Square310x310Logo.png')
make_wide(310, 150, 'Wide310x150Logo.png')
"""
    subprocess.run([str(python_exe), "-c", script], check=True)


def build_msix_package(
    *,
    makeappx_exe: Path,
    app_dir: Path,
    dist_dir: Path,
    venv_python: Path,
    private_pem: bytes,
    public_key_b64: str,
) -> Path:
    from xml.sax.saxutils import escape as _xml_escape

    def _xesc(val: object) -> str:
        return _xml_escape(str(val).strip(), {'"': "&quot;", "'": "&apos;"})

    ident_fp = ROOT / "store_identity.json"
    ident = json.loads(ident_fp.read_text(encoding="utf-8"))
    pkg_name = _xesc(ident["package_name"])
    publisher = _xesc(ident["publisher"])
    pub_disp = _xesc(ident["publisher_display_name"])
    disp_name = _xesc(ident["display_name"])
    desc = _xesc(ident.get("description") or ident["display_name"])

    msix_stage = ROOT / "build" / "msix_public"
    if msix_stage.exists():
        shutil.rmtree(msix_stage)
    shutil.copytree(app_dir, msix_stage)

    opc_conflict_dir = msix_stage / "_internal" / "docx" / "templates" / "default-docx-template"
    if opc_conflict_dir.exists():
        shutil.rmtree(opc_conflict_dir)
    build_integrity_manifest(
        msix_stage,
        version=FAIRYBREAD_VERSION,
        private_pem=private_pem,
        public_b64=public_key_b64,
    )

    assets_dir = msix_stage / "Assets"
    _generate_msix_tile_assets(ROOT / "fairybread_icon.png", assets_dir, venv_python)

    manifest_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">
  <Identity
    Name="{pkg_name}"
    Publisher="{publisher}"
    Version="{FAIRYBREAD_WINDOWS_VERSION}"
    ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>{disp_name}</DisplayName>
    <PublisherDisplayName>{pub_disp}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Applications>
    <Application
      Id="FairybreadApp"
      Executable="Fairybread.exe"
      EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName="{disp_name}"
        Description="{desc}"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png"
        BackgroundColor="#0d1117">
        <uap:DefaultTile
          ShortName="{disp_name}"
          Square71x71Logo="Assets\\Square71x71Logo.png"
          Wide310x150Logo="Assets\\Wide310x150Logo.png"
          Square310x310Logo="Assets\\Square310x310Logo.png" />
      </uap:VisualElements>
    </Application>
  </Applications>
  <Capabilities>
    <Capability Name="internetClient" />
    <rescap:Capability Name="runFullTrust" />
    <DeviceCapability Name="microphone" />
  </Capabilities>
</Package>
"""
    (msix_stage / "AppxManifest.xml").write_text(manifest_xml, encoding="utf-8")

    out_msix = dist_dir / f"Fairybread_v{FAIRYBREAD_VERSION}_Win_x64_StoreUpload.msix"
    print(f"[MSIX] Packing {out_msix.name} ...")
    subprocess.run(
        [str(makeappx_exe), "pack", "/d", str(msix_stage), "/p", str(out_msix), "/o"],
        check=True,
    )
    return out_msix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Fairybread Windows .exe, Setup.exe, and .msix packages.")
    parser.add_argument("--venv", type=Path, default=ROOT / ".build_venv", help="Path to isolated build virtualenv")
    parser.add_argument("--editions", nargs="+", choices=["public", "developer"], default=["public", "developer"])
    parser.add_argument("--msix-only", action="store_true", help="Rebuild MSIX only using existing pyi_public output")
    args = parser.parse_args(argv)

    venv_py = args.venv / "Scripts" / "python.exe"
    venv_pyinstaller = args.venv / "Scripts" / "pyinstaller.exe"
    if not venv_py.is_file() or not venv_pyinstaller.is_file():
        raise FileNotFoundError(f"Build venv missing python/pyinstaller in {args.venv}")

    iscc_exe = find_iscc_exe()
    makeappx_exe = find_makeappx_exe()
    priv_pem, pub_b64 = get_or_create_signing_keypair()

    dist_dir = ROOT / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    built_artifacts: list[Path] = []

    if args.msix_only:
        pub_app = ROOT / "build" / "pyi_public" / "Fairybread"
        if not (pub_app / "Fairybread.exe").is_file():
            pub_app, _ = compile_pyinstaller_edition(
                edition="public",
                venv_pyinstaller=venv_pyinstaller,
                private_pem=priv_pem,
                public_key_b64=pub_b64,
            )
        msix_fp = build_msix_package(
            makeappx_exe=makeappx_exe,
            app_dir=pub_app,
            dist_dir=dist_dir,
            venv_python=venv_py,
            private_pem=priv_pem,
            public_key_b64=pub_b64,
        )
        built_artifacts.append(msix_fp)
    else:
        for ed in args.editions:
            app_dir, stage_dir = compile_pyinstaller_edition(
                edition=ed,
                venv_pyinstaller=venv_pyinstaller,
                private_pem=priv_pem,
                public_key_b64=pub_b64,
            )
            setup_exe = compile_inno_setup(
                iscc_exe=iscc_exe,
                edition=ed,
                app_dir=app_dir,
                stage_dir=stage_dir,
                dist_dir=dist_dir,
            )
            built_artifacts.append(setup_exe)
            if ed == "public":
                msix_fp = build_msix_package(
                    makeappx_exe=makeappx_exe,
                    app_dir=app_dir,
                    dist_dir=dist_dir,
                    venv_python=venv_py,
                    private_pem=priv_pem,
                    public_key_b64=pub_b64,
                )
                built_artifacts.append(msix_fp)

    sums_fp, sig_fp = write_signed_sha256_sums(
        dist_dir,
        built_artifacts,
        private_pem=priv_pem,
        public_b64=pub_b64,
    )
    verify_html = write_client_verify_html(
        dist_dir / "verify.html",
        built_artifacts,
        version=FAIRYBREAD_VERSION,
        public_b64=pub_b64,
    )
    print("\n=== BUILD COMPLETE ===")
    for p in [*built_artifacts, sums_fp, sig_fp, verify_html]:
        print(f"  {p} ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
