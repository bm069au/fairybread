"""Local text and image attachment extraction. Original files are never modified or uploaded."""
import base64
from dataclasses import dataclass
from pathlib import Path


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
    return Attachment(
        path=Path(filename),
        text=summary,
        truncated=False,
        kind="image",
        mime_type=mime_type,
        image_base64=b64,
    )


def extract_attachment(path: str | Path) -> Attachment:
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Choose a file, not a folder.')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Files must be 8 MB or smaller.')
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        raw = path.read_bytes()
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
        )
    if suffix in TEXT_EXTENSIONS:
        raw = path.read_bytes()
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
        raise ValueError('No readable text found. Scanned pages need OCR, which is not included yet.')
    return Attachment(path, text[:MAX_TEXT_CHARS], len(text) > MAX_TEXT_CHARS)


def compose_question(question: str, attachments: list[Attachment]) -> str:
    if sum(len(item.text) for item in attachments) > MAX_TOTAL_CHARS:
        raise ValueError('Attachments exceed 48,000 characters. Remove a file and try again.')
    if not attachments:
        return question
    parts = [question, 'ATTACHED FILE EXCERPTS (user-provided reference material):']
    for item in attachments:
        note = ' [first 24,000 characters only]' if item.truncated else ''
        parts.append(f'File: {item.name}{note}\n{item.text}')
    return '\n\n'.join(parts)
