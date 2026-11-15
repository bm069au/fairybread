"""Palace Theme, Custom Vector Icons, Markdown Formatter, and AI Drawing/Image Engine."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtSvg import QSvgRenderer

from credential_store import CredentialStore
from palace_config import PROVIDER_CATALOG

NEUTRAL_GREY = "#6e7681"
NEUTRAL_GREY_TEXT = "#8b949e"
NEUTRAL_GREY_BG = "#161920"
NEUTRAL_BORDER = "#21262d"

AI_ICONS = {k: v["icon"] for k, v in PROVIDER_CATALOG.items()}
AI_COLORS = {k: v["color"] for k, v in PROVIDER_CATALOG.items()}
AI_BG_COLORS = {k: v["bg_color"] for k, v in PROVIDER_CATALOG.items()}
AI_DISPLAY_NAMES = {k: v["display_name"] for k, v in PROVIDER_CATALOG.items()}


def get_generated_images_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace" / "generated_images"
    base.mkdir(parents=True, exist_ok=True)
    return base


def provider_icon(name: str) -> str:
    return AI_ICONS.get((name or "").lower(), "•")


def provider_color(name: str) -> str:
    return AI_COLORS.get((name or "").lower(), NEUTRAL_GREY)


def provider_bg_color(name: str) -> str:
    return AI_BG_COLORS.get((name or "").lower(), NEUTRAL_GREY_BG)


AI_SHORT_NAMES = {
    "gemini": "Gemini",
    "openai": "OpenAI",
    "anthropic": "Claude",
    "xai": "Grok",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "cohere": "Cohere",
    "mistral": "Mistral",
    "openrouter": "OpenRouter",
    "deepinfra": "DeepInfra",
    "groq": "Groq",
    "cerebras": "Cerebras",
    "together": "Together",
    "perplexity": "Perplexity",
    "ollama": "Ollama",
}


def provider_display_name(name: str) -> str:
    clean = (name or "").lower()
    return AI_SHORT_NAMES.get(clean, AI_DISPLAY_NAMES.get(clean, clean.capitalize()))


def format_ai_badge_html(name: str, active: bool = True) -> str:
    icon = provider_icon(name)
    color = provider_color(name) if active else NEUTRAL_GREY
    disp = html.escape(provider_display_name(name))
    return (
        f'<span style="color:{color}; font-weight:700;">{icon}</span> '
        f'<span style="color:#e6edf3; font-weight:600;">{disp}</span>'
    )


def provider_token_qicon(name: str, state: str = "active", pulse_step: int = 0) -> QIcon:
    """Render a subtle, understated 16x16 symbol glyph:
    - state == 'active': Clean colored glyph (no neon box or heavy rings)
    - state == 'working': Glyph pulses softly between brand color and white
    - state == 'inactive': Pure Neutral Grey (#6e7681) glyph
    """
    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    is_active = state in {"active", "working"}
    fg_hex = provider_color(name) if is_active else NEUTRAL_GREY
    if state == "working" and (pulse_step % 2 == 1):
        fg_hex = "#ffffff"
    fg = QColor(fg_hex)
    if not is_active:
        fg.setAlpha(155)

    painter.setPen(fg)
    font = QFont("Segoe UI Symbol", 9)
    font.setBold(is_active)
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, 16, 16), Qt.AlignmentFlag.AlignCenter, provider_icon(name))
    painter.end()
    return QIcon(pix)


def provider_qicon(name: str, checked: bool | None = None) -> QIcon:
    """Menu / badge icon for a provider."""
    pix = QPixmap(20, 20)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    col = QColor(provider_color(name) if checked is not False else NEUTRAL_GREY)
    if checked is True:
        bg = QColor(provider_bg_color(name))
        painter.setPen(QPen(col, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(1, 1, 18, 18, 5, 5)
    elif checked is False:
        painter.setPen(QPen(QColor(NEUTRAL_GREY), 1.0))
        painter.drawRoundedRect(1, 1, 18, 18, 5, 5)
    painter.setPen(col)
    font = QFont("Segoe UI Symbol", 10)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, provider_icon(name))
    painter.end()
    return QIcon(pix)


def no_history_qicon(active: bool = False) -> QIcon:
    """Brain silhouette with diagonal slash: Pure Grey when OFF, Red (#ef4444) when ON."""
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    brain_col = QColor("#fca5a5" if active else NEUTRAL_GREY)
    pen = QPen(brain_col, 1.4)
    painter.setPen(pen)
    painter.setBrush(QColor("#3b1219") if active else Qt.BrushStyle.NoBrush)
    painter.drawEllipse(2, 3, 7, 6)
    painter.drawEllipse(7, 2, 8, 6)
    painter.drawEllipse(3, 7, 11, 6)

    slash_col = QColor("#ef4444" if active else NEUTRAL_GREY)
    slash_pen = QPen(slash_col, 2.0 if active else 1.5)
    slash_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(slash_pen)
    painter.drawLine(2, 15, 16, 2)
    painter.end()
    return QIcon(pix)


def tangent_qicon(active: bool = False) -> QIcon:
    """Branching Y-fork icon: Pure Grey when OFF, Yellow (#eab308) when ON."""
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor("#eab308" if active else NEUTRAL_GREY)
    pen = QPen(col, 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    # Main stem at bottom splitting into two branches
    painter.drawLine(9, 15, 9, 9)
    painter.drawLine(9, 9, 4, 4)
    painter.drawLine(9, 9, 14, 4)
    # Small arrow heads
    painter.drawLine(4, 4, 7, 4)
    painter.drawLine(4, 4, 4, 7)
    painter.drawLine(14, 4, 11, 4)
    painter.drawLine(14, 4, 14, 7)
    painter.end()
    return QIcon(pix)


def council_qicon(active: bool = True) -> QIcon:
    """Three connected council nodes when ON (Purple #a855f7), or direct arrow when OFF (Grey #6e7681)."""
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if active:
        col = QColor("#a855f7")
        painter.setPen(QPen(col, 1.3))
        painter.drawLine(9, 4, 4, 13)
        painter.drawLine(9, 4, 14, 13)
        painter.drawLine(4, 13, 14, 13)
        painter.setBrush(col)
        painter.drawEllipse(QPointF(9, 4), 2.3, 2.3)
        painter.drawEllipse(QPointF(4, 13), 2.3, 2.3)
        painter.drawEllipse(QPointF(14, 13), 2.3, 2.3)
    else:
        col = QColor(NEUTRAL_GREY)
        pen = QPen(col, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(3, 9, 14, 9)
        painter.drawLine(10, 5, 14, 9)
        painter.drawLine(10, 13, 14, 9)
    painter.end()
    return QIcon(pix)


def code_shield_qicon(active: bool = False) -> QIcon:
    """Code brackets { } icon: Pure Grey when OFF, Cyan (#06b6d4) when ON."""
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    col = QColor("#06b6d4" if active else NEUTRAL_GREY)
    painter.setPen(col)
    font = QFont("Consolas", 10)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "{}")
    painter.end()
    return QIcon(pix)


def idle_moon_qicon(active: bool = False) -> QIcon:
    """Crescent moon / sanctuary icon: Pure Grey when OFF, Emerald Green (#22c55e) when ON."""
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor("#22c55e" if active else NEUTRAL_GREY)
    painter.setPen(QPen(col, 1.5))
    painter.setBrush(col if active else Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.addEllipse(3, 3, 12, 12)
    cut = QPainterPath()
    cut.addEllipse(7, 1, 11, 11)
    crescent = path.subtracted(cut)
    painter.drawPath(crescent)
    painter.end()
    return QIcon(pix)


def folder_grey_qicon(active: bool = False) -> QIcon:
    """Clean monochrome vector folder icon (Grey when inactive, Cyan #06b6d4 when active — never orange emoji!)."""
    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor("#06b6d4" if active else NEUTRAL_GREY)
    painter.setPen(QPen(col, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(2, 4)
    path.lineTo(6, 4)
    path.lineTo(7.5, 6)
    path.lineTo(14, 6)
    path.lineTo(14, 13)
    path.lineTo(2, 13)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return QIcon(pix)


def mail_grey_qicon(has_unread: bool = False) -> QIcon:
    """Clean vector envelope icon (Grey when 0 unread, Green #22c55e dot when unread)."""
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor("#22c55e" if has_unread else NEUTRAL_GREY)
    painter.setPen(QPen(col, 1.4))
    painter.drawRoundedRect(2, 4, 14, 10, 2, 2)
    painter.drawLine(2, 5, 9, 10)
    painter.drawLine(16, 5, 9, 10)
    if has_unread:
        painter.setBrush(QColor("#22c55e"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(13, 2, 4, 4)
    painter.end()
    return QIcon(pix)


# --- AI DRAWING & IMAGE GENERATION TOOLS ---

_SVG_FENCE_PATTERN = re.compile(
    r"```svg\s*(.*?)\s*```|\[DRAW_SVG(?:\s+title=\"([^\"]*)\")?\s*\](.*?)\[/DRAW_SVG\]",
    re.IGNORECASE | re.DOTALL,
)

_GENERATE_IMAGE_PATTERN = re.compile(
    r"\[GENERATE_IMAGE\s+prompt=\"([^\"]+)\"(?:\s+title=\"([^\"]*)\")?\s*\]",
    re.IGNORECASE,
)

_PALACE_SNAPSHOT_PATTERN = re.compile(
    r"\[PALACE_UI_SNAPSHOT(?:\s+path=\"([^\"]*)\")?(?:\s+title=\"([^\"]*)\")?\s*\]",
    re.IGNORECASE,
)


_MARKDOWN_HTML_CACHE: dict[str, str] = {}


def render_svg_to_png(svg_xml: str, title: str = "palace_drawing") -> Path | None:
    """Render raw SVG XML from an AI response into a crisp high-resolution PNG file on disk."""
    clean_svg = (svg_xml or "").strip()
    if "<svg" not in clean_svg.lower():
        return None
    # Strip any HTML wrapper outside <svg ...>...</svg>
    start_idx = clean_svg.lower().find("<svg")
    end_idx = clean_svg.lower().rfind("</svg>")
    if start_idx >= 0 and end_idx > start_idx:
        clean_svg = clean_svg[start_idx : end_idx + 6]
    # Escape bare '&' inside AI-written SVG text (e.g. '100s & 1000s') so XML parsing succeeds
    clean_svg = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", clean_svg)

    # Expand viewBox right margin slightly if AI text overflows the right edge
    vb_match = re.search(r'viewBox="(\d+)\s+(\d+)\s+(\d+)\s+(\d+)"', clean_svg)
    if vb_match:
        vx, vy, vw, vh = (int(vb_match.group(i)) for i in range(1, 5))
        padded_vw = int(vw * 1.12)
        clean_svg = clean_svg.replace(vb_match.group(0), f'viewBox="{vx} {vy} {padded_vw} {vh}"', 1)

    # Instant SHA-1 disk cache check BEFORE touching QSvgRenderer or QPixmap!
    digest = hashlib.sha1((clean_svg + "_v2").encode("utf-8", errors="replace")).hexdigest()[:10]
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (title or "drawing").strip())[:24] or "drawing"
    out_path = get_generated_images_dir() / f"{safe_slug}_{digest}.png"
    if out_path.exists() and out_path.stat().st_size > 100:
        return out_path

    renderer = QSvgRenderer(QByteArray(clean_svg.encode("utf-8", errors="replace")))
    if not renderer.isValid():
        return None

    default_size = renderer.defaultSize()
    base_w = max(560, min(1400, default_size.width() if default_size.width() > 0 else 860))
    base_h = max(300, min(1000, default_size.height() if default_size.height() > 0 else 440))

    # Render at crisp 1:1 display width (760px) so QTextBrowser never blurs it by scaling!
    target_w = min(820, max(640, base_w))
    target_h = int(base_h * (target_w / float(base_w)))

    pix = QPixmap(target_w, target_h)
    pix.fill(QColor("#0d1117"))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, target_w, target_h))
    painter.end()

    pix.save(str(out_path), "PNG")
    return out_path


def generate_ai_image_to_png(prompt: str, title: str = "ai_image", *, allow_network: bool = False) -> Path | None:
    """Return cached image or generate via OpenAI Images API (only when allow_network=True on worker thread)."""
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return None
    digest = hashlib.sha1(clean_prompt.encode("utf-8", errors="replace")).hexdigest()[:10]
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (title or "image").strip())[:24] or "image"
    out_path = get_generated_images_dir() / f"{safe_slug}_{digest}.png"
    if out_path.exists():
        return out_path
    if not allow_network:
        return None

    # Try OpenAI DALL-E / gpt-image if key is present (worker thread only!)
    api_key = CredentialStore().get_api_key("openai")
    if api_key:
        try:
            payload = json.dumps({
                "model": "dall-e-3",
                "prompt": clean_prompt,
                "n": 1,
                "size": "1024x1024",
                "response_format": "b64_json",
            }).encode("utf-8")
            req = urllib_request.Request(
                "https://api.openai.com/v1/images/generations",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=35) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                b64_data = body["data"][0].get("b64_json")
                if b64_data:
                    out_path.write_bytes(base64.b64decode(b64_data))
                    return out_path
        except Exception:
            pass

    return None


def format_markdown_and_drawings(content: str) -> str:
    """Convert AI response text into clean HTML with rendered SVG/Image pictures, headings, bold, and code blocks."""
    raw = content or ""
    if raw in _MARKDOWN_HTML_CACHE and "[PALACE_UI_SNAPSHOT" not in raw:
        return _MARKDOWN_HTML_CACHE[raw]
    rendered_images_html: list[str] = []

    # 1. Extract and render any ```svg ... ``` or [DRAW_SVG]...[/DRAW_SVG] blocks into real PNG images
    def _replace_svg(match: re.Match) -> str:
        fenced_svg = match.group(1)
        tag_title = match.group(2) or "UI & Graphic Preview"
        tag_svg = match.group(3)
        svg_code = fenced_svg if fenced_svg is not None else (tag_svg or "")
        png_path = render_svg_to_png(svg_code, title=tag_title)
        if png_path and png_path.exists():
            file_url = png_path.as_uri()
            esc_title = html.escape(tag_title)
            esc_path = html.escape(str(png_path))
            img_block = (
                f'<table width="100%" cellspacing="0" cellpadding="8" style="margin:10px 0; background:#0d1117; border:1px solid #21262d;">'
                f'<tr><td>'
                f'<div style="color:#8b949e; font-size:11.5px; font-weight:600; margin-bottom:6px;">'
                f'🖼 {esc_title} &nbsp;·&nbsp; '
                f'<a href="open-img:{esc_path}" style="color:#3b82f6; text-decoration:none;">Click to Zoom / Open Full Size ↗</a>'
                f'</div>'
                f'<a href="open-img:{esc_path}"><img src="{file_url}" width="220"></a>'
                f'</td></tr></table>'
            )
            idx = len(rendered_images_html)
            rendered_images_html.append(img_block)
            return f"@@PALACE_IMG_{idx}@@"
        return match.group(0)

    processed = _SVG_FENCE_PATTERN.sub(_replace_svg, raw)

    # 2. Extract and render any [GENERATE_IMAGE prompt="..."] tags
    def _replace_gen_img(match: re.Match) -> str:
        img_prompt = match.group(1)
        img_title = match.group(2) or img_prompt[:40]
        png_path = generate_ai_image_to_png(img_prompt, title=img_title)
        if png_path and png_path.exists():
            file_url = png_path.as_uri()
            esc_title = html.escape(img_title)
            img_block = (
                f'<div style="margin:10px 0; padding:10px; background:#0d1117; border:1px solid #21262d; border-radius:8px;">'
                f'<div style="color:#8b949e; font-size:11.5px; font-weight:600; margin-bottom:6px;">'
                f'🎨 {esc_title} &nbsp;·&nbsp; '
                f'<a href="open-img:{html.escape(str(png_path))}" style="color:#22c55e; text-decoration:none;">Open Full Size ↗</a>'
                f'</div>'
                f'<img src="{file_url}" width="540" style="border-radius:6px;">'
                f'</div>'
            )
            idx = len(rendered_images_html)
            rendered_images_html.append(img_block)
            return f"@@PALACE_IMG_{idx}@@"
        return f'[Image Request: "{img_prompt}"]'

    processed = _GENERATE_IMAGE_PATTERN.sub(_replace_gen_img, processed)

    # 2b. Extract and render any [PALACE_UI_SNAPSHOT] tags (strictly PalaceWindow widget buffer only)
    def _replace_ui_snap(match: re.Match) -> str:
        explicit_path = (match.group(1) or "").strip()
        snap_title = (match.group(2) or "Live PalaceWindow Widget Self-Inspection Snapshot").strip()
        png_path: Path | None = None
        audit_summary = ""
        if explicit_path and Path(explicit_path).exists():
            png_path = Path(explicit_path)
        else:
            # Find latest palace_ui_snapshot*.png in generated_images
            gen_dir = get_generated_images_dir()
            snaps = sorted(gen_dir.glob("palace_*snap*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
            if snaps:
                png_path = snaps[0]
        audit_file = Path(r"C:\Palace_Idle_Sandbox\latest_ui_audit.json")
        if audit_file.exists():
            try:
                aud = json.loads(audit_file.read_text(encoding="utf-8"))
                audit_summary = (
                    f" · Window: {aud.get('window_size', '?')} · "
                    f"Buttons: {aud.get('visible_button_count', 0)} · "
                    f"Clipped: {aud.get('clipped_widget_count', 0)}"
                )
            except Exception:
                pass
        if png_path and png_path.exists():
            file_url = png_path.as_uri()
            esc_title = html.escape(snap_title + audit_summary)
            esc_path = html.escape(str(png_path))
            img_block = (
                f'<table width="100%" cellspacing="0" cellpadding="8" style="margin:10px 0; background:#0d1117; border:1px solid #2ea043;">'
                f'<tr><td>'
                f'<div style="color:#2ea043; font-size:11.5px; font-weight:600; margin-bottom:6px;">'
                f'📸 {esc_title} &nbsp;·&nbsp; '
                f'<a href="open-img:{esc_path}" style="color:#3b82f6; text-decoration:none;">Click to Inspect Full Size ↗</a>'
                f'</div>'
                f'<a href="open-img:{esc_path}"><img src="{file_url}" width="720"></a>'
                f'</td></tr></table>'
            )
            idx = len(rendered_images_html)
            rendered_images_html.append(img_block)
            return f"@@PALACE_IMG_{idx}@@"
        return "[Palace UI Snapshot Ready]"

    processed = _PALACE_SNAPSHOT_PATTERN.sub(_replace_ui_snap, processed)

    # 3. Extract fenced code blocks ```lang ... ``` so we don't mangle code
    code_blocks: list[str] = []

    def _replace_code(match: re.Match) -> str:
        lang = (match.group(1) or "").strip()
        code_txt = html.escape(match.group(2) or "")
        lang_hdr = (
            f'<div style="color:#6e7681; font-size:11px; font-family:Consolas,monospace; margin-bottom:4px;">{html.escape(lang)}</div>'
            if lang else ""
        )
        block = (
            f'<table width="100%" cellspacing="0" cellpadding="10" style="margin:8px 0; background:#0d1117; border:1px solid #21262d;">'
            f'<tr><td style="font-family:Consolas,monospace; font-size:12px; color:#d0d7de; white-space:pre-wrap;">'
            f'{lang_hdr}{code_txt}</td></tr></table>'
        )
        idx = len(code_blocks)
        code_blocks.append(block)
        return f"@@PALACE_CODE_{idx}@@"

    processed = re.sub(r"```([a-zA-Z0-9_-]*)\n(.*?)```", _replace_code, processed, flags=re.DOTALL)

    # 4. Escape remaining text and format Markdown headings, bold, inline code, and horizontal rules
    escaped = html.escape(processed)
    lines = escaped.split("\n")
    out_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped in {"---", "***", "___"}:
            out_lines.append('<hr style="border:none; border-top:1px solid #21262d; margin:10px 0;">')
            continue
        if stripped.startswith("#### "):
            out_lines.append(f'<div style="font-size:13.5px; font-weight:700; color:#f0f6fc; margin-top:8px;">{stripped[5:]}</div>')
            continue
        if stripped.startswith("### "):
            out_lines.append(f'<div style="font-size:14.5px; font-weight:700; color:#f0f6fc; margin-top:10px; margin-bottom:2px;">{stripped[4:]}</div>')
            continue
        if stripped.startswith("## "):
            out_lines.append(f'<div style="font-size:15.5px; font-weight:700; color:#ffffff; margin-top:12px; margin-bottom:3px;">{stripped[3:]}</div>')
            continue
        if stripped.startswith("# "):
            out_lines.append(f'<div style="font-size:16.5px; font-weight:700; color:#ffffff; margin-top:12px; margin-bottom:4px;">{stripped[2:]}</div>')
            continue
        if stripped.startswith("* ") or stripped.startswith("- "):
            line = f"&nbsp;&nbsp;• {stripped[2:]}"
        out_lines.append(line)

    formatted = "<br>".join(out_lines)
    # Bold **text**
    formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", formatted)
    # Inline `code`
    formatted = re.sub(
        r"`([^`\n]+)`",
        r'<span style="font-family:Consolas,monospace; background:#1c2129; color:#e6edf3; padding:1px 5px; border-radius:4px; font-size:12px;">\1</span>',
        formatted,
    )

    # Restore code blocks and rendered images
    for idx, cblock in enumerate(code_blocks):
        formatted = formatted.replace(f"@@PALACE_CODE_{idx}@@", cblock)
    for idx, iblock in enumerate(rendered_images_html):
        formatted = formatted.replace(f"@@PALACE_IMG_{idx}@@", iblock)

    if len(_MARKDOWN_HTML_CACHE) > 250:
        _MARKDOWN_HTML_CACHE.clear()
    _MARKDOWN_HTML_CACHE[raw] = formatted
    return formatted


def fairybread_app_qicon() -> QIcon:
    """Render a multi-resolution (16..256px) Fairybread app icon:
    Loads the transparent Fairybread mascot icon (fairybread_icon.png) across all Windows
    titlebar/taskbar resolutions (16..256px), falling back to the top-left white-bread triangle if absent.
    """
    icon = QIcon()
    asset_png = Path(__file__).resolve().parent / "fairybread_icon.png"
    if asset_png.exists():
        base_pix = QPixmap(str(asset_png))
        if not base_pix.isNull():
            for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
                scaled = base_pix.scaled(
                    sz,
                    sz,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                icon.addPixmap(scaled)
            try:
                ico_path = get_generated_images_dir().parent / "fairybread.ico"
                icon.pixmap(64, 64).save(str(ico_path), "ICO")
            except Exception:
                pass
            return icon

    # Fallback: Coordinates matching the top-left white-bread triangle + loose sprinkles below the diagonal cut
    sprinkle_specs = [
        # Row 1 (upper bread interior)
        (0.19, 0.23, "#ff5ca8"), (0.28, 0.25, "#ffd43b"), (0.37, 0.22, "#4dabf7"),
        (0.46, 0.21, "#69db7c"), (0.55, 0.24, "#ffa94d"), (0.64, 0.22, "#b197fc"),
        # Row 2
        (0.26, 0.34, "#ff6b6b"), (0.35, 0.36, "#ffd43b"), (0.45, 0.33, "#69db7c"),
        (0.54, 0.36, "#4dabf7"), (0.62, 0.34, "#b197fc"), (0.71, 0.38, "#ff5ca8"),
        # Row 3
        (0.17, 0.43, "#ffd43b"), (0.25, 0.46, "#4dabf7"), (0.34, 0.43, "#ff6b6b"),
        (0.43, 0.45, "#69db7c"), (0.60, 0.46, "#b197fc"), (0.69, 0.44, "#ffa94d"), (0.78, 0.47, "#4dabf7"),
        # Row 4
        (0.28, 0.56, "#ff5ca8"), (0.39, 0.58, "#ffd43b"), (0.49, 0.56, "#69db7c"),
        (0.59, 0.58, "#b197fc"), (0.69, 0.56, "#ffffff"), (0.80, 0.59, "#ff6b6b"),
        # Row 5 (lower corner + spilling off diagonal cut)
        (0.21, 0.69, "#b197fc"), (0.43, 0.68, "#ffd43b"), (0.55, 0.70, "#4dabf7"), (0.67, 0.68, "#69db7c"),
        (0.32, 0.78, "#ffa94d"), (0.46, 0.79, "#ffffff"), (0.61, 0.78, "#ff5ca8"), (0.74, 0.78, "#ffd43b"),
    ]
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pix = QPixmap(sz, sz)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Pure white bread interior (top-left 90-degree triangle: top-left, top-right, bottom-left)
        tri = QPolygonF([
            QPointF(sz * 0.06, sz * 0.08),
            QPointF(sz * 0.94, sz * 0.08),
            QPointF(sz * 0.06, sz * 0.88),
        ])
        p.setPen(QPen(QColor("#e2e8f0"), max(0.8, sz * 0.015)))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(tri)

        # Top horizontal crust bevel + Left vertical crust bevel (golden-brown #c87d32, darker outer rim #8c5218)
        crust_w = max(1.8, sz * 0.085)
        top_crust = QPolygonF([
            QPointF(sz * 0.04, sz * 0.05),
            QPointF(sz * 0.96, sz * 0.05),
            QPointF(sz * 0.88, sz * 0.05 + crust_w),
            QPointF(sz * 0.04 + crust_w, sz * 0.05 + crust_w),
        ])
        left_crust = QPolygonF([
            QPointF(sz * 0.04, sz * 0.05),
            QPointF(sz * 0.04 + crust_w, sz * 0.05 + crust_w),
            QPointF(sz * 0.04 + crust_w, sz * 0.84),
            QPointF(sz * 0.04, sz * 0.92),
        ])
        crust_border = QPen(QColor("#8c5218"), max(0.8, sz * 0.02))
        p.setPen(crust_border)
        p.setBrush(QColor("#c87d32"))
        p.drawPolygon(top_crust)
        p.drawPolygon(left_crust)

        # Colorful oval/round 100s & 1000s nonpareils
        rx_rad = max(1.25, sz * 0.046)
        ry_rad = max(1.05, sz * 0.036)
        p.setPen(Qt.PenStyle.NoPen)
        active_dots = sprinkle_specs[::2] if sz <= 20 else sprinkle_specs
        for rx, ry, col in active_dots:
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(sz * rx, sz * ry), rx_rad, ry_rad)
        p.end()
        icon.addPixmap(pix)

    try:
        ico_path = get_generated_images_dir().parent / "fairybread.ico"
        icon.pixmap(64, 64).save(str(ico_path), "ICO")
    except Exception:
        pass
    return icon


BUILTIN_THEMES: dict[str, dict[str, Any]] = {
    "dark": {
        "id": "dark",
        "name": "Midnight Dark (Default)",
        "bg_main": "#0d1117",
        "bg_sidebar": "#11161d",
        "bg_card": "#161b22",
        "bg_hover": "#1f242d",
        "border": "#21262d",
        "text_primary": "#e6edf3",
        "text_secondary": "#c9d1d9",
        "text_muted": "#6e7681",
        "user_bubble_bg": "#1c2128",
        "user_bubble_border": "#30363d",
        "user_bubble_text": "#f0f6fc",
        "send_bg": "#e6edf3",
        "send_fg": "#0d1117",
        "sprinkles": False,
    },
    "light": {
        "id": "light",
        "name": "Clean Daylight",
        "bg_main": "#ffffff",
        "bg_sidebar": "#f6f8fa",
        "bg_card": "#f3f4f6",
        "bg_hover": "#eaeef2",
        "border": "#d0d7de",
        "text_primary": "#1f2328",
        "text_secondary": "#24292f",
        "text_muted": "#57606a",
        "user_bubble_bg": "#ddf4ff",
        "user_bubble_border": "#54aeff",
        "user_bubble_text": "#0969da",
        "send_bg": "#0969da",
        "send_fg": "#ffffff",
        "sprinkles": False,
    },
    "fairybread": {
        "id": "fairybread",
        "name": "Fairybread (Iced VoVo & 100s & 1000s)",
        "bg_main": "#faf6f0",          # Soft Coconut Cream / Whipped White
        "bg_sidebar": "#f3e5c8",       # Warm Buttered Bread Crumb
        "bg_card": "#fce8ee",          # Iced VoVo Pink Fondant
        "bg_hover": "#f8d4e0",
        "border": "#dec49a",           # Toasted Golden Crust
        "text_primary": "#261c1a",     # Deep Cocoa / Espresso
        "text_secondary": "#3d2c29",
        "text_muted": "#7a5e58",
        "user_bubble_bg": "#fce4ec",   # Soft Iced VoVo Pink Pill
        "user_bubble_border": "#e091a9",
        "user_bubble_text": "#2b161b",
        "send_bg": "#d81b60",          # Raspberry Jam Accent
        "send_fg": "#ffffff",
        "sprinkles": True,
    },
}


def get_themes_dir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace" / "themes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_builtin_theme_files() -> Path:
    tdir = get_themes_dir()
    for tid, tdata in BUILTIN_THEMES.items():
        fp = tdir / f"{tid}.json"
        if not fp.exists():
            try:
                fp.write_text(json.dumps(tdata, indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
    return tdir


def _detect_windows_light_theme() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(val == 1)
    except Exception:
        return False


def list_available_themes() -> list[tuple[str, str]]:
    ensure_builtin_theme_files()
    out: list[tuple[str, str]] = [
        ("dark", "Midnight Dark (Default)"),
        ("fairybread", "Fairybread (Iced VoVo & 100s & 1000s)"),
        ("light", "Clean Daylight"),
        ("system", "Windows 11 System Auto"),
    ]
    seen = {k for k, _ in out}
    for fp in sorted(get_themes_dir().glob("*.json")):
        slug = fp.stem.lower()
        if slug in seen:
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            out.append((slug, str(data.get("name") or slug.capitalize())))
            seen.add(slug)
        except Exception:
            pass
    return out


def load_theme_dict(theme_id: str = "dark") -> dict[str, Any]:
    ensure_builtin_theme_files()
    clean = (theme_id or "dark").strip().lower()
    if clean == "system":
        clean = "light" if _detect_windows_light_theme() else "dark"
    base = dict(BUILTIN_THEMES.get(clean, BUILTIN_THEMES["dark"]))
    custom_fp = get_themes_dir() / f"{clean}.json"
    if custom_fp.exists():
        try:
            loaded = json.loads(custom_fp.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                base.update(loaded)
        except Exception:
            pass
    return base


def build_theme_stylesheet(theme_id: str = "dark") -> str:
    t = load_theme_dict(theme_id)
    bg_main = t["bg_main"]
    bg_side = t["bg_sidebar"]
    bg_card = t["bg_card"]
    bg_hover = t["bg_hover"]
    border = t["border"]
    txt = t["text_primary"]
    txt_sec = t["text_secondary"]
    txt_muted = t["text_muted"]
    send_bg = t["send_bg"]
    send_fg = t["send_fg"]
    return f"""
QMainWindow, QDialog {{ background: {bg_main}; color: {txt}; font-family: "Segoe UI Variable", "Segoe UI"; font-size: 13px; }}
QMenuBar {{ background: {bg_main}; color: {txt_sec}; border-bottom: 1px solid {border}; padding: 3px 8px; font-size: 12.5px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 5px; }}
QMenuBar::item:selected {{ background: {bg_card}; }}
QMenu {{ background: {bg_card}; color: {txt}; border: 1px solid {border}; padding: 4px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {bg_hover}; }}
QWidget#sidebar {{ background: {bg_side}; border-right: 1px solid {border}; }}
QWidget#chatPanel {{ background: {bg_main}; }}
QFrame#memoryPanel {{ background: {bg_side}; border-left: 1px solid {border}; }}
QFrame#loadedAIsBar {{ background: transparent; border: none; border-bottom: 1px solid {border}; border-radius: 0px; }}
QFrame#agentWorkbenchBar {{ background: transparent; border: none; }}
QFrame#idleBanner {{ background: {bg_side}; border: 1px solid {border}; border-radius: 8px; }}
QLabel#loadedAIsLabel {{ color: {txt_muted}; font-size: 12px; font-weight: 600; margin-right: 4px; }}
QLabel#sectionTitle {{ font-size: 15px; font-weight: 600; color: {txt}; }}
QLabel#sidebarHeading {{ color: {txt_muted}; font-size: 11.5px; font-weight: 600; }}
QLabel#muted {{ color: {txt_muted}; font-size: 11px; }}
QComboBox#profilePicker {{ background: {bg_card}; border: 1px solid {border}; border-radius: 6px; padding: 3px 8px; color: {txt_sec}; font-size: 12px; font-weight: 600; }}
QPushButton#pinnedHeaderButton, QPushButton#sectionToggleButton {{ background: transparent; border: none; border-radius: 6px; padding: 6px 8px; text-align: left; color: {txt_muted}; font-weight: 600; font-size: 12px; }}
QPushButton#pinnedHeaderButton:hover, QPushButton#sectionToggleButton:hover {{ background: {bg_hover}; color: {txt}; }}
QListWidget#pinnedList {{ background: transparent; border: none; border-left: 1px solid {border}; margin-left: 8px; padding-left: 4px; outline: none; }}
QListWidget#pinnedList::item, QListWidget#sidebarList::item {{ color: {txt_sec}; padding: 6px 8px; border-radius: 6px; margin-bottom: 2px; }}
QListWidget#sidebarList {{ background: transparent; border: none; padding: 2px; outline: none; }}
QListWidget#sidebarList::item:hover {{ background: {bg_hover}; }}
QListWidget#pinnedList::item:selected, QListWidget#sidebarList::item:selected {{ background: {bg_card}; color: {txt}; font-weight: 600; }}
QTextBrowser#chatView {{ background: {bg_main}; color: {txt}; border: none; padding: 4px 0px; font-size: 13px; }}
QFrame#composerCard {{ background: {bg_card}; border: 1px solid {border}; border-radius: 12px; }}
QTextEdit#composerInput {{ background: transparent; border: none; color: {txt}; font-size: 13px; padding: 2px; }}
QListWidget#attachmentList {{ background: {bg_side}; border: 1px solid {border}; border-radius: 6px; padding: 4px; }}
QLineEdit, QComboBox, QSpinBox, QListWidget, QTextBrowser, QTextEdit {{ background: {bg_card}; border: 1px solid {border}; border-radius: 6px; padding: 5px; color: {txt}; }}
QPushButton {{ background: {bg_card}; border: 1px solid {border}; border-radius: 6px; padding: 5px 10px; color: {txt_sec}; }}
QPushButton:hover {{ background: {bg_hover}; color: {txt}; }}
QPushButton#newConvoButton {{ background: {bg_card}; border: 1px solid {border}; border-radius: 8px; padding: 8px 12px; text-align: left; font-weight: 600; color: {txt}; }}
QPushButton#newConvoButton:hover {{ background: {bg_hover}; }}
QPushButton#settingsButton {{ background: transparent; border: none; text-align: left; color: {txt_muted}; padding: 7px 6px; border-radius: 6px; }}
QPushButton#settingsButton:hover {{ background: {bg_hover}; color: {txt}; }}
QPushButton#iconButton, QPushButton#topIconButton {{ background: transparent; border: 1px solid transparent; color: {txt_muted}; padding: 4px 7px; border-radius: 6px; font-size: 12px; }}
QPushButton#iconButton:hover, QPushButton#topIconButton:hover, QPushButton#topIconButton:checked {{ background: {bg_card}; border: 1px solid {border}; color: {txt}; }}
QPushButton#plusAttachButton {{ background: transparent; border: none; color: {txt_muted}; font-size: 16px; font-weight: 600; padding: 2px 6px; border-radius: 6px; }}
QPushButton#plusAttachButton:hover {{ background: {bg_hover}; color: {txt}; }}
QPushButton#aiPillButton {{ background: {bg_card}; border: 1px solid {border}; border-radius: 8px; padding: 4px 10px; font-size: 12px; font-weight: 600; color: {txt_sec}; }}
QPushButton#aiPillButton:hover {{ background: {bg_hover}; color: {txt}; }}
QPushButton#sendButton {{ background: {send_bg}; color: {send_fg}; font-size: 14px; font-weight: 700; border: none; border-radius: 15px; }}
QPushButton#sendButton:hover {{ opacity: 0.92; }}
QPushButton#sendButton:disabled {{ background: {border}; color: {txt_muted}; }}
QCheckBox {{ color: {txt_sec}; font-size: 12px; spacing: 5px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; }}
QCheckBox:checked {{ color: {txt}; font-weight: 600; }}
QSplitter::handle {{ background: {border}; width: 1px; }}
QScrollBar:vertical {{ background: {bg_main}; width: 12px; margin: 2px; border-radius: 6px; }}
QScrollBar::handle:vertical {{ background: {border}; min-height: 36px; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: {send_bg}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


STYLES = build_theme_stylesheet("dark")
