"""Palace Theme, Custom Vector Icons, Markdown Formatter, and AI Drawing/Image Engine."""

from __future__ import annotations

import base64
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from uuid import uuid4

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
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
    try:
        from palace_config import get_palace_data_root
        base = get_palace_data_root() / "generated_images"
    except Exception:
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


def mic_qicon(recording: bool = False) -> QIcon:
    """Clean vector microphone icon for voice dictation (Grey when idle, Red #ef4444 when recording)."""
    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor("#ef4444" if recording else NEUTRAL_GREY)
    painter.setPen(QPen(col, 1.4))
    painter.setBrush(col if recording else Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(5, 2, 6, 7, 3, 3)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(3, 4, 10, 7, 0, -180 * 16)
    painter.drawLine(8, 11, 8, 14)
    painter.drawLine(5, 14, 11, 14)
    painter.end()
    return QIcon(pix)


def voice_wave_qicon(active: bool = False) -> QIcon:
    """Live Voice Mode soundwave + sparkle icon (matching Antigravity's Live Voice Chat button)."""
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor("#22c55e" if active else "#0d1117")
    pen = QPen(col, 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    # 4 vertical soundwave bars
    painter.drawLine(3, 7, 3, 11)
    painter.drawLine(6, 4, 6, 14)
    painter.drawLine(9, 6, 9, 12)
    painter.drawLine(12, 8, 12, 10)
    # Small 4-point sparkle at top-right
    spark_pen = QPen(col, 1.3)
    spark_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(spark_pen)
    painter.drawLine(14, 3, 14, 7)
    painter.drawLine(12, 5, 16, 5)
    painter.end()
    return QIcon(pix)


# --- AI DRAWING & IMAGE GENERATION TOOLS ---

_SVG_FENCE_PATTERN = re.compile(
    r"```svg\s*(.*?)\s*```|\[DRAW_SVG(?:\s+title=\"([^\"]*)\")?\s*\](.*?)\[/DRAW_SVG\]",
    re.IGNORECASE | re.DOTALL,
)

_GENERATE_IMAGE_TAG_PATTERN = re.compile(
    r'\[GENERATE_IMAGE\s+((?:[^\]"]|"[^"]*")*)\]',
    re.IGNORECASE,
)

_ATTR_KV_PATTERN = re.compile(r'([a-zA-Z_]+)\s*=\s*"([^"]*)"')

_PALACE_SNAPSHOT_PATTERN = re.compile(
    r"\[PALACE_UI_SNAPSHOT(?:\s+path=\"([^\"]*)\")?(?:\s+title=\"([^\"]*)\")?\s*\]",
    re.IGNORECASE,
)

# Named social media, wallpaper, banner, and 300-DPI print presets
IMAGE_SIZE_PRESETS: dict[str, tuple[int, int, str]] = {
    "default": (1024, 1024, "1024×1024 Square HD"),
    "square": (1024, 1024, "1024×1024 Square HD"),
    "1:1": (1024, 1024, "1024×1024 Square HD"),
    "landscape": (1792, 1024, "1792×1024 Widescreen HD"),
    "wide": (1792, 1024, "1792×1024 Widescreen HD"),
    "16:9": (1920, 1080, "1920×1080 16:9 HD"),
    "portrait": (1024, 1792, "1024×1792 Portrait HD"),
    "vertical": (1024, 1792, "1024×1792 Portrait HD"),
    "9:16": (1080, 1920, "1080×1920 Vertical 9:16"),
    "youtube_banner": (2560, 1440, "2560×1440 YouTube Channel Banner"),
    "youtube_header": (2560, 1440, "2560×1440 YouTube Channel Banner"),
    "youtube_thumbnail": (1280, 720, "1280×720 YouTube Thumbnail"),
    "facebook_cover": (1920, 1080, "1920×1080 Facebook Page Cover"),
    "facebook_page": (1920, 1080, "1920×1080 Facebook Page Cover"),
    "facebook_pc_banner": (820, 312, "820×312 Facebook PC Cover"),
    "facebook_group": (1640, 856, "1640×856 Facebook Group Cover Banner"),
    "fb_group": (1640, 856, "1640×856 Facebook Group Cover Banner"),
    "desktop_wallpaper": (1920, 1080, "1920×1080 Desktop Wallpaper"),
    "pc_background": (1920, 1080, "1920×1080 PC Background"),
    "wallpaper_1440p": (2560, 1440, "2560×1440 QHD Wallpaper"),
    "wallpaper_4k": (3840, 2160, "3840×2160 4K UHD Wallpaper"),
    "phone_wallpaper": (1080, 1920, "1080×1920 Phone Wallpaper"),
    "story": (1080, 1920, "1080×1920 Social Story / Reel"),
    "instagram_post": (1080, 1080, "1080×1080 Instagram Square"),
    "instagram_portrait": (1080, 1350, "1080×1350 Instagram 4:5 Portrait"),
    "print_8x10": (2400, 3000, "2400×3000 (8×10 in @ 300 DPI Print)"),
    "print_10x8": (3000, 2400, "3000×2400 (10×8 in @ 300 DPI Print)"),
    "print_a4": (2480, 3508, "2480×3508 (A4 Portrait @ 300 DPI Print)"),
    "print_a4_landscape": (3508, 2480, "3508×2480 (A4 Landscape @ 300 DPI Print)"),
    "print_poster": (2700, 3600, "2700×3600 (18×24 Poster Ratio)"),
}


def resolve_target_image_size(size_spec: str = "", prompt: str = "") -> tuple[int, int, str]:
    """Resolve an explicit preset name, 'WxH' pixel string, 'WxHin' print string, or natural-language prompt hint
    into (target_width_px, target_height_px, human_label).
    """
    spec = (size_spec or "").strip().lower().replace(" ", "_")
    if spec in IMAGE_SIZE_PRESETS:
        return IMAGE_SIZE_PRESETS[spec]

    # Check explicit pixel dimensions like '2560x1440' or '1640×856'
    px_m = re.match(r"^(\d{2,4})\s*[x×]\s*(\d{2,4})(?:_?px)?$", spec)
    if px_m:
        w = max(128, min(4096, int(px_m.group(1))))
        h = max(128, min(4096, int(px_m.group(2))))
        return w, h, f"{w}×{h} px"

    # Check physical print inches like '8x10in' or '8x10_inches' at 300 DPI
    in_m = re.match(r"^(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)_?(?:in|inch|inches)$", spec)
    if in_m:
        in_w, in_h = float(in_m.group(1)), float(in_m.group(2))
        w = max(256, min(4096, int(round(in_w * 300))))
        h = max(256, min(4096, int(round(in_h * 300))))
        return w, h, f"{w}×{h} px ({in_w:g}×{in_h:g} in @ 300 DPI)"

    # Inspect natural-language prompt for platform/print hints when size_spec is omitted or generic
    p_low = f"{spec} {(prompt or '').lower()}"
    if "youtube" in p_low and ("banner" in p_low or "header" in p_low or "channel" in p_low):
        return IMAGE_SIZE_PRESETS["youtube_banner"]
    if "youtube" in p_low and "thumb" in p_low:
        return IMAGE_SIZE_PRESETS["youtube_thumbnail"]
    if "facebook" in p_low and "group" in p_low:
        return IMAGE_SIZE_PRESETS["facebook_group"]
    if "facebook" in p_low and ("page" in p_low or "cover" in p_low or "background" in p_low or "banner" in p_low):
        return IMAGE_SIZE_PRESETS["facebook_cover"]
    if any(k in p_low for k in ("desktop wallpaper", "pc background", "desktop background", "monitor wallpaper")):
        return IMAGE_SIZE_PRESETS["desktop_wallpaper"]
    if any(k in p_low for k in ("phone wallpaper", "mobile wallpaper", "tiktok", "instagram story", "reel")):
        return IMAGE_SIZE_PRESETS["phone_wallpaper"]
    if "8x10" in p_low or "8 x 10" in p_low:
        return IMAGE_SIZE_PRESETS["print_8x10"]
    if "a4" in p_low and "landscape" in p_low:
        return IMAGE_SIZE_PRESETS["print_a4_landscape"]
    if "a4" in p_low:
        return IMAGE_SIZE_PRESETS["print_a4"]
    if any(k in p_low for k in ("banner", "widescreen", "landscape", "header", "panoramic", "16:9")):
        return IMAGE_SIZE_PRESETS["landscape"]
    if any(k in p_low for k in ("portrait", "vertical", "poster", "tall", "9:16")):
        return IMAGE_SIZE_PRESETS["portrait"]

    return IMAGE_SIZE_PRESETS["default"]


def _parse_generate_image_attrs(attr_str: str) -> dict[str, str]:
    attrs = {k.lower(): v.strip() for k, v in _ATTR_KV_PATTERN.findall(attr_str or "")}
    return attrs


def _fit_and_save_target_png(raw_bytes: bytes, out_path: Path, target_w: int, target_h: int) -> bool:
    """Decode generated image bytes, perform aspect-preserving center crop + smooth Lanczos/bilinear scale
    to exact (target_w, target_h), stamp 300 DPI print metadata (11811 dots/meter), and save PNG.
    """
    qimg = QImage()
    if not qimg.loadFromData(raw_bytes):
        return False
    src_w, src_h = qimg.width(), qimg.height()
    if src_w <= 0 or src_h <= 0:
        return False

    if (src_w, src_h) != (target_w, target_h):
        target_ratio = target_w / float(target_h)
        src_ratio = src_w / float(src_h)
        if abs(src_ratio - target_ratio) > 0.02:
            if src_ratio > target_ratio:
                crop_w = int(round(src_h * target_ratio))
                crop_x = max(0, (src_w - crop_w) // 2)
                qimg = qimg.copy(crop_x, 0, crop_w, src_h)
            else:
                crop_h = int(round(src_w / target_ratio))
                crop_y = max(0, (src_h - crop_h) // 2)
                qimg = qimg.copy(0, crop_y, src_w, crop_h)
        qimg = qimg.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    # Stamp 300 DPI (11811 pixels per meter) so print apps respect exact physical dimensions
    qimg.setDotsPerMeterX(11811)
    qimg.setDotsPerMeterY(11811)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(f"{out_path.name}.{uuid4().hex[:6]}.tmp.png")
    try:
        if not qimg.save(str(tmp_path), "PNG"):
            return False
        os.replace(str(tmp_path), str(out_path))
        return True
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


_MARKDOWN_HTML_CACHE: OrderedDict[str, str] = OrderedDict()
_MARKDOWN_HTML_CACHE_MAX = 256
_RENDER_INDEX_LOCK = threading.Lock()


def _md_cache_get(key: str) -> str | None:
    val = _MARKDOWN_HTML_CACHE.get(key)
    if val is not None:
        _MARKDOWN_HTML_CACHE.move_to_end(key)
    return val


def _md_cache_put(key: str, val: str) -> None:
    _MARKDOWN_HTML_CACHE[key] = val
    _MARKDOWN_HTML_CACHE.move_to_end(key)
    while len(_MARKDOWN_HTML_CACHE) > _MARKDOWN_HTML_CACHE_MAX:
        _MARKDOWN_HTML_CACHE.popitem(last=False)


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

    # Respect viewBox aspect ratio (fixes widescreen viewBox being squished into square width/height)
    vb_w, vb_h = 0, 0
    vb_match = re.search(r'viewBox="(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"', clean_svg)
    if vb_match:
        vx, vy = float(vb_match.group(1)), float(vb_match.group(2))
        vw, vh = float(vb_match.group(3)), float(vb_match.group(4))
        vb_w, vb_h = int(round(vw)), int(round(vh))
        padded_vw = int(round(vw * 1.06))
        clean_svg = clean_svg.replace(vb_match.group(0), f'viewBox="{vx:g} {vy:g} {padded_vw} {vb_h}"', 1)

    # Instant SHA-1 disk cache check BEFORE touching QSvgRenderer or QPixmap!
    digest = hashlib.sha1((clean_svg + "_v3").encode("utf-8", errors="replace")).hexdigest()[:10]
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (title or "drawing").strip())[:24] or "drawing"
    out_path = get_generated_images_dir() / f"{safe_slug}_{digest}.png"
    if out_path.exists() and out_path.stat().st_size > 100:
        return out_path

    renderer = QSvgRenderer(QByteArray(clean_svg.encode("utf-8", errors="replace")))
    if not renderer.isValid():
        return None

    default_size = renderer.defaultSize()
    raw_w = vb_w if vb_w > 0 else (default_size.width() if default_size.width() > 0 else 860)
    raw_h = vb_h if vb_h > 0 else (default_size.height() if default_size.height() > 0 else 440)
    base_w = max(480, min(1600, raw_w))
    base_h = max(240, min(1200, int(round(base_w * (raw_h / float(max(1, raw_w)))))))

    target_w = min(920, max(640, base_w))
    target_h = max(200, int(round(base_h * (target_w / float(base_w)))))

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


def _save_engine_badge(out_path: Path, engine_label: str) -> None:
    try:
        out_path.with_suffix(".engine").write_text(engine_label, encoding="utf-8")
    except OSError:
        pass


def get_image_engine_badge(out_path: Path) -> str:
    try:
        badge_path = out_path.with_suffix(".engine")
        if badge_path.exists():
            return badge_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


_RECENT_RENDER_MAP: dict[str, Path] = {}


def _render_index_path() -> Path:
    return get_generated_images_dir() / "_render_index.json"


def _record_recent_render(base_key: str, out_path: Path) -> None:
    with _RENDER_INDEX_LOCK:
        _RECENT_RENDER_MAP[base_key] = out_path
        try:
            idx_p = _render_index_path()
            data: dict[str, str] = {}
            if idx_p.exists():
                try:
                    loaded = json.loads(idx_p.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = {str(k): str(v) for k, v in list(loaded.items())[-120:]}
                except Exception:
                    data = {}
            data[base_key] = str(out_path)
            idx_p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass


def _lookup_recent_render(base_key: str) -> Path | None:
    with _RENDER_INDEX_LOCK:
        cached = _RECENT_RENDER_MAP.get(base_key)
        if cached is not None and cached.exists() and cached.stat().st_size > 100:
            return cached
        try:
            idx_p = _render_index_path()
            if idx_p.exists():
                loaded = json.loads(idx_p.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and base_key in loaded:
                    cand = Path(loaded[base_key])
                    if cand.exists() and cand.stat().st_size > 100:
                        _RECENT_RENDER_MAP[base_key] = cand
                        return cand
        except Exception:
            pass
    return None


def extract_reference_image_paths(text: str, max_images: int = 2) -> list[Path]:
    """Extract existing local image file Paths from [ATTACHED_FILE_META kind="image" ...] markers."""
    if not text or "ATTACHED_FILE_META" not in text:
        return []
    try:
        from attachment_service import IMAGE_EXTENSIONS, get_uploaded_files_dir
    except Exception:
        return []
    up_dir = get_uploaded_files_dir()
    found: list[Path] = []
    seen: set[str] = set()
    matches = list(
        re.finditer(
            r'\[ATTACHED_FILE_META\s+kind="([^"]+)"\s+name="([^"]+)"\s+stored="([^"]*)"\]',
            text,
        )
    )
    for m in reversed(matches):
        kind, name, stored_name = m.group(1), m.group(2), m.group(3)
        if kind.lower() != "image":
            continue
        cand: Path | None = (up_dir / stored_name) if stored_name else None
        if (cand is None or not cand.is_file()) and name:
            p_name = Path(name)
            if p_name.suffix.lower() in IMAGE_EXTENSIONS:
                cands = sorted(
                    up_dir.glob(f"{p_name.stem[:48]}_*{p_name.suffix}"),
                    key=lambda p: p.stat().st_mtime if p.exists() else 0,
                    reverse=True,
                )
                if cands:
                    cand = cands[0]
        if cand is not None and cand.is_file():
            res = str(cand.resolve())
            if res not in seen:
                seen.add(res)
                found.append(cand)
                if len(found) >= max_images:
                    break
    return list(reversed(found))


def _encode_multipart_form(
    fields: dict[str, str],
    files: list[tuple[str, str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----FairybreadBoundary{uuid4().hex}"
    chunks: list[bytes] = []
    for k, v in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                f"{v}\r\n"
            ).encode("utf-8")
        )
    for field_name, filename, content_type, data in files:
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + data
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _is_permanent_image_error(err_text: str) -> bool:
    """Return True when an image generation error is non-retryable (auth, quota, 400/404, safety block)."""
    low = (err_text or "").lower()
    if not low.strip():
        return False
    permanent_tokens = (
        "missing ",
        "api key",
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "permission",
        "invalid_api_key",
        "404",
        "not found",
        "400",
        "invalid argument",
        "bad request",
        "safety",
        "policy",
        "content_policy",
        "blocked",
        "moderation",
        "prohibited",
        "quota",
        "insufficient_quota",
        "billing",
        "credit",
    )
    return any(tok in low for tok in permanent_tokens)


def generate_ai_image_to_png(
    prompt: str,
    title: str = "ai_image",
    size: str = "",
    quality: str = "high",
    style: str = "",
    *,
    model: str = "",
    allow_network: bool = False,
    reference_image_paths: list[Path | str] | None = None,
    primary_engine: str = "",
    fallback_engines: list[str] | None = None,
    primary_retry_delay_sec: float = 1.5,
) -> Path | None:
    """Return cached image or generate using configurable primary graphic AI + explicit fallback chain
    with optional native reference-image byte threading and 300 DPI atomic PNG save.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return None

    target_w, target_h, _size_label = resolve_target_image_size(size, clean_prompt)
    q_norm = (quality or "high").strip().lower()
    is_low_quality = q_norm in {"low", "draft", "fast", "standard", "medium"}

    valid_refs: list[Path] = []
    ref_hasher = hashlib.sha256()
    for rp in (reference_image_paths or [])[:2]:
        try:
            p_obj = Path(rp)
            if p_obj.is_file() and 0 < p_obj.stat().st_size <= 6 * 1024 * 1024:
                valid_refs.append(p_obj)
                ref_hasher.update(p_obj.read_bytes())
        except OSError:
            pass
    ref_hash = ref_hasher.hexdigest()[:12] if valid_refs else "noref"

    base_key = f"{clean_prompt}|{target_w}x{target_h}|{'std' if is_low_quality else 'hd'}"
    if not allow_network and not valid_refs:
        recent = _lookup_recent_render(base_key)
        if recent is not None:
            return recent

    cache_key = f"{base_key}|{ref_hash}|v3"
    digest = hashlib.sha1(cache_key.encode("utf-8", errors="replace")).hexdigest()[:10]
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (title or "image").strip())[:24] or "image"
    out_path = get_generated_images_dir() / f"{safe_slug}_{target_w}x{target_h}_{digest}.png"
    if out_path.exists() and out_path.stat().st_size > 100:
        return out_path
    if not allow_network:
        return None

    aspect = target_w / float(max(1, target_h))
    if aspect >= 1.55:
        gemini_aspect = "16:9"
        gpt_img_size = "1536x1024"
        flux_w, flux_h = 1344, 768
    elif aspect >= 1.15:
        gemini_aspect = "4:3"
        gpt_img_size = "1536x1024"
        flux_w, flux_h = 1344, 768
    elif aspect <= 0.65:
        gemini_aspect = "9:16"
        gpt_img_size = "1024x1536"
        flux_w, flux_h = 768, 1344
    elif aspect <= 0.88:
        gemini_aspect = "3:4"
        gpt_img_size = "1024x1536"
        flux_w, flux_h = 768, 1344
    else:
        gemini_aspect = "1:1"
        gpt_img_size = "1024x1024"
        flux_w, flux_h = 1024, 1024

    cs = CredentialStore()
    gem_key = cs.get_api_key("gemini")
    openai_key = cs.get_api_key("openai")
    req_model = (model or "").strip().lower()
    attempted_errors: list[str] = []

    def _mime_for(p: Path) -> str:
        ext = p.suffix.lower()
        if ext in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if ext == ".webp":
            return "image/webp"
        return "image/png"

    def _try_gemini_image(gem_model: str) -> tuple[Path | None, bool]:
        if not gem_key:
            attempted_errors.append(f"{gem_model}: missing gemini API key")
            return None, False
        parts: list[dict[str, Any]] = []
        used_ref = False
        for rp in valid_refs:
            try:
                raw_ref = rp.read_bytes()
                parts.append({
                    "inlineData": {
                        "mimeType": _mime_for(rp),
                        "data": base64.b64encode(raw_ref).decode("ascii"),
                    }
                })
                used_ref = True
            except OSError:
                pass
        parts.append({"text": clean_prompt})
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent?key={gem_key}"
            payload = json.dumps({
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                    "imageConfig": {"aspectRatio": gemini_aspect},
                },
            }).encode("utf-8")
            req = urllib_request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=75) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                for cand in body.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        inline = part.get("inlineData") or part.get("inline_data")
                        if inline and inline.get("data"):
                            raw_bytes = base64.b64decode(inline["data"])
                            if _fit_and_save_target_png(raw_bytes, out_path, target_w, target_h):
                                return out_path, used_ref
            attempted_errors.append(f"{gem_model}: response contained no image bytes")
        except Exception as exc:
            attempted_errors.append(f"{gem_model}: {exc}")
        return None, False

    def _try_openai_gpt_image_2() -> tuple[Path | None, bool]:
        if not openai_key:
            attempted_errors.append("gpt-image-2: missing openai API key")
            return None, False
        oai_q = "low" if q_norm in {"low", "draft", "fast"} else ("medium" if q_norm in {"medium", "standard"} else "high")
        if valid_refs:
            try:
                rp0 = valid_refs[0]
                body_bytes, ctype = _encode_multipart_form(
                    {
                        "model": "gpt-image-2",
                        "prompt": clean_prompt,
                        "n": "1",
                        "size": gpt_img_size,
                        "quality": oai_q,
                    },
                    [("image", rp0.name, _mime_for(rp0), rp0.read_bytes())],
                )
                req_ed = urllib_request.Request(
                    "https://api.openai.com/v1/images/edits",
                    data=body_bytes,
                    headers={
                        "Content-Type": ctype,
                        "Authorization": f"Bearer {openai_key}",
                    },
                    method="POST",
                )
                with urllib_request.urlopen(req_ed, timeout=115) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    item0 = body["data"][0]
                    b64_data = item0.get("b64_json")
                    if b64_data:
                        raw_bytes = base64.b64decode(b64_data)
                        if _fit_and_save_target_png(raw_bytes, out_path, target_w, target_h):
                            return out_path, True
            except Exception as exc:
                attempted_errors.append(f"gpt-image-2(edits): {exc}")
        try:
            payload = json.dumps({
                "model": "gpt-image-2",
                "prompt": clean_prompt,
                "n": 1,
                "size": gpt_img_size,
                "quality": oai_q,
            }).encode("utf-8")
            req = urllib_request.Request(
                "https://api.openai.com/v1/images/generations",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}",
                },
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=115) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                item0 = body["data"][0]
                b64_data = item0.get("b64_json")
                if b64_data:
                    raw_bytes = base64.b64decode(b64_data)
                    if _fit_and_save_target_png(raw_bytes, out_path, target_w, target_h):
                        return out_path, False
            attempted_errors.append("gpt-image-2: empty image payload")
        except Exception as exc:
            attempted_errors.append(f"gpt-image-2: {exc}")
        return None, False

    def _try_deepinfra_flux(flux_eng: str) -> tuple[Path | None, bool]:
        di_key = cs.get_api_key("deepinfra") or cs.get_api_key("qwen")
        if not di_key:
            attempted_errors.append(f"{flux_eng}: missing deepinfra/qwen key")
            return None, False
        try:
            use_schnell = ("schnell" in flux_eng) or (is_low_quality and "dev" not in flux_eng)
            flux_model = "black-forest-labs/FLUX-1-schnell" if use_schnell else "black-forest-labs/FLUX-1-dev"
            payload = json.dumps({
                "prompt": clean_prompt,
                "width": flux_w,
                "height": flux_h,
                "num_inference_steps": 4 if use_schnell else 28,
            }).encode("utf-8")
            req = urllib_request.Request(
                f"https://api.deepinfra.com/v1/inference/{flux_model}",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {di_key}",
                },
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                images_list = body.get("images") or []
                if images_list:
                    b64_str = str(images_list[0])
                    if "," in b64_str:
                        b64_str = b64_str.split(",", 1)[1]
                    raw_bytes = base64.b64decode(b64_str)
                    if _fit_and_save_target_png(raw_bytes, out_path, target_w, target_h):
                        return out_path, False
            attempted_errors.append(f"{flux_model}: empty images list")
        except Exception as exc:
            attempted_errors.append(f"{flux_eng}: {exc}")
        return None, False

    try:
        from palace_config import load_graphics_settings
        g_cfg = load_graphics_settings()
    except Exception:
        g_cfg = {
            "primary_image_engine": "gemini-3-pro-image",
            "draft_image_engine": "gemini-3.1-flash-image",
            "fallback_image_engines": ["gemini-3.1-flash-image", "gpt-image-2", "flux-1-dev"],
        }

    prim = (primary_engine or "").strip().lower()
    if not prim:
        if is_low_quality or "flash" in req_model:
            prim = str(g_cfg.get("draft_image_engine") or "gemini-3.1-flash-image").strip().lower()
        else:
            prim = str(g_cfg.get("primary_image_engine") or "gemini-3-pro-image").strip().lower()

    raw_chain: list[str] = []
    if req_model:
        raw_chain.append(req_model)
    if prim:
        raw_chain.append(prim)
    if fallback_engines is not None:
        raw_chain.extend(str(e).strip().lower() for e in fallback_engines if str(e).strip())
    else:
        raw_chain.extend(str(e).strip().lower() for e in (g_cfg.get("fallback_image_engines") or []) if str(e).strip())
        for default_eng in ("gemini-3.1-flash-image", "gemini-3-pro-image", "gpt-image-2", "flux-1-dev"):
            raw_chain.append(default_eng)

    engine_chain: list[str] = []
    for e in raw_chain:
        if e and e not in engine_chain:
            engine_chain.append(e)

    def _run_engine(eng: str) -> tuple[Path | None, bool, str]:
        if eng.startswith("gemini"):
            p, ref = _try_gemini_image(eng)
            return p, ref, eng
        if "gpt-image" in eng or eng.startswith("openai"):
            p, ref = _try_openai_gpt_image_2()
            return p, ref, "gpt-image-2"
        if "flux" in eng:
            p, ref = _try_deepinfra_flux(eng)
            b_lbl = "FLUX-1-schnell" if ("schnell" in eng or (is_low_quality and "dev" not in eng)) else "FLUX-1-dev"
            return p, ref, b_lbl
        p, ref = _try_gemini_image(eng)
        return p, ref, eng

    for idx, eng in enumerate(engine_chain):
        err_start = len(attempted_errors)
        res_path, used_ref, badge_label = _run_engine(eng)
        if res_path is None and idx == 0:
            new_errs = attempted_errors[err_start:]
            if not new_errs or not all(_is_permanent_image_error(e) for e in new_errs):
                if primary_retry_delay_sec and primary_retry_delay_sec > 0:
                    time.sleep(primary_retry_delay_sec)
                res_path, used_ref, badge_label = _run_engine(eng)

        if res_path is not None:
            billed_eng = badge_label
            if idx > 0:
                badge_label += " (fallback)"
            if used_ref:
                badge_label += " +ref"
            _save_engine_badge(out_path, badge_label)
            _record_recent_render(base_key, out_path)
            try:
                from cost_service import emit_image_cost
                emit_image_cost(billed_eng)
            except Exception:
                pass
            return res_path

    return None


def _unwrap_real_image_tags(text: str) -> str:
    """Unwrap real [GENERATE_IMAGE prompt="..." ...] tags that an AI accidentally placed inside
    ```text / ```markdown fences or standalone/inline backticks, while keeping short documentation
    examples (like `Use `[GENERATE_IMAGE prompt="example" title="demo"]` to draw.`) untouched as code.
    """
    if not text or "[GENERATE_IMAGE" not in text.upper():
        return text

    def _unwrap_fence(m: re.Match) -> str:
        inner = (m.group(3) or "").strip()
        while inner.startswith("`") and inner.endswith("`") and len(inner) > 2:
            inner = inner[1:-1].strip()
        if inner.upper().startswith("[GENERATE_IMAGE") and inner.endswith("]"):
            return f"\n{inner}\n"
        return m.group(0)

    # 1. Matches 3+ backticks fences with optional language and optional trailing spaces/newlines
    out = re.sub(
        r"(`{3,})([a-zA-Z0-9_-]*)[ \t]*\n?([ \t]*`?\[GENERATE_IMAGE\b.*?\]`?[ \t]*)\n?\1",
        _unwrap_fence,
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 2. Matches [GENERATE_IMAGE ...] enclosed in backticks anywhere as a real tag
    def _unwrap_backticked_tag(m: re.Match) -> str:
        tag = m.group(1)
        attrs = _parse_generate_image_attrs(tag)
        p = attrs.get("prompt", "").strip()
        if len(p) >= 10 and p.lower() not in {"example", "...", "rich visual description"}:
            return tag
        return m.group(0)

    out = re.sub(r'`+(\[GENERATE_IMAGE\s+(?:[^\]"`]|"[^"]*")*\])`+', _unwrap_backticked_tag, out, flags=re.IGNORECASE)
    return out


def _strip_code_spans_for_tag_scan(text: str) -> str:
    """Remove fenced code blocks and inline backtick spans so example tags inside code never fire API calls."""
    unwrapped = _unwrap_real_image_tags(text or "")
    without_fenced = re.sub(r"```.*?```", "", unwrapped, flags=re.DOTALL)
    return re.sub(r"`[^`\n]+`", "", without_fenced)


def neutralize_intermediate_image_tags(text: str) -> str:
    """Wrap bare [GENERATE_IMAGE ...] tags inside intermediate peer deliberation bubbles in inline backticks
    so only the final synthesized answer executes and renders the actual high-resolution image once.
    """
    if not text or "[GENERATE_IMAGE" not in text.upper():
        return text

    def _wrap_if_bare(m: re.Match) -> str:
        return f"`{m.group(0)}`"

    return _GENERATE_IMAGE_TAG_PATTERN.sub(_wrap_if_bare, text)


def prewarm_generated_images(
    content: str,
    *,
    reference_image_paths: list[Path | str] | None = None,
) -> list[Path]:
    """Run on background worker thread before UI render: pre-generates real (non-backticked)
    [GENERATE_IMAGE ...] tags concurrently with allow_network=True so UI rendering is instant.
    """
    scannable = _strip_code_spans_for_tag_scan(content or "")
    specs: list[tuple[str, str, str, str, str, str]] = []
    for match in _GENERATE_IMAGE_TAG_PATTERN.finditer(scannable):
        attrs = _parse_generate_image_attrs(match.group(1))
        img_prompt = attrs.get("prompt", "")
        if not img_prompt:
            continue
        specs.append((
            img_prompt,
            attrs.get("title") or img_prompt[:40],
            attrs.get("size") or attrs.get("preset") or "",
            attrs.get("quality") or "high",
            attrs.get("style") or "",
            attrs.get("model") or "",
        ))
    if not specs:
        return []

    def _run_one(sp: tuple[str, str, str, str, str, str]) -> Path | None:
        img_prompt, img_title, img_size, img_quality, img_style, img_model = sp
        return generate_ai_image_to_png(
            img_prompt,
            title=img_title,
            size=img_size,
            quality=img_quality,
            style=img_style,
            model=img_model,
            allow_network=True,
            reference_image_paths=reference_image_paths,
        )

    if len(specs) == 1:
        res = _run_one(specs[0])
        return [res] if res is not None else []

    with ThreadPoolExecutor(max_workers=min(3, len(specs))) as pool:
        results = list(pool.map(_run_one, specs))
    return [p for p in results if p is not None]


def format_markdown_and_drawings(content: str) -> str:
    """Convert AI response text into clean HTML with rendered SVG/Image pictures, headings, bold, and code blocks."""
    raw = content or ""
    if "[PALACE_UI_SNAPSHOT" not in raw and "[GENERATE_IMAGE" not in raw:
        cached = _md_cache_get(raw)
        if cached is not None:
            return cached
    rendered_images_html: list[str] = []
    code_blocks: list[str] = []
    inline_codes: list[str] = []

    # 1. Extract and render any ```svg ... ``` or [DRAW_SVG]...[/DRAW_SVG] blocks into real PNG images first
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
                f'<a href="open-img:{esc_path}" style="color:#3b82f6; text-decoration:none;">🔍 View Full Size</a> &nbsp;·&nbsp; '
                f'<a href="save-file:{esc_path}" style="color:#22c55e; text-decoration:none;">💾 Download / Save As…</a> &nbsp;·&nbsp; '
                f'<a href="reveal-file:{esc_path}" style="color:#58a6ff; text-decoration:none;">📂 Show in Folder</a> &nbsp;·&nbsp; '
                f'<a href="delete-file:{esc_path}" style="color:#f85149; text-decoration:none;">🗑 Delete</a>'
                f'</div>'
                f'<a href="open-img:{esc_path}"><img src="{file_url}" width="420"></a>'
                f'</td></tr></table>'
            )
            idx = len(rendered_images_html)
            rendered_images_html.append(img_block)
            return f"@@PALACE_IMG_{idx}@@"
        return match.group(0)

    processed = _SVG_FENCE_PATTERN.sub(_replace_svg, _unwrap_real_image_tags(raw))

    # 2. Extract fenced code blocks ```lang ... ``` and inline backticks `...` BEFORE matching [GENERATE_IMAGE]
    # so backticked documentation examples never trigger image rendering!
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

    def _replace_inline_code(match: re.Match) -> str:
        code_span = (
            f'<span style="background:#1c2128; color:#e6edf3; font-family:Consolas,monospace; '
            f'padding:1px 5px; border-radius:4px;">{html.escape(match.group(1))}</span>'
        )
        idx = len(inline_codes)
        inline_codes.append(code_span)
        return f"@@PALACE_INLINECODE_{idx}@@"

    processed = re.sub(r"`([^`\n]+)`", _replace_inline_code, processed)

    # 3. Extract and render any real [GENERATE_IMAGE ...] tags
    def _replace_gen_img(match: re.Match) -> str:
        attrs = _parse_generate_image_attrs(match.group(1))
        img_prompt = attrs.get("prompt", "")
        if not img_prompt:
            return match.group(0)
        img_title = attrs.get("title") or img_prompt[:40]
        img_size = attrs.get("size") or attrs.get("preset") or ""
        img_quality = attrs.get("quality") or "high"
        img_style = attrs.get("style") or ""
        img_model = attrs.get("model") or ""
        target_w, target_h, size_label = resolve_target_image_size(img_size, img_prompt)
        png_path = generate_ai_image_to_png(
            img_prompt,
            title=img_title,
            size=img_size,
            quality=img_quality,
            style=img_style,
            model=img_model,
            allow_network=False,
        )
        if png_path and png_path.exists():
            file_url = png_path.as_uri()
            esc_title = html.escape(img_title)
            esc_path = html.escape(str(png_path))
            engine_badge = get_image_engine_badge(png_path)
            meta_txt = f"{engine_badge} · {size_label}" if engine_badge else size_label
            esc_size = html.escape(meta_txt)
            is_draft_sample = (
                img_quality.lower() == "low"
                or max(target_w, target_h) <= 640
                or "draft" in img_title.lower()
            )
            if is_draft_sample:
                preview_w = min(360, max(220, int(260 * (target_w / float(max(1, target_h))))))
                from urllib import parse as _url_parse
                enc_draft = _url_parse.quote(img_title)
                promote_link = (
                    f'<a href="promote-draft:{enc_draft}" style="color:#a855f7; text-decoration:none; font-weight:700;">'
                    f'✨ Choose &amp; Render Full-Res Master</a> &nbsp;·&nbsp; '
                )
            else:
                preview_w = min(680, max(360, int(540 * (target_w / float(max(1, target_h))))))
                promote_link = ""
            img_block = (
                f'<table width="100%" cellspacing="0" cellpadding="10" style="margin:10px 0; background:#0d1117; border:1px solid #21262d;">'
                f'<tr><td>'
                f'<div style="color:#8b949e; font-size:11.5px; font-weight:600; margin-bottom:6px;">'
                f'🎨 {esc_title} &nbsp;<span style="color:#6e7681;">({esc_size})</span> &nbsp;·&nbsp; '
                f'{promote_link}'
                f'<a href="open-img:{esc_path}" style="color:#3b82f6; text-decoration:none;">🔍 View Full Size</a> &nbsp;·&nbsp; '
                f'<a href="save-file:{esc_path}" style="color:#22c55e; text-decoration:none;">💾 Download / Save As…</a> &nbsp;·&nbsp; '
                f'<a href="reveal-file:{esc_path}" style="color:#58a6ff; text-decoration:none;">📂 Show in Folder</a> &nbsp;·&nbsp; '
                f'<a href="delete-file:{esc_path}" style="color:#f85149; text-decoration:none;">🗑 Delete</a>'
                f'</div>'
                f'<a href="open-img:{esc_path}"><img src="{file_url}" width="{preview_w}"></a>'
                f'</td></tr></table>'
            )
            idx = len(rendered_images_html)
            rendered_images_html.append(img_block)
            return f"@@PALACE_IMG_{idx}@@"
        return f'[Image Request ({size_label}): "{img_prompt}"]'

    processed = _GENERATE_IMAGE_TAG_PATTERN.sub(_replace_gen_img, processed)

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
                f'<a href="open-img:{esc_path}" style="color:#3b82f6; text-decoration:none;">🔍 View Full Size</a> &nbsp;·&nbsp; '
                f'<a href="save-file:{esc_path}" style="color:#22c55e; text-decoration:none;">💾 Download / Save As…</a> &nbsp;·&nbsp; '
                f'<a href="reveal-file:{esc_path}" style="color:#58a6ff; text-decoration:none;">📂 Show in Folder</a>'
                f'</div>'
                f'<a href="open-img:{esc_path}"><img src="{file_url}" width="720"></a>'
                f'</td></tr></table>'
            )
            idx = len(rendered_images_html)
            rendered_images_html.append(img_block)
            return f"@@PALACE_IMG_{idx}@@"
        return "[Palace UI Snapshot Ready]"

    processed = _PALACE_SNAPSHOT_PATTERN.sub(_replace_ui_snap, processed)

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

    # Restore inline code, fenced code blocks, and rendered images
    for idx, icblock in enumerate(inline_codes):
        formatted = formatted.replace(f"@@PALACE_INLINECODE_{idx}@@", icblock)
    for idx, cblock in enumerate(code_blocks):
        formatted = formatted.replace(f"@@PALACE_CODE_{idx}@@", cblock)
    for idx, iblock in enumerate(rendered_images_html):
        formatted = formatted.replace(f"@@PALACE_IMG_{idx}@@", iblock)

    _md_cache_put(raw, formatted)
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
    "winamp_1999": {
        "id": "winamp_1999",
        "name": "Winamp Classic 1999 (2.x LED)",
        "bg_main": "#121612",
        "bg_sidebar": "#0a0d0a",
        "bg_card": "#1b241b",
        "bg_hover": "#253325",
        "border": "#375237",
        "text_primary": "#00ff41",
        "text_secondary": "#b8e6b8",
        "text_muted": "#6b9e6b",
        "user_bubble_bg": "#1e2e1e",
        "user_bubble_border": "#ffb000",
        "user_bubble_text": "#ffdf80",
        "send_bg": "#ffb000",
        "send_fg": "#0a0d0a",
        "sprinkles": False,
    },
    "cyberpunk_2077": {
        "id": "cyberpunk_2077",
        "name": "Cyberpunk Night City",
        "bg_main": "#0b0c14",
        "bg_sidebar": "#07080d",
        "bg_card": "#141726",
        "bg_hover": "#1e2238",
        "border": "#00f0ff",
        "text_primary": "#fcee0a",
        "text_secondary": "#e0f7fa",
        "text_muted": "#00b8d4",
        "user_bubble_bg": "#290924",
        "user_bubble_border": "#ff0055",
        "user_bubble_text": "#ffffff",
        "send_bg": "#ff0055",
        "send_fg": "#ffffff",
        "sprinkles": False,
    },
    "matrix_crt": {
        "id": "matrix_crt",
        "name": "Matrix Phosphor (CRT Terminal)",
        "bg_main": "#050805",
        "bg_sidebar": "#020402",
        "bg_card": "#0b140b",
        "bg_hover": "#122112",
        "border": "#194d19",
        "text_primary": "#39ff14",
        "text_secondary": "#76ff7a",
        "text_muted": "#2e8b57",
        "user_bubble_bg": "#0d1f0d",
        "user_bubble_border": "#39ff14",
        "user_bubble_text": "#ccffcc",
        "send_bg": "#39ff14",
        "send_fg": "#020402",
        "sprinkles": False,
    },
    "dracula_pro": {
        "id": "dracula_pro",
        "name": "Dracula Pro",
        "bg_main": "#282a36",
        "bg_sidebar": "#1e1f29",
        "bg_card": "#343746",
        "bg_hover": "#44475a",
        "border": "#6272a4",
        "text_primary": "#f8f8f2",
        "text_secondary": "#e2e2dc",
        "text_muted": "#9ea8c7",
        "user_bubble_bg": "#3b2d4a",
        "user_bubble_border": "#bd93f9",
        "user_bubble_text": "#f8f8f2",
        "send_bg": "#ff79c6",
        "send_fg": "#1e1f29",
        "sprinkles": False,
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
        ("winamp_1999", "Winamp Classic 1999 (2.x LED)"),
        ("cyberpunk_2077", "Cyberpunk Night City"),
        ("matrix_crt", "Matrix Phosphor (CRT Terminal)"),
        ("dracula_pro", "Dracula Pro"),
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
QToolTip {{ background: {bg_card}; color: {txt}; border: 1px solid {border}; border-radius: 6px; padding: 6px 10px; font-size: 12px; }}
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
QListWidget#pinnedList::item, QListWidget#sidebarList::item {{ color: {txt_sec}; padding: 2px 6px; border-radius: 5px; margin-bottom: 0px; }}
QListWidget#sidebarList {{ background: transparent; border: none; padding: 1px; outline: none; font-size: 12.5px; }}
QListWidget#sidebarList::item:hover {{ background: {bg_hover}; }}
QListWidget#pinnedList::item:selected, QListWidget#sidebarList::item:selected {{ background: {bg_card}; color: {txt}; font-weight: 600; }}
QTextBrowser#chatView {{ background: {bg_main}; color: {txt}; border: none; padding: 4px 0px; font-size: 13px; }}
QFrame#composerCard {{ background: {bg_card}; border: 1px solid {border}; border-radius: 12px; }}
QTextEdit#composerInput {{ background: transparent; border: none; color: {txt}; font-size: 13px; padding: 2px; }}
QListWidget#attachmentList {{ background: {bg_side}; border: 1px solid {border}; border-radius: 6px; padding: 4px; }}
QLineEdit, QComboBox, QSpinBox, QListWidget, QTextBrowser, QTextEdit {{ background: {bg_card}; border: 1px solid {border}; border-radius: 6px; padding: 5px 8px; color: {txt}; selection-background-color: #1f4b8e; selection-color: #ffffff; }}
QComboBox QAbstractItemView {{ background: {bg_card}; color: {txt}; border: 1px solid {border}; selection-background-color: #1f4b8e; selection-color: #ffffff; padding: 4px; outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 4px 10px; }}
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
