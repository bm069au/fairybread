"""Local text extraction. Original files are never modified or uploaded."""
from dataclasses import dataclass
from pathlib import Path


MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 24000
MAX_TOTAL_CHARS = 48000
TEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.tsv', '.json', '.jsonl', '.yaml', '.yml',
    '.xml', '.html', '.css', '.js', '.ts', '.tsx', '.jsx', '.py', '.ps1',
    '.sql', '.log', '.ini', '.toml', '.rst', '.c', '.cpp', '.h', '.cs',
}


@dataclass(frozen=True)
class Attachment:
    path: Path
    text: str
    truncated: bool = False

    @property
    def name(self):
        return self.path.name


def extract_attachment(path: str | Path) -> Attachment:
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Choose a file, not a folder.')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Files must be 8 MB or smaller.')
    suffix = path.suffix.lower()
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
        raise ValueError('Supported: text/code, PDF with selectable text, and Word .docx. Images, scans and other binary files are not supported yet.')
    if not text.strip():
        raise ValueError('No readable text found. Scanned pages and images need OCR, which is not included yet.')
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
