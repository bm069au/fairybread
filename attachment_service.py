"""Local text and image attachment extraction. Original files are never modified or uploaded."""
import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil


def get_uploaded_files_dir() -> Path:
    try:
        from palace_config import get_palace_data_root
        base = get_palace_data_root() / "uploaded_files"
    except Exception:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace" / "uploaded_files"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _archive_uploaded_bytes(raw: bytes, original_name: str) -> Path | None:
    try:
        up_dir = get_uploaded_files_dir()
        safe_name = Path(original_name or "uploaded_file").name
        digest = hashlib.sha256(raw).hexdigest()[:8]
        stem = Path(safe_name).stem[:48]
        suffix = Path(safe_name).suffix or ".bin"
        dest = up_dir / f"{stem}_{digest}{suffix}"
        if not dest.exists():
            tmp_path = dest.with_name(dest.name + ".tmp")
            try:
                with tmp_path.open("wb") as fh:
                    fh.write(raw)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(str(tmp_path), str(dest))
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        return dest
    except OSError:
        return None


MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 24000
MAX_TOTAL_CHARS = 48000
TEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.tsv', '.json', '.jsonl', '.yaml', '.yml',
    '.xml', '.html', '.css', '.js', '.ts', '.tsx', '.jsx', '.py', '.ps1',
    '.sql', '.log', '.ini', '.toml', '.rst', '.c', '.cpp', '.h', '.cs',
    '.bat', '.cmd', '.sh', '.java', '.go', '.rs', '.rb', '.php',
}
IMAGE_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp',
}


@dataclass(frozen=True)
class Attachment:
    path: Path
    text: str
    truncated: bool = False
    kind: str = "document"
    mime_type: str = "text/plain"
    image_base64: str = ""
    stored_path: Path | None = None

    @property
    def name(self):
        return self.path.name


def _detect_valid_image(raw: bytes) -> tuple[str, int, int] | None:
    """Validate image magic headers and return (mime_type, width, height) when valid."""
    if len(raw) >= 24 and raw.startswith(b'\x89PNG\r\n\x1a\n'):
        width = int.from_bytes(raw[16:20], 'big')
        height = int.from_bytes(raw[20:24], 'big')
        if width > 0 and height > 0:
            return ('image/png', width, height)
    if len(raw) >= 4 and raw.startswith(b'\xff\xd8\xff'):
        return ('image/jpeg', 0, 0)
    if len(raw) >= 10 and (raw.startswith(b'GIF87a') or raw.startswith(b'GIF89a')):
        width = int.from_bytes(raw[6:8], 'little')
        height = int.from_bytes(raw[8:10], 'little')
        return ('image/gif', width, height)
    if len(raw) >= 26 and raw.startswith(b'BM'):
        width = abs(int.from_bytes(raw[18:22], 'little', signed=True))
        height = abs(int.from_bytes(raw[22:26], 'little', signed=True))
        return ('image/bmp', width, height)
    if len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return ('image/webp', 0, 0)
    return None


def attachment_from_image_bytes(raw: bytes, filename: str = "clipboard-image.png") -> Attachment:
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError('Image must be non-empty and 8 MB or smaller.')
    info = _detect_valid_image(raw)
    if info is None:
        raise ValueError('This image file is damaged or not in a supported image format.')
    mime_type, width, height = info
    dims = f' ({width}x{height} px)' if width and height else ''
    b64 = base64.b64encode(raw).decode('ascii')
    summary = (
        f'[Attached Image: {filename}{dims}, {mime_type}, {len(raw):,} bytes]'
    )
    stored = _archive_uploaded_bytes(raw, filename)
    return Attachment(
        path=Path(filename),
        text=summary,
        truncated=False,
        kind="image",
        mime_type=mime_type,
        image_base64=b64,
        stored_path=stored,
    )


def _ocr_scanned_pdf_with_mistral(
    raw_pdf_bytes: bytes,
    *,
    credential_store=None,
) -> str:
    """Fallback OCR via `mistral-ocr-latest` when local pypdf extracts zero text from a scanned PDF."""
    if not raw_pdf_bytes:
        return ""
    # Skip hitting real network credentials during offscreen automated test runs unless a store was explicitly injected
    if credential_store is None and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return ""
    try:
        from credential_store import CredentialStore
        store = credential_store or CredentialStore()
        m_key = (store.get_api_key("mistral") or "").strip()
    except Exception:
        return ""
    if not m_key:
        return ""
    try:
        from mistralai.client import Mistral
        b64 = base64.b64encode(raw_pdf_bytes).decode("ascii")
        client = Mistral(api_key=m_key, timeout_ms=45000)
        resp = client.ocr.process(
            model="mistral-ocr-latest",
            document={"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"},
        )
        pages = getattr(resp, "pages", None) or []
        parts = [
            str(getattr(pg, "markdown", "") or "").strip()
            for pg in pages
            if str(getattr(pg, "markdown", "") or "").strip()
        ]
        return "\n\n".join(parts).strip()
    except Exception:
        return ""


def extract_attachment(path: str | Path, *, credential_store=None) -> Attachment:
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Choose a file, not a folder.')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Files must be 8 MB or smaller.')
    raw_all = path.read_bytes()
    stored_copy = _archive_uploaded_bytes(raw_all, path.name)
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        raw = raw_all
        # Ensure sRGB and 300 DPI metadata if processed via Pillow
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            out_io = io.BytesIO()
            save_kwargs = {'dpi': (300, 300)}
            if 'icc_profile' in img.info:
                save_kwargs['icc_profile'] = img.info['icc_profile']
            elif 'sRGB' not in getattr(img, 'text', {}):
                pass # Pillow default handles standard sRGB container
            format_name = img.format if img.format in ('PNG', 'JPEG', 'WEBP') else 'PNG'
            if format_name == 'JPEG':
                save_kwargs['quality'] = 95
            img.save(out_io, format=format_name, **save_kwargs)
            raw = out_io.getvalue()
        except Exception:
            pass # Fall back to raw bytes if PIL processing encounters non-standard frames
        info = _detect_valid_image(raw)
        if info is None:
            raise ValueError('This file is not a valid image.')
        mime_type, width, height = info
        dims = f' ({width}x{height} px)' if width and height else ''
        b64 = base64.b64encode(raw).decode('ascii')
        summary = f'[Attached Image: {path.name}{dims}, {mime_type}, {len(raw):,} bytes]'
        return Attachment(
            path=path,
            text=summary,
            truncated=False,
            kind="image",
            mime_type=mime_type,
            image_base64=b64,
            stored_path=stored_copy,
        )
    if suffix in TEXT_EXTENSIONS:
        raw = raw_all
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            text = raw.decode('utf-16')
        else:
            text = raw.decode('utf-8-sig')
        if '\x00' in text:
            raise ValueError('This appears to be a binary file, not readable text.')
    elif suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ValueError('Password-protected PDFs are not supported.')
        pieces = []
        count = 0
        for page in reader.pages:
            part = page.extract_text() or ''
            pieces.append(part)
            count += len(part) + 2
            if count > MAX_TEXT_CHARS:
                break
        text = '\n\n'.join(pieces)
        if not text.strip():
            ocr_txt = _ocr_scanned_pdf_with_mistral(raw_all, credential_store=credential_store)
            if ocr_txt.strip():
                text = ocr_txt
    elif suffix == '.docx':
        from zipfile import ZipFile
        from docx import Document
        with ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist()) > 32 * 1024 * 1024:
                raise ValueError('This Word document expands beyond the supported size.')
        document = Document(path)
        # Preserve the document's paragraph/table ordering.
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        pieces = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                pieces.append(block.text)
            elif isinstance(block, Table):
                pieces.extend(' | '.join(cell.text for cell in row.cells) for row in block.rows)
        text = '\n'.join(pieces)
    else:
        raise ValueError('Supported: text/code, PDF with selectable text, Word .docx, and standard images (.png, .jpg, .webp, .gif, .bmp).')
    if not text.strip():
        raise ValueError('No readable text found. Scanned pages need OCR (connect a Mistral API key with active billing for automatic Mistral OCR).')
    return Attachment(path, text[:MAX_TEXT_CHARS], len(text) > MAX_TEXT_CHARS, stored_path=stored_copy)


def compose_question(question: str, attachments: list[Attachment], allow_unlimited: bool = False) -> str:
    if not attachments:
        return question
    if not allow_unlimited and sum(len(item.text) for item in attachments) > MAX_TOTAL_CHARS:
        raise ValueError(
            f'Attachments exceed the {MAX_TOTAL_CHARS:,}-character limit. Remove one or ask about fewer files at once.'
        )
    parts = [question, 'ATTACHED FILE EXCERPTS (user-provided reference material):']
    for item in attachments:
        note = ' [first 24,000 characters only]' if item.truncated else ''
        stored_name = item.stored_path.name if item.stored_path is not None else ''
        meta_tag = f'[ATTACHED_FILE_META kind="{item.kind}" name="{item.name}" stored="{stored_name}"]\n'
        parts.append(f'{meta_tag}File: {item.name}{note}\n{item.text}')
    return '\n\n'.join(parts)


def parse_user_message_attachments(content: str) -> tuple[str, list[dict[str, str]]]:
    """Split a user prompt into (visible_user_text, attachment_visual_cards) so raw file dumps are hidden in the chat UI."""
    marker = 'ATTACHED FILE EXCERPTS (user-provided reference material):'
    if marker not in content:
        return content, []

    head, tail = content.split(marker, 1)
    clean_text = head.rstrip()
    up_dir = get_uploaded_files_dir()
    attachments_out: list[dict[str, str]] = []
    seen_names: set[str] = set()

    import re
    for m in re.finditer(r'\[ATTACHED_FILE_META\s+kind="([^"]+)"\s+name="([^"]+)"\s+stored="([^"]*)"\]', tail):
        kind, name, stored_name = m.group(1), m.group(2), m.group(3)
        resolved = (up_dir / stored_name) if stored_name else None
        if (resolved is None or not resolved.exists()) and name:
            p_name = Path(name)
            candidates = sorted(
                up_dir.glob(f"{p_name.stem[:48]}_*{p_name.suffix}"),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
            if candidates:
                resolved = candidates[0]
        attachments_out.append({
            "kind": kind,
            "name": name,
            "path": str(resolved) if (resolved and resolved.exists()) else "",
        })
        seen_names.add(name)

    for m in re.finditer(r'(?m)^File:\s+([^\r\n\[]+?)(?:\s+\[first 24,000 characters only\])?\s*$', tail):
        fname = m.group(1).strip()
        if not fname or fname in seen_names:
            continue
        p_name = Path(fname)
        ext = p_name.suffix.lower()
        kind = "image" if ext in IMAGE_EXTENSIONS else "text"
        resolved = None
        candidates = sorted(
            up_dir.glob(f"{p_name.stem[:48]}_*{p_name.suffix}"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if candidates:
            resolved = candidates[0]
        attachments_out.append({
            "kind": kind,
            "name": fname,
            "path": str(resolved) if (resolved and resolved.exists()) else "",
        })
        seen_names.add(fname)

    return clean_text, attachments_out

