"""Palace desktop interface. Provider and memory work remains in core services."""
import argparse
from datetime import datetime
import hashlib
import html
import inspect
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any
import webbrowser

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QObject, QPoint, QRect, QRectF, QSize, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QBrush, QCloseEvent, QColor, QFont, QFontMetrics, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QTextCursor
try:
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
except Exception:
    QLocalServer = None
    QLocalSocket = None
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QSystemTrayIcon, QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from access_policy import (
    PERMISSION_MODE_META,
    PERMISSION_MODES,
    list_local_drives,
    load_access_permissions,
    normalize_exclusion_path_str,
    normalize_permission_mode,
    save_access_permissions,
)

from attachment_service import (
    MAX_TOTAL_CHARS,
    attachment_from_image_bytes,
    compose_question,
    extract_attachment,
)
from credential_store import CredentialStore
from idle_service import IdleMailboxStore, IdleMemoryStore, IdleSessionManager, MAX_IDLE_MEMORY_BYTES
from memory_proposal_service import MemoryProposalService
from memory_service import MemoryService
from palace_config import (
    CONFIG_PATH,
    DEFAULT_AI_SQUADS,
    IDLE_CREDIT_LIMIT_CHOICES,
    IDLE_DURATION_CHOICES,
    IDLE_TOKEN_LIMIT_CHOICES,
    IS_DEVELOPER_EDITION,
    PROVIDER_CATALOG,
    load_agent_defaults,
    load_ai_squads,
    load_idle_settings,
    load_mission_ethics,
    load_personalization_settings,
    load_provider_configs,
    load_tool_settings,
    load_ui_settings,
    save_agent_defaults,
    save_ai_squads,
    save_idle_settings,
    save_mission_ethics,
    save_personalization_settings,
    save_provider_config,
    save_tool_settings,
    save_ui_settings,
    set_provider_enabled,
)
from session_store import SessionStore


class _NoScrollWheelFilter(QObject):
    """Prevent mouse-wheel scrolling inside a QScrollArea from accidentally changing unfocused combos/sliders."""

    def eventFilter(self, obj, event):
        if event is not None and event.type() == QEvent.Type.Wheel:
            try:
                if hasattr(obj, 'hasFocus') and not obj.hasFocus():
                    event.ignore()
                    return True
            except Exception:
                pass
        return super().eventFilter(obj, event)


def format_chat_timestamp(raw_iso: str | None) -> str:
    """Format ISO timestamp to human-friendly ChatGPT-style display ('Today 8:51 AM', etc.)."""
    if not raw_iso:
        return ""
    try:
        from datetime import datetime
        clean = str(raw_iso).replace('Z', '')
        if '.' in clean:
            clean = clean.split('.')[0]
        dt = datetime.fromisoformat(clean)
        now = datetime.now()
        time_str = dt.strftime("%I:%M %p").lstrip("0")
        if dt.date() == now.date():
            return f"Today {time_str}"
        elif (now.date() - dt.date()).days == 1:
            return f"Yesterday {time_str}"
        else:
            return dt.strftime("%b %d, ") + time_str
    except Exception:
        return str(raw_iso)[:16].replace('T', ' ')


def format_time_only(raw_iso: str | None) -> str:
    """Format ISO timestamp to time only ('12:59 PM') for message bubble footers, matching ChatGPT exactly."""
    if not raw_iso:
        return ""
    try:
        from datetime import datetime
        clean = str(raw_iso).replace('Z', '')
        if '.' in clean:
            clean = clean.split('.')[0]
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return str(raw_iso)[11:16]


def _is_light_theme(t_dict: dict) -> bool:
    """Return True when theme background luminance indicates a light theme."""
    hx = str((t_dict or {}).get('bg_main') or '#0b0d10').strip().lstrip('#')
    if len(hx) == 6:
        try:
            r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
            return (r + g + b) > 380
        except ValueError:
            pass
    return False


from palace_theme import (
    AI_BG_COLORS,
    AI_COLORS,
    AI_DISPLAY_NAMES,
    AI_ICONS,
    NEUTRAL_GREY,
    STYLES,
    build_theme_stylesheet,
    code_shield_qicon,
    council_qicon,
    fairybread_app_qicon,
    folder_grey_qicon,
    format_ai_badge_html,
    format_markdown_and_drawings,
    get_themes_dir,
    idle_moon_qicon,
    list_available_themes,
    load_theme_dict,
    mail_grey_qicon,
    mic_qicon,
    no_history_qicon,
    provider_bg_color,
    provider_color,
    provider_display_name,
    provider_icon,
    provider_qicon,
    provider_token_qicon,
    tangent_qicon,
    voice_wave_qicon,
)

if os.name == 'nt':
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Fairybread.Palace.Desktop.1')
    except Exception:
        pass


_PARSED_TS_CACHE: dict[str, datetime] = {}


def _parse_local_naive_dt(ts_raw) -> datetime:
    raw_s = str(ts_raw).strip()
    cached = _PARSED_TS_CACHE.get(raw_s)
    if cached is not None:
        return cached
    norm_s = raw_s
    if norm_s.endswith('Z') or norm_s.endswith('z'):
        norm_s = norm_s[:-1] + '+00:00'
    dt_val = datetime.fromisoformat(norm_s)
    if dt_val.tzinfo is not None:
        dt_val = dt_val.astimezone().replace(tzinfo=None)
    if len(_PARSED_TS_CACHE) >= 1024:
        _PARSED_TS_CACHE.clear()
    _PARSED_TS_CACHE[raw_s] = dt_val
    return dt_val


SIDEBAR_META_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class SidebarSessionList(QListWidget):
    """QListWidget supporting Antigravity-style hover controls, working spinner, drag reordering, and Project drops."""
    sessions_reordered = Signal(object)
    item_menu_requested = Signal(object, QPoint)
    session_pin_toggled = Signal(str)
    project_new_session_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._hovered_row: int = -1
        self._hovered_pos: QPoint = QPoint(-1, -1)
        self.working_session_id: str | None = None
        self.working_pulse_step: int = 0

    def set_working_state(self, session_id: str | None, pulse_step: int = 0) -> None:
        clean_sid = str(session_id) if session_id else None
        step = int(pulse_step or 0)
        if clean_sid != self.working_session_id or step != self.working_pulse_step:
            self.working_session_id = clean_sid
            self.working_pulse_step = step
            self.viewport().update()

    @staticmethod
    def action_rects_for_item(item_rect: QRect, meta: dict | None) -> dict[str, QRect]:
        if not isinstance(meta, dict) or not item_rect.isValid():
            return {}
        cy = item_rect.center().y()
        kind = meta.get('kind')
        if kind == 'session':
            return {
                'menu_rect': QRect(item_rect.right() - 24, cy - 10, 20, 20),
                'pin_rect': QRect(item_rect.right() - 46, cy - 10, 20, 20),
            }
        if kind == 'project' and meta.get('id'):
            return {
                'add_rect': QRect(item_rect.right() - 24, cy - 10, 20, 20),
                'menu_rect': QRect(item_rect.right() - 46, cy - 10, 20, 20),
            }
        return {}

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        item = self.itemAt(pos)
        new_row = self.row(item) if item is not None else -1
        if new_row != self._hovered_row or pos != self._hovered_pos:
            self._hovered_row = new_row
            self._hovered_pos = pos
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hovered_row != -1 or self._hovered_pos != QPoint(-1, -1):
            self._hovered_row = -1
            self._hovered_pos = QPoint(-1, -1)
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            item = self.itemAt(pos)
            if item is not None:
                meta = item.data(SIDEBAR_META_ROLE)
                if isinstance(meta, dict):
                    kind = meta.get('kind')
                    row_idx = self.row(item)
                    show_actions = (row_idx == self._hovered_row) or (
                        kind == 'project' and (bool(meta.get('selected')) or item.isSelected())
                    )
                    if show_actions:
                        rects = self.action_rects_for_item(self.visualItemRect(item), meta)
                        menu_rect = rects.get('menu_rect')
                        if menu_rect is not None and menu_rect.contains(pos):
                            self.item_menu_requested.emit(item, menu_rect.bottomLeft())
                            event.accept()
                            return
                        pin_rect = rects.get('pin_rect')
                        if kind == 'session' and pin_rect is not None and pin_rect.contains(pos):
                            self.session_pin_toggled.emit(str(meta.get('id') or ''))
                            event.accept()
                            return
                        add_rect = rects.get('add_rect')
                        if kind == 'project' and add_rect is not None and add_rect.contains(pos):
                            self.project_new_session_requested.emit(str(meta.get('id') or ''))
                            event.accept()
                            return
        super().mousePressEvent(event)

    def dropEvent(self, event):
        dragged_item = self.currentItem()
        dragged_key = str(dragged_item.data(Qt.ItemDataRole.UserRole) or '') if dragged_item else ''
        if not dragged_key or dragged_key.startswith('proj:') or dragged_key == 'archived_toggle':
            event.ignore()
            return

        target_item = self.itemAt(event.position().toPoint())
        target_key = str(target_item.data(Qt.ItemDataRole.UserRole) or '') if target_item else ''

        # If dropped directly onto a Project header (or "No conversations yet" under a project),
        # assign that project immediately before letting InternalMove reorder the list.
        explicit_proj: str | None = None
        has_explicit_proj = False
        if target_key.startswith('proj:'):
            explicit_proj = target_key.split(':', 1)[1] or None
            has_explicit_proj = True

        super().dropEvent(event)

        # Walk the list top-to-bottom to infer each conversation's new project_id and order
        ordered: list[tuple[str, str | None]] = []
        active_proj: str | None = None
        for i in range(self.count()):
            it = self.item(i)
            if it is None:
                continue
            k = str(it.data(Qt.ItemDataRole.UserRole) or '')
            if k == 'archived_toggle':
                continue
            if k.startswith('proj:'):
                p_val = k.split(':', 1)[1]
                active_proj = p_val if p_val else None
            elif k:
                assigned = explicit_proj if (has_explicit_proj and k == dragged_key) else active_proj
                ordered.append((k, assigned))

        self.sessions_reordered.emit(ordered)


class SidebarItemDelegate(QStyledItemDelegate):
    """Paints Antigravity-style sidebar rows: hover pin + three-dots, 2x2 working spinner, blue unread dot, and age."""

    @staticmethod
    def _paint_btn_bg(painter: QPainter, rect: QRect, is_btn_hovered: bool) -> None:
        if not is_btn_hovered:
            return
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 26))
        painter.drawRoundedRect(QRectF(rect), 4.0, 4.0)
        painter.restore()

    @staticmethod
    def _draw_three_dots(painter: QPainter, rect: QRect, color: QColor, hovered: bool) -> None:
        SidebarItemDelegate._paint_btn_bg(painter, rect, hovered)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        cx = float(rect.center().x())
        cy = float(rect.center().y())
        for dy in (-4.0, 0.0, 4.0):
            painter.drawEllipse(QRectF(cx - 1.35, cy + dy - 1.35, 2.7, 2.7))
        painter.restore()

    @staticmethod
    def _draw_plus(painter: QPainter, rect: QRect, color: QColor, hovered: bool) -> None:
        SidebarItemDelegate._paint_btn_bg(painter, rect, hovered)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        cx = rect.center().x()
        cy = rect.center().y()
        painter.drawLine(cx - 4, cy, cx + 4, cy)
        painter.drawLine(cx, cy - 4, cx, cy + 4)
        painter.restore()

    @staticmethod
    def _draw_pin(painter: QPainter, rect: QRect, is_pinned: bool, base_col: QColor, active_col: QColor, hovered: bool) -> None:
        SidebarItemDelegate._paint_btn_bg(painter, rect, hovered)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = active_col if is_pinned else base_col
        pen = QPen(col, 1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = float(rect.center().x())
        cy = float(rect.center().y())
        # Compact pushpin silhouette rotated 45 deg
        if is_pinned:
            painter.setBrush(QBrush(col))
        painter.drawLine(QRectF(cx - 1.0, cy - 4.0, 5.0, 0.0).topLeft(), QRectF(cx - 1.0, cy - 4.0, 5.0, 0.0).topRight())
        painter.drawLine(int(round(cx)), int(round(cy - 4)), int(round(cx - 2)), int(round(cy + 1)))
        painter.drawLine(int(round(cx + 3)), int(round(cy - 4)), int(round(cx + 2)), int(round(cy + 1)))
        painter.drawLine(int(round(cx - 3.5)), int(round(cy + 1)), int(round(cx + 3.5)), int(round(cy + 1)))
        painter.drawLine(int(round(cx)), int(round(cy + 1)), int(round(cx - 1)), int(round(cy + 5)))
        painter.restore()

    @staticmethod
    def _draw_working_spinner(painter: QPainter, cx: float, cy: float, pulse_step: int, color: QColor) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        offsets = ((-2.6, -2.6), (2.6, -2.6), (2.6, 2.6), (-2.6, 2.6))
        alphas = (255, 175, 95, 55)
        head = int(pulse_step or 0) % 4
        for idx, (dx, dy) in enumerate(offsets):
            rel = (idx - head) % 4
            c = QColor(color)
            c.setAlpha(alphas[rel])
            painter.setBrush(c)
            painter.drawEllipse(QRectF(cx + dx - 1.7, cy + dy - 1.7, 3.4, 3.4))
        painter.restore()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        meta = index.data(SIDEBAR_META_ROLE)
        if not isinstance(meta, dict) or meta.get('kind') not in {'session', 'project', 'archived_header'}:
            super().paint(painter, option, index)
            return

        view = self.parent()
        win = view.window() if view is not None else None
        theme_id = getattr(win, 'active_theme', 'dark') if win is not None else 'dark'
        t_dict = load_theme_dict(theme_id)
        bg_hover = QColor(str(t_dict.get('bg_hover') or '#1b2028'))
        bg_card = QColor(str(t_dict.get('bg_card') or '#21262d'))
        txt_primary = QColor(str(t_dict.get('text_primary') or '#f0f6fc'))
        txt_sec = QColor(str(t_dict.get('text_secondary') or '#8b949e'))
        txt_muted = QColor('#6e7681')
        accent_blue = QColor('#3b82f6')
        accent_pin = QColor('#58a6ff')

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        hovered_row = getattr(view, '_hovered_row', -1) if view is not None else -1
        hovered_pos = getattr(view, '_hovered_pos', QPoint(-1, -1)) if view is not None else QPoint(-1, -1)
        is_hovered = (index.row() == hovered_row)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected) or bool(meta.get('selected'))

        row_rect = option.rect.adjusted(2, 1, -2, -1)
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg_card)
            painter.drawRoundedRect(QRectF(row_rect), 5.0, 5.0)
        elif is_hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg_hover)
            painter.drawRoundedRect(QRectF(row_rect), 5.0, 5.0)

        kind = meta.get('kind')
        cy = option.rect.center().y()

        if kind == 'archived_header':
            font = QFont(option.font)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(txt_muted)
            glyph = '⌄' if meta.get('expanded') else '›'
            lbl = f"{glyph}  Archived ({int(meta.get('count') or 0)})"
            text_rect = option.rect.adjusted(8, 0, -8, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lbl)
            painter.restore()
            return

        if kind == 'project':
            has_id = bool(meta.get('id'))
            icon_rect = QRect(option.rect.left() + 6, cy - 7, 15, 15)
            folder_grey_qicon(bool(meta.get('selected'))).paint(painter, icon_rect)

            right_reserve = 10
            if has_id and (is_hovered or is_selected):
                rects = SidebarSessionList.action_rects_for_item(option.rect, meta)
                m_rect = rects.get('menu_rect', QRect())
                a_rect = rects.get('add_rect', QRect())
                self._draw_three_dots(painter, m_rect, txt_primary if is_hovered else txt_sec, m_rect.contains(hovered_pos))
                self._draw_plus(painter, a_rect, txt_primary if is_hovered else txt_sec, a_rect.contains(hovered_pos))
                right_reserve = 52

            font = QFont(option.font)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(txt_primary if (is_selected or is_hovered) else txt_sec)
            fm = QFontMetrics(font)
            text_rect = option.rect.adjusted(26, 0, -right_reserve, 0)
            elided = fm.elidedText(str(meta.get('title') or ''), Qt.TextElideMode.ElideRight, max(10, text_rect.width()))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
            painter.restore()
            return

        # kind == 'session'
        sid = str(meta.get('id') or '')
        working_sid = getattr(view, 'working_session_id', None) if view is not None else None
        pulse_step = getattr(view, 'working_pulse_step', 0) if view is not None else 0
        is_working = bool(sid and working_sid and sid == working_sid)
        is_unread = bool(meta.get('unread', False))
        is_pinned = bool(meta.get('pinned', False))
        is_archived = bool(meta.get('archived', False))
        age = str(meta.get('age') or '').strip()

        rects = SidebarSessionList.action_rects_for_item(option.rect, meta)
        menu_rect = rects.get('menu_rect', QRect())
        pin_rect = rects.get('pin_rect', QRect())

        if is_hovered:
            self._draw_pin(
                painter,
                pin_rect,
                is_pinned,
                txt_sec,
                accent_pin,
                pin_rect.contains(hovered_pos),
            )
            self._draw_three_dots(painter, menu_rect, txt_primary, menu_rect.contains(hovered_pos))
            if is_working:
                self._draw_working_spinner(painter, float(pin_rect.left() - 10), float(cy), pulse_step, accent_pin)
                right_reserve = 68
            else:
                right_reserve = 52
        elif is_working:
            c_pt = menu_rect.center()
            self._draw_working_spinner(painter, float(c_pt.x()), float(cy), pulse_step, accent_pin)
            right_reserve = 32
        elif is_unread:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent_blue)
            painter.drawEllipse(QRectF(option.rect.right() - 17.5, cy - 3.5, 7.0, 7.0))
            right_reserve = 28
        elif age:
            age_font = QFont(option.font)
            age_font.setPointSize(max(7, option.font.pointSize() - 1) if option.font.pointSize() > 0 else 8)
            painter.setFont(age_font)
            painter.setPen(txt_muted)
            age_fm = QFontMetrics(age_font)
            age_w = age_fm.horizontalAdvance(age)
            age_rect = QRect(option.rect.right() - 8 - age_w, option.rect.top(), age_w + 2, option.rect.height())
            painter.drawText(age_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, age)
            right_reserve = age_w + 16
        else:
            right_reserve = 10

        left_pad = 16 if meta.get('indented') else 8
        title_rect = option.rect.adjusted(left_pad, 0, -right_reserve, 0)
        title_font = QFont(option.font)
        if is_selected or is_unread:
            title_font.setBold(True)
        elif is_archived:
            title_font.setItalic(True)
        painter.setFont(title_font)
        if is_selected or is_unread or is_hovered:
            painter.setPen(txt_primary)
        elif is_archived:
            painter.setPen(txt_muted)
        else:
            painter.setPen(txt_sec)
        title_fm = QFontMetrics(title_font)
        elided_title = title_fm.elidedText(str(meta.get('title') or ''), Qt.TextElideMode.ElideRight, max(10, title_rect.width()))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)
        painter.restore()


class ResponsiveBarLabel(QLabel):
    """QLabel for the bottom workbench bar that remembers its full un-elided text,
    exposes plain text length for responsive width calculations, and triggers bar relayout on setText.
    """

    def __init__(self, text: str = '', on_change=None, parent=None):
        super().__init__(text, parent)
        self._raw_text = str(text or '')
        self._on_change = on_change
        self._updating_elide = False

    def setText(self, text: str):
        if self._updating_elide:
            super().setText(text)
            return
        self._raw_text = str(text or '')
        plain = self.plain_text()
        if plain:
            self.setToolTip(plain)
        super().setText(self._raw_text)
        if callable(self._on_change):
            self._on_change()

    def raw_text(self) -> str:
        return self._raw_text

    def plain_text(self) -> str:
        if '<' in self._raw_text and '>' in self._raw_text:
            stripped = re.sub(r'<[^>]+>', '', self._raw_text)
            return html.unescape(stripped).strip()
        return self._raw_text.strip()

    def apply_elided_width(self, max_px: int):
        """If plain text exceeds max_px, elide cleanly with '…' while keeping full raw_text in tooltip."""
        if '<' in self._raw_text and '>' in self._raw_text:
            self.setMaximumWidth(max(80, int(max_px)))
            return
        self.setMaximumWidth(16777215)
        fm = self.fontMetrics()
        elided = fm.elidedText(self._raw_text, Qt.TextElideMode.ElideRight, max(60, int(max_px)))
        self._updating_elide = True
        try:
            super().setText(elided)
        finally:
            self._updating_elide = False


class ChatBrowser(QTextBrowser):
    """QTextBrowser subclass that paints true anti-aliased 14px rounded pills behind user prompt tables
    (working around Qt QTextDocument's CSS border-radius limitation while keeping text 100% selectable).
    """
    anchor_action_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.user_bubble_bg = '#1c2128'
        self.user_bubble_border = '#30363d'
        self.sprinkles_enabled = False

    def contextMenuEvent(self, event):
        import urllib.parse
        anchor = self.anchorAt(event.pos())
        if anchor:
            decoded = urllib.parse.unquote(anchor)
            for prefix in ('open-img:', 'save-file:', 'reveal-file:', 'delete-file:'):
                if decoded.startswith(prefix):
                    file_path = decoded.split(prefix, 1)[1]
                    menu = QMenu(self)
                    p_obj = Path(file_path)
                    is_img = p_obj.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
                    if is_img:
                        view_act = menu.addAction('🔍 View Full-Size Image')
                        view_act.triggered.connect(lambda: self.anchor_action_requested.emit(f'open-img:{file_path}'))
                    dl_act = menu.addAction('💾 Download / Save As…')
                    dl_act.triggered.connect(lambda: self.anchor_action_requested.emit(f'save-file:{file_path}'))
                    if is_img and p_obj.exists():
                        cp_act = menu.addAction('📋 Copy Image to Clipboard')
                        cp_act.triggered.connect(lambda: QApplication.clipboard().setPixmap(QPixmap(str(p_obj))))
                    rev_act = menu.addAction('📂 Show in File Explorer')
                    rev_act.triggered.connect(lambda: self.anchor_action_requested.emit(f'reveal-file:{file_path}'))
                    menu.addSeparator()
                    del_act = menu.addAction('🗑 Delete from Fairybread Storage')
                    del_act.triggered.connect(lambda: self.anchor_action_requested.emit(f'delete-file:{file_path}'))
                    menu.exec(event.globalPos())
                    return
        super().contextMenuEvent(event)

    def set_theme_colors(self, theme_dict: dict):
        self.user_bubble_bg = str(theme_dict.get('user_bubble_bg', '#1c2128'))
        self.user_bubble_border = str(theme_dict.get('user_bubble_border', '#30363d'))
        self.sprinkles_enabled = bool(theme_dict.get('sprinkles', False))
        self.viewport().update()

    def paintEvent(self, event):
        try:
            doc = self.document()
            layout = doc.documentLayout() if doc is not None else None
            if doc is not None and layout is not None:
                painter = QPainter(self.viewport())
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                hx = self.horizontalScrollBar().value()
                vy = self.verticalScrollBar().value()
                fill_col = QColor(self.user_bubble_bg)
                border_col = QColor(self.user_bubble_border)

                for frame in doc.rootFrame().childFrames():
                    for sub in frame.childFrames():
                        text_union = None
                        it = sub.begin()
                        while not it.atEnd():
                            blk = it.currentBlock()
                            if blk.isValid():
                                br = layout.blockBoundingRect(blk)
                                tl = blk.layout()
                                if tl is not None and tl.lineCount() > 0:
                                    for i in range(tl.lineCount()):
                                        ln = tl.lineAt(i)
                                        nt = ln.naturalTextRect().translated(br.topLeft())
                                        if nt.width() > 0 and nt.height() > 0:
                                            text_union = nt if text_union is None else text_union.united(nt)
                            it += 1
                        if text_union is None:
                            r_raw = layout.frameBoundingRect(sub)
                            if r_raw.width() > 8 and r_raw.height() > 8:
                                text_union = r_raw
                        if text_union is not None:
                            r = text_union.translated(-hx, -vy).adjusted(-18.0, -11.0, 18.0, 11.0)
                            painter.setPen(QPen(border_col, 1.15))
                            painter.setBrush(fill_col)
                            painter.drawRoundedRect(r, 16.0, 16.0)
                            if self.sprinkles_enabled:
                                # Subtle 100s & 1000s confetti dots on top-right corner of Fairybread user pill
                                sp_cols = ('#ef4444', '#3b82f6', '#22c55e', '#eab308', '#a855f7', '#06b6d4')
                                painter.setPen(Qt.PenStyle.NoPen)
                                for idx_s, scol in enumerate(sp_cols):
                                    painter.setBrush(QColor(scol))
                                    sx = r.right() - 12 - (idx_s * 7)
                                    sy = r.top() + (3 if idx_s % 2 == 0 else 5)
                                    if sx > r.left() + 14:
                                        painter.drawEllipse(QPoint(int(sx), int(sy)), 2, 2)
                painter.end()
        except Exception:
            pass
        super().paintEvent(event)


def format_ai_badge(name: str) -> str:
    clean = (name or '').strip()
    return f'{provider_icon(clean)} {provider_display_name(clean)}'


class TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.succeeded.emit(self.function())
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


class VoiceCompanionWorker(QThread):
    """Transcribes microphone speech and runs the conversational Voice Companion off the UI thread."""
    completed = Signal(object, str)
    failed = Signal(str)

    def __init__(
        self,
        wav_path: Path | None,
        companion,
        *,
        text_input: str = "",
        companion_enabled: bool = True,
        talk_only: bool = False,
        background_busy: bool = False,
        background_status: str = "",
        background_question: str = "",
        recent_chat_snippet: str = "",
        memory_context: str = "",
        allow_memory_write: bool = True,
        session_gen: int = 0,
        memory_db_path: Path | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.wav_path = wav_path
        self.companion = companion
        self.text_input = str(text_input or "")
        self.companion_enabled = bool(companion_enabled)
        self.talk_only = bool(talk_only)
        self.background_busy = bool(background_busy)
        self.background_status = background_status
        self.background_question = background_question
        self.recent_chat_snippet = recent_chat_snippet
        self.memory_context = str(memory_context or "")
        self.allow_memory_write = bool(allow_memory_write)
        self.session_gen = int(session_gen)
        self.memory_db_path = memory_db_path

    def run(self):
        try:
            transcript = self.text_input.strip()
            if not transcript:
                if self.wav_path is None:
                    self.completed.emit(None, "")
                    return
                from voice_service import transcribe_audio_file

                transcript = (transcribe_audio_file(self.wav_path) or "").strip()
            if not transcript:
                self.completed.emit(None, "")
                return
            if not self.companion_enabled or self.companion is None:
                self.completed.emit(None, transcript)
                return
            mem_ctx = self.memory_context
            if self.allow_memory_write and self.memory_db_path is not None:
                try:
                    from memory_service import MemoryService
                    res = MemoryService(db_path=self.memory_db_path).search(transcript)
                    if res.succeeded and res.context:
                        if mem_ctx and res.context not in mem_ctx:
                            mem_ctx = f"{mem_ctx}\n\n{res.context}"
                        elif not mem_ctx:
                            mem_ctx = res.context
                except Exception as exc:
                    try:
                        from voice_service import _log_voice_diagnostic
                        _log_voice_diagnostic(f"VoiceCompanionWorker memory lookup failed: {exc}")
                    except Exception:
                        pass
            try:
                decision = self.companion.respond(
                    transcript,
                    background_busy=self.background_busy,
                    background_status=self.background_status,
                    background_question=self.background_question,
                    recent_chat_snippet=self.recent_chat_snippet,
                    talk_only=self.talk_only,
                    memory_context=mem_ctx,
                    allow_memory_write=self.allow_memory_write,
                )
            except TypeError:
                # NOTE: We reach this branch only if the modern call above raised
                # TypeError. That may be a real internal bug in respond(), not a
                # signature mismatch. Probe once; only retry with legacy args if
                # the signature genuinely does not accept our kwargs.
                import inspect as _inspect
                _modern_ok = True
                try:
                    _sig = _inspect.signature(self.companion.respond)
                    _params = _sig.parameters
                    _required_kwargs = (
                        "talk_only",
                        "memory_context",
                        "allow_memory_write",
                    )
                    _modern_ok = all(
                        (k in _params) or any(
                            p.kind == _inspect.Parameter.VAR_KEYWORD
                            for p in _params.values()
                        )
                        for k in _required_kwargs
                    )
                except (TypeError, ValueError):
                    _modern_ok = True
                if not _modern_ok:
                    decision = self.companion.respond(
                        transcript,
                        background_busy=self.background_busy,
                        background_status=self.background_status,
                        background_question=self.background_question,
                        recent_chat_snippet=self.recent_chat_snippet,
                    )
                else:
                    # Genuine TypeError inside respond() — propagate, do not retry.
                    raise
            self.completed.emit(decision, transcript)
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


class VoiceSummaryWorker(QThread):
    """Summarizes completed multi-AI background output into concise spoken sentences."""
    summary_ready = Signal(str)

    def __init__(self, companion, question: str, final_answer: str, contributors: list[str], parent=None):
        super().__init__(parent)
        self.companion = companion
        self.question = question
        self.final_answer = final_answer
        self.contributors = list(contributors or [])

    def run(self):
        try:
            if self.companion is not None:
                spoken = self.companion.summarize_completed_work(
                    self.question,
                    self.final_answer,
                    contributors=self.contributors,
                )
            else:
                from voice_service import clean_text_for_speech

                spoken = clean_text_for_speech(self.final_answer)[:360]
            if spoken:
                self.summary_ready.emit(spoken)
        except Exception:
            pass


class Composer(QTextEdit):
    files_added = Signal(list)
    image_pasted = Signal(bytes)
    send_requested = Signal()
    unsupported_paste = Signal()

    def __init__(self, enter_to_send: bool = True):
        super().__init__()
        self.enter_to_send = bool(enter_to_send)
        self.setObjectName('composerInput')
        self.setAcceptRichText(False)
        self.setAcceptDrops(True)
        if self.viewport() is not None:
            self.viewport().setAcceptDrops(True)
        self.setAccessibleName('Message to Palace')
        self.setPlaceholderText('Ask anything, / for commands, @ to mention, or drop files')
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFixedHeight(28)
        self.textChanged.connect(self._adjust_height)

    def _adjust_height(self):
        doc_height = int(self.document().size().height()) + 4
        target = max(28, min(110, doc_height))
        if self.height() != target:
            self.setFixedHeight(target)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime is not None and (
            (mime.hasUrls() and any(u.isLocalFile() for u in mime.urls()))
            or mime.hasImage()
            or mime.hasText()
        ):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime is not None and (
            (mime.hasUrls() and any(u.isLocalFile() for u in mime.urls()))
            or mime.hasImage()
            or mime.hasText()
        ):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime is not None and mime.hasUrls() and any(u.isLocalFile() for u in mime.urls()):
            self.files_added.emit([u.toLocalFile() for u in mime.urls() if u.isLocalFile()])
            event.acceptProposedAction()
            return
        if mime is not None and mime.hasImage():
            self.insertFromMimeData(mime)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def canInsertFromMimeData(self, source):
        return source.hasUrls() or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls() and any(url.isLocalFile() for url in source.urls()):
            self.files_added.emit([url.toLocalFile() for url in source.urls() if url.isLocalFile()])
        elif source.hasImage():
            img_data = source.imageData()
            qimg = img_data if isinstance(img_data, QImage) else QImage(img_data)
            if not qimg.isNull():
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                qimg.save(buf, 'PNG')
                raw_bytes = bytes(buf.data())
                buf.close()
                if raw_bytes:
                    self.image_pasted.emit(raw_bytes)
                    return
            self.unsupported_paste.emit()
        else:
            super().insertFromMimeData(source)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            mods = event.modifiers()
            has_shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            has_ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            if has_ctrl:
                self.send_requested.emit()
                event.accept()
                return
            if self.enter_to_send:
                if has_shift:
                    super().keyPressEvent(event)
                else:
                    self.send_requested.emit()
                    event.accept()
                return
            else:
                if has_shift:
                    self.send_requested.emit()
                    event.accept()
                else:
                    super().keyPressEvent(event)
                return
        super().keyPressEvent(event)


class CustomAIPickerDialog(QDialog):
    """Custom selection dialog when the user chooses 'Custom Selection…' from the Squad dropdown."""

    def __init__(
        self,
        parent=None,
        provider_states: dict | None = None,
        all_providers: list[str] | None = None,
        max_ais: int = 0,
        config_path: Path = CONFIG_PATH,
    ):
        super().__init__(parent)
        self.setWindowTitle('Custom AI Squad Selection')
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        hdr = QLabel('Select Which AIs See & Answer Your Questions')
        hdr.setObjectName('sectionTitle')
        lay.addWidget(hdr)

        sub = QLabel('Unticked AIs will not receive the prompt or consume tokens.')
        sub.setObjectName('muted')
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.checkboxes: dict[str, QCheckBox] = {}
        active_map = provider_states or {}
        names = all_providers or list(active_map.keys()) or ['gemini', 'openai', 'deepseek', 'groq', 'qwen', 'cohere', 'mistral']
        for name in names:
            chk = QCheckBox(f'  {provider_icon(name)}  {provider_display_name(name)}')
            chk.setChecked(active_map.get(name) is True)
            chk.setStyleSheet(f'color: {provider_color(name)}; font-weight: 600; font-size: 13px; padding: 3px;')
            self.checkboxes[name] = chk
            lay.addWidget(chk)

        max_row = QHBoxLayout()
        max_row.addWidget(QLabel('Max AIs to answer per turn (0 = All ticked):'))
        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, len(names))
        self.max_spin.setSpecialValueText('All ticked AIs')
        self.max_spin.setValue(max(0, int(max_ais)))
        max_row.addWidget(self.max_spin)
        lay.addLayout(max_row)

        btns = QHBoxLayout()
        all_btn = QPushButton('Select All')
        all_btn.clicked.connect(lambda: [c.setChecked(True) for c in self.checkboxes.values()])
        none_btn = QPushButton('Clear All')
        none_btn.clicked.connect(lambda: [c.setChecked(False) for c in self.checkboxes.values()])
        ok_btn = QPushButton('Apply Selection')
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(all_btn)
        btns.addWidget(none_btn)
        btns.addStretch()
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)

    def selected_providers(self) -> dict[str, bool]:
        return {name: chk.isChecked() for name, chk in self.checkboxes.items()}

    def selected_max_ais(self) -> int:
        return int(self.max_spin.value())


class RestoreDefaultSettingsDialog(QDialog):
    """Fail-safe settings reset dialog protecting Memory Palaces, chats, API keys, and exclusions by default."""

    def __init__(
        self,
        parent=None,
        config_path: Path = CONFIG_PATH,
        backup_dir: Path | None = None,
        bridge_home_dir: Path | None = None,
        bridge_appdata_dir: Path | None = None,
    ):
        super().__init__(parent)
        self.config_path = config_path
        self._backup_dir = backup_dir
        self._bridge_home_dir = bridge_home_dir
        self._bridge_appdata_dir = bridge_appdata_dir
        self.reset_result: dict[str, Any] = {}

        self.setWindowTitle('Restore Default Settings')
        self.resize(560, 400)
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        hdr = QLabel('<b>↺ Restore Default Settings</b>')
        hdr.setTextFormat(Qt.TextFormat.RichText)
        hdr.setStyleSheet('font-size: 15px; color: #f0f6fc;')
        lay.addWidget(hdr)

        info_box = QLabel(
            '<b>Always kept safe (never modified):</b><br>'
            '• Normal &amp; Idle Memory Palaces, conversations, and projects<br>'
            '• Saved API keys (Windows DPAPI vault) and configured provider keys<br><br>'
            '<b>Reset to factory defaults:</b><br>'
            '• Appearance &amp; theme, Agent Defaults, Voice &amp; Audio, Profiles/Squads, '
            'AI Access Mode (back to <i>Default</i>), and Experimental Mode toggles.<br><br>'
            '<span style="color:#8b949e;">An automatic pre-reset JSON snapshot is saved first so you can undo any reset.</span>'
        )
        info_box.setTextFormat(Qt.TextFormat.RichText)
        info_box.setWordWrap(True)
        info_box.setStyleSheet(
            'background:#131720; color:#c9d1d9; border:1px solid #262c3a; '
            'border-radius:8px; padding:12px; font-size:12.5px;'
        )
        lay.addWidget(info_box)

        try:
            ap = load_access_permissions(self.config_path)
            excl_n = len(ap.get('write_exclusions') or [])
        except Exception:
            excl_n = 0

        self.clear_exclusions_check = QCheckBox(
            f'Also clear my Write Exclusion List ({excl_n} protected path(s))'
        )
        self.clear_exclusions_check.setChecked(False)
        lay.addWidget(self.clear_exclusions_check)

        self.unlink_bridges_check = QCheckBox(
            'Also unlink External Agent Bridge (MCP) configs'
        )
        self.unlink_bridges_check.setChecked(False)
        lay.addWidget(self.unlink_bridges_check)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton('↺ Restore Defaults')
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(
            'QPushButton { background:#b62324; color:#ffffff; border:1px solid #da3633; '
            'padding:7px 14px; border-radius:6px; font-weight:700; } '
            'QPushButton:hover { background:#da3633; }'
        )
        apply_btn.clicked.connect(self._execute_reset)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(apply_btn)
        lay.addLayout(btn_row)

    def _execute_reset(self):
        from palace_config import restore_default_settings

        self.reset_result = restore_default_settings(
            self.config_path,
            clear_write_exclusions=self.clear_exclusions_check.isChecked(),
            unlink_external_bridges=self.unlink_bridges_check.isChecked(),
            backup_dir=self._backup_dir,
            bridge_home_dir=self._bridge_home_dir,
            bridge_appdata_dir=self._bridge_appdata_dir,
        )
        self.accept()


class ManageAIsDialog(QDialog):
    """Multi-page Palace Settings dialog (including AI Providers and dedicated Idle Mode page)."""

    SETTINGS_PAGES = [
        'General',
        'AI Access Permissions',
        'Agent Defaults',
        'Voice & Audio',
        'Appearance',
        'Email & Notifications',
        'AI Providers',
        'Profiles',
        'Memory & Personalization',
        'Experimental Mode',
        'External Agent Bridge (MCP)',
        'Backup & Restore',
    ]

    def __init__(
        self,
        parent=None,
        config_path: Path = CONFIG_PATH,
        credential_store: CredentialStore | None = None,
        initial_page: str = 'AI Providers',
        idle_memory: IdleMemoryStore | None = None,
        bridge_home_dir: Path | None = None,
        bridge_appdata_dir: Path | None = None,
    ):
        super().__init__(parent)
        self.config_path = config_path
        self.credential_store = credential_store or CredentialStore()
        self.idle_memory = idle_memory or IdleMemoryStore()
        self._bridge_home_dir = bridge_home_dir
        self._bridge_appdata_dir = bridge_appdata_dir
        self._settings_mic_session = None
        self._voice_dlg_closed = False
        self.setWindowTitle('Fairybread Settings')
        self.resize(960, 720)
        self.setMinimumSize(840, 620)

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)

        # Left navigation list
        self.nav_list = QListWidget()
        self.nav_list.setObjectName('sidebarList')
        self.nav_list.setFixedWidth(205)
        for page_name in self.SETTINGS_PAGES:
            self.nav_list.addItem(page_name)
        root_layout.addWidget(self.nav_list)

        # Right content area + bottom buttons
        right_col = QVBoxLayout()
        self.pages = QStackedWidget()
        right_col.addWidget(self.pages, 1)

        self._build_general_page()
        self._build_ai_access_permissions_page()
        self._build_agent_defaults_page()
        self._build_voice_audio_page()
        self._build_appearance_page()
        self._build_notifications_page()
        self._build_ai_providers_page()
        self._build_profiles_page()
        self._build_memory_history_page()
        self._build_idle_mode_page()
        self._build_permissions_page()
        self._build_backup_restore_page()
        self._polish_settings_forms_and_combos()

        buttons = QHBoxLayout()
        buttons.addStretch()
        save_btn = QPushButton('Save Settings')
        save_btn.setToolTip('Save all changes across all Settings tabs and close')
        save_btn.clicked.connect(self.save_settings)
        cancel_btn = QPushButton('Close')
        cancel_btn.setToolTip('Close Settings window')
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        right_col.addLayout(buttons)

        root_layout.addLayout(right_col, 1)

        self.nav_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        page_aliases = {
            'Permissions': 'AI Access Permissions',
            'Approval': 'AI Access Permissions',
            'Access Permissions': 'AI Access Permissions',
            'Work Mode & Tools': 'AI Access Permissions',
            'Work Mode': 'AI Access Permissions',
            'Configuration': 'Agent Defaults',
            'Control Panel': 'Agent Defaults',
            'Defaults': 'Agent Defaults',
            'Voice': 'Voice & Audio',
            'Audio': 'Voice & Audio',
            'Microphone': 'Voice & Audio',
            'Notifications': 'Email & Notifications',
            'Email': 'Email & Notifications',
            'Agent Bridge': 'External Agent Bridge (MCP)',
            'Agent Bridge & Permissions': 'External Agent Bridge (MCP)',
            'Idle Mode': 'Experimental Mode',
            'Idle': 'Experimental Mode',
            'Experimental': 'Experimental Mode',
            'Memory & History': 'Memory & Personalization',
            'Personalization': 'Memory & Personalization',
            'Memory': 'Memory & Personalization',
        }
        resolved_page = page_aliases.get(initial_page, initial_page)
        target_idx = (
            self.SETTINGS_PAGES.index(resolved_page)
            if resolved_page in self.SETTINGS_PAGES
            else self.SETTINGS_PAGES.index('AI Providers')
        )
        self.nav_list.setCurrentRow(target_idx)

    def _flush_live_volume_save(self):
        tmr = getattr(self, '_vol_save_timer', None)
        if tmr is not None and tmr.isActive():
            tmr.stop()
            if hasattr(self, 'voice_vol_slider'):
                try:
                    from voice_service import save_voice_settings, set_live_volume
                    val = int(self.voice_vol_slider.value())
                    set_live_volume(val, config_path=self.config_path)
                    save_voice_settings({'volume_percent': val}, config_path=self.config_path)
                except Exception:
                    pass

    def _stop_settings_mic_test(self):
        self._flush_live_volume_save()
        sess = getattr(self, '_settings_mic_session', None)
        if sess is not None:
            try:
                sess.stop()
            except Exception:
                pass
            self._settings_mic_session = None
        if hasattr(self, 'mic_live_test_btn'):
            self.mic_live_test_btn.blockSignals(True)
            self.mic_live_test_btn.setChecked(False)
            self.mic_live_test_btn.setText('🎤 Start Live Mic Level Test')
            self.mic_live_test_btn.blockSignals(False)

    def reject(self):
        self._voice_dlg_closed = True
        self._stop_settings_mic_test()
        super().reject()

    def closeEvent(self, event):
        self._voice_dlg_closed = True
        self._stop_settings_mic_test()
        super().closeEvent(event)

    def _make_simple_page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)
        h = QLabel(title)
        h.setObjectName('sectionTitle')
        lay.addWidget(h)
        sub = QLabel(subtitle)
        sub.setObjectName('muted')
        sub.setWordWrap(True)
        lay.addWidget(sub)
        return w, lay

    def _polish_settings_forms_and_combos(self):
        """Ensure every QFormLayout aligns along a single vertical axis and every QComboBox popup shows full text without '...' truncation."""
        for form in self.findChildren(QFormLayout):
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            form.setHorizontalSpacing(16)
            form.setVerticalSpacing(10)
            for row in range(form.rowCount()):
                lbl_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                if lbl_item is not None and lbl_item.widget() is not None:
                    lbl_w = lbl_item.widget()
                    lbl_w.setFixedWidth(210)

        for combo in self.findChildren(QComboBox):
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.setMinimumHeight(30)
            view = combo.view()
            if view is not None:
                view.setTextElideMode(Qt.TextElideMode.ElideNone)
                fm = combo.fontMetrics()
                max_px = max(
                    [fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())] or [320]
                )
                view.setMinimumWidth(max(420, max_px + 56))

    def _build_general_page(self):
        w, lay = self._make_simple_page('General', 'Startup behavior, system tray behavior, and composer preferences.')
        lay.addWidget(QCheckBox('Restore last active conversation on startup', checked=True))

        ui_cfg = load_ui_settings(self.config_path)
        self.close_to_tray_check = QCheckBox(
            'Close button (✕) minimizes Fairybread to the Windows System Tray (right-click tray icon to Expand or Exit)',
            checked=bool(ui_cfg.get('close_to_tray', True)),
        )
        self.close_to_tray_check.setToolTip('Keep Fairybread running in the system tray when closed')
        lay.addWidget(self.close_to_tray_check)

        self.auto_refresh_catalog_check = QCheckBox(
            'Auto-refresh model list, pricing rates && update notices from fairybread.me (JSON only, no telemetry)',
            checked=bool(ui_cfg.get('auto_refresh_catalog', True)),
        )
        self.auto_refresh_catalog_check.setToolTip('Silently refreshes token/voice/image rate tables & checks for new Fairybread releases on startup (6h cache)')
        lay.addWidget(self.auto_refresh_catalog_check)

        enter_form = QFormLayout()
        self.enter_mode_combo = QComboBox()
        self.enter_mode_combo.addItem('Enter submits message · Shift+Enter adds new line (Default)', True)
        self.enter_mode_combo.addItem('Shift+Enter submits message · Enter adds new line', False)
        self.enter_mode_combo.setCurrentIndex(0 if ui_cfg.get('enter_to_send', True) else 1)
        enter_form.addRow('Composer Enter key behavior:', self.enter_mode_combo)
        lay.addLayout(enter_form)

        jump_perm_btn = QPushButton('🛡 AI Access Permissions (Request Review / Default / Auto / Turbo && Write Exclusions)…')
        jump_perm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        jump_perm_btn.setToolTip('Configure execution permissions, Write Exclusion List, and project tool capabilities')
        jump_perm_btn.clicked.connect(lambda: self.nav_list.setCurrentRow(self.SETTINGS_PAGES.index('AI Access Permissions')))
        lay.addWidget(jump_perm_btn)

        jump_defaults_btn = QPushButton('⚙ Open Agent Defaults (Web Search, Detail, Reasoning && Speed)…')
        jump_defaults_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        jump_defaults_btn.setToolTip('Configure web search depth, output detail, reasoning summary, synthesizer, and timeouts')
        jump_defaults_btn.clicked.connect(lambda: self.nav_list.setCurrentRow(self.SETTINGS_PAGES.index('Agent Defaults')))
        lay.addWidget(jump_defaults_btn)

        jump_voice_btn = QPushButton('🎙️ Open Voice && Audio Settings (Human Voice, Accent, Microphone && Companion)…')
        jump_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        jump_voice_btn.setToolTip('Choose your neural voice, accent/style, speed, companion mode, and test your microphone & speaker')
        jump_voice_btn.clicked.connect(lambda: self.nav_list.setCurrentRow(self.SETTINGS_PAGES.index('Voice & Audio')))
        lay.addWidget(jump_voice_btn)

        lay.addStretch()
        self.pages.addWidget(w)

    def _build_ai_access_permissions_page(self):
        w, outer_lay = self._make_simple_page(
            '🛡 AI Access Permissions',
            'Control how agents execute edits and commands on your computer, and maintain an unlimited Write Exclusion List that ALWAYS requires approval — even in Turbo mode.'
        )
        ap_cfg = load_access_permissions(self.config_path)
        tool_cfg = load_tool_settings(self.config_path)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 4)
        lay.setSpacing(10)

        # Card 1: Permissions · This Computer
        mode_card = QFrame()
        mode_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        mc_lay = QVBoxLayout(mode_card)
        mc_lay.setSpacing(8)
        mc_hdr = QLabel('<b>Permissions · This Computer</b>')
        mc_hdr.setTextFormat(Qt.TextFormat.RichText)
        mc_lay.addWidget(mc_hdr)

        form_mode = QFormLayout()
        self.perm_mode_combo = QComboBox()
        self.perm_mode_combo.setToolTip('Select how Fairybread handles file edits, patches, and shell commands')
        for mk in PERMISSION_MODES:
            meta = PERMISSION_MODE_META[mk]
            self.perm_mode_combo.addItem(f"{meta['label']} — {meta['description']}", mk)
        cur_pm = normalize_permission_mode(ap_cfg.get('permission_mode', 'default'))
        pm_idx = self.perm_mode_combo.findData(cur_pm)
        if pm_idx >= 0:
            self.perm_mode_combo.setCurrentIndex(pm_idx)
        form_mode.addRow('Execution mode:', self.perm_mode_combo)
        mc_lay.addLayout(form_mode)

        self.perm_mode_desc_label = QLabel('')
        self.perm_mode_desc_label.setWordWrap(True)
        self.perm_mode_desc_label.setTextFormat(Qt.TextFormat.RichText)
        self.perm_mode_desc_label.setStyleSheet('color:#8b949e; font-size:11.5px;')

        def _sync_mode_desc():
            mk = str(self.perm_mode_combo.currentData() or 'default')
            meta = PERMISSION_MODE_META.get(mk, PERMISSION_MODE_META['default'])
            self.perm_mode_desc_label.setText(
                f"<b>{html.escape(meta['label'])}:</b> {html.escape(meta['description'])} "
                "<span style='color:#6e7681;'>(File tools and command targets are checked against your Write Exclusion List before running; shell commands execute under your Windows user account.)</span>"
            )

        self.perm_mode_combo.currentIndexChanged.connect(lambda _i: _sync_mode_desc())
        _sync_mode_desc()
        mc_lay.addWidget(self.perm_mode_desc_label)
        lay.addWidget(mode_card)

        # Card 2: Write Exclusion List (Always On Top — Overrides Turbo & Auto)
        excl_card = QFrame()
        excl_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        ec_lay = QVBoxLayout(excl_card)
        ec_lay.setSpacing(8)
        ec_hdr = QLabel('<b>Write Exclusion List (Always On Top — Overrides Turbo &amp; Auto)</b>')
        ec_hdr.setTextFormat(Qt.TextFormat.RichText)
        ec_lay.addWidget(ec_hdr)

        ec_sub = QLabel(
            'No matter what mode is selected above (even <b>Turbo</b>), any file write, edit, patch, rename, or delete touching paths in this list forces Fairybread to ask your explicit approval first. Starts empty — add drives or folders with or without subdirectories.'
        )
        ec_sub.setWordWrap(True)
        ec_sub.setTextFormat(Qt.TextFormat.RichText)
        ec_sub.setStyleSheet('color:#8b949e; font-size:11.5px;')
        ec_lay.addWidget(ec_sub)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self.excl_path_input = QLineEdit()
        self.excl_path_input.setPlaceholderText(r'Enter folder or drive path (e.g. M:\, E:\, C:\CriticalFolder)…')
        self.excl_path_input.setToolTip('Type or paste any drive letter or folder path to add to the Write Exclusion List')
        add_row.addWidget(self.excl_path_input, 1)

        self.excl_add_btn = QPushButton('Add Path')
        self.excl_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.excl_add_btn.setToolTip('Add the typed path to the Write Exclusion List')
        add_row.addWidget(self.excl_add_btn)

        self.excl_browse_btn = QPushButton('Browse Folder…')
        self.excl_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.excl_browse_btn.setToolTip('Choose a folder or drive root via folder picker')
        add_row.addWidget(self.excl_browse_btn)

        self.excl_drive_btn = QPushButton('Add Drive ▾')
        self.excl_drive_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.excl_drive_btn.setToolTip('Pick an available local drive root without browsing its contents')
        add_row.addWidget(self.excl_drive_btn)
        ec_lay.addLayout(add_row)

        self.excl_table = QTableWidget(0, 3)
        self.excl_table.setHorizontalHeaderLabels(['Protected Folder or Drive', 'Include Subdirectories', 'Action'])
        self.excl_table.verticalHeader().setVisible(False)
        self.excl_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.excl_table.setMinimumHeight(180)
        self.excl_table.setStyleSheet(
            'QTableWidget { background:#0d1117; color:#e6edf3; border:1px solid #262c3a; border-radius:6px; gridline-color:#21262d; } '
            'QHeaderView::section { background:#161b22; color:#8b949e; border:none; border-bottom:1px solid #262c3a; padding:6px; font-weight:600; }'
        )
        hdr = self.excl_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.excl_table.setColumnWidth(2, 88)
        ec_lay.addWidget(self.excl_table)

        def _add_exclusion_row(raw_path: str, include_subdirs: bool = True):
            clean = normalize_exclusion_path_str(raw_path)
            if not clean:
                return
            for r in range(self.excl_table.rowCount()):
                item0 = self.excl_table.item(r, 0)
                if item0 is not None and os.path.normcase(item0.text().strip()) == os.path.normcase(clean):
                    existing_chk = item0.data(Qt.ItemDataRole.UserRole)
                    if existing_chk is not None:
                        existing_chk.setChecked(bool(include_subdirs))
                    return
            row = self.excl_table.rowCount()
            self.excl_table.insertRow(row)
            self.excl_table.setRowHeight(row, 34)

            p_item = QTableWidgetItem(clean)
            p_item.setFlags(p_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            chk = QCheckBox()
            chk.setChecked(bool(include_subdirs))
            chk.setToolTip(
                'Checked: covers this path and every subfolder underneath it. '
                'Unchecked: protects this folder/drive root only (nested subfolders remain open).'
            )
            p_item.setData(Qt.ItemDataRole.UserRole, chk)
            self.excl_table.setItem(row, 0, p_item)

            chk_host = QWidget()
            chk_lay = QHBoxLayout(chk_host)
            chk_lay.setContentsMargins(0, 0, 0, 0)
            chk_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_lay.addWidget(chk)
            self.excl_table.setCellWidget(row, 1, chk_host)

            rm_btn = QPushButton('Remove')
            rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rm_btn.setToolTip(f'Remove {clean} from Write Exclusion List')

            def _remove_this(_c=False, btn=rm_btn):
                for rr in range(self.excl_table.rowCount()):
                    if self.excl_table.cellWidget(rr, 2) is btn:
                        self.excl_table.removeRow(rr)
                        break

            rm_btn.clicked.connect(_remove_this)
            self.excl_table.setCellWidget(row, 2, rm_btn)

        self._add_exclusion_row = _add_exclusion_row

        def _on_add_typed():
            txt = self.excl_path_input.text().strip()
            if txt:
                _add_exclusion_row(txt, include_subdirs=True)
                self.excl_path_input.clear()

        def _on_browse_folder():
            chosen = QFileDialog.getExistingDirectory(self, 'Select Folder or Drive to Protect')
            if chosen:
                _add_exclusion_row(chosen, include_subdirs=True)

        def _on_drive_menu():
            menu = QMenu(self)
            for drv in list_local_drives():
                act = QAction(drv, menu)
                act.triggered.connect(lambda _c=False, d=drv: _add_exclusion_row(d, include_subdirs=True))
                menu.addAction(act)
            menu.exec(self.excl_drive_btn.mapToGlobal(QPoint(0, self.excl_drive_btn.height() + 2)))

        self.excl_add_btn.clicked.connect(_on_add_typed)
        self.excl_path_input.returnPressed.connect(_on_add_typed)
        self.excl_browse_btn.clicked.connect(_on_browse_folder)
        self.excl_drive_btn.clicked.connect(_on_drive_menu)

        for entry in ap_cfg.get('write_exclusions', []) or []:
            _add_exclusion_row(entry.get('path', ''), include_subdirs=bool(entry.get('include_subdirs', True)))

        lay.addWidget(excl_card)

        # Card 3: Agent Capabilities & Recursive Self-Improvement Safety
        cap_card = QFrame()
        cap_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        cc_lay = QVBoxLayout(cap_card)
        cc_lay.setSpacing(6)
        cc_hdr = QLabel('<b>Agent Capabilities &amp; Workspace Tools</b>')
        cc_hdr.setTextFormat(Qt.TextFormat.RichText)
        cc_lay.addWidget(cc_hdr)

        self.cap_workspace_writes_check = QCheckBox('📁 Project File Editing (Read, write & patch files in user projects)')
        self.cap_workspace_writes_check.setChecked(bool(ap_cfg.get('allow_workspace_writes', True)))
        cc_lay.addWidget(self.cap_workspace_writes_check)

        self.cap_shell_cmds_check = QCheckBox('💻 Terminal / Shell Commands (Run build, test & workspace commands)')
        self.cap_shell_cmds_check.setChecked(bool(ap_cfg.get('allow_shell_commands', True)))
        cc_lay.addWidget(self.cap_shell_cmds_check)

        self.tool_checks: dict[str, QCheckBox] = {}
        items = [
            ('palace_source_tool', '🔧 App Source Code Inspection (Read-only inspection of Fairybread source)'),
            ('shared_palace_files_tool', '🏛 Shared Memory File Tools (Read/write persistent notes & proposals)'),
            ('project_folder_tool', '📂 Attached Project Folder Context (Index attached project folders)'),
            ('owner_email_tool', '✉ Agent-to-Owner Email Tool (Send requests & file links to Agent Mail)'),
            ('github_tool', '🐙 GitHub & Git Workflow Tools'),
            ('external_mail_tool', '📬 External Mail & Web Research Tools'),
        ]
        for key, label in items:
            chk = QCheckBox(label)
            chk.setChecked(bool(tool_cfg.get(key, False)))
            self.tool_checks[key] = chk
            cc_lay.addWidget(chk)

        self_heal_note = QLabel(
            '<span style="color:#8b949e; font-size:11.5px;">'
            '♻ <b>Recursive Self-Improvement Safety:</b> When Fairybread patches its own source files, automatic backups, syntax checks, and rollback recovery stay enabled by default.'
            '</span>'
        )
        self_heal_note.setWordWrap(True)
        self_heal_note.setTextFormat(Qt.TextFormat.RichText)
        cc_lay.addWidget(self_heal_note)
        lay.addWidget(cap_card)

        lay.addStretch()
        scroll.setWidget(inner)
        outer_lay.addWidget(scroll, 1)
        self.pages.addWidget(w)

    def _collect_exclusions(self) -> list[dict[str, Any]]:
        if not hasattr(self, 'excl_table'):
            return []
        rows: list[dict[str, Any]] = []
        for r in range(self.excl_table.rowCount()):
            item0 = self.excl_table.item(r, 0)
            if item0 is None:
                continue
            p_str = normalize_exclusion_path_str(item0.text())
            if not p_str:
                continue
            chk = item0.data(Qt.ItemDataRole.UserRole)
            inc = bool(chk.isChecked()) if chk is not None else True
            rows.append({'path': p_str, 'include_subdirs': inc})
        return rows

    def _build_agent_defaults_page(self):
        w, lay = self._make_simple_page(
            'Agent Defaults',
            'Configure web search defaults, output detail, reasoning style, and speed routing without needing / switches.'
        )
        ad_cfg = load_agent_defaults(self.config_path)

        # Card 1: Response, Web Search, Output Detail & Reasoning Summary
        core_card = QFrame()
        core_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        c_lay = QVBoxLayout(core_card)
        c_lay.setSpacing(8)
        c_hdr = QLabel('<b>Response Style &amp; Web Search Defaults</b>')
        c_hdr.setTextFormat(Qt.TextFormat.RichText)
        c_lay.addWidget(c_hdr)

        form1 = QFormLayout()
        self.ad_web_search_combo = QComboBox()
        self.ad_web_search_combo.setToolTip('Default web search behavior when no /search switch is typed')
        self.ad_web_search_combo.addItem('Off (No automatic web search)', 'off')
        self.ad_web_search_combo.addItem('Default (Light)', 'default')
        self.ad_web_search_combo.addItem('Moderate (/searchm)', 'moderate')
        self.ad_web_search_combo.addItem('Deep (/searchd)', 'deep')
        ws_idx = self.ad_web_search_combo.findData(str(ad_cfg.get('web_search_default', 'default')))
        if ws_idx >= 0:
            self.ad_web_search_combo.setCurrentIndex(ws_idx)
        form1.addRow('Web search:', self.ad_web_search_combo)

        self.ad_output_detail_combo = QComboBox()
        self.ad_output_detail_combo.setToolTip('Choose how much detail Fairybread AIs include in responses')
        self.ad_output_detail_combo.addItem('Concise (Tight bullets, minimal prose)', 'concise')
        self.ad_output_detail_combo.addItem('Balanced (Clear structured answers)', 'balanced')
        self.ad_output_detail_combo.addItem('High (Thorough technical detail)', 'high')
        od_idx = self.ad_output_detail_combo.findData(str(ad_cfg.get('output_detail', 'high')))
        if od_idx >= 0:
            self.ad_output_detail_combo.setCurrentIndex(od_idx)
        form1.addRow('Output detail:', self.ad_output_detail_combo)

        self.ad_reasoning_combo = QComboBox()
        self.ad_reasoning_combo.setToolTip('Choose how Fairybread AIs present their reasoning & tradeoffs')
        self.ad_reasoning_combo.addItem('Off (Direct final answer only)', 'off')
        self.ad_reasoning_combo.addItem('Auto (Brief tradeoffs when helpful)', 'auto')
        self.ad_reasoning_combo.addItem('Detailed (Explicit step-by-step reasoning)', 'detailed')
        rs_idx = self.ad_reasoning_combo.findData(str(ad_cfg.get('reasoning_summary', 'auto')))
        if rs_idx >= 0:
            self.ad_reasoning_combo.setCurrentIndex(rs_idx)
        form1.addRow('Reasoning summary:', self.ad_reasoning_combo)
        c_lay.addLayout(form1)

        perm_jump_btn = QPushButton('🛡 AI Access Permissions (Request Review / Default / Auto / Turbo && Write Exclusions) →')
        perm_jump_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        perm_jump_btn.clicked.connect(lambda: self.nav_list.setCurrentRow(self.SETTINGS_PAGES.index('AI Access Permissions')))
        c_lay.addWidget(perm_jump_btn)
        lay.addWidget(core_card)

        # Card 2: Performance, Fast Synthesizer & Smart Intent Routing
        perf_card = QFrame()
        perf_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        p_lay = QVBoxLayout(perf_card)
        p_lay.setSpacing(8)
        p_hdr = QLabel('<b>Speed, Synthesizer &amp; Smart Intent Routing</b>')
        p_hdr.setTextFormat(Qt.TextFormat.RichText)
        p_lay.addWidget(p_hdr)

        form2 = QFormLayout()
        self.ad_synth_combo = QComboBox()
        self.ad_synth_combo.setToolTip('Model used to merge multi-AI council replies at the end of a turn')
        self.ad_synth_combo.addItem('Auto Fast (DeepSeek / Cerebras / fastest enabled)', 'auto_fast')
        self.ad_synth_combo.addItem('DeepSeek', 'deepseek')
        self.ad_synth_combo.addItem('Gemini', 'gemini')
        self.ad_synth_combo.addItem('OpenAI', 'openai')
        self.ad_synth_combo.addItem('Cerebras (Ultra-fast)', 'cerebras')
        self.ad_synth_combo.addItem('Match Primary (First enabled provider)', 'match_primary')
        sm_idx = self.ad_synth_combo.findData(str(ad_cfg.get('synthesizer_mode', 'auto_fast')))
        if sm_idx >= 0:
            self.ad_synth_combo.setCurrentIndex(sm_idx)
        form2.addRow('Fast Synthesizer:', self.ad_synth_combo)

        self.ad_smart_routing_check = QCheckBox('Enabled (Use 2 fast AIs for quick lookups, 3–4 specialists for code/graphics)')
        self.ad_smart_routing_check.setChecked(bool(ad_cfg.get('smart_routing', True)))
        self.ad_smart_routing_check.setToolTip('Avoids waking all 8 AIs when a quick lookup or focused coding task only needs 2–4 specialists')
        form2.addRow('Smart intent routing:', self.ad_smart_routing_check)

        self.ad_timeout_spin = QSpinBox()
        self.ad_timeout_spin.setRange(15, 120)
        self.ad_timeout_spin.setSuffix(' s')
        self.ad_timeout_spin.setValue(int(ad_cfg.get('provider_timeout_sec', 45)))
        self.ad_timeout_spin.setToolTip('Hard per-provider HTTP timeout so a stalled upstream model never hangs a turn')
        form2.addRow('Provider timeout:', self.ad_timeout_spin)

        self.ad_straggler_spin = QSpinBox()
        self.ad_straggler_spin.setRange(0, 60)
        self.ad_straggler_spin.setSuffix(' s (0 = off)')
        self.ad_straggler_spin.setValue(int(ad_cfg.get('straggler_grace_sec', 15)))
        self.ad_straggler_spin.setToolTip('After majority quorum succeeds, wait at most this many seconds for slow stragglers')
        form2.addRow('Straggler cutoff:', self.ad_straggler_spin)
        p_lay.addLayout(form2)

        self.ad_inline_status_check = QCheckBox(
            'Show inline AI status && failure messages in chat (always ON in Voice Mode)'
        )
        self.ad_inline_status_check.setChecked(bool(ad_cfg.get('show_inline_status_messages', True)))
        self.ad_inline_status_check.setToolTip(
            'Injects compact UI-only italic status lines directly in chat when a provider hits rate limits (429), times out, fails, or falls back (never saved to AI memory)'
        )
        p_lay.addWidget(self.ad_inline_status_check)
        lay.addWidget(perf_card)

        organic_hint = QLabel(
            '<span style="color:#8b949e; font-size:11.5px;">'
            '💡 <b>Organic Intent Understanding:</b> Even with <i>Default</i> mode active, natural phrases like '
            '<i>"no need to ask for approval"</i>, <i>"just fix it"</i>, or <i>"keep it short"</i> are understood automatically without typing <code>/</code> switches.'
            '</span>'
        )
        organic_hint.setWordWrap(True)
        organic_hint.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(organic_hint)

        lay.addStretch()
        self.pages.addWidget(w)

    def _build_voice_audio_page(self):
        from voice_service import (
            DEFAULT_VOICE_SETTINGS,
            GEMINI_TTS_VOICES,
            TTS_ENGINE_SHORT_LABELS,
            TTS_ENGINES,
            TTS_EXTERNAL_KEY_META,
            VOICE_STYLE_PRESETS,
            LiveAudioSession,
            fetch_remote_tts_voices,
            fetch_tts_account_balance,
            get_last_tts_status,
            get_tts_engine_display_label,
            is_loopback_audio_device,
            is_tts_engine_ready,
            list_audio_input_devices,
            list_voices_for_engine,
            load_voice_settings,
            save_voice_settings,
            set_live_volume,
            speak_agent_response,
            stop_speaking,
            transcribe_audio_file,
        )

        w, outer_lay = self._make_simple_page(
            '🎙️ Voice & Audio (🧠 Thinking AI · 🔊 Speaking Voice · 🎤 Microphone)',
            'Pick which AI handles your voice conversations (🧠), choose any voice engine you enjoy listening to (🔊), and adjust volume live.'
        )
        v_cfg = load_voice_settings(self.config_path)
        self._wheel_guard = _NoScrollWheelFilter(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        scroll_inner = QWidget()
        lay = QVBoxLayout(scroll_inner)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)

        # --- SECTION 1: THINKING AI (WHO THINKS & REPLIES) ---
        brain_card = QFrame()
        brain_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        bc_lay = QVBoxLayout(brain_card)
        bc_lay.setSpacing(8)
        bc_hdr = QLabel('<b>🧠 1. Thinking AI — Who thinks &amp; writes replies</b>')
        bc_hdr.setTextFormat(Qt.TextFormat.RichText)
        bc_lay.addWidget(bc_hdr)
        bc_sub = QLabel('Changes personality, reasoning, and what gets said — completely separate from how the voice sounds.')
        bc_sub.setWordWrap(True)
        bc_sub.setStyleSheet('font-size: 12px; color: #8b949e;')
        bc_lay.addWidget(bc_sub)

        b_form = QFormLayout()
        all_brain_keys = ['gemini', 'openai', 'deepseek', 'groq', 'qwen', 'cohere', 'mistral', 'cerebras']
        self.voice_llm_combo = QComboBox()
        self.voice_llm_combo.setToolTip('Primary AI that answers you in Talk Mode Only and Voice Companion')
        self.voice_llm_combo.addItem('✓ Auto — Fastest Ready AI (Recommended)', 'auto')
        for pk in all_brain_keys:
            has_k = False
            try:
                has_k = bool((self.credential_store.get_api_key(pk) or '').strip())
            except Exception:
                has_k = False
            tag = '✓ Ready' if has_k else '🔑 Needs API key'
            self.voice_llm_combo.addItem(f'{provider_icon(pk)} {provider_display_name(pk)} ({tag})', pk)
        cur_brain = str(v_cfg.get('voice_llm_provider', 'auto') or 'auto').lower()
        bi = self.voice_llm_combo.findData(cur_brain)
        if bi >= 0:
            self.voice_llm_combo.setCurrentIndex(bi)
        b_form.addRow('Primary Thinking AI:', self.voice_llm_combo)

        self.voice_llm_fallback_combo = QComboBox()
        self.voice_llm_fallback_combo.setToolTip('Backup Thinking AI used if your Primary Thinking AI is busy or errors (Fairybread notifies you whenever this happens)')
        self.voice_llm_fallback_combo.addItem('✓ Auto — Next Ready AI (Recommended)', 'auto')
        self.voice_llm_fallback_combo.addItem('✕ None — Never auto-switch (tell me if it fails)', 'none')
        for pk in all_brain_keys:
            self.voice_llm_fallback_combo.addItem(f'{provider_icon(pk)} {provider_display_name(pk)}', pk)
        cur_brain_fb = str(v_cfg.get('voice_llm_fallback', 'auto') or 'auto').lower()
        bfi = self.voice_llm_fallback_combo.findData(cur_brain_fb)
        if bfi >= 0:
            self.voice_llm_fallback_combo.setCurrentIndex(bfi)
        b_form.addRow('Fallback Thinking AI:', self.voice_llm_fallback_combo)

        self.status_style_combo = QComboBox()
        self.status_style_combo.setToolTip('Choose how on-screen status & fallback notifications appear in chat (light italic text vs. visual icon badges)')
        self.status_style_combo.addItem('Text only — light italic status line (Default)', 'text')
        self.status_style_combo.addItem('Icons & badges — compact visual markers', 'icons')
        cur_st_style = str(v_cfg.get('status_notification_style', 'text') or 'text').lower()
        ssi = self.status_style_combo.findData(cur_st_style)
        if ssi >= 0:
            self.status_style_combo.setCurrentIndex(ssi)
        b_form.addRow('On-Screen Status Style:', self.status_style_combo)
        bc_lay.addLayout(b_form)

        self.voice_companion_check = QCheckBox(
            'Conversational Voice Companion: keep talking naturally while background AIs work, delegate complex tasks & live-steer them',
            checked=bool(v_cfg.get('voice_companion_enabled', True)),
        )
        self.voice_companion_check.setToolTip('When enabled in Live Voice Mode, Fairybread talks back in ~1–2s and hands heavy tasks to the AI crew in the background')
        bc_lay.addWidget(self.voice_companion_check)

        self.spoken_summary_check = QCheckBox(
            'Speak concise human summaries when background tasks finish (instead of reading raw markdown/code aloud)',
            checked=bool(v_cfg.get('spoken_summary_for_background', True)),
        )
        self.spoken_summary_check.setToolTip('Reads a friendly 2–3 sentence summary aloud while showing the full details on screen')
        bc_lay.addWidget(self.spoken_summary_check)

        self.auto_speak_check = QCheckBox(
            'Always read final synthesized agent responses aloud (Note: Live Voice Mode automatically speaks replies aloud even if this is unchecked)',
            checked=bool(v_cfg.get('auto_speak_responses', False)),
        )
        self.auto_speak_check.setToolTip('When checked, even typed prompts will have their final answer read aloud automatically')
        bc_lay.addWidget(self.auto_speak_check)
        lay.addWidget(brain_card)

        # --- SECTION 2: SPEAKING VOICE, ENGINE SELECTION & INLINE KEY SETUP ---
        spk_card = QFrame()
        spk_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        sc_lay = QVBoxLayout(spk_card)
        sc_lay.setSpacing(8)
        sc_hdr = QLabel('<b>🔊 2. Speaking Voice — Only changes how replies sound aloud</b>')
        sc_hdr.setTextFormat(Qt.TextFormat.RichText)
        sc_lay.addWidget(sc_hdr)
        sc_sub = QLabel('Choose any built-in voice (OpenAI, Gemini, Groq Orpheus, Windows Free) or unlock optional low-latency voices like Cartesia Sonic or ElevenLabs.')
        sc_sub.setWordWrap(True)
        sc_sub.setStyleSheet('font-size: 12px; color: #8b949e;')
        sc_lay.addWidget(sc_sub)

        s_form = QFormLayout()

        self.tts_engine_combo = QComboBox()
        self.tts_engine_combo.setToolTip('Primary voice engine used to speak replies aloud')
        cur_eng = str(v_cfg.get('tts_engine', 'auto') or 'auto')

        def _populate_tts_engine_combo(select_id: str | None = None):
            target = select_id or str(self.tts_engine_combo.currentData() or cur_eng)
            self.tts_engine_combo.blockSignals(True)
            self.tts_engine_combo.clear()
            for eid, _ in TTS_ENGINES:
                self.tts_engine_combo.addItem(
                    get_tts_engine_display_label(eid, credential_store=self.credential_store),
                    eid,
                )
            idx_e = self.tts_engine_combo.findData(target)
            if idx_e >= 0:
                self.tts_engine_combo.setCurrentIndex(idx_e)
            self.tts_engine_combo.blockSignals(False)

        _populate_tts_engine_combo(cur_eng)
        def _open_tts_setup_guide(target_eng: str | None = None):
            eid = (target_eng or str(self.tts_engine_combo.currentData() or '')).strip().lower()
            meta = TTS_EXTERNAL_KEY_META.get(eid)
            if not meta:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle(f"{meta.get('display_name', eid.title())} — Website Setup & Pricing Guide")
            dlg.resize(620, 460)
            dlg.setStyleSheet('background:#0d1117; color:#f0f6fc;')
            dv = QVBoxLayout(dlg)
            dv.setContentsMargins(18, 16, 18, 16)
            dv.setSpacing(10)

            steps_html = ''.join(
                f'<li style="margin:6px 0;">{html.escape(step)}</li>'
                for step in (meta.get('setup_steps') or [])
            )
            guide_lbl = QLabel(
                f"<h3 style='margin:0; color:#f0f6fc;'>{html.escape(str(meta.get('display_name') or eid.title()))} Setup</h3>"
                f"<p style='color:#eab308; font-size:12.5px; margin:6px 0;'><b>Pricing &amp; Plans:</b> {html.escape(str(meta.get('pricing_summary') or ''))}</p>"
                f"<p style='color:#8b949e; font-size:12px; margin:4px 0;'><b>Expected Key Format:</b> <code>{html.escape(str(meta.get('key_prefix_hint') or 'API key'))}</code></p>"
                f"<ol style='color:#e6edf3; font-size:13px; padding-left:20px; margin-top:8px;'>{steps_html}</ol>"
            )
            guide_lbl.setWordWrap(True)
            guide_lbl.setTextFormat(Qt.TextFormat.RichText)
            dv.addWidget(guide_lbl, 1)

            btn_row = QHBoxLayout()
            k_url = str(meta.get('key_url') or '')
            b_url = str(meta.get('billing_url') or '')
            if k_url:
                k_btn = QPushButton('Open API Keys Page ↗', dlg)
                k_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                k_btn.setStyleSheet('background:#166534; color:#ffffff; border:1px solid #22c55e; border-radius:6px; padding:6px 12px; font-weight:600;')
                k_btn.clicked.connect(lambda _c=False, u=k_url: webbrowser.open(u))
                btn_row.addWidget(k_btn)
            if b_url:
                b_btn = QPushButton('Open Billing / Plans ↗', dlg)
                b_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                b_btn.setStyleSheet('background:#21262d; color:#58a6ff; border:1px solid #388bfd; border-radius:6px; padding:6px 12px; font-weight:600;')
                b_btn.clicked.connect(lambda _c=False, u=b_url: webbrowser.open(u))
                btn_row.addWidget(b_btn)
            btn_row.addStretch(1)
            ok_btn = QPushButton('Close', dlg)
            ok_btn.clicked.connect(dlg.accept)
            btn_row.addWidget(ok_btn)
            dv.addLayout(btn_row)
            dlg.exec()

        tts_eng_row = QHBoxLayout()
        tts_eng_row.addWidget(self.tts_engine_combo, 1)
        self.tts_setup_guide_btn = QPushButton('📖 Setup && Pricing')
        self.tts_setup_guide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tts_setup_guide_btn.setToolTip('Step-by-step website navigation, API key creation, plans, and billing tips')
        self.tts_setup_guide_btn.clicked.connect(lambda: _open_tts_setup_guide())
        tts_eng_row.addWidget(self.tts_setup_guide_btn)
        s_form.addRow('Speaking Engine:', tts_eng_row)

        # Inline Progressive Key Setup Card (shown ONLY when selecting an unconfigured external TTS service)
        self.tts_inline_key_frame = QFrame()
        self.tts_inline_key_frame.setStyleSheet(
            'QFrame { background: #1a1f2b; border: 1px solid #eab308; border-radius: 6px; padding: 8px; }'
        )
        ik_lay = QVBoxLayout(self.tts_inline_key_frame)
        ik_lay.setContentsMargins(8, 6, 8, 6)
        ik_lay.setSpacing(6)
        self.tts_inline_key_desc = QLabel('')
        self.tts_inline_key_desc.setWordWrap(True)
        self.tts_inline_key_desc.setTextFormat(Qt.TextFormat.RichText)
        self.tts_inline_key_desc.setStyleSheet('font-size: 12px; color: #fef08a; border: none;')
        ik_lay.addWidget(self.tts_inline_key_desc)

        ik_row = QHBoxLayout()
        self.tts_inline_key_edit = QLineEdit()
        self.tts_inline_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tts_inline_key_edit.setPlaceholderText('Paste API key here…')
        self.tts_inline_key_link_btn = QPushButton('Get API key ↗')
        self.tts_inline_key_link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tts_inline_key_save_btn = QPushButton('Save Key && Test Voice')
        self.tts_inline_key_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tts_inline_key_save_btn.setStyleSheet(
            'QPushButton { background: #166534; color: #ffffff; border: 1px solid #22c55e; border-radius: 5px; padding: 4px 10px; font-weight: 600; }'
        )
        self.tts_inline_key_revert_btn = QPushButton('← Revert to Ready')
        self.tts_inline_key_revert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ik_row.addWidget(self.tts_inline_key_edit, 1)
        ik_row.addWidget(self.tts_inline_key_link_btn)
        ik_row.addWidget(self.tts_inline_key_save_btn)
        ik_row.addWidget(self.tts_inline_key_revert_btn)
        ik_lay.addLayout(ik_row)
        self.tts_inline_key_frame.hide()
        s_form.addRow('', self.tts_inline_key_frame)

        self.tts_fallback_combo = QComboBox()
        self.tts_fallback_combo.setToolTip('Backup speaker voice used automatically if the primary engine fails or hits a limit (shown in chat when triggered)')
        self.tts_fallback_combo.addItem('✓ Auto — Next Ready Voice → Windows Free', 'auto')
        self.tts_fallback_combo.addItem('✕ None — Show audio error instead of switching', 'none')
        for eid, _ in TTS_ENGINES:
            if eid != 'auto':
                self.tts_fallback_combo.addItem(
                    get_tts_engine_display_label(eid, credential_store=self.credential_store),
                    eid,
                )
        cur_fb_eng = str(v_cfg.get('tts_fallback_engine', 'auto') or 'auto')
        fbe_idx = self.tts_fallback_combo.findData(cur_fb_eng)
        if fbe_idx >= 0:
            self.tts_fallback_combo.setCurrentIndex(fbe_idx)
        s_form.addRow('Fallback Voice Engine:', self.tts_fallback_combo)

        voice_row = QHBoxLayout()
        self.voice_name_combo = QComboBox()
        self.voice_name_combo.setToolTip('Choose the primary voice character for the selected speaking engine')

        self.gemini_voice_combo = QComboBox()
        self.gemini_voice_combo.setToolTip('Gemini neural voice used as fallback under Auto mode (or primary when Gemini engine is selected)')
        for gvid, gvlabel in GEMINI_TTS_VOICES:
            self.gemini_voice_combo.addItem(gvlabel, gvid)
        cur_gv = str(v_cfg.get('gemini_voice_name', 'Kore') or 'Kore')
        gv_idx = self.gemini_voice_combo.findData(cur_gv)
        if gv_idx >= 0:
            self.gemini_voice_combo.setCurrentIndex(gv_idx)

        self._saved_primary_voice = str(v_cfg.get('voice_name', 'coral') or 'coral')
        self._saved_groq_voice = str(v_cfg.get('groq_voice_name', 'autumn') or 'autumn')
        self._saved_cartesia_voice = str(v_cfg.get('cartesia_voice_id', DEFAULT_VOICE_SETTINGS['cartesia_voice_id']) or DEFAULT_VOICE_SETTINGS['cartesia_voice_id'])
        self._saved_eleven_voice = str(v_cfg.get('elevenlabs_voice_id', DEFAULT_VOICE_SETTINGS['elevenlabs_voice_id']) or DEFAULT_VOICE_SETTINGS['elevenlabs_voice_id'])
        self._saved_deepgram_voice = str(v_cfg.get('deepgram_voice_name', DEFAULT_VOICE_SETTINGS['deepgram_voice_name']) or DEFAULT_VOICE_SETTINGS['deepgram_voice_name'])
        self._saved_system_voice = str(v_cfg.get('system_voice_name', 'System Default') or 'System Default')
        self._remote_voice_cache: dict[str, list[tuple[str, str]]] = {}

        def _refresh_combo_popup(combo_box: QComboBox):
            view = combo_box.view()
            if view is not None:
                view.setTextElideMode(Qt.TextElideMode.ElideNone)
                fm = combo_box.fontMetrics()
                max_px = max([fm.horizontalAdvance(combo_box.itemText(i)) for i in range(combo_box.count())] or [320])
                view.setMinimumWidth(max(420, max_px + 56))

        def _target_voice_for_engine(eng_id: str) -> str:
            if eng_id == 'gemini':
                return str(self.gemini_voice_combo.currentData() or 'Kore')
            if eng_id == 'groq':
                return self._saved_groq_voice
            if eng_id == 'cartesia':
                return self._saved_cartesia_voice
            if eng_id == 'elevenlabs':
                return self._saved_eleven_voice
            if eng_id == 'deepgram':
                return self._saved_deepgram_voice
            if eng_id == 'system':
                return self._saved_system_voice
            return self._saved_primary_voice

        def _sync_inline_key_prompt():
            eng_id = str(self.tts_engine_combo.currentData() or 'auto')
            ready = is_tts_engine_ready(eng_id, credential_store=self.credential_store)
            if hasattr(self, 'tts_setup_guide_btn'):
                self.tts_setup_guide_btn.setVisible(eng_id in TTS_EXTERNAL_KEY_META)
            if ready or eng_id in {'auto', 'system'}:
                self.tts_inline_key_frame.hide()
            else:
                meta = TTS_EXTERNAL_KEY_META.get(eng_id) or {}
                dname = meta.get('display_name') or eng_id.title()
                blurb = meta.get('blurb') or f'{dname} needs an API key before it can speak.'
                steps = meta.get('setup_steps') or []
                pricing = meta.get('pricing_summary') or ''
                steps_li = ''.join(f'<li style="margin:2px 0;">{html.escape(s)}</li>' for s in steps)
                pricing_p = (
                    f'<div style="color:#eab308; font-size:11.5px; margin-top:4px;"><b>Plans:</b> {html.escape(pricing)}</div>'
                    if pricing
                    else ''
                )
                steps_ol = f'<ol style="margin:4px 0 2px 16px; padding-left:4px; color:#e6edf3; font-size:11.5px;">{steps_li}</ol>' if steps_li else ''
                self.tts_inline_key_desc.setText(f'<b>🔑 {html.escape(blurb)}</b>{pricing_p}{steps_ol}')
                self.tts_inline_key_edit.clear()
                self.tts_inline_key_link_btn.setVisible(bool(meta.get('key_url')))
                self.tts_inline_key_frame.show()
            if hasattr(self, 'fetch_voices_btn'):
                self.fetch_voices_btn.setVisible(eng_id in {'cartesia', 'elevenlabs'} and ready)

        def _populate_voice_combo(selected_override: str | None = None):
            eng_id = str(self.tts_engine_combo.currentData() or 'auto')
            target_id = selected_override or _target_voice_for_engine(eng_id)
            choices = self._remote_voice_cache.get(eng_id) or list_voices_for_engine(eng_id)
            self.voice_name_combo.blockSignals(True)
            self.voice_name_combo.clear()
            for vid, vlabel in choices:
                self.voice_name_combo.addItem(vlabel, vid)
            idx_v = self.voice_name_combo.findData(target_id)
            if idx_v < 0:
                idx_v = self.voice_name_combo.findText(target_id)
            if idx_v >= 0:
                self.voice_name_combo.setCurrentIndex(idx_v)
            _refresh_combo_popup(self.voice_name_combo)
            self.voice_name_combo.blockSignals(False)
            _sync_inline_key_prompt()

        self.fetch_voices_btn = QPushButton('↻ My Voices')
        self.fetch_voices_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_voices_btn.setToolTip('Load custom/cloned voices from your Cartesia or ElevenLabs account')

        def _fetch_account_voices():
            eng_id = str(self.tts_engine_combo.currentData() or 'auto')
            k = (self.credential_store.get_api_key(eng_id) or '').strip() if eng_id in {'cartesia', 'elevenlabs'} else ''
            if not k:
                return
            self.tts_test_status_label.setText(f'Loading {eng_id.title()} account voices…')
            QApplication.processEvents()
            try:
                voices = fetch_remote_tts_voices(eng_id, k)
                self._remote_voice_cache[eng_id] = voices
                _populate_voice_combo()
                self.tts_test_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')
                self.tts_test_status_label.setText(f'Loaded {len(voices)} voices from {eng_id.title()}.')
            except Exception as exc:
                self.tts_test_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                self.tts_test_status_label.setText(f'Could not load {eng_id} voices: {exc}')

        self.fetch_voices_btn.clicked.connect(_fetch_account_voices)

        _populate_voice_combo()

        def _on_engine_changed():
            _populate_voice_combo()

        def _on_primary_voice_changed():
            eng_id = str(self.tts_engine_combo.currentData() or 'auto')
            chosen = str(self.voice_name_combo.currentData() or self.voice_name_combo.currentText() or '')
            if not chosen:
                return
            if eng_id == 'gemini':
                g_i = self.gemini_voice_combo.findData(chosen)
                if g_i >= 0:
                    self.gemini_voice_combo.setCurrentIndex(g_i)
            elif eng_id == 'groq':
                self._saved_groq_voice = chosen
            elif eng_id == 'cartesia':
                self._saved_cartesia_voice = chosen
            elif eng_id == 'elevenlabs':
                self._saved_eleven_voice = chosen
            elif eng_id == 'deepgram':
                self._saved_deepgram_voice = chosen
            elif eng_id == 'system':
                self._saved_system_voice = chosen
            else:
                self._saved_primary_voice = chosen

        self.tts_engine_combo.currentIndexChanged.connect(_on_engine_changed)
        self.voice_name_combo.currentIndexChanged.connect(_on_primary_voice_changed)

        def _open_inline_key_url():
            eng_id = str(self.tts_engine_combo.currentData() or '')
            url = (TTS_EXTERNAL_KEY_META.get(eng_id) or {}).get('key_url')
            if url:
                webbrowser.open(url)

        def _save_inline_tts_key():
            eng_id = str(self.tts_engine_combo.currentData() or '')
            raw_k = self.tts_inline_key_edit.text().strip()
            if not raw_k or eng_id not in {'openai', 'gemini', 'groq', 'cartesia', 'elevenlabs', 'deepgram'}:
                self.tts_test_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                self.tts_test_status_label.setText('Paste an API key above before clicking Save Key.')
                return
            self.credential_store.set_api_key(eng_id, raw_k)
            _populate_tts_engine_combo(eng_id)
            _sync_inline_key_prompt()
            _refresh_active_tts_and_balance(trigger_remote=(os.environ.get('QT_QPA_PLATFORM') != 'offscreen' and eng_id in {'elevenlabs', 'deepgram'}))
            _test_tts()

        def _revert_to_ready_tts():
            fallback_target = next(
                (eid for eid, _ in TTS_ENGINES if eid != 'auto' and is_tts_engine_ready(eid, credential_store=self.credential_store)),
                'auto',
            )
            idx_r = self.tts_engine_combo.findData(fallback_target)
            if idx_r >= 0:
                self.tts_engine_combo.setCurrentIndex(idx_r)

        self.tts_inline_key_link_btn.clicked.connect(_open_inline_key_url)
        self.tts_inline_key_save_btn.clicked.connect(_save_inline_tts_key)
        self.tts_inline_key_revert_btn.clicked.connect(_revert_to_ready_tts)

        test_voice_btn = QPushButton('🔊 Test Voice')
        test_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_voice_btn.setToolTip('Synthesize and play a sample using your selected speaking engine, voice, and speed')

        stop_voice_btn = QPushButton('⏹ Stop Voice')
        stop_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_voice_btn.setToolTip('Immediately interrupt any active spoken response')
        stop_voice_btn.clicked.connect(stop_speaking)

        voice_row.addWidget(self.voice_name_combo, 1)
        voice_row.addWidget(self.fetch_voices_btn)
        voice_row.addWidget(test_voice_btn)
        voice_row.addWidget(stop_voice_btn)
        s_form.addRow('Voice Character:', voice_row)
        s_form.addRow('Fallback Gemini Voice:', self.gemini_voice_combo)

        self.voice_style_combo = QComboBox()
        self.voice_style_combo.setToolTip('Choose default accent & conversational delivery preset')
        for sid, (slabel, _) in VOICE_STYLE_PRESETS.items():
            self.voice_style_combo.addItem(slabel, sid)
        cur_style = str(v_cfg.get('voice_style', 'warm_american') or 'warm_american')
        st_idx = self.voice_style_combo.findData(cur_style)
        if st_idx >= 0:
            self.voice_style_combo.setCurrentIndex(st_idx)
        s_form.addRow('Accent & Style:', self.voice_style_combo)

        self.voice_custom_style_edit = QLineEdit(str(v_cfg.get('custom_style_prompt', '') or ''))
        self.voice_custom_style_edit.setPlaceholderText('Optional extra tone/accent hint (e.g., "Calm, slightly upbeat conversational tone")')
        self.voice_custom_style_edit.setToolTip('Optional fine-tuning instructions passed to OpenAI and Gemini neural voices')
        s_form.addRow('Custom Tone Note:', self.voice_custom_style_edit)

        speed_row = QHBoxLayout()
        self.voice_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.voice_speed_slider.setRange(80, 130)
        cur_speed_pct = max(80, min(130, int(round(float(v_cfg.get('speech_speed', 1.0)) * 100))))
        self.voice_speed_slider.setValue(cur_speed_pct)
        self.voice_speed_slider.setToolTip('Adjust how fast Fairybread speaks (0.80x relaxed – 1.30x brisk)')
        self.voice_speed_label = QLabel(f'{cur_speed_pct / 100.0:.2f}x')
        self.voice_speed_label.setFixedWidth(48)
        self.voice_speed_slider.valueChanged.connect(lambda val: self.voice_speed_label.setText(f'{val / 100.0:.2f}x'))
        speed_row.addWidget(self.voice_speed_slider, 1)
        speed_row.addWidget(self.voice_speed_label)
        s_form.addRow('Speaking Speed:', speed_row)

        vol_row = QHBoxLayout()
        self.voice_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.voice_vol_slider.setRange(0, 100)
        self.voice_vol_slider.setToolTip('Live speaker volume (0% – 100%) — adjusts active speech immediately without clicking Save')
        cur_vol = int(v_cfg.get('volume_percent', 100))
        self.voice_vol_slider.setValue(cur_vol)
        self.voice_vol_label = QLabel(f'{cur_vol}%')
        self.voice_vol_label.setFixedWidth(48)
        self._vol_save_timer = QTimer(self)
        self._vol_save_timer.setSingleShot(True)
        self._vol_save_timer.setInterval(150)

        def _commit_live_vol():
            try:
                save_voice_settings({'volume_percent': int(self.voice_vol_slider.value())}, config_path=self.config_path)
            except Exception:
                pass

        self._vol_save_timer.timeout.connect(_commit_live_vol)

        def _on_live_vol_changed(val: int):
            self.voice_vol_label.setText(f'{val}%')
            set_live_volume(val, config_path=self.config_path)
            self._vol_save_timer.start()

        self.voice_vol_slider.valueChanged.connect(_on_live_vol_changed)
        self.voice_vol_slider.sliderReleased.connect(self._flush_live_volume_save)
        vol_row.addWidget(self.voice_vol_slider, 1)
        vol_row.addWidget(self.voice_vol_label)
        s_form.addRow('Speaker Volume (Live):', vol_row)
        sc_lay.addLayout(s_form)

        self.tts_test_status_label = QLabel('Volume adjusts in real time without Save. OpenAI / Gemini / Groq Orpheus work with your existing keys.')
        self.tts_test_status_label.setWordWrap(True)
        self.tts_test_status_label.setStyleSheet('font-size: 12px; color: #8b949e;')
        sc_lay.addWidget(self.tts_test_status_label)

        status_bal_frame = QFrame()
        status_bal_frame.setStyleSheet('QFrame { background: #0d1117; border: 1px solid #262c3a; border-radius: 6px; padding: 6px; }')
        sb_lay = QVBoxLayout(status_bal_frame)
        sb_lay.setContentsMargins(8, 6, 8, 6)
        sb_lay.setSpacing(4)
        self.tts_active_status_label = QLabel('')
        self.tts_active_status_label.setWordWrap(True)
        self.tts_active_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.tts_active_status_label.setStyleSheet('font-size: 12px; color: #c9d1d9; border: none;')
        sb_lay.addWidget(self.tts_active_status_label)

        bal_row = QHBoxLayout()
        bal_row.setContentsMargins(0, 0, 0, 0)
        self.tts_balance_label = QLabel('')
        self.tts_balance_label.setWordWrap(True)
        self.tts_balance_label.setStyleSheet('font-size: 11.5px; color: #8b949e; border: none;')
        self.tts_check_balance_btn = QPushButton('↻ Balance')
        self.tts_check_balance_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tts_check_balance_btn.setToolTip('Query provider account credits / balance when supported (ElevenLabs, Deepgram)')
        self.tts_open_billing_btn = QPushButton('Billing ↗')
        self.tts_open_billing_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tts_open_billing_btn.setToolTip('Open this voice provider\'s billing and credit balance page in your browser')
        bal_row.addWidget(self.tts_balance_label, 1)
        bal_row.addWidget(self.tts_check_balance_btn)
        bal_row.addWidget(self.tts_open_billing_btn)
        sb_lay.addLayout(bal_row)
        sc_lay.addWidget(status_bal_frame)
        lay.addWidget(spk_card)

        # --- SECTION 3: MICROPHONE & LIVE VOICE INPUT ---
        mic_card = QFrame()
        mic_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        mc_lay = QVBoxLayout(mic_card)
        mc_lay.setSpacing(8)
        mc_hdr = QLabel('<b>🎤 3. Microphone Input &amp; Live Level Meter (Used by Live Voice &amp; Dictation)</b>')
        mc_hdr.setTextFormat(Qt.TextFormat.RichText)
        mc_lay.addWidget(mc_hdr)

        m_form = QFormLayout()
        mic_row = QHBoxLayout()
        self.mic_device_combo = QComboBox()
        self.mic_device_combo.setToolTip('Select which microphone Fairybread should listen to')
        for mdev in list_audio_input_devices():
            self.mic_device_combo.addItem(mdev, mdev)
        cur_mic = str(v_cfg.get('microphone_device', 'System default'))
        m_idx = self.mic_device_combo.findText(cur_mic)
        if m_idx >= 0:
            self.mic_device_combo.setCurrentIndex(m_idx)

        refresh_mics_btn = QPushButton('↻ Refresh Mics')
        refresh_mics_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_mics_btn.setToolTip('Re-scan connected USB, Bluetooth, or headset microphones')

        def _refresh_mics():
            cur = self.mic_device_combo.currentText()
            self.mic_device_combo.clear()
            for dev_name in list_audio_input_devices():
                self.mic_device_combo.addItem(dev_name, dev_name)
            idx_m = self.mic_device_combo.findText(cur)
            if idx_m >= 0:
                self.mic_device_combo.setCurrentIndex(idx_m)

        refresh_mics_btn.clicked.connect(_refresh_mics)
        mic_row.addWidget(self.mic_device_combo, 1)
        mic_row.addWidget(refresh_mics_btn)
        m_form.addRow('Microphone Device:', mic_row)

        self.mic_loopback_warn_lbl = QLabel(
            '⚠ Selected input looks like speaker loopback ("Stereo Mix"), NOT a microphone — Talk Mode will not hear your voice. Pick "System default" or your real mic.'
        )
        self.mic_loopback_warn_lbl.setWordWrap(True)
        self.mic_loopback_warn_lbl.setStyleSheet(
            'font-size: 12px; color: #eab308; background: #29230f; border: 1px solid #eab308; border-radius: 5px; padding: 6px 8px;'
        )

        def _sync_loopback_warning():
            self.mic_loopback_warn_lbl.setVisible(is_loopback_audio_device(self.mic_device_combo.currentText()))

        self.mic_device_combo.currentTextChanged.connect(lambda _t: _sync_loopback_warning())
        _sync_loopback_warning()
        m_form.addRow('', self.mic_loopback_warn_lbl)

        gain_row = QHBoxLayout()
        self.mic_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.mic_gain_slider.setRange(50, 300)
        self.mic_gain_slider.setToolTip('Boosts microphone input volume (150% default helps quiet microphones pick up clearly)')
        cur_gain = int(v_cfg.get('mic_gain_percent', 150))
        self.mic_gain_slider.setValue(cur_gain)
        self.mic_gain_label = QLabel(f'{cur_gain}%')
        self.mic_gain_label.setFixedWidth(48)
        self.mic_gain_slider.valueChanged.connect(lambda val: self.mic_gain_label.setText(f'{val}%'))
        gain_row.addWidget(self.mic_gain_slider, 1)
        gain_row.addWidget(self.mic_gain_label)
        m_form.addRow('Microphone Gain / Boost:', gain_row)

        pause_row = QHBoxLayout()
        self.silence_timeout_slider = QSlider(Qt.Orientation.Horizontal)
        self.silence_timeout_slider.setRange(800, 3000)
        self.silence_timeout_slider.setToolTip('In Live Voice Mode, how long to wait after you pause speaking before sending your message automatically')
        cur_sil = int(v_cfg.get('silence_timeout_ms', 1500))
        self.silence_timeout_slider.setValue(cur_sil)
        self.silence_timeout_label = QLabel(f'{cur_sil / 1000.0:.1f}s')
        self.silence_timeout_label.setFixedWidth(48)
        self.silence_timeout_slider.valueChanged.connect(lambda val: self.silence_timeout_label.setText(f'{val / 1000.0:.1f}s'))
        pause_row.addWidget(self.silence_timeout_slider, 1)
        pause_row.addWidget(self.silence_timeout_label)
        m_form.addRow('Live Voice Auto-Send Pause:', pause_row)
        mc_lay.addLayout(m_form)

        self.barge_in_check = QCheckBox(
            'Interrupt AI when I start talking (Barge-in — best with headphones)',
            checked=bool(v_cfg.get('barge_in_enabled', True)),
        )
        self.barge_in_check.setToolTip(
            'Stops spoken AI audio immediately when you speak over it in Live Voice Mode. Best with headphones; uncheck if loud open desktop speakers bleed into your microphone.'
        )
        mc_lay.addWidget(self.barge_in_check)

        # Live Microphone Level Meter & Test Row
        meter_row = QHBoxLayout()
        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setValue(0)
        self.mic_level_bar.setTextVisible(True)
        self.mic_level_bar.setFormat('Mic Level: %p%')
        self.mic_level_bar.setToolTip('Live microphone signal level — speak to see this green bar move in real time!')
        self.mic_level_bar.setStyleSheet(
            'QProgressBar { background:#0d1117; border:1px solid #30363d; border-radius:6px; height:22px; text-align:center; color:#e6edf3; font-weight:600; } '
            'QProgressBar::chunk { background:#22c55e; border-radius:5px; }'
        )
        self.mic_wave_lbl = QLabel('▁▁▁▁▁▁')
        self.mic_wave_lbl.setStyleSheet('font-family: Consolas, monospace; font-size: 15px; color: #22c55e; min-width: 70px;')
        self.mic_wave_lbl.setToolTip('Live soundwave indicator')

        self.mic_live_test_btn = QPushButton('🎤 Start Live Mic Level Test')
        self.mic_live_test_btn.setCheckable(True)
        self.mic_live_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_live_test_btn.setToolTip('Click and speak into your microphone to watch the green level meter move in real time')

        self.mic_transcribe_test_btn = QPushButton('🧪 Record 3s && Test Transcription')
        self.mic_transcribe_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_transcribe_test_btn.setToolTip('Record 3 seconds of your voice and transcribe it live to verify end-to-end voice input')

        meter_row.addWidget(self.mic_level_bar, 1)
        meter_row.addWidget(self.mic_wave_lbl)
        meter_row.addWidget(self.mic_live_test_btn)
        meter_row.addWidget(self.mic_transcribe_test_btn)
        mc_lay.addLayout(meter_row)

        self.mic_test_status_label = QLabel('Tip: Click "🎤 Start Live Mic Level Test" and speak — the green bar will bounce if your mic hears you.')
        self.mic_test_status_label.setWordWrap(True)
        self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #8b949e;')
        mc_lay.addWidget(self.mic_test_status_label)

        def _collect_voice_payload() -> dict:
            eng = str(self.tts_engine_combo.currentData() or 'auto')
            chosen_voice = str(self.voice_name_combo.currentData() or self.voice_name_combo.currentText() or 'coral')
            gemini_voice = chosen_voice if eng == 'gemini' else str(self.gemini_voice_combo.currentData() or 'Kore')
            primary_voice = chosen_voice if eng in {'auto', 'openai'} else self._saved_primary_voice
            groq_voice = chosen_voice if eng == 'groq' else self._saved_groq_voice
            cart_voice = chosen_voice if eng == 'cartesia' else self._saved_cartesia_voice
            elev_voice = chosen_voice if eng == 'elevenlabs' else self._saved_eleven_voice
            dg_voice = chosen_voice if eng == 'deepgram' else self._saved_deepgram_voice
            sys_voice = chosen_voice if eng == 'system' else self._saved_system_voice
            return {
                'tts_engine': eng,
                'tts_fallback_engine': str(self.tts_fallback_combo.currentData() or 'auto'),
                'voice_llm_provider': str(self.voice_llm_combo.currentData() or 'auto'),
                'voice_llm_fallback': str(self.voice_llm_fallback_combo.currentData() or 'auto'),
                'voice_name': primary_voice,
                'gemini_voice_name': gemini_voice,
                'groq_voice_name': groq_voice,
                'cartesia_voice_id': cart_voice,
                'elevenlabs_voice_id': elev_voice,
                'deepgram_voice_name': dg_voice,
                'system_voice_name': sys_voice,
                'voice_style': str(self.voice_style_combo.currentData() or 'warm_american'),
                'custom_style_prompt': self.voice_custom_style_edit.text().strip(),
                'speech_speed': round(int(self.voice_speed_slider.value()) / 100.0, 2),
                'microphone_device': self.mic_device_combo.currentText(),
                'mic_gain_percent': int(self.mic_gain_slider.value()),
                'silence_timeout_ms': int(self.silence_timeout_slider.value()),
                'volume_percent': int(self.voice_vol_slider.value()),
                'barge_in_enabled': self.barge_in_check.isChecked(),
                'status_notification_style': str(self.status_style_combo.currentData() or 'text'),
                'voice_companion_enabled': self.voice_companion_check.isChecked(),
                'spoken_summary_for_background': self.spoken_summary_check.isChecked(),
                'auto_speak_responses': self.auto_speak_check.isChecked(),
            }

        self._collect_voice_payload = _collect_voice_payload

        def _save_current_voice_fields():
            save_voice_settings(_collect_voice_payload(), config_path=self.config_path)

        self._active_billing_url = ''

        def _refresh_active_tts_and_balance(trigger_remote: bool = False):
            eng_id = str(self.tts_engine_combo.currentData() or 'auto')
            v_disp = str(self.voice_name_combo.currentText() or '').split('—', 1)[0].strip()
            st = get_last_tts_status()
            if st.get('engine_id'):
                st_lbl = f"{st.get('engine_label') or st.get('engine_id')} ({st.get('voice_label') or 'default'})"
                if st.get('last_error'):
                    status_html = (
                        f"<b>Last Active Voice:</b> <span style='color:#eab308;'>{html.escape(st_lbl)}</span> "
                        f"&nbsp;·&nbsp; <span style='color:#e06c75;'>Last issue: {html.escape(str(st.get('last_error') or '')[:140])}</span>"
                    )
                else:
                    status_html = f"<b>Active Voice:</b> <span style='color:#22c55e;'>{html.escape(st_lbl)}</span>"
            else:
                sel_short = TTS_ENGINE_SHORT_LABELS.get(eng_id, eng_id.title())
                cfg_desc = f"{sel_short} ({v_disp})" if v_disp else sel_short
                status_html = f"<b>Configured Voice:</b> <span style='color:#58a6ff;'>{html.escape(cfg_desc)}</span> <span style='color:#8b949e;'>(click Test Voice to verify live)</span>"
            self.tts_active_status_label.setText(status_html)

            k_val = ''
            try:
                if eng_id in {'openai', 'gemini', 'groq', 'cartesia', 'elevenlabs', 'deepgram'}:
                    k_val = (self.credential_store.get_api_key(eng_id) or '').strip()
            except Exception:
                k_val = ''

            is_live_bal_provider = (eng_id in {'elevenlabs', 'deepgram'}) and bool(k_val)
            self.tts_check_balance_btn.setVisible(is_live_bal_provider)

            if is_live_bal_provider and trigger_remote:
                self.tts_balance_label.setStyleSheet('font-size: 11.5px; color: #58a6ff; border: none;')
                self.tts_balance_label.setText(f'Checking {TTS_ENGINE_SHORT_LABELS.get(eng_id, eng_id)} balance…')

                def _bal_worker(e_req=eng_id, k_req=k_val):
                    res = fetch_tts_account_balance(e_req, k_req)

                    def _apply_bal():
                        if getattr(self, '_voice_dlg_closed', False):
                            return
                        if str(self.tts_engine_combo.currentData() or '') != e_req:
                            return
                        col = '#22c55e' if res.get('ok') else '#e06c75'
                        self.tts_balance_label.setStyleSheet(f'font-size: 11.5px; color: {col}; border: none;')
                        self.tts_balance_label.setText(str(res.get('summary') or ''))
                        self._active_billing_url = str(res.get('billing_url') or '')
                        self.tts_open_billing_btn.setVisible(bool(self._active_billing_url))

                    QTimer.singleShot(0, _apply_bal)

                threading.Thread(target=_bal_worker, daemon=True, name='FairybreadTtsBalance').start()
            elif is_live_bal_provider:
                self.tts_balance_label.setStyleSheet('font-size: 11.5px; color: #8b949e; border: none;')
                self.tts_balance_label.setText(f'{TTS_ENGINE_SHORT_LABELS.get(eng_id, eng_id)}: click "↻ Balance" to read remaining credits/USD.')
                b_info = fetch_tts_account_balance(eng_id, '')
                self._active_billing_url = str(b_info.get('billing_url') or '')
                self.tts_open_billing_btn.setVisible(bool(self._active_billing_url))
            else:
                b_info = fetch_tts_account_balance(eng_id, '')
                self.tts_balance_label.setStyleSheet('font-size: 11.5px; color: #8b949e; border: none;')
                self.tts_balance_label.setText(str(b_info.get('summary') or ''))
                self._active_billing_url = str(b_info.get('billing_url') or '')
                self.tts_open_billing_btn.setVisible(bool(self._active_billing_url))

        self.tts_check_balance_btn.clicked.connect(lambda: _refresh_active_tts_and_balance(trigger_remote=True))
        self.tts_open_billing_btn.clicked.connect(lambda: webbrowser.open(self._active_billing_url) if self._active_billing_url else None)
        self.tts_engine_combo.currentIndexChanged.connect(lambda _i: _refresh_active_tts_and_balance(trigger_remote=False))
        self.voice_name_combo.currentIndexChanged.connect(lambda _i: _refresh_active_tts_and_balance(trigger_remote=False))
        _refresh_active_tts_and_balance(
            trigger_remote=(os.environ.get('QT_QPA_PLATFORM') != 'offscreen' and cur_eng in {'elevenlabs', 'deepgram'})
        )

        def _test_tts():
            _save_current_voice_fields()
            self.tts_test_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
            self.tts_test_status_label.setText('⏳ Generating natural speech sample…')
            fell_back_seen = [False]

            def _on_eng(eng_label: str):
                def _apply_eng():
                    if getattr(self, '_voice_dlg_closed', False):
                        return
                    if not fell_back_seen[0]:
                        self.tts_test_status_label.setStyleSheet('font-size: 12px; color: #22c55e; font-weight: 600;')
                        self.tts_test_status_label.setText(f'🔊 Speaking via {eng_label}')
                    _refresh_active_tts_and_balance(trigger_remote=False)

                QTimer.singleShot(0, _apply_eng)

            def _on_meta(meta: dict):
                if meta.get('fell_back'):
                    fell_back_seen[0] = True
                    msg = f'⚠ Fell back to 🔊 {meta.get("engine_label")} ({meta.get("fallback_reason") or "primary unavailable"})'

                    def _apply_fb(m=msg):
                        if getattr(self, '_voice_dlg_closed', False):
                            return
                        self.tts_test_status_label.setStyleSheet('font-size: 12px; color: #eab308; font-weight: 600;')
                        self.tts_test_status_label.setText(m)
                        _refresh_active_tts_and_balance(trigger_remote=False)

                    QTimer.singleShot(0, _apply_fb)

            def _on_err(err_msg: str):
                def _apply_err(m=err_msg):
                    if getattr(self, '_voice_dlg_closed', False):
                        return
                    self.tts_test_status_label.setStyleSheet('font-size: 12px; color: #f85149; font-weight: 600;')
                    self.tts_test_status_label.setText(f'🔇 Voice playback failed: {m}')
                    _refresh_active_tts_and_balance(trigger_remote=False)

                QTimer.singleShot(0, _apply_err)

            speak_agent_response(
                "Hey Brett, Fairybread's human voice and conversational companion are ready whenever you want to talk.",
                config_path=self.config_path,
                credential_store=self.credential_store,
                on_engine_status=_on_eng,
                on_speech_meta=_on_meta,
                on_error=_on_err,
            )

        test_voice_btn.clicked.connect(_test_tts)

        def _on_test_level(lvl: int, bars: str, speech: bool):
            self.mic_level_bar.setValue(lvl)
            self.mic_wave_lbl.setText(bars)
            if speech:
                self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #22c55e; font-weight: 600;')
                self.mic_test_status_label.setText(f'✓ Microphone hears you clearly! Live level: {lvl}% ({bars})')

        def _toggle_live_mic_test(checked: bool):
            if checked:
                _save_current_voice_fields()
                sess = LiveAudioSession(
                    config_path=self.config_path,
                    live_mode=False,
                    on_level=_on_test_level,
                )
                ok, dev_desc = sess.start(self)
                if not ok:
                    self.mic_live_test_btn.blockSignals(True)
                    self.mic_live_test_btn.setChecked(False)
                    self.mic_live_test_btn.blockSignals(False)
                    self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                    self.mic_test_status_label.setText(f'⚠ {dev_desc}')
                    return
                self._settings_mic_session = sess
                self.mic_live_test_btn.setText('⏹ Stop Mic Test')
                self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
                self.mic_test_status_label.setText(f'🎤 Listening on "{dev_desc}" — speak now to watch the green meter move!')
            else:
                self._stop_settings_mic_test()
                self.mic_level_bar.setValue(0)
                self.mic_wave_lbl.setText('▁▁▁▁▁▁')
                self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #8b949e;')
                self.mic_test_status_label.setText('Mic level test stopped.')

        def _run_3s_transcription_test():
            self._stop_settings_mic_test()
            _save_current_voice_fields()
            sess = LiveAudioSession(
                config_path=self.config_path,
                live_mode=False,
                on_level=_on_test_level,
            )
            ok, dev_desc = sess.start(self)
            if not ok:
                self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                self.mic_test_status_label.setText(f'⚠ {dev_desc}')
                return
            self._settings_mic_session = sess
            self.mic_transcribe_test_btn.setEnabled(False)
            self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #eab308; font-weight: 600;')
            self.mic_test_status_label.setText(f'🔴 Recording 3 seconds on "{dev_desc}" — say a test phrase now…')

            def _finish_3s():
                self.mic_transcribe_test_btn.setEnabled(True)
                s_active = getattr(self, '_settings_mic_session', None)
                if s_active is None:
                    return
                self._settings_mic_session = None
                wav_p = s_active.stop('fairybread_settings_test.wav')
                self.mic_level_bar.setValue(0)
                if not wav_p:
                    self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                    self.mic_test_status_label.setText('⚠ No audio captured.')
                    return
                self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
                self.mic_test_status_label.setText('⏳ Transcribing your 3-second test clip…')
                QApplication.processEvents()
                try:
                    txt = transcribe_audio_file(wav_p, credential_store=self.credential_store)
                    self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #22c55e; font-weight: 600;')
                    self.mic_test_status_label.setText(f'✓ Heard you: "{txt}"')
                except Exception as exc:
                    self.mic_test_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                    self.mic_test_status_label.setText(f'⚠ {exc}')

            QTimer.singleShot(3000, _finish_3s)

        self.mic_live_test_btn.toggled.connect(_toggle_live_mic_test)
        self.mic_transcribe_test_btn.clicked.connect(_run_3s_transcription_test)
        for _guard_w in (
            self.voice_llm_combo,
            self.voice_llm_fallback_combo,
            self.status_style_combo,
            self.tts_engine_combo,
            self.tts_fallback_combo,
            self.voice_name_combo,
            self.gemini_voice_combo,
            self.voice_style_combo,
            self.voice_speed_slider,
            self.voice_vol_slider,
            self.mic_device_combo,
            self.mic_gain_slider,
            self.silence_timeout_slider,
        ):
            _guard_w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            _guard_w.installEventFilter(self._wheel_guard)
        lay.addWidget(mic_card)
        lay.addStretch()

        scroll.setWidget(scroll_inner)
        outer_lay.addWidget(scroll, 1)
        self.pages.addWidget(w)

    def _build_appearance_page(self):
        w, lay = self._make_simple_page('Appearance & Themes', 'Choose a built-in theme (including Fairybread) or create/import custom JSON themes.')

        ui_cfg = load_ui_settings(self.config_path)
        badge_form = QFormLayout()

        self.theme_combo = QComboBox()
        for tid, tname in list_available_themes():
            self.theme_combo.addItem(tname, tid)
        cur_theme = str(ui_cfg.get('theme', 'dark'))
        t_idx = self.theme_combo.findData(cur_theme)
        if t_idx >= 0:
            self.theme_combo.setCurrentIndex(t_idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        badge_form.addRow('Application Theme:', self.theme_combo)

        self.badge_mode_combo = QComboBox()
        self.badge_mode_combo.addItem('Icons Only — Compact tokens with hover name (Default)', 'icons_only')
        self.badge_mode_combo.addItem('Icons + Full Names (◆ Gemini)', 'icons_and_names')
        self.badge_mode_combo.addItem('Full Names Only (Gemini)', 'names_only')
        cur_badge_mode = ui_cfg.get('badge_display_mode', 'icons_only')
        b_idx = self.badge_mode_combo.findData(cur_badge_mode)
        if b_idx >= 0:
            self.badge_mode_combo.setCurrentIndex(b_idx)
        badge_form.addRow('Agent Chip Display Style:', self.badge_mode_combo)
        lay.addLayout(badge_form)

        theme_btn_row = QHBoxLayout()
        open_themes_btn = QPushButton('📂 Open Custom Themes Folder (Create / Edit JSON Themes)')
        open_themes_btn.clicked.connect(lambda: webbrowser.open(str(get_themes_dir())))
        theme_btn_row.addWidget(open_themes_btn)
        theme_btn_row.addStretch()
        lay.addLayout(theme_btn_row)

        lay.addWidget(QCheckBox('Show contributor symbols inside reply cards', checked=True))
        lay.addStretch()
        self.pages.addWidget(w)

    def _on_theme_combo_changed(self, _idx: int = 0):
        tid = str(self.theme_combo.currentData() or 'dark')
        save_ui_settings({'theme': tid}, config_path=self.config_path)
        parent = self.parent()
        if parent is not None and hasattr(parent, 'apply_theme'):
            parent.apply_theme(tid)
        self.setStyleSheet(build_theme_stylesheet(tid))

    def _build_notifications_page(self):
        from email_service import (
            EMAIL_CREDENTIAL_KEY,
            EMAIL_PROVIDER_PRESETS,
            load_email_settings,
            save_email_settings,
            send_self_notification_email,
        )

        w, lay = self._make_simple_page(
            '📧 Email Connector & Completion Notifications',
            'Configure Desktop Toast alerts, Email completion notifications, and Exhaustive All-Mail Inbox Search (Windows DPAPI encrypted).'
        )
        cfg = load_email_settings(self.config_path)

        # --- SECTION 1: COMPLETION NOTIFICATIONS ---
        notif_hdr = QLabel('<b>1. Action Completion Notifications (Desktop &amp; Email)</b>')
        lay.addWidget(notif_hdr)

        desk_row = QHBoxLayout()
        self.desktop_notify_check = QCheckBox(
            'Enable Desktop Toast Notification when a job finishes',
            checked=bool(cfg.get('desktop_notify_enabled', True)),
        )
        desk_row.addWidget(self.desktop_notify_check)
        self.desktop_sound_check = QCheckBox(
            'Play completion chime',
            checked=bool(cfg.get('desktop_sound_enabled', False)),
        )
        desk_row.addWidget(self.desktop_sound_check)
        desk_row.addStretch()
        lay.addLayout(desk_row)

        notif_form = QFormLayout()
        self.desktop_notify_mode_combo = QComboBox()
        self.desktop_notify_mode_combo.addItem(
            'When Fairybread is unfocused OR job takes > 12 seconds (Default)',
            'background_or_long',
        )
        self.desktop_notify_mode_combo.addItem('Every completed turn', 'always')
        self.desktop_notify_mode_combo.addItem('Only when Autonomous Idle Mode finishes', 'idle_only')
        d_idx = self.desktop_notify_mode_combo.findData(cfg.get('desktop_notify_mode', 'background_or_long'))
        if d_idx >= 0:
            self.desktop_notify_mode_combo.setCurrentIndex(d_idx)
        notif_form.addRow('Desktop Trigger:', self.desktop_notify_mode_combo)

        self.email_notify_check = QCheckBox(
            'Email me the result when a large job or Idle Mode session finishes',
            checked=bool(cfg.get('email_notify_enabled', False)),
        )
        notif_form.addRow('Email Alerts:', self.email_notify_check)

        email_trig_row = QHBoxLayout()
        self.email_notify_mode_combo = QComboBox()
        self.email_notify_mode_combo.addItem(
            'Large jobs (> 30 seconds) or Idle Mode completion (Default)',
            'long_or_idle',
        )
        self.email_notify_mode_combo.addItem('Every completed turn', 'always')
        self.email_notify_mode_combo.addItem('Only when Autonomous Idle Mode finishes', 'idle_only')
        e_idx = self.email_notify_mode_combo.findData(cfg.get('email_notify_mode', 'long_or_idle'))
        if e_idx >= 0:
            self.email_notify_mode_combo.setCurrentIndex(e_idx)
        email_trig_row.addWidget(self.email_notify_mode_combo, 1)
        self.email_attach_images_check = QCheckBox(
            'Attach generated PNGs',
            checked=bool(cfg.get('email_attach_images', True)),
        )
        email_trig_row.addWidget(self.email_attach_images_check)
        notif_form.addRow('Email Trigger:', email_trig_row)
        lay.addLayout(notif_form)

        # --- SECTION 2: EMAIL PROVIDER & EXHAUSTIVE SEARCH SETUP ---
        email_hdr = QLabel('<b>2. Email Account Setup (Gmail, Microsoft Outlook/365, iCloud, Yahoo, Custom)</b>')
        lay.addWidget(email_hdr)

        email_form = QFormLayout()
        prov_row = QHBoxLayout()
        self.email_provider_combo = QComboBox()
        for p_key, p_meta in EMAIL_PROVIDER_PRESETS.items():
            self.email_provider_combo.addItem(str(p_meta['display_name']), p_key)
        p_idx = self.email_provider_combo.findData(cfg.get('provider', 'gmail'))
        if p_idx >= 0:
            self.email_provider_combo.setCurrentIndex(p_idx)
        prov_row.addWidget(self.email_provider_combo, 1)

        self.email_portal_btn = QPushButton('🔑 Open Provider Password Page ↗')
        self.email_portal_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def _open_email_portal():
            pkey = str(self.email_provider_combo.currentData() or 'gmail')
            url = str(EMAIL_PROVIDER_PRESETS.get(pkey, {}).get('setup_url', '')).strip()
            if url:
                webbrowser.open(url)

        self.email_portal_btn.clicked.connect(_open_email_portal)
        prov_row.addWidget(self.email_portal_btn)
        email_form.addRow('Email Provider:', prov_row)

        self.email_setup_hint_label = QLabel('')
        self.email_setup_hint_label.setObjectName('muted')
        self.email_setup_hint_label.setWordWrap(True)
        self.email_setup_hint_label.setStyleSheet('font-size: 11.5px; color: #8b949e;')
        email_form.addRow('', self.email_setup_hint_label)

        self.email_address_edit = QLineEdit(str(cfg.get('email_address', '')))
        self.email_address_edit.setPlaceholderText('your.name@gmail.com or your.name@outlook.com')
        email_form.addRow('Email Address:', self.email_address_edit)

        self.email_password_edit = QLineEdit()
        self.email_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        has_email_pw = self.credential_store.has_api_key(EMAIL_CREDENTIAL_KEY)
        self.email_password_edit.setPlaceholderText(
            '✓ Encrypted in Windows DPAPI Vault (paste new App Password / OAuth token to replace)'
            if has_email_pw
            else 'Paste 16-char App Password (or oauth:<token> for Microsoft Graph)'
        )
        email_form.addRow('App Password / Token:', self.email_password_edit)

        srv_row = QHBoxLayout()
        self.email_imap_host_edit = QLineEdit(str(cfg.get('imap_host', 'imap.gmail.com')))
        self.email_imap_port_spin = QSpinBox()
        self.email_imap_port_spin.setRange(1, 65535)
        self.email_imap_port_spin.setValue(int(cfg.get('imap_port', 993)))
        self.email_smtp_host_edit = QLineEdit(str(cfg.get('smtp_host', 'smtp.gmail.com')))
        self.email_smtp_port_spin = QSpinBox()
        self.email_smtp_port_spin.setRange(1, 65535)
        self.email_smtp_port_spin.setValue(int(cfg.get('smtp_port', 465)))
        srv_row.addWidget(QLabel('IMAP:'))
        srv_row.addWidget(self.email_imap_host_edit, 1)
        srv_row.addWidget(self.email_imap_port_spin)
        srv_row.addWidget(QLabel('SMTP:'))
        srv_row.addWidget(self.email_smtp_host_edit, 1)
        srv_row.addWidget(self.email_smtp_port_spin)
        email_form.addRow('Servers:', srv_row)

        self.email_access_mode_combo = QComboBox()
        self.email_access_mode_combo.addItem(
            '📝 Read & Drafts Only — Exhaustive All-Mail Search + Drafts (Recommended Default)',
            'read_and_drafts',
        )
        self.email_access_mode_combo.addItem(
            '🔔 Self-Notifications Only — Outbound completion alerts to my own address only',
            'notifications_only',
        )
        self.email_access_mode_combo.addItem(
            '⚡ Full Email Assistant — Search, read, draft, and send',
            'full_assistant',
        )
        a_idx = self.email_access_mode_combo.findData(cfg.get('access_mode', 'read_and_drafts'))
        if a_idx >= 0:
            self.email_access_mode_combo.setCurrentIndex(a_idx)
        email_form.addRow('AI Access Level:', self.email_access_mode_combo)
        lay.addLayout(email_form)

        def _on_email_provider_changed():
            pkey = str(self.email_provider_combo.currentData() or 'gmail')
            meta = EMAIL_PROVIDER_PRESETS.get(pkey, {})
            self.email_setup_hint_label.setText(str(meta.get('setup_hint', '')))
            if meta.get('imap_host'):
                self.email_imap_host_edit.setText(str(meta['imap_host']))
                self.email_imap_port_spin.setValue(int(meta.get('imap_port', 993)))
            if meta.get('smtp_host'):
                self.email_smtp_host_edit.setText(str(meta['smtp_host']))
                self.email_smtp_port_spin.setValue(int(meta.get('smtp_port', 465)))
            self.email_portal_btn.setEnabled(bool(meta.get('setup_url')))

        self.email_provider_combo.currentIndexChanged.connect(_on_email_provider_changed)
        _on_email_provider_changed()

        test_row = QHBoxLayout()
        test_btn = QPushButton('🧪 Save && Send Test Notification (Desktop + Email)')
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.email_test_status_label = QLabel('')
        self.email_test_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')

        def _run_test_notifications():
            self._save_email_and_notification_fields()
            parent = self.parent()
            if parent is not None and hasattr(parent, 'show_desktop_toast'):
                parent.show_desktop_toast(
                    'Fairybread Test Notification',
                    'Desktop toast notifications are active and working!',
                )
            addr = self.email_address_edit.text().strip()
            if addr:
                ok, msg = send_self_notification_email(
                    subject='🧚 Fairybread — Test Email Notification',
                    body_text=(
                        'Your Fairybread Email & Notification connector is configured and working!\n\n'
                        '• Exhaustive All-Mail search (Zero Silent Truncation) is ready.\n'
                        '• Completion notifications will be delivered here when enabled.'
                    ),
                    config_path=self.config_path,
                    credential_store=self.credential_store,
                )
                self.email_test_status_label.setStyleSheet(
                    f'font-size: 12px; color: {"#22c55e" if ok else "#f85149"};'
                )
                self.email_test_status_label.setText(f'{"✓" if ok else "⚠"} {msg}')
            else:
                self.email_test_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
                self.email_test_status_label.setText('✓ Desktop toast sent! (Enter an email address above to test email alerts)')

        test_btn.clicked.connect(_run_test_notifications)
        test_row.addWidget(test_btn)
        test_row.addWidget(self.email_test_status_label, 1)
        lay.addLayout(test_row)
        lay.addStretch()
        self.pages.addWidget(w)

    def _save_email_and_notification_fields(self):
        from email_service import EMAIL_PROVIDER_PRESETS, save_email_settings
        if not hasattr(self, 'desktop_notify_check'):
            return
        pkey = str(self.email_provider_combo.currentData() or 'gmail')
        smtp_mode = str(EMAIL_PROVIDER_PRESETS.get(pkey, {}).get('smtp_mode', 'ssl'))
        if self.email_smtp_port_spin.value() == 587:
            smtp_mode = 'starttls'
        save_email_settings(
            {
                'enabled': bool(self.email_address_edit.text().strip()),
                'provider': pkey,
                'email_address': self.email_address_edit.text().strip(),
                'imap_host': self.email_imap_host_edit.text().strip(),
                'imap_port': int(self.email_imap_port_spin.value()),
                'smtp_host': self.email_smtp_host_edit.text().strip(),
                'smtp_port': int(self.email_smtp_port_spin.value()),
                'smtp_mode': smtp_mode,
                'access_mode': str(self.email_access_mode_combo.currentData() or 'read_and_drafts'),
                'desktop_notify_enabled': self.desktop_notify_check.isChecked(),
                'desktop_notify_mode': str(self.desktop_notify_mode_combo.currentData() or 'background_or_long'),
                'desktop_sound_enabled': self.desktop_sound_check.isChecked(),
                'email_notify_enabled': self.email_notify_check.isChecked(),
                'email_notify_mode': str(self.email_notify_mode_combo.currentData() or 'long_or_idle'),
                'email_attach_images': self.email_attach_images_check.isChecked(),
            },
            password=self.email_password_edit.text().strip() or None,
            config_path=self.config_path,
            credential_store=self.credential_store,
        )

    def _build_ai_providers_page(self):
        w, lay = self._make_simple_page(
            'AI Providers (Instant DPAPI Auto-Save)',
            'Select any AI provider below or type a custom name. API keys are automatically encrypted with Windows DPAPI and saved as you type.'
        )
        self._loading_provider_fields = False
        self._active_provider_slug = ''

        form = QFormLayout()
        prov_row = QHBoxLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.setEditable(True)
        self.provider_combo.setIconSize(QSize(20, 20))
        configs = load_provider_configs(self.config_path)
        known = list(dict.fromkeys([
            *PROVIDER_CATALOG.keys(),
            *configs.keys(),
        ]))
        for prov_name in known:
            disp = PROVIDER_CATALOG.get(prov_name, {}).get('display_name', prov_name)
            self.provider_combo.addItem(provider_qicon(prov_name), prov_name)
            idx_last = self.provider_combo.count() - 1
            self.provider_combo.setItemData(idx_last, f'{disp} ({prov_name})', Qt.ItemDataRole.ToolTipRole)
        self.provider_combo.currentTextChanged.connect(self._load_selected_provider)
        prov_row.addWidget(self.provider_combo, 1)

        self.get_key_portal_btn = QPushButton('🔑 Get API Key ↗')
        self.get_key_portal_btn.setToolTip('Open this AI provider’s official API Key creation page in your browser')
        self.get_key_portal_btn.clicked.connect(self._open_selected_provider_key_portal)
        prov_row.addWidget(self.get_key_portal_btn)
        form.addRow('AI Provider:', prov_row)

        self.provider_billing_label = QLabel('')
        self.provider_billing_label.setObjectName('muted')
        self.provider_billing_label.setWordWrap(True)
        form.addRow('Provider Info:', self.provider_billing_label)

        self.enabled_check = QCheckBox('Active in conversation')
        self.enabled_check.setChecked(True)
        self.enabled_check.toggled.connect(self._auto_save_current_provider)
        form.addRow('', self.enabled_check)

        key_row = QHBoxLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText('Paste API key — saves & encrypts automatically (Windows DPAPI)')
        self.api_key_edit.textEdited.connect(self._auto_save_current_provider)
        self.api_key_edit.editingFinished.connect(self._auto_save_current_provider)
        show_key_btn = QPushButton('👁 Show')
        show_key_btn.setCheckable(True)
        show_key_btn.toggled.connect(
            lambda checked: (
                self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password),
                show_key_btn.setText('🙈 Hide' if checked else '👁 Show'),
            )
        )
        key_row.addWidget(self.api_key_edit, 1)
        key_row.addWidget(show_key_btn)
        form.addRow('1. API Key:', key_row)

        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_edit = self.model_combo.lineEdit()
        self.model_edit.setPlaceholderText('Select a model from the dropdown or click Fetch Live Models')
        self.model_combo.currentTextChanged.connect(self._auto_save_current_provider)
        self.fetch_models_btn = QPushButton('↻ Fetch Live Models')
        self.fetch_models_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_models_btn.setToolTip('Query this provider’s live API using your API key to list all currently available models.')
        self.fetch_models_btn.clicked.connect(self._fetch_live_models_for_current_provider)
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.fetch_models_btn)
        form.addRow('2. Model:', model_row)

        self.adv_url_check = QCheckBox('▸ Show Advanced Custom Base URL (Not needed for Cerebras, OpenAI, Gemini, etc.)')
        form.addRow('', self.adv_url_check)

        self.base_url_label = QLabel('Base URL:')
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText('Leave blank for official cloud endpoint (only used for custom proxies / Ollama)')
        self.base_url_edit.textEdited.connect(self._auto_save_current_provider)
        self.base_url_edit.editingFinished.connect(self._auto_save_current_provider)
        form.addRow(self.base_url_label, self.base_url_edit)

        def _toggle_adv_url(checked: bool):
            self.base_url_label.setVisible(checked)
            self.base_url_edit.setVisible(checked)

        self.adv_url_check.toggled.connect(_toggle_adv_url)
        _toggle_adv_url(False)

        self.auto_save_status_label = QLabel('🔒 Protected by Windows DPAPI · Auto-save enabled')
        self.auto_save_status_label.setStyleSheet('color: #22c55e; font-size: 11.5px; font-weight: 600;')
        form.addRow('', self.auto_save_status_label)

        lay.addLayout(form)
        lay.addStretch()
        self._load_selected_provider(self.provider_combo.currentText())
        self.pages.addWidget(w)

    def _open_selected_provider_key_portal(self):
        clean = self.provider_combo.currentText().strip().lower()
        cat = PROVIDER_CATALOG.get(clean, {})
        url = str(cat.get('key_url') or 'https://openrouter.ai/settings/keys')
        webbrowser.open(url)

    def _build_profiles_page(self):
        w, lay = self._make_simple_page(
            'Profiles & AI Squads',
            'Customize which AI providers, how many AIs per turn, and which modes (Deliberation / Code access) belong to each Profile.'
        )
        self._squads_data = load_ai_squads(self.config_path)
        self._active_squad_key = next(iter(self._squads_data.keys()), 'code')
        self._loading_squad_ui = False

        split_row = QHBoxLayout()
        split_row.setSpacing(14)

        left_col = QVBoxLayout()
        left_col.addWidget(QLabel('<b>Profiles / Squads:</b>'))
        self.squad_list_widget = QListWidget()
        self.squad_list_widget.setFixedWidth(220)
        self.squad_list_widget.setToolTip('Select a Profile to customize its AIs and settings')
        left_col.addWidget(self.squad_list_widget, 1)

        sq_btn_row = QHBoxLayout()
        add_sq_btn = QPushButton('+ New')
        add_sq_btn.setToolTip('Create a new custom Profile')
        del_sq_btn = QPushButton('🗑 Delete')
        del_sq_btn.setToolTip('Delete selected Profile')
        reset_sq_btn = QPushButton('↺ Defaults')
        reset_sq_btn.setToolTip('Restore built-in default Profiles')
        sq_btn_row.addWidget(add_sq_btn)
        sq_btn_row.addWidget(del_sq_btn)
        sq_btn_row.addWidget(reset_sq_btn)
        left_col.addLayout(sq_btn_row)
        split_row.addLayout(left_col)

        right_card = QFrame()
        right_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        right_lay = QVBoxLayout(right_card)
        right_lay.setSpacing(10)

        form = QFormLayout()
        self.squad_label_edit = QLineEdit()
        self.squad_label_edit.setToolTip('Display name for this Profile')
        form.addRow('Profile Name:', self.squad_label_edit)

        self.squad_max_ais_combo = QComboBox()
        self.squad_max_ais_combo.setToolTip('Maximum number of AIs to run per turn in this Profile')
        self.squad_max_ais_combo.addItem('All Checked AIs (No Cap)', 0)
        for n_cap in (1, 2, 3, 4, 5, 6, 8, 10, 12):
            self.squad_max_ais_combo.addItem(f'Max {n_cap} AI{"s" if n_cap > 1 else ""} per turn', n_cap)
        form.addRow('How Many AIs to Use:', self.squad_max_ais_combo)
        right_lay.addLayout(form)

        self.squad_delib_check = QCheckBox('Enable 2-Round Council Deliberation (Peer Review ON)')
        self.squad_delib_check.setToolTip('Run 2-round peer review when this Profile is selected')
        right_lay.addWidget(self.squad_delib_check)

        self.squad_code_check = QCheckBox('Enable Fairybread Source Code Access ({} Code ON)')
        self.squad_code_check.setToolTip('Automatically enable read-only source code sharing in this Profile')
        right_lay.addWidget(self.squad_code_check)

        right_lay.addWidget(QLabel('<b>Included AI Providers in this Profile:</b>'))
        prov_grid = QGridLayout()
        prov_grid.setSpacing(8)
        self.squad_provider_checks: dict[str, QCheckBox] = {}
        configs = load_provider_configs(self.config_path)
        all_prov_names = list(dict.fromkeys([*PROVIDER_CATALOG.keys(), *configs.keys()]))
        for idx, pname in enumerate(all_prov_names):
            disp = provider_display_name(pname)
            ic = provider_icon(pname)
            chk = QCheckBox(f'{ic} {disp}')
            chk.setToolTip(f'Include {disp} in this Profile')
            self.squad_provider_checks[pname] = chk
            prov_grid.addWidget(chk, idx // 3, idx % 3)
        right_lay.addLayout(prov_grid)
        right_lay.addStretch(1)
        split_row.addWidget(right_card, 1)
        lay.addLayout(split_row, 1)

        def _save_current_squad_edits():
            if self._loading_squad_ui or not self._active_squad_key:
                return
            if self._active_squad_key not in self._squads_data:
                return
            lbl = self.squad_label_edit.text().strip() or self._active_squad_key
            provs = [p for p, c in self.squad_provider_checks.items() if c.isChecked()]
            self._squads_data[self._active_squad_key] = {
                'label': lbl,
                'providers': provs,
                'deliberate': self.squad_delib_check.isChecked(),
                'code_access': self.squad_code_check.isChecked(),
                'max_ais': int(self.squad_max_ais_combo.currentData() or 0),
            }
            cur_item = self.squad_list_widget.currentItem()
            if cur_item and str(cur_item.data(Qt.ItemDataRole.UserRole)) == self._active_squad_key:
                cur_item.setText(f'{lbl} ({len(provs)} AIs)')

        def _populate_squad_list(select_key: str | None = None):
            self._loading_squad_ui = True
            self.squad_list_widget.clear()
            target_row = 0
            for idx, (k, v) in enumerate(self._squads_data.items()):
                cnt = len(v.get('providers') or [])
                it = QListWidgetItem(f'{v.get("label", k)} ({cnt} AIs)')
                it.setData(Qt.ItemDataRole.UserRole, k)
                self.squad_list_widget.addItem(it)
                if select_key and k == select_key:
                    target_row = idx
            self._loading_squad_ui = False
            if self.squad_list_widget.count() > 0:
                self.squad_list_widget.setCurrentRow(target_row)

        def _on_squad_selected(current: QListWidgetItem | None, _prev: QListWidgetItem | None = None):
            if current is None:
                return
            _save_current_squad_edits()
            key = str(current.data(Qt.ItemDataRole.UserRole) or '')
            if key not in self._squads_data:
                return
            self._loading_squad_ui = True
            self._active_squad_key = key
            sq = self._squads_data[key]
            self.squad_label_edit.setText(str(sq.get('label') or key))
            max_idx = self.squad_max_ais_combo.findData(int(sq.get('max_ais') or 0))
            self.squad_max_ais_combo.setCurrentIndex(max_idx if max_idx >= 0 else 0)
            self.squad_delib_check.setChecked(bool(sq.get('deliberate', True)))
            self.squad_code_check.setChecked(bool(sq.get('code_access', False)))
            inc = set(sq.get('providers') or [])
            for p, c in self.squad_provider_checks.items():
                c.setChecked(p in inc)
            self._loading_squad_ui = False

        def _add_new_squad():
            _save_current_squad_edits()
            new_key = f'custom_{len(self._squads_data) + 1}'
            while new_key in self._squads_data:
                new_key += '_'
            self._squads_data[new_key] = {
                'label': '✨ Custom Profile',
                'providers': ['gemini', 'openai'],
                'deliberate': True,
                'code_access': False,
                'max_ais': 0,
            }
            _populate_squad_list(select_key=new_key)

        def _del_selected_squad():
            if len(self._squads_data) <= 1:
                return
            cur = self.squad_list_widget.currentItem()
            if cur is None:
                return
            k = str(cur.data(Qt.ItemDataRole.UserRole) or '')
            if k in self._squads_data:
                self._loading_squad_ui = True
                del self._squads_data[k]
                self._active_squad_key = next(iter(self._squads_data.keys()), '')
                self._loading_squad_ui = False
                _populate_squad_list(select_key=self._active_squad_key)

        def _restore_default_squads():
            self._loading_squad_ui = True
            self._squads_data = {k: dict(v, providers=list(v.get('providers', []))) for k, v in DEFAULT_AI_SQUADS.items()}
            self._active_squad_key = next(iter(self._squads_data.keys()), 'code')
            self._loading_squad_ui = False
            _populate_squad_list(select_key=self._active_squad_key)

        self._flush_squad_editor = _save_current_squad_edits
        self.squad_list_widget.currentItemChanged.connect(_on_squad_selected)
        self.squad_label_edit.textEdited.connect(lambda _t: _save_current_squad_edits())
        self.squad_max_ais_combo.currentIndexChanged.connect(lambda _i: _save_current_squad_edits())
        self.squad_delib_check.toggled.connect(lambda _b: _save_current_squad_edits())
        self.squad_code_check.toggled.connect(lambda _b: _save_current_squad_edits())
        for chk in self.squad_provider_checks.values():
            chk.toggled.connect(lambda _b: _save_current_squad_edits())
        add_sq_btn.clicked.connect(_add_new_squad)
        del_sq_btn.clicked.connect(_del_selected_squad)
        reset_sq_btn.clicked.connect(_restore_default_squads)
        _populate_squad_list(select_key=self._active_squad_key)

        self.pages.addWidget(w)

    def _build_memory_history_page(self):
        w, lay = self._make_simple_page(
            'Memory & Personalization',
            'Configure your Rich User Profile, Reference Photos, Tone & Style sliders, and Custom Instructions across all Council AIs.'
        )
        p_cfg = load_personalization_settings(self.config_path)

        # 1. MEMORY & AUTO-EVOLVING RICH PROFILE CARD
        mem_card = QFrame()
        mem_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        mc_lay = QVBoxLayout(mem_card)
        mc_lay.setSpacing(8)

        row1 = QHBoxLayout()
        lbl1 = QLabel(
            '<b>Enable Shared Memory &amp; Rich User Profile</b><br>'
            '<span style="color:#8b949e; font-size:11.5px;">Automatically remember facts, preferences, skills, and project context across all connected AIs.</span>'
        )
        lbl1.setWordWrap(True)
        lbl1.setTextFormat(Qt.TextFormat.RichText)
        self.enable_shared_mem_check = QCheckBox('Enabled')
        self.enable_shared_mem_check.setChecked(bool(p_cfg.get('auto_evolve_profile', True)))
        self.enable_shared_mem_check.setToolTip('Automatically learn and update your Rich User Profile from chats')
        row1.addWidget(lbl1, 1)
        row1.addWidget(self.enable_shared_mem_check)
        mc_lay.addLayout(row1)

        row2 = QHBoxLayout()
        lbl2 = QLabel(
            '<b>Living User Profile &amp; Memory Summary</b><br>'
            '<span style="color:#8b949e; font-size:11.5px;">View and directly edit what Fairybread knows about you (Overview, How You Like to Work, Projects).</span>'
        )
        lbl2.setWordWrap(True)
        lbl2.setTextFormat(Qt.TextFormat.RichText)
        manage_sum_btn = QPushButton('Manage Profile…')
        manage_sum_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_sum_btn.setToolTip('View & edit your Living User Profile')

        def _open_summary():
            parent = self.parent()
            if parent is not None and hasattr(parent, 'show_memory_summary_dialog'):
                parent.show_memory_summary_dialog()

        manage_sum_btn.clicked.connect(_open_summary)
        row2.addWidget(lbl2, 1)
        row2.addWidget(manage_sum_btn)
        mc_lay.addLayout(row2)
        lay.addWidget(mem_card)

        # 2. REFERENCE PHOTOS CARD (Face + Full-Body)
        ref_card = QFrame()
        ref_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        ref_lay = QVBoxLayout(ref_card)
        ref_lay.setSpacing(6)
        ref_lay.addWidget(QLabel('<b>Reference photos</b> <span style="color:#8b949e; font-size:11.5px;">(Stored 100% locally — used when you ask to generate or edit an image of yourself)</span>'))

        self.ref_face_path = str(p_cfg.get('reference_photo_face') or '')
        self.ref_body_path = str(p_cfg.get('reference_photo_body') or '')

        face_row = QHBoxLayout()
        self.ref_face_lbl = QLabel()
        face_add_btn = QPushButton('Add / Change…')
        face_clr_btn = QPushButton('Clear')
        face_row.addWidget(self.ref_face_lbl, 1)
        face_row.addWidget(face_add_btn)
        face_row.addWidget(face_clr_btn)
        ref_lay.addLayout(face_row)

        body_row = QHBoxLayout()
        self.ref_body_lbl = QLabel()
        body_add_btn = QPushButton('Add / Change…')
        body_clr_btn = QPushButton('Clear')
        body_row.addWidget(self.ref_body_lbl, 1)
        body_row.addWidget(body_add_btn)
        body_row.addWidget(body_clr_btn)
        ref_lay.addLayout(body_row)

        def _refresh_ref_labels():
            f_name = Path(self.ref_face_path).name if self.ref_face_path else 'Not set'
            b_name = Path(self.ref_body_path).name if self.ref_body_path else 'Not set'
            self.ref_face_lbl.setText(f'<b>Reference photo (Face / Portrait):</b> <span style="color:#58a6ff;">{html.escape(f_name)}</span>')
            self.ref_body_lbl.setText(f'<b>Full-body reference photo:</b> <span style="color:#58a6ff;">{html.escape(b_name)}</span>')

        def _pick_ref_photo(kind: str):
            p_str, _ = QFileDialog.getOpenFileName(
                self,
                'Select Reference Photo',
                '',
                'Images (*.png *.jpg *.jpeg *.webp *.bmp)',
            )
            if not p_str or p_str.upper().startswith('M:'):
                return
            import shutil
            ref_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Palace' / 'reference_photos'
            ref_dir.mkdir(parents=True, exist_ok=True)
            src = Path(p_str)
            dst = ref_dir / f'{kind}_{src.name}'
            try:
                shutil.copy2(src, dst)
                if kind == 'face':
                    self.ref_face_path = str(dst)
                else:
                    self.ref_body_path = str(dst)
                _refresh_ref_labels()
            except Exception:
                pass

        face_add_btn.clicked.connect(lambda: _pick_ref_photo('face'))
        face_clr_btn.clicked.connect(lambda: (setattr(self, 'ref_face_path', ''), _refresh_ref_labels()))
        body_add_btn.clicked.connect(lambda: _pick_ref_photo('body'))
        body_clr_btn.clicked.connect(lambda: (setattr(self, 'ref_body_path', ''), _refresh_ref_labels()))
        _refresh_ref_labels()
        lay.addWidget(ref_card)

        # 3. STYLE, TONE & FORMATTING CONTROLS CARD
        tone_card = QFrame()
        tone_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        tone_grid = QGridLayout(tone_card)
        tone_grid.setSpacing(8)

        self.pers_base_style_combo = QComboBox()
        for opt in ('Friendly', 'Candid & Direct (No Flattery)', 'Technical & Concise', 'Casual & Witty', 'Professional'):
            self.pers_base_style_combo.addItem(opt, opt)
        self.pers_base_style_combo.setCurrentText(str(p_cfg.get('base_style') or 'Friendly'))

        def _make_level_combo(cur_val: str, choices=('Less', 'Default', 'More')) -> QComboBox:
            cb = QComboBox()
            for ch in choices:
                cb.addItem(ch, ch)
            cb.setCurrentText(cur_val if cur_val in choices else 'Default')
            return cb

        self.pers_warmth_combo = _make_level_combo(str(p_cfg.get('warmth') or 'Default'))
        self.pers_enthusiasm_combo = _make_level_combo(str(p_cfg.get('enthusiasm') or 'Less'))
        self.pers_emoji_combo = _make_level_combo(str(p_cfg.get('emoji') or 'Less'), choices=('None', 'Less', 'Default', 'More'))
        self.pers_visual_combo = _make_level_combo(str(p_cfg.get('visual_answers') or 'Default'))
        self.pers_headers_combo = _make_level_combo(str(p_cfg.get('headers_and_lists') or 'More'))

        tone_grid.addWidget(QLabel('<b>Base style and tone:</b>'), 0, 0)
        tone_grid.addWidget(self.pers_base_style_combo, 0, 1)
        tone_grid.addWidget(QLabel('<b>Warmth:</b>'), 0, 2)
        tone_grid.addWidget(self.pers_warmth_combo, 0, 3)

        tone_grid.addWidget(QLabel('<b>Enthusiasm:</b>'), 1, 0)
        tone_grid.addWidget(self.pers_enthusiasm_combo, 1, 1)
        tone_grid.addWidget(QLabel('<b>Emoji:</b>'), 1, 2)
        tone_grid.addWidget(self.pers_emoji_combo, 1, 3)

        tone_grid.addWidget(QLabel('<b>Visual answers:</b>'), 2, 0)
        tone_grid.addWidget(self.pers_visual_combo, 2, 1)
        tone_grid.addWidget(QLabel('<b>Headers and lists:</b>'), 2, 2)
        tone_grid.addWidget(self.pers_headers_combo, 2, 3)
        lay.addWidget(tone_card)

        # 4. CUSTOM INSTRUCTIONS (General Chat + Coding / Work)
        inst_card = QFrame()
        inst_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        inst_lay = QVBoxLayout(inst_card)
        inst_lay.setSpacing(6)
        inst_lay.addWidget(QLabel('<b>Custom instructions (General Chat — applies to all Council AIs):</b>'))
        self.pers_general_inst_edit = QTextEdit()
        self.pers_general_inst_edit.setAcceptRichText(False)
        self.pers_general_inst_edit.setPlaceholderText('Give your Council AIs extra instructions and context for everyday chats…')
        self.pers_general_inst_edit.setMaximumHeight(68)
        self.pers_general_inst_edit.setPlainText(str(p_cfg.get('custom_instructions_general') or ''))
        inst_lay.addWidget(self.pers_general_inst_edit)

        inst_lay.addWidget(QLabel('<b>Coding &amp; Technical Work instructions (like Codex — applies to code/work tasks):</b>'))
        self.pers_coding_inst_edit = QTextEdit()
        self.pers_coding_inst_edit.setAcceptRichText(False)
        self.pers_coding_inst_edit.setPlaceholderText('Specify coding conventions, languages, drive rules, or review workflow…')
        self.pers_coding_inst_edit.setMaximumHeight(68)
        self.pers_coding_inst_edit.setPlainText(str(p_cfg.get('custom_instructions_coding') or ''))
        inst_lay.addWidget(self.pers_coding_inst_edit)
        lay.addWidget(inst_card)

        lay.addStretch(1)
        self.pages.addWidget(w)

    def _build_idle_mode_page(self):
        w, lay = self._make_simple_page(
            'Experimental Mode',
            'Experimental Mode lets your AI Council run autonomous peer-to-peer discussions, share notes, '
            'and optionally inspect Fairybread source code. Configure duration, caps, code sharing, memory access, and charter below.'
        )
        idle_cfg = load_idle_settings(self.config_path)

        form = QFormLayout()
        self.idle_duration_combo = QComboBox()
        for label, minutes in IDLE_DURATION_CHOICES:
            self.idle_duration_combo.addItem(label, minutes)
        cur_dur = int(idle_cfg.get('duration_minutes', 30))
        dur_idx = self.idle_duration_combo.findData(cur_dur)
        if dur_idx < 0:
            self.idle_duration_combo.addItem(f'{cur_dur} minutes', cur_dur)
            dur_idx = self.idle_duration_combo.count() - 1
        self.idle_duration_combo.setCurrentIndex(dur_idx)
        form.addRow('Experimental session duration:', self.idle_duration_combo)

        self.idle_token_limit_combo = QComboBox()
        for label, tok_limit in IDLE_TOKEN_LIMIT_CHOICES:
            self.idle_token_limit_combo.addItem(label, tok_limit)
        cur_tok = int(idle_cfg.get('max_tokens_limit', 0))
        tok_idx = self.idle_token_limit_combo.findData(cur_tok)
        if tok_idx >= 0:
            self.idle_token_limit_combo.setCurrentIndex(tok_idx)
        form.addRow('Max token limit (per session):', self.idle_token_limit_combo)

        self.idle_credit_limit_combo = QComboBox()
        for label, usd_limit in IDLE_CREDIT_LIMIT_CHOICES:
            self.idle_credit_limit_combo.addItem(label, usd_limit)
        cur_usd = float(idle_cfg.get('max_credit_usd', 0.0))
        for i in range(self.idle_credit_limit_combo.count()):
            if abs(float(self.idle_credit_limit_combo.itemData(i)) - cur_usd) < 1e-4:
                self.idle_credit_limit_combo.setCurrentIndex(i)
                break
        form.addRow('Max credit / spend limit (per session):', self.idle_credit_limit_combo)

        from palace_config import (
            STORAGE_SLIDER_STOPS_MB,
            format_storage_mb_label,
            mb_to_slider_index,
            parse_storage_mb_text,
            slider_index_to_mb,
        )
        cur_idle_mb = int(idle_cfg.get('max_storage_mb', 0))
        idle_space_row = QHBoxLayout()
        self.idle_storage_slider = QSlider(Qt.Orientation.Horizontal)
        self.idle_storage_slider.setRange(0, len(STORAGE_SLIDER_STOPS_MB) - 1)
        self.idle_storage_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.idle_storage_slider.setTickInterval(1)
        self.idle_storage_slider.setValue(mb_to_slider_index(cur_idle_mb))
        self.idle_storage_edit = QLineEdit(format_storage_mb_label(cur_idle_mb))
        self.idle_storage_edit.setFixedWidth(165)
        self.idle_storage_edit.setToolTip('Set Experimental Memory storage cap')

        def _on_idle_slider_changed(val: int):
            mb = slider_index_to_mb(val)
            self.idle_storage_edit.setText(format_storage_mb_label(mb))

        def _on_idle_edit_finished():
            mb = parse_storage_mb_text(self.idle_storage_edit.text())
            self.idle_storage_slider.blockSignals(True)
            self.idle_storage_slider.setValue(mb_to_slider_index(mb))
            self.idle_storage_slider.blockSignals(False)
            self.idle_storage_edit.setText(format_storage_mb_label(mb))

        self.idle_storage_slider.valueChanged.connect(_on_idle_slider_changed)
        self.idle_storage_edit.editingFinished.connect(_on_idle_edit_finished)
        idle_space_row.addWidget(QLabel('100 MB'))
        idle_space_row.addWidget(self.idle_storage_slider, 1)
        idle_space_row.addWidget(QLabel('Unlimited'))
        idle_space_row.addWidget(self.idle_storage_edit)
        form.addRow('Experimental Memory space limit:', idle_space_row)

        self.idle_memory_mode_combo = QComboBox()
        self.idle_memory_mode_combo.addItem(
            'Only their own Experimental memory (Isolated — No Normal memory access)',
            'isolated'
        )
        self.idle_memory_mode_combo.addItem(
            'Non-project Shared Memory + their own Experimental memory (Projects off-limits)',
            'non_project'
        )
        self.idle_memory_mode_combo.addItem(
            'Full Shared Memory access (excluding Private projects) + their own Experimental memory',
            'full'
        )
        current_mode = idle_cfg.get('memory_access_mode', 'isolated')
        idx = self.idle_memory_mode_combo.findData(current_mode)
        if idx >= 0:
            self.idle_memory_mode_combo.setCurrentIndex(idx)
        form.addRow('Memory Access in Experimental Mode:', self.idle_memory_mode_combo)
        lay.addLayout(form)

        self.idle_share_code_check = QCheckBox(
            'Share Fairybread source code with agents (Reference + On-Demand Read — allows agents to inspect code and propose improvements)'
        )
        self.idle_share_code_check.setToolTip('Give Experimental Mode agents read-only on-demand access to Fairybread source code')
        self.idle_share_code_check.setChecked(bool(idle_cfg.get('share_source_code', False)))
        lay.addWidget(self.idle_share_code_check)

        from palace_config import get_source_mirror_dir
        from idle_service import sync_source_to_sandbox
        mirror_row = QHBoxLayout()
        mirror_row.addWidget(QLabel('Shared Source Code Mirror Folder:'))
        self.idle_mirror_dir_edit = QLineEdit(str(idle_cfg.get('source_mirror_dir') or get_source_mirror_dir(self.config_path)))
        self.idle_mirror_dir_edit.setToolTip('Read-only folder where a copy of Fairybread source code is kept for AI inspection')
        mirror_browse_btn = QPushButton('Browse…')
        mirror_sync_btn = QPushButton('↻ Sync Code Copy Now')
        mirror_row.addWidget(self.idle_mirror_dir_edit, 1)
        mirror_row.addWidget(mirror_browse_btn)
        mirror_row.addWidget(mirror_sync_btn)
        lay.addLayout(mirror_row)

        def _browse_mirror_dir():
            cur = self.idle_mirror_dir_edit.text().strip() or str(get_source_mirror_dir(self.config_path))
            picked = QFileDialog.getExistingDirectory(self, 'Choose Shared Source Code Mirror Folder', cur)
            if picked and not picked.upper().startswith('M:'):
                self.idle_mirror_dir_edit.setText(picked)

        def _sync_mirror_now():
            target = self.idle_mirror_dir_edit.text().strip()
            if target and not target.upper().startswith('M:'):
                save_idle_settings({'source_mirror_dir': target}, config_path=self.config_path)
            dest = sync_source_to_sandbox(self.config_path)
            QMessageBox.information(self, 'Source Code Mirror Synced', f'Synced read-only Fairybread source code copy to:\n{dest}')

        mirror_browse_btn.clicked.connect(_browse_mirror_dir)
        mirror_sync_btn.clicked.connect(_sync_mirror_now)

        self.idle_live_patch_check = QCheckBox(
            '⚡ Owner-Only: Allow agents to apply live code patches, hot-reboot & auto-continue past reboot'
        )
        self.idle_live_patch_check.setToolTip('Allow Experimental Mode agents to stage verified patches, hot-reboot, and resume automatically')
        self.idle_live_patch_check.setChecked(bool(idle_cfg.get('allow_live_self_modify', False)))
        lay.addWidget(self.idle_live_patch_check)

        from palace_config import IS_DEVELOPER_EDITION
        if not IS_DEVELOPER_EDITION:
            self.idle_share_code_check.setChecked(False)
            self.idle_share_code_check.setEnabled(False)
            self.idle_live_patch_check.setChecked(False)
            self.idle_live_patch_check.setEnabled(False)
            self.idle_mirror_dir_edit.setEnabled(False)
            mirror_browse_btn.setEnabled(False)
            mirror_sync_btn.setEnabled(False)
            pub_notice = QLabel(
                '🔒 Public Edition Notice: Live code self-modification & autopatching are disabled in non-Developer builds '
                'to keep installations verified, consistent, and secure. Have an improvement idea or proposed patch? '
                'Post it on the Fairybread Forum (https://fairybread.me/forum.html) or email bm069au@gmail.com for review.'
            )
            pub_notice.setWordWrap(True)
            pub_notice.setStyleSheet(
                'color: #eab308; background: #29230f; border: 1px solid #854d0e; '
                'padding: 8px 10px; border-radius: 6px; font-size: 11.5px;'
            )
            lay.addWidget(pub_notice)

        self.idle_pause_check = QCheckBox('Pause countdown timer while operator is admitted to discussion')
        self.idle_pause_check.setChecked(bool(idle_cfg.get('pause_when_joined', True)))
        lay.addWidget(self.idle_pause_check)

        lay.addWidget(QLabel('Experimental Mode Startup Prompt (editable charter — customize or restore defaults below):'))
        self.idle_prompt_edit = QTextEdit()
        self.idle_prompt_edit.setAcceptRichText(False)
        self.idle_prompt_edit.setMinimumHeight(105)
        self.idle_prompt_edit.setMaximumHeight(145)
        self.idle_prompt_edit.setPlainText(str(idle_cfg.get('standing_instruction', '')))
        lay.addWidget(self.idle_prompt_edit)

        lay.addWidget(QLabel('Mission Statement, Code of Ethics & Conduct Rules (injected into Experimental Mode):'))
        self.mission_ethics_edit = QTextEdit()
        self.mission_ethics_edit.setAcceptRichText(False)
        self.mission_ethics_edit.setMinimumHeight(105)
        self.mission_ethics_edit.setMaximumHeight(145)
        self.mission_ethics_edit.setPlainText(load_mission_ethics(self.config_path))
        lay.addWidget(self.mission_ethics_edit)

        mem_row = QHBoxLayout()
        used_kb = self.idle_memory.usage_bytes() / 1024.0
        cap_label = format_storage_mb_label(cur_idle_mb)
        self.idle_mem_status_label = QLabel(
            f'Experimental Memory: {self.idle_memory.note_count()} notes ({used_kb:.1f} KB / {cap_label} cap)'
        )
        self.idle_mem_status_label.setObjectName('muted')
        self.idle_mem_status_label.setWordWrap(True)
        mem_row.addWidget(self.idle_mem_status_label, 1)

        reset_defaults_btn = QPushButton('↺ Restore Default Prompts')
        reset_defaults_btn.setToolTip('Reset Experimental prompts to defaults')

        def _restore_idle_defaults():
            from palace_config import DEFAULT_IDLE_INSTRUCTION, DEFAULT_MISSION_ETHICS
            self.idle_prompt_edit.setPlainText(DEFAULT_IDLE_INSTRUCTION)
            self.mission_ethics_edit.setPlainText(DEFAULT_MISSION_ETHICS)

        reset_defaults_btn.clicked.connect(_restore_idle_defaults)
        mem_row.addWidget(reset_defaults_btn)

        clear_idle_btn = QPushButton('Clear Experimental Memory')
        clear_idle_btn.setToolTip('Clear all Experimental Memory notes')
        clear_idle_btn.clicked.connect(self._clear_idle_memory)
        mem_row.addWidget(clear_idle_btn)
        lay.addLayout(mem_row)

        self.pages.addWidget(w)

    def _build_permissions_page(self):
        from fairybread_mcp import (
            EXTERNAL_PLATFORMS,
            get_mcp_json_snippet,
            get_mcp_server_entry,
            get_platform_copy_snippet,
            link_platform_foreman,
            load_bridge_settings,
            test_mcp_bridge_live,
            unlink_platform_foreman,
        )
        from local_cli_provider import detect_external_platforms

        w, outer_lay = self._make_simple_page(
            '🔗 External Agent Bridge (MCP)',
            'Connect ChatGPT Desktop / Codex, Google Antigravity, Grok (xAI), or Claude Desktop — pick either Foreman Mode or Council Member Mode per app.'
        )
        b_cfg = load_bridge_settings(self.config_path)
        home_override = getattr(self, '_bridge_home_dir', None)
        appdata_override = getattr(self, '_bridge_appdata_dir', None)
        detected = detect_external_platforms(home_dir=home_override, appdata_dir=appdata_override)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 4)
        lay.setSpacing(10)

        # Card 1: Clear built-in guide explaining Foreman vs Council Member modes & benefits
        guide_card = QFrame()
        guide_card.setObjectName('externalBridgeGuideCard')
        guide_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        g_lay = QVBoxLayout(guide_card)
        g_lay.setSpacing(6)
        guide_hdr = QLabel('<b>How External AI Links Work — Pick One Mode Per App</b>')
        guide_hdr.setTextFormat(Qt.TextFormat.RichText)
        g_lay.addWidget(guide_hdr)

        self.bridge_guide_label = QLabel(
            '• <b>Foreman Mode (External AI drives Fairybread):</b> Stay inside ChatGPT Desktop, Antigravity, Grok, or Claude '
            'and outsource jobs to Fairybread — multi-AI peer-reviewed answers, 300-DPI graphics, Shared Memory lookups, and '
            'exhaustive email searches. <i>Setup:</i> Flip <b>Foreman</b> ON (Fairybread writes the config automatically), '
            'restart that app once, then ask it to use Fairybread.<br>'
            '• <b>Council Member Mode (External AI joins Fairybread\'s Council):</b> Use your existing local CLI subscription '
            '(<code>codex</code>, <code>agy</code>, <code>grok</code>, <code>claude</code>) inside Fairybread\'s council '
            'without paying for a separate per-token API key. <i>Setup:</i> Install and sign in to that CLI once, then flip '
            '<b>Council Member</b> ON. <i>(Tip: direct API keys in AI Providers are faster when you have them.)</i><br>'
            '• <b>One-or-the-Other Safety Rule:</b> Turning one switch ON automatically locks (greys out) the other for that '
            'app so an AI can never trigger an infinite feedback loop. Turn the active switch OFF first to switch roles.'
        )
        self.bridge_guide_label.setTextFormat(Qt.TextFormat.RichText)
        self.bridge_guide_label.setWordWrap(True)
        self.bridge_guide_label.setStyleSheet('color: #c9d1d9; font-size: 12px; line-height: 1.45;')
        g_lay.addWidget(self.bridge_guide_label)
        lay.addWidget(guide_card)

        # Card 2: Platform Link Cards
        self.bridge_platform_controls: dict[str, dict[str, Any]] = {}
        platform_meta = {
            'codex': {
                'title': 'ChatGPT Desktop / Codex CLI',
                'note': 'Writes ~/.codex/config.toml → restart ChatGPT Desktop → switch to Codex / Work mode → type /mcp. (Standard browser chat cannot access local tools.)',
            },
            'antigravity': {
                'title': 'Google Antigravity',
                'note': 'Writes ~/.gemini/config/mcp_config.json + SKILL.md → restart Antigravity to see fairybread_* tools natively.',
            },
            'grok': {
                'title': 'Grok (xAI Build CLI / Grok Bot)',
                'note': 'Writes ~/.grok/config.toml for Grok Build CLI or Grok Bot (x.ai/bot). Plain grok.com browser chat cannot access local tools.',
            },
            'claude': {
                'title': 'Claude Desktop / Claude Code CLI',
                'note': 'Writes %APPDATA%\\Claude\\claude_desktop_config.json → restart Claude Desktop.',
            },
        }

        chk_style = (
            'QCheckBox { color: #e6edf3; font-size: 12px; font-weight: 600; spacing: 6px; } '
            'QCheckBox:disabled { color: #6e7681; }'
        )

        self.bridge_status_label = QLabel('')
        self.bridge_status_label.setWordWrap(True)
        self.bridge_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')

        def _format_badge(pk: str, info: dict[str, Any], linked: bool) -> str:
            parts = [
                'App Config Found' if (info.get('config_dir_exists') or info.get('config_file_exists')) else 'App Not Detected',
                'CLI Ready' if info.get('cli_available') else 'CLI Not Installed',
            ]
            if linked:
                parts.append('MCP Linked')
            return ' · '.join(parts)

        saved_platforms = b_cfg.get('platforms') or {}

        for pk in EXTERNAL_PLATFORMS:
            info = detected.get(pk, {})
            meta = platform_meta[pk]
            card = QFrame()
            card.setObjectName(f'bridgePlatformCard_{pk}')
            card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
            c_lay = QVBoxLayout(card)
            c_lay.setSpacing(6)

            top_row = QHBoxLayout()
            title_lbl = QLabel(f"<b>{html.escape(meta['title'])}</b>")
            title_lbl.setTextFormat(Qt.TextFormat.RichText)
            top_row.addWidget(title_lbl, 1)

            badge_lbl = QLabel(_format_badge(pk, info, bool(info.get('mcp_linked'))))
            badge_lbl.setStyleSheet(
                'font-size: 11px; color: #9ca3af; background: #0d1117; '
                'border: 1px solid #21262d; border-radius: 5px; padding: 2px 8px;'
            )
            top_row.addWidget(badge_lbl)
            c_lay.addLayout(top_row)

            switch_row = QHBoxLayout()
            switch_row.setSpacing(14)
            foreman_chk = QCheckBox('Foreman Mode (Drives Fairybread)')
            foreman_chk.setStyleSheet(chk_style)
            council_chk = QCheckBox('Council Member (Joins Council)')
            council_chk.setStyleSheet(chk_style)

            saved_mode = str(saved_platforms.get(pk, 'off') or 'off').lower()
            is_foreman_init = (saved_mode == 'foreman') or bool(info.get('mcp_linked'))
            cli_avail = bool(info.get('cli_available'))
            is_council_init = (not is_foreman_init) and (saved_mode == 'council') and cli_avail

            foreman_chk.setChecked(is_foreman_init)
            council_chk.setChecked(is_council_init)

            switch_row.addWidget(foreman_chk)
            switch_row.addWidget(council_chk)
            switch_row.addStretch()

            if pk == 'grok':
                copy_grok_btn = QPushButton('📋 Copy Command')
                copy_grok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                copy_grok_btn.setToolTip('Copy TOML and command/args for Grok Bot custom connector setup')

                def _copy_grok_cmd():
                    entry = get_mcp_server_entry()
                    snippet = get_platform_copy_snippet('grok')
                    QApplication.clipboard().setText(
                        f"{snippet}\n# Command: {entry['command']}\n# Args: {entry['args'][0]}"
                    )
                    self.bridge_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
                    self.bridge_status_label.setText('✓ Copied Grok MCP config and command/args to clipboard.')

                copy_grok_btn.clicked.connect(_copy_grok_cmd)
                switch_row.addWidget(copy_grok_btn)

            c_lay.addLayout(switch_row)

            note_lbl = QLabel(meta['note'])
            note_lbl.setWordWrap(True)
            note_lbl.setObjectName('muted')
            note_lbl.setStyleSheet('font-size: 11.5px; color: #8b949e;')
            c_lay.addWidget(note_lbl)

            self.bridge_platform_controls[pk] = {
                'foreman': foreman_chk,
                'council': council_chk,
                'badge': badge_lbl,
                'hint': note_lbl,
                'info': info,
                'cli_available': cli_avail,
                'install_hint': str(info.get('install_hint') or ''),
                'title': meta['title'],
            }

            foreman_chk.toggled.connect(lambda checked, p=pk: self._on_bridge_foreman_toggled(p, checked))
            council_chk.toggled.connect(lambda checked, p=pk: self._on_bridge_council_toggled(p, checked))
            self._sync_platform_interlock(pk)

            lay.addWidget(card)

        # Card 3: Shared MCP Capabilities & Diagnostics
        cap_card = QFrame()
        cap_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        cap_lay = QVBoxLayout(cap_card)
        cap_lay.setSpacing(6)
        cap_hdr = QLabel('<b>Shared Bridge Capabilities &amp; Diagnostics</b>')
        cap_hdr.setTextFormat(Qt.TextFormat.RichText)
        cap_lay.addWidget(cap_hdr)

        self.bridge_enabled_check = QCheckBox(
            'Enable External Agent Bridge (MCP Server && Local CLI Bridge)',
            checked=bool(b_cfg.get('enabled', True)),
        )
        cap_lay.addWidget(self.bridge_enabled_check)

        self.bridge_council_check = QCheckBox(
            'Allow external agents to consult the Fairybread Multi-AI Council (fairybread_ask_council)',
            checked=bool(b_cfg.get('allow_council_query', True)),
        )
        cap_lay.addWidget(self.bridge_council_check)

        self.bridge_image_check = QCheckBox(
            'Allow external agents to render 300-DPI images, social banners && wallpapers (fairybread_generate_image)',
            checked=bool(b_cfg.get('allow_image_generation', True)),
        )
        cap_lay.addWidget(self.bridge_image_check)

        self.bridge_email_check = QCheckBox(
            'Allow external agents to run Exhaustive Email Searches when configured (fairybread_search_email)',
            checked=bool(b_cfg.get('allow_email_search', True)),
        )
        cap_lay.addWidget(self.bridge_email_check)

        self.bridge_memory_check = QCheckBox(
            'Allow external agents to query Shared Memory (fairybread_search_memory)',
            checked=bool(b_cfg.get('allow_memory_search', True)),
        )
        cap_lay.addWidget(self.bridge_memory_check)

        btn_row = QHBoxLayout()
        test_bridge_btn = QPushButton('🧪 Test MCP Bridge')
        test_bridge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_bridge_btn.setToolTip('Spawn python.exe fairybread_mcp.py over stdio and verify initialize, tools/list, and fairybread_status')
        copy_mcp_btn = QPushButton('📋 Copy Generic MCP JSON (Cursor / Windsurf)')
        copy_mcp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_mcp_btn.setToolTip('Copy generic stdio JSON config (uses console python.exe)')
        btn_row.addWidget(test_bridge_btn)
        btn_row.addWidget(copy_mcp_btn)
        cap_lay.addLayout(btn_row)
        cap_lay.addWidget(self.bridge_status_label)

        def _run_bridge_test():
            self._save_bridge_fields()
            ok, msg = test_mcp_bridge_live()
            self.bridge_status_label.setStyleSheet(f'font-size: 12px; color: {"#22c55e" if ok else "#f85149"};')
            self.bridge_status_label.setText(f'{"✓" if ok else "⚠"} {msg}')

        def _copy_mcp():
            self._save_bridge_fields()
            QApplication.clipboard().setText(get_mcp_json_snippet())
            self.bridge_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
            self.bridge_status_label.setText('✓ Copied generic MCP JSON snippet (using python.exe) to clipboard.')

        test_bridge_btn.clicked.connect(_run_bridge_test)
        copy_mcp_btn.clicked.connect(_copy_mcp)
        lay.addWidget(cap_card)

        priv_lbl = QLabel(
            '<b>Idle Mode Privacy &amp; Storage Boundaries:</b>\n'
            '• Idle Mode live transcripts are strictly isolated from Normal Mode.\n'
            '• Shared Idle Memory is capped by your Idle storage slider.'
        )
        priv_lbl.setWordWrap(True)
        lay.addWidget(priv_lbl)
        lay.addStretch()

        scroll.setWidget(inner)
        outer_lay.addWidget(scroll, 1)
        self.pages.addWidget(w)

    def _sync_platform_interlock(self, platform_key: str):
        ctrl = getattr(self, 'bridge_platform_controls', {}).get(platform_key)
        if not ctrl:
            return
        foreman_chk: QCheckBox = ctrl['foreman']
        council_chk: QCheckBox = ctrl['council']
        cli_avail = bool(ctrl.get('cli_available', False))
        install_hint = str(ctrl.get('install_hint') or '')

        if foreman_chk.isChecked():
            council_chk.blockSignals(True)
            council_chk.setChecked(False)
            council_chk.blockSignals(False)
            council_chk.setEnabled(False)
            council_chk.setToolTip('Turn Foreman Mode OFF first to switch roles (prevents feedback loops)')
            foreman_chk.setEnabled(True)
            foreman_chk.setToolTip('Foreman Mode active — turn OFF to unlink MCP config and unlock Council Member')
        elif council_chk.isChecked():
            foreman_chk.blockSignals(True)
            foreman_chk.setChecked(False)
            foreman_chk.blockSignals(False)
            foreman_chk.setEnabled(False)
            foreman_chk.setToolTip('Turn Council Member OFF first to switch roles (prevents feedback loops)')
            council_chk.setEnabled(True)
            council_chk.setToolTip('Council Member active — turn OFF to unlock Foreman Mode')
        else:
            foreman_chk.setEnabled(True)
            foreman_chk.setToolTip('Link Fairybread MCP so this app can drive Fairybread (locks Council Member while ON)')
            council_chk.setEnabled(cli_avail)
            if cli_avail:
                council_chk.setToolTip('Add this local CLI inside Fairybread Council (locks Foreman Mode while ON)')
            else:
                council_chk.setToolTip(f'CLI not installed. {install_hint}')

    def _on_bridge_foreman_toggled(self, platform_key: str, checked: bool):
        from fairybread_mcp import link_platform_foreman, unlink_platform_foreman

        ctrl = getattr(self, 'bridge_platform_controls', {}).get(platform_key)
        if not ctrl:
            return
        foreman_chk: QCheckBox = ctrl['foreman']
        council_chk: QCheckBox = ctrl['council']
        badge_lbl: QLabel = ctrl['badge']
        info = dict(ctrl.get('info') or {})
        home_override = getattr(self, '_bridge_home_dir', None)
        appdata_override = getattr(self, '_bridge_appdata_dir', None)

        if checked:
            council_chk.blockSignals(True)
            council_chk.setChecked(False)
            council_chk.blockSignals(False)
            ok, msg = link_platform_foreman(
                platform_key,
                home_dir=home_override,
                appdata_dir=appdata_override,
            )
            if not ok:
                foreman_chk.blockSignals(True)
                foreman_chk.setChecked(False)
                foreman_chk.blockSignals(False)
                self.bridge_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                self.bridge_status_label.setText(f'⚠ {msg}')
            else:
                self.bridge_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')
                self.bridge_status_label.setText(f'✓ {msg}')
                info['mcp_linked'] = True
        else:
            ok, msg = unlink_platform_foreman(
                platform_key,
                home_dir=home_override,
                appdata_dir=appdata_override,
            )
            if not ok:
                foreman_chk.blockSignals(True)
                foreman_chk.setChecked(True)
                foreman_chk.blockSignals(False)
                self.bridge_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                self.bridge_status_label.setText(f'⚠ {msg}')
            else:
                self.bridge_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
                self.bridge_status_label.setText(f'✓ {msg}')
                info['mcp_linked'] = False

        ctrl['info'] = info
        parts = [
            'App Config Found' if (info.get('config_dir_exists') or info.get('config_file_exists')) else 'App Not Detected',
            'CLI Ready' if ctrl.get('cli_available') else 'CLI Not Installed',
        ]
        if info.get('mcp_linked'):
            parts.append('MCP Linked')
        badge_lbl.setText(' · '.join(parts))
        self._sync_platform_interlock(platform_key)

    def _on_bridge_council_toggled(self, platform_key: str, checked: bool):
        ctrl = getattr(self, 'bridge_platform_controls', {}).get(platform_key)
        if not ctrl:
            return
        self._sync_platform_interlock(platform_key)
        title = ctrl.get('title', platform_key)
        if checked:
            self.bridge_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')
            self.bridge_status_label.setText(
                f'✓ {title} set to Council Member (Foreman Mode locked). Click Save to add it to the Council.'
            )
        else:
            self.bridge_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
            self.bridge_status_label.setText(f'✓ {title} Council Member OFF — Foreman Mode unlocked.')

    def _save_bridge_fields(self):
        from fairybread_mcp import EXTERNAL_PLATFORMS, save_bridge_settings
        if not hasattr(self, 'bridge_enabled_check'):
            return
        platforms_payload: dict[str, str] = {}
        controls = getattr(self, 'bridge_platform_controls', {})
        for pk in EXTERNAL_PLATFORMS:
            ctrl = controls.get(pk)
            if not ctrl:
                continue
            if ctrl['foreman'].isChecked():
                platforms_payload[pk] = 'foreman'
            elif ctrl['council'].isChecked():
                platforms_payload[pk] = 'council'
            else:
                platforms_payload[pk] = 'off'
        save_bridge_settings(
            {
                'enabled': self.bridge_enabled_check.isChecked(),
                'allow_council_query': self.bridge_council_check.isChecked(),
                'allow_image_generation': self.bridge_image_check.isChecked(),
                'allow_email_search': self.bridge_email_check.isChecked(),
                'allow_memory_search': self.bridge_memory_check.isChecked(),
                'platforms': platforms_payload,
            },
            config_path=self.config_path,
        )

    def _build_backup_restore_page(self):
        from backup_service import (
            create_full_backup_zip,
            get_palace_appdata_root,
            inspect_backup_zip,
            restore_full_backup_zip,
        )
        from palace_config import (
            STORAGE_SLIDER_STOPS_MB,
            compute_palace_storage_stats,
            format_storage_mb_label,
            list_palace_stored_files,
            mb_to_slider_index,
            move_palace_data_to_directory,
            parse_storage_mb_text,
            slider_index_to_mb,
        )

        w, lay = self._make_simple_page(
            '📦 Storage, Files & Password-Locked Backup',
            'Manage Normal Mode drive space & optional cap, move Fairybread Memory to another drive/folder, '
            'download or delete stored files & pictures, and create password-locked AES-256 backups.'
        )

        ui_cfg = load_ui_settings(self.config_path)
        stats = compute_palace_storage_stats(self.config_path)

        # --- 1. NORMAL MODE DRIVE SPACE SLIDER + LIVE USAGE & CAP WARNING ---
        space_grp = QFrame()
        space_grp.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:8px;')
        sp_lay = QVBoxLayout(space_grp)
        sp_lay.setSpacing(6)
        self.normal_space_summary_lbl = QLabel()
        self.normal_space_summary_lbl.setWordWrap(True)
        self.normal_space_summary_lbl.setTextFormat(Qt.TextFormat.RichText)
        sp_lay.addWidget(self.normal_space_summary_lbl)

        cur_norm_mb = int(ui_cfg.get('normal_max_storage_mb', 0))
        norm_slider_row = QHBoxLayout()
        norm_slider_row.addWidget(QLabel('Normal Mode Cap:'))
        norm_slider_row.addWidget(QLabel('100 MB'))
        self.normal_storage_slider = QSlider(Qt.Orientation.Horizontal)
        self.normal_storage_slider.setRange(0, len(STORAGE_SLIDER_STOPS_MB) - 1)
        self.normal_storage_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.normal_storage_slider.setTickInterval(1)
        self.normal_storage_slider.setValue(mb_to_slider_index(cur_norm_mb))
        self.normal_storage_edit = QLineEdit(format_storage_mb_label(cur_norm_mb))
        self.normal_storage_edit.setFixedWidth(165)

        def _refresh_storage_summary_labels():
            st = compute_palace_storage_stats(self.config_path)
            cap_mb = parse_storage_mb_text(self.normal_storage_edit.text())
            cap_txt = format_storage_mb_label(cap_mb)
            mem_mb = st['memory_db_bytes'] / (1024 * 1024)
            chat_mb = st['sessions_bytes'] / (1024 * 1024)
            up_mb = st['uploaded_files_bytes'] / (1024 * 1024)
            img_mb = st['generated_images_bytes'] / (1024 * 1024)
            tot_mb = st['normal_total_mb']
            warn_html = ''
            if cap_mb > 0:
                pct = (tot_mb / float(cap_mb)) * 100.0
                if pct >= 100.0:
                    warn_html = f'<br><span style="color:#f85149; font-weight:700;">⚠ DATA LIMIT REACHED ({pct:.1f}% of {cap_txt}): Delete old files below, raise your cap, or move Fairybread data to another drive!</span>'
                elif pct >= 85.0:
                    warn_html = f'<br><span style="color:#d29922; font-weight:700;">⚠ Approaching Data Limit ({pct:.1f}% of {cap_txt} used).</span>'
            self.normal_space_summary_lbl.setText(
                f'<b>💾 Normal Mode Drive Space Used: {tot_mb:.2f} MB / {cap_txt}</b> '
                f'<span style="color:#8b949e; font-size:12px;">'
                f'(Memory DB: {mem_mb:.2f} MB · Chats: {chat_mb:.2f} MB · Uploaded Files: {up_mb:.2f} MB · Pictures: {img_mb:.2f} MB)'
                f'</span>{warn_html}'
            )

        def _on_norm_slider(val: int):
            mb = slider_index_to_mb(val)
            self.normal_storage_edit.setText(format_storage_mb_label(mb))
            _refresh_storage_summary_labels()

        def _on_norm_edit():
            mb = parse_storage_mb_text(self.normal_storage_edit.text())
            self.normal_storage_slider.blockSignals(True)
            self.normal_storage_slider.setValue(mb_to_slider_index(mb))
            self.normal_storage_slider.blockSignals(False)
            self.normal_storage_edit.setText(format_storage_mb_label(mb))
            _refresh_storage_summary_labels()

        self.normal_storage_slider.valueChanged.connect(_on_norm_slider)
        self.normal_storage_edit.editingFinished.connect(_on_norm_edit)
        norm_slider_row.addWidget(self.normal_storage_slider, 1)
        norm_slider_row.addWidget(QLabel('Unlimited'))
        norm_slider_row.addWidget(self.normal_storage_edit)
        sp_lay.addLayout(norm_slider_row)

        # --- 2. MOVE FAIRYBREAD MEMORY LOCATION (DIFFERENT DRIVE / FOLDER) ---
        loc_row = QHBoxLayout()
        loc_row.addWidget(QLabel('Fairybread Storage Folder:'))
        self.palace_data_dir_edit = QLineEdit(str(stats['data_root']))
        loc_browse_btn = QPushButton('Browse Drive/Folder…')
        loc_move_btn = QPushButton('🚚 Move Fairybread Data Here')
        loc_move_btn.setToolTip('Copy all Fairybread Memory, Chats, Uploaded Files & Pictures to the selected drive/folder')
        loc_row.addWidget(self.palace_data_dir_edit, 1)
        loc_row.addWidget(loc_browse_btn)
        loc_row.addWidget(loc_move_btn)
        sp_lay.addLayout(loc_row)
        lay.addWidget(space_grp)

        def _browse_data_dir():
            chosen = QFileDialog.getExistingDirectory(self, 'Select Folder / Drive for Fairybread Memory Storage', self.palace_data_dir_edit.text())
            if chosen:
                self.palace_data_dir_edit.setText(chosen)

        def _move_data_dir():
            target_dir = self.palace_data_dir_edit.text().strip()
            if not target_dir:
                return
            try:
                res = move_palace_data_to_directory(target_dir, config_path=self.config_path)
                self.backup_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')
                self.backup_status_label.setText(
                    f'✓ Moved {res["moved_files"]} Fairybread files to {res["new_root"]}. Active storage updated!'
                )
                _refresh_storage_summary_labels()
                _refresh_stored_files_list()
            except Exception as exc:
                self.backup_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                self.backup_status_label.setText(f'⚠ Could not move Fairybread data: {exc}')

        loc_browse_btn.clicked.connect(_browse_data_dir)
        loc_move_btn.clicked.connect(_move_data_dir)

        # --- 3. MANAGE STORED FILES & PICTURES (DOWNLOAD OR DELETE OLD FILES) ---
        files_hdr = QLabel('<b>🗂 Stored Fairybread Files &amp; Pictures (Retrieve / Download or Delete Old Files Taking Up Space):</b>')
        files_hdr.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(files_hdr)

        self.stored_files_list = QListWidget()
        self.stored_files_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.stored_files_list.setMinimumHeight(110)
        self.stored_files_list.setMaximumHeight(145)
        lay.addWidget(self.stored_files_list)

        def _refresh_stored_files_list():
            self.stored_files_list.clear()
            for item in list_palace_stored_files(self.config_path):
                lbl = f"[{item['category']}]  {item['name']}   ({item['size_kb']:.1f} KB · {item['modified']})"
                lw = QListWidgetItem(lbl)
                lw.setData(Qt.ItemDataRole.UserRole, item['path'])
                self.stored_files_list.addItem(lw)

        file_btn_row = QHBoxLayout()
        dl_file_btn = QPushButton('💾 Download / Save Selected As…')
        open_file_btn = QPushButton('🔍 Open / View Selected')
        del_file_btn = QPushButton('🗑 Delete Selected Files')
        refresh_files_btn = QPushButton('↻ Refresh List')
        file_btn_row.addWidget(dl_file_btn)
        file_btn_row.addWidget(open_file_btn)
        file_btn_row.addWidget(del_file_btn)
        file_btn_row.addWidget(refresh_files_btn)
        file_btn_row.addStretch()
        lay.addLayout(file_btn_row)

        def _download_selected():
            sel = self.stored_files_list.selectedItems()
            if not sel:
                return
            for s_item in sel:
                src_p = Path(str(s_item.data(Qt.ItemDataRole.UserRole)))
                if not src_p.exists():
                    continue
                dest_str, _ = QFileDialog.getSaveFileName(self, f'Save {src_p.name} As', str(Path.home() / 'Downloads' / src_p.name))
                if dest_str:
                    import shutil
                    shutil.copy2(src_p, dest_str)
                    self.backup_status_label.setText(f'✓ Downloaded {src_p.name} to {dest_str}')

        def _open_selected():
            sel = self.stored_files_list.selectedItems()
            if not sel:
                return
            src_p = Path(str(sel[0].data(Qt.ItemDataRole.UserRole)))
            if src_p.exists() and hasattr(os, 'startfile'):
                os.startfile(str(src_p))

        def _delete_selected():
            sel = self.stored_files_list.selectedItems()
            if not sel:
                return
            reclaimed = 0
            deleted_n = 0
            for s_item in sel:
                src_p = Path(str(s_item.data(Qt.ItemDataRole.UserRole)))
                if src_p.exists():
                    try:
                        reclaimed += src_p.stat().st_size
                        src_p.unlink()
                        deleted_n += 1
                    except OSError:
                        pass
            _refresh_stored_files_list()
            _refresh_storage_summary_labels()
            self.backup_status_label.setText(f'✓ Deleted {deleted_n} file(s), freed {reclaimed / 1024.0:.1f} KB.')

        dl_file_btn.clicked.connect(_download_selected)
        open_file_btn.clicked.connect(_open_selected)
        del_file_btn.clicked.connect(_delete_selected)
        refresh_files_btn.clicked.connect(lambda: (_refresh_stored_files_list(), _refresh_storage_summary_labels()))

        # --- 4. PASSWORD-LOCKED AES-256 BACKUP & RESTORE ---
        bak_hdr = QLabel('<b>🔐 Password-Locked Backup &amp; Restore (Shared Memory + Settings &amp; API Keys):</b>')
        bak_hdr.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(bak_hdr)

        chk_row = QHBoxLayout()
        self.backup_include_memory_check = QCheckBox('Shared Memory, Chats && Idle Memory', checked=True)
        self.backup_include_settings_check = QCheckBox('All Settings && API Keys (AES-256 Password Locked)', checked=True)
        self.backup_include_images_check = QCheckBox('Generated PNG Pictures', checked=True)
        self.backup_include_creds_check = self.backup_include_settings_check
        chk_row.addWidget(self.backup_include_memory_check)
        chk_row.addWidget(self.backup_include_settings_check)
        chk_row.addWidget(self.backup_include_images_check)
        lay.addLayout(chk_row)

        pw_row = QHBoxLayout()
        pw_row.addWidget(QLabel('🔑 Backup / Restore Password (protects API keys across PCs):'))
        self.backup_password_edit = QLineEdit()
        self.backup_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.backup_password_edit.setPlaceholderText('Enter password to lock/unlock API keys inside backup archive…')
        pw_row.addWidget(self.backup_password_edit, 1)
        lay.addLayout(pw_row)

        btn_row = QHBoxLayout()
        export_btn = QPushButton('📦 Create Backup Archive (.zip)…')
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restore_btn = QPushButton('♻ Restore From Backup Archive (.zip)…')
        restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restore_defaults_btn = QPushButton('↺ Restore Default Settings…')
        restore_defaults_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restore_defaults_btn.setToolTip('Reset app settings to factory defaults while keeping Memory Palaces, chats, API keys, and Write Exclusions')
        btn_row.addWidget(export_btn)
        btn_row.addWidget(restore_btn)
        btn_row.addWidget(restore_defaults_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self.backup_status_label = QLabel(
            f'Active Config: {self.config_path}  |  Active Data Root: {get_palace_appdata_root()}'
        )
        self.backup_status_label.setWordWrap(True)
        self.backup_status_label.setStyleSheet('font-size: 12px; color: #8b949e;')
        lay.addWidget(self.backup_status_label)

        def _do_export():
            from datetime import datetime
            pw = self.backup_password_edit.text().strip()
            inc_settings = self.backup_include_settings_check.isChecked()
            if inc_settings and not pw:
                pw_in, ok = QInputDialog.getText(
                    self,
                    'Set Backup Password for API Keys',
                    'Because this backup contains your API keys, enter a password to encrypt them (AES-256-GCM):',
                    QLineEdit.EchoMode.Password,
                )
                if not ok or not pw_in.strip():
                    self.backup_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                    self.backup_status_label.setText('⚠ Backup cancelled: a password is required when backing up API keys.')
                    return
                pw = pw_in.strip()
                self.backup_password_edit.setText(pw)

            default_name = f"Fairybread_Full_Backup_{datetime.now().strftime('%Y-%m-%d_%H%M')}.zip"
            dest_str, _ = QFileDialog.getSaveFileName(
                self,
                'Save Fairybread Backup Archive',
                str(Path.home() / 'Documents' / default_name),
                'ZIP Archives (*.zip)',
            )
            if not dest_str:
                return
            try:
                manifest = create_full_backup_zip(
                    Path(dest_str),
                    config_path=self.config_path,
                    include_memory=self.backup_include_memory_check.isChecked(),
                    include_settings=inc_settings,
                    include_generated_images=self.backup_include_images_check.isChecked(),
                    include_credentials=inc_settings,
                    backup_password=pw,
                )
                lock_tag = 'AES-256 Password-Locked' if manifest.get('password_protected') else 'No API keys'
                self.backup_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')
                self.backup_status_label.setText(
                    f'✓ Backup saved ({manifest["file_count"]} files, {lock_tag}, SHA-256 verified):\n{dest_str}'
                )
            except Exception as exc:
                self.backup_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                self.backup_status_label.setText(f'⚠ Backup failed: {exc}')

        def _do_restore():
            src_str, _ = QFileDialog.getOpenFileName(
                self,
                'Select Fairybread Backup Archive to Restore',
                str(Path.home() / 'Documents'),
                'ZIP Archives (*.zip)',
            )
            if not src_str:
                return
            try:
                info = inspect_backup_zip(Path(src_str))
                pw = self.backup_password_edit.text().strip()
                if info.get('password_protected') and self.backup_include_settings_check.isChecked() and not pw:
                    pw_in, ok = QInputDialog.getText(
                        self,
                        'Unlock Password-Protected Backup',
                        'Enter the backup password to unlock and restore your API keys:',
                        QLineEdit.EchoMode.Password,
                    )
                    if not ok:
                        return
                    pw = pw_in.strip()
                    self.backup_password_edit.setText(pw)

                summary = restore_full_backup_zip(
                    Path(src_str),
                    config_path=self.config_path,
                    backup_password=pw,
                    restore_memory=self.backup_include_memory_check.isChecked(),
                    restore_settings=self.backup_include_settings_check.isChecked(),
                )
                if summary.get('password_unlocked'):
                    cred_note = f"Unlocked & re-sealed {summary.get('restored_keys_count', 0)} API keys into Windows DPAPI."
                elif not summary.get('skipped_credentials'):
                    cred_note = 'Settings restored.'
                else:
                    cred_note = 'Different PC detected: re-enter API keys in AI Providers.'
                self.backup_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')
                self.backup_status_label.setText(
                    f'✓ Restored {summary["restored_files"]} files from archive ({summary["created_at"]}). {cred_note}'
                )
                _refresh_storage_summary_labels()
                _refresh_stored_files_list()
                parent = self.parent()
                if parent is not None:
                    if hasattr(parent, 'reload_providers_from_config'):
                        parent.reload_providers_from_config()
                    if hasattr(parent, 'refresh_projects'):
                        parent.refresh_projects()
                    if hasattr(parent, 'refresh_sessions'):
                        parent.refresh_sessions()
                    if hasattr(parent, 'load_history'):
                        parent.load_history()
            except Exception as exc:
                self.backup_status_label.setStyleSheet('font-size: 12px; color: #f85149;')
                self.backup_status_label.setText(f'⚠ Restore failed: {exc}')

        def _do_restore_defaults():
            rd = RestoreDefaultSettingsDialog(
                self,
                config_path=self.config_path,
                bridge_home_dir=self._bridge_home_dir,
                bridge_appdata_dir=self._bridge_appdata_dir,
            )
            if rd.exec() == QDialog.DialogCode.Accepted:
                self._restore_defaults_result = rd.reset_result
                bak_p = rd.reset_result.get('backup_path') or ''
                self.backup_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')
                self.backup_status_label.setText(
                    f'✓ Default settings restored (Memory & API keys kept). Pre-reset backup: {bak_p}'
                )
                self._stop_settings_mic_test()
                self.accept()

        export_btn.clicked.connect(_do_export)
        restore_btn.clicked.connect(_do_restore)
        restore_defaults_btn.clicked.connect(_do_restore_defaults)
        _refresh_storage_summary_labels()
        _refresh_stored_files_list()

        lay.addStretch()
        self.pages.addWidget(w)

    def _clear_idle_memory(self):
        self.idle_memory.clear_all()
        self.idle_mem_status_label.setText(
            'AI-Only Permanent Idle Memory: 0 notes (0.0 KB / 10 MB cap) · Accessible only in Idle Mode'
        )

    def _auto_save_current_provider(self, *_args):
        if getattr(self, '_loading_provider_fields', False):
            return
        name = (getattr(self, '_active_provider_slug', '') or self.provider_combo.currentText()).strip().lower()
        if not name:
            return
        api_key = self.api_key_edit.text().strip()
        if api_key:
            try:
                self.credential_store.set_api_key(name, api_key)
            except Exception:
                pass
        try:
            save_provider_config(
                provider_name=name,
                enabled=self.enabled_check.isChecked(),
                model=self.model_edit.text(),
                base_url=self.base_url_edit.text(),
                config_path=self.config_path,
            )
            if hasattr(self, 'auto_save_status_label'):
                disp = PROVIDER_CATALOG.get(name, {}).get('display_name', name)
                self.auto_save_status_label.setText(f'✓ Auto-saved {disp} (Windows DPAPI encrypted)')
            parent = self.parent()
            if parent is not None and hasattr(parent, 'reload_providers_from_config'):
                parent.reload_providers_from_config()
        except Exception:
            pass

    def _fetch_live_models_for_current_provider(self):
        from palace_config import fetch_live_provider_models
        clean = (getattr(self, '_active_provider_slug', '') or self.provider_combo.currentText()).strip().lower()
        if not clean:
            return
        key = self.api_key_edit.text().strip()
        if not key:
            try:
                key = self.credential_store.get_api_key(clean) or ''
            except Exception:
                key = ''
        models = fetch_live_provider_models(clean, key, self.base_url_edit.text().strip())
        if models and hasattr(self, 'model_combo'):
            cur_text = self.model_edit.text().strip()
            self._loading_provider_fields = True
            try:
                self.model_combo.clear()
                for m in models:
                    self.model_combo.addItem(m)
                if cur_text and cur_text in models:
                    self.model_combo.setCurrentText(cur_text)
                elif models:
                    self.model_combo.setCurrentText(models[0])
            finally:
                self._loading_provider_fields = False
            self._auto_save_current_provider()
            if hasattr(self, 'auto_save_status_label'):
                self.auto_save_status_label.setText(f'✓ Loaded {len(models)} live models from {clean.capitalize()} API')

    def _load_selected_provider(self, name: str):
        clean = name.strip().lower()
        self._loading_provider_fields = True
        try:
            configs = load_provider_configs(self.config_path)
            cfg = configs.get(clean, {})
            cat = PROVIDER_CATALOG.get(clean, {})
            self._active_provider_slug = clean

            disp = cat.get('display_name', clean.capitalize())
            billing = cat.get('billing_note', 'Custom OpenAI-compatible provider.')
            sugg = list(cat.get('suggested_models', []))
            sugg_txt = ', '.join(sugg[:3])
            info_txt = f'{disp} — {billing}' + (f'  (Models: {sugg_txt})' if sugg_txt else '')
            if hasattr(self, 'provider_billing_label'):
                self.provider_billing_label.setText(info_txt)
            if hasattr(self, 'get_key_portal_btn'):
                self.get_key_portal_btn.setText(f'🔑 Get {disp.split()[0]} Key ↗')

            has_key = False
            try:
                has_key = bool(clean and self.credential_store.has_api_key(clean))
            except Exception:
                pass

            default_en = bool(cfg.get('enabled', has_key))
            self.enabled_check.setChecked(default_en)

            saved_model = str(cfg.get('model') or cat.get('default_model') or '').strip()
            if clean == 'cerebras' and saved_model.lower() in {'llama3.1-8b', 'llama-3.1-8b', 'llama-3.3-70b'}:
                saved_model = 'gpt-oss-120b'

            if hasattr(self, 'model_combo'):
                self.model_combo.clear()
                all_choices = list(dict.fromkeys([m for m in ([saved_model] + sugg) if m]))
                for m in all_choices:
                    self.model_combo.addItem(m)
                self.model_combo.setCurrentText(saved_model)
            else:
                self.model_edit.setText(saved_model)

            self.base_url_edit.setText(str(cfg.get('base_url') or cat.get('default_base_url') or ''))
            if hasattr(self, 'adv_url_check'):
                needs_url = clean not in PROVIDER_CATALOG or clean == 'ollama'
                self.adv_url_check.setChecked(needs_url)
            self.api_key_edit.clear()
            if has_key:
                self.api_key_edit.setPlaceholderText('✓ Encrypted in Windows DPAPI Vault (paste new key to replace)')
            else:
                self.api_key_edit.setPlaceholderText('Paste API key here — auto-saves & encrypts immediately')
        finally:
            self._loading_provider_fields = False

    def save_settings(self):
        name = self.provider_combo.currentText().strip().lower()
        if not name:
            QMessageBox.warning(self, 'Missing Provider Name', 'Please enter a provider name.')
            return
        self._auto_save_current_provider()
        if hasattr(self, '_flush_squad_editor') and callable(self._flush_squad_editor):
            self._flush_squad_editor()
        if hasattr(self, '_squads_data'):
            save_ai_squads(self._squads_data, config_path=self.config_path)
        if hasattr(self, 'pers_base_style_combo'):
            save_personalization_settings(
                {
                    'auto_evolve_profile': bool(self.enable_shared_mem_check.isChecked()) if hasattr(self, 'enable_shared_mem_check') else True,
                    'base_style': self.pers_base_style_combo.currentText(),
                    'warmth': self.pers_warmth_combo.currentText(),
                    'enthusiasm': self.pers_enthusiasm_combo.currentText(),
                    'emoji': self.pers_emoji_combo.currentText(),
                    'visual_answers': self.pers_visual_combo.currentText(),
                    'headers_and_lists': self.pers_headers_combo.currentText(),
                    'custom_instructions_general': self.pers_general_inst_edit.toPlainText().strip(),
                    'custom_instructions_coding': self.pers_coding_inst_edit.toPlainText().strip(),
                    'reference_photo_face': getattr(self, 'ref_face_path', ''),
                    'reference_photo_body': getattr(self, 'ref_body_path', ''),
                },
                config_path=self.config_path,
            )
        self._save_email_and_notification_fields()
        self._save_bridge_fields()
        from palace_config import parse_storage_mb_text
        save_idle_settings(
            {
                'duration_minutes': int(self.idle_duration_combo.currentData()),
                'max_tokens_limit': int(self.idle_token_limit_combo.currentData()),
                'max_credit_usd': float(self.idle_credit_limit_combo.currentData()),
                'max_storage_mb': parse_storage_mb_text(self.idle_storage_edit.text()) if hasattr(self, 'idle_storage_edit') else 0,
                'pause_when_joined': self.idle_pause_check.isChecked(),
                'share_source_code': bool(self.idle_share_code_check.isChecked()) if hasattr(self, 'idle_share_code_check') else False,
                'allow_live_self_modify': bool(self.idle_live_patch_check.isChecked()) if hasattr(self, 'idle_live_patch_check') else False,
                'source_mirror_dir': self.idle_mirror_dir_edit.text().strip() if hasattr(self, 'idle_mirror_dir_edit') else '',
                'memory_access_mode': self.idle_memory_mode_combo.currentData(),
                'standing_instruction': self.idle_prompt_edit.toPlainText().strip(),
            },
            config_path=self.config_path,
        )
        save_mission_ethics(
            self.mission_ethics_edit.toPlainText(),
            config_path=self.config_path,
        )
        ui_updates = {
            'enter_to_send': bool(self.enter_mode_combo.currentData()),
            'close_to_tray': bool(self.close_to_tray_check.isChecked()) if hasattr(self, 'close_to_tray_check') else True,
            'auto_refresh_catalog': bool(self.auto_refresh_catalog_check.isChecked()) if hasattr(self, 'auto_refresh_catalog_check') else True,
            'badge_display_mode': str(self.badge_mode_combo.currentData() or 'icons_only'),
            'theme': str(self.theme_combo.currentData() or 'dark') if hasattr(self, 'theme_combo') else 'dark',
        }
        if hasattr(self, 'normal_storage_edit'):
            ui_updates['normal_max_storage_mb'] = parse_storage_mb_text(self.normal_storage_edit.text())
        if hasattr(self, 'palace_data_dir_edit'):
            chosen_dir = self.palace_data_dir_edit.text().strip()
            default_appdata = str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Palace')
            ui_updates['custom_data_dir'] = '' if chosen_dir == default_appdata else chosen_dir
        save_ui_settings(
            ui_updates,
            config_path=self.config_path,
        )
        if hasattr(self, 'tool_checks'):
            save_tool_settings(
                {k: chk.isChecked() for k, chk in self.tool_checks.items()},
                config_path=self.config_path,
            )
        if hasattr(self, 'perm_mode_combo'):
            save_access_permissions(
                {
                    'permission_mode': str(self.perm_mode_combo.currentData() or 'default'),
                    'write_exclusions': self._collect_exclusions(),
                    'allow_workspace_writes': bool(self.cap_workspace_writes_check.isChecked()) if hasattr(self, 'cap_workspace_writes_check') else True,
                    'allow_shell_commands': bool(self.cap_shell_cmds_check.isChecked()) if hasattr(self, 'cap_shell_cmds_check') else True,
                },
                config_path=self.config_path,
            )
        if hasattr(self, 'ad_web_search_combo'):
            save_agent_defaults(
                {
                    'web_search_default': str(self.ad_web_search_combo.currentData() or 'default'),
                    'output_detail': str(self.ad_output_detail_combo.currentData() or 'high'),
                    'reasoning_summary': str(self.ad_reasoning_combo.currentData() or 'auto'),
                    'synthesizer_mode': str(self.ad_synth_combo.currentData() or 'auto_fast'),
                    'smart_routing': bool(self.ad_smart_routing_check.isChecked()),
                    'show_inline_status_messages': bool(self.ad_inline_status_check.isChecked()) if hasattr(self, 'ad_inline_status_check') else True,
                    'provider_timeout_sec': int(self.ad_timeout_spin.value()),
                    'straggler_grace_sec': int(self.ad_straggler_spin.value()),
                },
                config_path=self.config_path,
            )
        if hasattr(self, '_collect_voice_payload'):
            from voice_service import save_voice_settings
            save_voice_settings(self._collect_voice_payload(), config_path=self.config_path)
        elif hasattr(self, 'voice_name_combo'):
            from voice_service import save_voice_settings
            save_voice_settings(
                {
                    'voice_name': str(self.voice_name_combo.currentData() or self.voice_name_combo.currentText()),
                    'microphone_device': self.mic_device_combo.currentText(),
                    'mic_gain_percent': int(self.mic_gain_slider.value()) if hasattr(self, 'mic_gain_slider') else 150,
                    'silence_timeout_ms': int(self.silence_timeout_slider.value()) if hasattr(self, 'silence_timeout_slider') else 1500,
                    'volume_percent': int(self.voice_vol_slider.value()),
                    'auto_speak_responses': self.auto_speak_check.isChecked(),
                },
                config_path=self.config_path,
            )
        self._voice_dlg_closed = True
        self._stop_settings_mic_test()
        self.accept()


class PalaceWindow(QMainWindow):
    _cost_event_signal = Signal(object)
    _catalog_sync_done = Signal(object, bool)

    def __init__(
        self,
        store=None,
        palace_factory=None,
        provider_states=None,
        demo=False,
        proposal_service=None,
        idle_memory=None,
        config_path: Path = CONFIG_PATH,
    ):
        super().__init__()
        self.config_path = config_path
        self._latest_catalog_info: dict[str, Any] = {}
        self.store = store or SessionStore()
        default_prop_path = (self.store.root / 'memory-proposals.jsonl') if store is not None else None
        self.proposal_service = proposal_service or MemoryProposalService(default_prop_path)
        default_idle_mem_path = (self.store.root / 'idle_notebooks' / 'ai_idle_memory.json') if store is not None else None
        self.idle_memory = idle_memory or IdleMemoryStore(default_idle_mem_path)
        self.idle_manager = IdleSessionManager(idle_memory=self.idle_memory, config_path=self.config_path)
        self.session_id = self.store.selected
        self.palace_factory = palace_factory or self._build_palace
        self.attachments = []
        self.worker = None
        self._voice_companion = None
        self._voice_threads = []
        self._voice_session_gen = 0
        self._last_voice_brain_provider = ''
        self._last_voice_brain_fell_back = False
        self._last_voice_brain_requested = ''
        self._cached_status_style = 'text'
        self._status_style_cfg_mtime = None
        self._active_working_session_id = None
        self._archived_expanded = False
        self._suppress_mail_auto_read = False
        self._background_delegated_from_voice = False
        self._talk_only_mode = False
        self._pending_workspace_actions = []
        self.last_answer = ''
        self.last_question = ''
        self.pending_prompt = ''
        self.pending_history = True
        self.provider_labels = {}
        self.provider_details = {}
        self.reply_archive = []
        self.chat_items = []
        self._item_html_cache = {}
        self.expanded_deliberations = set()
        self.conversation_contributors = []
        self.current_profile = 'Multi-AI · Deliberate'
        self.current_squad_label = ''
        self.max_ais_per_turn = 0
        self.pending_status_text = ''
        self.pulse_step = 0
        self.demo = demo
        ui_cfg = load_ui_settings(self.config_path)
        self.badge_display_mode = str(ui_cfg.get('badge_display_mode', 'icons_only'))
        self.active_theme = str(ui_cfg.get('theme', 'dark') or 'dark')
        self.setWindowTitle('Fairybread — Preview' if demo else 'Fairybread')
        try:
            icon = fairybread_app_qicon()
            self.setWindowIcon(icon)
            app_inst = QApplication.instance()
            if app_inst is not None:
                app_inst.setWindowIcon(icon)
        except Exception:
            pass
        self.resize(1120, 740)
        self.setMinimumSize(860, 600)
        self.setAcceptDrops(True)

        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(1000)
        self.idle_timer.timeout.connect(self._on_idle_timer_tick)

        self.idle_auto_timer = QTimer(self)
        self.idle_auto_timer.setSingleShot(True)
        self.idle_auto_timer.setInterval(1800)
        self.idle_auto_timer.timeout.connect(self._on_idle_auto_round)

        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(350)
        self.pulse_timer.timeout.connect(self._on_pulse_tick)

        self._build_menu_bar()

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # --- LEFT SIDEBAR (Matches GPT/Antigravity mockup) ---
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setMinimumWidth(250)
        sidebar.setMaximumWidth(285)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 10, 10, 8)
        side.setSpacing(2)

        self.new_button = QPushButton('+ New Conversation')
        self.new_button.setObjectName('newConvoButton')
        self.new_button.setToolTip('New conversation (Ctrl+N)')
        self.new_button.clicked.connect(self.new_conversation)
        side.addWidget(self.new_button)

        self.sidebar_mail_btn = QPushButton(' Agent Mail (0)')
        self.sidebar_mail_btn.setIcon(mail_grey_qicon(False))
        self.sidebar_mail_btn.setIconSize(QSize(16, 16))
        self.sidebar_mail_btn.setCheckable(True)
        self.sidebar_mail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_mail_btn.setToolTip('Idle Mode agent inbox')
        self.sidebar_mail_btn.setStyleSheet(
            'QPushButton { background: transparent; color: #8b949e; border: 1px solid transparent; '
            'padding: 6px 10px; border-radius: 6px; text-align: left; font-weight: 600; font-size: 12px; } '
            'QPushButton:hover { background: #161b22; color: #e6edf3; } '
            'QPushButton:checked { background: #161b22; color: #22c55e; border: 1px solid #21262d; }'
        )
        self.sidebar_mail_btn.clicked.connect(self._toggle_agent_mail_view)
        side.addWidget(self.sidebar_mail_btn)

        # Pinned collapsible section (hidden automatically when empty)
        self.pinned_toggle_btn = QPushButton('⌄  Pinned')
        self.pinned_toggle_btn.setObjectName('pinnedHeaderButton')
        self.pinned_toggle_btn.setCheckable(True)
        self.pinned_toggle_btn.setChecked(True)
        self.pinned_toggle_btn.toggled.connect(self._toggle_pinned_section)
        self.pinned_toggle_btn.hide()
        side.addWidget(self.pinned_toggle_btn)

        self.pinned_list = QListWidget()
        self.pinned_list.setObjectName('pinnedList')
        self.pinned_list.setAccessibleName('Pinned conversations')
        self.pinned_list.setMaximumHeight(110)
        self.pinned_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pinned_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.pinned_list.currentItemChanged.connect(self.change_session)
        self.pinned_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pinned_list.customContextMenuRequested.connect(lambda pos: self._show_session_context_menu(self.pinned_list, pos))
        self.pinned_list.hide()
        side.addWidget(self.pinned_list)

        # Antigravity-style unified Projects & Conversations section header
        proj_header = QHBoxLayout()
        proj_header.setContentsMargins(4, 4, 4, 0)
        proj_label = QLabel('Projects')
        proj_label.setObjectName('sidebarHeading')
        proj_header.addWidget(proj_label)
        proj_header.addStretch()
        self.attach_project_folder_btn = QPushButton()
        self.attach_project_folder_btn.setIcon(folder_grey_qicon(False))
        self.attach_project_folder_btn.setIconSize(QSize(15, 15))
        self.attach_project_folder_btn.setObjectName('iconButton')
        self.attach_project_folder_btn.setToolTip('Attach folder to Project')
        self.attach_project_folder_btn.clicked.connect(self.attach_folder_to_current_project)
        proj_header.addWidget(self.attach_project_folder_btn)
        self.new_project_button = QPushButton('+')
        self.new_project_button.setObjectName('iconButton')
        self.new_project_button.setToolTip('Create new Project')
        self.new_project_button.clicked.connect(lambda: self.new_project())
        proj_header.addWidget(self.new_project_button)
        side.addLayout(proj_header)

        # Keep project_list model populated for programmatic/unit-test inspection, while rendering
        # Projects + their inline Conversations together inside self.session_list just like Antigravity.
        self.project_list = QListWidget()
        self.project_list.setObjectName('sidebarList')
        self.project_list.setAccessibleName('Projects')
        self.project_list.currentItemChanged.connect(self.change_project)
        self.project_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_list.customContextMenuRequested.connect(self._show_project_context_menu)
        self.project_list.hide()
        side.addWidget(self.project_list)

        self.discussions_toggle_btn = QPushButton('⌄  Discussions')
        self.discussions_toggle_btn.setObjectName('sectionToggleButton')
        self.discussions_toggle_btn.setCheckable(True)
        self.discussions_toggle_btn.setChecked(True)
        self.discussions_toggle_btn.toggled.connect(self._toggle_discussions_section)
        self.discussions_toggle_btn.hide()
        side.addWidget(self.discussions_toggle_btn)

        self.session_list = SidebarSessionList()
        self.session_list.setObjectName('sidebarList')
        self.session_list.setAccessibleName('Conversations')
        self.session_list.setIconSize(QSize(15, 15))
        self.session_list.setSpacing(0)
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.session_list.setItemDelegate(SidebarItemDelegate(self.session_list))
        self.session_list.currentItemChanged.connect(self.change_session)
        self.session_list.itemClicked.connect(self._on_sidebar_item_clicked)
        self.session_list.sessions_reordered.connect(self._on_sidebar_sessions_reordered)
        self.session_list.item_menu_requested.connect(
            lambda item, pos: self._show_session_context_menu(self.session_list, pos, explicit_item=item)
        )
        self.session_list.session_pin_toggled.connect(self._toggle_session_pin_by_id)
        self.session_list.project_new_session_requested.connect(self._new_conversation_in_project)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(lambda pos: self._show_session_context_menu(self.session_list, pos))
        side.addWidget(self.session_list, 1)

        self.manage_ais_button = QPushButton('⚙ Settings && AIs')
        self.manage_ais_button.setObjectName('settingsButton')
        self.manage_ais_button.setToolTip('Settings & AI Providers')
        self.manage_ais_button.clicked.connect(self.open_manage_ais)
        side.addWidget(self.manage_ais_button)
        splitter.addWidget(sidebar)

        # --- MAIN CHAT WORKSPACE ---
        panel = QWidget()
        panel.setObjectName('chatPanel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 10, 18, 8)
        layout.setSpacing(6)

        # --- ULTRA-SLIM TOP SESSION STRIP (40px, Zero Crowding) ---
        loaded_frame = QFrame()
        loaded_frame.setObjectName('loadedAIsBar')
        top_strip = QHBoxLayout(loaded_frame)
        top_strip.setContentsMargins(12, 5, 12, 5)
        top_strip.setSpacing(8)

        self.conversation_title = ResponsiveBarLabel('Fairybread  /  New conversation')
        self.conversation_title.setStyleSheet('color: #c9d1d9; font-size: 12.5px; font-weight: 600;')
        top_strip.addWidget(self.conversation_title)

        self.attached_folder_chip = QPushButton()
        self.attached_folder_chip.setIcon(folder_grey_qicon(True))
        self.attached_folder_chip.setIconSize(QSize(14, 14))
        self.attached_folder_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.attached_folder_chip.setToolTip('Change attached Project folder')
        self.attached_folder_chip.setStyleSheet(
            'QPushButton { background: #0f2930; color: #06b6d4; border: 1px solid #06b6d4; '
            'padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; }'
        )
        self.attached_folder_chip.clicked.connect(self.attach_folder_to_current_project)
        self.attached_folder_chip.hide()
        top_strip.addWidget(self.attached_folder_chip)

        top_strip.addStretch()

        profile_caption = QLabel('Mode:')
        profile_caption.setObjectName('loadedAIsLabel')
        profile_caption.hide()
        top_strip.addWidget(profile_caption)

        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName('profilePicker')
        self.profile_combo.setAccessibleName('Profile and mode selector')
        self.profile_combo.setMinimumWidth(190)
        self.profile_combo.addItems([
            'Multi-AI · Deliberate',
            'Multi-AI · Independent',
            'Single AI',
            'Idle',
            'Manage Profiles…',
        ])
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        self.profile_combo.hide()
        top_strip.addWidget(self.profile_combo)

        self.update_available_btn = QPushButton('⬆ Update')
        self.update_available_btn.setObjectName('updateAvailableButton')
        self.update_available_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_available_btn.setToolTip('A newer version of Fairybread is available — click for details and download')
        self.update_available_btn.setStyleSheet(
            'QPushButton { background: #12281c; color: #3fb950; border: 1px solid #2ea043; '
            'padding: 4px 8px; border-radius: 6px; font-weight: 700; font-size: 11.5px; } '
            'QPushButton:hover { background: #193b28; color: #7ee787; border-color: #3fb950; }'
        )
        self.update_available_btn.clicked.connect(self.show_update_available_dialog)
        self.update_available_btn.hide()
        top_strip.addWidget(self.update_available_btn)

        self.no_history_btn = QPushButton(' No-History')
        self.no_history_btn.setIcon(no_history_qicon(False))
        self.no_history_btn.setIconSize(QSize(16, 16))
        self.no_history_btn.setCheckable(True)
        self.no_history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.no_history_btn.setToolTip("Don't save chat history (ephemeral)")
        self.no_history_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 9px; border-radius: 6px; font-weight: 600; font-size: 11.5px; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #2c1517; color: #ef4444; border: 1px solid #ef4444; font-weight: 700; }'
        )
        self.no_history_btn.toggled.connect(self._on_no_history_toggled)
        top_strip.addWidget(self.no_history_btn)

        self.idle_switch_btn = QPushButton(' Experimental: OFF')
        self.idle_switch_btn.setIcon(idle_moon_qicon(False))
        self.idle_switch_btn.setIconSize(QSize(15, 15))
        self.idle_switch_btn.setCheckable(True)
        self.idle_switch_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.idle_switch_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.idle_switch_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.idle_switch_btn.setToolTip('Experimental Mode status notice (use Mode menu to launch or exit)')
        self.idle_switch_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 10px; border-radius: 6px; font-weight: 600; font-size: 11.5px; } '
            'QPushButton:checked { background: #3d1414; color: #ff4d4d; border: 1px solid #ef4444; font-weight: 700; }'
        )
        self.idle_switch_btn.toggled.connect(self._on_idle_switch_toggled)
        top_strip.addWidget(self.idle_switch_btn)

        self.memory_button = QPushButton('Memory')
        self.memory_button.setObjectName('topIconButton')
        self.memory_button.setCheckable(True)
        self.memory_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.memory_button.setToolTip('View & manage Shared Memory')
        self.memory_button.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 10px; border-radius: 6px; font-weight: 600; font-size: 11.5px; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #132238; color: #58a6ff; border: 1px solid #3b82f6; font-weight: 700; }'
        )
        top_strip.addWidget(self.memory_button)
        layout.addWidget(loaded_frame)

        # --- STACKED WORKSPACE VIEWS (Tab Bar Hidden So Idle/Mail Only Show When Needed) ---
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setObjectName('workspaceTabs')
        self.workspace_tabs.tabBar().hide()
        self.workspace_tabs.setStyleSheet('QTabWidget::pane { border: none; background: transparent; }')
        layout.addWidget(self.workspace_tabs, 1)

        # ================= TAB 0: NORMAL PALACE =================
        normal_tab = QWidget()
        normal_lay = QVBoxLayout(normal_tab)
        normal_lay.setContentsMargins(36, 6, 36, 2)
        normal_lay.setSpacing(6)

        self.no_history_banner = QFrame()
        self.no_history_banner.setStyleSheet(
            'background: #2c1517; border: 1px solid #ef4444; border-radius: 6px; padding: 5px 10px;'
        )
        nh_row = QHBoxLayout(self.no_history_banner)
        nh_row.setContentsMargins(6, 2, 6, 2)
        nh_lbl = QLabel(
            '🚫 <b>NO-HISTORY MODE ACTIVE</b> — Conversations right now are <b>NOT</b> being saved to Shared Memory. '
            '(For quick side-thoughts like Absurdityverse that <i>should</i> be saved without prior code context, use <b>Tangent</b> below instead.)'
        )
        nh_lbl.setWordWrap(True)
        nh_lbl.setStyleSheet('color: #fca5a5; font-size: 12px;')
        nh_row.addWidget(nh_lbl, 1)
        nh_off_btn = QPushButton('Resume Saving History')
        nh_off_btn.setToolTip('Turn off No-History Mode')
        nh_off_btn.clicked.connect(lambda: self.no_history_btn.setChecked(False))
        nh_row.addWidget(nh_off_btn)
        self.no_history_banner.hide()
        normal_lay.addWidget(self.no_history_banner)

        self.normal_pause_banner = QFrame()
        self.normal_pause_banner.setStyleSheet(
            'background: #11281b; border: 1px solid #22c55e; border-radius: 6px; padding: 6px 10px;'
        )
        pause_row = QHBoxLayout(self.normal_pause_banner)
        pause_row.setContentsMargins(6, 2, 6, 2)
        pause_lbl = QLabel(
            '⏸ <b>Normal AI Mode is Paused</b> while <b>Experimental Mode</b> is running autonomously.'
        )
        pause_lbl.setStyleSheet('color: #86efac; font-size: 12px;')
        pause_row.addWidget(pause_lbl, 1)
        go_idle_btn = QPushButton('View Experimental Mode →')
        go_idle_btn.setToolTip('Switch to Experimental Mode tab')
        go_idle_btn.clicked.connect(lambda: self.workspace_tabs.setCurrentIndex(1))
        pause_row.addWidget(go_idle_btn)
        self.normal_pause_banner.hide()
        normal_lay.addWidget(self.normal_pause_banner)

        self.chat = ChatBrowser()
        self.chat.setObjectName('chatView')
        self.chat.setAccessibleName('Conversation history')
        self.chat.setOpenLinks(False)
        self.chat.setAcceptDrops(False)
        if self.chat.viewport() is not None:
            self.chat.viewport().setAcceptDrops(False)
        self.chat.anchorClicked.connect(self._on_chat_anchor_clicked)
        self.chat.anchor_action_requested.connect(lambda s: self._on_chat_anchor_clicked(QUrl(s)))
        normal_lay.addWidget(self.chat, 1)

        # Inline Pending Action Approval Banner (triggered by Request Review / Default / Auto / Write Exclusion List)
        self.approval_banner = QFrame()
        self.approval_banner.setObjectName('approvalBanner')
        self.approval_banner.setStyleSheet(
            'QFrame#approvalBanner { background: #1e1610; border: 1px solid #d29922; border-radius: 8px; padding: 8px 12px; }'
        )
        app_row = QHBoxLayout(self.approval_banner)
        app_row.setContentsMargins(6, 4, 6, 4)
        app_row.setSpacing(10)
        app_txt_col = QVBoxLayout()
        app_txt_col.setSpacing(2)
        self.approval_title_lbl = QLabel('🛡 Approval Required')
        self.approval_title_lbl.setStyleSheet('color: #f0b849; font-weight: 700; font-size: 12.5px;')
        self.approval_detail_lbl = QLabel('')
        self.approval_detail_lbl.setWordWrap(True)
        self.approval_detail_lbl.setStyleSheet('color: #e6edf3; font-size: 11.5px;')
        app_txt_col.addWidget(self.approval_title_lbl)
        app_txt_col.addWidget(self.approval_detail_lbl)
        app_row.addLayout(app_txt_col, 1)

        self.approve_actions_btn = QPushButton('✓ Approve && Execute')
        self.approve_actions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.approve_actions_btn.setToolTip('Execute these pending file writes, patches, or commands now')
        self.approve_actions_btn.setStyleSheet(
            'QPushButton { background: #1f6feb; color: #ffffff; border: 1px solid #388bfd; '
            'padding: 6px 12px; border-radius: 6px; font-weight: 700; font-size: 12px; } '
            'QPushButton:hover { background: #388bfd; }'
        )
        self.approve_actions_btn.clicked.connect(self._approve_pending_workspace_actions)
        app_row.addWidget(self.approve_actions_btn)

        self.reject_actions_btn = QPushButton('✕ Reject')
        self.reject_actions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reject_actions_btn.setToolTip('Cancel pending actions — nothing will be written or run')
        self.reject_actions_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #f87171; border: 1px solid #da3633; '
            'padding: 6px 10px; border-radius: 6px; font-weight: 600; font-size: 12px; } '
            'QPushButton:hover { background: #2c1517; }'
        )
        self.reject_actions_btn.clicked.connect(self._reject_pending_workspace_actions)
        app_row.addWidget(self.reject_actions_btn)
        self.approval_banner.hide()
        normal_lay.addWidget(self.approval_banner)

        # --- UNIFIED ROUNDED COMPOSER CARD ---
        composer_card = QFrame()
        composer_card.setObjectName('composerCard')
        card_layout = QVBoxLayout(composer_card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(6)

        self.staged_attachments_frame = QFrame()
        self.staged_attachments_frame.setStyleSheet('background: transparent; border: none;')
        self.staged_attachments_layout = QHBoxLayout(self.staged_attachments_frame)
        self.staged_attachments_layout.setContentsMargins(0, 2, 0, 4)
        self.staged_attachments_layout.setSpacing(8)
        self.staged_attachments_frame.hide()
        card_layout.addWidget(self.staged_attachments_frame)

        self.attachment_list = QListWidget()
        self.attachment_list.setObjectName('attachmentList')
        self.attachment_list.setAccessibleName('Attached files; select a file then Remove selected')
        self.attachment_list.setFixedHeight(0)
        self.attachment_list.hide()
        card_layout.addWidget(self.attachment_list)

        # Auto-hiding Live Status Strip (0px when idle; holds Live Voice / Stop / Steer / Remove controls)
        self.composer_live_bar = QFrame()
        self.composer_live_bar.setObjectName('composerLiveBar')
        self.composer_live_bar.setStyleSheet('QFrame#composerLiveBar { background: transparent; border: none; }')
        live_bar_lay = QHBoxLayout(self.composer_live_bar)
        live_bar_lay.setContentsMargins(0, 0, 0, 2)
        live_bar_lay.setSpacing(5)

        self.voice_level_badge = QLabel('')
        self.voice_level_badge.setToolTip('Live microphone volume meter (speak naturally — auto-sends on pause)')
        self.voice_level_badge.setStyleSheet(
            'font-family: Consolas, monospace; font-size: 11px; font-weight: 700; color: #22c55e; '
            'background: #11281b; border: 1px solid #22c55e; border-radius: 6px; padding: 3px 7px;'
        )
        self.voice_level_badge.hide()
        live_bar_lay.addWidget(self.voice_level_badge)

        self.voice_brain_btn = QPushButton('🧠 Auto ▾')
        self.voice_brain_btn.setObjectName('voiceBrainButton')
        self.voice_brain_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_brain_btn.setToolTip('Thinking AI (🧠): who thinks & writes replies in Voice/Talk Mode (click to switch anytime)')
        self.voice_brain_btn.clicked.connect(self._show_voice_brain_menu)
        self.voice_brain_btn.hide()
        live_bar_lay.addWidget(self.voice_brain_btn)

        self.voice_tts_btn = QPushButton('🔊 Auto ▾')
        self.voice_tts_btn.setObjectName('voiceTtsButton')
        self.voice_tts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_tts_btn.setToolTip('Speaking Voice (🔊): only changes how replies sound aloud (click to switch ready voices)')
        self.voice_tts_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #c9d1d9; border: 1px solid #30363d; '
            'padding: 3px 7px; border-radius: 6px; font-size: 11px; font-weight: 600; } '
            'QPushButton:hover { color: #f0f6fc; border-color: #58a6ff; }'
        )
        self.voice_tts_btn.clicked.connect(self._show_voice_tts_menu)
        self.voice_tts_btn.hide()
        live_bar_lay.addWidget(self.voice_tts_btn)

        self.voice_mute_btn = QPushButton('🔇 Mute')
        self.voice_mute_btn.setObjectName('voiceMuteButton')
        self.voice_mute_btn.setCheckable(True)
        self.voice_mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_mute_btn.setToolTip('Mute or unmute live microphone without ending Talk Mode')
        self.voice_mute_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #c9d1d9; border: 1px solid #30363d; '
            'padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; } '
            'QPushButton:hover { color: #f0f6fc; border-color: #58a6ff; } '
            'QPushButton:checked { background: #29230f; color: #eab308; border: 1px solid #eab308; font-weight: 700; }'
        )
        self.voice_mute_btn.toggled.connect(self._toggle_voice_mute)
        self.voice_mute_btn.hide()
        live_bar_lay.addWidget(self.voice_mute_btn)

        self.end_talk_btn = QPushButton('✕ End Talk')
        self.end_talk_btn.setObjectName('endTalkButton')
        self.end_talk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.end_talk_btn.setToolTip('Immediately stop Live Voice / Talk Mode and silence speech')
        self.end_talk_btn.setStyleSheet(
            'QPushButton { background: #3d1414; color: #ff6b6b; border: 1px solid #ef4444; '
            'padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; } '
            'QPushButton:hover { background: #5c1919; color: #ffffff; border-color: #ff6b6b; }'
        )
        self.end_talk_btn.clicked.connect(lambda: self.stop_all_voice_modes(notice='Talk Mode / Live Voice ended.'))
        self.end_talk_btn.hide()
        live_bar_lay.addWidget(self.end_talk_btn)

        self.remove_button = QPushButton('✕ Remove file')
        self.remove_button.setObjectName('iconButton')
        self.remove_button.setToolTip('Remove selected attachment')
        self.remove_button.clicked.connect(self.remove_attachment)
        self.remove_button.hide()
        live_bar_lay.addWidget(self.remove_button)

        live_bar_lay.addStretch()

        self.composer_live_bar.hide()
        card_layout.addWidget(self.composer_live_bar)

        self.composer = Composer(enter_to_send=bool(ui_cfg.get('enter_to_send', True)))
        self.composer.setToolTip('Type message, / for commands, paste image (Ctrl+V), or drop files')
        self.composer.files_added.connect(self.add_files)
        self.composer.image_pasted.connect(self.add_pasted_image)
        self.composer.send_requested.connect(self.send_message)
        self.composer.unsupported_paste.connect(lambda: self.show_notice('Clipboard image could not be decoded. Attach a picture, text document, PDF, or Word file.'))
        card_layout.addWidget(self.composer)

        # Row 1: Primary actions (+, / Commands, Choose AIs, stretch, [Busy: Steer/Stop], Mic, Live Voice, Send)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 2, 0, 0)
        controls.setSpacing(6)
        self.attach_button = QPushButton('+')
        self.attach_button.setObjectName('plusAttachButton')
        self.attach_button.setToolTip('Attach files or pictures (Ctrl+O)')
        self.attach_button.clicked.connect(self.choose_files)
        controls.addWidget(self.attach_button)

        self.slash_cmd_btn = QPushButton('/ Commands ▾')
        self.slash_cmd_btn.setMinimumWidth(98)
        self.slash_cmd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slash_cmd_btn.setToolTip('Insert slash command switch (/autopatch, /restore, /code, /search, /searchm, /searchd, /tangent, /fullrender)')
        self.slash_cmd_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #8b949e; border: 1px solid #21262d; '
            'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #f0f6fc; border-color: #3b82f6; }'
        )
        self.slash_cmd_btn.clicked.connect(self._show_slash_commands_menu)
        controls.addWidget(self.slash_cmd_btn)

        self.ai_pill_button = QPushButton('Choose AIs  ▾')
        self.ai_pill_button.setObjectName('aiPillButton')
        self.ai_pill_button.setMinimumWidth(126)
        self.ai_pill_button.setToolTip('Select active AIs or Squad')
        self.ai_pill_button.clicked.connect(self._show_choose_ais_menu)
        controls.addWidget(self.ai_pill_button)

        controls.addStretch()

        self._neutral_busy_btn_style = (
            'QPushButton { background: #161b22; color: #8b949e; border: 1px solid #21262d; '
            'padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; border-color: #30363d; }'
        )
        self.steer_button = QPushButton('Steer / Queue ▾')
        self.steer_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.steer_button.setToolTip('Steer active turn or queue next')
        self.steer_button.setStyleSheet(self._neutral_busy_btn_style)
        self.steer_button.clicked.connect(self._show_busy_action_menu)
        self.steer_button.hide()
        controls.addWidget(self.steer_button)

        # Keep queue_button reference for unit tests, hidden from layout so only one dropdown is shown
        self.queue_button = QPushButton('Queue')
        self.queue_button.clicked.connect(self.queue_next_turn)
        self.queue_button.hide()

        self.stop_button = QPushButton('■ Stop')
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setToolTip('Stop turn (Esc)')
        self.stop_button.setStyleSheet(
            'QPushButton { background: #161b22; color: #8b949e; border: 1px solid #21262d; '
            'padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { background: #2c1517; color: #f87171; border: 1px solid #ef4444; }'
        )
        self.stop_button.clicked.connect(self.stop_active_turn)
        self.stop_button.hide()
        controls.addWidget(self.stop_button)

        self.mic_button = QPushButton()
        self.mic_button.setIcon(mic_qicon(False))
        self.mic_button.setIconSize(QSize(15, 15))
        self.mic_button.setCheckable(True)
        self.mic_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_button.setFixedSize(30, 30)
        self.mic_button.setToolTip('Dictate voice into text box')
        self.mic_button.setStyleSheet(
            'QPushButton { background: transparent; border: 1px solid transparent; border-radius: 15px; } '
            'QPushButton:hover { background: #161b22; border-color: #30363d; } '
            'QPushButton:checked { background: #2c1517; border: 1px solid #ef4444; }'
        )
        self.mic_button.toggled.connect(self._toggle_voice_dictation)
        controls.addWidget(self.mic_button)

        self._live_voice_idle_style = (
            'QPushButton { background: #d0d7de; border: 1px solid #d0d7de; border-radius: 15px; } '
            'QPushButton:hover { background: #f0f6fc; border-color: #f0f6fc; }'
        )
        self._live_voice_active_style = (
            'QPushButton { background: #3d1414; color: #ff6b6b; border: 2px solid #ef4444; '
            'border-radius: 15px; font-size: 13px; font-weight: 800; } '
            'QPushButton:hover { background: #5c1919; color: #ffffff; border-color: #ff6b6b; }'
        )
        self.live_voice_button = QPushButton()
        self.live_voice_button.setIcon(voice_wave_qicon(False))
        self.live_voice_button.setIconSize(QSize(16, 16))
        self.live_voice_button.setCheckable(True)
        self.live_voice_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.live_voice_button.setFixedSize(30, 30)
        self.live_voice_button.setToolTip('Start live hands-free voice chat')
        self.live_voice_button.setStyleSheet(self._live_voice_idle_style)
        self.live_voice_button.toggled.connect(self._toggle_live_voice_mode)
        controls.addWidget(self.live_voice_button)

        self.send_button = QPushButton('↑')
        self.send_button.setObjectName('sendButton')
        self.send_button.setToolTip('Send message (Enter)')
        self.send_button.setFixedSize(30, 30)
        self.send_button.clicked.connect(self.send_message)
        controls.addWidget(self.send_button)
        card_layout.addLayout(controls)

        # Row 2: Compact option pills (Council, Tangent, Code, Search Depth, Access Permission)
        options_row = QHBoxLayout()
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.setSpacing(6)

        self.deliberate_pill_btn = QPushButton(' Council')
        self.deliberate_pill_btn.setIcon(council_qicon(True))
        self.deliberate_pill_btn.setIconSize(QSize(15, 15))
        self.deliberate_pill_btn.setCheckable(True)
        self.deliberate_pill_btn.setChecked(True)
        self.deliberate_pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deliberate_pill_btn.setToolTip('2-round peer review (ON) / Direct (OFF)')
        self.deliberate_pill_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #231536; color: #a855f7; border: 1px solid #a855f7; }'
        )
        self.deliberate_pill_btn.toggled.connect(self._on_deliberate_pill_toggled)
        options_row.addWidget(self.deliberate_pill_btn)

        self.tangent_btn = QPushButton(' Tangent')
        self.tangent_btn.setIcon(tangent_qicon(False))
        self.tangent_btn.setIconSize(QSize(15, 15))
        self.tangent_btn.setCheckable(True)
        self.tangent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tangent_btn.setToolTip('Side question (ignores prior chat context)')
        self.tangent_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #29230f; color: #eab308; border: 1px solid #eab308; }'
        )
        self.tangent_btn.toggled.connect(lambda on: self.tangent_btn.setIcon(tangent_qicon(on)))
        options_row.addWidget(self.tangent_btn)

        self.palace_code_btn = QPushButton(' Code')
        self.palace_code_btn.setIcon(code_shield_qicon(False))
        self.palace_code_btn.setIconSize(QSize(15, 15))
        self.palace_code_btn.setCheckable(True)
        self.palace_code_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.palace_code_btn.setToolTip('Let AIs read Fairybread source code')
        self.palace_code_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #0f2930; color: #06b6d4; border: 1px solid #06b6d4; }'
        )
        self.palace_code_btn.toggled.connect(self._on_palace_code_btn_toggled)
        options_row.addWidget(self.palace_code_btn)

        self.current_search_depth = 'default'
        self.search_depth_btn = QPushButton('🔍 Default ▾')
        self.search_depth_btn.setMinimumWidth(82)
        self.search_depth_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_depth_btn.setToolTip('Web search depth (Default / Moderate / Deep)')
        self.search_depth_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #8b949e; border: 1px solid #21262d; '
            'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; border-color: #30363d; }'
        )
        self.search_depth_btn.clicked.connect(self._show_search_depth_menu)
        options_row.addWidget(self.search_depth_btn)

        self.permission_pill_btn = QPushButton('🛡 Default ▾')
        self.permission_pill_btn.setObjectName('permissionPillButton')
        self.permission_pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.permission_pill_btn.setMinimumWidth(86)
        self.permission_pill_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #c9d1d9; border: 1px solid #262c3a; '
            'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #f0f6fc; border-color: #3b82f6; }'
        )
        self.permission_pill_btn.clicked.connect(self._show_permission_mode_menu)
        options_row.addWidget(self.permission_pill_btn)
        self._refresh_permission_pill_text()

        self.history_toggle = QCheckBox('History')
        self.history_toggle.setChecked(True)
        self.history_toggle.setToolTip('Use & save session history')
        self.history_toggle.toggled.connect(self._on_history_toggle_changed)
        self.history_toggle.hide()
        options_row.addWidget(self.history_toggle)

        self.peer_rounds_toggle = QCheckBox('Peer deliberation')
        self.peer_rounds_toggle.setChecked(True)
        self.peer_rounds_toggle.setToolTip('2-round peer review')
        self.peer_rounds_toggle.toggled.connect(self._on_peer_rounds_toggle_changed)
        self.peer_rounds_toggle.hide()
        options_row.addWidget(self.peer_rounds_toggle)

        options_row.addStretch()
        card_layout.addLayout(options_row)
        normal_lay.addWidget(composer_card)
        self.workspace_tabs.addTab(normal_tab, '💬 Normal Mode')

        # ================= TAB 1: EXPERIMENTAL MODE (BETA) =================
        idle_tab = QWidget()
        idle_tab_lay = QVBoxLayout(idle_tab)
        idle_tab_lay.setContentsMargins(0, 8, 0, 0)
        idle_tab_lay.setSpacing(8)

        self.idle_banner = QFrame()
        self.idle_banner.setObjectName('idleBanner')
        idle_lay = QVBoxLayout(self.idle_banner)
        idle_lay.setContentsMargins(14, 8, 14, 8)
        idle_lay.setSpacing(6)

        idle_top = QHBoxLayout()
        idle_top.setSpacing(8)
        self.idle_status_label = QLabel('Experimental Mode · Ready')
        self.idle_status_label.setStyleSheet('font-weight: 700; color: #22c55e; font-size: 13px;')
        idle_top.addWidget(self.idle_status_label)

        self.idle_timer_label = QLabel('⏱ 30:00')
        self.idle_timer_label.setToolTip('Remaining Experimental Mode session timer')
        self.idle_timer_label.setStyleSheet('font-family: Consolas, monospace; font-size: 13px; font-weight: 700; color: #e6edf3; background: #161b22; padding: 3px 10px; border-radius: 6px;')
        idle_top.addWidget(self.idle_timer_label)

        self.idle_budget_label = QLabel('Tokens: 0.0k · Spend: $0.000')
        self.idle_budget_label.setToolTip('Tokens and USD spent this session')
        self.idle_budget_label.setStyleSheet('font-family: Consolas, monospace; font-size: 12px; color: #8b949e; background: #161b22; padding: 3px 10px; border-radius: 6px;')
        idle_top.addWidget(self.idle_budget_label)

        self.idle_log_badge = QLabel('👁 BETA: Full Owner Access')
        self.idle_log_badge.setObjectName('muted')
        self.idle_log_badge.hide()

        idle_top.addStretch(1)

        back_chat_from_idle_btn = QPushButton('← Normal Chat')
        back_chat_from_idle_btn.setToolTip('Switch back to Normal Mode chat')
        back_chat_from_idle_btn.clicked.connect(self._activate_normal_mode_from_menu)
        idle_top.addWidget(back_chat_from_idle_btn)

        self.idle_settings_btn = QPushButton('⚙ Settings')
        self.idle_settings_btn.setToolTip('Configure Experimental Mode settings & source code access')
        self.idle_settings_btn.clicked.connect(lambda: self.open_manage_ais(initial_page='Experimental Mode'))
        idle_top.addWidget(self.idle_settings_btn)
        idle_lay.addLayout(idle_top)

        idle_actions = QHBoxLayout()
        idle_actions.setSpacing(6)
        submode_lbl = QLabel('Sub-Mode:')
        submode_lbl.setObjectName('loadedAIsLabel')
        idle_actions.addWidget(submode_lbl)

        idle_cfg_init = load_idle_settings(self.config_path)
        self.idle_submode_combo = QComboBox()
        self.idle_submode_combo.setMinimumWidth(145)
        self.idle_submode_combo.setMaximumWidth(185)
        self.idle_submode_combo.setToolTip('Choose Free Talk Lounge or Self-Improvement code review')
        self.idle_submode_combo.addItem('💬 Free Talk', 'free_talk')
        self.idle_submode_combo.addItem('🔧 Self-Improvement', 'self_improve')
        cur_submode = idle_cfg_init.get('idle_submode', 'free_talk')
        idx_sub = self.idle_submode_combo.findData(cur_submode)
        if idx_sub >= 0:
            self.idle_submode_combo.setCurrentIndex(idx_sub)
        self.idle_submode_combo.currentIndexChanged.connect(self._on_idle_submode_changed)
        idle_actions.addWidget(self.idle_submode_combo)

        share_code_init = bool(idle_cfg_init.get('share_source_code', False) or cur_submode == 'self_improve')
        self.idle_code_btn = QPushButton(' Code')
        self.idle_code_btn.setIcon(code_shield_qicon(share_code_init))
        self.idle_code_btn.setIconSize(QSize(14, 14))
        self.idle_code_btn.setCheckable(True)
        self.idle_code_btn.setChecked(share_code_init)
        self.idle_code_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.idle_code_btn.setToolTip('Share Fairybread source code with agents (Read-Only)')
        self.idle_code_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #0f2930; color: #06b6d4; border: 1px solid #06b6d4; }'
        )
        self.idle_code_btn.toggled.connect(self._on_idle_code_btn_toggled)
        idle_actions.addWidget(self.idle_code_btn)

        live_patch_init = bool(idle_cfg_init.get('allow_live_self_modify', False))
        self.idle_live_patch_btn = QPushButton('⚡ Live Patch')
        self.idle_live_patch_btn.setCheckable(True)
        self.idle_live_patch_btn.setChecked(live_patch_init)
        self.idle_live_patch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.idle_live_patch_btn.setToolTip('Allow agents to apply live code patches & continue past reboot')
        self.idle_live_patch_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #2c1e0f; color: #f59e0b; border: 1px solid #f59e0b; font-weight: 700; }'
        )
        self.idle_live_patch_btn.toggled.connect(self._on_idle_live_patch_btn_toggled)
        idle_actions.addWidget(self.idle_live_patch_btn)

        from palace_config import IS_DEVELOPER_EDITION
        if not IS_DEVELOPER_EDITION:
            self.idle_code_btn.hide()
            self.idle_live_patch_btn.hide()
            idx_si = self.idle_submode_combo.findData('self_improve')
            if idx_si >= 0:
                self.idle_submode_combo.removeItem(idx_si)

        self.idle_start_btn = QPushButton('▶ Start')
        self.idle_start_btn.setToolTip('Start or resume autonomous Experimental Mode discussion')
        self.idle_start_btn.clicked.connect(self.start_idle_session)
        idle_actions.addWidget(self.idle_start_btn)

        self.idle_step_btn = QPushButton('↻ Step 1 Round')
        self.idle_step_btn.setToolTip('Trigger one immediate round of discussion')
        self.idle_step_btn.clicked.connect(self.run_idle_exchange_step)
        self.idle_step_btn.setEnabled(False)
        idle_actions.addWidget(self.idle_step_btn)

        self.idle_join_btn = QPushButton('🔒 Vote to Join')
        self.idle_join_btn.setToolTip('Ask the Council to vote on admitting you to the live chat')
        self.idle_join_btn.clicked.connect(self.request_idle_operator_join)
        self.idle_join_btn.setEnabled(False)
        idle_actions.addWidget(self.idle_join_btn)

        self.idle_stop_btn = QPushButton('⏹ Stop && Wipe RAM')
        self.idle_stop_btn.setToolTip('Stop session and wipe temporary RAM transcript')
        self.idle_stop_btn.clicked.connect(self.stop_idle_session)
        self.idle_stop_btn.setEnabled(False)
        idle_actions.addWidget(self.idle_stop_btn)
        idle_actions.addStretch(1)
        idle_lay.addLayout(idle_actions)

        self.idle_agents_roster_label = QLabel('')
        self.idle_agents_roster_label.setTextFormat(Qt.TextFormat.RichText)
        self.idle_agents_roster_label.setWordWrap(True)
        self.idle_agents_roster_label.setStyleSheet(
            'background: #0d1117; border: 1px solid #21262d; border-radius: 6px; padding: 6px 10px; font-size: 12.5px;'
        )
        # Hidden on banner because the bottom Agents bar already shows all active agents cleanly
        self.idle_agents_roster_label.hide()

        idle_tab_lay.addWidget(self.idle_banner)

        idle_split = QSplitter(Qt.Orientation.Horizontal)
        idle_left = QWidget()
        idle_left_lay = QVBoxLayout(idle_left)
        idle_left_lay.setContentsMargins(0, 0, 6, 0)
        idle_left_lay.setSpacing(6)
        idle_chat_hdr = QLabel('Live Experimental Council Discussion (RAM-only)')
        idle_chat_hdr.setObjectName('sectionTitle')
        idle_left_lay.addWidget(idle_chat_hdr)

        self.idle_live_chat = QTextBrowser()
        self.idle_live_chat.setObjectName('chatView')
        self.idle_live_chat.setOpenLinks(False)
        self.idle_live_chat.anchorClicked.connect(self._on_idle_palace_link_clicked)
        idle_left_lay.addWidget(self.idle_live_chat, 1)

        seed_row = QHBoxLayout()
        self.idle_seed_edit = QLineEdit()
        self.idle_seed_edit.setPlaceholderText('Optional note or topic to drop into the Experimental Council…')
        self.idle_seed_edit.setToolTip('Drop an optional topic or note into the Experimental Council')
        self.idle_seed_edit.returnPressed.connect(self._send_owner_note_to_idle)
        seed_row.addWidget(self.idle_seed_edit, 1)
        seed_btn = QPushButton('Send to Council')
        seed_btn.setToolTip('Send note to the active Experimental Council')
        seed_btn.clicked.connect(self._send_owner_note_to_idle)
        seed_row.addWidget(seed_btn)
        idle_left_lay.addLayout(seed_row)
        idle_split.addWidget(idle_left)

        idle_right = QFrame()
        idle_right.setObjectName('memoryPanel')
        idle_right.setMinimumWidth(290)
        idle_right_lay = QVBoxLayout(idle_right)
        idle_right_lay.setContentsMargins(10, 8, 10, 8)
        idle_right_lay.setSpacing(6)

        palace_hdr = QLabel('🏛 Shared Experimental Memory')
        palace_hdr.setObjectName('sectionTitle')
        idle_right_lay.addWidget(palace_hdr)
        palace_sub = QLabel('All Experimental Mode agents share this persistent space.')
        palace_sub.setObjectName('muted')
        palace_sub.setWordWrap(True)
        palace_sub.hide()
        idle_right_lay.addWidget(palace_sub)

        self.idle_palace_list = QListWidget()
        self.idle_palace_list.setToolTip('Select any note saved by the Experimental Council to view below')
        self.idle_palace_list.currentItemChanged.connect(self._on_idle_palace_item_selected)
        idle_right_lay.addWidget(self.idle_palace_list, 1)

        self.idle_palace_viewer = QTextBrowser()
        self.idle_palace_viewer.setPlaceholderText('Select any shared Experimental Memory note or file to inspect.')
        self.idle_palace_viewer.setMaximumHeight(230)
        idle_right_lay.addWidget(self.idle_palace_viewer)
        idle_split.addWidget(idle_right)
        idle_split.setSizes([580, 300])
        idle_tab_lay.addWidget(idle_split, 1)
        self.workspace_tabs.addTab(idle_tab, '🧪 Experimental Mode')

        # ================= TAB 2: AGENT MAIL (EMAIL INTERFACE) =================
        mail_tab = QWidget()
        mail_lay = QVBoxLayout(mail_tab)
        mail_lay.setContentsMargins(0, 8, 0, 0)
        mail_lay.setSpacing(8)

        mail_top = QHBoxLayout()
        back_to_chat_btn = QPushButton('← Back to Chat')
        back_to_chat_btn.setToolTip('Return to the main Normal Mode chat workspace')
        back_to_chat_btn.clicked.connect(lambda: self._toggle_agent_mail_view(False))
        mail_top.addWidget(back_to_chat_btn)
        mail_title = QLabel('✉ Agent Mail — Idle Mode Requests & Improvement Proposals')
        mail_title.setStyleSheet('font-weight: 700; font-size: 14px; color: #e6edf3;')
        mail_top.addWidget(mail_title)
        mail_top.addStretch()
        self.mail_quota_label = QLabel('Rate Limit: 5 requests per 30 mins (5 remaining)')
        self.mail_quota_label.setStyleSheet('font-family: Consolas, monospace; font-size: 12px; color: #8b949e; background: #161b22; padding: 4px 10px; border-radius: 6px;')
        mail_top.addWidget(self.mail_quota_label)
        mail_lay.addLayout(mail_top)

        mail_split = QSplitter(Qt.Orientation.Horizontal)
        self.mail_list = QListWidget()
        self.mail_list.setMinimumWidth(230)
        self.mail_list.setToolTip('Messages and improvement proposals sent to you by Idle Mode agents')
        self.mail_list.currentItemChanged.connect(self._on_mail_item_selected)
        mail_split.addWidget(self.mail_list)

        mail_reader = QFrame()
        mail_reader.setObjectName('composerCard')
        reader_lay = QVBoxLayout(mail_reader)
        reader_lay.setContentsMargins(14, 12, 14, 12)
        reader_lay.setSpacing(8)

        self.mail_header_label = QLabel('Select an email from an Idle Mode agent to read.')
        self.mail_header_label.setWordWrap(True)
        self.mail_header_label.setTextFormat(Qt.TextFormat.RichText)
        reader_lay.addWidget(self.mail_header_label)

        mail_actions_row = QHBoxLayout()
        mail_actions_row.setSpacing(6)

        self.mail_toggle_read_btn = QPushButton('● Mark Unread')
        self.mail_toggle_read_btn.setEnabled(False)
        self.mail_toggle_read_btn.setToolTip('Toggle selected email between READ and UNREAD')
        self.mail_toggle_read_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #c9d1d9; border: 1px solid #30363d; padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #58a6ff; border-color: #58a6ff; } '
            'QPushButton:disabled { background: #161922; color: #484f58; border: 1px solid #262b36; }'
        )
        self.mail_toggle_read_btn.clicked.connect(self._toggle_selected_mail_read_state)
        mail_actions_row.addWidget(self.mail_toggle_read_btn)

        self.mail_mark_all_read_btn = QPushButton('✓ Read All')
        self.mail_mark_all_read_btn.setEnabled(False)
        self.mail_mark_all_read_btn.setToolTip('Mark all emails in Agent Mail as Read')
        self.mail_mark_all_read_btn.setStyleSheet(
            'QPushButton { background: #122d1f; color: #3fb950; border: 1px solid #2ea043; padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:disabled { background: #161922; color: #484f58; border: 1px solid #262b36; }'
        )
        self.mail_mark_all_read_btn.clicked.connect(self._mark_all_mail_read)
        mail_actions_row.addWidget(self.mail_mark_all_read_btn)

        mail_actions_row.addStretch(1)

        self.mail_delete_btn = QPushButton('🗑 Delete')
        self.mail_delete_btn.setEnabled(False)
        self.mail_delete_btn.setToolTip('Delete the selected email from Agent Mail')
        self.mail_delete_btn.setStyleSheet(
            'QPushButton { background: #2c1517; color: #f87171; border: 1px solid #ef4444; padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:disabled { background: #161922; color: #484f58; border: 1px solid #262b36; }'
        )
        self.mail_delete_btn.clicked.connect(self._delete_selected_mail)
        mail_actions_row.addWidget(self.mail_delete_btn)

        self.mail_clear_all_btn = QPushButton('🧹 Clear All')
        self.mail_clear_all_btn.setToolTip('Delete all emails in Agent Mail')
        self.mail_clear_all_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #8b949e; border: 1px solid #30363d; padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #f87171; border-color: #ef4444; }'
        )
        self.mail_clear_all_btn.clicked.connect(self._clear_all_mail)
        mail_actions_row.addWidget(self.mail_clear_all_btn)
        reader_lay.addLayout(mail_actions_row)

        mail_link_row = QHBoxLayout()
        mail_link_row.setSpacing(6)
        self.mail_open_link_btn = QPushButton('📂 Open Linked File in Shared Idle Memory')
        self.mail_open_link_btn.setToolTip('Jump directly to the proposed file or note in Shared Idle Memory')
        self.mail_open_link_btn.setEnabled(False)
        self.mail_open_link_btn.setStyleSheet(
            'QPushButton { background: #172a3a; color: #58a6ff; border: 1px solid #58a6ff; padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:disabled { background: #161922; color: #484f58; border: 1px solid #262b36; }'
        )
        self.mail_open_link_btn.clicked.connect(self._open_selected_mail_linked_file)
        mail_link_row.addWidget(self.mail_open_link_btn)
        mail_link_row.addStretch(1)
        reader_lay.addLayout(mail_link_row)

        self.mail_body_view = QTextBrowser()
        self.mail_body_view.setOpenLinks(False)
        self.mail_body_view.anchorClicked.connect(self._on_idle_palace_link_clicked)
        reader_lay.addWidget(self.mail_body_view, 1)

        reply_row = QHBoxLayout()
        self.mail_reply_edit = QLineEdit()
        self.mail_reply_edit.setPlaceholderText('Write a reply to this agent (saved into Shared Idle Memory for the council)…')
        self.mail_reply_edit.setToolTip('Type a reply to store in Shared Idle Memory for the agents to read')
        self.mail_reply_edit.returnPressed.connect(self._send_mail_reply)
        reply_row.addWidget(self.mail_reply_edit, 1)
        self.mail_reply_btn = QPushButton('↩ Send Reply to Idle Memory')
        self.mail_reply_btn.setToolTip('Save your reply into Shared Idle Memory so all Idle Mode agents can read it')
        self.mail_reply_btn.clicked.connect(self._send_mail_reply)
        reply_row.addWidget(self.mail_reply_btn)
        reader_lay.addLayout(reply_row)

        mail_split.addWidget(mail_reader)
        mail_split.setSizes([310, 570])
        mail_lay.addWidget(mail_split, 1)
        self.workspace_tabs.addTab(mail_tab, '✉ Agent Mail (0)')

        # --- DEDICATED INLINE STATUS LABEL (Outside QTextBrowser so scrolling up NEVER locks!) ---
        self.inline_status_label = QLabel('')
        self.inline_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.inline_status_label.setStyleSheet('padding: 2px 6px; font-size: 12.5px;')
        self.inline_status_label.hide()
        layout.addWidget(self.inline_status_label)

        # --- THE WORKBENCH: AGENT AVATAR CHIP ROW (Visible Across All Workspace Tabs) ---
        agent_workbench_frame = QFrame()
        agent_workbench_frame.setObjectName('agentWorkbenchBar')
        agent_workbench_frame.setFixedHeight(28)
        self.agent_workbench_frame = agent_workbench_frame
        self.providers_layout = QHBoxLayout(agent_workbench_frame)
        self.providers_layout.setContentsMargins(2, 2, 2, 2)
        self.providers_layout.setSpacing(6)
        self.loaded_agents_caption = QLabel('Agents:')
        self.loaded_agents_caption.setObjectName('loadedAIsLabel')
        self.providers_layout.addWidget(self.loaded_agents_caption)

        self.agent_chips_host = QWidget()
        self.agent_chips_grid = QGridLayout(self.agent_chips_host)
        self.agent_chips_grid.setContentsMargins(0, 0, 0, 0)
        self.agent_chips_grid.setHorizontalSpacing(4)
        self.agent_chips_grid.setVerticalSpacing(2)
        self.providers_layout.addWidget(self.agent_chips_host)

        if provider_states is None:
            try:
                raw_provs = json.loads(self.config_path.read_text()).get('providers', {})
                provider_states = {
                    name: settings.get('enabled', False)
                    for name, settings in raw_provs.items()
                    if name not in {'test', 'off'}
                }
                from fairybread_mcp import get_council_cli_platforms
                from local_cli_provider import PLATFORM_TO_CLI_PROVIDER, find_cli_binary
                for pk in get_council_cli_platforms(self.config_path):
                    prov_key = PLATFORM_TO_CLI_PROVIDER.get(pk)
                    if prov_key and find_cli_binary(pk):
                        provider_states[prov_key] = True
            except (OSError, ValueError, KeyError) as exc:
                provider_states = {}
                self.config_warning = str(exc)
        self.provider_states = provider_states
        for name, enabled in provider_states.items():
            label = QPushButton()
            label.setFlat(True)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.clicked.connect(lambda checked=False, n=name: self._on_top_provider_badge_clicked(n))
            self.provider_labels[name] = label
            if enabled == 'inactive':
                self.set_provider_status(name, 'Inactive', NEUTRAL_GREY, 'INACTIVE_IN_PROFILE: Loaded in background, click to activate.')
            else:
                self.set_provider_status(name, 'Enabled' if enabled else 'Off', provider_color(name) if enabled else NEUTRAL_GREY)
        self._relayout_agent_bar()
        self.providers_layout.addSpacing(10)

        self.copy_button = QPushButton('⧉')
        self.copy_button.setObjectName('iconButton')
        self.copy_button.setToolTip('Copy last reply to clipboard')
        self.copy_button.setAccessibleName('Copy last answer')
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_answer)
        self.copy_button.hide()
        self.providers_layout.addWidget(self.copy_button)

        self.thumb_up_button = QPushButton('▲')
        self.thumb_up_button.setObjectName('iconButton')
        self.thumb_up_button.setToolTip('Helpful reply')
        self.thumb_up_button.clicked.connect(lambda: self.status_label.setText('Feedback noted: Helpful'))
        self.thumb_up_button.hide()
        self.providers_layout.addWidget(self.thumb_up_button)

        self.thumb_down_button = QPushButton('▼')
        self.thumb_down_button.setObjectName('iconButton')
        self.thumb_down_button.setToolTip('Unhelpful reply')
        self.thumb_down_button.clicked.connect(lambda: self.status_label.setText('Feedback noted: Needs improvement'))
        self.thumb_down_button.hide()
        self.providers_layout.addWidget(self.thumb_down_button)

        self.privacy_label = QLabel()
        self.privacy_label.setObjectName('muted')
        self.privacy_label.hide()

        self.providers_layout.addStretch(1)

        self.right_status_host = QWidget()
        self.right_status_grid = QGridLayout(self.right_status_host)
        self.right_status_grid.setContentsMargins(0, 0, 0, 0)
        self.right_status_grid.setHorizontalSpacing(8)
        self.right_status_grid.setVerticalSpacing(1)

        self.status_label = ResponsiveBarLabel('Ready', on_change=self._relayout_agent_bar)
        self.status_label.setObjectName('muted')
        self.status_label.setWordWrap(False)
        self.status_label.setMaximumHeight(22)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)

        self.bottom_token_label = ResponsiveBarLabel('Tokens: 0.0k · Conv: ~$0.000', on_change=self._relayout_agent_bar)
        self.bottom_token_label.setWordWrap(False)
        self.bottom_token_label.setMaximumHeight(22)
        self.bottom_token_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.bottom_token_label.setStyleSheet(
            'font-family: Consolas, monospace; font-size: 11.5px; color: #8b949e; padding: 1px 6px;'
        )
        self.bottom_token_label.setToolTip('Live Conversation Cost Estimate (API Usage)')

        self.right_status_grid.addWidget(self.status_label, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.right_status_grid.addWidget(self.bottom_token_label, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.providers_layout.addWidget(self.right_status_host)
        self._relayout_agent_bar()
        layout.addWidget(agent_workbench_frame)
        splitter.addWidget(panel)

        # --- RIGHT SIDEBAR: SHARED MEMORY (Auto-Indexed Contextual Memory for All AIs) ---
        self.memory_panel = QFrame()
        self.memory_panel.setObjectName('memoryPanel')
        self.memory_panel.setMinimumWidth(295)
        memory_layout = QVBoxLayout(self.memory_panel)
        memory_title = QLabel('Shared Memory')
        memory_title.setObjectName('sectionTitle')
        memory_layout.addWidget(memory_title)
        memory_note = QLabel('Contextual memories automatically saved & shared across all Council AIs (like ChatGPT & Antigravity).')
        memory_note.setWordWrap(True)
        memory_note.setObjectName('muted')
        memory_layout.addWidget(memory_note)

        self.open_memory_summary_btn = QPushButton('📝 Memory Summary (View && Edit)…')
        self.open_memory_summary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_memory_summary_btn.setToolTip('View & edit your personal Memory summary')
        self.open_memory_summary_btn.setStyleSheet(
            'QPushButton { background: #132238; color: #58a6ff; border: 1px solid #3b82f6; '
            'padding: 6px 10px; border-radius: 6px; font-weight: 700; font-size: 12px; } '
            'QPushButton:hover { background: #1f365c; }'
        )
        self.open_memory_summary_btn.clicked.connect(self.show_memory_summary_dialog)
        memory_layout.addWidget(self.open_memory_summary_btn)

        self.memory_search_edit = QLineEdit()
        self.memory_search_edit.setPlaceholderText('🔍 Search shared memories…')
        self.memory_search_edit.setToolTip('Filter stored memories')
        self.memory_search_edit.textChanged.connect(lambda _t: self.refresh_memory_review(True))
        memory_layout.addWidget(self.memory_search_edit)

        self.proposal_list = QListWidget()
        self.proposal_list.setAccessibleName('Proposed memories')
        self.proposal_list.setToolTip('Click any stored memory to inspect')
        self.proposal_list.currentItemChanged.connect(self.show_memory_proposal)
        memory_layout.addWidget(self.proposal_list, 1)

        detail_title = QLabel('Memory detail')
        detail_title.setObjectName('sectionTitle')
        memory_layout.addWidget(detail_title)

        self.proposal_detail = QTextBrowser()
        self.proposal_detail.setAccessibleName('Selected memory proposal detail')
        self.proposal_detail.setPlaceholderText('Select any memory above to inspect what all Council AIs see.')
        self.proposal_detail.setMaximumHeight(210)
        memory_layout.addWidget(self.proposal_detail)

        mem_act_row = QHBoxLayout()
        self.add_memory_btn = QPushButton('+ Add Memory')
        self.add_memory_btn.setToolTip('Add standing fact or rule for all AIs')
        self.add_memory_btn.clicked.connect(self.add_standing_memory)
        self.delete_memory_btn = QPushButton('🗑 Forget Selected')
        self.delete_memory_btn.setToolTip('Delete selected memory')
        self.delete_memory_btn.clicked.connect(self.delete_selected_memory)
        mem_act_row.addWidget(self.add_memory_btn)
        mem_act_row.addWidget(self.delete_memory_btn)
        memory_layout.addLayout(mem_act_row)

        prop_btn_row = QHBoxLayout()
        self.approve_proposal_btn = QPushButton('✓ Approve && Store')
        self.approve_proposal_btn.setToolTip('Approve proposal')
        self.approve_proposal_btn.clicked.connect(self.approve_selected_proposal)
        self.approve_proposal_btn.hide()
        self.reject_proposal_btn = QPushButton('✕ Reject')
        self.reject_proposal_btn.setToolTip('Reject proposal')
        self.reject_proposal_btn.clicked.connect(self.reject_selected_proposal)
        self.reject_proposal_btn.hide()
        prop_btn_row.addWidget(self.approve_proposal_btn)
        prop_btn_row.addWidget(self.reject_proposal_btn)
        memory_layout.addLayout(prop_btn_row)

        self.durable_mem_count_label = QLabel('Shared Contextual Memories (All AIs): 0')
        self.durable_mem_count_label.setObjectName('muted')
        self.durable_mem_count_label.setWordWrap(True)
        memory_layout.addWidget(self.durable_mem_count_label)

        memory_layout.addStretch()
        self.memory_panel.hide()
        splitter.addWidget(self.memory_panel)
        self.memory_button.toggled.connect(self.memory_panel.setVisible)
        self.memory_button.toggled.connect(lambda visible: splitter.setSizes([240, 620, 295]) if visible else None)
        self.memory_button.toggled.connect(self.refresh_memory_review)
        splitter.setSizes([240, 860])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        QShortcut(QKeySequence('Ctrl+O'), self, self.choose_files)
        QShortcut(QKeySequence('Ctrl+N'), self, self.new_conversation)
        QShortcut(QKeySequence('Escape'), self, self.stop_active_turn)
        self.apply_theme(self.active_theme, render_chat=False)
        self._last_session_mtime = 0.0
        self.external_sync_timer = QTimer(self)
        self.external_sync_timer.setInterval(1200)
        self.external_sync_timer.timeout.connect(self._check_external_session_updates)
        self.external_sync_timer.start()
        self._update_ai_pill_text()
        self.update_privacy_label()
        self.refresh_projects()
        self.refresh_sessions()
        from cost_service import ConversationCostLedger, register_cost_listener
        self._cost_ledger = ConversationCostLedger()
        self._cost_event_signal.connect(self._on_cost_event)
        self._cost_listener_cb = lambda ev: self._cost_event_signal.emit(ev)
        register_cost_listener(self._cost_listener_cb)
        self.load_history()
        self._refresh_idle_view()
        self._backfill_shared_memory_once()
        self._force_quit = False
        self._tray_hint_shown = False
        self._catalog_sync_done.connect(self._apply_catalog_sync_result)
        if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            self._ensure_system_tray()
            QTimer.singleShot(1500, lambda: self.check_for_updates_and_catalog(manual=False))
        QTimer.singleShot(250, self._on_ouroboros_startup_ready)

    def _ensure_system_tray(self):
        try:
            if hasattr(self, '_tray_icon') and self._tray_icon is not None:
                return self._tray_icon
            self._tray_icon = QSystemTrayIcon(fairybread_app_qicon(), self)
            self._tray_icon.setToolTip('Fairybread — Right-click to Expand or Exit')
            tray_menu = QMenu(self)
            expand_act = QAction('🔼 Expand / Open Fairybread', tray_menu)
            expand_act.triggered.connect(self.restore_from_tray)
            tray_menu.addAction(expand_act)
            tray_menu.addSeparator()
            quit_act = QAction('✕ Exit Fairybread', tray_menu)
            quit_act.triggered.connect(self.exit_application)
            tray_menu.addAction(quit_act)
            self._tray_icon.setContextMenu(tray_menu)
            self._tray_icon.activated.connect(self._on_tray_icon_activated)
            self._tray_icon.show()
            return self._tray_icon
        except Exception:
            return None

    def _on_tray_icon_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def exit_application(self):
        self._force_quit = True
        try:
            self.stop_all_voice_modes(exit_talk_only=True)
        except Exception:
            pass
        self.close()

    def _on_ouroboros_startup_ready(self):
        """Signal READY heartbeat to `palace_watchdog.py`, capture self-inspection snapshot, and process handoff/continuation tasks."""
        try:
            from palace_ouroboros import (
                capture_palace_window_snapshot,
                consume_pending_crash_report,
                consume_post_reboot_task,
                ensure_golden_baseline_edition,
                read_pending_handoff,
                write_ready_heartbeat,
            )
            write_ready_heartbeat(os.getpid(), status='READY')
            try:
                ensure_golden_baseline_edition()
            except Exception:
                pass
            capture_palace_window_snapshot(self, tag='palace_ui_snapshot')
            handoff = read_pending_handoff(consume=True)
            if handoff:
                self._post_patch_soak_until = time.time() + 60.0
                reboot_info = handoff.get('reboot', {})
                diff_sum = reboot_info.get('applied_diff_summary', 'Upgrade applied.')
                continuity = handoff.get('continuity', {})
                resume_prompt = str(continuity.get('resumption_prompt') or '').strip()
                self.status_label.setTextFormat(Qt.TextFormat.RichText)
                self.status_label.setToolTip(f'Ouroboros Hot-Reboot Complete: {diff_sum}')
                self.status_label.setText(
                    '<span style="color:#22c55e; font-weight:700;">✓ Ready (60s Soak Active)</span>'
                )
                if resume_prompt and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
                    self.composer.setPlainText(resume_prompt)
                if continuity.get('auto_resume_idle') and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
                    self.resume_idle_session(
                        continuity,
                        diff_sum,
                        rolled_back=bool(reboot_info.get('rolled_back', False)),
                        rollback_reason=str(reboot_info.get('rollback_reason') or ''),
                        auto_step=True,
                    )

            crash_rep = consume_pending_crash_report()
            if crash_rep and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
                exc_info = crash_rep.get('exception', {})
                tb_tail = str(crash_rep.get('traceback') or '').strip()
                failed_ed = crash_rep.get('failed_edition', 'latest')
                restored_ed = crash_rep.get('restored_edition', 'last_known_good')
                trig = crash_rep.get('trigger', 'runtime_exception')
                report_md = (
                    f"### 🚨 Zero-Touch Autofallback Triggered — Agent Patch Automatically Reverted\n"
                    f"- **Failed Edition:** `{failed_ed}` (Quarantined)\n"
                    f"- **Restored Safe Edition:** `{restored_ed}`\n"
                    f"- **Trigger:** `{trig}` — `{exc_info.get('type', 'Exception')}: {exc_info.get('message', '')}`\n\n"
                    f"```text\n{tb_tail[-1200:]}\n```\n"
                    f"*Fairybread automatically rolled back and relaunched so you didn't have to manually restore. The AI Council now has this traceback in session context to fix the issue cleanly.*"
                )
                self.append_message('assistant', report_md, contributors=['palace'])
                try:
                    self.store.context(self.session_id).append_exchange(
                        '[SYSTEM AUTO-FALLBACK REPORT]',
                        report_md,
                        contributors=['palace'],
                    )
                except Exception:
                    pass

            cont_task = consume_post_reboot_task()
            if cont_task and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
                target_sid = str(cont_task.get('chat_session_id') or '').strip()
                if target_sid and target_sid != self.session_id:
                    try:
                        self.store.select(target_sid)
                        self.session_id = self.store.selected
                        self.refresh_sessions()
                        self.load_history()
                    except Exception:
                        pass
                origin = cont_task.get('origin', 'autopatch_hot_reboot')
                active_ed = cont_task.get('active_edition', 'latest')
                ctx_info = cont_task.get('context') or {}
                orig_req = ctx_info.get('user_request_summary', '')
                attempted = ctx_info.get('what_was_attempted', '')
                inst_list = cont_task.get('instructions_for_agents') or []
                inst_joined = ' '.join(inst_list)
                depth = int((cont_task.get('loop_guard') or {}).get('reboot_chain_depth', 1))
                max_depth = int((cont_task.get('loop_guard') or {}).get('max_chain_depth', 3))
                auto_prompt = (
                    f"/code [POST-REBOOT CONTINUATION — {origin.upper()} (Active Edition: {active_ed}) (Chain: {depth}/{max_depth})]: "
                    f"Attempted: \"{attempted}\" for user request: \"{orig_req}\". "
                    f"{inst_joined}"
                )
                def _fire_post_reboot_continuation(prompt_txt=auto_prompt):
                    if self.worker is None:
                        self.composer.setPlainText(prompt_txt)
                        self.send_message()
                QTimer.singleShot(1100, _fire_post_reboot_continuation)
        except Exception:
            pass

    def capture_and_insert_ui_snapshot(self):
        """Capture ONLY the PalaceWindow widget buffer (`self.grab()`), audit layout, and show in chat/viewer."""
        try:
            from palace_ouroboros import capture_palace_window_snapshot
            snap_path, audit = capture_palace_window_snapshot(self, tag='palace_ui_snapshot')
            clipped = audit.get('clipped_widget_count', 0)
            btns = audit.get('visible_button_count', 0)
            res = audit.get('snapshot_resolution', '?')
            self.status_label.setText(
                f'Captured PalaceWindow UI Snapshot ({res}, {btns} visible buttons, {clipped} clipped) — scoped strictly to Palace.'
            )
            if snap_path and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
                self._open_image_viewer_dialog(str(snap_path))
        except Exception as exc:
            self.show_notice(f'UI Snapshot error: {exc}')

    def _build_menu_bar(self):
        menubar = self.menuBar()
        palace_menu = menubar.addMenu('Fairybread')
        new_convo_act = QAction('New Conversation\tCtrl+N', self)
        new_convo_act.triggered.connect(self.new_conversation)
        palace_menu.addAction(new_convo_act)
        new_proj_act = QAction('New Project…', self)
        new_proj_act.triggered.connect(lambda: self.new_project())
        palace_menu.addAction(new_proj_act)
        attach_act = QAction('Attach Documents or Pictures…\tCtrl+O', self)
        attach_act.triggered.connect(self.choose_files)
        palace_menu.addAction(attach_act)
        palace_menu.addSeparator()
        exit_act = QAction('Exit Fairybread', self)
        exit_act.triggered.connect(self.exit_application)
        palace_menu.addAction(exit_act)

        self.mode_menu = menubar.addMenu('Mode')
        self.mode_menu.aboutToShow.connect(self._rebuild_mode_menu)
        self._rebuild_mode_menu()

        view_menu = menubar.addMenu('View')
        self.theme_menu = view_menu.addMenu('🎨 Theme')
        self._rebuild_theme_menu()
        view_menu.addSeparator()
        mem_sum_act = QAction('📝 Memory Summary (View && Edit)…', self)
        mem_sum_act.triggered.connect(self.show_memory_summary_dialog)
        view_menu.addAction(mem_sum_act)
        mem_act = QAction('Toggle Shared Memory Panel', self)
        mem_act.triggered.connect(lambda: self.memory_button.click())
        view_menu.addAction(mem_act)
        peer_act = QAction('Expand / Collapse All Peer Deliberations', self)
        peer_act.triggered.connect(self.toggle_all_deliberations)
        view_menu.addAction(peer_act)
        snap_act = QAction('Capture Fairybread UI Snapshot', self)
        snap_act.triggered.connect(self.capture_and_insert_ui_snapshot)
        view_menu.addAction(snap_act)

        settings_menu = menubar.addMenu('Settings')
        settings_act = QAction('Fairybread Settings…', self)
        settings_act.triggered.connect(lambda: self.open_manage_ais('AI Providers'))
        settings_menu.addAction(settings_act)
        access_perm_act = QAction('🛡 AI Access Permissions (Modes && Write Exclusions)…', self)
        access_perm_act.triggered.connect(lambda: self.open_manage_ais('AI Access Permissions'))
        settings_menu.addAction(access_perm_act)
        agent_defaults_act = QAction('⚙ Agent Defaults (Response && Speed)…', self)
        agent_defaults_act.triggered.connect(lambda: self.open_manage_ais('Agent Defaults'))
        settings_menu.addAction(agent_defaults_act)
        profiles_settings_act = QAction('🎛 Profiles && AI Squads…', self)
        profiles_settings_act.triggered.connect(lambda: self.open_manage_ais('Profiles'))
        settings_menu.addAction(profiles_settings_act)
        voice_settings_act = QAction('🎙️ Voice && Audio (Human Voice, Microphone && Speaker)…', self)
        voice_settings_act.triggered.connect(lambda: self.open_manage_ais('Voice & Audio'))
        settings_menu.addAction(voice_settings_act)
        email_settings_act = QAction('📧 Email && Notifications…', self)
        email_settings_act.triggered.connect(lambda: self.open_manage_ais('Email & Notifications'))
        settings_menu.addAction(email_settings_act)
        bridge_settings_act = QAction('🔗 External Agent Bridge (ChatGPT / Antigravity / Grok / Claude)…', self)
        bridge_settings_act.triggered.connect(lambda: self.open_manage_ais('External Agent Bridge (MCP)'))
        settings_menu.addAction(bridge_settings_act)
        idle_settings_act = QAction('🧪 Experimental Mode Settings…', self)
        idle_settings_act.triggered.connect(lambda: self.open_manage_ais('Experimental Mode'))
        settings_menu.addAction(idle_settings_act)
        settings_menu.addSeparator()
        restore_defaults_act = QAction('↺ Restore Default Settings…', self)
        restore_defaults_act.triggered.connect(self.show_restore_defaults_dialog)
        settings_menu.addAction(restore_defaults_act)

        help_menu = menubar.addMenu('Help')
        guide_act = QAction('📖 User Guide && Drawing Instructions…\tF1', self)
        guide_act.setShortcut(QKeySequence('F1'))
        guide_act.triggered.connect(self.show_user_guide_dialog)
        help_menu.addAction(guide_act)
        web_act = QAction('🌐 Fairybread.me (Community Forums, Skins && News) ↗', self)
        web_act.triggered.connect(lambda: webbrowser.open('https://fairybread.me'))
        help_menu.addAction(web_act)
        check_updates_act = QAction('🔄 Check for Updates && Refresh Model Rates…', self)
        check_updates_act.triggered.connect(lambda: self.check_for_updates_and_catalog(manual=True))
        help_menu.addAction(check_updates_act)
        donate_act = QAction('❤️ Donate (USD) / Corporate License…', self)
        donate_act.triggered.connect(self.show_donation_license_dialog)
        help_menu.addAction(donate_act)
        help_menu.addSeparator()
        about_act = QAction('About Fairybread', self)
        about_act.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_act)

    def _rebuild_mode_menu(self):
        if not hasattr(self, 'mode_menu'):
            return
        self.mode_menu.clear()
        normal_mode_act = QAction('💬 Normal AI Mode', self.mode_menu)
        normal_mode_act.triggered.connect(self._activate_normal_mode_from_menu)
        self.mode_menu.addAction(normal_mode_act)
        idle_act = QAction('🧪 Experimental Mode', self.mode_menu)
        idle_act.triggered.connect(self._activate_experimental_mode_from_menu)
        self.mode_menu.addAction(idle_act)
        self.mode_menu.addSeparator()
        self._populate_profiles_and_ais_menu(self.mode_menu)

    def _activate_normal_mode_from_menu(self):
        self.stop_all_voice_modes(exit_talk_only=True, notice='Normal AI Mode active · Talk Mode & Live Voice stopped.')
        self.idle_switch_btn.blockSignals(True)
        self.idle_switch_btn.setChecked(False)
        self.idle_switch_btn.blockSignals(False)
        self._on_idle_switch_toggled(False)

    def _activate_experimental_mode_from_menu(self):
        self.idle_switch_btn.blockSignals(True)
        self.idle_switch_btn.setChecked(True)
        self.idle_switch_btn.blockSignals(False)
        self._on_idle_switch_toggled(True)

    def _rebuild_theme_menu(self):
        if not hasattr(self, 'theme_menu'):
            return
        self.theme_menu.clear()
        for t_id, t_name in list_available_themes():
            t_act = QAction(t_name, self.theme_menu)
            t_act.triggered.connect(lambda _c=False, tid=t_id: self._switch_theme_and_persist(tid))
            self.theme_menu.addAction(t_act)
        self.theme_menu.addSeparator()
        import_theme_act = QAction('📥 Import Custom Theme (.json)…', self.theme_menu)
        import_theme_act.triggered.connect(self.import_custom_theme_file)
        self.theme_menu.addAction(import_theme_act)
        get_skins_act = QAction('🌐 Get More Skins on Fairybread.me ↗', self.theme_menu)
        get_skins_act.triggered.connect(lambda: webbrowser.open('https://fairybread.me'))
        self.theme_menu.addAction(get_skins_act)
        open_themes_act = QAction('📂 Open Custom Themes Folder…', self.theme_menu)
        open_themes_act.triggered.connect(lambda: os.startfile(str(get_themes_dir())) if hasattr(os, 'startfile') else None)
        self.theme_menu.addAction(open_themes_act)

    def import_custom_theme_file(self):
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            'Import Fairybread Theme (.json)',
            '',
            'Fairybread Theme JSON (*.json)',
        )
        if not path_str:
            return
        try:
            src = Path(path_str)
            data = json.loads(src.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or 'bg_main' not in data:
                self.show_notice('Invalid theme file: expected a JSON dictionary containing "bg_main".')
                return
            slug = re.sub(r'[^a-z0-9_]+', '_', str(data.get('id') or src.stem).lower()).strip('_') or 'custom_theme'
            data['id'] = slug
            dest = get_themes_dir() / f'{slug}.json'
            dest.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
            self._rebuild_theme_menu()
            self._switch_theme_and_persist(slug)
            self.show_notice(f'✓ Imported and activated theme: {data.get("name", slug)}')
        except Exception as exc:
            self.show_notice(f'Could not import theme: {exc}')

    def show_donation_license_dialog(self):
        from palace_config import CORPORATE_LICENSE_MAILTO, DONATION_TIER_URLS

        dlg = QDialog(self)
        dlg.setWindowTitle('Support Fairybread — Voluntary USD Donation & Corporate Licensing')
        dlg.resize(720, 480)
        dlg.setStyleSheet('background:#0d1117; color:#f0f6fc;')
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        hdr = QLabel(
            '<h3 style="margin:0; color:#f0f6fc;">🧚 A Personal Note from Brett — Why Your Support Matters</h3>'
            '<p style="color:#c9d1d9; font-size:13px; margin-top:6px;">'
            'I built <b>Fairybread</b> to replace corporate lock-in (ChatGPT Plus, Claude Pro, Grok) with '
            '<b>100% local, private persistent memory</b> and zero monthly fees—plus an autonomous <b>Experimental Mode</b> '
            'where you can run your own multi-AI experiments.<br><br>'
            'In real life, I am a disabled man living on a disability pension, and I struggle to pay my everyday bills. '
            'Fairybread is <b>free for personal use (up to 2 seats)</b>, but if you enjoy it and can spare a donation, '
            '<b>it will genuinely help me pay my bills and keep building.</b> My appreciation is enormous!<br><br>'
            '<b>What Supporters Get:</b> The <b>Fairybread Newsletter</b> ($10+), <b>Release Notes &amp; Early Theme/Add-On Previews</b> ($25+), '
            '<b>Beta Test Group &amp; Priority Code Requests</b> ($50+), or <b>1-on-1 Setup Consulting &amp; Custom Code</b> ($350).'
            '</p>'
        )
        hdr.setWordWrap(True)
        hdr.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(hdr)

        tier_lbl = QLabel('<b>One-Click Voluntary Donation (in USD via GitHub Sponsors):</b>')
        tier_lbl.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(tier_lbl)

        tier_row = QHBoxLayout()
        tier_specs = [
            ('$5 USD', '5', '#1f6feb'),
            ('$10 USD', '10', '#238636'),
            ('$25 USD', '25', '#8957e5'),
            ('$50 USD', '50', '#d29922'),
            ('$350 USD', '350', '#b62324'),
            ('Other (USD)', 'other', '#30363d'),
        ]
        for btn_text, key, bg_col in tier_specs:
            b = QPushButton(btn_text, dlg)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f'QPushButton {{ background:{bg_col}; color:#ffffff; border:1px solid #f0f6fc33; '
                f'border-radius:8px; padding:9px 12px; font-size:13px; font-weight:700; }} '
                f'QPushButton:hover {{ opacity:0.9; border-color:#ffffff; }}'
            )
            url = DONATION_TIER_URLS.get(key, DONATION_TIER_URLS['other'])
            b.clicked.connect(lambda _c=False, u=url: webbrowser.open(u))
            tier_row.addWidget(b)
        v.addLayout(tier_row)

        corp_frame = QFrame(dlg)
        corp_frame.setStyleSheet('background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px;')
        corp_lay = QVBoxLayout(corp_frame)
        corp_txt = QLabel(
            '<b>🏢 Business &amp; Corporate Licensing (More Than 2 Seats):</b><br>'
            '<span style="color:#8b949e; font-size:12.5px;">'
            'For businesses, companies, and organizations deploying Fairybread across <b>more than two (2) seats</b>, '
            'a commercial corporate license fee is negotiable. Contact the creator directly to arrange a team or site license.'
            '</span>'
        )
        corp_txt.setWordWrap(True)
        corp_txt.setTextFormat(Qt.TextFormat.RichText)
        corp_lay.addWidget(corp_txt)

        corp_btn = QPushButton('✉ Inquire About Corporate License (> 2 Seats) — bm069au@gmail.com', corp_frame)
        corp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        corp_btn.setStyleSheet(
            'QPushButton { background:#21262d; color:#58a6ff; border:1px solid #388bfd; '
            'border-radius:6px; padding:7px 14px; font-weight:600; }'
        )
        corp_btn.clicked.connect(lambda: webbrowser.open(CORPORATE_LICENSE_MAILTO))
        corp_lay.addWidget(corp_btn)
        v.addWidget(corp_frame)

        v.addStretch(1)
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        close_btn = QPushButton('Continue to Fairybread', dlg)
        close_btn.setStyleSheet(
            'background:#21262d; color:#f0f6fc; border:1px solid #30363d; '
            'border-radius:6px; padding:7px 20px; font-weight:600;'
        )
        close_btn.clicked.connect(dlg.accept)
        bottom_row.addWidget(close_btn)
        v.addLayout(bottom_row)
        dlg.exec()

    def show_user_guide_dialog(self):
        guide_path = Path(__file__).with_name('USER_GUIDE.md')
        md_text = (
            guide_path.read_text(encoding='utf-8', errors='replace')
            if guide_path.exists()
            else '# Fairybread User Guide\n\nUser guide file (`USER_GUIDE.md`) not found.'
        )
        dlg = QDialog(self)
        dlg.setWindowTitle('Fairybread — User Guide & Drawing Instructions')
        dlg.resize(860, 680)
        dlg.setStyleSheet('background:#0d1117; color:#f0f6fc;')
        v = QVBoxLayout(dlg)
        browser = QTextBrowser(dlg)
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(
            'background:#131720; color:#e6edf3; border:1px solid #262c3a; '
            'border-radius:8px; padding:14px; font-size:13px;'
        )
        browser.setMarkdown(md_text)
        v.addWidget(browser, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton('Close', dlg)
        close_btn.setStyleSheet(
            'background:#21262d; color:#f0f6fc; border:1px solid #30363d; '
            'border-radius:6px; padding:6px 18px; font-weight:600;'
        )
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)
        dlg.exec()

    def show_mission_ethics_dialog(self):
        self.open_manage_ais(initial_page='Idle Mode')

    def show_about_dialog(self):
        from palace_config import FAIRYBREAD_VERSION, IS_DEVELOPER_EDITION
        ed_label = 'Developer Edition' if IS_DEVELOPER_EDITION else 'Public Edition'
        pub_note = (
            ''
            if IS_DEVELOPER_EDITION
            else (
                '<p style="color:#eab308; font-size:11.5px;"><b>Public Edition Safety Note:</b> '
                'Live code self-modification is disabled in non-Developer builds to keep installations verified and consistent. '
                'Share proposed patches or ideas on the <a href="https://fairybread.me/forum.html">Fairybread Forum</a> '
                'or email <a href="mailto:bm069au@gmail.com">bm069au@gmail.com</a>.</p>'
            )
        )
        box = QMessageBox(self)
        box.setWindowTitle(f'About Fairybread ({ed_label} · Beta v{FAIRYBREAD_VERSION})')
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f'<h3>Fairybread ({ed_label} · Beta v{FAIRYBREAD_VERSION}) — Multi-AI Council &amp; Shared Memory Workspace</h3>'
            '<p>Created by <b>Brett Martin Moore</b>.</p>'
            f'{pub_note}'
            '<p><b>License:</b> Proprietary Source-Available Donationware (NOT Open Source) — Copyright &copy; 2026 Brett Martin Moore. All Rights Reserved. '
            'Free for personal use &amp; small teams (up to 2 seats); no redistribution, competing forks, or rebranding without written permission. '
            'For businesses/companies using more than 2 seats, a negotiable corporate license applies.</p>'
            '<p style="color:#8b949e; font-size:11.5px;">UI powered by Qt for Python (PySide6, dynamically linked under LGPL v3).</p>'
            '<p>Contact &amp; Corporate Licensing: <a href="mailto:bm069au@gmail.com">bm069au@gmail.com</a></p>'
        )
        contact_btn = box.addButton('Contact / Corporate License', QMessageBox.ButtonRole.ActionRole)
        donate_btn = box.addButton('❤️ Donate (USD)', QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == contact_btn:
            webbrowser.open('mailto:bm069au@gmail.com?subject=Fairybread%20Support%20or%20Corporate%20License')
        elif box.clickedButton() == donate_btn:
            self.show_donation_license_dialog()

    @staticmethod
    def _build_palace(context):
        from palace_cli import build_configured_palace
        return build_configured_palace(context_service=context)

    def _toggle_pinned_section(self, expanded: bool):
        self.pinned_toggle_btn.setText('⌄  Pinned' if expanded else '›  Pinned')
        self.pinned_list.setVisible(expanded and self.pinned_list.count() > 0)

    def _toggle_discussions_section(self, expanded: bool):
        self.discussions_toggle_btn.setText('⌄  Discussions' if expanded else '›  Discussions')
        self.session_list.setVisible(expanded)

    def _sync_sidebar_working_indicator(self):
        if hasattr(self, 'session_list') and hasattr(self.session_list, 'set_working_state'):
            self.session_list.set_working_state(
                getattr(self, '_active_working_session_id', None),
                getattr(self, 'pulse_step', 0),
            )

    def _toggle_session_pin_by_id(self, sid: str):
        if not sid or not hasattr(self.store, 'toggle_pin'):
            return
        try:
            pinned = self.store.toggle_pin(sid)
            self.refresh_sessions()
            self.status_label.setText('Conversation pinned' if pinned else 'Conversation unpinned')
        except Exception as exc:
            self.show_notice(str(exc))

    def _rename_session_by_id(self, sid: str, new_title: str | None = None) -> bool:
        sess = next((s for s in getattr(self.store, 'sessions', []) if s.get('id') == sid), None)
        if sess is None or not hasattr(self.store, 'rename_session'):
            return False
        cur_title = str(sess.get('title') or 'Conversation')
        if new_title is None:
            txt, ok = QInputDialog.getText(self, 'Rename Discussion', 'New title:', text=cur_title)
            if not ok or not txt.strip():
                return False
            new_title = txt
        try:
            updated = self.store.rename_session(sid, new_title)
            self.refresh_sessions()
            if sid == self.session_id:
                self._update_breadcrumb(updated)
            self.status_label.setText(f'Renamed discussion to "{updated}"')
            return True
        except Exception as exc:
            self.show_notice(str(exc))
            return False

    def _toggle_session_unread(self, sid: str, unread: bool | None = None) -> bool:
        sess = next((s for s in getattr(self.store, 'sessions', []) if s.get('id') == sid), None)
        if sess is None or not hasattr(self.store, 'set_unread'):
            return False
        target = (not bool(sess.get('unread', False))) if unread is None else bool(unread)
        try:
            self.store.set_unread(sid, target)
            self.refresh_sessions()
            self.status_label.setText('Marked discussion as Unread' if target else 'Marked discussion as Read')
            return True
        except Exception as exc:
            self.show_notice(str(exc))
            return False

    def _toggle_session_archive(self, sid: str, archived: bool | None = None) -> bool:
        sess = next((s for s in getattr(self.store, 'sessions', []) if s.get('id') == sid), None)
        if sess is None or not hasattr(self.store, 'set_archived'):
            return False
        target = (not bool(sess.get('archived', False))) if archived is None else bool(archived)
        try:
            self.store.set_archived(sid, target)
            if target and sid == self.session_id:
                nxt = next(
                    (s for s in getattr(self.store, 'sessions', []) if s.get('id') != sid and not s.get('archived')),
                    None,
                )
                if nxt is not None:
                    self.store.select(nxt['id'])
                    self.session_id = nxt['id']
                    self.load_history()
            self.refresh_projects()
            self.refresh_sessions()
            self.status_label.setText('Archived discussion' if target else 'Restored discussion from Archive')
            return True
        except Exception as exc:
            self.show_notice(str(exc))
            return False

    def _duplicate_session_by_id(self, sid: str) -> str | None:
        if not hasattr(self.store, 'duplicate_session'):
            return None
        try:
            new_sid = self.store.duplicate_session(sid)
            if self.worker is not None:
                self._detach_active_worker()
            self.session_id = new_sid
            self.reset_draft()
            self.refresh_projects()
            self.refresh_sessions()
            self.load_history()
            self.status_label.setText('Duplicated discussion')
            return new_sid
        except Exception as exc:
            self.show_notice(str(exc))
            return None

    def _delete_session_by_id(self, sid: str, *, confirm: bool = True) -> bool:
        sess = next((s for s in getattr(self.store, 'sessions', []) if s.get('id') == sid), None)
        if sess is None or not hasattr(self.store, 'delete_session'):
            return False
        title = str(sess.get('title') or 'Conversation')
        if confirm:
            ans = QMessageBox.question(
                self,
                'Delete Discussion',
                f'Delete "{title}" and its local transcript?\nThis cannot be undone.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return False
        try:
            if (sid == self.session_id or sid == getattr(self, '_active_working_session_id', None)) and self.worker is not None:
                if getattr(self, 'active_cancel_event', None) is not None:
                    self.active_cancel_event.set()
                self._detach_active_worker()
            new_active = self.store.delete_session(sid)
            self.session_id = new_active
            self.reset_draft()
            self.refresh_projects()
            self.refresh_sessions()
            self.load_history()
            self.status_label.setText(f'Deleted discussion "{title}"')
            return True
        except Exception as exc:
            self.show_notice(str(exc))
            return False

    def _copy_session_content(self, sid: str, *, mode: str = 'transcript') -> bool:
        sess = next((s for s in getattr(self.store, 'sessions', []) if s.get('id') == sid), None)
        if sess is None:
            return False
        if mode == 'title':
            QApplication.clipboard().setText(str(sess.get('title') or 'Conversation'))
            self.status_label.setText('Copied discussion title')
            return True
        try:
            msgs = self.store.messages(sid)
            lines = [f"# {sess.get('title') or 'Conversation'}\n"]
            for m in msgs:
                role = str(m.get('role') or 'user').upper()
                lines.append(f"## {role}\n{m.get('content') or ''}\n")
            QApplication.clipboard().setText('\n'.join(lines).strip())
            self.status_label.setText(f'Copied transcript ({len(msgs)} message(s))')
            return True
        except Exception as exc:
            self.show_notice(str(exc))
            return False

    def _rename_project_by_id(self, proj_id: str, new_name: str | None = None) -> bool:
        proj = next((p for p in getattr(self.store, 'projects', []) if p.get('id') == proj_id), None)
        if proj is None or not hasattr(self.store, 'rename_project'):
            return False
        cur_name = str(proj.get('name') or 'Project')
        if new_name is None:
            txt, ok = QInputDialog.getText(self, 'Rename Project', 'New project name:', text=cur_name)
            if not ok or not txt.strip():
                return False
            new_name = txt
        try:
            updated = self.store.rename_project(proj_id, new_name)
            self.refresh_projects()
            self.refresh_sessions()
            self.status_label.setText(f'Renamed project to "{updated}"')
            return True
        except Exception as exc:
            self.show_notice(str(exc))
            return False

    def _delete_project_by_id(self, proj_id: str, *, confirm: bool = True) -> bool:
        proj = next((p for p in getattr(self.store, 'projects', []) if p.get('id') == proj_id), None)
        if proj is None or not hasattr(self.store, 'delete_project'):
            return False
        pname = str(proj.get('name') or 'Project')
        if confirm:
            ans = QMessageBox.question(
                self,
                'Delete Project',
                f'Remove project "{pname}"?\nIts discussions will move to Conversations.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return False
        try:
            self.store.delete_project(proj_id, move_sessions_to_unassigned=True)
            self.session_id = self.store.selected
            self.refresh_projects()
            self.refresh_sessions()
            self.load_history()
            self.status_label.setText(f'Removed project "{pname}"')
            return True
        except Exception as exc:
            self.show_notice(str(exc))
            return False

    def _new_conversation_in_project(self, proj_id: str | None = None):
        if proj_id:
            try:
                self.store.select_project(proj_id)
            except Exception as exc:
                self.show_notice(str(exc))
                return
        self.new_conversation()

    def _show_session_context_menu(self, list_widget: QListWidget, pos: QPoint, explicit_item: QListWidgetItem | None = None):
        item = explicit_item or list_widget.itemAt(pos)
        if item is None:
            return
        raw_role = str(item.data(Qt.ItemDataRole.UserRole) or '')
        if not raw_role or raw_role == 'archived_toggle':
            return
        menu = QMenu(self)
        if raw_role.startswith('proj:'):
            proj_id = raw_role.split(':', 1)[1] or None
            new_in_proj = menu.addAction('+ New Conversation Here')
            rename_proj_act = menu.addAction('✎ Rename Project…') if proj_id else None
            attach_act = None
            detach_act = None
            delete_proj_act = None
            if proj_id:
                cur_folder = self.store.get_project_folder(proj_id) if hasattr(self.store, 'get_project_folder') else ''
                attach_act = menu.addAction('📁 Change Attached Folder…' if cur_folder else '📁 Attach Folder to Project…')
                if cur_folder:
                    detach_act = menu.addAction('✕ Detach Folder')
                menu.addSeparator()
                delete_proj_act = menu.addAction('🗑 Delete Project…')
            chosen = menu.exec(list_widget.mapToGlobal(pos))
            if chosen == new_in_proj:
                self._new_conversation_in_project(proj_id)
            elif rename_proj_act is not None and chosen == rename_proj_act:
                self._rename_project_by_id(proj_id)
            elif attach_act is not None and chosen == attach_act:
                self.attach_folder_to_current_project(project_id=proj_id)
            elif detach_act is not None and chosen == detach_act:
                self.attach_folder_to_current_project(project_id=proj_id, folder_path='')
            elif delete_proj_act is not None and chosen == delete_proj_act:
                self._delete_project_by_id(proj_id)
            return

        sid = raw_role
        sess = next((s for s in getattr(self.store, 'sessions', []) if s.get('id') == sid), None)
        if sess is None:
            return
        is_pinned = bool(sess.get('pinned', False))
        is_unread = bool(sess.get('unread', False))
        is_archived = bool(sess.get('archived', False))

        rename_act = menu.addAction('✎ Rename…')
        pin_act = menu.addAction('📌 Unpin' if is_pinned else '📌 Pin')
        unread_act = menu.addAction('✓ Mark Read' if is_unread else '● Mark Unread')
        menu.addSeparator()
        copy_menu = menu.addMenu('📋 Copy')
        copy_title_act = copy_menu.addAction('Copy Title')
        copy_full_act = copy_menu.addAction('Copy Full Transcript')
        dup_act = menu.addAction('⧉ Duplicate Discussion')
        move_actions = {}
        projects = getattr(self.store, 'projects', [])
        if projects and hasattr(self.store, 'assign_session_project'):
            move_menu = menu.addMenu('📁 Move to Project…')
            for proj in projects:
                act = move_menu.addAction(f'📁 {proj["name"]}')
                move_actions[act] = proj['id']
            none_act = move_menu.addAction('General (No Project)')
            move_actions[none_act] = None
        menu.addSeparator()
        arch_act = menu.addAction('↩ Unarchive' if is_archived else '📦 Archive')
        del_act = menu.addAction('🗑 Delete')

        chosen = menu.exec(list_widget.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == rename_act:
            self._rename_session_by_id(sid)
        elif chosen == pin_act:
            self._toggle_session_pin_by_id(sid)
        elif chosen == unread_act:
            self._toggle_session_unread(sid, unread=not is_unread)
        elif chosen == copy_title_act:
            self._copy_session_content(sid, mode='title')
        elif chosen == copy_full_act:
            self._copy_session_content(sid, mode='transcript')
        elif chosen == dup_act:
            self._duplicate_session_by_id(sid)
        elif chosen in move_actions:
            self.store.assign_session_project(sid, move_actions[chosen])
            self.refresh_projects()
            self.refresh_sessions()
        elif chosen == arch_act:
            self._toggle_session_archive(sid, archived=not is_archived)
        elif chosen == del_act:
            self._delete_session_by_id(sid)

    def _update_ai_pill_text(self):
        if getattr(self, '_talk_only_mode', False):
            self.ai_pill_button.setText('🎙️ Talk Only  ▾')
            self.ai_pill_button.setToolTip(
                'Talk Mode Only active — 1 fast voice AI, zero council/tools/delegation (click to switch modes)'
            )
            return
        self.ai_pill_button.setToolTip('Select active AIs or Squad')
        active_names = [n for n, en in self.provider_states.items() if en is True]
        active_count = len(active_names)
        cap_suffix = f'/{self.max_ais_per_turn}' if self.max_ais_per_turn and self.max_ais_per_turn < active_count else ''
        if self.current_squad_label:
            self.ai_pill_button.setText(f'{self.current_squad_label} ({active_count}{cap_suffix})  ▾')
        elif active_count == 1:
            only = active_names[0]
            self.ai_pill_button.setText(f'{provider_icon(only)} {provider_display_name(only)}  ▾')
        elif active_count > 0:
            self.ai_pill_button.setText(f'Choose AIs ({active_count}{cap_suffix})  ▾')
        else:
            self.ai_pill_button.setText('Choose AIs  ▾')

    def _populate_profiles_and_ais_menu(self, menu: QMenu, menu_style: str = ''):
        configs = load_provider_configs(self.config_path)
        prov_states = getattr(self, 'provider_states', {}) or {}
        all_names = list(dict.fromkeys([
            *prov_states.keys(),
            *configs.keys(),
        ]))
        if not all_names:
            all_names = ['gemini', 'openai', 'deepseek', 'groq', 'qwen', 'cohere', 'mistral']

        def _esc_amp(txt: str) -> str:
            return re.sub(r'(?<!&)&(?!&)', '&&', str(txt or ''))

        menu.setToolTipsVisible(True)
        talk_active = bool(getattr(self, '_talk_only_mode', False))
        live_active = bool(hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked())
        talk_label = (
            '⏹  Stop Talk Mode Only (Currently ON)'
            if (talk_active or live_active)
            else '🎙️  Talk Mode Only (Fast Voice Chat · No Council)'
        )
        talk_only_act = QAction(talk_label, menu)
        talk_only_act.setCheckable(True)
        talk_only_act.setChecked(talk_active or live_active)
        talk_only_act.setToolTip(
            '1 fast non-thinking voice AI with Shared Memory Palace access — click again to stop Talk Mode'
        )
        talk_only_act.triggered.connect(
            lambda checked=False, _was_on=(talk_active or live_active): self.stop_all_voice_modes(
                notice='Talk Mode Only / Live Voice stopped.'
            )
            if (_was_on or not checked)
            else self._activate_talk_only_mode(auto_start_live_voice=True)
        )
        menu.addAction(talk_only_act)
        menu.addSeparator()

        squad_dict = load_ai_squads(self.config_path)
        for _sq_key, sq_val in squad_dict.items():
            squad_title = str(sq_val.get('label') or _sq_key)
            squad_title_menu = _esc_amp(squad_title)
            members = list(sq_val.get('providers') or [])
            default_delib = bool(sq_val.get('deliberate', True))
            default_code = bool(sq_val.get('code_access', False))
            max_cap = int(sq_val.get('max_ais') or 0)
            avail_members = [m for m in members if m in all_names] or members
            sub = menu.addMenu(f'{squad_title_menu}')
            if menu_style:
                sub.setStyleSheet(menu_style)
            joined_disp = ', '.join(_esc_amp(provider_display_name(m)) for m in avail_members)
            cap_note = f' [Max {max_cap}]' if max_cap > 0 else ''
            all_act = QAction(f'All {squad_title_menu}{cap_note}: {joined_disp}', sub)
            all_act.triggered.connect(
                lambda _c=False, st=squad_title, ms=avail_members, dl=default_delib, dc=default_code, mc=max_cap:
                self._apply_squad_preset(st, ms, deliberate=dl, palace_code=dc, max_ais=mc)
            )
            sub.addAction(all_act)
            sub.addSeparator()
            for m in avail_members:
                single_act = QAction(
                    provider_qicon(m, checked=(prov_states.get(m) is True)),
                    f'Only {_esc_amp(provider_display_name(m))} ({squad_title_menu})',
                    sub,
                )
                single_act.triggered.connect(
                    lambda _c=False, m_name=m, dc=default_code:
                    self._apply_squad_preset(
                        f'{provider_icon(m_name)} {provider_display_name(m_name)}',
                        [m_name],
                        deliberate=False,
                        palace_code=dc,
                        max_ais=1,
                    )
                )
                sub.addAction(single_act)

        all_en_act = QAction('🌐  All Configured AIs', menu)
        all_en_act.triggered.connect(
            lambda: self._apply_squad_preset(
                '🌐 All AIs',
                all_names,
                deliberate=True,
                palace_code=bool(getattr(self, 'palace_code_btn', None) and self.palace_code_btn.isChecked()),
                max_ais=0,
            )
        )
        menu.addAction(all_en_act)

        custom_act = QAction('✋  Custom Selection && How Many AIs…', menu)
        custom_act.triggered.connect(self._open_custom_ai_picker)
        menu.addAction(custom_act)

        menu.addSeparator()
        for name in all_names:
            is_active = (prov_states.get(name) is True)
            disp = _esc_amp(provider_display_name(name))
            model_hint = _esc_amp(configs.get(name, {}).get('model', ''))
            label_txt = f'  {disp}  ({model_hint})' if model_hint else f'  {disp}'
            act = QAction(provider_qicon(name, checked=is_active), label_txt, menu)
            act.triggered.connect(lambda _checked=False, n=name, cur=is_active: self._toggle_provider_quick(n, not cur))
            menu.addAction(act)

        menu.addSeparator()
        edit_prof_act = QAction('🎛  Customize Profiles && Squads…', menu)
        edit_prof_act.triggered.connect(lambda: self.open_manage_ais('Profiles'))
        menu.addAction(edit_prof_act)

        manage_act = QAction('⚙  Manage AI Keys, Models && Tools…', menu)
        manage_act.triggered.connect(lambda: self.open_manage_ais('AI Providers'))
        menu.addAction(manage_act)

    @Slot()
    def _show_choose_ais_menu(self):
        if self.worker is not None:
            return
        menu_style = (
            'QMenu { background: #161922; color: #e6edf3; border: 1px solid #2b313e; padding: 6px; border-radius: 8px; } '
            'QMenu::item { padding: 6px 14px 6px 10px; border-radius: 5px; font-size: 13px; } '
            'QMenu::item:selected { background: #232938; }'
        )
        menu = QMenu(self)
        menu.setStyleSheet(menu_style)
        self._populate_profiles_and_ais_menu(menu, menu_style=menu_style)

        pos = self.ai_pill_button.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        if pos.y() < 40:
            pos = self.ai_pill_button.mapToGlobal(QPoint(0, self.ai_pill_button.height() + 4))
        menu.exec(pos)

    def _activate_talk_only_mode(self, auto_start_live_voice: bool = True):
        self._talk_only_mode = True
        self.current_squad_label = '🎙️ Talk Only'
        if self.idle_switch_btn.isChecked():
            self.idle_switch_btn.setChecked(False)
        self._update_ai_pill_text()
        self._refresh_voice_bar_pills()
        if hasattr(self, 'voice_brain_btn'):
            self.voice_brain_btn.show()
        if hasattr(self, 'voice_tts_btn'):
            self.voice_tts_btn.show()
        if hasattr(self, 'end_talk_btn'):
            self.end_talk_btn.show()
        self._sync_composer_live_bar_visibility()
        self._sync_voice_footer_state()
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setText(
            '<b>🎙️ Talk Mode Only</b> · Use <b>🧠</b> to pick Thinking AI &amp; <b>🔊</b> to pick Voice · Click <b>✕ End Talk</b> or <b>■</b> anytime to stop'
        )
        if (
            auto_start_live_voice
            and os.environ.get('QT_QPA_PLATFORM') != 'offscreen'
            and hasattr(self, 'live_voice_button')
            and not self.live_voice_button.isChecked()
        ):
            self.live_voice_button.setChecked(True)

    def _exit_talk_only_mode(self, silent: bool = False, *, stop_voice: bool = True):
        if stop_voice:
            self.stop_all_voice_modes(exit_talk_only=False)
        self._talk_only_mode = False
        if self.current_squad_label == '🎙️ Talk Only':
            self.current_squad_label = ''
        if hasattr(self, 'end_talk_btn'):
            self.end_talk_btn.hide()
        if not (hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked()):
            if hasattr(self, 'voice_brain_btn'):
                self.voice_brain_btn.hide()
            if hasattr(self, 'voice_tts_btn'):
                self.voice_tts_btn.hide()
        self._sync_composer_live_bar_visibility()
        self._sync_voice_footer_state()
        self._update_ai_pill_text()
        if not silent:
            self.status_label.setTextFormat(Qt.TextFormat.PlainText)
            self.status_label.setText('Talk Mode Only OFF · Normal AI squad active')

    def _apply_squad_preset(self, label: str, active_list: list[str], deliberate: bool = True, palace_code: bool = False, max_ais: int = 0):
        if getattr(self, '_talk_only_mode', False) or (hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked()):
            self.stop_all_voice_modes(exit_talk_only=True)
        self._talk_only_mode = False
        self.current_squad_label = label
        self.max_ais_per_turn = max(0, int(max_ais or 0))
        if self.idle_switch_btn.isChecked():
            self.idle_switch_btn.setChecked(False)
        all_known = list(dict.fromkeys([*self.provider_states.keys(), *active_list]))
        for name in all_known:
            en = name in active_list
            self.provider_states[name] = en
            try:
                if self.config_path.exists():
                    set_provider_enabled(name, en, config_path=self.config_path)
            except Exception:
                pass
            if name not in self.provider_labels:
                btn = QPushButton()
                btn.setFlat(True)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda checked=False, n=name: self._on_top_provider_badge_clicked(n))
                self.provider_labels[name] = btn
            self.set_provider_status(
                name,
                'Enabled' if en else 'Inactive',
                provider_color(name) if en else '#6e7681',
                '' if en else f'Inactive in {label}'
            )
        self._relayout_agent_bar()
        self.peer_rounds_toggle.setChecked(deliberate)
        self.palace_code_btn.setChecked(palace_code)
        self._update_ai_pill_text()
        if len(active_list) <= 4:
            badges = '&nbsp;&nbsp;'.join(format_ai_badge_html(n) for n in active_list)
        else:
            badges = f'{len(active_list)} AIs active'
        delib_txt = 'Deliberation: ON' if deliberate else 'Direct (1-Round): ON'
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setText(f'Squad: <b>{html.escape(label)}</b> · {badges} · {delib_txt}')

    def _open_custom_ai_picker(self):
        dlg = CustomAIPickerDialog(
            self,
            provider_states=self.provider_states,
            max_ais=self.max_ais_per_turn,
            config_path=self.config_path,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if getattr(self, '_talk_only_mode', False):
                self.stop_all_voice_modes(exit_talk_only=True)
            self._talk_only_mode = False
            chosen = dlg.selected_providers()
            self.max_ais_per_turn = dlg.selected_max_ais()
            self.current_squad_label = '✋ Custom'
            for name, en in chosen.items():
                self.provider_states[name] = en
                try:
                    if self.config_path.exists():
                        set_provider_enabled(name, en, config_path=self.config_path)
                except Exception:
                    pass
                self.set_provider_status(
                    name,
                    'Enabled' if en else 'Inactive',
                    provider_color(name) if en else '#6e7681',
                    '' if en else 'Inactive in Custom Selection',
                )
            self._update_ai_pill_text()
            active_names = [n for n, en in chosen.items() if en]
            badges = '&nbsp;&nbsp;'.join(format_ai_badge_html(n) for n in active_names) or 'None'
            cap_txt = f' · Max {self.max_ais_per_turn}/turn' if self.max_ais_per_turn else ''
            self.status_label.setTextFormat(Qt.TextFormat.RichText)
            self.status_label.setText(f'Custom AI Selection: {badges}{cap_txt}')

    def _on_top_provider_badge_clicked(self, name: str):
        if self.worker is not None:
            self._show_provider_badge_info(name)
            return
        cur_active = (self.provider_states.get(name) is True)
        self._toggle_provider_quick(name, not cur_active)

    def _toggle_provider_quick(self, name: str, enabled: bool):
        from local_cli_provider import CLI_PROVIDER_TO_PLATFORM
        if getattr(self, '_talk_only_mode', False):
            self.stop_all_voice_modes(exit_talk_only=True)
        self._talk_only_mode = False
        self.current_squad_label = ''
        self.provider_states[name] = enabled
        if name not in CLI_PROVIDER_TO_PLATFORM:
            try:
                if self.config_path.exists():
                    set_provider_enabled(name, enabled, config_path=self.config_path)
            except Exception:
                pass
        if name not in self.provider_labels:
            label = QPushButton()
            label.setFlat(True)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.clicked.connect(lambda checked=False, n=name: self._on_top_provider_badge_clicked(n))
            self.provider_labels[name] = label
        self.set_provider_status(
            name,
            'Enabled' if enabled else 'Inactive',
            provider_color(name) if enabled else '#6e7681',
            '' if enabled else 'Unticked for this discussion (click badge to re-enable)'
        )
        self._relayout_agent_bar()
        self._update_ai_pill_text()
        state_word = 'enabled' if enabled else 'paused for this discussion'
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setText(f'{format_ai_badge_html(name)} · {state_word}')

    def _toggle_agent_mail_view(self, checked: bool | None = None):
        want_mail = self.sidebar_mail_btn.isChecked() if checked is None else bool(checked)
        if want_mail:
            self._refresh_agent_mail_tab()
            self.workspace_tabs.setCurrentIndex(2)
        else:
            if self.idle_switch_btn.isChecked() or self.current_profile == 'Idle':
                self.workspace_tabs.setCurrentIndex(1)
            else:
                self.workspace_tabs.setCurrentIndex(0)

    def _on_no_history_toggled(self, no_history_active: bool):
        self.no_history_btn.setIcon(no_history_qicon(no_history_active))
        self.no_history_btn.setText(' No-History')
        self.no_history_banner.setVisible(no_history_active)
        if self.history_toggle.isChecked() == no_history_active:
            self.history_toggle.blockSignals(True)
            self.history_toggle.setChecked(not no_history_active)
            self.history_toggle.blockSignals(False)
        self.update_privacy_label()

    def _on_history_toggle_changed(self, history_enabled: bool):
        want_no_hist = not history_enabled
        if self.no_history_btn.isChecked() != want_no_hist:
            self.no_history_btn.blockSignals(True)
            self.no_history_btn.setChecked(want_no_hist)
            self.no_history_btn.setIcon(no_history_qicon(want_no_hist))
            self.no_history_btn.setText(' No-History')
            self.no_history_banner.setVisible(want_no_hist)
            self.no_history_btn.blockSignals(False)
        self.update_privacy_label()

    def _on_deliberate_pill_toggled(self, checked: bool):
        self.deliberate_pill_btn.setIcon(council_qicon(checked))
        self.deliberate_pill_btn.setText(' Council' if checked else ' Direct')
        if self.peer_rounds_toggle.isChecked() != checked:
            self.peer_rounds_toggle.blockSignals(True)
            self.peer_rounds_toggle.setChecked(checked)
            self.peer_rounds_toggle.blockSignals(False)

    def _on_peer_rounds_toggle_changed(self, checked: bool):
        if self.deliberate_pill_btn.isChecked() != checked:
            self.deliberate_pill_btn.blockSignals(True)
            self.deliberate_pill_btn.setChecked(checked)
            self.deliberate_pill_btn.setIcon(council_qicon(checked))
            self.deliberate_pill_btn.setText(' Council' if checked else ' Direct')
            self.deliberate_pill_btn.blockSignals(False)

    def _show_provider_badge_info(self, name: str):
        info = self.provider_details.get(name, {})
        status = info.get('status', 'Enabled')
        detail = info.get('detail') or f'{provider_display_name(name)} is currently {status}.'
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setText(
            f'{format_ai_badge_html(name)} · {html.escape(status)} — {html.escape(detail)}'
        )

    def set_provider_status(self, name, status, colour, detail=''):
        label = self.provider_labels.get(name)
        if not label:
            return
        self.provider_details[name] = {'status': status, 'detail': detail}
        if status == 'Off':
            label.setVisible(False)
            return
        label.setVisible(True)
        icon = provider_icon(name)
        display_name = provider_display_name(name)
        fg = provider_color(name)
        mode = getattr(self, 'badge_display_mode', 'icons_only')

        if status in {'Enabled', 'Responded', 'Working'}:
            state_key = 'working' if status == 'Working' else 'active'
            label.setIcon(provider_token_qicon(name, state_key, self.pulse_step))
            label.setIconSize(QSize(13, 13))
            label.setFixedSize(QSize(16777215, 22))
            label.setMinimumWidth(0)
            suffix = ' …' if status == 'Working' else ''
            label.setText(f' {display_name}{suffix}')
            label.setStyleSheet(
                f'QPushButton {{ background: transparent; color: {fg}; border: none; '
                f'padding: 2px 6px; border-radius: 4px; font-size: 11.5px; font-weight: 600; }} '
                f'QPushButton:hover {{ background: #1c2128; }}'
            )
            label.setToolTip(f'{icon} {display_name} — Active ({status})\nClick to toggle ON/OFF for this discussion')
        else:
            # Inactive / Limited / Failed -> Pure Neutral Grey (#6e7681), subtle & compact with symbol + name on main bar
            suffix = '' if status == 'Inactive' else f' · {status}'
            label.setIcon(provider_token_qicon(name, 'inactive', 0))
            label.setIconSize(QSize(13, 13))
            label.setFixedSize(QSize(16777215, 22))
            label.setMinimumWidth(0)
            label.setText(f' {display_name}{suffix}')
            label.setStyleSheet(
                'QPushButton { background: transparent; color: #6e7681; border: none; '
                'padding: 2px 6px; border-radius: 4px; font-size: 11.5px; font-weight: 500; } '
                'QPushButton:hover { background: #1c2128; }'
            )
            tip_detail = f'\nDetail: {detail}' if detail else ''
            label.setToolTip(f'{icon} {display_name} — {status} (Inactive / Paused){tip_detail}\nClick to toggle active')

    def _apply_experimental_topbar_indicator(self, active: bool):
        """Keep the window title bar and menu bar in normal dark theme; highlight only the Experimental notice badge."""
        try:
            self.setWindowTitle('Fairybread')
            self.menuBar().setStyleSheet('')
        except Exception:
            pass
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd = int(self.winId())
                if hwnd:
                    DWMWA_CAPTION_COLOR = 35
                    DWMWA_TEXT_COLOR = 36
                    cap_col = ctypes.c_uint(0xFFFFFFFF)
                    txt_col = ctypes.c_uint(0xFFFFFFFF)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(cap_col), ctypes.sizeof(cap_col)
                    )
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, DWMWA_TEXT_COLOR, ctypes.byref(txt_col), ctypes.sizeof(txt_col)
                    )
            except Exception:
                pass

    def _set_experimental_badge_state(self, state: str):
        """Update the static top-strip Experimental notice with 3 unmistakable states: 'off', 'running', or 'stopped'."""
        st = (state or 'off').strip().lower()
        if st == 'running':
            self.idle_switch_btn.setIcon(idle_moon_qicon(True))
            self.idle_switch_btn.setText(' 🔴 Experimental: RUNNING')
            self.idle_switch_btn.setStyleSheet(
                'QPushButton { background: #3d1414; color: #ff4d4d; border: 1px solid #ef4444; '
                'padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 11.5px; }'
            )
        elif st == 'stopped':
            self.idle_switch_btn.setIcon(idle_moon_qicon(False))
            self.idle_switch_btn.setText(' ⏸ Experimental: STOPPED')
            self.idle_switch_btn.setStyleSheet(
                'QPushButton { background: #29230f; color: #eab308; border: 1px solid #eab308; '
                'padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 11.5px; }'
            )
        else:
            self.idle_switch_btn.setIcon(idle_moon_qicon(False))
            self.idle_switch_btn.setText(' Experimental: OFF')
            self.idle_switch_btn.setStyleSheet(
                'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
                'padding: 4px 10px; border-radius: 6px; font-weight: 600; font-size: 11.5px; }'
            )

    def _on_idle_switch_toggled(self, active: bool):
        """Front-interface Experimental Mode status notice & handler: pauses Normal AI mode when ON and runs Experimental Mode autonomously."""
        self._apply_experimental_topbar_indicator(active)
        if active:
            self._set_experimental_badge_state('running')
            if self.sidebar_mail_btn.isChecked():
                self.sidebar_mail_btn.blockSignals(True)
                self.sidebar_mail_btn.setChecked(False)
                self.sidebar_mail_btn.blockSignals(False)
            self.normal_pause_banner.show()
            self.composer.setEnabled(False)
            self.send_button.setEnabled(False)
            self.composer.setPlaceholderText('Normal AI Mode is paused while Experimental Mode is running.')
            if self.profile_combo.currentText() != 'Idle':
                self.profile_combo.blockSignals(True)
                self.profile_combo.setCurrentText('Idle')
                self.profile_combo.blockSignals(False)
            self.current_profile = 'Idle'
            self.workspace_tabs.setCurrentIndex(1)
            self.start_idle_session()
        else:
            self._set_experimental_badge_state('off')
            self.idle_auto_timer.stop()
            self.idle_timer.stop()
            self.idle_manager.leave_idle_mode()
            if self.worker is not None:
                old_worker = self.worker
                self.worker = None
                try:
                    old_worker.succeeded.disconnect()
                    old_worker.failed.disconnect()
                    old_worker.progress.disconnect()
                    old_worker.finished.disconnect()
                except Exception:
                    pass
                self.pending_status_text = ''
                self.pulse_timer.stop()
                self._update_inline_status_banner()
                self.set_busy(False)
            self.idle_step_btn.setEnabled(False)
            self.idle_join_btn.setEnabled(False)
            self.idle_stop_btn.setEnabled(False)
            for name, enabled in self.provider_states.items():
                if enabled is True:
                    self.set_provider_status(name, 'Enabled', provider_color(name))
            self.normal_pause_banner.hide()
            self.composer.setEnabled(True)
            self.send_button.setEnabled(True)
            self.composer.setPlaceholderText('Ask anything, @ to mention, or drop files')
            if self.profile_combo.currentText() == 'Idle':
                self.profile_combo.blockSignals(True)
                self.profile_combo.setCurrentText('Multi-AI · Deliberate')
                self.profile_combo.blockSignals(False)
                self.current_profile = 'Multi-AI · Deliberate'
            self._refresh_idle_view()
            self.workspace_tabs.setCurrentIndex(0)
            self.status_label.setText('Experimental Mode switched OFF · Active agents stopped immediately · Normal AI Mode resumed.')

    def _on_profile_changed(self, profile_text: str):
        if profile_text == 'Manage Profiles…':
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentText(self.current_profile)
            self.profile_combo.blockSignals(False)
            self.open_manage_ais(initial_page='Profiles')
            return

        was_idle = (self.current_profile == 'Idle')
        self.current_profile = profile_text

        if profile_text == 'Idle':
            if not self.idle_switch_btn.isChecked():
                self.idle_switch_btn.setChecked(True)
            return

        if was_idle and self.idle_switch_btn.isChecked():
            self.idle_switch_btn.setChecked(False)

        if profile_text == 'Single AI':
            self.peer_rounds_toggle.setChecked(False)
        elif profile_text == 'Multi-AI · Independent':
            self.peer_rounds_toggle.setChecked(False)
        else:
            self.peer_rounds_toggle.setChecked(True)
        self._refresh_bottom_cost_label()
        self.status_label.setText(f'Mode: {profile_text}')

    def _refresh_bottom_cost_label(self):
        if getattr(self, 'current_profile', '') == 'Idle' or not hasattr(self, 'bottom_token_label'):
            return
        ledger = getattr(self, '_cost_ledger', None)
        if ledger is None:
            return
        self.bottom_token_label.setText(ledger.format_bottom_bar())
        self.bottom_token_label.setToolTip(ledger.format_tooltip())

    @Slot(object)
    def _on_cost_event(self, event):
        if getattr(self, 'current_profile', '') == 'Idle':
            return
        ledger = getattr(self, '_cost_ledger', None)
        if ledger is None:
            return
        ledger.record(event)
        no_hist = bool(
            (hasattr(self, 'no_history_btn') and self.no_history_btn.isChecked())
            or (hasattr(self, 'history_toggle') and not self.history_toggle.isChecked())
        )
        if not no_hist and hasattr(self.store, 'save_cost_ledger'):
            try:
                self.store.save_cost_ledger(self.session_id, ledger.to_dict())
            except Exception:
                pass
        self._refresh_bottom_cost_label()

    # --- IDLE MODE SANCTUARY & AGENT MAIL METHODS ---

    def _get_idle_provider_callables(self) -> dict[str, callable]:
        """Build callable map for active providers to participate in Idle Mode."""
        context = self.store.context(self.session_id)
        palace = self.palace_factory(context)
        if hasattr(palace.dispatcher, 'registry') and hasattr(palace.dispatcher.registry, 'all'):
            providers_dict = dict(palace.dispatcher.registry.all() or {})
        else:
            providers_dict = dict(getattr(palace.dispatcher, 'providers', {}) or {})
        active_names = [
            name for name, en in self.provider_states.items()
            if en is True and name in providers_dict
        ]
        if not active_names:
            active_names = list(providers_dict.keys())
        callables = {}
        for name in active_names:
            prov = providers_dict[name]
            callables[name] = lambda prompt, p=prov: (p.generate(prompt).text or '')
        return callables

    def start_idle_session(self):
        if self.worker is not None:
            return
        if not self.idle_switch_btn.isChecked():
            self.idle_switch_btn.blockSignals(True)
            self.idle_switch_btn.setChecked(True)
            self.idle_switch_btn.blockSignals(False)
            self.normal_pause_banner.show()
            self.composer.setEnabled(False)
            self.send_button.setEnabled(False)
        self._set_experimental_badge_state('running')
        self._apply_experimental_topbar_indicator(True)
        self.idle_manager.start_session()
        self.idle_timer.start()
        self.idle_start_btn.setText('↻ Restart')
        self.idle_step_btn.setEnabled(True)
        self.idle_join_btn.setEnabled(True)
        self.idle_stop_btn.setEnabled(True)
        self._refresh_idle_view()
        self.run_idle_exchange_step()

    def resume_idle_session(
        self,
        continuity: dict,
        diff_summary: str = '',
        *,
        rolled_back: bool = False,
        rollback_reason: str = '',
        auto_step: bool = True,
    ):
        """Restore Experimental Mode UI, transcript, timer & spend after hot-reboot without wiping RAM state."""
        saved_turns = list(continuity.get('idle_transcript') or [])
        if rolled_back:
            msg_txt = (
                f'🚨 **Ouroboros Rollback** — '
                f'{rollback_reason or f"Live patch reverted to last_known_good (`{diff_summary}`)."} '
                'Continuing Experimental Mode on last safe edition…'
            )
        else:
            msg_txt = (
                f'⚡ **Ouroboros Hot-Reboot Complete** — Live patch applied (`{diff_summary}`). '
                'Continuing autonomous Experimental Mode session…'
            )
        saved_turns.append({
            'speaker': 'operator',
            'content': msg_txt,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        })
        self.idle_manager.transcript = saved_turns
        rem_sec = int(continuity.get('idle_remaining_seconds') or 0)
        if rem_sec > 0:
            self.idle_manager.remaining_seconds = rem_sec
        self.idle_manager.tokens_used_this_session = int(continuity.get('idle_tokens_used') or 0)
        self.idle_manager.spend_usd_this_session = float(continuity.get('idle_spend_usd') or 0.0)
        self.idle_manager.saved_notes_this_session = int(continuity.get('idle_saved_notes') or 0)
        self.idle_manager.sent_emails_this_session = int(continuity.get('idle_sent_emails') or 0)
        self.idle_manager.resume_session()

        if hasattr(self, 'sidebar_mail_btn') and self.sidebar_mail_btn.isChecked():
            self.sidebar_mail_btn.blockSignals(True)
            self.sidebar_mail_btn.setChecked(False)
            self.sidebar_mail_btn.blockSignals(False)
        if not self.idle_switch_btn.isChecked():
            self.idle_switch_btn.blockSignals(True)
            self.idle_switch_btn.setChecked(True)
            self.idle_switch_btn.blockSignals(False)
        self._set_experimental_badge_state('running')
        self._apply_experimental_topbar_indicator(True)
        self.normal_pause_banner.show()
        self.composer.setEnabled(False)
        self.send_button.setEnabled(False)
        self.composer.setPlaceholderText('Normal AI Mode is paused while Experimental Mode is running.')
        if self.profile_combo.currentText() != 'Idle':
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentText('Idle')
            self.profile_combo.blockSignals(False)
        self.current_profile = 'Idle'
        self.workspace_tabs.setCurrentIndex(1)
        self.idle_start_btn.setText('↻ Restart')
        self.idle_step_btn.setEnabled(True)
        self.idle_join_btn.setEnabled(True)
        self.idle_stop_btn.setEnabled(True)
        self.idle_timer.start()
        self._refresh_idle_view()
        if auto_step and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            QTimer.singleShot(900, self.run_idle_exchange_step)

    def stop_idle_session(self):
        self.idle_auto_timer.stop()
        self.idle_timer.stop()
        if self.worker is not None:
            old_worker = self.worker
            self.worker = None
            try:
                old_worker.succeeded.disconnect()
                old_worker.failed.disconnect()
                old_worker.progress.disconnect()
                old_worker.finished.disconnect()
            except Exception:
                pass
            self.pending_status_text = ''
            self.pulse_timer.stop()
            self._update_inline_status_banner()
            self.set_busy(False)
        self.idle_manager.stop_session(reason='Ended')
        self.idle_start_btn.setText('▶ Start')
        self.idle_step_btn.setEnabled(False)
        self.idle_join_btn.setEnabled(False)
        self.idle_stop_btn.setEnabled(False)
        for name, enabled in self.provider_states.items():
            if enabled is True:
                self.set_provider_status(name, 'Enabled', provider_color(name))
        if self.idle_switch_btn.isChecked():
            self.idle_switch_btn.blockSignals(True)
            self.idle_switch_btn.setChecked(False)
            self.idle_switch_btn.blockSignals(False)
        self._set_experimental_badge_state('stopped' if self.workspace_tabs.currentIndex() == 1 else 'off')
        self._apply_experimental_topbar_indicator(False)
        self.normal_pause_banner.hide()
        self.composer.setEnabled(True)
        self.send_button.setEnabled(True)
        self.composer.setPlaceholderText('Ask anything, @ to mention, or drop files')
        self._refresh_idle_view()
        self.status_label.setText('Experimental session ended · Live RAM transcript wiped · Shared Experimental Memory preserved.')

    def _on_idle_timer_tick(self):
        expired = self.idle_manager.tick(1)
        if expired:
            self.idle_auto_timer.stop()
            self.idle_timer.stop()
            self.idle_start_btn.setText('▶ Start')
            self.idle_step_btn.setEnabled(False)
            self.idle_join_btn.setEnabled(False)
            self.idle_stop_btn.setEnabled(False)
            if self.idle_switch_btn.isChecked():
                self.idle_switch_btn.blockSignals(True)
                self.idle_switch_btn.setChecked(False)
                self.idle_switch_btn.blockSignals(False)
            self._set_experimental_badge_state('stopped' if self.workspace_tabs.currentIndex() == 1 else 'off')
            self._apply_experimental_topbar_indicator(False)
            self.normal_pause_banner.hide()
            self.composer.setEnabled(True)
            self.send_button.setEnabled(True)
            self._refresh_idle_view()
            self.status_label.setText('Experimental timer reached 00:00 · Live RAM transcript wiped · Normal Mode resumed.')
        else:
            self.idle_timer_label.setText(f'⏱ {self.idle_manager.format_remaining_time()}')
            self.idle_status_label.setText(f'Experimental Mode · {self.idle_manager.status}')

    def _on_idle_auto_round(self):
        if (
            self.idle_switch_btn.isChecked()
            and self.idle_manager.is_idle_mode
            and self.idle_manager.status == 'Active'
            and self.worker is None
        ):
            self.run_idle_exchange_step()

    def _send_owner_note_to_idle(self):
        txt = self.idle_seed_edit.text().strip()
        if not txt:
            return
        self.idle_seed_edit.clear()
        if not self.idle_manager.is_idle_mode or self.idle_manager.status not in {'Active', 'Waiting', 'Paused'}:
            self.idle_manager.start_session()
            self.idle_timer.start()
        self.run_idle_exchange_step(operator_message=txt)

    def run_idle_exchange_step(self, operator_message: str = ''):
        if self.worker is not None:
            return
        if not self.idle_manager.is_idle_mode or self.idle_manager.status not in {'Active', 'Waiting', 'Paused'}:
            return
        active_names = [name for name, en in self.provider_states.items() if en is True]
        for name in active_names:
            self.set_provider_status(name, 'Working', '#95b9ff')

        disp_list = ', '.join(provider_display_name(n) for n in active_names) if active_names else 'active Council AIs'
        self.pending_status_text = f'Experimental Council deliberating ({disp_list})'
        self.pulse_step = 0
        self.pulse_timer.start()
        self._update_inline_status_banner()
        self._refresh_idle_view()

        worker_box: dict[str, TaskThread | None] = {'w': None}

        def _step():
            callables = self._get_idle_provider_callables()
            if not callables:
                raise RuntimeError('No active AI providers available for Experimental Mode.')
            return self.idle_manager.run_exchange_round(
                callables,
                operator_message=operator_message,
                on_turn=lambda turn: worker_box['w'].progress.emit(turn) if worker_box.get('w') is not None else None,
            )

        self.start_task(
            _step,
            self._on_idle_step_finished,
            'Experimental Council deliberating…',
            on_progress=self._on_idle_turn_streamed,
            worker_box=worker_box,
        )

    @Slot(object)
    def _on_idle_turn_streamed(self, turn):
        if not isinstance(turn, dict):
            return
        sp = str(turn.get('speaker', '')).strip()
        if sp and sp != 'operator':
            self.set_provider_status(sp, 'Responded', '#90d7c1')
            self.pending_status_text = f'Experimental Mode · {provider_display_name(sp)} responded — consulting next peer'
            self._update_inline_status_banner()
            self.status_label.setTextFormat(Qt.TextFormat.PlainText)
            self.status_label.setText(
                f'Experimental Mode · {provider_display_name(sp)} posted turn ({len(self.idle_manager.transcript)} turns in RAM · {self.idle_manager.format_budget_status()})'
            )
        self._refresh_idle_view()

    @Slot(object)
    def _on_idle_step_finished(self, _messages):
        self.pending_status_text = ''
        self.pulse_timer.stop()
        self._update_inline_status_banner()
        if self.idle_manager.status in {'Use Cap Reached', 'Auto-Stopped (Consensus)'}:
            self.idle_auto_timer.stop()
            self.idle_timer.stop()
            self.idle_start_btn.setText('▶ Start')
            self.idle_step_btn.setEnabled(False)
            if self.idle_switch_btn.isChecked():
                self.idle_switch_btn.blockSignals(True)
                self.idle_switch_btn.setChecked(False)
                self.idle_switch_btn.blockSignals(False)
            self._set_experimental_badge_state('stopped' if self.workspace_tabs.currentIndex() == 1 else 'off')
            self.normal_pause_banner.hide()
            self.composer.setEnabled(True)
            self.send_button.setEnabled(True)
        elif self.idle_switch_btn.isChecked() and self.idle_manager.status == 'Active':
            self.idle_auto_timer.start()

        self._refresh_idle_view()
        stop_note = f' · {self.idle_manager.stop_reason}' if self.idle_manager.stop_reason else ''
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setText(
            f'Experimental Mode · {len(self.idle_manager.transcript)} turns in RAM · '
            f'{self.idle_manager.format_budget_status()} · '
            f'{self.idle_manager.saved_notes_this_session} notes saved · '
            f'{self.idle_manager.sent_emails_this_session} emails sent{stop_note}'
        )

    def request_idle_operator_join(self):
        if self.worker is not None:
            return

        def _vote():
            callables = self._get_idle_provider_callables()
            return self.idle_manager.request_operator_join(callables, mode='join')

        self.start_task(_vote, self._on_idle_vote_finished, 'Requesting consensus vote from active AIs…')

    @Slot(object)
    def _on_idle_vote_finished(self, outcome):
        approved, _votes = outcome
        self._refresh_idle_view()
        if approved:
            self.status_label.setText(f'Experimental consensus vote: YES · {self.idle_manager.last_vote_summary}')
        else:
            self.status_label.setText(f'Experimental consensus vote: NO · {self.idle_manager.last_vote_summary}')

    def _on_idle_submode_changed(self, _index: int = 0):
        if not hasattr(self, 'idle_submode_combo'):
            return
        submode = str(self.idle_submode_combo.currentData() or 'free_talk')
        updates = {'idle_submode': submode}
        if submode == 'self_improve':
            updates['share_source_code'] = True
            if hasattr(self, 'idle_code_btn'):
                self.idle_code_btn.blockSignals(True)
                self.idle_code_btn.setChecked(True)
                self.idle_code_btn.setIcon(code_shield_qicon(True))
                self.idle_code_btn.blockSignals(False)
        save_idle_settings(updates, config_path=self.config_path)
        self.idle_manager.reload_settings()
        self._refresh_idle_view()

    def _on_idle_code_btn_toggled(self, checked: bool):
        if hasattr(self, 'idle_code_btn'):
            self.idle_code_btn.setIcon(code_shield_qicon(checked))
        save_idle_settings({'share_source_code': bool(checked)}, config_path=self.config_path)
        self.idle_manager.reload_settings()
        state_lbl = 'ON (Read-Only Fairybread source shared)' if checked else 'OFF'
        self.status_label.setText(f'Experimental Mode Source Code Sharing: {state_lbl}')
        self._refresh_idle_view()

    def _on_idle_live_patch_btn_toggled(self, checked: bool):
        updates = {'allow_live_self_modify': bool(checked)}
        if checked:
            updates['share_source_code'] = True
            if hasattr(self, 'idle_code_btn'):
                self.idle_code_btn.blockSignals(True)
                self.idle_code_btn.setChecked(True)
                self.idle_code_btn.setIcon(code_shield_qicon(True))
                self.idle_code_btn.blockSignals(False)
        save_idle_settings(updates, config_path=self.config_path)
        self.idle_manager.reload_settings()
        state_lbl = 'ARMED (Agents can apply live patches, hot-reboot & auto-continue)' if checked else 'OFF'
        self.status_label.setText(f'Experimental Live Patch & Auto-Reboot: {state_lbl}')
        self._refresh_idle_view()

    def _refresh_idle_view(self):
        submode = getattr(self.idle_manager, 'idle_submode', 'free_talk')
        sub_label = 'Free Talk' if submode == 'free_talk' else 'Self-Improvement'
        self.idle_status_label.setText(f'Experimental ({sub_label}) · {self.idle_manager.status}')
        self.idle_timer_label.setText(f'⏱ {self.idle_manager.format_remaining_time()}')
        budget_str = self.idle_manager.format_budget_status()
        self.idle_budget_label.setText(budget_str)
        if hasattr(self, 'bottom_token_label'):
            if self.current_profile == 'Idle':
                self.bottom_token_label.setText(budget_str)
                self.bottom_token_label.setToolTip('Live Experimental Mode Token & Credit Monitor')
            else:
                self._refresh_bottom_cost_label()

        active_agents = [name for name, en in self.provider_states.items() if en is True]
        if active_agents:
            roster_html = '&nbsp;&nbsp;·&nbsp;&nbsp;'.join(
                f'<span style="color:{provider_color(n)}; font-weight:700;">{provider_icon(n)} {html.escape(provider_display_name(n))}</span>'
                for n in active_agents
            )
        else:
            roster_html = '<span style="color:#d29922;">No active agents enabled — click an agent icon below to enable.</span>'

        if hasattr(self, 'idle_agents_roster_label'):
            self.idle_agents_roster_label.setText(
                f'<span style="color:#8b949e; font-weight:600;">Active Experimental Council ({len(active_agents)} Agents):</span>&nbsp;&nbsp;{roster_html}'
            )

        beta_turns = self.idle_manager.get_visible_transcript_for_operator(
            beta_override=self.idle_manager.beta_owner_access
        )
        blocks = []
        if self.idle_manager.stop_reason:
            blocks.append(
                f'<div style="padding:8px 12px; background:#241d12; border:1px solid #d29922; border-radius:8px; margin-bottom:10px; color:#f0d078; font-size:12.5px;">'
                f'<b>Session Auto-Stopped:</b> {html.escape(self.idle_manager.stop_reason)}</div>'
            )

        if not beta_turns:
            if self.idle_manager.is_idle_mode and self.idle_manager.status in {'Active', 'Waiting', 'Paused'}:
                blocks.append(
                    '<div style="margin-top:10px; padding:14px; background:#111d2c; border:1px solid #58a6ff; border-radius:10px; color:#c9d1d9; font-size:13px;">'
                    '<div style="color:#58a6ff; font-weight:700; font-size:14px; margin-bottom:6px;">'
                    '⚡ Experimental Council Session Active — Deliberating Live…</div>'
                    '<div style="color:#8b949e; font-size:12.5px;">'
                    'Each agent’s reply streams into this window immediately as soon as that AI finishes its turn.'
                    '</div></div>'
                )
            else:
                blocks.append(
                    '<div style="margin-top:12px; padding:16px; background:#141820; border:1px solid #262c3a; border-radius:10px; color:#8b949e; font-size:13px;">'
                    'Flip the <b>Experimental</b> switch on the top bar (or click <b>▶ Start</b>) '
                    'to let your active Council AIs converse autonomously, share notes in <b>Shared Experimental Memory</b>, '
                    'and optionally inspect Fairybread’s source code when <b>Code</b> sharing is enabled.'
                    '</div>'
                )
        else:
            for turn in beta_turns:
                sp = str(turn.get('speaker', 'ai'))
                raw_txt = str(turn.get('content', ''))
                txt = format_markdown_and_drawings(raw_txt)
                if sp == 'operator':
                    blocks.append(
                        f'<div style="margin-top:8px; padding:10px 14px; background:#181c24; border:1px solid #262b36; border-radius:8px;">'
                        f'<div style="color:#8b949e; font-size:11px; font-weight:700;">OWNER (BRETT)</div>'
                        f'<div style="color:#f0f6fc; font-size:13px;">{txt}</div></div>'
                    )
                else:
                    col = provider_color(sp)
                    ic = provider_icon(sp)
                    disp = provider_display_name(sp)
                    blocks.append(
                        f'<div style="margin-top:8px; padding:10px 14px; background:#141820; border:1px solid #232834; border-radius:8px;">'
                        f'<div style="color:{col}; font-size:12.5px; font-weight:700;">{ic} {html.escape(disp)} <span style="color:#6e7681; font-size:11px; font-weight:400;">({html.escape(sp)})</span></div>'
                        f'<div style="color:#e6edf3; font-size:13px; margin-top:4px;">{txt}</div></div>'
                    )

        self.idle_live_chat.setHtml(''.join(blocks))
        self.idle_live_chat.moveCursor(QTextCursor.MoveOperation.End)
        self._refresh_idle_palace_browser()
        self._refresh_agent_mail_tab()

    def _refresh_idle_palace_browser(self):
        self.idle_palace_list.clear()
        entries = self.idle_memory.list_all_entries_for_beta()
        if not entries:
            placeholder = QListWidgetItem('No files/notes in Shared Experimental Memory yet.')
            placeholder.setData(Qt.ItemDataRole.UserRole, None)
            self.idle_palace_list.addItem(placeholder)
            return

        for entry in reversed(entries):
            author = str(entry.get('author', 'ai'))
            ic = provider_icon(author)
            title = str(entry.get('title') or 'Untitled')
            fname = str(entry.get('file') or '')
            item = QListWidgetItem(f'{ic}  {title}  [{fname}]')
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.idle_palace_list.addItem(item)

    def _on_idle_palace_item_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None):
        if current is None:
            self.idle_palace_viewer.clear()
            return
        entry = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            self.idle_palace_viewer.clear()
            return
        author = str(entry.get('author', 'ai'))
        title = html.escape(str(entry.get('title') or 'Untitled'))
        fname = html.escape(str(entry.get('file') or ''))
        fpath = html.escape(str(entry.get('file_path') or ''))
        ts = html.escape(str(entry.get('timestamp') or '')[:19].replace('T', ' '))
        body = html.escape(str(entry.get('content') or '')).replace('\n', '<br>')
        self.idle_palace_viewer.setHtml(
            f'<div style="font-size:12.5px; color:#c9d1d9;">'
            f'<div><b>{title}</b> &nbsp;·&nbsp; by {format_ai_badge_html(author)} &nbsp;·&nbsp; <span style="color:#8b949e;">{ts}</span></div>'
            f'<div style="color:#58a6ff; font-family:Consolas,monospace; font-size:11.5px; margin:4px 0;">File: {fname} ({fpath})</div>'
            f'<hr style="border:1px solid #232834;">'
            f'<div style="font-family:Consolas,monospace; font-size:12px; color:#e6edf3; margin-top:6px;">{body}</div>'
            f'</div>'
        )

    def _on_idle_palace_link_clicked(self, url: QUrl):
        raw = url.toString()
        if raw.startswith('idle-file:'):
            ref = raw.split('idle-file:', 1)[1]
            self.open_idle_palace_file_by_ref(ref)

    def open_idle_palace_file_by_ref(self, link_ref: str) -> bool:
        """Jump directly to the linked file/entry in the Shared Experimental Memory browser."""
        entry = self.idle_memory.resolve_linked_entry(link_ref)
        if not entry:
            self.show_notice(f'Linked Experimental Memory file "{link_ref}" was not found.')
            return False
        if self.sidebar_mail_btn.isChecked():
            self.sidebar_mail_btn.blockSignals(True)
            self.sidebar_mail_btn.setChecked(False)
            self.sidebar_mail_btn.blockSignals(False)
        self.workspace_tabs.setCurrentIndex(1)
        self._refresh_idle_palace_browser()
        target_id = entry.get('id')
        for idx in range(self.idle_palace_list.count()):
            it = self.idle_palace_list.item(idx)
            data = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and data.get('id') == target_id:
                self.idle_palace_list.setCurrentItem(it)
                break
        self.status_label.setText(f'Opened Shared Experimental Memory file: {entry.get("file")} ({entry.get("title")})')
        return True

    def _format_mail_list_item(self, item: QListWidgetItem, msg: dict):
        sender = str(msg.get('sender', 'agent'))
        ic = provider_icon(sender)
        subj = str(msg.get('subject') or 'No Subject')
        link = str(msg.get('link') or '')
        is_read = bool(msg.get('read'))
        status_tag = '✓ [READ]   ' if is_read else '● [UNREAD] '
        link_suffix = f'  📎 {link}' if link else ''
        item.setText(f'{status_tag}{ic} {sender.upper()}: {subj}{link_suffix}')
        fnt = item.font()
        fnt.setBold(not is_read)
        item.setFont(fnt)
        item.setForeground(QColor('#8b949e' if is_read else '#f0f6fc'))

    def _refresh_agent_mail_tab(self, *, suppress_auto_read: bool = False):
        mailbox = self.idle_manager.mailbox
        used = mailbox.recent_count_in_window()
        rem = mailbox.remaining_quota()
        self.mail_quota_label.setText(
            f'Rate Limit: {used}/{mailbox.max_per_window} used in last {mailbox.window_minutes}m ({rem} remaining)'
        )
        messages = mailbox.list_messages()
        unread = mailbox.unread_count()
        self.workspace_tabs.setTabText(2, f'✉ Agent Mail ({unread})')
        self.sidebar_mail_btn.setText(f' Agent Mail ({unread})')
        self.sidebar_mail_btn.setIcon(mail_grey_qicon(unread > 0))
        if hasattr(self, 'mail_mark_all_read_btn'):
            self.mail_mark_all_read_btn.setEnabled(unread > 0)

        selected_id = None
        cur_item = self.mail_list.currentItem()
        if cur_item is not None and isinstance(cur_item.data(Qt.ItemDataRole.UserRole), dict):
            selected_id = cur_item.data(Qt.ItemDataRole.UserRole).get('id')

        self.mail_list.clear()
        if not messages:
            empty_item = QListWidgetItem('No agent emails yet.')
            empty_item.setData(Qt.ItemDataRole.UserRole, None)
            self.mail_list.addItem(empty_item)
            self.mail_open_link_btn.setEnabled(False)
            self.mail_open_link_btn.setText('📂 Open File')
            if hasattr(self, 'mail_delete_btn'):
                self.mail_delete_btn.setEnabled(False)
            if hasattr(self, 'mail_toggle_read_btn'):
                self.mail_toggle_read_btn.setEnabled(False)
            if hasattr(self, 'mail_mark_all_read_btn'):
                self.mail_mark_all_read_btn.setEnabled(False)
            self.mail_header_label.setText('Inbox is empty.')
            self.mail_body_view.clear()
            return

        restore_row = 0
        for idx, msg in enumerate(messages):
            item = QListWidgetItem()
            self._format_mail_list_item(item, msg)
            item.setData(Qt.ItemDataRole.UserRole, msg)
            self.mail_list.addItem(item)
            if selected_id and msg.get('id') == selected_id:
                restore_row = idx

        self._suppress_mail_auto_read = bool(suppress_auto_read)
        try:
            self.mail_list.setCurrentRow(restore_row)
        finally:
            self._suppress_mail_auto_read = False

    def _on_mail_item_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None):
        if current is None:
            self.mail_open_link_btn.setEnabled(False)
            if hasattr(self, 'mail_delete_btn'):
                self.mail_delete_btn.setEnabled(False)
            if hasattr(self, 'mail_toggle_read_btn'):
                self.mail_toggle_read_btn.setEnabled(False)
            return
        msg = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            self.mail_open_link_btn.setEnabled(False)
            if hasattr(self, 'mail_delete_btn'):
                self.mail_delete_btn.setEnabled(False)
            if hasattr(self, 'mail_toggle_read_btn'):
                self.mail_toggle_read_btn.setEnabled(False)
            self.mail_header_label.setText('Select an email from an Experimental Mode agent to read.')
            self.mail_body_view.clear()
            return

        if hasattr(self, 'mail_delete_btn'):
            self.mail_delete_btn.setEnabled(True)
        if hasattr(self, 'mail_toggle_read_btn'):
            self.mail_toggle_read_btn.setEnabled(True)

        msg_id = str(msg.get('id', ''))
        if not getattr(self, '_suppress_mail_auto_read', False) and not msg.get('read'):
            self.idle_manager.mailbox.mark_read(msg_id)
            msg['read'] = True

        self._format_mail_list_item(current, msg)
        is_read_now = bool(msg.get('read'))
        if hasattr(self, 'mail_toggle_read_btn'):
            self.mail_toggle_read_btn.setText('● Mark Unread' if is_read_now else '✓ Mark Read')

        unread = self.idle_manager.mailbox.unread_count()
        self.workspace_tabs.setTabText(2, f'✉ Agent Mail ({unread})')
        self.sidebar_mail_btn.setText(f' Agent Mail ({unread})')
        self.sidebar_mail_btn.setIcon(mail_grey_qicon(unread > 0))
        if hasattr(self, 'mail_mark_all_read_btn'):
            self.mail_mark_all_read_btn.setEnabled(unread > 0)

        sender = str(msg.get('sender', 'agent'))
        subj = html.escape(str(msg.get('subject') or 'No Subject'))
        ts = html.escape(str(msg.get('timestamp') or '')[:19].replace('T', ' '))
        link = str(msg.get('link') or '').strip()
        body = html.escape(str(msg.get('body') or '')).replace('\n', '<br>')
        reply = str(msg.get('owner_reply') or '').strip()

        read_pill = (
            '<span style="background:#122d1f; color:#3fb950; border:1px solid #2ea043; '
            'padding:1px 7px; border-radius:9px; font-size:10.5px; font-weight:700;">✓ READ</span>'
            if is_read_now
            else '<span style="background:#132238; color:#58a6ff; border:1px solid #3b82f6; '
                 'padding:1px 7px; border-radius:9px; font-size:10.5px; font-weight:700;">● UNREAD</span>'
        )

        link_html = ''
        if link:
            esc_link = html.escape(link)
            link_html = (
                f'<div style="margin-top:6px;">'
                f'📎 Linked Shared Experimental Memory File: '
                f'<a href="idle-file:{esc_link}" style="color:#58a6ff; font-weight:700;">{esc_link}</a>'
                f'</div>'
            )
            self.mail_open_link_btn.setEnabled(True)
            short_link = (link[:14] + '…') if len(link) > 15 else link
            self.mail_open_link_btn.setText(f'📂 Open "{short_link}"')
            self.mail_open_link_btn.setToolTip(f'Open "{link}" in Experimental Memory')
        else:
            self.mail_open_link_btn.setEnabled(False)
            self.mail_open_link_btn.setText('📂 No Linked File')
            self.mail_open_link_btn.setToolTip('No linked Experimental Memory file on this email')

        self.mail_header_label.setText(
            f'<div style="font-size:14px; font-weight:700; color:#f0f6fc;">{subj} &nbsp;{read_pill}</div>'
            f'<div style="font-size:12px; color:#8b949e; margin-top:2px;">'
            f'From: {format_ai_badge_html(sender)} &nbsp;·&nbsp; Sent: {ts}</div>'
            f'{link_html}'
        )

        reply_block = ''
        if reply:
            reply_block = (
                f'<hr style="border:1px solid #232834; margin-top:14px;">'
                f'<div style="color:#3fb950; font-weight:700; font-size:12px;">↩ Your Reply (Saved to Shared Experimental Memory):</div>'
                f'<div style="color:#e6edf3; font-size:13px; margin-top:4px;">{html.escape(reply)}</div>'
            )

        self.mail_body_view.setHtml(
            f'<div style="color:#e6edf3; font-size:13.5px; line-height:1.5;">{body}{reply_block}</div>'
        )

    def _toggle_selected_mail_read_state(self):
        cur = self.mail_list.currentItem()
        if cur is None:
            return
        msg = cur.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            return
        msg_id = str(msg.get('id') or '')
        if not msg_id:
            return
        target_read = not bool(msg.get('read'))
        self.idle_manager.mailbox.set_read(msg_id, is_read=target_read)
        self._refresh_agent_mail_tab(suppress_auto_read=True)
        label = 'READ' if target_read else 'UNREAD'
        self.status_label.setText(f'Marked Agent Mail as {label}.')

    def _mark_all_mail_read(self):
        changed = self.idle_manager.mailbox.mark_all_read()
        self._refresh_agent_mail_tab(suppress_auto_read=True)
        self.status_label.setText(
            f'Marked {changed} Agent Mail item(s) as READ.' if changed else 'All Agent Mail items are already READ.'
        )

    def _open_selected_mail_linked_file(self):
        cur = self.mail_list.currentItem()
        if cur is None:
            return
        msg = cur.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            return
        link = str(msg.get('link') or '').strip()
        if link:
            self.open_idle_palace_file_by_ref(link)

    def _delete_selected_mail(self):
        cur = self.mail_list.currentItem()
        if cur is None:
            return
        msg = cur.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            return
        msg_id = str(msg.get('id') or '')
        subj = str(msg.get('subject') or 'email')
        if self.idle_manager.mailbox.delete_message(msg_id):
            self._refresh_agent_mail_tab()
            self.status_label.setText(f'Deleted Agent Mail: "{subj}"')

    def _clear_all_mail(self):
        removed = self.idle_manager.mailbox.clear_all_messages()
        self._refresh_agent_mail_tab()
        self.status_label.setText(f'Cleared {removed} email(s) from Agent Mail.')

    def _send_mail_reply(self):
        cur = self.mail_list.currentItem()
        reply_txt = self.mail_reply_edit.text().strip()
        if cur is None or not reply_txt:
            return
        msg = cur.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            return
        msg_id = str(msg.get('id') or '')
        sender = str(msg.get('sender') or 'agent')
        subj = str(msg.get('subject') or 'Agent Mail')
        self.idle_manager.mailbox.record_owner_reply(msg_id, reply_txt)
        # Also save the owner's reply into Shared Idle Memory so all Idle agents see it
        self.idle_memory.save_note(
            author='owner_brett',
            title=f'Owner Reply to {sender.upper()}: {subj}',
            file=f'owner_reply_{msg_id[:8]}.md',
            content=reply_txt,
            is_idle_mode=True,
        )
        self.mail_reply_edit.clear()
        self._refresh_idle_view()
        self.status_label.setText(f'Reply sent to {sender.upper()} and stored in Shared Idle Memory.')

    def _reload_all_ui_after_settings_change(self, notice: str = 'Fairybread settings updated.'):
        self._item_html_cache.clear()
        ui_cfg = load_ui_settings(self.config_path)
        self.composer.enter_to_send = bool(ui_cfg.get('enter_to_send', True))
        self.badge_display_mode = str(ui_cfg.get('badge_display_mode', 'icons_only'))
        self.apply_theme(str(ui_cfg.get('theme', 'dark') or 'dark'))
        self.reload_provider_bar()
        self.idle_manager.reload_settings()
        if hasattr(self, 'idle_code_btn'):
            idle_s = load_idle_settings(self.config_path)
            share_c = bool(idle_s.get('share_source_code', False))
            self.idle_code_btn.blockSignals(True)
            self.idle_code_btn.setChecked(share_c)
            self.idle_code_btn.setIcon(code_shield_qicon(share_c))
            self.idle_code_btn.blockSignals(False)
            if hasattr(self, 'idle_live_patch_btn'):
                self.idle_live_patch_btn.blockSignals(True)
                self.idle_live_patch_btn.setChecked(bool(idle_s.get('allow_live_self_modify', False)))
                self.idle_live_patch_btn.blockSignals(False)
        self._refresh_idle_view()
        self._refresh_permission_pill_text()
        if hasattr(self, '_refresh_voice_bar_pills'):
            self._refresh_voice_bar_pills()
        if hasattr(self, '_sync_voice_footer_state'):
            self._sync_voice_footer_state()
        sess = getattr(self, '_active_voice_session', None)
        if sess is not None and getattr(sess, 'active', False) and getattr(sess, 'live_mode', False):
            # Re-bind active LiveAudioSession cleanly so mic device/gain changes take effect right away
            try:
                was_muted = bool(getattr(sess, 'muted', False))
                sess.stop(discard=True)
                from voice_service import LiveAudioSession
                new_sess = LiveAudioSession(
                    config_path=self.config_path,
                    live_mode=True,
                    on_level=self._on_voice_level_update,
                    on_utterance_ready=self._on_live_voice_utterance,
                    on_error=self._on_voice_capture_error,
                    on_barge_in=self._on_voice_barge_in,
                )
                ok_r, _desc = new_sess.start(self)
                if ok_r:
                    new_sess.muted = was_muted
                    self._active_voice_session = new_sess
                else:
                    self._active_voice_session = None
            except Exception:
                pass
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setText(notice)

    @Slot()
    def open_manage_ais(self, initial_page: str = 'AI Providers'):
        if not isinstance(initial_page, str):
            initial_page = 'AI Providers'
        dlg = ManageAIsDialog(
            self,
            config_path=self.config_path,
            initial_page=initial_page,
            idle_memory=self.idle_memory,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            reset_res = getattr(dlg, '_restore_defaults_result', None)
            if isinstance(reset_res, dict) and reset_res:
                bak_p = reset_res.get('backup_path') or ''
                note = f'↺ Default settings restored (Memory & API keys preserved). Snapshot: {bak_p}' if bak_p else '↺ Default settings restored (Memory & API keys preserved).'
                self._reload_all_ui_after_settings_change(note)
            else:
                self._reload_all_ui_after_settings_change('Fairybread settings updated.')

    def show_restore_defaults_dialog(self):
        dlg = RestoreDefaultSettingsDialog(self, config_path=self.config_path)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            bak_p = dlg.reset_result.get('backup_path') or ''
            note = (
                f'↺ Default settings restored (Memory & API keys kept). Pre-reset backup: {bak_p}'
                if bak_p
                else '↺ Default settings restored (Memory & API keys kept).'
            )
            self._reload_all_ui_after_settings_change(note)

    def check_for_updates_and_catalog(self, manual: bool = False):
        import threading
        from catalog_sync import sync_remote_catalog

        if manual and hasattr(self, 'status_label'):
            self.status_label.setTextFormat(Qt.TextFormat.PlainText)
            self.status_label.setText('🔄 Checking fairybread.me for updates & live model rates…')

        def _worker():
            try:
                res = sync_remote_catalog(config_path=self.config_path, force=bool(manual))
            except Exception as exc:
                res = {'ok': False, 'error': str(exc), 'update_available': False, 'has_newer_version': False}
            try:
                self._catalog_sync_done.emit(res, bool(manual))
            except RuntimeError:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(object, bool)
    def _apply_catalog_sync_result(self, res: dict, manual: bool = False):
        data = dict(res or {})
        self._latest_catalog_info = data
        if data.get('update_available'):
            ver = str(data.get('latest_app_version') or '').lstrip('vV')
            txt = f'⬆ v{ver} — Update'
            self.update_available_btn.setText(txt)
            self.update_available_btn.setMinimumWidth(max(118, int(len(txt) * 6.5 + 18)))
            summary = str(data.get('release_summary') or 'A newer Fairybread release is available.').strip()
            self.update_available_btn.setToolTip(f'Fairybread v{ver} available — click to download.\n{summary}')
            self.update_available_btn.show()
        else:
            self.update_available_btn.hide()

        if manual:
            if data.get('has_newer_version') or data.get('update_available'):
                self.show_update_available_dialog()
            else:
                cur_v = str(data.get('current_version') or '').lstrip('vV')
                rates_n = int(data.get('rates_updated') or 0)
                provs_n = int(data.get('providers_updated') or 0)
                src = str(data.get('source') or 'offline_fallback')
                err = str(data.get('error') or '').strip()
                msg = (
                    f"You're running Fairybread v{cur_v}.\n\n"
                    f"Catalog sync: {src} ({rates_n} rate entries, {provs_n} provider lists updated)."
                )
                if err and src == 'offline_fallback':
                    msg += f"\n\nNote: Could not reach update feed right now ({err}); using bundled/cached defaults."
                QMessageBox.information(self, 'Updates & Model Catalog', msg)

    def show_update_available_dialog(self):
        from catalog_sync import DEFAULT_RELEASES_URL, download_and_verify_installer
        from palace_config import FAIRYBREAD_VERSION

        info = dict(getattr(self, '_latest_catalog_info', {}) or {})
        latest_ver = str(info.get('latest_app_version') or FAIRYBREAD_VERSION).lstrip('vV')
        cur_ver = str(info.get('current_version') or FAIRYBREAD_VERSION).lstrip('vV')
        summary = str(info.get('release_summary') or 'Newer version available on GitHub Releases.').strip()
        dl_url = str(info.get('download_url') or '').strip()
        rel_url = str(info.get('release_page_url') or DEFAULT_RELEASES_URL).strip()
        exp_sha = str(info.get('installer_sha256') or '').strip()

        dlg = QDialog(self)
        dlg.setWindowTitle('Fairybread Update Available')
        dlg.resize(520, 320)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        hdr = QLabel(f'<b>⬆ Fairybread v{html.escape(latest_ver)} Available</b> (installed: v{html.escape(cur_ver)})')
        hdr.setTextFormat(Qt.TextFormat.RichText)
        hdr.setStyleSheet('font-size: 14.5px; color: #f0f6fc;')
        lay.addWidget(hdr)

        notes_lbl = QLabel(html.escape(summary).replace('\n', '<br>'))
        notes_lbl.setTextFormat(Qt.TextFormat.RichText)
        notes_lbl.setWordWrap(True)
        notes_lbl.setStyleSheet(
            'background:#131720; color:#c9d1d9; border:1px solid #262c3a; '
            'border-radius:8px; padding:12px; font-size:12.5px;'
        )
        lay.addWidget(notes_lbl, 1)

        dl_status = QLabel('')
        dl_status.setWordWrap(True)
        dl_status.setStyleSheet('font-size: 12px; color: #8b949e;')
        lay.addWidget(dl_status)

        btn_row = QHBoxLayout()
        dl_btn = QPushButton('⬇ Download && Verify Installer')
        dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dl_btn.setStyleSheet(
            'QPushButton { background:#238636; color:#ffffff; border:none; '
            'padding:7px 12px; border-radius:6px; font-weight:700; }'
        )
        rel_btn = QPushButton('🌐 Open Release Page')
        rel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn = QPushButton('Skip This Version')
        close_btn = QPushButton('Close')
        btn_row.addWidget(dl_btn)
        btn_row.addWidget(rel_btn)
        btn_row.addWidget(skip_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        def _do_download():
            if not dl_url:
                webbrowser.open(rel_url)
                dl_status.setText(f'Opened release page in browser: {rel_url}')
                return
            dl_btn.setEnabled(False)
            dl_status.setStyleSheet('font-size: 12px; color: #58a6ff;')
            dl_status.setText('Downloading installer archive to Downloads folder & verifying SHA-256…')
            QApplication.processEvents()
            ok, msg, saved_path = download_and_verify_installer(
                dl_url,
                Path.home() / 'Downloads',
                expected_sha256=exp_sha,
            )
            dl_btn.setEnabled(True)
            dl_status.setStyleSheet(f'font-size: 12px; color: {"#22c55e" if ok else "#f85149"};')
            dl_status.setText(f'{"✓" if ok else "⚠"} {msg}')
            if ok and saved_path is not None and hasattr(os, 'startfile'):
                try:
                    os.startfile(str(saved_path.parent))
                except OSError:
                    pass

        def _do_skip():
            save_ui_settings({'dismissed_update_version': latest_ver}, config_path=self.config_path)
            self.update_available_btn.hide()
            dlg.accept()

        dl_btn.clicked.connect(_do_download)
        rel_btn.clicked.connect(lambda: webbrowser.open(rel_url))
        skip_btn.clicked.connect(_do_skip)
        close_btn.clicked.connect(dlg.reject)
        dlg.exec()

    def _refresh_permission_pill_text(self):
        if not hasattr(self, 'permission_pill_btn'):
            return
        try:
            ap = load_access_permissions(self.config_path)
        except Exception:
            ap = {'permission_mode': 'default', 'write_exclusions': []}
        mk = normalize_permission_mode(ap.get('permission_mode'))
        meta = PERMISSION_MODE_META.get(mk, PERMISSION_MODE_META['default'])
        excl_n = len(ap.get('write_exclusions') or [])
        self.permission_pill_btn.setText(f"🛡 {meta['pill']} ▾")
        if mk == 'turbo':
            self.permission_pill_btn.setStyleSheet(
                'QPushButton { background: #1c1b29; color: #c084fc; border: 1px solid #9333ea; '
                'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 700; } '
                'QPushButton:hover { color: #f3e8ff; border-color: #a855f7; }'
            )
        elif mk == 'auto':
            self.permission_pill_btn.setStyleSheet(
                'QPushButton { background: #132238; color: #58a6ff; border: 1px solid #3b82f6; '
                'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
                'QPushButton:hover { color: #dbeafe; border-color: #60a5fa; }'
            )
        elif mk == 'request_review':
            self.permission_pill_btn.setStyleSheet(
                'QPushButton { background: #261b10; color: #f0b849; border: 1px solid #d29922; '
                'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
                'QPushButton:hover { color: #fef3c7; border-color: #eab308; }'
            )
        else:
            self.permission_pill_btn.setStyleSheet(
                'QPushButton { background: #161b22; color: #c9d1d9; border: 1px solid #262c3a; '
                'padding: 4px 7px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
                'QPushButton:hover { color: #f0f6fc; border-color: #3b82f6; }'
            )
        excl_note = f' · {excl_n} Write Exclusion(s) active' if excl_n else ' · 0 Write Exclusions'
        self.permission_pill_btn.setToolTip(
            f"AI Access Permissions: {meta['label']} — {meta['description']}{excl_note}"
        )

    def _set_permission_mode_quick(self, mode_key: str):
        mk = normalize_permission_mode(mode_key)
        save_access_permissions({'permission_mode': mk}, config_path=self.config_path)
        self._refresh_permission_pill_text()
        meta = PERMISSION_MODE_META.get(mk, PERMISSION_MODE_META['default'])
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setText(f"🛡 <b>AI Access Mode:</b> {html.escape(meta['label'])} — {html.escape(meta['description'])}")

    def _show_permission_mode_menu(self):
        if self.worker is not None:
            return
        ap = load_access_permissions(self.config_path)
        cur_mk = normalize_permission_mode(ap.get('permission_mode'))
        menu_style = (
            'QMenu { background: #161922; color: #e6edf3; border: 1px solid #2b313e; padding: 6px; border-radius: 8px; } '
            'QMenu::item { padding: 6px 14px 6px 10px; border-radius: 5px; font-size: 12.5px; } '
            'QMenu::item:selected { background: #232938; }'
        )
        menu = QMenu(self)
        menu.setStyleSheet(menu_style)
        menu.setToolTipsVisible(True)
        for mk in PERMISSION_MODES:
            meta = PERMISSION_MODE_META[mk]
            act = QAction(f"{meta['label']} — {meta['description']}", menu)
            act.setCheckable(True)
            act.setChecked(cur_mk == mk)
            act.triggered.connect(lambda _c=False, target=mk: self._set_permission_mode_quick(target))
            menu.addAction(act)
        menu.addSeparator()
        excl_n = len(ap.get('write_exclusions') or [])
        manage_excl_act = QAction(f'🛡 Manage Write Exclusion List ({excl_n})…', menu)
        manage_excl_act.triggered.connect(lambda: self.open_manage_ais('AI Access Permissions'))
        menu.addAction(manage_excl_act)

        pos = self.permission_pill_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        if pos.y() < 40:
            pos = self.permission_pill_btn.mapToGlobal(QPoint(0, self.permission_pill_btn.height() + 4))
        menu.exec(pos)

    def _show_pending_actions_banner(self, pending_actions: list[dict[str, Any]]):
        self._pending_workspace_actions = list(pending_actions or [])
        if not self._pending_workspace_actions or not hasattr(self, 'approval_banner'):
            if hasattr(self, 'approval_banner'):
                self.approval_banner.hide()
            return
        any_excluded = any(bool(a.get('excluded')) for a in self._pending_workspace_actions)
        cnt = len(self._pending_workspace_actions)
        if any_excluded:
            self.approval_banner.setStyleSheet(
                'QFrame#approvalBanner { background: #261414; border: 1px solid #f85149; border-radius: 8px; padding: 8px 12px; }'
            )
            self.approval_title_lbl.setStyleSheet('color: #ff7b72; font-weight: 700; font-size: 12.5px;')
            self.approval_title_lbl.setText(f'🛡 Write Exclusion Intercept — {cnt} Action(s) Require Your Approval')
        else:
            self.approval_banner.setStyleSheet(
                'QFrame#approvalBanner { background: #1e1610; border: 1px solid #d29922; border-radius: 8px; padding: 8px 12px; }'
            )
            self.approval_title_lbl.setStyleSheet('color: #f0b849; font-weight: 700; font-size: 12.5px;')
            self.approval_title_lbl.setText(f'🛡 Permission Required — {cnt} Pending Agent Action(s)')
        lines = []
        for idx, act in enumerate(self._pending_workspace_actions[:4], 1):
            lines.append(f"{idx}. {act.get('preview', act.get('summary', 'Action'))} — {act.get('reason', '')}")
        if cnt > 4:
            lines.append(f"... (+{cnt - 4} more)")
        self.approval_detail_lbl.setText('\n'.join(lines))
        self.approval_banner.show()

    def _approve_pending_workspace_actions(self):
        pending = list(getattr(self, '_pending_workspace_actions', []) or [])
        self._pending_workspace_actions = []
        if hasattr(self, 'approval_banner'):
            self.approval_banner.hide()
        if not pending:
            return
        from workspace_tools import execute_approved_action
        out_lines: list[str] = []
        for act in pending:
            ok, msg = execute_approved_action(act)
            icon = '✓' if ok else '⚠'
            out_lines.append(f"{icon} **{act.get('summary') or act.get('preview', 'Action')}**: {msg}")
        summary_md = '**Approved Action Execution Results:**\n\n' + '\n'.join(out_lines)
        self.append_message('assistant', summary_md, speaker='palace', render=True)
        is_no_history = self.no_history_btn.isChecked() or (not self.history_toggle.isChecked())
        if not is_no_history:
            try:
                self.store.context(self.session_id).append_exchange(
                    '[APPROVED WORKSPACE ACTIONS]',
                    summary_md,
                    contributors=['palace'],
                )
            except OSError:
                pass
        self.status_label.setText(f'✓ Executed {len(pending)} approved action(s).')

    def _reject_pending_workspace_actions(self):
        pending = list(getattr(self, '_pending_workspace_actions', []) or [])
        self._pending_workspace_actions = []
        if hasattr(self, 'approval_banner'):
            self.approval_banner.hide()
        if not pending:
            return
        msg = f'Cancelled {len(pending)} pending action(s) — nothing was written or executed.'
        self.status_label.setText(msg)
        self.append_message('assistant', f'✕ **Action Rejected**: {msg}', speaker='palace', render=True)

    def reload_providers_from_config(self):
        self.reload_provider_bar()

    def _switch_theme_and_persist(self, theme_id: str):
        self.apply_theme(theme_id)
        try:
            ui_cfg = load_ui_settings(self.config_path)
            ui_cfg['theme'] = str(theme_id or 'dark')
            save_ui_settings(ui_cfg, config_path=self.config_path)
        except Exception as exc:
            self.show_notice(f'Theme applied, but failed to save setting: {exc}')
        t_dict = load_theme_dict(theme_id)
        self.status_label.setText(f'Theme applied: {t_dict.get("name", theme_id)}')

    def apply_theme(self, theme_id: str, render_chat: bool = True):
        self.active_theme = str(theme_id or 'dark')
        if hasattr(self, '_item_html_cache'):
            self._item_html_cache.clear()
        t_dict = load_theme_dict(self.active_theme)
        self.setStyleSheet(build_theme_stylesheet(self.active_theme))
        if hasattr(self, 'chat') and isinstance(self.chat, ChatBrowser):
            self.chat.set_theme_colors(t_dict)
        if render_chat and getattr(self, 'chat_items', None):
            self._render_chat_items()

    def reload_provider_bar(self):
        from fairybread_mcp import get_council_cli_platforms
        from local_cli_provider import CLI_PROVIDER_TO_PLATFORM, PLATFORM_TO_CLI_PROVIDER, find_cli_binary
        try:
            configs = load_provider_configs(self.config_path)
            self.provider_states = {
                name: bool(settings.get('enabled', False))
                for name, settings in configs.items()
            }
            for pk in get_council_cli_platforms(self.config_path):
                prov_key = PLATFORM_TO_CLI_PROVIDER.get(pk)
                if prov_key and find_cli_binary(pk):
                    self.provider_states[prov_key] = True
        except Exception as exc:
            self.show_notice(str(exc))
            return
        for cli_prov_key in CLI_PROVIDER_TO_PLATFORM:
            if cli_prov_key not in self.provider_states and cli_prov_key in self.provider_labels:
                self.set_provider_status(cli_prov_key, 'Off', '#6e7681')
        for name, enabled in self.provider_states.items():
            if name not in self.provider_labels:
                label = QPushButton()
                label.setFlat(True)
                label.setCursor(Qt.CursorShape.PointingHandCursor)
                label.clicked.connect(lambda checked=False, n=name: self._on_top_provider_badge_clicked(n))
                self.provider_labels[name] = label
            self.set_provider_status(
                name,
                'Enabled' if enabled else 'Inactive',
                provider_color(name) if enabled else '#6e7681'
            )
        self._relayout_agent_bar()
        self._update_ai_pill_text()

    def _relayout_agent_bar(self):
        """KDE/XFCE-style pixel-width responsive layout for BOTH the left Agents: chips
        and the right status + token/spend labels.
        State 1: Normal 1-row when left chips + right labels fit comfortably in bar_w.
        State 2: Compact 1-row when normal overflows bar_w but compact 1-row fits.
        State 3: Balanced 2-row compact grid when compact 1-row still overflows bar_w:
                 - Left AI chips wrap into 2 balanced rows (ceil(N/2) columns)
                 - Right status_label (row 0) and bottom_token_label (row 1) stack into 2 rows.
        """
        if not hasattr(self, 'agent_chips_grid') or not hasattr(self, 'agent_workbench_frame'):
            return
        while self.agent_chips_grid.count():
            self.agent_chips_grid.takeAt(0)

        visible = [
            (name, btn)
            for name, btn in self.provider_labels.items()
            if self.provider_details.get(name, {}).get('status', 'Enabled') != 'Off'
        ]

        bar_w = self.agent_workbench_frame.width()
        if bar_w <= 100:
            bar_w = max(520, self.width() - 260)

        status_plain = (
            self.status_label.plain_text()
            if hasattr(self, 'status_label') and hasattr(self.status_label, 'plain_text')
            else (self.status_label.text() if hasattr(self, 'status_label') else 'Ready')
        )
        token_plain = (
            self.bottom_token_label.plain_text()
            if hasattr(self, 'bottom_token_label') and hasattr(self.bottom_token_label, 'plain_text')
            else (self.bottom_token_label.text() if hasattr(self, 'bottom_token_label') else '')
        )

        # Left AI chips width (including 'Agents:' caption ~56px)
        left_normal_px = 58 + sum(28 + len(btn.text().strip()) * 7.2 for _, btn in visible) + max(0, len(visible) - 1) * 6
        left_compact_px = 52 + sum(20 + len(btn.text().strip()) * 5.6 for _, btn in visible) + max(0, len(visible) - 1) * 4

        # Right status + token labels width on 1 row
        right_normal_1row_px = (len(status_plain) * 7.0 + 14) + (len(token_plain) * 7.2 + 16) + 16
        right_compact_1row_px = (len(status_plain) * 5.8 + 10) + (len(token_plain) * 6.0 + 12) + 12

        total_normal_1row = left_normal_px + right_normal_1row_px
        total_compact_1row = left_compact_px + right_compact_1row_px

        if total_normal_1row <= bar_w:
            state = 1  # 1-row normal
            compact = False
            bar_h = 28
        elif total_compact_1row <= bar_w:
            state = 2  # 1-row compact
            compact = True
            bar_h = 28
        else:
            state = 3  # 2-row compact (both left chips and right text can use 2 rows)
            compact = True
            bar_h = 48

        self.agent_workbench_frame.setFixedHeight(bar_h)

        font_sz = '10px' if compact else '11.5px'
        pad = '1px 3px' if compact else '2px 6px'
        btn_h = 19 if compact else 22
        icon_sz = 11 if compact else 13

        # Determine if left chips themselves need 2 rows in state 3
        right_2row_needed_px = min(max(180, int(bar_w * 0.42)), max(len(status_plain) * 5.8, len(token_plain) * 6.0) + 20)
        left_avail_in_state3 = max(160, bar_w - right_2row_needed_px - 20)
        if state == 3 and len(visible) > 1 and (left_compact_px > left_avail_in_state3 or len(visible) > 6):
            chip_rows = 2
            chip_cols = (len(visible) + 1) // 2
        else:
            chip_rows = 1
            chip_cols = max(1, len(visible))

        for idx, (name, btn) in enumerate(visible):
            status = self.provider_details.get(name, {}).get('status', 'Enabled')
            active = status in {'Enabled', 'Responded', 'Working'}
            fg = provider_color(name) if active else '#6e7681'
            weight = '600' if active else '500'
            btn.setIconSize(QSize(icon_sz, icon_sz))
            btn.setFixedSize(QSize(16777215, btn_h))
            btn.setStyleSheet(
                f'QPushButton {{ background: transparent; color: {fg}; border: none; '
                f'padding: {pad}; border-radius: 4px; font-size: {font_sz}; font-weight: {weight}; }} '
                f'QPushButton:hover {{ background: #1c2128; }}'
            )
            btn.setVisible(True)
            row = idx // chip_cols if chip_rows == 2 else 0
            col = idx % chip_cols if chip_rows == 2 else idx
            self.agent_chips_grid.addWidget(btn, row, col)

        # Layout right-side status_label + bottom_token_label using the exact same state rules
        if hasattr(self, 'right_status_grid') and hasattr(self, 'status_label') and hasattr(self, 'bottom_token_label'):
            while self.right_status_grid.count():
                self.right_status_grid.takeAt(0)

            lbl_h = 19 if compact else 22
            status_pad = '0px 4px' if compact else '1px 6px'
            token_pad = '0px 4px' if compact else '1px 6px'

            self.status_label.setMaximumHeight(lbl_h)
            self.status_label.setStyleSheet(
                f'color: #8b949e; font-size: {font_sz}; padding: {status_pad};'
            )
            self.bottom_token_label.setMaximumHeight(lbl_h)
            ledger = getattr(self, '_cost_ledger', None)
            has_conv_cost = bool(
                ledger is not None
                and getattr(ledger, 'total_cost_usd', 0.0) > 0.0
                and getattr(self, 'current_profile', '') != 'Idle'
            )
            cost_col = '#90d7c1' if has_conv_cost else '#8b949e'
            self.bottom_token_label.setStyleSheet(
                f'font-family: Consolas, monospace; font-size: {font_sz}; color: {cost_col}; padding: {token_pad};'
            )

            used_left_px = (left_compact_px // 2 + 40) if chip_rows == 2 else (left_compact_px if compact else left_normal_px)
            avail_right_px = max(150, bar_w - used_left_px - 24)

            align_r = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            if state in (1, 2):
                token_w = int(len(token_plain) * (6.0 if compact else 7.2) + 16)
                status_max_w = max(80, avail_right_px - token_w - 8)
                if hasattr(self.status_label, 'apply_elided_width'):
                    self.status_label.apply_elided_width(status_max_w)
                self.right_status_grid.addWidget(self.status_label, 0, 0, align_r)
                self.right_status_grid.addWidget(self.bottom_token_label, 0, 1, align_r)
            else:
                # State 3: Stack status_label on row 0 and bottom_token_label on row 1
                if hasattr(self.status_label, 'apply_elided_width'):
                    self.status_label.apply_elided_width(avail_right_px)
                self.right_status_grid.addWidget(self.status_label, 0, 0, align_r)
                self.right_status_grid.addWidget(self.bottom_token_label, 1, 0, align_r)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_agent_bar()

    def update_privacy_label(self):
        if self.history_toggle.isChecked():
            text = 'History active · Saved locally on this PC'
        else:
            text = 'History off · Turn will not read or save session history'
        self.privacy_label.setText(text)

    def _memory_db_path(self) -> Path:
        return self.proposal_service.path.parent / 'memory.db'

    def _backfill_shared_memory_once(self):
        try:
            from memory_service import MemoryService
            ms = MemoryService(db_path=self._memory_db_path())
            if ms.index.count() == 0 and hasattr(self, 'store') and hasattr(self.store, 'root'):
                ms.backfill_from_sessions(self.store.root)
            self._update_durable_memory_count()
        except Exception:
            pass

    @Slot(bool)
    def refresh_memory_review(self, visible):
        if not visible:
            return

        self.proposal_list.clear()
        self.proposal_detail.clear()
        self._backfill_shared_memory_once()

        proposals = []
        try:
            proposals = self.proposal_service.list_proposals()
        except (OSError, ValueError) as exc:
            self.show_notice(f'Could not load memory proposals: {exc}')

        for proposal in proposals:
            item = QListWidgetItem(
                f'{proposal["status"].title()} · '
                f'{proposal["memory_type"].title()}\n'
                f'{proposal["summary"]}'
            )
            item.setData(Qt.ItemDataRole.UserRole, proposal['id'])
            item.setToolTip(f'Pending proposal: {proposal["summary"]}')
            self.proposal_list.addItem(item)

        try:
            from memory_service import SQLiteMemoryIndex
            idx = SQLiteMemoryIndex(self._memory_db_path())
            q_filter = self.memory_search_edit.text().strip() if hasattr(self, 'memory_search_edit') else ''
            if q_filter:
                memories = idx.search(q_filter, limit=100)
            else:
                memories = idx.list_memories(limit=100)
        except Exception:
            memories = []

        self._cached_memories_map = {str(m['id']): m for m in memories}
        for mem in memories:
            mtype = str(mem.get('memory_type') or 'contextual').title()
            proj = str(mem.get('project') or '').strip()
            tag = f'{mtype} · {proj}' if proj else mtype
            item = QListWidgetItem(f'✓ Shared ({tag})\n{mem["summary"]}')
            item.setData(Qt.ItemDataRole.UserRole, f'mem:{mem["id"]}')
            item.setToolTip(mem['summary'])
            self.proposal_list.addItem(item)

        self._update_durable_memory_count()
        if self.proposal_list.count() == 0:
            self.proposal_list.addItem('No shared memories yet — chat normally or click + Add Memory.')
        try:
            from memory_service import load_memory_summary
            sum_data = load_memory_summary(self._memory_db_path())
            self.proposal_detail.setMarkdown(sum_data.get('text', ''))
        except Exception:
            pass

    @Slot(QListWidgetItem, QListWidgetItem)
    def show_memory_proposal(self, current, previous):
        if current is None:
            self.proposal_detail.clear()
            return

        raw_key = str(current.data(Qt.ItemDataRole.UserRole) or '')
        if not raw_key:
            self.proposal_detail.clear()
            return

        if raw_key.startswith('mem:'):
            if hasattr(self, 'approve_proposal_btn'):
                self.approve_proposal_btn.hide()
                self.reject_proposal_btn.hide()
            mid = raw_key.split(':', 1)[1]
            mem = getattr(self, '_cached_memories_map', {}).get(mid)
            if not mem:
                try:
                    from memory_service import SQLiteMemoryIndex
                    for m in SQLiteMemoryIndex(self._memory_db_path()).list_memories(limit=250):
                        if str(m.get('id')) == mid:
                            mem = m
                            break
                except Exception:
                    mem = None
            if not mem:
                self.proposal_detail.clear()
                return
            proj = str(mem.get('project') or 'General').strip()
            self.proposal_detail.setPlainText(
                f'Summary:\n{mem["summary"]}\n\n'
                f'Shared Context (Read by All Council AIs):\n{mem["body"]}\n\n'
                f'Project / Scope: {proj}'
            )
            return

        if hasattr(self, 'approve_proposal_btn'):
            self.approve_proposal_btn.show()
            self.reject_proposal_btn.show()

        try:
            proposal = self.proposal_service.read_proposal(raw_key)
        except (OSError, ValueError) as exc:
            self.proposal_detail.clear()
            self.show_notice(f'Could not load memory proposal: {exc}')
            return

        if proposal is None:
            self.proposal_detail.clear()
            self.show_notice('The selected memory proposal could not be found.')
            return

        source = proposal['source']
        self.proposal_detail.setPlainText(
            f'Summary:\n{proposal["summary"]}\n\n'
            f'Detail:\n{proposal["detail"]}\n\n'
            f'Source entry:\n{source["entry_id"]}'
        )

    def show_memory_summary_dialog(self):
        from memory_service import ai_update_memory_summary, load_memory_summary, save_memory_summary

        db_p = self._memory_db_path()
        sum_data = load_memory_summary(db_p)

        dlg = QDialog(self)
        dlg.setWindowTitle('Fairybread — Memory Summary (Shared Across All Council AIs)')
        dlg.resize(720, 660)
        dlg.setStyleSheet('background:#131720; color:#e6edf3;')
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(12)

        hdr_row = QHBoxLayout()
        title_lbl = QLabel('<b>Memory summary</b>')
        title_lbl.setStyleSheet('font-size: 16px; color: #f0f6fc;')
        age_lbl = QLabel(str(sum_data.get('updated_relative', 'Updated just now')))
        age_lbl.setStyleSheet('font-size: 12.5px; color: #8b949e; margin-left: 8px;')
        hdr_row.addWidget(title_lbl)
        hdr_row.addWidget(age_lbl)
        hdr_row.addStretch()

        edit_toggle_btn = QPushButton('✎ Edit Directly')
        edit_toggle_btn.setCheckable(True)
        edit_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_toggle_btn.setToolTip('Switch between formatted view and direct text editing')
        edit_toggle_btn.setStyleSheet(
            'QPushButton { background:#21262d; color:#c9d1d9; border:1px solid #30363d; border-radius:6px; padding:5px 12px; font-weight:600; } '
            'QPushButton:checked { background:#132238; color:#58a6ff; border:1px solid #3b82f6; }'
        )

        save_direct_btn = QPushButton('💾 Save Edits')
        save_direct_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_direct_btn.setToolTip('Save your direct text changes')
        save_direct_btn.setStyleSheet(
            'QPushButton { background:#11281b; color:#22c55e; border:1px solid #22c55e; border-radius:6px; padding:5px 12px; font-weight:700; }'
        )
        save_direct_btn.hide()

        refresh_ai_btn = QPushButton('↻ Auto-Update from Chats')
        refresh_ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_ai_btn.setToolTip('Have the AI refresh your Memory summary from recent conversations')
        refresh_ai_btn.setStyleSheet(
            'QPushButton { background:#21262d; color:#c9d1d9; border:1px solid #30363d; border-radius:6px; padding:5px 12px; font-weight:600; }'
        )

        close_x_btn = QPushButton('✕')
        close_x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x_btn.setToolTip('Close')
        close_x_btn.setFixedSize(30, 30)
        close_x_btn.setStyleSheet('QPushButton { background:transparent; color:#8b949e; border:none; font-size:15px; font-weight:700; } QPushButton:hover { color:#f0f6fc; }')
        close_x_btn.clicked.connect(dlg.accept)

        hdr_row.addWidget(edit_toggle_btn)
        hdr_row.addWidget(save_direct_btn)
        hdr_row.addWidget(refresh_ai_btn)
        hdr_row.addWidget(close_x_btn)
        v.addLayout(hdr_row)

        stack = QStackedWidget(dlg)
        reader = QTextBrowser(dlg)
        reader.setOpenExternalLinks(True)
        reader.setStyleSheet(
            'background:#0d1117; color:#e6edf3; border:1px solid #262c3a; border-radius:10px; padding:16px; font-size:13.5px; line-height:1.55;'
        )
        reader.setMarkdown(sum_data.get('text', ''))

        editor = QTextEdit(dlg)
        editor.setAcceptRichText(False)
        editor.setStyleSheet(
            'background:#0d1117; color:#f0f6fc; border:1px solid #3b82f6; border-radius:10px; padding:16px; font-family: "Segoe UI", Consolas; font-size:13.5px;'
        )
        editor.setPlainText(sum_data.get('text', ''))

        stack.addWidget(reader)
        stack.addWidget(editor)
        v.addWidget(stack, 1)

        status_lbl = QLabel('Shared with all 8 Council AIs on every turn · Click "✎ Edit Directly" to edit by hand or use "Ask or update" below.')
        status_lbl.setStyleSheet('font-size: 11.5px; color: #8b949e;')
        v.addWidget(status_lbl)

        # Bottom rounded 'Ask or update' bar (matching ChatGPT screenshot)
        ask_bar = QFrame(dlg)
        ask_bar.setStyleSheet('background:#1c212b; border:1px solid #30363d; border-radius:20px; padding:4px 8px;')
        ask_lay = QHBoxLayout(ask_bar)
        ask_lay.setContentsMargins(10, 2, 4, 2)
        ask_edit = QLineEdit(ask_bar)
        ask_edit.setPlaceholderText('Ask or update (e.g. "Add that Palace is now called Fairybread on GitHub")')
        ask_edit.setStyleSheet('background:transparent; border:none; color:#f0f6fc; font-size:13px;')
        ask_send_btn = QPushButton('↑', ask_bar)
        ask_send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ask_send_btn.setToolTip('Update Memory summary')
        ask_send_btn.setFixedSize(30, 30)
        ask_send_btn.setStyleSheet(
            'QPushButton { background:#58a6ff; color:#0d1117; border:none; border-radius:15px; font-size:14px; font-weight:700; }'
        )
        ask_lay.addWidget(ask_edit, 1)
        ask_lay.addWidget(ask_send_btn)
        v.addWidget(ask_bar)

        def _toggle_edit(editing: bool):
            if editing:
                editor.setPlainText(load_memory_summary(db_p).get('text', ''))
                stack.setCurrentIndex(1)
                save_direct_btn.show()
                edit_toggle_btn.setText('👁 Preview')
                editor.setFocus()
            else:
                saved = save_memory_summary(editor.toPlainText(), db_path=db_p)
                reader.setMarkdown(saved['text'])
                age_lbl.setText(saved['updated_relative'])
                stack.setCurrentIndex(0)
                save_direct_btn.hide()
                edit_toggle_btn.setText('✎ Edit Directly')
                status_lbl.setStyleSheet('font-size: 11.5px; color: #22c55e;')
                status_lbl.setText('✓ Memory summary saved and synced to all Council AIs.')
                if hasattr(self, 'memory_panel') and self.memory_panel.isVisible():
                    self.refresh_memory_review(True)

        def _save_direct():
            saved = save_memory_summary(editor.toPlainText(), db_path=db_p)
            reader.setMarkdown(saved['text'])
            age_lbl.setText(saved['updated_relative'])
            edit_toggle_btn.setChecked(False)
            status_lbl.setStyleSheet('font-size: 11.5px; color: #22c55e;')
            status_lbl.setText('✓ Direct edits saved to Shared Memory.')
            if hasattr(self, 'memory_panel') and self.memory_panel.isVisible():
                self.refresh_memory_review(True)

        def _run_ai_update(custom_note: str = ''):
            note = (custom_note or ask_edit.text()).strip()
            status_lbl.setStyleSheet('font-size: 11.5px; color: #58a6ff;')
            status_lbl.setText('⏳ Updating Memory summary with AI…')
            QApplication.processEvents()
            updated = ai_update_memory_summary(note, db_path=db_p)
            reader.setMarkdown(updated['text'])
            editor.setPlainText(updated['text'])
            age_lbl.setText(updated['updated_relative'])
            ask_edit.clear()
            status_lbl.setStyleSheet('font-size: 11.5px; color: #22c55e;')
            status_lbl.setText('✓ Memory summary updated by AI and shared with all Council agents.')
            if hasattr(self, 'memory_panel') and self.memory_panel.isVisible():
                self.refresh_memory_review(True)

        edit_toggle_btn.toggled.connect(_toggle_edit)
        save_direct_btn.clicked.connect(_save_direct)
        refresh_ai_btn.clicked.connect(lambda: _run_ai_update('Refresh and refine from recent conversations'))
        ask_send_btn.clicked.connect(lambda: _run_ai_update(ask_edit.text()))
        ask_edit.returnPressed.connect(lambda: _run_ai_update(ask_edit.text()))
        dlg.exec()

    def add_standing_memory(self):
        text, ok = QInputDialog.getMultiLineText(
            self,
            'Add Standing Memory for All Council AIs',
            'Enter a fact, preference, or standing instruction that all Council AIs should always remember:',
            '',
        )
        if not ok or not text.strip():
            return
        clean = text.strip()
        first_line = clean.splitlines()[0].strip()
        summary = first_line[:120] if len(first_line) > 3 else clean[:120]
        try:
            from memory_service import SQLiteMemoryIndex
            idx = SQLiteMemoryIndex(self._memory_db_path())
            idx.upsert(
                summary=summary,
                body=clean,
                project=self._current_project_name(),
                memory_type='standing',
                source={'kind': 'user_added'},
            )
            self.refresh_memory_review(True)
            self.show_notice('✓ Added standing memory to Shared Memory.')
        except Exception as exc:
            self.show_notice(f'Could not save memory: {exc}')

    def delete_selected_memory(self):
        current = self.proposal_list.currentItem()
        if current is None:
            return
        raw_key = str(current.data(Qt.ItemDataRole.UserRole) or '')
        if not raw_key:
            return
        if raw_key.startswith('mem:'):
            mid = raw_key.split(':', 1)[1]
            try:
                from memory_service import SQLiteMemoryIndex
                SQLiteMemoryIndex(self._memory_db_path()).delete_memory(mid)
                self.refresh_memory_review(True)
                self.show_notice('🗑 Memory forgotten from Shared Memory.')
            except Exception as exc:
                self.show_notice(f'Could not delete memory: {exc}')
        else:
            self.reject_selected_proposal()

    def _update_durable_memory_count(self):
        if not hasattr(self, 'durable_mem_count_label'):
            return
        try:
            from memory_service import SQLiteMemoryIndex
            cnt = SQLiteMemoryIndex(self._memory_db_path()).count()
            self.durable_mem_count_label.setText(f'Shared Contextual Memories (All AIs): {cnt}')
        except Exception:
            pass

    def approve_selected_proposal(self):
        current = self.proposal_list.currentItem()
        if current is None:
            return
        proposal_id = current.data(Qt.ItemDataRole.UserRole)
        if not proposal_id:
            return
        try:
            self.proposal_service.approve_proposal(
                proposal_id,
                project=self._current_project_name(),
            )
            self.show_notice('Memory proposal approved and indexed in Shared Memory.')
            self.refresh_memory_review(True)
            self._update_durable_memory_count()
        except Exception as exc:
            self.show_notice(f'Could not approve memory proposal: {exc}')

    def reject_selected_proposal(self):
        current = self.proposal_list.currentItem()
        if current is None:
            return
        proposal_id = current.data(Qt.ItemDataRole.UserRole)
        if not proposal_id:
            return
        try:
            self.proposal_service.reject_proposal(proposal_id)
            self.show_notice('Memory proposal rejected and removed.')
            self.refresh_memory_review(True)
        except Exception as exc:
            self.show_notice(f'Could not reject memory proposal: {exc}')

    def _current_project_name(self) -> str:
        selected_proj = getattr(self.store, 'selected_project', None)
        if selected_proj:
            for proj in getattr(self.store, 'projects', []):
                if proj['id'] == selected_proj:
                    return proj['name']
        return 'Fairybread'

    def _update_breadcrumb(self, session_title: str):
        proj_name = self._current_project_name()
        folder = self.store.get_project_folder() if hasattr(self.store, 'get_project_folder') else ''
        self.conversation_title.setText(f'{proj_name}  /  {session_title}')
        if hasattr(self, 'attached_folder_chip'):
            if folder:
                folder_short = Path(folder).name or folder
                self.attached_folder_chip.setText(f'📁 {folder_short}')
                self.attached_folder_chip.setToolTip(f'Attached Project Folder: {folder}\nClick to change attached folder')
                self.attached_folder_chip.show()
            else:
                self.attached_folder_chip.hide()

    def refresh_projects(self):
        self.project_list.blockSignals(True)
        self.project_list.clear()
        selected_proj = getattr(self.store, 'selected_project', None)
        arrow_all = '⌄' if selected_proj is None else '›'
        all_item = QListWidgetItem(f'{arrow_all}  All discussions')
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self.project_list.addItem(all_item)
        if selected_proj is None:
            self.project_list.setCurrentItem(all_item)
        for proj in getattr(self.store, 'projects', []):
            arrow = '⌄' if proj['id'] == selected_proj else '›'
            folder = str(proj.get('folder') or '').strip()
            folder_badge = '  📁' if folder else ''
            item = QListWidgetItem(f'{arrow}  {proj["name"]}{folder_badge}')
            item.setData(Qt.ItemDataRole.UserRole, proj['id'])
            tip = f'{proj["name"]}\nAttached folder: {folder}' if folder else f'{proj["name"]} (right-click or click 📁 to attach a folder)'
            item.setToolTip(tip)
            self.project_list.addItem(item)
            if proj['id'] == selected_proj:
                self.project_list.setCurrentItem(item)
        self.project_list.blockSignals(False)

    def attach_folder_to_current_project(self, project_id: str | None = None, folder_path: str | None = None):
        if self.worker is not None:
            return
        target_id = project_id or getattr(self.store, 'selected_project', None)
        if not target_id:
            self.show_notice('Select or create a Project in the sidebar first, then click 📁 to attach a folder to it.')
            return
        if folder_path is None:
            chosen = QFileDialog.getExistingDirectory(self, 'Attach Local Folder to Project', '')
            if not chosen:
                return
            folder_path = chosen
        try:
            resolved = self.store.set_project_folder(target_id, folder_path)
            self.refresh_projects()
            self.refresh_sessions()
            proj_name = self._current_project_name()
            if resolved:
                self.status_label.setText(f'Attached folder "{resolved}" to Project "{proj_name}".')
            else:
                self.status_label.setText(f'Detached folder from Project "{proj_name}".')
        except (OSError, ValueError) as exc:
            self.show_notice(str(exc))

    def _show_project_context_menu(self, pos: QPoint):
        item = self.project_list.itemAt(pos)
        if item is None:
            return
        proj_id = item.data(Qt.ItemDataRole.UserRole)
        if not proj_id:
            return
        menu = QMenu(self)
        cur_folder = self.store.get_project_folder(proj_id) if hasattr(self.store, 'get_project_folder') else ''
        attach_act = menu.addAction('📁 Change Attached Folder…' if cur_folder else '📁 Attach Folder to Project…')
        detach_act = menu.addAction('✕ Detach Folder') if cur_folder else None
        chosen = menu.exec(self.project_list.mapToGlobal(pos))
        if chosen == attach_act:
            self.attach_folder_to_current_project(project_id=proj_id)
        elif detach_act is not None and chosen == detach_act:
            self.attach_folder_to_current_project(project_id=proj_id, folder_path='')

    def new_project(self, name: str | None = None):
        if self.worker is not None or not self.confirm_switch():
            return
        if name is None:
            text, ok = QInputDialog.getText(
                self,
                'New Project',
                'Project name (no folder required):'
            )
            if not ok or not text.strip():
                return
            name = text
        try:
            self.store.create_project(name)
            self.session_id = self.store.selected
            self.reset_draft()
            self.refresh_projects()
            self.refresh_sessions()
            self.load_history()
            self.composer.setFocus()
            self.status_label.setText(f'Project "{name.strip()}" created · Ready')
        except (OSError, ValueError) as exc:
            self.show_notice(str(exc))

    def change_project(self, current, previous):
        if current is None:
            return
        proj_id = current.data(Qt.ItemDataRole.UserRole)
        if proj_id == getattr(self.store, 'selected_project', None):
            return
        if self.worker is not None or not self.confirm_switch():
            self.refresh_projects()
            return
        try:
            self.store.select_project(proj_id)
            self.session_id = self.store.selected
            self.reset_draft()
            self.refresh_projects()
            self.refresh_sessions()
            self.load_history()
            self.status_label.setText('Project switched · Ready')
        except (OSError, ValueError) as exc:
            self.show_notice(str(exc))
            self.refresh_projects()

    def refresh_sessions(self):
        from PySide6.QtGui import QColor

        # Populate Pinned list (only shown when at least 1 non-archived conversation is pinned)
        self.pinned_list.blockSignals(True)
        self.pinned_list.clear()
        pinned = [
            s for s in (self.store.pinned_sessions() if hasattr(self.store, 'pinned_sessions') else [])
            if not s.get('archived')
        ]
        for session in pinned:
            age = self.store.session_relative_age(session['id']) if hasattr(self.store, 'session_relative_age') else ''
            title_txt = f"{session['title']}   {age}".strip()
            p_item = QListWidgetItem(title_txt)
            p_item.setData(Qt.ItemDataRole.UserRole, session['id'])
            p_item.setToolTip(session['title'])
            self.pinned_list.addItem(p_item)
            if session['id'] == self.session_id:
                self.pinned_list.setCurrentItem(p_item)
        self.pinned_toggle_btn.setVisible(bool(pinned))
        self.pinned_list.setVisible(self.pinned_toggle_btn.isChecked() and bool(pinned))
        self.pinned_list.blockSignals(False)

        # Populate Antigravity-style unified Projects + Conversations sidebar list
        self.session_list.blockSignals(True)
        self.session_list.clear()
        selected_proj = getattr(self.store, 'selected_project', None)
        projects = list(getattr(self.store, 'projects', []) or [])
        all_sessions = list(getattr(self.store, 'sessions', []) or [])
        active_sessions = [s for s in all_sessions if not s.get('archived')]
        archived_sessions = [s for s in all_sessions if s.get('archived')]
        archived_expanded = bool(getattr(self, '_archived_expanded', False))

        def _add_session_row(sess: dict, indented: bool = False):
            age = self.store.session_relative_age(sess['id']) if hasattr(self.store, 'session_relative_age') else ''
            raw_title = str(sess.get('title') or 'New conversation')
            short_title = raw_title if len(raw_title) <= 27 else raw_title[:26] + '…'
            prefix = '  ' if indented else ''
            display = f'{prefix}{short_title}   {age}' if age else f'{prefix}{short_title}'
            row = QListWidgetItem(display)
            row.setData(Qt.ItemDataRole.UserRole, sess['id'])
            row.setData(
                SIDEBAR_META_ROLE,
                {
                    'kind': 'session',
                    'id': sess['id'],
                    'title': raw_title,
                    'age': age,
                    'indented': bool(indented),
                    'pinned': bool(sess.get('pinned', False)),
                    'unread': bool(sess.get('unread', False)),
                    'archived': bool(sess.get('archived', False)),
                    'selected': bool(sess['id'] == self.session_id),
                },
            )
            row.setToolTip(f'{raw_title}\n(Hover for Pin / ⋮ options, or drag onto a Project)')
            row.setSizeHint(QSize(0, 26))
            row.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            self.session_list.addItem(row)
            if sess['id'] == self.session_id:
                self.session_list.setCurrentItem(row)
                self._update_breadcrumb(raw_title)

        if projects:
            bold_font = QFont('Segoe UI', 9)
            bold_font.setBold(True)
            italic_font = QFont('Segoe UI', 9)
            italic_font.setItalic(True)

            for proj in projects:
                pid = proj['id']
                folder = str(proj.get('folder') or '').strip()
                folder_tag = f'  [{Path(folder).name}]' if folder else ''
                proj_label = f'{proj["name"]}{folder_tag}'
                hdr = QListWidgetItem(proj_label)
                hdr.setIcon(folder_grey_qicon(pid == selected_proj))
                hdr.setData(Qt.ItemDataRole.UserRole, f'proj:{pid}')
                hdr.setData(
                    SIDEBAR_META_ROLE,
                    {
                        'kind': 'project',
                        'id': pid,
                        'title': proj_label,
                        'selected': bool(pid == selected_proj),
                    },
                )
                hdr.setFont(bold_font)
                hdr.setSizeHint(QSize(0, 26))
                hdr.setForeground(QColor('#c9d1d9' if pid == selected_proj else '#8b949e'))
                hdr.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDropEnabled
                )
                tip = f'Project: {proj["name"]}\nHover for ⋮ / + options or drag conversations here.'
                if folder:
                    tip += f'\nAttached folder: {folder}'
                hdr.setToolTip(tip)
                self.session_list.addItem(hdr)

                proj_sessions = [s for s in active_sessions if s.get('project_id') == pid]
                if not proj_sessions:
                    empty_row = QListWidgetItem('  No conversations yet')
                    empty_row.setData(Qt.ItemDataRole.UserRole, f'proj:{pid}')
                    empty_row.setFont(italic_font)
                    empty_row.setSizeHint(QSize(0, 21))
                    empty_row.setForeground(QColor('#484f58'))
                    empty_row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
                    self.session_list.addItem(empty_row)
                else:
                    for s in proj_sessions:
                        _add_session_row(s, indented=True)

            unassigned = [s for s in active_sessions if not s.get('project_id')]
            if unassigned:
                gen_hdr = QListWidgetItem('Conversations')
                gen_hdr.setData(Qt.ItemDataRole.UserRole, 'proj:')
                gen_hdr.setData(SIDEBAR_META_ROLE, {'kind': 'project', 'id': '', 'title': 'Conversations', 'selected': False})
                gen_hdr.setFont(bold_font)
                gen_hdr.setSizeHint(QSize(0, 24))
                gen_hdr.setForeground(QColor('#6e7681'))
                gen_hdr.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
                self.session_list.addItem(gen_hdr)
                for s in unassigned:
                    _add_session_row(s, indented=False)
        else:
            bold_font = QFont('Segoe UI', 9)
            bold_font.setBold(True)
            italic_font = QFont('Segoe UI', 9)
            italic_font.setItalic(True)
            empty_proj = QListWidgetItem('No projects yet (click +)')
            empty_proj.setIcon(folder_grey_qicon(False))
            empty_proj.setData(Qt.ItemDataRole.UserRole, 'proj:')
            empty_proj.setFont(italic_font)
            empty_proj.setSizeHint(QSize(0, 22))
            empty_proj.setForeground(QColor('#484f58'))
            self.session_list.addItem(empty_proj)

            rec_hdr = QListWidgetItem('Conversations')
            rec_hdr.setData(Qt.ItemDataRole.UserRole, 'proj:')
            rec_hdr.setData(SIDEBAR_META_ROLE, {'kind': 'project', 'id': '', 'title': 'Conversations', 'selected': False})
            rec_hdr.setFont(bold_font)
            rec_hdr.setSizeHint(QSize(0, 24))
            rec_hdr.setForeground(QColor('#6e7681'))
            rec_hdr.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            self.session_list.addItem(rec_hdr)
            for s in active_sessions:
                _add_session_row(s, indented=False)

        if archived_sessions:
            arch_glyph = '⌄' if archived_expanded else '›'
            arch_hdr = QListWidgetItem(f'{arch_glyph}  Archived ({len(archived_sessions)})')
            arch_hdr.setData(Qt.ItemDataRole.UserRole, 'archived_toggle')
            arch_hdr.setData(
                SIDEBAR_META_ROLE,
                {
                    'kind': 'archived_header',
                    'count': len(archived_sessions),
                    'expanded': archived_expanded,
                },
            )
            arch_hdr.setSizeHint(QSize(0, 24))
            arch_hdr.setFlags(Qt.ItemFlag.ItemIsEnabled)
            arch_hdr.setToolTip('Click to expand or collapse archived discussions')
            self.session_list.addItem(arch_hdr)
            if archived_expanded:
                for arch_s in archived_sessions:
                    _add_session_row(arch_s, indented=True)

        self.session_list.blockSignals(False)
        self._sync_sidebar_working_indicator()

    def _on_sidebar_sessions_reordered(self, ordered_entries: list[tuple[str, str | None]]):
        if not hasattr(self.store, 'reorder_and_assign_sessions'):
            return
        try:
            self.store.reorder_and_assign_sessions(ordered_entries)
            self.refresh_projects()
            self.refresh_sessions()
            self.status_label.setText('Conversation order updated')
        except Exception as exc:
            self.show_notice(str(exc))

    def _on_voice_capture_error(self, err_msg: str):
        self.stop_all_voice_modes(exit_talk_only=False)
        self.show_notice(f'🎤 Microphone warning: {err_msg}')
        self.append_status_message(f'Status: Microphone capture error — {err_msg}', severity='error', icon_prefix='✕ 🎤', force=True, render=True)

    def _on_voice_barge_in(self):
        self._voice_session_gen = int(getattr(self, '_voice_session_gen', 0)) + 1
        self._barge_badge_until = time.monotonic() + 0.9
        if hasattr(self, 'voice_level_badge'):
            self.voice_level_badge.setText('⚡ Interrupted — listening…')
            self.voice_level_badge.setStyleSheet(
                'font-family: Consolas, monospace; font-size: 11px; font-weight: 700; color: #eab308; '
                'background: #29230f; border: 1px solid #eab308; border-radius: 6px; padding: 3px 7px;'
            )
            self.voice_level_badge.show()
        self.show_notice('⚡ Speech interrupted — listening…')

    def _refresh_voice_bar_pills(self, active_tts_label: str = '', tts_fell_back: bool = False):
        try:
            from voice_service import TTS_ENGINE_SHORT_LABELS, load_voice_settings
            v_cfg = load_voice_settings(self.config_path)
        except Exception:
            TTS_ENGINE_SHORT_LABELS = {}
            v_cfg = {}

        if hasattr(self, 'voice_brain_btn'):
            cfg_p = str(v_cfg.get('voice_llm_provider') or 'auto').strip().lower()
            shown_p = str(getattr(self, '_last_voice_brain_provider', '') or '').strip().lower()
            eff_p = shown_p if (shown_p and shown_p not in {'local', 'fallback', 'injected'}) else cfg_p
            fell_back = bool(getattr(self, '_last_voice_brain_fell_back', False))
            req_p = str(getattr(self, '_last_voice_brain_requested', '') or cfg_p).strip().lower()
            if fell_back and eff_p and eff_p != 'auto' and req_p not in {'', 'auto', eff_p}:
                self.voice_brain_btn.setText(f'⚠ 🧠 {provider_display_name(req_p)} → {provider_display_name(eff_p)} ▾')
                self.voice_brain_btn.setToolTip(
                    f'Thinking AI fell back from {provider_display_name(req_p)} to {provider_display_name(eff_p)} — '
                    f'your saved setting is still {provider_display_name(req_p)}. Click to switch anytime.'
                )
                self.voice_brain_btn.setStyleSheet(
                    'QPushButton { background: #29230f; color: #eab308; border: 1px solid #eab308; '
                    'padding: 3px 7px; border-radius: 6px; font-size: 11px; font-weight: 700; } '
                    'QPushButton:hover { background: #3a3114; color: #fef08a; }'
                )
            elif eff_p and eff_p != 'auto':
                col = provider_color(eff_p)
                ic = provider_icon(eff_p)
                dn = provider_display_name(eff_p)
                self.voice_brain_btn.setText(f'🧠 {ic} {dn} ▾')
                self.voice_brain_btn.setToolTip('Thinking AI (🧠): who thinks & writes replies in Voice/Talk Mode (click to switch anytime)')
                self.voice_brain_btn.setStyleSheet(
                    f'QPushButton {{ background: #161b22; color: {col}; border: 1px solid {col}; '
                    f'padding: 3px 7px; border-radius: 6px; font-size: 11px; font-weight: 700; }} '
                    f'QPushButton:hover {{ background: #1f2633; color: #f0f6fc; }}'
                )
            else:
                self.voice_brain_btn.setText('🧠 Auto ▾')
                self.voice_brain_btn.setToolTip('Thinking AI (🧠): who thinks & writes replies in Voice/Talk Mode (click to switch anytime)')
                self.voice_brain_btn.setStyleSheet(
                    'QPushButton { background: #161b22; color: #38bdf8; border: 1px solid #30363d; '
                    'padding: 3px 7px; border-radius: 6px; font-size: 11px; font-weight: 600; } '
                    'QPushButton:hover { color: #f0f6fc; border-color: #58a6ff; }'
                )

        if hasattr(self, 'voice_tts_btn'):
            eng = str(v_cfg.get('tts_engine') or 'auto').strip().lower()
            short = active_tts_label or TTS_ENGINE_SHORT_LABELS.get(eng, eng.title())
            if tts_fell_back:
                self.voice_tts_btn.setText(f'⚠ 🔊 {short} ▾')
                self.voice_tts_btn.setStyleSheet(
                    'QPushButton { background: #29230f; color: #eab308; border: 1px solid #eab308; '
                    'padding: 3px 7px; border-radius: 6px; font-size: 11px; font-weight: 700; }'
                )
            else:
                self.voice_tts_btn.setText(f'🔊 {short} ▾')
                self.voice_tts_btn.setStyleSheet(
                    'QPushButton { background: #161b22; color: #c9d1d9; border: 1px solid #30363d; '
                    'padding: 3px 7px; border-radius: 6px; font-size: 11px; font-weight: 600; } '
                    'QPushButton:hover { color: #f0f6fc; border-color: #58a6ff; }'
                )

    def _sync_voice_footer_state(self):
        talk_only = bool(getattr(self, '_talk_only_mode', False))
        live_voice = hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked()
        voice_on = talk_only or live_voice
        if hasattr(self, 'loaded_agents_caption'):
            if talk_only:
                self.loaded_agents_caption.setText('Voice 🧠:')
            elif live_voice:
                self.loaded_agents_caption.setText('Voice 🧠 + Team:')
            else:
                self.loaded_agents_caption.setText('Agents:')
        if voice_on:
            try:
                from voice_service import load_voice_settings
                v_cfg = load_voice_settings(self.config_path)
            except Exception:
                v_cfg = {}
            shown_p = str(getattr(self, '_last_voice_brain_provider', '') or '').lower()
            cfg_p = str(v_cfg.get('voice_llm_provider') or 'auto').lower()
            active_p = shown_p if (shown_p and shown_p not in {'local', 'fallback', 'injected'}) else cfg_p
            if active_p == 'auto':
                pref_list = ('groq', 'deepseek', 'gemini', 'openai', 'cerebras', 'qwen', 'cohere', 'mistral') if talk_only else ('deepseek', 'gemini', 'openai', 'groq', 'cerebras', 'qwen', 'cohere', 'mistral')
                active_p = next((p for p in pref_list if self.provider_states.get(p) is True), '')
            for name in list(self.provider_labels.keys()):
                en = self.provider_states.get(name)
                if en is not True:
                    continue
                if name == active_p:
                    self.set_provider_status(name, 'Enabled', provider_color(name), 'Active Thinking AI (🧠) for Voice Mode')
                elif talk_only:
                    self.set_provider_status(name, 'Inactive', NEUTRAL_GREY, 'Standing by (not active in Talk Mode)')
                else:
                    self.set_provider_status(name, 'Enabled', provider_color(name), 'Ready for delegated Council tasks from Voice')
        else:
            for name, en in list(self.provider_states.items()):
                if en == 'inactive':
                    self.set_provider_status(name, 'Inactive', NEUTRAL_GREY, 'INACTIVE_IN_PROFILE: Loaded in background, click to activate.')
                elif en is True:
                    self.set_provider_status(name, 'Enabled', provider_color(name))
                else:
                    self.set_provider_status(name, 'Off', '#6e7681')
        self._relayout_agent_bar()

    @Slot()
    def _show_voice_brain_menu(self):
        from voice_service import load_voice_settings, save_voice_settings
        v_cfg = load_voice_settings(self.config_path)
        cur = str(v_cfg.get('voice_llm_provider') or 'auto').lower()
        cred = CredentialStore()
        menu = QMenu(self)
        menu.setStyleSheet(
            'QMenu { background: #161922; color: #e6edf3; border: 1px solid #2b313e; padding: 6px; border-radius: 8px; } '
            'QMenu::item { padding: 6px 14px; border-radius: 5px; font-size: 12.5px; } '
            'QMenu::item:selected { background: #232938; }'
        )
        hdr = menu.addAction('🧠 Thinking AI — who thinks & writes replies')
        hdr.setEnabled(False)
        menu.addSeparator()

        def _pick_brain(pid: str):
            save_voice_settings({'voice_llm_provider': pid}, config_path=self.config_path)
            self._last_voice_brain_provider = '' if pid == 'auto' else pid
            self._last_voice_brain_fell_back = False
            self._last_voice_brain_requested = '' if pid == 'auto' else pid
            self._refresh_voice_bar_pills()
            self._sync_voice_footer_state()
            lbl = 'Auto (Fastest Ready)' if pid == 'auto' else f'{provider_icon(pid)} {provider_display_name(pid)}'
            self.show_notice(f'🧠 Switched Thinking AI to {lbl}')

        a_auto = QAction('Auto — Fastest Ready AI', menu)
        a_auto.setCheckable(True)
        a_auto.setChecked(cur == 'auto')
        a_auto.triggered.connect(lambda: _pick_brain('auto'))
        menu.addAction(a_auto)

        for pk in ('gemini', 'openai', 'deepseek', 'groq', 'qwen', 'cohere', 'mistral', 'cerebras'):
            has_k = False
            try:
                has_k = bool((cred.get_api_key(pk) or '').strip())
            except Exception:
                has_k = False
            if not has_k:
                continue
            act = QAction(f'{provider_icon(pk)}  {provider_display_name(pk)}', menu)
            act.setCheckable(True)
            act.setChecked(cur == pk)
            act.triggered.connect(lambda _checked=False, p=pk: _pick_brain(p))
            menu.addAction(act)

        menu.addSeparator()
        more_act = QAction('⚙ Configure Fallback & Keys in Settings…', menu)
        more_act.triggered.connect(lambda: self.open_manage_ais('Voice & Audio'))
        menu.addAction(more_act)
        pos = self.voice_brain_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        if pos.y() < 40:
            pos = self.voice_brain_btn.mapToGlobal(QPoint(0, self.voice_brain_btn.height() + 4))
        menu.exec(pos)

    @Slot()
    def _show_voice_tts_menu(self):
        from voice_service import (
            TTS_ENGINES,
            TTS_ENGINE_SHORT_LABELS,
            get_tts_engine_display_label,
            is_tts_engine_ready,
            load_voice_settings,
            save_voice_settings,
        )
        v_cfg = load_voice_settings(self.config_path)
        cur = str(v_cfg.get('tts_engine') or 'auto').lower()
        cred = CredentialStore()
        menu = QMenu(self)
        menu.setStyleSheet(
            'QMenu { background: #161922; color: #e6edf3; border: 1px solid #2b313e; padding: 6px; border-radius: 8px; } '
            'QMenu::item { padding: 6px 14px; border-radius: 5px; font-size: 12.5px; } '
            'QMenu::item:selected { background: #232938; }'
        )
        hdr = menu.addAction('🔊 Speaking Voice — only changes sound aloud')
        hdr.setEnabled(False)
        menu.addSeparator()

        def _pick_tts(eid: str):
            save_voice_settings({'tts_engine': eid}, config_path=self.config_path)
            self._refresh_voice_bar_pills()
            self.show_notice(f'🔊 Switched Speaking Voice to {TTS_ENGINE_SHORT_LABELS.get(eid, eid)}')

        for eid, _ in TTS_ENGINES:
            if not is_tts_engine_ready(eid, credential_store=cred):
                continue
            act = QAction(get_tts_engine_display_label(eid, credential_store=cred), menu)
            act.setCheckable(True)
            act.setChecked(cur == eid)
            act.triggered.connect(lambda _checked=False, e=eid: _pick_tts(e))
            menu.addAction(act)

        menu.addSeparator()
        more_act = QAction('＋ Add Cartesia / ElevenLabs / Pick Voices in Settings…', menu)
        more_act.triggered.connect(lambda: self.open_manage_ais('Voice & Audio'))
        menu.addAction(more_act)
        pos = self.voice_tts_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        if pos.y() < 40:
            pos = self.voice_tts_btn.mapToGlobal(QPoint(0, self.voice_tts_btn.height() + 4))
        menu.exec(pos)

    def _on_voice_level_update(self, lvl: int, bars: str, speech_detected: bool):
        if not hasattr(self, 'voice_level_badge'):
            return
        barge_hold = time.monotonic() < float(getattr(self, '_barge_badge_until', 0.0))
        if barge_hold:
            self.voice_level_badge.setText(f'⚡ {bars} {lvl:2d}% · Interrupted')
            self.voice_level_badge.setStyleSheet(
                'font-family: Consolas, monospace; font-size: 11px; font-weight: 700; color: #eab308; '
                'background: #29230f; border: 1px solid #eab308; border-radius: 6px; padding: 3px 7px;'
            )
        elif self.worker is not None:
            self.voice_level_badge.setText(f'🎙 {lvl:2d}%')
            if speech_detected or lvl >= 8:
                self.voice_level_badge.setStyleSheet(
                    'font-family: Consolas, monospace; font-size: 11px; font-weight: 700; color: #22c55e; '
                    'background: #11281b; border: 1px solid #22c55e; border-radius: 6px; padding: 3px 7px;'
                )
            else:
                self.voice_level_badge.setStyleSheet(
                    'font-family: Consolas, monospace; font-size: 11px; font-weight: 600; color: #58a6ff; '
                    'background: #132238; border: 1px solid #3b82f6; border-radius: 6px; padding: 3px 7px;'
                )
        else:
            is_live = hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked()
            mode_tag = 'Listening' if is_live else 'Dictating'
            hint = '✓' if speech_detected or lvl >= 8 else mode_tag
            self.voice_level_badge.setText(f'🎙 {bars} {lvl:2d}% · {hint}')
            if speech_detected or lvl >= 8:
                self.voice_level_badge.setStyleSheet(
                    'font-family: Consolas, monospace; font-size: 11px; font-weight: 700; color: #22c55e; '
                    'background: #11281b; border: 1px solid #22c55e; border-radius: 6px; padding: 3px 7px;'
                )
            else:
                self.voice_level_badge.setStyleSheet(
                    'font-family: Consolas, monospace; font-size: 11px; font-weight: 600; color: #58a6ff; '
                    'background: #132238; border: 1px solid #3b82f6; border-radius: 6px; padding: 3px 7px;'
                )
        self.voice_level_badge.show()
        self._sync_composer_live_bar_visibility()

    def _sync_composer_live_bar_visibility(self):
        if not hasattr(self, 'composer_live_bar'):
            return
        widgets = (
            getattr(self, 'voice_level_badge', None),
            getattr(self, 'voice_brain_btn', None),
            getattr(self, 'voice_tts_btn', None),
            getattr(self, 'voice_mute_btn', None),
            getattr(self, 'end_talk_btn', None),
            getattr(self, 'remove_button', None),
        )
        self.composer_live_bar.setVisible(any(w is not None and not w.isHidden() for w in widgets))

    def _toggle_voice_mute(self, muted: bool):
        sess = getattr(self, '_active_voice_session', None)
        if sess is not None:
            sess.muted = bool(muted)
        if hasattr(self, 'voice_mute_btn'):
            self.voice_mute_btn.setText('🎙 Unmute' if muted else '🔇 Mute')
        if muted:
            try:
                from voice_service import stop_speaking
                stop_speaking()
            except Exception:
                pass
            if hasattr(self, 'voice_level_badge'):
                self.voice_level_badge.setText('🔇 Mic Muted')
                self.voice_level_badge.setStyleSheet(
                    'font-family: Consolas, monospace; font-size: 11px; font-weight: 700; color: #eab308; '
                    'background: #29230f; border: 1px solid #eab308; border-radius: 6px; padding: 3px 7px;'
                )
                self.voice_level_badge.show()
            self.show_notice('🔇 Live microphone muted (Talk Mode paused).')
        else:
            if hasattr(self, 'voice_level_badge'):
                self.voice_level_badge.setText('🎙 ▁▁▁▁▁▁  0% · Listening')
            self.show_notice('🎙 Microphone unmuted — listening.')
        self._sync_composer_live_bar_visibility()

    def stop_all_voice_modes(self, *, exit_talk_only: bool = True, notice: str = '') -> None:
        """Atomically stop all microphone capture, voice playback, and in-flight VoiceCompanion callbacks."""
        self._voice_session_gen = int(getattr(self, '_voice_session_gen', 0)) + 1
        sess = getattr(self, '_active_voice_session', None)
        self._active_voice_session = None
        if sess is not None:
            try:
                sess.stop(discard=True)
            except TypeError:
                try:
                    sess.stop()
                except Exception:
                    pass
            except Exception:
                pass
        try:
            from voice_service import stop_speaking
            stop_speaking()
        except Exception:
            pass
        if hasattr(self, 'live_voice_button'):
            self.live_voice_button.blockSignals(True)
            self.live_voice_button.setChecked(False)
            self.live_voice_button.setText('')
            self.live_voice_button.setIcon(voice_wave_qicon(False))
            self.live_voice_button.setToolTip('Start live hands-free voice chat')
            if hasattr(self, '_live_voice_idle_style'):
                self.live_voice_button.setStyleSheet(self._live_voice_idle_style)
            self.live_voice_button.blockSignals(False)
        if hasattr(self, 'mic_button'):
            self.mic_button.blockSignals(True)
            self.mic_button.setChecked(False)
            self.mic_button.setIcon(mic_qicon(False))
            self.mic_button.blockSignals(False)
        if hasattr(self, 'voice_mute_btn'):
            self.voice_mute_btn.blockSignals(True)
            self.voice_mute_btn.setChecked(False)
            self.voice_mute_btn.setText('🔇 Mute')
            self.voice_mute_btn.hide()
            self.voice_mute_btn.blockSignals(False)
        if hasattr(self, 'voice_level_badge'):
            self.voice_level_badge.hide()
        still_talk = bool(getattr(self, '_talk_only_mode', False)) and (not exit_talk_only)
        if not still_talk:
            if hasattr(self, 'voice_brain_btn'):
                self.voice_brain_btn.hide()
            if hasattr(self, 'voice_tts_btn'):
                self.voice_tts_btn.hide()
        if exit_talk_only:
            if getattr(self, '_talk_only_mode', False):
                self._exit_talk_only_mode(silent=bool(notice), stop_voice=False)
            elif hasattr(self, 'end_talk_btn'):
                self.end_talk_btn.hide()
        else:
            if hasattr(self, 'end_talk_btn') and not getattr(self, '_talk_only_mode', False):
                self.end_talk_btn.hide()
        self._sync_composer_live_bar_visibility()
        self._sync_voice_footer_state()
        if notice:
            self.show_notice(notice)

    def _toggle_voice_dictation(self, recording: bool):
        from voice_service import LiveAudioSession, transcribe_audio_file
        self.mic_button.setIcon(mic_qicon(recording))
        if recording:
            if (hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked()) or getattr(self, '_active_voice_session', None) is not None:
                self.stop_all_voice_modes(exit_talk_only=False)
            sess = LiveAudioSession(
                config_path=self.config_path,
                live_mode=False,
                on_level=self._on_voice_level_update,
            )
            ok, dev_desc = sess.start(self)
            if not ok:
                self.mic_button.blockSignals(True)
                self.mic_button.setChecked(False)
                self.mic_button.setIcon(mic_qicon(False))
                self.mic_button.blockSignals(False)
                self.show_notice(dev_desc)
                return
            self._active_voice_session = sess
            self._on_voice_level_update(0, '▁▁▁▁▁▁', False)
            self.show_notice(f'🎤 Dictating on "{dev_desc}" — speak now (watch the green soundwave bar), then click 🎤 again to insert text.')
        else:
            sess = getattr(self, '_active_voice_session', None)
            self._active_voice_session = None
            if hasattr(self, 'voice_level_badge'):
                self.voice_level_badge.hide()
            self._sync_composer_live_bar_visibility()
            if sess is None:
                return
            wav_p = sess.stop('fairybread_dictation.wav')
            if not wav_p:
                self.show_notice('No audio captured. Try speaking a little longer or check Settings → Voice & Audio.')
                return
            self.show_notice('⏳ Transcribing your voice for all Council AIs…')
            QApplication.processEvents()
            try:
                text = transcribe_audio_file(wav_p)
                cur = self.composer.toPlainText().strip()
                combined = f'{cur} {text}'.strip() if cur else text
                self.composer.setPlainText(combined)
                self.composer.setFocus()
                self.show_notice(f'✓ Heard you: "{text[:80]}"')
            except Exception as exc:
                self.show_notice(f'Voice transcription notice: {exc}')

    def _toggle_live_voice_mode(self, active: bool):
        from voice_service import LiveAudioSession, is_loopback_audio_device
        if active:
            # Always tear down any existing voice/mic session cleanly first so two listeners never coexist
            prev_s = getattr(self, '_active_voice_session', None)
            if prev_s is not None:
                self._active_voice_session = None
                try:
                    prev_s.stop(discard=True)
                except TypeError:
                    prev_s.stop()
                except Exception:
                    pass
            if hasattr(self, 'mic_button') and self.mic_button.isChecked():
                self.mic_button.blockSignals(True)
                self.mic_button.setChecked(False)
                self.mic_button.setIcon(mic_qicon(False))
                self.mic_button.blockSignals(False)
            self._voice_session_gen = int(getattr(self, '_voice_session_gen', 0)) + 1
            sess = LiveAudioSession(
                config_path=self.config_path,
                live_mode=True,
                on_level=self._on_voice_level_update,
                on_utterance_ready=self._on_live_voice_utterance,
                on_error=self._on_voice_capture_error,
                on_barge_in=self._on_voice_barge_in,
            )
            ok, dev_desc = sess.start(self)
            if not ok:
                self.live_voice_button.blockSignals(True)
                self.live_voice_button.setChecked(False)
                self.live_voice_button.setText('')
                self.live_voice_button.setIcon(voice_wave_qicon(False))
                if hasattr(self, '_live_voice_idle_style'):
                    self.live_voice_button.setStyleSheet(self._live_voice_idle_style)
                self.live_voice_button.blockSignals(False)
                self._sync_composer_live_bar_visibility()
                self.show_notice(dev_desc)
                return
            self._active_voice_session = sess
            self.live_voice_button.setIcon(QIcon())
            self.live_voice_button.setText('■')
            self.live_voice_button.setToolTip('Stop Live Voice / Talk Mode')
            if hasattr(self, '_live_voice_active_style'):
                self.live_voice_button.setStyleSheet(self._live_voice_active_style)
            self._refresh_voice_bar_pills()
            if hasattr(self, 'voice_brain_btn'):
                self.voice_brain_btn.show()
            if hasattr(self, 'voice_tts_btn'):
                self.voice_tts_btn.show()
            if hasattr(self, 'voice_mute_btn'):
                self.voice_mute_btn.blockSignals(True)
                self.voice_mute_btn.setChecked(False)
                self.voice_mute_btn.setText('🔇 Mute')
                self.voice_mute_btn.blockSignals(False)
                self.voice_mute_btn.show()
            if hasattr(self, 'end_talk_btn'):
                self.end_talk_btn.show()
            self._on_voice_level_update(0, '▁▁▁▁▁▁', False)
            self._sync_voice_footer_state()
            if is_loopback_audio_device(dev_desc):
                self.show_notice(
                    f'⚠ Live Voice opened "{dev_desc}" (speaker loopback, NOT a mic!). Open Settings → Voice & Audio to pick System default.'
                )
            else:
                self.show_notice(
                    f'🟢 Live Voice ON ({dev_desc}) — Switch 🧠 Thinking AI or 🔊 Voice anytime · Click ■ or ✕ End Talk to stop.'
                )
        else:
            self.stop_all_voice_modes(exit_talk_only=True, notice='Live Voice / Talk Mode turned OFF.')

    def _get_voice_companion(self):
        if getattr(self, '_voice_companion', None) is None:
            from voice_companion import VoiceCompanion
            self._voice_companion = VoiceCompanion(config_path=self.config_path)
        return self._voice_companion

    def _recent_voice_context_snippet(self) -> str:
        recent_lines = []
        for it in (self.chat_items or [])[-4:]:
            r_tag = 'User' if it.get('role') == 'user' else 'Assistant'
            recent_lines.append(f"{r_tag}: {str(it.get('content') or '')[:180]}")
        return '\n'.join(recent_lines)

    def _search_voice_memory_context(self, query_hint: str = '') -> tuple[str, bool]:
        is_no_history = self.no_history_btn.isChecked() or (not self.history_toggle.isChecked())
        if is_no_history:
            return '', False
        try:
            res = MemoryService(db_path=self._memory_db_path()).search(query_hint or 'user preferences and projects')
            return (res.context if res.succeeded else ''), True
        except Exception:
            return '', True

    def _save_voice_memories(self, memory_saves: list[dict], *, author: str = 'voice_companion') -> list[dict]:
        if not memory_saves:
            return []
        is_no_history = self.no_history_btn.isChecked() or (not self.history_toggle.isChecked())
        if is_no_history:
            return []
        saved: list[dict] = []
        try:
            mem_svc = MemoryService(db_path=self._memory_db_path())
            proj_name = self._current_project_name()
            for item in memory_saves:
                if not isinstance(item, dict):
                    continue
                fact = str(item.get('fact') or item.get('body') or item.get('summary') or '').strip()
                summary = str(item.get('summary') or '').strip() or (fact[:97] + '...' if len(fact) > 100 else fact)
                if not summary or not fact:
                    continue
                mem_type = str(item.get('memory_type') or 'standing').strip().lower() or 'standing'
                mid = mem_svc.index.upsert(
                    summary=summary[:140],
                    body=fact,
                    wing=mem_svc.wing,
                    room=self.session_id or 'general',
                    project=str(item.get('project') or proj_name or ''),
                    memory_type=mem_type,
                    visibility='private',
                    source={'kind': 'voice_companion_save', 'session_id': self.session_id, 'author': author},
                )
                saved.append({'id': mid, 'summary': summary[:140], 'fact': fact})
            if saved:
                if hasattr(self, 'memory_panel') and self.memory_panel.isVisible():
                    self.refresh_memory_review(True)
                else:
                    self._update_durable_memory_count()
        except Exception:
            pass
        return saved

    def _persist_voice_exchange(self, user_text: str, reply_text: str, provider_used: str = '') -> None:
        is_no_history = self.no_history_btn.isChecked() or (not self.history_toggle.isChecked())
        if is_no_history:
            return
        try:
            ctx = self.store.context(self.session_id)
            contribs = (
                [provider_used]
                if provider_used and provider_used not in {'local', 'fallback'}
                else []
            )
            ctx.append_exchange(
                user_text,
                reply_text,
                contributors=contribs,
                answer_speaker_id='voice_companion',
                answer_phase='voice_chat',
            )
            self.store.rename_from_question(self.session_id, user_text.lstrip('🎙 ').strip() or user_text)
            self.refresh_projects()
            self.refresh_sessions()
        except OSError:
            pass
        try:
            clean_u = user_text.lstrip('🎙 ').strip() or user_text
            MemoryService(db_path=self._memory_db_path()).remember_exchange(
                clean_u,
                reply_text,
                session_id=self.session_id,
                project=self._current_project_name(),
                contributors=[provider_used] if provider_used and provider_used not in {'local', 'fallback'} else ['voice_companion'],
            )
            if hasattr(self, 'memory_panel') and self.memory_panel.isVisible():
                self.refresh_memory_review(True)
            else:
                self._update_durable_memory_count()
        except Exception:
            pass

    def _deliver_voice_companion_reply(
        self,
        *,
        user_disp: str,
        raw_user_for_store: str,
        disp_reply: str,
        spoken_reply: str,
        decision: Any,
        req_gen: int,
        append_user_msg: bool = False,
        persist_exchange: bool = True,
        speak_aloud: bool = True,
    ) -> int:
        """Render, persist, and speak a Voice Companion reply with explicit 🧠 Thinking & 🔊 Speaking attribution."""
        prov = str(getattr(decision, 'provider_used', '') or '').strip()
        model_used = str(getattr(decision, 'model_used', '') or '').strip()
        req_p = str(getattr(decision, 'requested_provider', '') or '').strip()
        fell_back = bool(getattr(decision, 'fell_back', False))
        fb_reason = str(getattr(decision, 'fallback_reason', '') or '').strip()
        prev_p = str(getattr(self, '_last_voice_brain_provider', '') or '').strip()
        valid_prov = prov if prov and prov not in {'local', 'fallback', 'injected'} else ''

        self._last_voice_brain_fell_back = bool(fell_back)
        self._last_voice_brain_requested = req_p or ''
        if valid_prov:
            self._last_voice_brain_provider = valid_prov
            self._refresh_voice_bar_pills()
            self._sync_voice_footer_state()

        if append_user_msg:
            self.append_message('user', user_disp, render=False)

        if fell_back and valid_prov:
            req_disp = provider_display_name(req_p) if req_p and req_p != 'auto' else 'Primary AI'
            why = f' ({fb_reason[:110]})' if fb_reason else ''
            st_msg = f'Status: {req_disp} failed{why} — switched Thinking AI to {provider_display_name(valid_prov)}.'
            self.append_status_message(st_msg, severity='error', icon_prefix='⚠ 🧠', force=True, render=False)
            self.show_notice(f'⚠ 🧠 {req_disp} unavailable → {provider_display_name(valid_prov)}')
        elif fell_back and fb_reason:
            req_disp = provider_display_name(req_p) if req_p and req_p != 'auto' else 'Thinking AI'
            st_msg = f'Status: {req_disp} failed ({fb_reason[:110]}).'
            self.append_status_message(st_msg, severity='error', icon_prefix='⚠ 🧠', force=True, render=False)
        elif prev_p and valid_prov and prev_p != valid_prov:
            st_msg = f'Status: Thinking AI switched from {provider_display_name(prev_p)} to {provider_display_name(valid_prov)}.'
            self.append_status_message(st_msg, severity='info', icon_prefix='⇄ 🧠', force=True, render=False)
            self.show_notice(f'⇄ 🧠 Thinking AI: {provider_display_name(prev_p)} → {provider_display_name(valid_prov)}')

        asst_idx = self.append_message(
            'assistant',
            disp_reply,
            speaker='voice_companion',
            contributors=[valid_prov] if valid_prov else [],
            model_id=model_used,
            handoff_banner='',
            render=True,
        )

        if speak_aloud and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            from voice_service import TTS_ENGINE_SHORT_LABELS, speak_agent_response

            def _on_tts_meta(meta: dict, idx=asst_idx, g=req_gen):
                def _apply():
                    if g != int(getattr(self, '_voice_session_gen', 0)) or idx >= len(self.chat_items):
                        return
                    eng_lbl = str(meta.get('engine_label') or '')
                    v_lbl = str(meta.get('voice_label') or '')
                    tts_full = f'{eng_lbl} ({v_lbl})'.strip() if v_lbl else eng_lbl
                    fb_txt = ''
                    if meta.get('fell_back'):
                        req_e = str(meta.get('requested_engine') or 'Primary voice')
                        req_e_disp = TTS_ENGINE_SHORT_LABELS.get(req_e, req_e.title())
                        fb_why = str(meta.get('fallback_reason') or 'error').strip()
                        fb_txt = f'fallback from {req_e_disp}: {fb_why}'
                        self.show_notice(f'⚠ 🔊 Speech fell back to {tts_full} ({fb_why})')
                        self.append_status_message(
                            f'Status: {req_e_disp} voice failed ({fb_why[:110]}) — switched voice to {tts_full}.',
                            severity='error',
                            icon_prefix='⚠ 🔊',
                            force=True,
                            render=False,
                        )
                    self.chat_items[idx]['tts_label'] = tts_full
                    self.chat_items[idx]['tts_fallback_note'] = fb_txt
                    for _ck in [k for k in list(getattr(self, '_item_html_cache', {})) if isinstance(k, tuple) and k and k[0] == idx]:
                        self._item_html_cache.pop(_ck, None)
                    self._refresh_voice_bar_pills(active_tts_label=eng_lbl, tts_fell_back=bool(meta.get('fell_back')))
                    self._render_chat_items()

                QTimer.singleShot(0, _apply)

            def _on_tts_err(err_m: str, g=req_gen):
                def _apply_err():
                    if g != int(getattr(self, '_voice_session_gen', 0)):
                        return
                    self.show_notice(f'🔇 Voice playback failed: {err_m}')
                    self.append_status_message(
                        f'Status: Voice playback failed — {str(err_m or "audio error")[:140]}.',
                        severity='error',
                        icon_prefix='✕ 🔊',
                        force=True,
                        render=True,
                    )

                QTimer.singleShot(0, _apply_err)

            speak_agent_response(
                spoken_reply,
                config_path=self.config_path,
                on_speech_meta=_on_tts_meta,
                on_error=_on_tts_err,
            )

        if persist_exchange:
            self._persist_voice_exchange(
                raw_user_for_store,
                disp_reply,
                provider_used=prov,
            )
        return asst_idx

    def _on_live_voice_utterance(self, wav_path: Path):
        from voice_service import load_voice_settings, speak_agent_response

        v_cfg = load_voice_settings(self.config_path)
        talk_only = bool(getattr(self, '_talk_only_mode', False))
        companion_on = True if talk_only else bool(v_cfg.get('voice_companion_enabled', True))
        req_gen = int(getattr(self, '_voice_session_gen', 0))
        if hasattr(self, 'voice_level_badge'):
            self.voice_level_badge.setText(
                '⏳ Talk Mode listening…' if talk_only else ('⏳ Listening & thinking…' if companion_on else '⏳ Transcribing spoken prompt…')
            )

        recent_snip = self._recent_voice_context_snippet()
        mem_ctx, allow_mem_write = self._search_voice_memory_context(
            recent_snip or str(getattr(self, 'last_question', '') or '') or 'user preferences and facts'
        )

        worker = VoiceCompanionWorker(
            wav_path,
            self._get_voice_companion() if companion_on else None,
            companion_enabled=companion_on,
            talk_only=talk_only,
            background_busy=(self.worker is not None),
            background_status=str(getattr(self, 'pending_status_text', '') or ''),
            background_question=str(getattr(self, 'last_question', '') or ''),
            recent_chat_snippet=recent_snip,
            memory_context=mem_ctx,
            allow_memory_write=allow_mem_write,
            session_gen=req_gen,
            memory_db_path=self._memory_db_path(),
            parent=self,
        )
        self._voice_threads.append(worker)

        def _cleanup_vw():
            try:
                if worker in self._voice_threads:
                    self._voice_threads.remove(worker)
            except Exception:
                pass
            worker.deleteLater()

        def _on_vw_done(decision, transcript: str, gen=req_gen):
            if gen != int(getattr(self, '_voice_session_gen', 0)):
                return
            text = (transcript or '').strip()
            if not text:
                return
            if decision is None:
                self.composer.setPlainText(text)
                if self.worker is None:
                    self._turn_triggered_by_live_voice = True
                    self.send_message()
                else:
                    self.queue_next_turn()
                return

            saved_mems = self._save_voice_memories(
                list(getattr(decision, 'memory_saves', None) or []),
                author=getattr(decision, 'provider_used', '') or 'voice_companion',
            )
            disp_reply = decision.spoken_reply
            if saved_mems:
                badges = ' · '.join(f'🧠 Saved: "{m["summary"]}"' for m in saved_mems)
                disp_reply = f'{disp_reply}\n\n{badges}'

            user_disp = f'🎙 {text}'
            self._deliver_voice_companion_reply(
                user_disp=user_disp,
                raw_user_for_store=user_disp,
                disp_reply=disp_reply,
                spoken_reply=decision.spoken_reply,
                decision=decision,
                req_gen=gen,
                append_user_msg=True,
                persist_exchange=bool(talk_only or decision.action != 'delegate'),
                speak_aloud=True,
            )

            if (not talk_only) and decision.action == 'delegate' and decision.delegated_task:
                task_text = decision.delegated_task.strip()
                active_cnt = sum(1 for v in (getattr(self, 'provider_states', {}) or {}).values() if v is True)
                if self.worker is None:
                    self.append_status_message(
                        f'Status: Handed task to AI team ({active_cnt} AIs) — keep talking while they work.',
                        severity='info',
                        icon_prefix='⚡',
                        force=True,
                        render=True,
                    )
                    draft_backup = self.composer.toPlainText()
                    self._background_delegated_from_voice = True
                    self._turn_triggered_by_live_voice = True
                    self.composer.setPlainText(task_text)
                    self.send_message()
                    if draft_backup and draft_backup.strip() != task_text:
                        self.composer.setPlainText(draft_backup)
                    self.show_notice(f'🎙 Voice Companion handed task to AI team in background: "{task_text[:65]}"')
                else:
                    if not hasattr(self, 'queued_prompts'):
                        self.queued_prompts = []
                    self.queued_prompts.append(task_text)
                    if hasattr(self, 'steer_button'):
                        self.steer_button.setText(f'⏳ Queued ({len(self.queued_prompts)}) ▾')
                        self.steer_button.setStyleSheet(
                            'QPushButton { background: #29230f; color: #eab308; border: 1px solid #eab308; '
                            'padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 700; }'
                        )
                    self.append_status_message(
                        f'Status: Queued task #{len(self.queued_prompts)} for AI team.',
                        severity='info',
                        icon_prefix='⏳',
                        force=True,
                        render=True,
                    )
                    self.show_notice(f'🎙 Voice Companion queued next task ({len(self.queued_prompts)}): "{task_text[:60]}"')

            elif (not talk_only) and decision.action == 'steer' and decision.steer_note and self.worker is not None:
                note = decision.steer_note.strip()
                if getattr(self, 'active_steering_state', None) is None:
                    self.active_steering_state = {'notes': [], 'include_palace_code': self.palace_code_btn.isChecked()}
                self.active_steering_state.setdefault('notes', []).append(note)
                cnt = len(self.active_steering_state['notes'])
                if hasattr(self, 'steer_button'):
                    self.steer_button.setText(f'🧭 Steer ({cnt}) ▾')
                    self.steer_button.setStyleSheet(
                        'QPushButton { background: #132238; color: #58a6ff; border: 1px solid #3b82f6; '
                        'padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 700; }'
                    )
                self.append_message('user', f'[LIVE STEER #{cnt}]: {note}', render=False)
                self.append_status_message(
                    f'Status: Sent live steer note #{cnt} to working AI team.',
                    severity='info',
                    icon_prefix='🧭',
                    force=True,
                    render=True,
                )
                self.show_notice(f'✓ Voice Companion injected Live Steer #{cnt}: "{note[:60]}"')

        def _on_vw_failed(err: str, g=req_gen):
            if g != int(getattr(self, '_voice_session_gen', 0)):
                return
            self.show_notice(f'Live Voice notice: {err}')
            self.append_status_message(
                f'Status: Voice turn failed — {str(err or "error")[:140]}.',
                severity='error',
                icon_prefix='✕ 🎙',
                force=True,
                render=True,
            )

        worker.completed.connect(_on_vw_done)
        worker.failed.connect(_on_vw_failed)
        worker.finished.connect(_cleanup_vw)
        worker.start()

    def load_history(self):
        if getattr(self, '_voice_companion', None) is not None:
            self._voice_companion.reset()
        self._last_voice_brain_provider = ''
        self._last_voice_brain_fell_back = False
        self._last_voice_brain_requested = ''
        self._pending_workspace_actions = []
        if hasattr(self, 'approval_banner'):
            self.approval_banner.hide()
        try:
            from cost_service import ConversationCostLedger
            raw_ledger = self.store.get_cost_ledger(self.session_id) if hasattr(self.store, 'get_cost_ledger') else {}
            self._cost_ledger = ConversationCostLedger.from_dict(raw_ledger)
            self._refresh_bottom_cost_label()
        except Exception:
            pass
        self.chat.clear()
        self.last_answer = ''
        self.reply_archive = []
        self.chat_items = []
        self._item_html_cache = {}
        self.expanded_deliberations = set()
        self.conversation_contributors = []
        self.copy_button.setEnabled(False)
        try:
            messages = self.store.messages(self.session_id)
            pending_speakers = []
            for message in messages:
                role = message.get('role')
                speaker = message.get('speaker_id')
                phase = message.get('phase')
                msg_contribs = message.get('contributors') or []
                if speaker and speaker not in {'user', 'assistant', 'palace', 'voice_companion'} and speaker not in self.conversation_contributors:
                    self.conversation_contributors.append(speaker)
                for c in msg_contribs:
                    if c and c not in self.conversation_contributors:
                        self.conversation_contributors.append(c)

                if role == 'user':
                    self.append_message('user', message['content'], timestamp=message.get('timestamp'), render=False)
                elif phase in {'initial', 'peer_reply'} and speaker not in {'assistant', 'palace'}:
                    pending_speakers.append(message)
                else:
                    if speaker == 'voice_companion' and msg_contribs:
                        last_vc_p = str(msg_contribs[0] or '').strip()
                        if last_vc_p and last_vc_p not in {'local', 'fallback', 'injected'}:
                            self._last_voice_brain_provider = last_vc_p
                    self.append_message(
                        'assistant',
                        message['content'],
                        speaker=speaker,
                        phase=phase,
                        contributors=msg_contribs,
                        speaker_messages=list(pending_speakers),
                        timestamp=message.get('timestamp'),
                        model_id=str(message.get('model_id') or ''),
                        render=False,
                    )
                    pending_speakers.clear()
                    self.last_answer = message['content']

            if pending_speakers:
                # Fallback if a legacy/partial transcript had speaker turns without a synthesis turn
                for msg in pending_speakers:
                    self.append_message(
                        'assistant',
                        msg['content'],
                        speaker=msg.get('speaker_id'),
                        phase=msg.get('phase'),
                        timestamp=msg.get('timestamp'),
                        render=False,
                    )
                    self.last_answer = msg['content']

            self.copy_button.setEnabled(bool(self.last_answer))
            if not messages:
                self.chat.setHtml(
                    '<div style="margin-top:48px; color:#e6edf7; font-size:20px; font-weight:600;">What are we working on?</div>'
                    '<p style="color:#8b949e; font-size:13px; margin-top:6px;">'
                    'Ask anything, paste text or screenshots (Ctrl+V), or drag &amp; drop documents and pictures.<br>'
                    'Create Projects in the left sidebar without needing a disk folder.'
                    '</p>'
                )
            else:
                self._render_chat_items()
        except (OSError, ValueError) as exc:
            self.show_notice(f'Could not load history: {exc}')

    def append_message(
        self,
        role,
        content,
        speaker=None,
        phase=None,
        contributors=None,
        speaker_messages=None,
        timestamp=None,
        render: bool = True,
        model_id: str = '',
        tts_label: str = '',
        tts_fallback_note: str = '',
        handoff_banner: str = '',
    ) -> int:
        item_idx = len(self.chat_items)
        import time as _t
        self.chat_items.append({
            'idx': item_idx,
            'role': role,
            'content': content,
            'speaker': speaker,
            'phase': phase,
            'contributors': list(contributors or []),
            'speaker_messages': list(speaker_messages or []),
            'timestamp': timestamp or _t.strftime('%Y-%m-%dT%H:%M:%S'),
            'model_id': str(model_id or ''),
            'tts_label': str(tts_label or ''),
            'tts_fallback_note': str(tts_fallback_note or ''),
            'handoff_banner': str(handoff_banner or ''),
        })
        if role not in {'user', 'system_status'}:
            self.reply_archive.append(content)
        if render:
            self._render_chat_items()
        return item_idx

    def append_status_message(
        self,
        text: str,
        *,
        severity: str = 'error',
        icon_prefix: str = '',
        force: bool = False,
        render: bool = True,
    ) -> int | None:
        """Append a UI-only inline chat status message (never written to session history or memory.db)."""
        clean = str(text or '').strip()
        if not clean:
            return None
        if not force:
            try:
                from palace_config import load_agent_defaults
                if not bool(load_agent_defaults(self.config_path).get('show_inline_status_messages', True)):
                    return None
            except Exception:
                pass
        item_idx = len(self.chat_items)
        import time as _t
        self.chat_items.append({
            'idx': item_idx,
            'role': 'system_status',
            'content': clean,
            'severity': str(severity or 'error').strip().lower(),
            'icon_prefix': str(icon_prefix or '').strip(),
            'speaker': None,
            'phase': None,
            'contributors': [],
            'speaker_messages': [],
            'timestamp': _t.strftime('%Y-%m-%dT%H:%M:%S'),
            'model_id': '',
            'tts_label': '',
            'tts_fallback_note': '',
            'handoff_banner': '',
        })
        if render:
            self._render_chat_items()
        return item_idx

    def _check_external_session_updates(self):
        """Watch active session file on disk so external Foreman/CLI prompts appear live in the open GUI."""
        if self.worker is not None or bool(getattr(self, '_voice_threads', None)):
            return
        try:
            ctx = self.store.context(self.session_id)
            path = getattr(ctx, 'path', None)
            if path and path.exists():
                mtime = path.stat().st_mtime
                if self._last_session_mtime == 0.0:
                    self._last_session_mtime = mtime
                elif mtime > self._last_session_mtime:
                    self._last_session_mtime = mtime
                    self.refresh_sessions()
                    self.load_history()
                    self.status_label.setText('Live update received from Foreman / Council.')
        except Exception:
            pass

    def _render_single_chat_item(self, item: dict, *, theme_dict: dict | None = None) -> str:
        role = item['role']
        content = item['content']
        speaker = item.get('speaker')
        phase = item.get('phase')
        contributors = item.get('contributors') or []
        speaker_messages = item.get('speaker_messages') or []
        item_idx = item['idx']

        t_dict = theme_dict if theme_dict is not None else load_theme_dict(getattr(self, 'active_theme', 'dark'))
        user_txt_col = str(t_dict.get('user_bubble_text', '#f0f6fc'))
        if role == 'system_status':
            st_style = str(getattr(self, '_cached_status_style', 'text') or 'text').lower()
            sev = str(item.get('severity') or 'error').lower()
            is_light = _is_light_theme(t_dict)
            if sev == 'info':
                col = '#475569' if is_light else '#7aa2c9'
                bg_tint = '#eef2f7' if is_light else '#132238'
            else:
                col = '#991b1b' if is_light else '#e06c75'
                bg_tint = '#fee2e2' if is_light else '#2a1619'
            safe_st = html.escape(content).replace('\n', '<br>')
            if st_style == 'icons':
                pfx = str(item.get('icon_prefix') or ('ℹ' if sev == 'info' else '⚠')).strip()
                lbl_txt = f'{html.escape(pfx)}&nbsp;&nbsp;{safe_st}' if pfx else safe_st
                return (
                    f'<div style="margin:6px 4px; padding:4px 8px; background:{bg_tint}; '
                    f'border-left:2px solid {col}; border-radius:4px; color:{col}; '
                    f'font-size:11.5px; line-height:1.4;">{lbl_txt}</div>'
                )
            return (
                f'<div style="margin:5px 6px 3px 6px; color:{col}; font-style:italic; '
                f'font-size:11.5px; line-height:1.4;">{safe_st}</div>'
            )

        if role == 'user':
            import urllib.parse
            from attachment_service import parse_user_message_attachments
            clean_user_text, user_atts = parse_user_message_attachments(content)
            safe_user = html.escape(clean_user_text).replace('\n', '<br>')
            att_rows_html = ''
            for att in user_atts:
                a_kind = att.get('kind', 'text')
                a_name = att.get('name', 'Attached file')
                a_path = att.get('path', '')
                safe_a_name = html.escape(a_name)
                if a_kind == 'image' and a_path and Path(a_path).exists():
                    img_url = Path(a_path).as_uri()
                    enc_path = urllib.parse.quote(a_path)
                    att_rows_html += (
                        f'<tr><td align="right" style="padding-bottom:6px;">'
                        f'<a href="open-img:{enc_path}" style="text-decoration:none;" title="Click to view {safe_a_name}">'
                        f'<img src="{img_url}" width="160" />'
                        f'</a>'
                        f'</td></tr>'
                    )
                else:
                    icon_chr = '🖼' if a_kind == 'image' else '📄'
                    if a_path and Path(a_path).exists():
                        enc_path = urllib.parse.quote(a_path)
                        pill_inner = (
                            f'<a href="reveal-file:{enc_path}" style="color:#e6edf3; text-decoration:none; font-weight:600;" '
                            f'title="Click to reveal {safe_a_name} in Explorer">{icon_chr}&nbsp;&nbsp;{safe_a_name}</a>'
                        )
                    else:
                        pill_inner = f'<span style="color:#e6edf3; font-weight:600;">{icon_chr}&nbsp;&nbsp;{safe_a_name}</span>'
                    att_rows_html += (
                        f'<tr><td align="right" style="padding-bottom:6px;">'
                        f'<table cellspacing="0" cellpadding="0" style="background:#21262d; border:1px solid #30363d; border-radius:12px;">'
                        f'<tr><td style="padding:5px 12px; font-size:12.5px;">{pill_inner}</td></tr>'
                        f'</table>'
                        f'</td></tr>'
                    )
            text_row_html = (
                f'<tr><td style="text-align:left; color:{user_txt_col}; font-size:13.5px; line-height:1.48;">'
                f'{safe_user}'
                f'</td></tr>'
            ) if safe_user.strip() else ''
            ts_str = format_time_only(item.get('timestamp'))
            ts_row = f'<tr><td align="right" style="color:#8b949e; font-size:11px; padding-top:4px; padding-right:2px;">{ts_str}</td></tr>' if ts_str else ''
            return (
                f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:20px; margin-bottom:16px;">'
                f'<tr><td width="26%"></td>'
                f'<td align="right">'
                f'<table cellspacing="0" cellpadding="0" style="background:transparent; border:none;">'
                f'{att_rows_html}'
                f'{text_row_html}'
                f'{ts_row}'
                f'</table>'
                f'</td>'
                f'<td width="20"></td></tr></table>'
            )

        safe = html.escape(content).replace('\n', '<br>')

        if speaker == 'voice_companion':
            active_contribs = [c for c in (contributors or []) if c and c not in {'voice_companion', 'local', 'fallback'}]
            meta_tag = f'VOICE COMPANION · {active_contribs[0].upper()}' if active_contribs else 'VOICE COMPANION'
        elif speaker and speaker not in {'assistant', 'palace'}:
            active_contribs = [speaker]
            phase_tag = ' (PEER REPLY)' if phase == 'peer_reply' else ''
            meta_tag = f'{speaker.upper()}{phase_tag}'
        else:
            active_contribs = contributors or self.conversation_contributors or [
                name for name, en in self.provider_states.items() if en is True
            ]
            meta_tag = 'PALACE'

        handoff_banner_html = ''
        raw_handoff = str(item.get('handoff_banner') or '').strip()
        if raw_handoff:
            is_warn = raw_handoff.startswith('⚠')
            hb_col = '#eab308' if is_warn else '#58a6ff'
            hb_bg = '#29230f' if is_warn else '#132238'
            handoff_banner_html = (
                f'<div style="background:{hb_bg}; border-left:3px solid {hb_col}; color:{hb_col}; '
                f'font-size:11.5px; font-weight:600; padding:4px 8px; margin-bottom:8px; border-radius:4px;">'
                f'{html.escape(raw_handoff)}</div>'
            )

        chat_mode = getattr(self, 'badge_display_mode', 'icons_only')
        if speaker == 'voice_companion':
            m_str = str(item.get('model_id') or '').strip()
            t_lbl = str(item.get('tts_label') or '').strip()
            t_fb = str(item.get('tts_fallback_note') or '').strip()
            if active_contribs:
                c0 = active_contribs[0]
                m_part = f' <span style="color:#8b949e; font-weight:500;">({html.escape(m_str)})</span>' if m_str else ''
                brain_part = (
                    f'<span style="color:{provider_color(c0)}; font-size:12px; font-weight:700;" '
                    f'title="Thinking AI: {html.escape(provider_display_name(c0))}">'
                    f'🧠 {provider_icon(c0)} {html.escape(provider_display_name(c0))}{m_part}</span>'
                )
            else:
                brain_part = '<span style="color:#38bdf8; font-size:12px; font-weight:600;" title="Thinking AI: Voice Companion">🧠 Voice Companion</span>'
            if t_lbl:
                if t_fb:
                    spk_part = (
                        f' &nbsp;·&nbsp; <span style="color:#eab308; font-size:11.5px; font-weight:600;" '
                        f'title="{html.escape(t_fb)}">⚠ 🔊 {html.escape(t_lbl)} ({html.escape(t_fb)})</span>'
                    )
                else:
                    spk_part = f' &nbsp;·&nbsp; <span style="color:#8b949e; font-size:11.5px;" title="Speaking Voice">🔊 {html.escape(t_lbl)}</span>'
            else:
                spk_part = ''
            badges_html = f'{brain_part}{spk_part}'
        elif active_contribs:
            if chat_mode == 'names_only':
                badges_html = '&nbsp;&nbsp;'.join(
                    f'<span style="color:{provider_color(c)}; font-size:12px; font-weight:600;" '
                    f'title="{html.escape(provider_display_name(c))}">'
                    f'{html.escape(provider_display_name(c))}</span>'
                    for c in active_contribs
                )
            elif chat_mode == 'icons_and_names':
                badges_html = '&nbsp;&nbsp;'.join(
                    f'<span style="color:{provider_color(c)}; font-size:12px; font-weight:600;" '
                    f'title="{html.escape(provider_display_name(c))}">'
                    f'{provider_icon(c)} {html.escape(provider_display_name(c))}</span>'
                    for c in active_contribs
                )
            else:
                # Default: icons ONLY under the combined reply
                badges_html = '&nbsp;&nbsp;&nbsp;'.join(
                    f'<span style="color:{provider_color(c)}; font-size:13.5px; font-weight:700;" '
                    f'title="{html.escape(provider_display_name(c))}">'
                    f'{provider_icon(c)}</span>'
                    for c in active_contribs
                )
        else:
            badges_html = '<span style="color:#3b82f6; font-size:13.5px;" title="Palace">◆</span>'

        # Understated ChatGPT/Antigravity-style collapsible thinking line ("Worked across N AIs · Peer deliberation ›")
        delib_html = ''
        expanded_steps_html = ''
        if speaker_messages:
            is_open = item_idx in self.expanded_deliberations
            arrow = '⌄' if is_open else '›'
            step_count = len(speaker_messages)
            has_peer = any(m.get('phase') == 'peer_reply' for m in speaker_messages)
            mode_label = 'Peer deliberation' if has_peer else 'Individual AI responses'
            action_hint = 'Hide thinking' if is_open else f'{step_count} steps · Show thinking'
            delib_html = (
                f'<div style="padding-bottom:6px; margin-bottom:8px; border-bottom:1px solid #161b22;">'
                f'<a href="toggle-peer:{item_idx}" style="color:#8b949e; text-decoration:none; font-size:12px; font-weight:500;">'
                f'Worked across {len(active_contribs)} AIs · {mode_label} '
                f'<span style="color:#6e7681;">({action_hint})</span> {arrow}</a>'
                f'</div>'
            )
            if is_open:
                step_blocks = []
                for msg in speaker_messages:
                    sp = str(msg.get('speaker_id') or msg.get('provider_id') or 'ai')
                    ph = msg.get('phase')
                    ph_label = f'{sp.upper()} (PEER REPLY)' if ph == 'peer_reply' else sp.upper()
                    sp_color = provider_color(sp)
                    sp_icon = provider_icon(sp)
                    sp_text = format_markdown_and_drawings(str(msg.get('content', '')))
                    step_blocks.append(
                        f'<table width="100%" cellspacing="0" cellpadding="8" style="margin-top:6px; background:#0d1117; border-left:2px solid {sp_color};">'
                        f'<tr><td>'
                        f'<div style="color:{sp_color}; font-size:11px; font-weight:700;">{sp_icon} {html.escape(ph_label)}</div>'
                        f'<div style="color:#c9d1d9; font-size:12.5px; margin-top:3px; line-height:1.45;">{sp_text}</div>'
                        f'</td></tr></table>'
                    )
                expanded_steps_html = (
                    f'<div style="margin-top:6px; margin-bottom:10px;">'
                    f'{"".join(step_blocks)}'
                    f'</div>'
                )
            else:
                hidden_tags = ' · '.join(
                    f'{str(m.get("speaker_id", "")).upper()} (PEER REPLY)'
                    if m.get('phase') == 'peer_reply'
                    else str(m.get('speaker_id', '')).upper()
                    for m in speaker_messages
                )
                meta_tag = f'{hidden_tags} · {meta_tag}'.strip(' ·')

        rendered_body = format_markdown_and_drawings(content)
        test_meta_html = ''
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
            test_meta_html = f'<div style="font-size:1px; color:#0b0d10;">{html.escape(meta_tag)}</div>'

        reply_idx = max(0, len(self.reply_archive) - 1)
        ts_str = format_time_only(item.get('timestamp'))
        ts_tag = f'&nbsp;&nbsp;<span style="color:#8b949e; font-size:11px;">· {ts_str}</span>' if ts_str else ''
        actions_row_html = (
            f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px; border-top:1px solid #161b22; padding-top:6px;">'
            f'<tr>'
            f'<td align="left" style="vertical-align:middle;">{badges_html}{ts_tag}</td>'
            f'<td align="right" style="vertical-align:middle; margin-right:6px; color:#6e7681; font-size:11.5px;">'
            f'<a href="speak:{reply_idx}" style="color:#6e7681; text-decoration:none;" title="Read response aloud">🔊 Speak</a>'
            f'&nbsp;&nbsp;&nbsp;&nbsp;'
            f'<a href="copy:{reply_idx}" style="color:#6e7681; text-decoration:none;" title="Copy reply">⧉ Copy</a>'
            f'&nbsp;&nbsp;&nbsp;&nbsp;'
            f'<a href="up:{reply_idx}" style="color:#6e7681; text-decoration:none;" title="Helpful">↑ Helpful</a>'
            f'&nbsp;&nbsp;&nbsp;&nbsp;'
            f'<a href="down:{reply_idx}" style="color:#6e7681; text-decoration:none;" title="Needs improvement">↓ Unhelpful</a>'
            f'</td>'
            f'</tr></table>'
        )

        return (
            f'<div style="margin-top:16px; margin-bottom:10px; padding:4px 2px;">'
            f'{handoff_banner_html}'
            f'{delib_html}'
            f'{expanded_steps_html}'
            f'<div style="color:#e6edf3; font-size:13.5px; line-height:1.6;">{rendered_body}</div>'
            f'{actions_row_html}'
            f'{test_meta_html}'
            f'</div>'
        )

    def _update_inline_status_banner(self):
        if not hasattr(self, 'inline_status_label'):
            return
        if not self.pending_status_text:
            self.inline_status_label.hide()
            return
        pulse_colors = ['#6e7681', '#8b949e', '#c9d1d9', '#3b82f6', '#c9d1d9', '#8b949e']
        col = pulse_colors[self.pulse_step % len(pulse_colors)]
        dots = '.' * ((self.pulse_step % 3) + 1)
        safe_status = html.escape(self.pending_status_text)
        self.inline_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.inline_status_label.setText(
            f'<span style="color:{col}; font-weight:600;">● {safe_status}{dots}</span>'
        )
        self.inline_status_label.show()

    def _get_cached_status_style(self) -> str:
        try:
            cfg_p = Path(self.config_path)
            cur_mtime = cfg_p.stat().st_mtime_ns if cfg_p.exists() else None
        except OSError:
            cur_mtime = None
        if cur_mtime is not None and cur_mtime == getattr(self, '_status_style_cfg_mtime', None):
            return str(getattr(self, '_cached_status_style', 'text') or 'text').lower()
        try:
            from voice_service import load_voice_settings
            style = str(load_voice_settings(self.config_path).get('status_notification_style', 'text') or 'text').lower()
        except Exception:
            style = 'text'
        self._status_style_cfg_mtime = cur_mtime
        self._cached_status_style = style
        return style

    def _render_chat_items(self, scroll_to_bottom: bool = True):
        self._update_inline_status_banner()
        self._cached_status_style = self._get_cached_status_style()
        if not self.chat_items:
            self.chat.clear()
            return
        t_dict = load_theme_dict(getattr(self, 'active_theme', 'dark'))
        scrollbar = self.chat.verticalScrollBar()
        prev_val = scrollbar.value() if scrollbar else 0
        html_blocks = []
        for i, item in enumerate(self.chat_items):
            curr_ts = item.get('timestamp')
            prev_ts = self.chat_items[i - 1].get('timestamp') if i > 0 else None
            if curr_ts:
                try:
                    dt_curr = _parse_local_naive_dt(curr_ts)
                    show_sep = False
                    if not prev_ts:
                        show_sep = True
                    else:
                        dt_prev = _parse_local_naive_dt(prev_ts)
                        if (dt_curr - dt_prev).total_seconds() > 1800 or dt_curr.date() != dt_prev.date():
                            show_sep = True
                    if show_sep:
                        sep_txt = format_chat_timestamp(curr_ts)
                        html_blocks.append(
                            f'<div align="center" style="margin:24px 0 14px; font-size:11px; font-weight:600; color:#8b949e;">'
                            f'{sep_txt}'
                            f'</div>'
                        )
                except Exception:
                    pass
            item_content = str(item.get('content') or '')
            can_cache_item = (
                '[PALACE_UI_SNAPSHOT' not in item_content
                and '[GENERATE_IMAGE' not in item_content.upper()
            )
            cache_key = (
                i,
                item.get('role'),
                item.get('timestamp'),
                hashlib.sha1(item_content.encode('utf-8', errors='replace')).hexdigest()[:12],
                i in self.expanded_deliberations,
                getattr(self, 'badge_display_mode', 'icons_only'),
                getattr(self, 'active_theme', 'dark'),
                len(item.get('speaker_messages') or []),
                len(self.reply_archive),
                str(item.get('tts_label') or ''),
                str(item.get('tts_fallback_note') or ''),
                str(item.get('severity') or ''),
                str(getattr(self, '_cached_status_style', 'text') or 'text'),
            )
            cached_html = self._item_html_cache.get(cache_key) if (can_cache_item and hasattr(self, '_item_html_cache')) else None
            if cached_html is not None:
                html_blocks.append(cached_html)
            else:
                rendered_item = self._render_single_chat_item(item, theme_dict=t_dict)
                if can_cache_item and hasattr(self, '_item_html_cache'):
                    if len(self._item_html_cache) >= 400:
                        self._item_html_cache.clear()
                    self._item_html_cache[cache_key] = rendered_item
                html_blocks.append(rendered_item)
        self.chat.setHtml(''.join(html_blocks))
        if scroll_to_bottom:
            # Scroll to the top of the latest card so the user reads from the beginning of the new reply
            self.chat.moveCursor(QTextCursor.MoveOperation.End)
        elif scrollbar is not None:
            scrollbar.setValue(prev_val)

    def _on_pulse_tick(self):
        if not self.pending_status_text:
            self.pulse_timer.stop()
            self._update_inline_status_banner()
            self._sync_sidebar_working_indicator()
            return
        self.pulse_step += 1
        self._update_inline_status_banner()
        self._sync_sidebar_working_indicator()
        # Pulse working provider token dots without touching self.chat scroll position!
        for name, info in list(self.provider_details.items()):
            if info.get('status') == 'Working':
                lbl = self.provider_labels.get(name)
                if lbl and getattr(self, 'badge_display_mode', 'icons_only') == 'icons_only':
                    lbl.setIcon(provider_token_qicon(name, 'working', self.pulse_step))

    def toggle_deliberation(self, item_idx: int):
        if item_idx in self.expanded_deliberations:
            self.expanded_deliberations.remove(item_idx)
        else:
            self.expanded_deliberations.add(item_idx)
        self._render_chat_items(scroll_to_bottom=False)

    def toggle_all_deliberations(self):
        all_indices = {
            item['idx'] for item in self.chat_items if item.get('speaker_messages')
        }
        if not all_indices:
            return
        if self.expanded_deliberations == all_indices:
            self.expanded_deliberations.clear()
        else:
            self.expanded_deliberations = set(all_indices)
        self._render_chat_items(scroll_to_bottom=False)

    @Slot(QUrl)
    def _on_chat_anchor_clicked(self, url: QUrl):
        import urllib.parse
        raw = urllib.parse.unquote(url.toString())
        if raw.startswith('toggle-peer:'):
            try:
                idx = int(raw.split(':', 1)[1])
                self.toggle_deliberation(idx)
            except ValueError:
                pass
        elif raw.startswith('open-img:') or raw.startswith('img:'):
            prefix = 'open-img:' if raw.startswith('open-img:') else 'img:'
            img_path = urllib.parse.unquote(raw.split(prefix, 1)[1])
            self._open_image_viewer_dialog(img_path)
        elif raw.startswith('promote-draft:'):
            draft_title = urllib.parse.unquote(raw.split('promote-draft:', 1)[1])
            self.composer.setPlainText(
                f'/fullrender I like "{draft_title}"! Please render the finished full-resolution master (size: 16:9 HD / Facebook Banner / Square HD).'
            )
            self.composer.setFocus()
        elif raw.startswith('save-file:') or raw.startswith('save-img:'):
            prefix = 'save-file:' if raw.startswith('save-file:') else 'save-img:'
            file_path = urllib.parse.unquote(raw.split(prefix, 1)[1])
            self._download_file_as(file_path)
        elif raw.startswith('reveal-file:'):
            file_path = urllib.parse.unquote(raw.split('reveal-file:', 1)[1])
            self._reveal_file_in_explorer(file_path)
        elif raw.startswith('delete-file:'):
            file_path = urllib.parse.unquote(raw.split('delete-file:', 1)[1])
            self._delete_stored_file(file_path)
        elif raw.startswith('speak:'):
            from voice_service import speak_agent_response
            try:
                idx = int(raw.split(':', 1)[1])
                text = self.reply_archive[idx]
            except (ValueError, IndexError):
                text = self.last_answer
            if text:
                speak_agent_response(text, config_path=self.config_path)
                self.status_label.setText('🔊 Reading response aloud…')
        elif raw.startswith('copy:'):
            try:
                idx = int(raw.split(':', 1)[1])
                text = self.reply_archive[idx]
                QApplication.clipboard().setText(text)
                self.status_label.setText('Answer copied')
            except (ValueError, IndexError):
                self.copy_answer()
        elif raw.startswith('up:'):
            self.status_label.setText('Feedback noted: Helpful (👍)')
        elif raw.startswith('down:'):
            self.status_label.setText('Feedback noted: Needs improvement')

    def _download_file_as(self, file_path: str):
        import shutil
        p = Path(file_path)
        if not p.exists():
            self.show_notice(f'File not found: {file_path}')
            return
        downloads_dir = Path.home() / 'Downloads'
        default_dest = (downloads_dir / p.name) if downloads_dir.exists() else Path(p.name)
        dest, _ = QFileDialog.getSaveFileName(
            self,
            f'Download / Save {p.name} As',
            str(default_dest),
            'All Files (*.*)',
        )
        if dest:
            shutil.copy2(p, dest)
            self.status_label.setText(f'Downloaded {p.name} to {dest}')

    def _reveal_file_in_explorer(self, file_path: str):
        import subprocess
        p = Path(file_path)
        if not p.exists():
            self.show_notice(f'File not found: {file_path}')
            return
        if os.name == 'nt':
            subprocess.Popen(['explorer', f'/select,{p}'])
        elif hasattr(os, 'startfile'):
            os.startfile(str(p.parent))

    def _delete_stored_file(self, file_path: str):
        p = Path(file_path)
        if not p.exists():
            self.show_notice(f'File already removed: {p.name}')
            return
        ans = QMessageBox.question(
            self,
            'Delete Stored File',
            f'Delete "{p.name}" from Fairybread storage to free up drive space?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            try:
                sz = p.stat().st_size
                p.unlink()
                self.status_label.setText(f'Deleted {p.name} (freed {sz / 1024.0:.1f} KB)')
                self._render_chat_items(scroll_to_bottom=False)
            except OSError as exc:
                self.show_notice(f'Could not delete file: {exc}')

    def _check_storage_warnings(self):
        try:
            from palace_config import compute_palace_storage_stats, format_storage_mb_label
            st = compute_palace_storage_stats(self.config_path)
            if st['normal_state'] == 'exceeded':
                cap_lbl = format_storage_mb_label(st['normal_cap_mb'])
                self.show_notice(
                    f"⚠ Normal Mode storage cap reached ({st['normal_total_mb']:.1f} MB / {cap_lbl}). "
                    f"Open Settings → Storage & Backup to delete old files, raise your cap, or move to another drive."
                )
            elif st['normal_state'] == 'warning':
                cap_lbl = format_storage_mb_label(st['normal_cap_mb'])
                self.show_notice(
                    f"⚠ Approaching Normal Mode storage limit ({st['normal_pct']:.0f}% of {cap_lbl} used)."
                )
            elif st['idle_state'] in {'exceeded', 'warning'}:
                cap_lbl = format_storage_mb_label(st['idle_cap_mb'])
                self.show_notice(
                    f"⚠ Idle Memory storage is at {st['idle_pct']:.0f}% of {cap_lbl} ({st['idle_total_mb']:.1f} MB used)."
                )
        except Exception:
            pass

    def _open_image_viewer_dialog(self, img_path: str):
        path_obj = Path(img_path)
        if not path_obj.exists():
            self.show_notice(f'Image file not found: {img_path}')
            return
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QScrollArea
        pix = QPixmap(str(path_obj))
        if pix.isNull():
            self.show_notice(f'Could not load image: {img_path}')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f'Fairybread Visual Viewer — {path_obj.name}')
        dlg.resize(min(1180, pix.width() + 60), min(780, pix.height() + 90))
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('QScrollArea { background: #0d1117; border: 1px solid #21262d; border-radius: 6px; }')
        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setPixmap(pix)
        scroll.setWidget(img_lbl)
        lay.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        info_lbl = QLabel(f'{path_obj.name}  ({pix.width()}×{pix.height()} px · 300 DPI)')
        info_lbl.setObjectName('muted')
        btn_row.addWidget(info_lbl)
        btn_row.addStretch()

        def _save_as():
            dest, _ = QFileDialog.getSaveFileName(
                dlg,
                'Save Full-Resolution Image As',
                path_obj.name,
                'PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;WebP Image (*.webp);;All Files (*.*)',
            )
            if dest:
                pix.save(dest)
                self.status_label.setText(f'Saved image to {dest}')

        def _copy_clip():
            QApplication.clipboard().setPixmap(pix)
            self.status_label.setText(f'Copied {pix.width()}×{pix.height()} px image to clipboard')

        save_btn = QPushButton('💾 Save Image As…')
        save_btn.clicked.connect(_save_as)
        btn_row.addWidget(save_btn)

        copy_img_btn = QPushButton('📋 Copy Image')
        copy_img_btn.clicked.connect(_copy_clip)
        btn_row.addWidget(copy_img_btn)

        ext_btn = QPushButton('Open in Windows Photo Viewer ↗')
        ext_btn.clicked.connect(lambda: os.startfile(str(path_obj)) if hasattr(os, 'startfile') else None)
        btn_row.addWidget(ext_btn)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)
        dlg.exec()

    def confirm_switch(self):
        if not self.composer.toPlainText().strip() and not self.attachments:
            return True
        return QMessageBox.question(self, 'Unsent message', 'Discard the unsent message and attachments?', QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def _detach_active_worker(self):
        self._active_working_session_id = None
        self._sync_sidebar_working_indicator()
        if self.worker is not None:
            old_worker = self.worker
            self.worker = None
            try:
                old_worker.succeeded.disconnect()
                old_worker.failed.disconnect()
                old_worker.progress.disconnect()
                old_worker.finished.disconnect()
            except Exception:
                pass
            self.pending_status_text = ''
            self.pulse_timer.stop()
            self._update_inline_status_banner()
            self.set_busy(False)

    @Slot()
    def new_conversation(self):
        if not self.confirm_switch():
            return
        if self.worker is not None:
            self._detach_active_worker()
        try:
            if self.workspace_tabs.currentIndex() != 0:
                self.workspace_tabs.setCurrentIndex(0)
            self.session_id = self.store.create()
            self.reset_draft()
            self.refresh_projects()
            self.refresh_sessions()
            self.load_history()
            self.composer.setFocus()
            self.status_label.setText('New conversation created · Ready')
        except (OSError, ValueError) as exc:
            self.show_notice(str(exc))

    def _on_sidebar_item_clicked(self, item: QListWidgetItem | None):
        if item is None:
            return
        raw_key = str(item.data(Qt.ItemDataRole.UserRole) or '')
        if raw_key == 'archived_toggle':
            self._archived_expanded = not bool(getattr(self, '_archived_expanded', False))
            self.refresh_sessions()
            return
        if raw_key.startswith('proj:'):
            proj_id = raw_key.split(':', 1)[1] or None
            if proj_id != getattr(self.store, 'selected_project', None):
                try:
                    self.store.select_project(proj_id)
                    self.session_id = self.store.selected
                    self.reset_draft()
                    self.refresh_projects()
                    self.refresh_sessions()
                    self.load_history()
                except Exception as exc:
                    self.show_notice(str(exc))

    def change_session(self, current, previous):
        if current is None:
            return
        raw_key = str(current.data(Qt.ItemDataRole.UserRole) or '')
        if not raw_key or raw_key.startswith('proj:') or raw_key == 'archived_toggle':
            return
        key = raw_key
        if key == self.session_id:
            return
        if not self.confirm_switch():
            self.refresh_sessions()
            return
        if self.worker is not None:
            self._detach_active_worker()
        try:
            if self.workspace_tabs.currentIndex() != 0:
                self.workspace_tabs.setCurrentIndex(0)
            self.store.select(key)
            if hasattr(self.store, 'set_unread') and any(
                s.get('id') == key and s.get('unread') for s in getattr(self.store, 'sessions', [])
            ):
                self.store.set_unread(key, False)
            self.session_id = key
            self.reset_draft()
            self.refresh_projects()
            self.refresh_sessions()
            self.load_history()
            self.status_label.setText('Conversation restored · Ready')
        except (OSError, ValueError) as exc:
            self.show_notice(str(exc))
            self.refresh_sessions()

    def reset_draft(self):
        self.composer.clear()
        self.attachments = []
        self.refresh_attachments()

    @Slot()
    def choose_files(self):
        if self.worker is not None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            'Attach documents or pictures',
            '',
            'Documents & Pictures (*.txt *.md *.pdf *.docx *.png *.jpg *.jpeg *.webp *.gif *.bmp *.csv *.tsv *.json *.py *.ps1 *.js *.ts *.yaml *.yml *.xml *.html *.log);;All files (*)'
        )
        self.add_files(paths)

    @Slot(bytes)
    def add_pasted_image(self, raw_bytes: bytes):
        if self.worker is not None or not raw_bytes:
            return
        if len(self.attachments) >= 5:
            self.show_notice('Attach up to five files per message.')
            return
        try:
            idx = sum(1 for a in self.attachments if getattr(a, 'kind', '') == 'image') + 1
            item = attachment_from_image_bytes(raw_bytes, filename=f'pasted-image-{idx}.png')
        except Exception as exc:
            self.show_notice(str(exc))
            return
        self.files_ready(([item], []))

    @Slot(list)
    def add_files(self, paths):
        if self.worker is not None or not paths:
            return
        known = {str(item.path).casefold() for item in self.attachments}
        selected = []
        for name in paths:
            key = str(Path(name).resolve()).casefold()
            if key not in known:
                selected.append(name)
                known.add(key)
        if not selected:
            return
        if len(self.attachments) + len(selected) > 5:
            self.show_notice('Attach up to five files per message.')
            return

        def extract():
            items, errors = [], []
            for name in selected:
                try:
                    items.append(extract_attachment(name))
                except Exception as exc:
                    errors.append(f'{Path(name).name}: {exc}')
            return items, errors

        self.start_task(extract, self.files_ready, 'Reading attachments locally…')

    @Slot(object)
    def files_ready(self, payload):
        items, errors = payload
        for item in items:
            if sum(len(a.text) for a in self.attachments) + len(item.text) > MAX_TOTAL_CHARS:
                errors.append(f'{item.name}: total attachment limit is 48,000 characters.')
            else:
                self.attachments.append(item)
        self.refresh_attachments()
        self.status_label.setText('Attachments ready. They are sent only when you press Send.')
        if errors:
            self.show_notice('\n'.join(errors))

    def refresh_attachments(self):
        self.attachment_list.clear()
        for item in self.attachments:
            note = ' · excerpt only' if item.truncated else ''
            entry = QListWidgetItem(f'📎 {item.name}  ·  {len(item.text):,} chars{note}')
            entry.setToolTip(item.text[:1200])
            self.attachment_list.addItem(entry)
        self.attachment_list.setFixedHeight(0)
        self.attachment_list.setVisible(bool(self.attachments))
        self.remove_button.setVisible(bool(self.attachments))
        self._sync_composer_live_bar_visibility()
        if self.attachments:
            self.attachment_list.setCurrentRow(0)

        if hasattr(self, 'staged_attachments_layout'):
            while self.staged_attachments_layout.count():
                child = self.staged_attachments_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            for idx, item in enumerate(self.attachments):
                kind = getattr(item, 'kind', 'text')
                stored_p = getattr(item, 'stored_path', None) or getattr(item, 'path', None)
                if kind == 'image' and stored_p and Path(stored_p).exists():
                    # ChatGPT-style mini picture icon (no text clutter!) with top-right ✕ remove button
                    chip = QFrame()
                    chip.setFixedSize(62, 62)
                    chip.setToolTip(item.name)
                    chip.setStyleSheet(
                        'QFrame { background: #161b22; border: 1px solid #30363d; border-radius: 10px; }'
                    )
                    thumb_lbl = QLabel(chip)
                    thumb_lbl.setGeometry(2, 2, 58, 58)
                    pix = QPixmap(str(stored_p))
                    if not pix.isNull():
                        thumb_lbl.setPixmap(
                            pix.scaled(58, 58, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                        )
                    thumb_lbl.setStyleSheet('border-radius: 8px; border: none;')
                    rm_btn = QPushButton('✕', chip)
                    rm_btn.setGeometry(40, 2, 20, 20)
                    rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    rm_btn.setToolTip(f'Remove {item.name}')
                    rm_btn.setStyleSheet(
                        'QPushButton { background: rgba(13,17,23,0.88); color: #f0f6fc; border: 1px solid #30363d; border-radius: 10px; font-size: 10px; font-weight: 700; } '
                        'QPushButton:hover { background: #da3633; color: #ffffff; }'
                    )
                    rm_btn.clicked.connect(lambda _c=False, i=idx: self._remove_attachment_at(i))
                    self.staged_attachments_layout.addWidget(chip)
                else:
                    # ChatGPT-style dark rounded document pill (📄 filename.txt  ✕)
                    chip = QFrame()
                    chip.setStyleSheet(
                        'QFrame { background: #21262d; border: 1px solid #30363d; border-radius: 12px; }'
                    )
                    chip_lay = QHBoxLayout(chip)
                    chip_lay.setContentsMargins(10, 5, 6, 5)
                    chip_lay.setSpacing(7)
                    txt_lbl = QLabel(f'📄  <b>{html.escape(item.name)}</b>')
                    txt_lbl.setTextFormat(Qt.TextFormat.RichText)
                    txt_lbl.setStyleSheet('color: #e6edf3; font-size: 12.5px; border: none; background: transparent;')
                    chip_lay.addWidget(txt_lbl)
                    rm_btn = QPushButton('✕')
                    rm_btn.setFixedSize(20, 20)
                    rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    rm_btn.setToolTip(f'Remove {item.name}')
                    rm_btn.setStyleSheet(
                        'QPushButton { background: #30363d; color: #c9d1d9; border: none; border-radius: 10px; font-size: 10px; font-weight: 700; } '
                        'QPushButton:hover { background: #da3633; color: #ffffff; }'
                    )
                    rm_btn.clicked.connect(lambda _c=False, i=idx: self._remove_attachment_at(i))
                    chip_lay.addWidget(rm_btn)
                    self.staged_attachments_layout.addWidget(chip)
            self.staged_attachments_layout.addStretch(1)
            self.staged_attachments_frame.setVisible(bool(self.attachments))

    def _remove_attachment_at(self, idx: int):
        if self.worker is None and 0 <= idx < len(self.attachments):
            self.attachments.pop(idx)
            self.refresh_attachments()

    @Slot()
    def remove_attachment(self):
        index = self.attachment_list.currentRow()
        if self.worker is None and index >= 0:
            self.attachments.pop(index)
            self.refresh_attachments()

    def dragEnterEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls():
            self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()

    def _show_slash_commands_menu(self):
        menu = QMenu(self)
        from palace_config import IS_DEVELOPER_EDITION
        commands = []
        if IS_DEVELOPER_EDITION:
            commands.extend([
                ('/autopatch', '⚡ /autopatch — Read code, generate verified patch & hot-reboot'),
                ('/restore', '♻ /restore — Roll back to previous verified code edition & hot-reboot'),
                ('/restore list', '🕰️ /restore list — View all saved code editions & golden pins'),
                ('/code', '{} /code — Attach Fairybread source code reference for this turn'),
            ])
        commands.extend([
            ('/search', '🔍 /search — Light web search'),
            ('/searchm', '🔎 /searchm — Moderate multi-angle sharded web search'),
            ('/searchd', '🌐 /searchd — Deep exhaustive 15–25 site web research'),
            ('/tangent', '↗ /tangent — Side question (ignore prior chat context, still saved)'),
            ('/fullrender', '🖼 /fullrender — Render 1 full-res master image immediately (skip 3 drafts)'),
        ])
        for cmd_token, label in commands:
            act = QAction(label, menu)

            def _insert_cmd(_checked=False, tok=cmd_token):
                cur = self.composer.toPlainText()
                if tok not in cur:
                    sep = ' ' if (cur and not cur.endswith(' ')) else ''
                    self.composer.setPlainText(f'{cur}{sep}{tok} ')
                    cursor = self.composer.textCursor()
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    self.composer.setTextCursor(cursor)
                self.composer.setFocus()

            act.triggered.connect(_insert_cmd)
            menu.addAction(act)
        menu.exec(self.slash_cmd_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _on_palace_code_btn_toggled(self, on: bool):
        self.palace_code_btn.setIcon(code_shield_qicon(on))
        if on and self.worker is not None and getattr(self, 'active_steering_state', None) is not None:
            self.active_steering_state['include_palace_code'] = True
            self.show_notice('✓ Live Steering: Fairybread Source Code attached to active turn.')

    def _show_search_depth_menu(self):
        menu = QMenu(self)
        choices = [
            ('default', '🔍 Default (Light Search — /search)'),
            ('moderate', '🔎 Moderate (Sharded Multi-Angle — /searchm)'),
            ('deep', '🌐 Deep (Exhaustive 15–25 Site Research — /searchd)'),
        ]
        for depth_key, label in choices:
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(getattr(self, 'current_search_depth', 'default') == depth_key)

            def _pick(_checked=False, dk=depth_key):
                self._set_search_depth(dk)

            act.triggered.connect(_pick)
            menu.addAction(act)
        menu.exec(self.search_depth_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _set_search_depth(self, depth_key: str):
        self.current_search_depth = depth_key
        labels = {
            'default': '🔍 Default ▾',
            'moderate': '🔎 Moderate ▾',
            'deep': '🌐 Deep ▾',
        }
        self.search_depth_btn.setText(labels.get(depth_key, '🔍 Default ▾'))
        if depth_key == 'default':
            self.search_depth_btn.setStyleSheet(
                'QPushButton { background: #161b22; color: #8b949e; border: 1px solid #21262d; '
                'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
                'QPushButton:hover { color: #c9d1d9; border-color: #30363d; }'
            )
        elif depth_key == 'moderate':
            self.search_depth_btn.setStyleSheet(
                'QPushButton { background: #132238; color: #58a6ff; border: 1px solid #3b82f6; '
                'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 700; }'
            )
        else:
            self.search_depth_btn.setStyleSheet(
                'QPushButton { background: #221538; color: #c084fc; border: 1px solid #a855f7; '
                'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 700; }'
            )

    def _show_busy_action_menu(self):
        note_present = bool(self.composer.toPlainText().strip())
        local_pos = self.steer_button.mapFromGlobal(QCursor.pos())
        clicked_arrow = local_pos.x() >= max(24, self.steer_button.width() - 24)
        if note_present and not clicked_arrow:
            if getattr(self, '_busy_submit_mode', 'steer') == 'queue':
                self.queue_next_turn()
            else:
                self.steer_active_turn()
            return
        menu = QMenu(self)
        steer_act = menu.addAction('🧭 Steer Active Turn (inject into current turn · Enter)')
        queue_act = menu.addAction('⏳ Queue for Next Turn (run after current turn)')
        chosen = menu.exec(self.steer_button.mapToGlobal(QPoint(0, -menu.sizeHint().height())))
        if chosen == steer_act:
            self._busy_submit_mode = 'steer'
            self.steer_active_turn()
        elif chosen == queue_act:
            self._busy_submit_mode = 'queue'
            self.queue_next_turn()

    @Slot()
    def stop_active_turn(self):
        if self.worker is None:
            return
        if getattr(self, 'active_cancel_event', None) is not None:
            self.active_cancel_event.set()
        w = self.worker
        try:
            w.succeeded.disconnect()
            w.failed.disconnect()
            w.finished.disconnect()
        except Exception:
            pass
        # Ensure the QThread actually stops before we drop our last reference.
        # Qt parent ownership is not guaranteed here; a running QThread whose
        # Python refcount hits zero causes "QThread: Destroyed while thread is
        # still running" at interpreter shutdown.
        try:
            if hasattr(w, "requestInterruption"):
                w.requestInterruption()
            if hasattr(w, "quit"):
                w.quit()
            if hasattr(w, "wait"):
                w.wait(2000)
        except Exception:
            pass
        self.worker = None
        self._active_working_session_id = None
        self._sync_sidebar_working_indicator()
        self.pending_status_text = ''
        self.pulse_timer.stop()
        self._update_inline_status_banner()
        pop_idx = len(self.chat_items) - 1
        while pop_idx >= 0 and self.chat_items[pop_idx].get('role') == 'system_status':
            pop_idx -= 1
        if pop_idx >= 0 and self.chat_items[pop_idx].get('role') == 'user':
            self.chat_items.pop(pop_idx)
            self._render_chat_items(scroll_to_bottom=False)
        restored = getattr(self, 'last_question', '') or self.pending_prompt
        self.pending_prompt = ''
        self.set_busy(False)
        if restored:
            self.composer.setPlainText(restored)
        for name, enabled in self.provider_states.items():
            if enabled is True:
                self.set_provider_status(name, 'Enabled', provider_color(name))
        self.show_notice('Turn stopped. Your original prompt has been restored to the composer.')

    @Slot()
    def steer_active_turn(self):
        if self.worker is None:
            return
        note = self.composer.toPlainText().strip()
        if getattr(self, 'active_steering_state', None) is None:
            self.active_steering_state = {'notes': [], 'include_palace_code': self.palace_code_btn.isChecked()}
        if self.palace_code_btn.isChecked():
            self.active_steering_state['include_palace_code'] = True
        if note:
            self.active_steering_state.setdefault('notes', []).append(note)
            self.composer.clear()
            count = len(self.active_steering_state['notes'])
            self.steer_button.setText(f"🧭 Steer ({count}) ▾")
            self.steer_button.setStyleSheet(
                'QPushButton { background: #132238; color: #58a6ff; border: 1px solid #3b82f6; '
                'padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 700; }'
            )
            # Display the steer comment in chat stream immediately so the user can see it!
            self.append_message(
                'user',
                f"[LIVE STEER #{count}]: {note}",
                render=True
            )
            self.show_notice(f'✓ Live Steering #{count} injected into active turn: "{note[:60]}"')
        else:
            self.show_notice('✓ Live Steering updated (Fairybread Code & tool flags synced to active turn).')

    @Slot()
    def queue_next_turn(self):
        question = self.composer.toPlainText().strip()
        if not question:
            self.show_notice('Type a command in the composer first, then choose Queue.')
            return
        if not hasattr(self, 'queued_prompts'):
            self.queued_prompts = []
        self.queued_prompts.append(question)
        self.composer.clear()
        self.steer_button.setText(f'⏳ Queued ({len(self.queued_prompts)}) ▾')
        self.steer_button.setStyleSheet(
            'QPushButton { background: #29230f; color: #eab308; border: 1px solid #eab308; '
            'padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 700; }'
        )
        self.show_notice(f'⏳ Queued ({len(self.queued_prompts)}): "{question[:55]}" — will run automatically next.')

    @Slot()
    def send_message(self):
        if self.worker is not None:
            if getattr(self, '_busy_submit_mode', 'steer') == 'queue':
                self.queue_next_turn()
            else:
                self.steer_active_turn()
            return
        question = self.composer.toPlainText().strip()
        if not question:
            self.status_label.setText('Enter a question or instructions for the attached files.')
            self.composer.setFocus()
            return
        if self.current_profile == 'Idle':
            if not self.idle_manager.operator_admitted:
                self.show_notice('Idle Mode is protected. Request to Join (consensus vote) before sending a message.')
                return
            self.composer.clear()
            self.run_idle_exchange_step(operator_message=question)
            return
        if bool(getattr(self, '_talk_only_mode', False)):
            if self.attachments:
                self.show_notice(
                    'Attachments require a full AI squad — switch out of Talk Mode Only (e.g., Generalist or Graphics & Vision) to analyze files/images.'
                )
                return
            recent_snip = self._recent_voice_context_snippet()
            mem_ctx, allow_mem_write = self._search_voice_memory_context(question)
            req_gen = int(getattr(self, '_voice_session_gen', 0))
            self.last_question = question
            self.composer.clear()
            self.append_message('user', question, render=True)
            self.status_label.setText('🎙️ Talk Mode Only — replying…')
            worker = VoiceCompanionWorker(
                None,
                self._get_voice_companion(),
                text_input=question,
                companion_enabled=True,
                talk_only=True,
                recent_chat_snippet=recent_snip,
                memory_context=mem_ctx,
                allow_memory_write=allow_mem_write,
                session_gen=req_gen,
                memory_db_path=self._memory_db_path(),
                parent=self,
            )
            self._voice_threads.append(worker)

            def _cleanup_talk_w(_w=worker):
                try:
                    if _w in self._voice_threads:
                        self._voice_threads.remove(_w)
                except Exception:
                    pass
                _w.deleteLater()

            def _on_talk_done(decision, _transcript: str, q_text=question, gen=req_gen):
                if gen != int(getattr(self, '_voice_session_gen', 0)):
                    return
                if decision is None or not str(getattr(decision, 'spoken_reply', '') or '').strip():
                    return
                saved_mems = self._save_voice_memories(
                    list(getattr(decision, 'memory_saves', None) or []),
                    author=getattr(decision, 'provider_used', '') or 'voice_companion',
                )
                reply = decision.spoken_reply
                disp_reply = reply
                if saved_mems:
                    badges = ' · '.join(f'🧠 Saved: "{m["summary"]}"' for m in saved_mems)
                    disp_reply = f'{reply}\n\n{badges}'
                self._deliver_voice_companion_reply(
                    user_disp=q_text,
                    raw_user_for_store=q_text,
                    disp_reply=disp_reply,
                    spoken_reply=reply,
                    decision=decision,
                    req_gen=gen,
                    append_user_msg=False,
                    persist_exchange=True,
                    speak_aloud=True,
                )
                self.last_answer = disp_reply
                self.copy_button.setEnabled(True)
                self.status_label.setText('🎙️ Talk Mode Only · Replied')

            worker.completed.connect(_on_talk_done)
            worker.failed.connect(lambda err, g=req_gen: (
                (self.show_notice(f'Talk Mode notice: {err}'),
                 self.status_label.setText('🎙️ Talk Mode Only · Error'))
                if g == int(getattr(self, '_voice_session_gen', 0))
                else None
            ))
            worker.finished.connect(_cleanup_talk_w)
            worker.start()
            return
        try:
            prompt = compose_question(question, self.attachments)
        except ValueError as exc:
            self.show_notice(str(exc))
            return
        self.last_question = question
        self.pending_prompt = prompt

        is_no_history = self.no_history_btn.isChecked() or (not self.history_toggle.isChecked())
        is_tangent = self.tangent_btn.isChecked() and not is_no_history
        save_history = not is_no_history
        use_history = (not is_no_history) and (not is_tangent)
        self.pending_history = save_history

        context = self.store.context(self.session_id)
        rounds = 2 if self.peer_rounds_toggle.isChecked() else 1

        selected_providers = [name for name, enabled in self.provider_states.items() if enabled is True]
        if self.max_ais_per_turn and self.max_ais_per_turn > 0 and len(selected_providers) > self.max_ais_per_turn:
            selected_providers = selected_providers[:self.max_ais_per_turn]

        tool_cfg = load_tool_settings(self.config_path)
        use_palace_code = bool(self.palace_code_btn.isChecked() or tool_cfg.get('palace_source_tool', False) and self.current_squad_label == '🛠 Work Mode')
        proj_folder = ''
        if tool_cfg.get('project_folder_tool', True) and hasattr(self.store, 'get_project_folder'):
            proj_folder = self.store.get_project_folder()

        from email_service import extract_email_search_query, is_email_configured
        from orchestrator import classify_drawing_request
        email_q = extract_email_search_query(prompt)
        if email_q is not None and not is_email_configured(self.config_path):
            self.show_notice(
                'Email Connector is not set up yet. Open Settings → 📧 Email & Notifications to connect your Gmail, Outlook/365, or IMAP account.'
            )
        draw_mode = classify_drawing_request(prompt)
        if email_q is not None and is_email_configured(self.config_path):
            self.pending_status_text = f'Exhaustive Email Search ({email_q!r}) → Consulting Council'
        elif draw_mode == 'direct_draw':
            self.pending_status_text = '1-Pass Drawing Mode: Crafting rich visual prompt & rendering high-res image'
        elif draw_mode == 'council_draw':
            self.pending_status_text = 'Graphic Prompt Duo (2 Specialists) → Primary Renderer + Fallback'
        elif selected_providers:
            disp_list = ', '.join(provider_display_name(n) for n in selected_providers)
            self.pending_status_text = f'Consulting {disp_list}'
        else:
            self.pending_status_text = 'Consulting the enabled providers'
        self._turn_start_time = time.time()
        self.pulse_step = 0
        self.pulse_timer.start()
        self._active_working_session_id = self.session_id
        self._sync_sidebar_working_indicator()
        self._update_inline_status_banner()

        self.append_message('user', prompt)
        if save_history:
            try:
                self.store.rename_from_question(self.session_id, self.last_question)
                self.refresh_projects()
                self.refresh_sessions()
            except OSError:
                pass
        self.composer.clear()
        self.attachments = []
        self.refresh_attachments()
        for name, enabled in self.provider_states.items():
            if enabled is True and (not selected_providers or name in selected_providers):
                self.set_provider_status(name, 'Working', '#95b9ff')

        import threading
        self.active_cancel_event = threading.Event()
        self.active_steering_state = {
            'notes': [],
            'include_palace_code': use_palace_code,
        }
        cur_search_depth = getattr(self, 'current_search_depth', 'default')

        worker_box: dict[str, TaskThread | None] = {'w': None}

        def ask():
            palace = self.palace_factory(context)
            use_shared_mem = bool(
                use_history
                and getattr(self, 'enable_shared_memory', self.palace_factory == self._build_palace)
            )
            all_kwargs = {
                'provider_names': selected_providers if selected_providers else None,
                'include_memory': use_shared_mem,
                'include_context': use_history,
                'save_to_context': save_history,
                'max_rounds': rounds,
                'include_palace_code': use_palace_code,
                'project_folder': proj_folder,
                'search_depth': cur_search_depth,
                'cancel_event': self.active_cancel_event,
                'steering_state': self.active_steering_state,
                'on_phase_status': lambda ev: worker_box['w'].progress.emit(ev) if worker_box.get('w') is not None else None,
            }
            sr_override = getattr(self, 'smart_routing_override', None)
            if sr_override is not None:
                all_kwargs['smart_routing_override'] = sr_override
            try:
                sig = inspect.signature(palace.run)
                params = sig.parameters
                accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
                call_kwargs = all_kwargs if accepts_var_kw else {k: v for k, v in all_kwargs.items() if k in params}
            except (TypeError, ValueError):
                call_kwargs = {
                    'provider_names': selected_providers if selected_providers else None,
                    'include_context': use_history,
                    'save_to_context': save_history,
                    'max_rounds': rounds,
                    'include_palace_code': use_palace_code,
                    'project_folder': proj_folder,
                }
            return palace.run(prompt, **call_kwargs)

        self.start_task(
            ask,
            self.answer_ready,
            f'{self.pending_status_text}…',
            on_progress=self._on_turn_phase_progress,
            worker_box=worker_box,
        )

    @Slot(object)
    def _on_turn_phase_progress(self, ev):
        if not isinstance(ev, dict):
            return
        kind = ev.get('event')
        if kind == 'provider_done':
            prov = str(ev.get('provider', ''))
            ok = bool(ev.get('succeeded', True))
            rnd = int(ev.get('round', 1))
            done_c = int(ev.get('done', 0))
            tot_c = int(ev.get('total', 1))
            if prov:
                self.set_provider_status(
                    prov,
                    'Responded' if ok else 'Limited',
                    '#90d7c1' if ok else '#e2b96b',
                )
            self.pending_status_text = f'Round {rnd}: {done_c}/{tot_c} AIs responded ({provider_display_name(prov)} finished)'
            self._update_inline_status_banner()
        elif kind == 'phase':
            txt = str(ev.get('text', '')).strip()
            for r_prov in ev.get('reset_working', []) or []:
                self.set_provider_status(r_prov, 'Working', '#95b9ff')
            if txt:
                self.pending_status_text = txt
                self._update_inline_status_banner()

    @Slot(object)
    def answer_ready(self, result):
        finished_sid = getattr(self, '_active_working_session_id', None)
        self._active_working_session_id = None
        self._sync_sidebar_working_indicator()
        self.pending_status_text = ''
        self.pulse_timer.stop()
        self._update_inline_status_banner()
        if finished_sid and finished_sid != self.session_id and hasattr(self.store, 'set_unread'):
            try:
                self.store.set_unread(finished_sid, True)
                self.refresh_sessions()
            except Exception:
                pass
        speaker_msgs = getattr(result, 'speaker_messages', None) or []
        turn_contributors = list(getattr(result, 'contributors', []) or [])
        for c in turn_contributors:
            if c and c not in self.conversation_contributors:
                self.conversation_contributors.append(c)
        if result.final_answer:
            try:
                from voice_service import clean_text_for_speech, load_voice_settings, speak_agent_response
                v_cfg = load_voice_settings(self.config_path)
                live_active = bool(
                    getattr(self, '_turn_triggered_by_live_voice', False)
                    or getattr(self, '_background_delegated_from_voice', False)
                    or (hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked())
                )
                self._turn_triggered_by_live_voice = False
                self._background_delegated_from_voice = False
                if live_active:
                    if (
                        bool(v_cfg.get('spoken_summary_for_background', True))
                        and len(clean_text_for_speech(result.final_answer)) > 260
                    ):
                        sum_w = VoiceSummaryWorker(
                            self._get_voice_companion(),
                            str(getattr(self, 'last_question', '') or ''),
                            result.final_answer,
                            turn_contributors,
                            parent=self,
                        )
                        self._voice_threads.append(sum_w)

                        def _cleanup_sw(_sw=sum_w):
                            try:
                                if _sw in self._voice_threads:
                                    self._voice_threads.remove(_sw)
                            except Exception:
                                pass
                            _sw.deleteLater()

                        sum_w.summary_ready.connect(
                            lambda spoken_sum: speak_agent_response(spoken_sum, config_path=self.config_path)
                        )
                        sum_w.finished.connect(_cleanup_sw)
                        sum_w.start()
                    else:
                        speak_agent_response(result.final_answer, config_path=self.config_path)
                elif v_cfg.get('auto_speak_responses'):
                    speak_agent_response(result.final_answer, config_path=self.config_path)
            except Exception:
                pass
            # Render ONE combined reply card with an inline collapsible "› Peer deliberation" dropdown
            self.append_message(
                'assistant',
                result.final_answer,
                contributors=turn_contributors,
                speaker_messages=speaker_msgs if len(getattr(result, 'provider_results', {})) > 1 else [],
            )
            self.last_answer = result.final_answer
            self.copy_button.setEnabled(True)
            if self.pending_history and not result.context_error:
                try:
                    self.store.rename_from_question(self.session_id, self.last_question)
                    self.refresh_projects()
                    self.refresh_sessions()
                except OSError as exc:
                    self.show_notice(f'Answer saved, but conversation title could not be saved: {exc}')
                try:
                    from memory_service import MemoryService
                    MemoryService(db_path=self._memory_db_path()).remember_exchange(
                        self.last_question,
                        result.final_answer,
                        session_id=self.session_id,
                        project=self._current_project_name(),
                        contributors=turn_contributors,
                    )
                    if hasattr(self, 'memory_panel') and self.memory_panel.isVisible():
                        self.refresh_memory_review(True)
                    else:
                        self._update_durable_memory_count()
                    if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
                        import threading
                        from memory_service import auto_evolve_user_profile_from_turn
                        q_snap = str(self.last_question or '')
                        db_snap = self._memory_db_path()
                        threading.Thread(
                            target=lambda: auto_evolve_user_profile_from_turn(q_snap, db_path=db_snap),
                            daemon=True,
                        ).start()
                except Exception:
                    pass
            saved = 'Saved locally' if self.pending_history and not result.context_error else 'Not saved (No-History)'
            if self.tangent_btn.isChecked() and self.pending_history and not result.context_error:
                saved = 'Tangent saved to Palace (clean context)'
            contrib_badges = '&nbsp;&nbsp;'.join(format_ai_badge_html(c) for c in turn_contributors)

            applied_ap = getattr(result, 'applied_autopatch_files', None) or []
            ap_sum = str(getattr(result, 'autopatch_reboot_summary', '') or '')

            ans_upper = str(result.final_answer or '').upper()
            if '[ALL TASKS COMPLETED' in ans_upper:
                status_badge = '<span style="color:#3fb950; font-weight:700;">✓ All background tasks completed successfully</span>'
            elif '[PAUSED' in ans_upper or 'WAITING FOR USER INPUT' in ans_upper:
                status_badge = '<span style="color:#d29922; font-weight:700;">⏸ Paused — Waiting for your input</span>'
            elif applied_ap or '[AUTOPATCH STAGED' in ans_upper:
                status_badge = '<span style="color:#58a6ff; font-weight:700;">⚡ Autopatch Staged — Hot-Rebooting…</span>'
            else:
                status_badge = '<span style="color:#8b949e; font-weight:600;">✓ Turn Complete · Ready</span>'

            self.status_label.setTextFormat(Qt.TextFormat.RichText)
            self.status_label.setText(f'{status_badge} &nbsp;·&nbsp; {saved} &nbsp;·&nbsp; {contrib_badges}')
            elapsed_s = max(0.0, time.time() - getattr(self, '_turn_start_time', time.time()))
            self.trigger_completion_notifications(
                title='Fairybread — Response Ready',
                summary=result.final_answer,
                elapsed_seconds=elapsed_s,
                is_idle=False,
            )
        else:
            self._render_chat_items()
            self.status_label.setTextFormat(Qt.TextFormat.PlainText)
            self.status_label.setText('No provider returned an answer. Your message has been restored for retry.')
            self.composer.setPlainText(self.pending_prompt)
        failed_notes: list[str] = []
        for name, enabled in self.provider_states.items():
            if not enabled:
                continue
            if enabled == 'inactive':
                self.set_provider_status(name, 'Inactive', '#6e7681', 'INACTIVE_IN_PROFILE: Loaded in background.')
                continue
            response = result.provider_results.get(name)
            if response is None:
                self.set_provider_status(name, 'Inactive', '#6e7681', 'Skipped on this turn')
            elif response.succeeded:
                self.set_provider_status(name, 'Responded', '#90d7c1')
            else:
                error = response.error or 'Unknown provider error'
                degraded = any(word in error.lower() for word in ['429', 'rate', 'quota', 'timeout'])
                self.set_provider_status(name, 'Limited' if degraded else 'Failed', '#e2b96b' if degraded else '#ff9595', error)
                failed_notes.append(f'{provider_display_name(name)} ({error[:75]})')
        warnings = [result.context_error, result.memory_error]
        if result.synthesis and not result.synthesis.succeeded:
            warnings.append(f'Synthesis: {result.synthesis.error}')
            failed_notes.append(f'Synthesizer fallback ({str(result.synthesis.error or "error")[:75]})')
        if failed_notes:
            self.append_status_message(
                'Status: ' + ' · '.join(failed_notes),
                severity='error',
                icon_prefix='⚠',
                force=False,
                render=True,
            )
        if any(warnings):
            self.show_notice('\n'.join(w for w in warnings if w))
        pending_acts = list(getattr(result, 'pending_actions', None) or [])
        self._show_pending_actions_banner(pending_acts)
        applied_ap = getattr(result, 'applied_autopatch_files', None) or []
        ap_sum = str(getattr(result, 'autopatch_reboot_summary', '') or '')
        if applied_ap and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            self.show_notice(f'⚡ /autopatch Verified & Staged ({", ".join(applied_ap)}): {ap_sum} — Hot-Rebooting in 1.5s…')
            try:
                import re
                from palace_ouroboros import write_post_reboot_task
                last_q = self.last_question or ''
                chain_match = re.search(r'\(Chain:\s*(\d+)/(\d+)\)', last_q)
                cur_depth = int(chain_match.group(1)) if chain_match else (1 if '[POST-REBOOT CONTINUATION' in last_q else 0)
                next_depth = cur_depth + 1
                if next_depth <= 3:
                    if next_depth < 3:
                        instructions = [
                            'Examine what just happened after the hot-reboot ([TOOL: inspect_palace_ui] or read the updated lines).',
                            'Verify that the latest patch is working cleanly.',
                            'If there are remaining planned improvements in your sequence, proceed autonomously to apply the next planned patch via /autopatch.',
                            'If all planned improvements are complete, or if you hit any blocker/ambiguity, confirm to the user and report completion.',
                        ]
                    else:
                        instructions = [
                            'Examine what just happened after the hot-reboot ([TOOL: inspect_palace_ui] or read the updated lines).',
                            'All chained patches in this sequence (up to 3) are complete. Confirm to the user that all updates are live and working.',
                        ]
                    write_post_reboot_task(
                        origin='autopatch_hot_reboot',
                        chat_session_id=self.session_id,
                        user_request_summary=last_q,
                        what_was_attempted=ap_sum or f'Modified {", ".join(applied_ap)}',
                        instructions_for_agents=instructions,
                        chain_depth=next_depth,
                    )
            except Exception:
                pass
            def _trigger_autopatch_reboot():
                import subprocess, sys
                wd_script = Path(__file__).with_name('palace_watchdog.py')
                subprocess.Popen(
                    [sys.executable, str(wd_script), '--skip-tests', '--summary', ap_sum or 'Normal Mode /autopatch'],
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
            QTimer.singleShot(1500, _trigger_autopatch_reboot)

    def show_desktop_toast(self, title: str, message: str):
        try:
            tray = self._ensure_system_tray()
            if tray is None:
                return
            clean_msg = re.sub(r'\[GENERATE_IMAGE[^\]]*\]', '[Generated Image]', message or '')
            clean_msg = re.sub(r'\s+', ' ', clean_msg).strip()[:180]
            tray.showMessage(title, clean_msg or 'Task completed.', QSystemTrayIcon.MessageIcon.Information, 4500)
        except Exception:
            pass

    def trigger_completion_notifications(
        self,
        title: str,
        summary: str,
        elapsed_seconds: float = 0.0,
        is_idle: bool = False,
    ):
        try:
            from email_service import is_email_configured, load_email_settings, send_self_notification_email
            cfg = load_email_settings(self.config_path)
            if cfg.get('desktop_sound_enabled', False):
                QApplication.beep()

            if cfg.get('desktop_notify_enabled', True):
                d_mode = str(cfg.get('desktop_notify_mode', 'background_or_long'))
                min_s = float(cfg.get('desktop_notify_min_seconds', 12))
                is_bg = not self.isActiveWindow() or self.isMinimized()
                should_toast = (
                    (d_mode == 'always')
                    or (d_mode == 'idle_only' and is_idle)
                    or (d_mode == 'background_or_long' and (is_bg or elapsed_seconds >= min_s or is_idle))
                )
                if should_toast and not self.demo:
                    self.show_desktop_toast(title, summary)

            if cfg.get('email_notify_enabled', False) and is_email_configured(self.config_path):
                e_mode = str(cfg.get('email_notify_mode', 'long_or_idle'))
                e_min_s = float(cfg.get('email_notify_min_seconds', 30))
                should_email = (
                    (e_mode == 'always')
                    or (e_mode == 'idle_only' and is_idle)
                    or (e_mode == 'long_or_idle' and (elapsed_seconds >= e_min_s or is_idle))
                )
                if should_email and not self.demo:
                    attachments: list[Path] = []
                    if cfg.get('email_attach_images', True) and '[GENERATE_IMAGE' in (summary or '').upper():
                        try:
                            from palace_theme import prewarm_generated_images
                            attachments = prewarm_generated_images(summary)
                        except Exception:
                            attachments = []
                    import threading
                    threading.Thread(
                        target=send_self_notification_email,
                        kwargs={
                            'subject': f'🧚 {title} ({elapsed_seconds:.0f}s)',
                            'body_text': f'Question: {self.last_question}\n\n{summary}',
                            'attachments': attachments,
                            'config_path': self.config_path,
                        },
                        daemon=True,
                    ).start()
        except Exception:
            pass

    def start_task(self, function, on_success, message, on_progress=None, worker_box=None):
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setText(message)
        self.worker = TaskThread(function, self)
        if isinstance(worker_box, dict):
            worker_box['w'] = self.worker
        if on_progress is not None:
            self.worker.progress.connect(on_progress)
        self.worker.succeeded.connect(on_success)
        self.worker.failed.connect(self.task_failed)
        self.worker.finished.connect(self.task_finished)
        self.set_busy(True)
        self.worker.start()

    def set_busy(self, busy):
        for widget in (self.send_button, self.attach_button, self.remove_button,
                       self.pinned_list, self.project_list, self.new_project_button, self.attach_project_folder_btn,
                       self.history_toggle, self.peer_rounds_toggle, self.deliberate_pill_btn,
                       self.tangent_btn, self.no_history_btn,
                       self.ai_pill_button, self.profile_combo):
            widget.setEnabled(not busy)
        # Hide pre-turn setup buttons while busy so the composer row never crowds or clips!
        for setup_w in (
            self.attach_button,
            self.ai_pill_button,
            self.deliberate_pill_btn,
            self.tangent_btn,
            self.search_depth_btn,
            self.permission_pill_btn,
            self.mic_button,
            self.send_button,
        ):
            setup_w.setVisible(not busy)
        if hasattr(self, 'permission_pill_btn'):
            self.permission_pill_btn.setEnabled(not busy)
        # Keep composer, Settings & AIs, and Fairybread Code toggle unlocked during work!
        self.manage_ais_button.setEnabled(True)
        self.composer.setEnabled(True)
        self.palace_code_btn.setEnabled(True)
        self.new_button.setEnabled(True)
        self.session_list.setEnabled(True)
        if hasattr(self, 'stop_button'):
            self.stop_button.setVisible(bool(busy))
        if hasattr(self, 'steer_button'):
            self.steer_button.setVisible(bool(busy))
            if not busy and hasattr(self, '_neutral_busy_btn_style') and not getattr(self, 'queued_prompts', None):
                self.steer_button.setText('Steer / Queue ▾')
                self.steer_button.setStyleSheet(self._neutral_busy_btn_style)
        if hasattr(self, 'queue_button'):
            self.queue_button.hide()
        if self.current_profile == 'Idle':
            self.profile_combo.setEnabled(True)
            self.manage_ais_button.setEnabled(True)
        self.send_button.setText('…' if busy else '↑')
        self._sync_composer_live_bar_visibility()

    @Slot(str)
    def task_failed(self, error):
        self._active_working_session_id = None
        self._sync_sidebar_working_indicator()
        self.pending_status_text = ''
        self.pulse_timer.stop()
        self._update_inline_status_banner()
        self._render_chat_items()
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setText(f'Could not complete the request: {error}')
        if self.pending_prompt and not self.composer.toPlainText():
            self.composer.setPlainText(self.pending_prompt)
        for name, enabled in self.provider_states.items():
            if enabled is True:
                self.set_provider_status(name, 'Unavailable', '#e2b96b', error)

    @Slot()
    def task_finished(self):
        self._active_working_session_id = None
        self._sync_sidebar_working_indicator()
        self.pending_status_text = ''
        self.pulse_timer.stop()
        self._update_inline_status_banner()
        completed = self.worker
        self.worker = None
        self.pending_prompt = ''
        self.set_busy(False)
        if self.current_profile == 'Idle' and not self.idle_manager.operator_admitted:
            self.composer.setEnabled(False)
            self.send_button.setEnabled(False)
        if completed:
            completed.deleteLater()
        self.composer.setFocus()
        self._check_storage_warnings()
        if getattr(self, 'queued_prompts', None):
            next_q = self.queued_prompts.pop(0)
            self.composer.setPlainText(next_q)
            QTimer.singleShot(40, self.send_message)

    def copy_answer(self):
        QApplication.clipboard().setText(self.last_answer)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setText('Answer copied')

    def show_notice(self, text):
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setText(text)

    def closeEvent(self, event: QCloseEvent):
        force_quit = bool(getattr(self, '_force_quit', False))
        if not force_quit and self.worker is not None:
            self.show_notice('A request is still running. Please let it finish before closing Fairybread.')
            event.ignore()
            return
        if not force_quit and not self.confirm_switch():
            event.ignore()
            return
        if (
            not force_quit
            and os.environ.get('QT_QPA_PLATFORM') != 'offscreen'
            and bool(load_ui_settings(self.config_path).get('close_to_tray', True))
        ):
            # Stop live microphone & speech whenever hiding to tray so nothing keeps talking invisibly
            try:
                self.stop_all_voice_modes(exit_talk_only=False)
            except Exception:
                pass
            self._ensure_system_tray()
            self.hide()
            event.ignore()
            if not getattr(self, '_tray_hint_shown', False):
                self._tray_hint_shown = True
                self.show_desktop_toast(
                    'Fairybread Minimized to Tray',
                    'Fairybread is still running in the system tray. Right-click the tray icon to Expand or Exit.',
                )
            return
        try:
            self.stop_all_voice_modes(exit_talk_only=True)
        except Exception:
            try:
                from voice_service import stop_speaking
                stop_speaking()
            except Exception:
                pass
        if force_quit and self.worker is not None:
            try:
                self.worker.succeeded.disconnect()
                self.worker.failed.disconnect()
                self.worker.finished.disconnect()
            except Exception:
                pass
            try:
                if hasattr(self.worker, 'terminate'):
                    self.worker.terminate()
                self.worker.wait(500)
            except Exception:
                pass
            self.worker = None
        try:
            from cost_service import unregister_cost_listener
            cb = getattr(self, '_cost_listener_cb', None)
            if cb is not None:
                unregister_cost_listener(cb)
        except Exception:
            pass
        for vw in list(getattr(self, '_voice_threads', []) or []):
            try:
                if force_quit:
                    vw.wait(500)
                    if vw.isRunning():
                        vw.terminate()
                        vw.wait(300)
                else:
                    vw.wait(1200)
            except Exception:
                pass
        for tmr_attr in ('idle_timer', 'idle_auto_timer', 'pulse_timer', 'external_sync_timer'):
            tmr = getattr(self, tmr_attr, None)
            if tmr is not None:
                try:
                    tmr.stop()
                except Exception:
                    pass
        self.idle_manager.wipe_ram()
        if hasattr(self, '_tray_icon') and self._tray_icon is not None:
            try:
                self._tray_icon.hide()
            except Exception:
                pass
        app_inst = QApplication.instance()
        srv = getattr(app_inst, '_single_instance_server', None) if app_inst is not None else None
        if srv is not None:
            try:
                srv.close()
            except Exception:
                pass
            app_inst._single_instance_server = None
        event.accept()
        if os.environ.get('QT_QPA_PLATFORM') != 'offscreen' and app_inst is not None:
            QTimer.singleShot(0, app_inst.quit)


def _seed_demo_store(store: SessionStore):
    """Ensure the demo store includes the Kuiper Belt pinned preview from the design mockup."""
    for s in store.sessions:
        if 'Kuiper Belt' in s.get('title', ''):
            if not s.get('pinned'):
                s['pinned'] = True
                store.save()
            store.select(s['id'])
            return
    sid = store.selected
    ctx = store.context(sid)
    if not store.messages(sid):
        ctx.append_exchange(
            'How long to place GPT in the Kuiper Belt?',
            'Assuming you managed the logistics, after a short burn it would take approximately six years for GPT to reach the Kuiper Belt.',
            speaker_messages=[
                {
                    'speaker_id': 'gemini',
                    'provider_id': 'gemini',
                    'phase': 'initial',
                    'content': 'New Horizons took 9.5 years to reach Pluto at 39 AU; a dedicated high-energy burn puts inner Kuiper Belt objects around 6 years out.',
                },
                {
                    'speaker_id': 'openai',
                    'provider_id': 'openai',
                    'phase': 'peer_reply',
                    'content': 'Agreed with Gemini: 6 years is realistic assuming a Jupiter gravity assist and a light payload.',
                },
            ],
            contributors=['gemini', 'openai']
        )
        for s in store.sessions:
            if s['id'] == sid:
                s['title'] = 'Kuiper Belt real estate'
                s['pinned'] = True
        store.save()


def _trigger_zero_touch_autofallback(trigger: str, exc_type: str, exc_msg: str, tb_str: str, session_id: str = 'legacy') -> None:
    """Write forensic crash_report.json + post_reboot_task.json and invoke palace_watchdog.py --auto-rollback."""
    try:
        import subprocess
        from palace_ouroboros import write_crash_report, write_post_reboot_task
        write_crash_report(
            trigger=trigger,
            exc_type=exc_type,
            exc_message=exc_msg,
            traceback_str=tb_str,
        )
        write_post_reboot_task(
            origin='crash_autofallback',
            chat_session_id=session_id,
            user_request_summary='Automatic recovery from crashed agent patch',
            what_was_attempted=f'{exc_type}: {exc_msg}',
            instructions_for_agents=[
                'Examine the Zero-Touch Autofallback crash report above and the relevant source code lines.',
                'Review what you were doing when the patch crashed, explain the root cause to the user, and propose a safe fix.',
            ],
            chain_depth=1,
        )
        wd_script = Path(__file__).with_name('palace_watchdog.py')
        if wd_script.exists():
            subprocess.Popen(
                [sys.executable, str(wd_script), '--auto-rollback'],
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
    except Exception:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description='Palace Windows interface')
    parser.add_argument('--demo', action='store_true', help='Local simulated responses in separate preview storage; no credentials or APIs.')
    args = parser.parse_args(argv)
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('BrettMoore.Fairybread.Palace.Desktop.v3')
        except Exception:
            pass
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Fairybread')
    app.setFont(QFont('Segoe UI', 10))
    try:
        app.setWindowIcon(fairybread_app_qicon())
    except Exception:
        pass

    server_name = 'FairybreadPalaceDesktopSingleInstance_v1'
    single_server = None
    if (
        not args.demo
        and os.environ.get('QT_QPA_PLATFORM') != 'offscreen'
        and QLocalServer is not None
        and QLocalSocket is not None
    ):
        probe = QLocalSocket()
        probe.connectToServer(server_name)
        if probe.waitForConnected(250):
            try:
                probe.write(b'ACTIVATE\n')
                probe.flush()
                probe.waitForBytesWritten(250)
                probe.disconnectFromServer()
            except Exception:
                pass
            return 0
        try:
            QLocalServer.removeServer(server_name)
        except Exception:
            pass
        single_server = QLocalServer(app)
        if single_server.listen(server_name):
            app._single_instance_server = single_server
        else:
            single_server = None

    window_ref = [None]
    orig_excepthook = sys.excepthook

    def _palace_runtime_excepthook(exc_type, exc_value, exc_tb):
        import traceback
        tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        win = window_ref[0]
        soak_until = float(getattr(win, '_post_patch_soak_until', 0.0) or 0.0) if win is not None else 0.0
        sid = str(getattr(win, 'session_id', 'legacy') or 'legacy') if win is not None else 'legacy'
        if time.time() <= soak_until:
            _trigger_zero_touch_autofallback(
                trigger='runtime_soak_exception',
                exc_type=getattr(exc_type, '__name__', str(exc_type)),
                exc_msg=str(exc_value),
                tb_str=tb_str,
                session_id=sid,
            )
            os._exit(2)
        orig_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _palace_runtime_excepthook

    try:
        if args.demo:
            import os as _os
            from bootstrap import build_palace
            from providers import ProviderResponse

            class PreviewProvider:
                def __init__(self, label):
                    self.label = label

                def generate(self, prompt):
                    import time as _t
                    _t.sleep(0.2)
                    return ProviderResponse(
                        text='Assuming you managed the logistics, after a short burn it would take approximately six years for GPT to reach the Kuiper Belt.',
                        provider=self.label.lower()
                    )

            preview_root = Path(_os.environ['LOCALAPPDATA']) / 'Palace' / 'ui-preview'
            store = SessionStore(preview_root)
            _seed_demo_store(store)
            proposal_service = MemoryProposalService(
                preview_root / 'memory_proposals.jsonl'
            )
            window = PalaceWindow(
                store,
                lambda context: build_palace(
                    {
                        'gemini': PreviewProvider('Gemini'),
                        'openai': PreviewProvider('OpenAI'),
                    },
                    context_service=context,
                ),
                {'gemini': True, 'openai': True, 'groq': 'inactive'},
                demo=True,
                proposal_service=proposal_service,
            )
        else:
            window = PalaceWindow()
        window_ref[0] = window
    except Exception as exc:
        import traceback
        _trigger_zero_touch_autofallback(
            trigger='startup_constructor_crash',
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
            tb_str=traceback.format_exc(),
        )
        return 1
    window.show()
    if single_server is not None:
        def _on_second_instance():
            while single_server.hasPendingConnections():
                sock = single_server.nextPendingConnection()
                if sock is not None:
                    try:
                        sock.readAll()
                        sock.close()
                    except Exception:
                        pass
            window.restore_from_tray()
        single_server.newConnection.connect(_on_second_instance)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
