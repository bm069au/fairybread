"""Palace desktop interface. Provider and memory work remains in core services."""
import argparse
import html
import json
import os
from pathlib import Path
import re
import sys
import time
import webbrowser

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QSize, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QSystemTrayIcon, QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
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
from palace_config import (
    CONFIG_PATH,
    DEFAULT_AI_SQUADS,
    IDLE_CREDIT_LIMIT_CHOICES,
    IDLE_DURATION_CHOICES,
    IDLE_TOKEN_LIMIT_CHOICES,
    PROVIDER_CATALOG,
    load_ai_squads,
    load_idle_settings,
    load_mission_ethics,
    load_provider_configs,
    load_tool_settings,
    load_ui_settings,
    save_ai_squads,
    save_idle_settings,
    save_mission_ethics,
    save_provider_config,
    save_tool_settings,
    save_ui_settings,
    set_provider_enabled,
)
from session_store import SessionStore


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


class SidebarSessionList(QListWidget):
    """QListWidget supporting drag-and-drop conversation reordering and dropping conversations onto Projects."""
    sessions_reordered = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event):
        dragged_item = self.currentItem()
        dragged_key = str(dragged_item.data(Qt.ItemDataRole.UserRole) or '') if dragged_item else ''
        if not dragged_key or dragged_key.startswith('proj:'):
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
            if k.startswith('proj:'):
                p_val = k.split(':', 1)[1]
                active_proj = p_val if p_val else None
            elif k:
                assigned = explicit_proj if (has_explicit_proj and k == dragged_key) else active_proj
                ordered.append((k, assigned))

        self.sessions_reordered.emit(ordered)


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
        self.setAccessibleName('Message to Palace')
        self.setPlaceholderText('Ask anything, @ to mention, or drop files')
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFixedHeight(28)
        self.textChanged.connect(self._adjust_height)

    def _adjust_height(self):
        doc_height = int(self.document().size().height()) + 4
        target = max(28, min(110, doc_height))
        if self.height() != target:
            self.setFixedHeight(target)

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


class ManageAIsDialog(QDialog):
    """Multi-page Palace Settings dialog (including AI Providers and dedicated Idle Mode page)."""

    SETTINGS_PAGES = [
        'General',
        'Voice & Audio',
        'Appearance',
        'Email & Notifications',
        'AI Providers',
        'Profiles',
        'Work Mode & Tools',
        'Memory & History',
        'Experimental Mode',
        'Agent Bridge & Permissions',
        'Backup & Restore',
    ]

    def __init__(
        self,
        parent=None,
        config_path: Path = CONFIG_PATH,
        credential_store: CredentialStore | None = None,
        initial_page: str = 'AI Providers',
        idle_memory: IdleMemoryStore | None = None,
    ):
        super().__init__(parent)
        self.config_path = config_path
        self.credential_store = credential_store or CredentialStore()
        self.idle_memory = idle_memory or IdleMemoryStore()
        self._settings_mic_session = None
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
        self._build_voice_audio_page()
        self._build_appearance_page()
        self._build_notifications_page()
        self._build_ai_providers_page()
        self._build_profiles_page()
        self._build_work_tools_page()
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
            'Voice': 'Voice & Audio',
            'Audio': 'Voice & Audio',
            'Microphone': 'Voice & Audio',
            'Notifications': 'Email & Notifications',
            'Email': 'Email & Notifications',
            'Permissions': 'Agent Bridge & Permissions',
            'Agent Bridge': 'Agent Bridge & Permissions',
            'Idle Mode': 'Experimental Mode',
            'Idle': 'Experimental Mode',
            'Experimental': 'Experimental Mode',
        }
        resolved_page = page_aliases.get(initial_page, initial_page)
        target_idx = self.SETTINGS_PAGES.index(resolved_page) if resolved_page in self.SETTINGS_PAGES else 4
        self.nav_list.setCurrentRow(target_idx)

    def _stop_settings_mic_test(self):
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
        self._stop_settings_mic_test()
        super().reject()

    def closeEvent(self, event):
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

        enter_form = QFormLayout()
        self.enter_mode_combo = QComboBox()
        self.enter_mode_combo.addItem('Enter submits message · Shift+Enter adds new line (Default)', True)
        self.enter_mode_combo.addItem('Shift+Enter submits message · Enter adds new line', False)
        self.enter_mode_combo.setCurrentIndex(0 if ui_cfg.get('enter_to_send', True) else 1)
        enter_form.addRow('Composer Enter key behavior:', self.enter_mode_combo)
        lay.addLayout(enter_form)

        jump_voice_btn = QPushButton('🎙️ Open Voice & Audio Settings (Select Microphone, Live Level Meter & Speaker Volume)…')
        jump_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        jump_voice_btn.setToolTip('Switch to the dedicated Voice & Audio tab to test your microphone and speaker')
        jump_voice_btn.clicked.connect(lambda: self.nav_list.setCurrentRow(self.SETTINGS_PAGES.index('Voice & Audio')))
        lay.addWidget(jump_voice_btn)

        lay.addStretch()
        self.pages.addWidget(w)

    def _build_voice_audio_page(self):
        from voice_service import (
            LiveAudioSession,
            list_audio_input_devices,
            list_available_tts_voices,
            load_voice_settings,
            save_voice_settings,
            speak_agent_response,
            stop_speaking,
            transcribe_audio_file,
        )

        w, lay = self._make_simple_page(
            '🎙️ Voice & Audio (Live Voice Mode, Microphone & Speaker)',
            'Select and test your microphone with a live visual volume meter, boost quiet mic gain, and configure agent voice output.'
        )
        v_cfg = load_voice_settings(self.config_path)

        # --- SECTION 1: MICROPHONE & LIVE VOICE INPUT ---
        mic_card = QFrame()
        mic_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        mc_lay = QVBoxLayout(mic_card)
        mc_lay.setSpacing(8)
        mc_hdr = QLabel('<b>1. Microphone Input &amp; Live Level Meter (Used by Live Voice Mode &amp; Dictation)</b>')
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

        self.mic_transcribe_test_btn = QPushButton('🧪 Record 3s & Test Transcription')
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

        def _save_current_voice_fields():
            save_voice_settings(
                {
                    'voice_name': self.voice_name_combo.currentText(),
                    'microphone_device': self.mic_device_combo.currentText(),
                    'mic_gain_percent': int(self.mic_gain_slider.value()),
                    'silence_timeout_ms': int(self.silence_timeout_slider.value()),
                    'volume_percent': int(self.voice_vol_slider.value()),
                    'auto_speak_responses': self.auto_speak_check.isChecked(),
                },
                config_path=self.config_path,
            )

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
        lay.addWidget(mic_card)

        # --- SECTION 2: SPEAKER / AGENT VOICE OUTPUT ---
        spk_card = QFrame()
        spk_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:10px;')
        sc_lay = QVBoxLayout(spk_card)
        sc_lay.setSpacing(8)
        sc_hdr = QLabel('<b>2. Speaker &amp; Agent Voice Output (TTS)</b>')
        sc_hdr.setTextFormat(Qt.TextFormat.RichText)
        sc_lay.addWidget(sc_hdr)

        s_form = QFormLayout()
        voice_row = QHBoxLayout()
        self.voice_name_combo = QComboBox()
        self.voice_name_combo.setToolTip('Choose the system voice used when Fairybread speaks responses aloud')
        for vname in list_available_tts_voices():
            self.voice_name_combo.addItem(vname, vname)
        cur_v = str(v_cfg.get('voice_name', 'System Default'))
        v_idx = self.voice_name_combo.findText(cur_v)
        if v_idx >= 0:
            self.voice_name_combo.setCurrentIndex(v_idx)

        test_voice_btn = QPushButton('🔊 Test Speaker Voice')
        test_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_voice_btn.setToolTip('Play a test sentence through your speakers at the selected volume')

        stop_voice_btn = QPushButton('⏹ Stop Voice')
        stop_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_voice_btn.setToolTip('Immediately stop any active spoken response')
        stop_voice_btn.clicked.connect(stop_speaking)

        def _test_tts():
            _save_current_voice_fields()
            speak_agent_response('Hello Brett, Fairybread live voice mode and speaker output are working clearly.', config_path=self.config_path)

        test_voice_btn.clicked.connect(_test_tts)
        voice_row.addWidget(self.voice_name_combo, 1)
        voice_row.addWidget(test_voice_btn)
        voice_row.addWidget(stop_voice_btn)
        s_form.addRow('Speaker Voice:', voice_row)

        vol_row = QHBoxLayout()
        self.voice_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.voice_vol_slider.setRange(0, 100)
        self.voice_vol_slider.setToolTip('Adjust how loud Fairybread’s spoken voice is (0% – 100%)')
        cur_vol = int(v_cfg.get('volume_percent', 100))
        self.voice_vol_slider.setValue(cur_vol)
        self.voice_vol_label = QLabel(f'{cur_vol}%')
        self.voice_vol_label.setFixedWidth(48)
        self.voice_vol_slider.valueChanged.connect(lambda val: self.voice_vol_label.setText(f'{val}%'))
        vol_row.addWidget(self.voice_vol_slider, 1)
        vol_row.addWidget(self.voice_vol_label)
        s_form.addRow('Speaker Volume:', vol_row)
        sc_lay.addLayout(s_form)

        self.auto_speak_check = QCheckBox(
            'Always read final synthesized agent responses aloud (Note: Live Voice Mode automatically speaks replies aloud even if this is unchecked)',
            checked=bool(v_cfg.get('auto_speak_responses', False)),
        )
        self.auto_speak_check.setToolTip('When checked, even typed prompts will have their final answer read aloud automatically')
        sc_lay.addWidget(self.auto_speak_check)
        lay.addWidget(spk_card)

        lay.addStretch()
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
        test_btn = QPushButton('🧪 Save & Send Test Notification (Desktop + Email)')
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

    def _build_work_tools_page(self):
        w, lay = self._make_simple_page(
            'Work Mode & Agent Tools',
            'Configure the sandboxed tools available to AIs in Work Mode, Normal Mode, and Idle Mode.'
        )
        tool_cfg = load_tool_settings(self.config_path)
        self.tool_checks: dict[str, QCheckBox] = {}

        items = [
            ('palace_source_tool', '🔧 Fairybread Source Code Tool (Read-only inspection of C:\\Palace_Idle_Sandbox\\source_mirror\\)'),
            ('shared_palace_files_tool', '🏛 Shared Memory File Tools (Read/write persistent notes & proposals)'),
            ('project_folder_tool', '📁 Attached Project Folder Tool (Read-only workspace access to folders attached to Projects; M: blocked)'),
            ('owner_email_tool', '✉ Agent-to-Owner Email Tool (Send requests & file links to Agent Mail, max 5 per 30m)'),
            ('github_tool', '🐙 GitHub & Git Workflow Tools (Stage 3 Roadmap — Read/PR staging with Owner Approval)'),
            ('external_mail_tool', '📬 Gmail / MS Mail & Web Research Tools (Stage 4 Roadmap — Read & Draft-only with Owner Approval)'),
        ]
        for key, label in items:
            chk = QCheckBox(label)
            chk.setChecked(bool(tool_cfg.get(key, False)))
            if key in {'github_tool', 'external_mail_tool'}:
                chk.setToolTip('Planned for Stage 3 / Stage 4 tool expansion.')
            self.tool_checks[key] = chk
            lay.addWidget(chk)

        lay.addStretch()
        self.pages.addWidget(w)

    def _build_memory_history_page(self):
        w, lay = self._make_simple_page(
            'Memory & Personalization',
            'Configure how Fairybread manages shared contextual memory across all Council AIs (like ChatGPT & Antigravity).'
        )
        mem_card = QFrame()
        mem_card.setStyleSheet('background:#131720; border:1px solid #262c3a; border-radius:8px; padding:12px;')
        mc_lay = QVBoxLayout(mem_card)
        mc_lay.setSpacing(10)

        row1 = QHBoxLayout()
        lbl1 = QLabel(
            '<b>Enable memory</b><br>'
            '<span style="color:#8b949e; font-size:12px;">Let all Council AIs personalize your experience based on your chats, files, and connected apps.</span>'
        )
        lbl1.setWordWrap(True)
        lbl1.setTextFormat(Qt.TextFormat.RichText)
        self.enable_shared_mem_check = QCheckBox('Enabled')
        self.enable_shared_mem_check.setChecked(True)
        self.enable_shared_mem_check.setToolTip('Toggle Shared Memory across conversations')
        row1.addWidget(lbl1, 1)
        row1.addWidget(self.enable_shared_mem_check)
        mc_lay.addLayout(row1)

        row2 = QHBoxLayout()
        lbl2 = QLabel(
            '<b>Memory summary</b><br>'
            '<span style="color:#8b949e; font-size:12px;">View and directly edit the overview of what Fairybread has learned about you (Overview, How You Like to Work, Software Projects).</span>'
        )
        lbl2.setWordWrap(True)
        lbl2.setTextFormat(Qt.TextFormat.RichText)
        manage_sum_btn = QPushButton('Manage')
        manage_sum_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_sum_btn.setToolTip('View & edit Memory summary')

        def _open_summary():
            parent = self.parent()
            if parent is not None and hasattr(parent, 'show_memory_summary_dialog'):
                parent.show_memory_summary_dialog()

        manage_sum_btn.clicked.connect(_open_summary)
        row2.addWidget(lbl2, 1)
        row2.addWidget(manage_sum_btn)
        mc_lay.addLayout(row2)
        lay.addWidget(mem_card)

        lay.addWidget(QCheckBox('Save standard chat transcripts locally per conversation', checked=True))
        lay.addStretch()
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
            'Share Fairybread source code with agents (Read-Only — allows agents to inspect code and propose improvements)'
        )
        self.idle_share_code_check.setToolTip('Give Experimental Mode agents read-only access to Fairybread source code')
        self.idle_share_code_check.setChecked(bool(idle_cfg.get('share_source_code', False)))
        lay.addWidget(self.idle_share_code_check)

        self.idle_live_patch_check = QCheckBox(
            '⚡ Owner-Only: Allow agents to apply live code patches, hot-reboot & auto-continue past reboot'
        )
        self.idle_live_patch_check.setToolTip('Allow Experimental Mode agents to stage verified patches, hot-reboot, and resume automatically')
        self.idle_live_patch_check.setChecked(bool(idle_cfg.get('allow_live_self_modify', False)))
        self.idle_live_patch_check.hide()

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
            get_mcp_json_snippet,
            install_antigravity_bridge,
            install_claude_desktop_bridge,
            load_bridge_settings,
            save_bridge_settings,
        )

        w, lay = self._make_simple_page(
            '🔗 External Agent Bridge (MCP) & Permissions',
            'Let your Google Antigravity, Anthropic Claude Desktop / Claude Code, or OpenAI ChatGPT Desktop / Codex CLI consult your Fairybread council and render high-res graphics.'
        )
        b_cfg = load_bridge_settings(self.config_path)

        self.bridge_enabled_check = QCheckBox(
            'Enable External Agent Bridge (MCP Server & Local CLI Bridge)',
            checked=bool(b_cfg.get('enabled', True)),
        )
        lay.addWidget(self.bridge_enabled_check)

        self.bridge_council_check = QCheckBox(
            'Allow external agents to consult the Fairybread Multi-AI Council (fairybread_ask_council)',
            checked=bool(b_cfg.get('allow_council_query', True)),
        )
        lay.addWidget(self.bridge_council_check)

        self.bridge_image_check = QCheckBox(
            'Allow external agents to render 300-DPI images, social banners & wallpapers (fairybread_generate_image)',
            checked=bool(b_cfg.get('allow_image_generation', True)),
        )
        lay.addWidget(self.bridge_image_check)

        self.bridge_email_check = QCheckBox(
            'Allow external agents to run Exhaustive Email Searches when configured (fairybread_search_email)',
            checked=bool(b_cfg.get('allow_email_search', True)),
        )
        lay.addWidget(self.bridge_email_check)

        self.bridge_memory_check = QCheckBox(
            'Allow external agents to query Shared Memory (fairybread_search_memory)',
            checked=bool(b_cfg.get('allow_memory_search', True)),
        )
        lay.addWidget(self.bridge_memory_check)

        self.bridge_code_upgrade_check = QCheckBox(
            'Developer Mode: Allow external agent to stage Fairybread code upgrades (Locked by default)',
            checked=bool(b_cfg.get('allow_code_self_upgrade', False)),
        )
        lay.addWidget(self.bridge_code_upgrade_check)

        btn_row = QHBoxLayout()
        ag_btn = QPushButton('🔗 Connect Google Antigravity')
        ag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        claude_btn = QPushButton('🔗 Connect Claude Desktop / Claude Code')
        claude_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_mcp_btn = QPushButton('📋 Copy MCP Config (ChatGPT Desktop / Cursor)')
        copy_mcp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(ag_btn)
        btn_row.addWidget(claude_btn)
        btn_row.addWidget(copy_mcp_btn)
        lay.addLayout(btn_row)

        self.bridge_status_label = QLabel('')
        self.bridge_status_label.setWordWrap(True)
        self.bridge_status_label.setStyleSheet('font-size: 12px; color: #22c55e;')
        lay.addWidget(self.bridge_status_label)

        def _connect_ag():
            self._save_bridge_fields()
            ok, msg = install_antigravity_bridge()
            self.bridge_status_label.setStyleSheet(f'font-size: 12px; color: {"#22c55e" if ok else "#f85149"};')
            self.bridge_status_label.setText(f'{"✓" if ok else "⚠"} {msg}')

        def _connect_claude():
            self._save_bridge_fields()
            ok, msg = install_claude_desktop_bridge()
            self.bridge_status_label.setStyleSheet(f'font-size: 12px; color: {"#22c55e" if ok else "#f85149"};')
            self.bridge_status_label.setText(f'{"✓" if ok else "⚠"} {msg}')

        def _copy_mcp():
            self._save_bridge_fields()
            QApplication.clipboard().setText(get_mcp_json_snippet())
            self.bridge_status_label.setStyleSheet('font-size: 12px; color: #58a6ff;')
            self.bridge_status_label.setText('✓ Copied MCP server JSON snippet to clipboard!')

        ag_btn.clicked.connect(_connect_ag)
        claude_btn.clicked.connect(_connect_claude)
        copy_mcp_btn.clicked.connect(_copy_mcp)

        lay.addWidget(QLabel(
            '<b>Idle Mode Privacy &amp; Storage Boundaries:</b>\n'
            '• Idle Mode live transcripts are strictly isolated from Normal Mode.\n'
            '• Shared Idle Memory is capped by your Idle storage slider.'
        ))
        lay.addStretch()
        self.pages.addWidget(w)

    def _save_bridge_fields(self):
        from fairybread_mcp import save_bridge_settings
        if not hasattr(self, 'bridge_enabled_check'):
            return
        save_bridge_settings(
            {
                'enabled': self.bridge_enabled_check.isChecked(),
                'allow_council_query': self.bridge_council_check.isChecked(),
                'allow_image_generation': self.bridge_image_check.isChecked(),
                'allow_email_search': self.bridge_email_check.isChecked(),
                'allow_memory_search': self.bridge_memory_check.isChecked(),
                'allow_code_self_upgrade': self.bridge_code_upgrade_check.isChecked(),
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
        self.backup_include_memory_check = QCheckBox('Shared Memory, Chats & Idle Memory', checked=True)
        self.backup_include_settings_check = QCheckBox('All Settings & API Keys (AES-256 Password Locked)', checked=True)
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
        btn_row.addWidget(export_btn)
        btn_row.addWidget(restore_btn)
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

        export_btn.clicked.connect(_do_export)
        restore_btn.clicked.connect(_do_restore)
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
        save_tool_settings(
            {k: chk.isChecked() for k, chk in self.tool_checks.items()},
            config_path=self.config_path,
        )
        if hasattr(self, 'voice_name_combo'):
            from voice_service import save_voice_settings
            save_voice_settings(
                {
                    'voice_name': self.voice_name_combo.currentText(),
                    'microphone_device': self.mic_device_combo.currentText(),
                    'mic_gain_percent': int(self.mic_gain_slider.value()) if hasattr(self, 'mic_gain_slider') else 150,
                    'silence_timeout_ms': int(self.silence_timeout_slider.value()) if hasattr(self, 'silence_timeout_slider') else 1500,
                    'volume_percent': int(self.voice_vol_slider.value()),
                    'auto_speak_responses': self.auto_speak_check.isChecked(),
                },
                config_path=self.config_path,
            )
        self._stop_settings_mic_test()
        self.accept()


class PalaceWindow(QMainWindow):
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
        self.store = store or SessionStore()
        self.proposal_service = proposal_service or MemoryProposalService()
        default_idle_mem_path = (self.store.root / 'idle_notebooks' / 'ai_idle_memory.json') if store is not None else None
        self.idle_memory = idle_memory or IdleMemoryStore(default_idle_mem_path)
        self.idle_manager = IdleSessionManager(idle_memory=self.idle_memory, config_path=self.config_path)
        self.session_id = self.store.selected
        self.palace_factory = palace_factory or self._build_palace
        self.attachments = []
        self.worker = None
        self.last_answer = ''
        self.last_question = ''
        self.pending_prompt = ''
        self.pending_history = True
        self.provider_labels = {}
        self.provider_details = {}
        self.reply_archive = []
        self.chat_items = []
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
        self.session_list.currentItemChanged.connect(self.change_session)
        self.session_list.itemClicked.connect(self._on_sidebar_item_clicked)
        self.session_list.sessions_reordered.connect(self._on_sidebar_sessions_reordered)
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
        self.idle_switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.idle_switch_btn.setToolTip('Toggle Autonomous Experimental Mode')
        self.idle_switch_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 10px; border-radius: 6px; font-weight: 600; font-size: 11.5px; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #11281b; color: #22c55e; border: 1px solid #22c55e; font-weight: 700; }'
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
            '(For quick side-thoughts that <i>should</i> be saved without prior code context, use <b>Tangent</b> below instead.)'
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
        self.chat.anchorClicked.connect(self._on_chat_anchor_clicked)
        self.chat.anchor_action_requested.connect(lambda s: self._on_chat_anchor_clicked(QUrl(s)))
        normal_lay.addWidget(self.chat, 1)

        # --- UNIFIED ROUNDED COMPOSER CARD ---
        composer_card = QFrame()
        composer_card.setObjectName('composerCard')
        card_layout = QVBoxLayout(composer_card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(6)

        self.attachment_list = QListWidget()
        self.attachment_list.setObjectName('attachmentList')
        self.attachment_list.setAccessibleName('Attached files; select a file then Remove selected')
        self.attachment_list.setMaximumHeight(60)
        self.attachment_list.hide()
        card_layout.addWidget(self.attachment_list)

        self.composer = Composer(enter_to_send=bool(ui_cfg.get('enter_to_send', True)))
        self.composer.setToolTip('Type message, paste image (Ctrl+V), or drop files')
        self.composer.files_added.connect(self.add_files)
        self.composer.image_pasted.connect(self.add_pasted_image)
        self.composer.send_requested.connect(self.send_message)
        self.composer.unsupported_paste.connect(lambda: self.show_notice('Clipboard image could not be decoded. Attach a picture, text document, PDF, or Word file.'))
        card_layout.addWidget(self.composer)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 2, 0, 0)
        controls.setSpacing(6)
        self.attach_button = QPushButton('+')
        self.attach_button.setObjectName('plusAttachButton')
        self.attach_button.setToolTip('Attach files or pictures (Ctrl+O)')
        self.attach_button.clicked.connect(self.choose_files)
        controls.addWidget(self.attach_button)

        self.remove_button = QPushButton('✕ Remove file')
        self.remove_button.setObjectName('iconButton')
        self.remove_button.setToolTip('Remove selected attachment')
        self.remove_button.clicked.connect(self.remove_attachment)
        self.remove_button.hide()
        controls.addWidget(self.remove_button)

        self.ai_pill_button = QPushButton('Choose AIs  ▾')
        self.ai_pill_button.setObjectName('aiPillButton')
        self.ai_pill_button.setMinimumWidth(126)
        self.ai_pill_button.setToolTip('Select active AIs or Squad')
        self.ai_pill_button.clicked.connect(self._show_choose_ais_menu)
        controls.addWidget(self.ai_pill_button)

        self.deliberate_pill_btn = QPushButton(' Council')
        self.deliberate_pill_btn.setIcon(council_qicon(True))
        self.deliberate_pill_btn.setIconSize(QSize(15, 15))
        self.deliberate_pill_btn.setCheckable(True)
        self.deliberate_pill_btn.setChecked(True)
        self.deliberate_pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deliberate_pill_btn.setToolTip('2-round peer review (ON) / Direct (OFF)')
        self.deliberate_pill_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #231536; color: #a855f7; border: 1px solid #a855f7; }'
        )
        self.deliberate_pill_btn.toggled.connect(self._on_deliberate_pill_toggled)
        controls.addWidget(self.deliberate_pill_btn)

        self.tangent_btn = QPushButton(' Tangent')
        self.tangent_btn.setIcon(tangent_qicon(False))
        self.tangent_btn.setIconSize(QSize(15, 15))
        self.tangent_btn.setCheckable(True)
        self.tangent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tangent_btn.setToolTip('Side question (ignores prior chat context)')
        self.tangent_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #29230f; color: #eab308; border: 1px solid #eab308; }'
        )
        self.tangent_btn.toggled.connect(lambda on: self.tangent_btn.setIcon(tangent_qicon(on)))
        controls.addWidget(self.tangent_btn)

        self.palace_code_btn = QPushButton(' Code')
        self.palace_code_btn.setIcon(code_shield_qicon(False))
        self.palace_code_btn.setIconSize(QSize(15, 15))
        self.palace_code_btn.setCheckable(True)
        self.palace_code_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.palace_code_btn.setToolTip('Let AIs read Fairybread source code')
        self.palace_code_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #6e7681; border: 1px solid #21262d; '
            'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; } '
            'QPushButton:checked { background: #0f2930; color: #06b6d4; border: 1px solid #06b6d4; }'
        )
        self.palace_code_btn.toggled.connect(self._on_palace_code_btn_toggled)
        controls.addWidget(self.palace_code_btn)

        self.current_search_depth = 'default'
        self.search_depth_btn = QPushButton('🔍 Default ▾')
        self.search_depth_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_depth_btn.setToolTip('Web search depth (Default / Moderate / Deep)')
        self.search_depth_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #8b949e; border: 1px solid #21262d; '
            'padding: 4px 9px; border-radius: 6px; font-size: 11.5px; font-weight: 600; } '
            'QPushButton:hover { color: #c9d1d9; border-color: #30363d; }'
        )
        self.search_depth_btn.clicked.connect(self._show_search_depth_menu)
        controls.addWidget(self.search_depth_btn)

        self.history_toggle = QCheckBox('History')
        self.history_toggle.setChecked(True)
        self.history_toggle.setToolTip('Use & save session history')
        self.history_toggle.toggled.connect(self._on_history_toggle_changed)
        self.history_toggle.hide()
        controls.addWidget(self.history_toggle)

        self.peer_rounds_toggle = QCheckBox('Peer deliberation')
        self.peer_rounds_toggle.setChecked(True)
        self.peer_rounds_toggle.setToolTip('2-round peer review')
        self.peer_rounds_toggle.toggled.connect(self._on_peer_rounds_toggle_changed)
        self.peer_rounds_toggle.hide()
        controls.addWidget(self.peer_rounds_toggle)

        controls.addStretch()

        # Live Voice / Microphone Soundwave Level Indicator (visible whenever Dictation or Live Voice is active)
        self.voice_level_badge = QLabel('')
        self.voice_level_badge.setToolTip('Live microphone volume meter')
        self.voice_level_badge.setStyleSheet(
            'font-family: Consolas, monospace; font-size: 11.5px; font-weight: 700; color: #22c55e; '
            'background: #11281b; border: 1px solid #22c55e; border-radius: 6px; padding: 3px 8px;'
        )
        self.voice_level_badge.hide()
        controls.addWidget(self.voice_level_badge)

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

        self.live_voice_button = QPushButton()
        self.live_voice_button.setIcon(voice_wave_qicon(False))
        self.live_voice_button.setIconSize(QSize(16, 16))
        self.live_voice_button.setCheckable(True)
        self.live_voice_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.live_voice_button.setFixedSize(30, 30)
        self.live_voice_button.setToolTip('Live hands-free voice chat')
        self.live_voice_button.setStyleSheet(
            'QPushButton { background: #d0d7de; border: 1px solid #d0d7de; border-radius: 15px; } '
            'QPushButton:hover { background: #f0f6fc; border-color: #f0f6fc; } '
            'QPushButton:checked { background: #11281b; border: 2px solid #22c55e; }'
        )
        self.live_voice_button.toggled.connect(self._toggle_live_voice_mode)
        controls.addWidget(self.live_voice_button)

        self.send_button = QPushButton('↑')
        self.send_button.setObjectName('sendButton')
        self.send_button.setToolTip('Send message (Enter)')
        self.send_button.setFixedSize(30, 30)
        self.send_button.clicked.connect(self.send_message)
        controls.addWidget(self.send_button)
        card_layout.addLayout(controls)
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
        back_chat_from_idle_btn.clicked.connect(lambda: self.workspace_tabs.setCurrentIndex(0))
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
        self.idle_live_patch_btn.hide()

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
        self.mail_list.setMinimumWidth(290)
        self.mail_list.setToolTip('Messages and improvement proposals sent to you by Idle Mode agents')
        self.mail_list.currentItemChanged.connect(self._on_mail_item_selected)
        mail_split.addWidget(self.mail_list)

        mail_reader = QFrame()
        mail_reader.setObjectName('composerCard')
        reader_lay = QVBoxLayout(mail_reader)
        reader_lay.setContentsMargins(14, 12, 14, 12)
        reader_lay.setSpacing(8)

        hdr_row = QHBoxLayout()
        self.mail_header_label = QLabel('Select an email from an Idle Mode agent to read.')
        self.mail_header_label.setWordWrap(True)
        self.mail_header_label.setTextFormat(Qt.TextFormat.RichText)
        hdr_row.addWidget(self.mail_header_label, 1)

        self.mail_open_link_btn = QPushButton('📂 Open Linked File in Shared Idle Memory')
        self.mail_open_link_btn.setToolTip('Jump directly to the proposed file or note in Shared Idle Memory')
        self.mail_open_link_btn.setEnabled(False)
        self.mail_open_link_btn.setStyleSheet(
            'QPushButton { background: #172a3a; color: #58a6ff; border: 1px solid #58a6ff; padding: 5px 12px; border-radius: 6px; font-weight: 600; } '
            'QPushButton:disabled { background: #161922; color: #484f58; border: 1px solid #262b36; }'
        )
        self.mail_open_link_btn.clicked.connect(self._open_selected_mail_linked_file)
        hdr_row.addWidget(self.mail_open_link_btn)

        self.mail_delete_btn = QPushButton('🗑 Delete')
        self.mail_delete_btn.setEnabled(False)
        self.mail_delete_btn.setToolTip('Delete the selected email from Agent Mail')
        self.mail_delete_btn.setStyleSheet(
            'QPushButton { background: #2c1517; color: #f87171; border: 1px solid #ef4444; padding: 5px 10px; border-radius: 6px; font-weight: 600; } '
            'QPushButton:disabled { background: #161922; color: #484f58; border: 1px solid #262b36; }'
        )
        self.mail_delete_btn.clicked.connect(self._delete_selected_mail)
        hdr_row.addWidget(self.mail_delete_btn)

        self.mail_clear_all_btn = QPushButton('🧹 Clear All')
        self.mail_clear_all_btn.setToolTip('Delete all emails in Agent Mail')
        self.mail_clear_all_btn.setStyleSheet(
            'QPushButton { background: #161b22; color: #8b949e; border: 1px solid #30363d; padding: 5px 10px; border-radius: 6px; font-weight: 600; } '
            'QPushButton:hover { color: #f87171; border-color: #ef4444; }'
        )
        self.mail_clear_all_btn.clicked.connect(self._clear_all_mail)
        hdr_row.addWidget(self.mail_clear_all_btn)
        reader_lay.addLayout(hdr_row)

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
        loaded_caption = QLabel('Agents:')
        loaded_caption.setObjectName('loadedAIsLabel')
        self.providers_layout.addWidget(loaded_caption)

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

        self.bottom_token_label = ResponsiveBarLabel('Tokens: 0.0k · Spend: $0.000', on_change=self._relayout_agent_bar)
        self.bottom_token_label.setWordWrap(False)
        self.bottom_token_label.setMaximumHeight(22)
        self.bottom_token_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.bottom_token_label.setStyleSheet(
            'font-family: Consolas, monospace; font-size: 11.5px; color: #8b949e; padding: 1px 6px;'
        )
        self.bottom_token_label.setToolTip('Live Session Token & Credit Monitor')

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

        self.open_memory_summary_btn = QPushButton('📝 Memory Summary (View & Edit)…')
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
        self.approve_proposal_btn = QPushButton('✓ Approve & Store')
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
        self.load_history()
        self._refresh_idle_view()
        self._backfill_shared_memory_once()
        self._force_quit = False
        self._tray_hint_shown = False
        if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            self._ensure_system_tray()
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
        self.close()

    def _on_ouroboros_startup_ready(self):
        """Signal READY heartbeat to `palace_watchdog.py`, capture self-inspection snapshot, and process handoff."""
        try:
            from palace_ouroboros import (
                capture_palace_window_snapshot,
                read_pending_handoff,
                write_ready_heartbeat,
            )
            write_ready_heartbeat(os.getpid(), status='READY')
            # Capture a live self-inspection snapshot of the PalaceWindow widget buffer (never desktop)
            capture_palace_window_snapshot(self, tag='palace_ui_snapshot')
            handoff = read_pending_handoff(consume=True)
            if handoff:
                reboot_info = handoff.get('reboot', {})
                diff_sum = reboot_info.get('applied_diff_summary', 'Upgrade applied.')
                continuity = handoff.get('continuity', {})
                resume_prompt = str(continuity.get('resumption_prompt') or '').strip()
                self.status_label.setTextFormat(Qt.TextFormat.RichText)
                self.status_label.setToolTip(f'Ouroboros Hot-Reboot Complete: {diff_sum}')
                self.status_label.setText(
                    '<span style="color:#22c55e; font-weight:700;">✓ Ready</span>'
                )
                if resume_prompt and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
                    self.composer.setPlainText(resume_prompt)
                if continuity.get('auto_resume_idle') and os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
                    saved_turns = list(continuity.get('idle_transcript') or [])
                    saved_turns.append({
                        'speaker': 'operator',
                        'content': f'⚡ **Ouroboros Hot-Reboot Complete** — Live patch applied (`{diff_sum}`). Continuing autonomous Experimental Mode session…',
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    })
                    self.idle_manager.transcript = saved_turns
                    rem_sec = int(continuity.get('idle_remaining_seconds') or 0)
                    if rem_sec > 0:
                        self.idle_manager.remaining_seconds = rem_sec
                    self.idle_manager.tokens_used_this_session = int(continuity.get('idle_tokens_used') or 0)
                    self.idle_manager.spend_usd_this_session = float(continuity.get('idle_spend_usd') or 0.0)
                    self.workspace_tabs.setCurrentIndex(1)
                    self._refresh_idle_view()
                    QTimer.singleShot(900, lambda: self.idle_switch_btn.setChecked(True))
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
        profiles_settings_act = QAction('🎛 Profiles && AI Squads…', self)
        profiles_settings_act.triggered.connect(lambda: self.open_manage_ais('Profiles'))
        settings_menu.addAction(profiles_settings_act)
        voice_settings_act = QAction('🎙️ Voice && Audio (Microphone && Speaker)…', self)
        voice_settings_act.triggered.connect(lambda: self.open_manage_ais('Voice & Audio'))
        settings_menu.addAction(voice_settings_act)
        email_settings_act = QAction('📧 Email && Notifications…', self)
        email_settings_act.triggered.connect(lambda: self.open_manage_ais('Email & Notifications'))
        settings_menu.addAction(email_settings_act)
        bridge_settings_act = QAction('🔗 External Agent Bridge (Antigravity / Claude / ChatGPT)…', self)
        bridge_settings_act.triggered.connect(lambda: self.open_manage_ais('Agent Bridge & Permissions'))
        settings_menu.addAction(bridge_settings_act)
        idle_settings_act = QAction('🧪 Experimental Mode Settings…', self)
        idle_settings_act.triggered.connect(lambda: self.open_manage_ais('Experimental Mode'))
        settings_menu.addAction(idle_settings_act)

        help_menu = menubar.addMenu('Help')
        guide_act = QAction('📖 User Guide && Drawing Instructions…\tF1', self)
        guide_act.setShortcut(QKeySequence('F1'))
        guide_act.triggered.connect(self.show_user_guide_dialog)
        help_menu.addAction(guide_act)
        web_act = QAction('🌐 Fairybread.me (Community Forums, Skins && News) ↗', self)
        web_act.triggered.connect(lambda: webbrowser.open('https://fairybread.me'))
        help_menu.addAction(web_act)
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
        normal_mode_act.triggered.connect(lambda: self.idle_switch_btn.setChecked(False))
        self.mode_menu.addAction(normal_mode_act)
        idle_act = QAction('🧪 Experimental Mode', self.mode_menu)
        idle_act.triggered.connect(lambda: self.idle_switch_btn.setChecked(True))
        self.mode_menu.addAction(idle_act)
        self.mode_menu.addSeparator()
        self._populate_profiles_and_ais_menu(self.mode_menu)

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
        box = QMessageBox(self)
        box.setWindowTitle('About Fairybread')
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            '<h3>Fairybread (Beta) — Multi-AI Council &amp; Shared Memory Workspace</h3>'
            '<p>Created by <b>Brett Martin Moore</b>.</p>'
            '<p><b>License:</b> Open-Source / Source-Available Donationware for personal use &amp; small teams (up to 2 seats). '
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

    def _show_session_context_menu(self, list_widget: QListWidget, pos: QPoint):
        item = list_widget.itemAt(pos)
        if item is None:
            return
        raw_role = str(item.data(Qt.ItemDataRole.UserRole) or '')
        if not raw_role:
            return
        menu = QMenu(self)
        if raw_role.startswith('proj:'):
            proj_id = raw_role.split(':', 1)[1] or None
            new_in_proj = menu.addAction('+ New Conversation Here')
            attach_act = None
            detach_act = None
            if proj_id:
                cur_folder = self.store.get_project_folder(proj_id) if hasattr(self.store, 'get_project_folder') else ''
                attach_act = menu.addAction('📁 Change Attached Folder…' if cur_folder else '📁 Attach Folder to Project…')
                if cur_folder:
                    detach_act = menu.addAction('✕ Detach Folder')
            chosen = menu.exec(list_widget.mapToGlobal(pos))
            if chosen == new_in_proj:
                self.store.select_project(proj_id)
                self.new_conversation()
            elif attach_act is not None and chosen == attach_act:
                self.attach_folder_to_current_project(project_id=proj_id)
            elif detach_act is not None and chosen == detach_act:
                self.attach_folder_to_current_project(project_id=proj_id, folder_path='')
            return

        sid = raw_role
        if not hasattr(self.store, 'toggle_pin'):
            return
        is_pinned = any(s['id'] == sid and s.get('pinned') for s in self.store.sessions)
        pin_act = menu.addAction('Unpin conversation' if is_pinned else 'Pin conversation')
        move_actions = {}
        projects = getattr(self.store, 'projects', [])
        if projects and hasattr(self.store, 'assign_session_project'):
            move_menu = menu.addMenu('Move to Project…')
            for proj in projects:
                act = move_menu.addAction(f'📁 {proj["name"]}')
                move_actions[act] = proj['id']
            none_act = move_menu.addAction('General (No Project)')
            move_actions[none_act] = None
        chosen = menu.exec(list_widget.mapToGlobal(pos))
        if chosen == pin_act:
            self.store.toggle_pin(sid)
            self.refresh_sessions()
        elif chosen in move_actions:
            self.store.assign_session_project(sid, move_actions[chosen])
            self.refresh_projects()
            self.refresh_sessions()

    def _update_ai_pill_text(self):
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

        squad_dict = load_ai_squads(self.config_path)
        for _sq_key, sq_val in squad_dict.items():
            squad_title = str(sq_val.get('label') or _sq_key)
            members = list(sq_val.get('providers') or [])
            default_delib = bool(sq_val.get('deliberate', True))
            default_code = bool(sq_val.get('code_access', False))
            max_cap = int(sq_val.get('max_ais') or 0)
            avail_members = [m for m in members if m in all_names] or members
            sub = menu.addMenu(f'{squad_title}')
            if menu_style:
                sub.setStyleSheet(menu_style)
            joined_disp = ', '.join(provider_display_name(m) for m in avail_members)
            cap_note = f' [Max {max_cap}]' if max_cap > 0 else ''
            all_act = QAction(f'All {squad_title}{cap_note}: {joined_disp}', sub)
            all_act.triggered.connect(
                lambda _c=False, st=squad_title, ms=avail_members, dl=default_delib, dc=default_code, mc=max_cap:
                self._apply_squad_preset(st, ms, deliberate=dl, palace_code=dc, max_ais=mc)
            )
            sub.addAction(all_act)
            sub.addSeparator()
            for m in avail_members:
                single_act = QAction(
                    provider_qicon(m, checked=(prov_states.get(m) is True)),
                    f'Only {provider_display_name(m)} ({squad_title})',
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

        custom_act = QAction('✋  Custom Selection & How Many AIs…', menu)
        custom_act.triggered.connect(self._open_custom_ai_picker)
        menu.addAction(custom_act)

        menu.addSeparator()
        for name in all_names:
            is_active = (prov_states.get(name) is True)
            disp = provider_display_name(name)
            model_hint = configs.get(name, {}).get('model', '')
            label_txt = f'  {disp}  ({model_hint})' if model_hint else f'  {disp}'
            act = QAction(provider_qicon(name, checked=is_active), label_txt, menu)
            act.triggered.connect(lambda _checked=False, n=name, cur=is_active: self._toggle_provider_quick(n, not cur))
            menu.addAction(act)

        menu.addSeparator()
        edit_prof_act = QAction('🎛  Customize Profiles & Squads…', menu)
        edit_prof_act.triggered.connect(lambda: self.open_manage_ais('Profiles'))
        menu.addAction(edit_prof_act)

        manage_act = QAction('⚙  Manage AI Keys, Models & Tools…', menu)
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

    def _apply_squad_preset(self, label: str, active_list: list[str], deliberate: bool = True, palace_code: bool = False, max_ais: int = 0):
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
        self.current_squad_label = ''
        self.provider_states[name] = enabled
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

    def _on_idle_switch_toggled(self, active: bool):
        """Front-interface Experimental Mode switch: pauses Normal AI mode when ON and runs Experimental Mode autonomously."""
        self.idle_switch_btn.setIcon(idle_moon_qicon(active))
        if active:
            self.idle_switch_btn.setText(' Experimental: ON')
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
            self.idle_switch_btn.setText(' Experimental: OFF')
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
        self.status_label.setText(f'Mode: {profile_text}')

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
            self.idle_switch_btn.setIcon(idle_moon_qicon(True))
            self.idle_switch_btn.setText(' Experimental: ON')
            self.idle_switch_btn.blockSignals(False)
            self.normal_pause_banner.show()
            self.composer.setEnabled(False)
            self.send_button.setEnabled(False)
        self.idle_manager.start_session()
        self.idle_timer.start()
        self.idle_start_btn.setText('↻ Restart')
        self.idle_step_btn.setEnabled(True)
        self.idle_join_btn.setEnabled(True)
        self.idle_stop_btn.setEnabled(True)
        self._refresh_idle_view()
        self.run_idle_exchange_step()

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
            self.idle_switch_btn.setIcon(idle_moon_qicon(False))
            self.idle_switch_btn.setText(' Experimental: OFF')
            self.idle_switch_btn.blockSignals(False)
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
                self.idle_switch_btn.setIcon(idle_moon_qicon(False))
                self.idle_switch_btn.setText(' Experimental: OFF')
                self.idle_switch_btn.blockSignals(False)
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
                self.idle_switch_btn.setIcon(idle_moon_qicon(False))
                self.idle_switch_btn.setText(' Experimental: OFF')
                self.idle_switch_btn.blockSignals(False)
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
            self.bottom_token_label.setText(budget_str)

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
                        f'<div style="color:#8b949e; font-size:11px; font-weight:700;">OWNER / OPERATOR</div>'
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

    def _refresh_agent_mail_tab(self):
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
            if hasattr(self, 'mail_delete_btn'):
                self.mail_delete_btn.setEnabled(False)
            self.mail_header_label.setText('Inbox is empty.')
            self.mail_body_view.clear()
            return

        restore_row = 0
        for idx, msg in enumerate(messages):
            sender = str(msg.get('sender', 'agent'))
            ic = provider_icon(sender)
            subj = str(msg.get('subject') or 'No Subject')
            link = str(msg.get('link') or '')
            unread_prefix = '● ' if not msg.get('read') else ''
            link_suffix = f'  📎 {link}' if link else ''
            item = QListWidgetItem(f'{unread_prefix}{ic} {sender.upper()}: {subj}{link_suffix}')
            item.setData(Qt.ItemDataRole.UserRole, msg)
            self.mail_list.addItem(item)
            if selected_id and msg.get('id') == selected_id:
                restore_row = idx

        self.mail_list.setCurrentRow(restore_row)

    def _on_mail_item_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None):
        if current is None:
            self.mail_open_link_btn.setEnabled(False)
            if hasattr(self, 'mail_delete_btn'):
                self.mail_delete_btn.setEnabled(False)
            return
        msg = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(msg, dict):
            self.mail_open_link_btn.setEnabled(False)
            if hasattr(self, 'mail_delete_btn'):
                self.mail_delete_btn.setEnabled(False)
            self.mail_header_label.setText('Select an email from an Experimental Mode agent to read.')
            self.mail_body_view.clear()
            return

        if hasattr(self, 'mail_delete_btn'):
            self.mail_delete_btn.setEnabled(True)
        self.idle_manager.mailbox.mark_read(str(msg.get('id', '')))
        msg['read'] = True
        cur_txt = current.text()
        if cur_txt.startswith('● '):
            current.setText(cur_txt[2:])
        unread = self.idle_manager.mailbox.unread_count()
        self.workspace_tabs.setTabText(2, f'✉ Agent Mail ({unread})')
        self.sidebar_mail_btn.setText(f' Agent Mail ({unread})')
        self.sidebar_mail_btn.setIcon(mail_grey_qicon(unread > 0))
        sender = str(msg.get('sender', 'agent'))
        subj = html.escape(str(msg.get('subject') or 'No Subject'))
        ts = html.escape(str(msg.get('timestamp') or '')[:19].replace('T', ' '))
        link = str(msg.get('link') or '').strip()
        body = html.escape(str(msg.get('body') or '')).replace('\n', '<br>')
        reply = str(msg.get('owner_reply') or '').strip()

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
            self.mail_open_link_btn.setText(f'📂 Open "{link}" in Experimental Memory')
        else:
            self.mail_open_link_btn.setEnabled(False)
            self.mail_open_link_btn.setText('📂 No Linked Experimental Memory File')

        self.mail_header_label.setText(
            f'<div style="font-size:14px; font-weight:700; color:#f0f6fc;">{subj}</div>'
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
            author='owner',
            title=f'Owner Reply to {sender.upper()}: {subj}',
            file=f'owner_reply_{msg_id[:8]}.md',
            content=reply_txt,
            is_idle_mode=True,
        )
        self.mail_reply_edit.clear()
        self._refresh_idle_view()
        self.status_label.setText(f'Reply sent to {sender.upper()} and stored in Shared Idle Memory.')

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
            self.status_label.setText('Fairybread settings updated.')

    def reload_providers_from_config(self):
        self.reload_provider_bar()

    def _switch_theme_and_persist(self, theme_id: str):
        self.apply_theme(theme_id)
        try:
            ui_cfg = load_ui_settings(self.config_path)
            save_ui_settings(
                enter_to_send=bool(ui_cfg.get('enter_to_send', True)),
                badge_display_mode=str(ui_cfg.get('badge_display_mode', 'icons_only')),
                theme=theme_id,
                config_path=self.config_path,
            )
        except Exception:
            pass
        t_dict = load_theme_dict(theme_id)
        self.status_label.setText(f'Theme applied: {t_dict.get("name", theme_id)}')

    def apply_theme(self, theme_id: str, render_chat: bool = True):
        self.active_theme = str(theme_id or 'dark')
        t_dict = load_theme_dict(self.active_theme)
        self.setStyleSheet(build_theme_stylesheet(self.active_theme))
        if hasattr(self, 'chat') and isinstance(self.chat, ChatBrowser):
            self.chat.set_theme_colors(t_dict)
        if render_chat and getattr(self, 'chat_items', None):
            self._render_chat_items()

    def reload_provider_bar(self):
        try:
            configs = load_provider_configs(self.config_path)
            self.provider_states = {
                name: bool(settings.get('enabled', False))
                for name, settings in configs.items()
            }
        except Exception as exc:
            self.show_notice(str(exc))
            return
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
            self.bottom_token_label.setStyleSheet(
                f'font-family: Consolas, monospace; font-size: {font_sz}; color: #8b949e; padding: {token_pad};'
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

        # Populate Pinned list (only shown when at least 1 conversation is pinned)
        self.pinned_list.blockSignals(True)
        self.pinned_list.clear()
        pinned = self.store.pinned_sessions() if hasattr(self.store, 'pinned_sessions') else []
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

        def _add_session_row(sess: dict, indented: bool = False):
            age = self.store.session_relative_age(sess['id']) if hasattr(self.store, 'session_relative_age') else ''
            raw_title = str(sess.get('title') or 'New conversation')
            short_title = raw_title if len(raw_title) <= 27 else raw_title[:26] + '…'
            prefix = '  ' if indented else ''
            display = f'{prefix}{short_title}   {age}' if age else f'{prefix}{short_title}'
            row = QListWidgetItem(display)
            row.setData(Qt.ItemDataRole.UserRole, sess['id'])
            row.setToolTip(f'{raw_title}\n(Drag to reorder or drop onto a Project folder)')
            row.setSizeHint(QSize(0, 23))
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
                hdr = QListWidgetItem(f'{proj["name"]}{folder_tag}')
                hdr.setIcon(folder_grey_qicon(pid == selected_proj))
                hdr.setData(Qt.ItemDataRole.UserRole, f'proj:{pid}')
                hdr.setFont(bold_font)
                hdr.setSizeHint(QSize(0, 24))
                hdr.setForeground(QColor('#c9d1d9' if pid == selected_proj else '#8b949e'))
                hdr.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDropEnabled
                )
                tip = f'Project: {proj["name"]}\nDrag any conversation onto this folder to move it here, or right-click for options.'
                if folder:
                    tip += f'\nAttached folder: {folder}'
                hdr.setToolTip(tip)
                self.session_list.addItem(hdr)

                proj_sessions = [s for s in all_sessions if s.get('project_id') == pid]
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

            unassigned = [s for s in all_sessions if not s.get('project_id')]
            if unassigned:
                gen_hdr = QListWidgetItem('Conversations')
                gen_hdr.setData(Qt.ItemDataRole.UserRole, 'proj:')
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
            rec_hdr.setFont(bold_font)
            rec_hdr.setSizeHint(QSize(0, 24))
            rec_hdr.setForeground(QColor('#6e7681'))
            rec_hdr.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            self.session_list.addItem(rec_hdr)
            for s in all_sessions:
                _add_session_row(s, indented=False)

        self.session_list.blockSignals(False)

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

    def _on_voice_level_update(self, lvl: int, bars: str, speech_detected: bool):
        if not hasattr(self, 'voice_level_badge'):
            return
        is_live = hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked()
        mode_tag = 'Live Voice' if is_live else 'Dictating'
        state_hint = 'Hearing you!' if speech_detected or lvl >= 8 else 'Speak now…'
        self.voice_level_badge.setText(f'🎙 {bars} {lvl:2d}% · {mode_tag} ({state_hint})')
        if speech_detected or lvl >= 8:
            self.voice_level_badge.setStyleSheet(
                'font-family: Consolas, monospace; font-size: 11.5px; font-weight: 700; color: #22c55e; '
                'background: #11281b; border: 1px solid #22c55e; border-radius: 6px; padding: 3px 8px;'
            )
        else:
            self.voice_level_badge.setStyleSheet(
                'font-family: Consolas, monospace; font-size: 11.5px; font-weight: 600; color: #58a6ff; '
                'background: #132238; border: 1px solid #3b82f6; border-radius: 6px; padding: 3px 8px;'
            )
        self.voice_level_badge.show()

    def _toggle_voice_dictation(self, recording: bool):
        from voice_service import LiveAudioSession, transcribe_audio_file
        self.mic_button.setIcon(mic_qicon(recording))
        if recording:
            if hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked():
                self.live_voice_button.setChecked(False)
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
        from voice_service import LiveAudioSession, stop_speaking
        self.live_voice_button.setIcon(voice_wave_qicon(active))
        if active:
            if hasattr(self, 'mic_button') and self.mic_button.isChecked():
                self.mic_button.blockSignals(True)
                self.mic_button.setChecked(False)
                self.mic_button.setIcon(mic_qicon(False))
                self.mic_button.blockSignals(False)
                prev_s = getattr(self, '_active_voice_session', None)
                if prev_s is not None:
                    prev_s.stop()
                    self._active_voice_session = None
            sess = LiveAudioSession(
                config_path=self.config_path,
                live_mode=True,
                on_level=self._on_voice_level_update,
                on_utterance_ready=self._on_live_voice_utterance,
            )
            ok, dev_desc = sess.start(self)
            if not ok:
                self.live_voice_button.blockSignals(True)
                self.live_voice_button.setChecked(False)
                self.live_voice_button.setIcon(voice_wave_qicon(False))
                self.live_voice_button.blockSignals(False)
                self.show_notice(dev_desc)
                return
            self._active_voice_session = sess
            self._on_voice_level_update(0, '▁▁▁▁▁▁', False)
            self.show_notice(
                f'🟢 Live Voice Mode ON ({dev_desc}) — Speak naturally! When you pause (~1.5s), Fairybread automatically sends to the Council and speaks the reply aloud.'
            )
        else:
            sess = getattr(self, '_active_voice_session', None)
            self._active_voice_session = None
            if hasattr(self, 'voice_level_badge'):
                self.voice_level_badge.hide()
            if sess is not None:
                # If the user spoke before clicking off, transcribe that utterance into the composer
                had_speech = getattr(sess, '_speech_detected', False)
                wav_p = sess.stop('fairybread_live_final.wav')
                if had_speech and wav_p:
                    self._on_live_voice_utterance(wav_p)
            stop_speaking()
            self.show_notice('Live Voice Mode turned OFF.')

    def _on_live_voice_utterance(self, wav_path: Path):
        from voice_service import transcribe_audio_file
        if hasattr(self, 'voice_level_badge'):
            self.voice_level_badge.setText('⏳ Transcribing spoken prompt…')
        QApplication.processEvents()
        try:
            text = transcribe_audio_file(wav_path)
        except Exception as exc:
            self.show_notice(f'Live Voice notice: {exc}')
            return
        if not text:
            return
        self.composer.setPlainText(text)
        if self.worker is None:
            self._turn_triggered_by_live_voice = True
            self.send_message()
        else:
            self.queue_next_turn()

    def load_history(self):
        self.chat.clear()
        self.last_answer = ''
        self.reply_archive = []
        self.chat_items = []
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
                if speaker and speaker not in {'user', 'assistant', 'palace'} and speaker not in self.conversation_contributors:
                    self.conversation_contributors.append(speaker)
                for c in msg_contribs:
                    if c and c not in self.conversation_contributors:
                        self.conversation_contributors.append(c)

                if role == 'user':
                    self.append_message('user', message['content'], render=False)
                elif phase in {'initial', 'peer_reply'} and speaker not in {'assistant', 'palace'}:
                    pending_speakers.append(message)
                else:
                    self.append_message(
                        'assistant',
                        message['content'],
                        speaker=speaker,
                        phase=phase,
                        contributors=msg_contribs,
                        speaker_messages=list(pending_speakers),
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

    def append_message(self, role, content, speaker=None, phase=None, contributors=None, speaker_messages=None, render: bool = True):
        item_idx = len(self.chat_items)
        self.chat_items.append({
            'idx': item_idx,
            'role': role,
            'content': content,
            'speaker': speaker,
            'phase': phase,
            'contributors': list(contributors or []),
            'speaker_messages': list(speaker_messages or []),
        })
        if role != 'user':
            self.reply_archive.append(content)
        if render:
            self._render_chat_items()

    def _check_external_session_updates(self):
        """Watch active session file on disk so external Foreman/CLI prompts appear live in the open GUI."""
        if self.worker is not None:
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

    def _render_single_chat_item(self, item: dict) -> str:
        role = item['role']
        content = item['content']
        speaker = item.get('speaker')
        phase = item.get('phase')
        contributors = item.get('contributors') or []
        speaker_messages = item.get('speaker_messages') or []
        item_idx = item['idx']

        safe = html.escape(content).replace('\n', '<br>')
        t_dict = load_theme_dict(getattr(self, 'active_theme', 'dark'))
        user_txt_col = str(t_dict.get('user_bubble_text', '#f0f6fc'))
        if role == 'user':
            return (
                f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:20px; margin-bottom:16px;">'
                f'<tr><td width="26%"></td>'
                f'<td align="right">'
                f'<table cellspacing="0" cellpadding="0" style="background:transparent; border:none;">'
                f'<tr><td style="text-align:left; color:{user_txt_col}; font-size:13.5px; line-height:1.48;">'
                f'{safe}'
                f'</td></tr></table>'
                f'</td>'
                f'<td width="20"></td></tr></table>'
            )

        if speaker and speaker not in {'assistant', 'palace'}:
            active_contribs = [speaker]
            phase_tag = ' (PEER REPLY)' if phase == 'peer_reply' else ''
            meta_tag = f'{speaker.upper()}{phase_tag}'
        else:
            active_contribs = contributors or self.conversation_contributors or [
                name for name, en in self.provider_states.items() if en is True
            ]
            meta_tag = 'PALACE'

        chat_mode = getattr(self, 'badge_display_mode', 'icons_only')
        if active_contribs:
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
        actions_row_html = (
            f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px; border-top:1px solid #161b22; padding-top:6px;">'
            f'<tr>'
            f'<td align="left" style="vertical-align:middle;">{badges_html}</td>'
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

    def _render_chat_items(self, scroll_to_bottom: bool = True):
        self._update_inline_status_banner()
        if not self.chat_items:
            self.chat.clear()
            return
        scrollbar = self.chat.verticalScrollBar()
        prev_val = scrollbar.value() if scrollbar else 0
        html_blocks = [self._render_single_chat_item(item) for item in self.chat_items]
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
            return
        self.pulse_step += 1
        self._update_inline_status_banner()
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
        if not raw_key or raw_key.startswith('proj:'):
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
        self.attachment_list.setVisible(bool(self.attachments))
        self.remove_button.setVisible(bool(self.attachments))
        if self.attachments:
            self.attachment_list.setCurrentRow(0)

    @Slot()
    def remove_attachment(self):
        index = self.attachment_list.currentRow()
        if self.worker is None and index >= 0:
            self.attachments.pop(index)
            self.refresh_attachments()

    def dragEnterEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.worker is None:
            self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()

    def _on_palace_code_btn_toggled(self, on: bool):
        self.palace_code_btn.setIcon(code_shield_qicon(on))
        if on and self.worker is not None and getattr(self, 'active_steering_state', None) is not None:
            self.active_steering_state['include_palace_code'] = True
            self.show_notice('✓ Live Steering: Fairybread Source Code attached to active turn.')

    def _show_search_depth_menu(self):
        menu = QMenu(self)
        choices = [
            ('default', '🔍 Default (Light Search — /search)'),
            ('moderate', '🔎 Moderate (Sharded Multi-Angle — /msearch)'),
            ('deep', '🌐 Deep (Exhaustive 15–25 Site Research — /deepsearch)'),
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
        menu = QMenu(self)
        steer_act = menu.addAction('🧭 Steer Active Turn (inject into current turn)')
        queue_act = menu.addAction('⏳ Queue for Next Turn (run after current turn)')
        chosen = menu.exec(self.steer_button.mapToGlobal(QPoint(0, -menu.sizeHint().height())))
        if chosen == steer_act:
            self.steer_active_turn()
        elif chosen == queue_act:
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
        self.worker = None
        self.pending_status_text = ''
        self.pulse_timer.stop()
        self._update_inline_status_banner()
        if self.chat_items and self.chat_items[-1].get('role') == 'user':
            self.chat_items.pop()
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
            self.steer_button.setText(f"🧭 Steer ({len(self.active_steering_state['notes'])}) ▾")
            self.steer_button.setStyleSheet(
                'QPushButton { background: #132238; color: #58a6ff; border: 1px solid #3b82f6; '
                'padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 700; }'
            )
            self.show_notice(f'✓ Live Steering injected into active turn: "{note[:60]}"')
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
        use_palace_code = bool(self.palace_code_btn.isChecked() or tool_cfg.get('palace_source_read', False) and self.current_squad_label == '🛠 Work Mode')
        proj_folder = ''
        if tool_cfg.get('project_folder_read', True) and hasattr(self.store, 'get_project_folder'):
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
            self.pending_status_text = 'Council Drawing Mode: All agents collaborating on prompt → 1 final image'
        elif selected_providers:
            disp_list = ', '.join(provider_display_name(n) for n in selected_providers)
            self.pending_status_text = f'Consulting {disp_list}'
        else:
            self.pending_status_text = 'Consulting the enabled providers'
        self._turn_start_time = time.time()
        self.pulse_step = 0
        self.pulse_timer.start()
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
            try:
                return palace.run(
                    prompt,
                    provider_names=selected_providers if selected_providers else None,
                    include_memory=use_shared_mem,
                    include_context=use_history,
                    save_to_context=save_history,
                    max_rounds=rounds,
                    include_palace_code=use_palace_code,
                    project_folder=proj_folder,
                    search_depth=cur_search_depth,
                    cancel_event=self.active_cancel_event,
                    steering_state=self.active_steering_state,
                    on_phase_status=lambda ev: worker_box['w'].progress.emit(ev) if worker_box.get('w') is not None else None,
                )
            except TypeError:
                try:
                    return palace.run(
                        prompt,
                        provider_names=selected_providers if selected_providers else None,
                        include_context=use_history,
                        save_to_context=save_history,
                        max_rounds=rounds,
                        include_palace_code=use_palace_code,
                        project_folder=proj_folder,
                    )
                except TypeError:
                    try:
                        return palace.run(prompt, include_context=use_history, max_rounds=rounds)
                    except TypeError:
                        return palace.run(prompt, include_context=use_history)

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
        self.pending_status_text = ''
        self.pulse_timer.stop()
        self._update_inline_status_banner()
        speaker_msgs = getattr(result, 'speaker_messages', None) or []
        turn_contributors = list(getattr(result, 'contributors', []) or [])
        for c in turn_contributors:
            if c and c not in self.conversation_contributors:
                self.conversation_contributors.append(c)
        if result.final_answer:
            try:
                from voice_service import load_voice_settings, speak_agent_response
                live_active = bool(getattr(self, '_turn_triggered_by_live_voice', False) or (hasattr(self, 'live_voice_button') and self.live_voice_button.isChecked()))
                self._turn_triggered_by_live_voice = False
                if live_active or load_voice_settings(self.config_path).get('auto_speak_responses'):
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
                except Exception:
                    pass
            saved = 'Saved locally' if self.pending_history and not result.context_error else 'Not saved (No-History)'
            if self.tangent_btn.isChecked() and self.pending_history and not result.context_error:
                saved = 'Tangent saved to Palace (clean context)'
            contrib_badges = '&nbsp;&nbsp;'.join(format_ai_badge_html(c) for c in turn_contributors)
            self.status_label.setTextFormat(Qt.TextFormat.RichText)
            self.status_label.setText(f'{saved} · Contributors: {contrib_badges}')
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
        warnings = [result.context_error, result.memory_error]
        if result.synthesis and not result.synthesis.succeeded:
            warnings.append(f'Synthesis: {result.synthesis.error}')
        if any(warnings):
            self.show_notice('\n'.join(w for w in warnings if w))

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
            self.mic_button,
            self.send_button,
        ):
            setup_w.setVisible(not busy)
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

    @Slot(str)
    def task_failed(self, error):
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
        if self.worker is not None:
            self.show_notice('A request is still running. Please let it finish before closing Fairybread.')
            event.ignore()
            return
        if not self.confirm_switch():
            event.ignore()
            return
        if (
            not getattr(self, '_force_quit', False)
            and os.environ.get('QT_QPA_PLATFORM') != 'offscreen'
            and bool(load_ui_settings(self.config_path).get('close_to_tray', True))
        ):
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
        self.idle_timer.stop()
        self.idle_manager.wipe_ram()
        if hasattr(self, '_tray_icon') and self._tray_icon is not None:
            try:
                self._tray_icon.hide()
            except Exception:
                pass
        event.accept()


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
    try:
        if args.demo:
            import os
            from bootstrap import build_palace
            from providers import ProviderResponse

            class PreviewProvider:
                def __init__(self, label):
                    self.label = label

                def generate(self, prompt):
                    import time
                    time.sleep(0.2)
                    return ProviderResponse(
                        text='Assuming you managed the logistics, after a short burn it would take approximately six years for GPT to reach the Kuiper Belt.',
                        provider=self.label.lower()
                    )

            preview_root = Path(os.environ['LOCALAPPDATA']) / 'Palace' / 'ui-preview'
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
    except Exception as exc:
        QMessageBox.critical(None, 'Palace could not start', str(exc))
        return 1
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
