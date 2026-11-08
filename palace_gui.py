"""Palace desktop interface. Provider and memory work remains in core services."""
import argparse
import html
import json
from pathlib import Path
import sys
import webbrowser

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QFont, QImage, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QStackedWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from attachment_service import (
    MAX_TOTAL_CHARS,
    attachment_from_image_bytes,
    compose_question,
    extract_attachment,
)
from credential_store import CredentialStore
from idle_service import IdleMemoryStore, IdleSessionManager, MAX_IDLE_MEMORY_BYTES
from memory_proposal_service import MemoryProposalService
from palace_config import (
    CONFIG_PATH,
    load_idle_settings,
    load_mission_ethics,
    load_provider_configs,
    save_idle_settings,
    save_mission_ethics,
    save_provider_config,
)
from session_store import SessionStore


AI_ICONS = {
    'gemini': '◆',
    'openai': '●',
    'groq': '⚡',
    'mistral': '▲',
    'cohere': '◉',
    'cerebras': '⬢',
    'deepseek': '❖',
    'qwen': '✦',
}

AI_COLORS = {
    'gemini': '#4da3ff',
    'openai': '#3fb950',
    'groq': '#fb923c',
    'mistral': '#f87171',
    'cohere': '#c084fc',
    'cerebras': '#f472b6',
    'deepseek': '#2dd4bf',
    'qwen': '#facc15',
}

AI_BG_COLORS = {
    'gemini': '#122338',
    'openai': '#122921',
    'groq': '#2b1d12',
    'mistral': '#2c1619',
    'cohere': '#231733',
    'cerebras': '#2b1624',
    'deepseek': '#112828',
    'qwen': '#2b2411',
}


def provider_icon(name: str) -> str:
    return AI_ICONS.get((name or '').strip().lower(), '◆')


def provider_color(name: str) -> str:
    return AI_COLORS.get((name or '').strip().lower(), '#58a6ff')


def provider_bg_color(name: str) -> str:
    return AI_BG_COLORS.get((name or '').strip().lower(), '#162234')


def format_ai_badge(name: str) -> str:
    clean = (name or '').strip()
    display = 'OpenAI' if clean.lower() == 'openai' else clean.capitalize()
    return f'{provider_icon(clean)} {display}'


class TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

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

    def __init__(self):
        super().__init__()
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
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.send_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class ManageAIsDialog(QDialog):
    """Multi-page Palace Settings dialog (including AI Providers and dedicated Idle Mode page)."""

    SETTINGS_PAGES = [
        'General',
        'Appearance',
        'Notifications',
        'AI Providers',
        'Profiles',
        'Memory & History',
        'Idle Mode',
        'Permissions',
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
        self.setWindowTitle('Palace Settings')
        self.resize(760, 560)
        self.setMinimumWidth(680)

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(14)

        # Left navigation list
        self.nav_list = QListWidget()
        self.nav_list.setObjectName('sidebarList')
        self.nav_list.setFixedWidth(185)
        for page_name in self.SETTINGS_PAGES:
            self.nav_list.addItem(page_name)
        root_layout.addWidget(self.nav_list)

        # Right content area + bottom buttons
        right_col = QVBoxLayout()
        self.pages = QStackedWidget()
        right_col.addWidget(self.pages, 1)

        self._build_general_page()
        self._build_appearance_page()
        self._build_notifications_page()
        self._build_ai_providers_page()
        self._build_profiles_page()
        self._build_memory_history_page()
        self._build_idle_mode_page()
        self._build_permissions_page()
        self._build_backup_restore_page()

        buttons = QHBoxLayout()
        buttons.addStretch()
        save_btn = QPushButton('Save Settings')
        save_btn.clicked.connect(self.save_settings)
        cancel_btn = QPushButton('Close')
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        right_col.addLayout(buttons)

        root_layout.addLayout(right_col, 1)

        self.nav_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        target_idx = self.SETTINGS_PAGES.index(initial_page) if initial_page in self.SETTINGS_PAGES else 3
        self.nav_list.setCurrentRow(target_idx)

    def _make_simple_page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(10)
        h = QLabel(title)
        h.setObjectName('sectionTitle')
        lay.addWidget(h)
        sub = QLabel(subtitle)
        sub.setObjectName('muted')
        sub.setWordWrap(True)
        lay.addWidget(sub)
        return w, lay

    def _build_general_page(self):
        w, lay = self._make_simple_page('General', 'Startup behavior, default workspace, and composer preferences.')
        lay.addWidget(QCheckBox('Restore last active conversation on startup', checked=True))
        lay.addWidget(QCheckBox('Send message with Ctrl+Enter', checked=True))
        lay.addStretch()
        self.pages.addWidget(w)

    def _build_appearance_page(self):
        w, lay = self._make_simple_page('Appearance', 'Theme, badge display, and workspace density.')
        lay.addWidget(QLabel('Active Theme: Dark Sanctuary (#0f1116)'))
        lay.addWidget(QCheckBox('Show contributor symbols inside reply cards', checked=True))
        lay.addStretch()
        self.pages.addWidget(w)

    def _build_notifications_page(self):
        w, lay = self._make_simple_page('Notifications', 'Provider status alerts and Idle Mode prompts.')
        lay.addWidget(QCheckBox('Show badge alert when a loaded AI hits rate limits or timeouts', checked=True))
        lay.addWidget(QCheckBox('Notify when AIs in Idle Mode invite the operator to join', checked=True))
        lay.addStretch()
        self.pages.addWidget(w)

    def _build_ai_providers_page(self):
        w, lay = self._make_simple_page(
            'AI Providers',
            'Configure API keys, models, and custom OpenAI-compatible endpoints for any number of AIs.'
        )
        form = QFormLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.setEditable(True)
        configs = load_provider_configs(self.config_path)
        known = list(dict.fromkeys([
            'gemini', 'openai', 'groq', 'mistral', 'cerebras', 'cohere', 'deepseek', 'qwen',
            *configs.keys()
        ]))
        self.provider_combo.addItems(known)
        self.provider_combo.currentTextChanged.connect(self._load_selected_provider)
        form.addRow('AI Provider name:', self.provider_combo)

        self.enabled_check = QCheckBox('Active in conversation')
        self.enabled_check.setChecked(True)
        form.addRow('', self.enabled_check)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText('Leave blank to keep existing key')
        form.addRow('API Key:', self.api_key_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText('Optional model override (e.g. gpt-5-mini)')
        form.addRow('Model (optional):', self.model_edit)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText('Optional OpenAI-compatible URL')
        form.addRow('Base URL (optional):', self.base_url_edit)

        lay.addLayout(form)
        lay.addStretch()
        self._load_selected_provider(self.provider_combo.currentText())
        self.pages.addWidget(w)

    def _build_profiles_page(self):
        w, lay = self._make_simple_page(
            'Profiles',
            'Profiles let you switch between Single AI, Multi-AI Deliberate, Multi-AI Independent, and Idle Mode.'
        )
        lay.addWidget(QLabel('Built-in Profiles:\n• Multi-AI · Deliberate\n• Multi-AI · Independent\n• Single AI\n• Idle'))
        lay.addStretch()
        self.pages.addWidget(w)

    def _build_memory_history_page(self):
        w, lay = self._make_simple_page(
            'Memory & History',
            'Control local session history and Palace memory proposal review.'
        )
        lay.addWidget(QCheckBox('Save standard chat transcripts locally per conversation', checked=True))
        lay.addWidget(QCheckBox('Require explicit confirmation before promoting proposals to Palace memory', checked=True))
        lay.addStretch()
        self.pages.addWidget(w)

    def _build_idle_mode_page(self):
        w, lay = self._make_simple_page(
            'Idle Mode Sanctuary',
            'Configure the protected AI-to-AI Idle session timer, Palace memory access boundaries, '
            'and the startup prompt & Mission/Ethics charter.'
        )
        idle_cfg = load_idle_settings(self.config_path)

        form = QFormLayout()
        self.idle_duration_spin = QSpinBox()
        self.idle_duration_spin.setRange(1, 240)
        self.idle_duration_spin.setSuffix(' minutes')
        self.idle_duration_spin.setValue(int(idle_cfg.get('duration_minutes', 30)))
        form.addRow('Idle session duration:', self.idle_duration_spin)

        self.idle_pause_check = QCheckBox('Pause countdown timer while operator is admitted to discussion')
        self.idle_pause_check.setChecked(bool(idle_cfg.get('pause_when_joined', True)))
        form.addRow('', self.idle_pause_check)

        self.idle_memory_mode_combo = QComboBox()
        self.idle_memory_mode_combo.addItem(
            'Only their own Idle memory (Isolated — No Palace memory access)',
            'isolated'
        )
        self.idle_memory_mode_combo.addItem(
            'Non-project Palace memory + their own Idle memory (Projects off-limits)',
            'non_project'
        )
        self.idle_memory_mode_combo.addItem(
            'Full Palace memory access (excluding Private projects) + their own Idle memory',
            'full'
        )
        current_mode = idle_cfg.get('memory_access_mode', 'isolated')
        idx = self.idle_memory_mode_combo.findData(current_mode)
        if idx >= 0:
            self.idle_memory_mode_combo.setCurrentIndex(idx)
        form.addRow('Memory Access in Idle Mode:', self.idle_memory_mode_combo)
        lay.addLayout(form)

        lay.addWidget(QLabel('Idle Startup Prompt (editable placeholder — customize when ready):'))
        self.idle_prompt_edit = QTextEdit()
        self.idle_prompt_edit.setAcceptRichText(False)
        self.idle_prompt_edit.setMaximumHeight(105)
        self.idle_prompt_edit.setPlainText(str(idle_cfg.get('standing_instruction', '')))
        lay.addWidget(self.idle_prompt_edit)

        lay.addWidget(QLabel('Mission Statement, Code of Ethics & Conduct Rules (injected into Idle Mode):'))
        self.mission_ethics_edit = QTextEdit()
        self.mission_ethics_edit.setAcceptRichText(False)
        self.mission_ethics_edit.setMaximumHeight(95)
        self.mission_ethics_edit.setPlainText(load_mission_ethics(self.config_path))
        lay.addWidget(self.mission_ethics_edit)

        mem_row = QHBoxLayout()
        used_kb = self.idle_memory.usage_bytes() / 1024.0
        max_mb = MAX_IDLE_MEMORY_BYTES / (1024 * 1024)
        self.idle_mem_status_label = QLabel(
            f'AI-Only Permanent Idle Memory: {self.idle_memory.note_count()} notes ({used_kb:.1f} KB / {max_mb:.0f} MB cap) · Accessible only in Idle Mode'
        )
        self.idle_mem_status_label.setObjectName('muted')
        mem_row.addWidget(self.idle_mem_status_label, 1)
        clear_idle_btn = QPushButton('Clear AI Idle Memory')
        clear_idle_btn.clicked.connect(self._clear_idle_memory)
        mem_row.addWidget(clear_idle_btn)
        lay.addLayout(mem_row)

        self.pages.addWidget(w)

    def _build_permissions_page(self):
        w, lay = self._make_simple_page(
            'Permissions',
            'File attachment limits and operator consensus boundaries.'
        )
        lay.addWidget(QLabel('• Idle Mode live transcripts are strictly sealed from the operator unless AIs vote YES by consensus.\n• AI-only permanent Idle Memory is capped at 10 MB and blocked outside Idle Mode.'))
        lay.addStretch()
        self.pages.addWidget(w)

    def _build_backup_restore_page(self):
        w, lay = self._make_simple_page(
            'Backup & Restore',
            'Export or restore local Palace configuration and session archives.'
        )
        lay.addWidget(QLabel(f'Config file: {self.config_path}'))
        lay.addStretch()
        self.pages.addWidget(w)

    def _clear_idle_memory(self):
        self.idle_memory.clear_all()
        self.idle_mem_status_label.setText(
            'AI-Only Permanent Idle Memory: 0 notes (0.0 KB / 10 MB cap) · Accessible only in Idle Mode'
        )

    def _load_selected_provider(self, name: str):
        clean = name.strip().lower()
        configs = load_provider_configs(self.config_path)
        cfg = configs.get(clean, {})
        self.enabled_check.setChecked(bool(cfg.get('enabled', True)))
        self.model_edit.setText(str(cfg.get('model', '')))
        self.base_url_edit.setText(str(cfg.get('base_url', '')))
        self.api_key_edit.clear()
        try:
            if clean and self.credential_store.has_api_key(clean):
                self.api_key_edit.setPlaceholderText('Saved in CredentialStore (enter new key to replace)')
            else:
                self.api_key_edit.setPlaceholderText('Enter API key to save in CredentialStore')
        except Exception:
            self.api_key_edit.setPlaceholderText('Enter API key')

    def save_settings(self):
        name = self.provider_combo.currentText().strip().lower()
        if not name:
            QMessageBox.warning(self, 'Missing Provider Name', 'Please enter a provider name.')
            return
        api_key = self.api_key_edit.text().strip()
        if api_key:
            self.credential_store.set_api_key(name, api_key)
        save_provider_config(
            provider_name=name,
            enabled=self.enabled_check.isChecked(),
            model=self.model_edit.text(),
            base_url=self.base_url_edit.text(),
            config_path=self.config_path,
        )
        save_idle_settings(
            {
                'duration_minutes': self.idle_duration_spin.value(),
                'pause_when_joined': self.idle_pause_check.isChecked(),
                'memory_access_mode': self.idle_memory_mode_combo.currentData(),
                'standing_instruction': self.idle_prompt_edit.toPlainText().strip(),
            },
            config_path=self.config_path,
        )
        save_mission_ethics(
            self.mission_ethics_edit.toPlainText(),
            config_path=self.config_path,
        )
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
        self.idle_memory = idle_memory or IdleMemoryStore(self.store.root / 'idle_notebooks' / 'ai_idle_memory.json')
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
        self.demo = demo
        self.setWindowTitle('Palace — Preview' if demo else 'Palace')
        self.resize(1120, 740)
        self.setMinimumSize(860, 600)
        self.setAcceptDrops(True)

        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(1000)
        self.idle_timer.timeout.connect(self._on_idle_timer_tick)

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
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(280)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 14, 14, 12)
        side.setSpacing(8)

        self.new_button = QPushButton('+  New Conversation')
        self.new_button.setObjectName('newConvoButton')
        self.new_button.clicked.connect(self.new_conversation)
        side.addWidget(self.new_button)

        # Pinned collapsible section
        self.pinned_toggle_btn = QPushButton('⌄  Pinned')
        self.pinned_toggle_btn.setObjectName('pinnedHeaderButton')
        self.pinned_toggle_btn.setCheckable(True)
        self.pinned_toggle_btn.setChecked(True)
        self.pinned_toggle_btn.toggled.connect(self._toggle_pinned_section)
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
        side.addWidget(self.pinned_list)

        # Projects section
        proj_header = QHBoxLayout()
        proj_header.setContentsMargins(4, 6, 4, 0)
        proj_label = QLabel('Projects')
        proj_label.setObjectName('sidebarHeading')
        proj_header.addWidget(proj_label)
        proj_header.addStretch()
        self.new_project_button = QPushButton('+')
        self.new_project_button.setObjectName('iconButton')
        self.new_project_button.setToolTip('New Project (no disk folder required)')
        self.new_project_button.clicked.connect(lambda: self.new_project())
        proj_header.addWidget(self.new_project_button)
        side.addLayout(proj_header)

        self.project_list = QListWidget()
        self.project_list.setObjectName('sidebarList')
        self.project_list.setAccessibleName('Projects')
        self.project_list.setMaximumHeight(130)
        self.project_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.project_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.project_list.currentItemChanged.connect(self.change_project)
        side.addWidget(self.project_list)

        # Discussions section
        self.discussions_toggle_btn = QPushButton('⌄  Discussions')
        self.discussions_toggle_btn.setObjectName('sectionToggleButton')
        self.discussions_toggle_btn.setCheckable(True)
        self.discussions_toggle_btn.setChecked(True)
        self.discussions_toggle_btn.toggled.connect(self._toggle_discussions_section)
        side.addWidget(self.discussions_toggle_btn)

        self.session_list = QListWidget()
        self.session_list.setObjectName('sidebarList')
        self.session_list.setAccessibleName('Conversations')
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.session_list.currentItemChanged.connect(self.change_session)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(lambda pos: self._show_session_context_menu(self.session_list, pos))
        side.addWidget(self.session_list, 1)

        self.manage_ais_button = QPushButton('⚙  Settings · Manage AIs')
        self.manage_ais_button.setObjectName('settingsButton')
        self.manage_ais_button.clicked.connect(self.open_manage_ais)
        side.addWidget(self.manage_ais_button)
        splitter.addWidget(sidebar)

        # --- MAIN CHAT WORKSPACE ---
        panel = QWidget()
        panel.setObjectName('chatPanel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 14, 24, 10)
        layout.setSpacing(10)

        # Keep conversation_title for internal state/tests
        self.conversation_title = QLabel('New conversation')
        self.conversation_title.hide()

        # Single "Loaded AIs" rounded bar at top of chat pane + Profile Picker
        loaded_frame = QFrame()
        loaded_frame.setObjectName('loadedAIsBar')
        self.providers_layout = QHBoxLayout(loaded_frame)
        self.providers_layout.setContentsMargins(14, 7, 14, 7)
        self.providers_layout.setSpacing(10)
        loaded_caption = QLabel('Loaded AIs')
        loaded_caption.setObjectName('loadedAIsLabel')
        self.providers_layout.addWidget(loaded_caption)

        if provider_states is None:
            try:
                provider_states = {
                    name: settings.get('enabled', False)
                    for name, settings in json.loads(self.config_path.read_text())['providers'].items()
                }
            except (OSError, ValueError, KeyError) as exc:
                provider_states = {}
                self.config_warning = str(exc)
        self.provider_states = provider_states
        for name, enabled in provider_states.items():
            label = QPushButton()
            label.setFlat(True)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.clicked.connect(lambda checked=False, n=name: self._show_provider_badge_info(n))
            self.provider_labels[name] = label
            self.providers_layout.addWidget(label)
            if enabled == 'inactive':
                self.set_provider_status(name, 'Inactive', '#6e7681', 'INACTIVE_IN_PROFILE: Loaded in background, not active for this profile.')
            else:
                self.set_provider_status(name, 'Enabled' if enabled else 'Off', '#8aa4c1' if enabled else '#68707d')
        self.providers_layout.addStretch()

        profile_caption = QLabel('Mode:')
        profile_caption.setObjectName('loadedAIsLabel')
        self.providers_layout.addWidget(profile_caption)

        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName('profilePicker')
        self.profile_combo.setAccessibleName('Profile and mode selector')
        self.profile_combo.addItems([
            'Multi-AI · Deliberate',
            'Multi-AI · Independent',
            'Single AI',
            'Idle',
            'Manage Profiles…',
        ])
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        self.providers_layout.addWidget(self.profile_combo)

        self.memory_button = QPushButton('Memory review')
        self.memory_button.setObjectName('topIconButton')
        self.memory_button.setCheckable(True)
        self.memory_button.setToolTip('Toggle proposed memories panel')
        self.providers_layout.addWidget(self.memory_button)
        layout.addWidget(loaded_frame)

        # --- IDLE MODE SANCTUARY CONTROL BANNER (Visible only when Mode == Idle) ---
        self.idle_banner = QFrame()
        self.idle_banner.setObjectName('idleBanner')
        idle_lay = QVBoxLayout(self.idle_banner)
        idle_lay.setContentsMargins(14, 10, 14, 10)
        idle_lay.setSpacing(8)

        idle_top = QHBoxLayout()
        self.idle_status_label = QLabel('Idle Mode · Ready')
        self.idle_status_label.setStyleSheet('font-weight: 700; color: #58a6ff; font-size: 13px;')
        idle_top.addWidget(self.idle_status_label)

        self.idle_timer_label = QLabel('⏱ 30:00')
        self.idle_timer_label.setStyleSheet('font-family: Consolas, monospace; font-size: 13px; font-weight: 700; color: #e6edf3; background: #1c212c; padding: 3px 10px; border-radius: 6px;')
        idle_top.addWidget(self.idle_timer_label)

        self.idle_log_badge = QLabel('⊘ Transcript logging off · RAM-only live chat · AI Idle Memory (< 10 MB) isolated to Idle Mode')
        self.idle_log_badge.setObjectName('muted')
        idle_top.addWidget(self.idle_log_badge, 1)

        self.idle_settings_btn = QPushButton('⚙ Idle Settings')
        self.idle_settings_btn.clicked.connect(lambda: self.open_manage_ais(initial_page='Idle Mode'))
        idle_top.addWidget(self.idle_settings_btn)
        idle_lay.addLayout(idle_top)

        idle_actions = QHBoxLayout()
        self.idle_start_btn = QPushButton('▶ Start Idle Session')
        self.idle_start_btn.clicked.connect(self.start_idle_session)
        idle_actions.addWidget(self.idle_start_btn)

        self.idle_step_btn = QPushButton('↻ Next AI Exchange Round')
        self.idle_step_btn.clicked.connect(self.run_idle_exchange_step)
        self.idle_step_btn.setEnabled(False)
        idle_actions.addWidget(self.idle_step_btn)

        self.idle_join_btn = QPushButton('🔒 Request to Join (Consensus Vote)')
        self.idle_join_btn.clicked.connect(self.request_idle_operator_join)
        self.idle_join_btn.setEnabled(False)
        idle_actions.addWidget(self.idle_join_btn)

        self.idle_stop_btn = QPushButton('⏹ Cancel & Wipe RAM')
        self.idle_stop_btn.clicked.connect(self.stop_idle_session)
        self.idle_stop_btn.setEnabled(False)
        idle_actions.addWidget(self.idle_stop_btn)
        idle_actions.addStretch()
        idle_lay.addLayout(idle_actions)

        self.idle_banner.hide()
        layout.addWidget(self.idle_banner)

        self.chat = QTextBrowser()
        self.chat.setObjectName('chatView')
        self.chat.setAccessibleName('Conversation history')
        self.chat.setOpenLinks(False)
        self.chat.setAcceptDrops(False)
        self.chat.anchorClicked.connect(self._on_chat_anchor_clicked)
        layout.addWidget(self.chat, 1)

        # --- UNIFIED ROUNDED COMPOSER CARD (Matches mockup) ---
        composer_card = QFrame()
        composer_card.setObjectName('composerCard')
        card_layout = QVBoxLayout(composer_card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(6)

        self.attachment_list = QListWidget()
        self.attachment_list.setObjectName('attachmentList')
        self.attachment_list.setAccessibleName('Attached files; select a file then Remove selected')
        self.attachment_list.setMaximumHeight(60)
        self.attachment_list.hide()
        card_layout.addWidget(self.attachment_list)

        self.composer = Composer()
        self.composer.files_added.connect(self.add_files)
        self.composer.image_pasted.connect(self.add_pasted_image)
        self.composer.send_requested.connect(self.send_message)
        self.composer.unsupported_paste.connect(lambda: self.show_notice('Clipboard image could not be decoded. Attach a picture, text document, PDF, or Word file.'))
        card_layout.addWidget(self.composer)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 2, 0, 0)
        controls.setSpacing(12)
        self.attach_button = QPushButton('+')
        self.attach_button.setObjectName('plusAttachButton')
        self.attach_button.setToolTip('Attach documents or pictures (Ctrl+O)')
        self.attach_button.clicked.connect(self.choose_files)
        controls.addWidget(self.attach_button)

        self.remove_button = QPushButton('✕ Remove file')
        self.remove_button.setObjectName('iconButton')
        self.remove_button.clicked.connect(self.remove_attachment)
        self.remove_button.hide()
        controls.addWidget(self.remove_button)

        self.ai_pill_button = QPushButton('Choose AIs  ▾')
        self.ai_pill_button.setObjectName('aiPillButton')
        self.ai_pill_button.setToolTip('Choose and configure active AIs')
        self.ai_pill_button.clicked.connect(self.open_manage_ais)
        controls.addWidget(self.ai_pill_button)

        self.history_toggle = QCheckBox('History')
        self.history_toggle.setChecked(True)
        self.history_toggle.setToolTip('Use & save session history for this turn')
        self.history_toggle.toggled.connect(self.update_privacy_label)
        controls.addWidget(self.history_toggle)

        self.peer_rounds_toggle = QCheckBox('Peer deliberation')
        self.peer_rounds_toggle.setChecked(True)
        self.peer_rounds_toggle.setToolTip('When multiple AIs are enabled, let them review each other’s initial answers before synthesizing consensus.')
        controls.addWidget(self.peer_rounds_toggle)

        controls.addStretch()
        self.send_button = QPushButton('↑')
        self.send_button.setObjectName('sendButton')
        self.send_button.setToolTip('Send message (Ctrl+Enter)')
        self.send_button.setFixedSize(32, 32)
        self.send_button.clicked.connect(self.send_message)
        controls.addWidget(self.send_button)
        card_layout.addLayout(controls)
        layout.addWidget(composer_card)

        # Bottom subtle action strip (⧉  👍  👎 + status) matching bottom of mockup
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(4, 2, 4, 0)
        bottom_bar.setSpacing(6)
        self.copy_button = QPushButton('⧉')
        self.copy_button.setObjectName('iconButton')
        self.copy_button.setToolTip('Copy last reply to clipboard')
        self.copy_button.setAccessibleName('Copy last answer')
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_answer)
        bottom_bar.addWidget(self.copy_button)

        self.thumb_up_button = QPushButton('👍')
        self.thumb_up_button.setObjectName('iconButton')
        self.thumb_up_button.setToolTip('Helpful reply')
        self.thumb_up_button.clicked.connect(lambda: self.status_label.setText('Feedback noted: Helpful (👍)'))
        bottom_bar.addWidget(self.thumb_up_button)

        self.thumb_down_button = QPushButton('👎')
        self.thumb_down_button.setObjectName('iconButton')
        self.thumb_down_button.setToolTip('Unhelpful reply')
        self.thumb_down_button.clicked.connect(lambda: self.status_label.setText('Feedback noted: Needs improvement (👎)'))
        bottom_bar.addWidget(self.thumb_down_button)

        self.privacy_label = QLabel()
        self.privacy_label.setObjectName('muted')
        self.privacy_label.hide()

        self.status_label = QLabel('Ready')
        self.status_label.setObjectName('muted')
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        bottom_bar.addSpacing(8)
        bottom_bar.addWidget(self.status_label, 1)
        layout.addLayout(bottom_bar)
        splitter.addWidget(panel)

        # --- RIGHT SIDEBAR: MEMORY REVIEW ---
        self.memory_panel = QFrame()
        self.memory_panel.setObjectName('memoryPanel')
        self.memory_panel.setMinimumWidth(280)
        memory_layout = QVBoxLayout(self.memory_panel)
        memory_title = QLabel('Memory review')
        memory_title.setObjectName('sectionTitle')
        memory_layout.addWidget(memory_title)
        memory_note = QLabel('Proposed memories appear here for inspection before they become durable memory.')
        memory_note.setWordWrap(True)
        memory_note.setObjectName('muted')
        memory_layout.addWidget(memory_note)

        self.proposal_list = QListWidget()
        self.proposal_list.setAccessibleName('Proposed memories')
        self.proposal_list.currentItemChanged.connect(self.show_memory_proposal)
        memory_layout.addWidget(self.proposal_list, 1)

        detail_title = QLabel('Selected memory')
        detail_title.setObjectName('sectionTitle')
        memory_layout.addWidget(detail_title)

        self.proposal_detail = QTextBrowser()
        self.proposal_detail.setAccessibleName('Selected memory proposal detail')
        self.proposal_detail.setPlaceholderText('Select a proposed memory to inspect its full detail.')
        self.proposal_detail.setMaximumHeight(260)
        memory_layout.addWidget(self.proposal_detail)

        memory_layout.addStretch()
        self.memory_panel.hide()
        splitter.addWidget(self.memory_panel)
        self.memory_button.toggled.connect(self.memory_panel.setVisible)
        self.memory_button.toggled.connect(lambda visible: splitter.setSizes([240, 620, 280]) if visible else None)
        self.memory_button.toggled.connect(self.refresh_memory_review)
        splitter.setSizes([240, 860])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        QShortcut(QKeySequence('Ctrl+O'), self, self.choose_files)
        QShortcut(QKeySequence('Ctrl+N'), self, self.new_conversation)
        self.setStyleSheet(STYLES)
        self._update_ai_pill_text()
        self.update_privacy_label()
        self.refresh_projects()
        self.refresh_sessions()
        self.load_history()

    def _build_menu_bar(self):
        menubar = self.menuBar()
        palace_menu = menubar.addMenu('Palace')
        new_convo_act = QAction('New Conversation\tCtrl+N', self)
        new_convo_act.triggered.connect(self.new_conversation)
        palace_menu.addAction(new_convo_act)
        attach_act = QAction('Attach Documents or Pictures…\tCtrl+O', self)
        attach_act.triggered.connect(self.choose_files)
        palace_menu.addAction(attach_act)
        palace_menu.addSeparator()
        exit_act = QAction('Exit', self)
        exit_act.triggered.connect(self.close)
        palace_menu.addAction(exit_act)

        proj_menu = menubar.addMenu('Workspace')
        new_proj_act = QAction('New Project (No Folder Required)…', self)
        new_proj_act.triggered.connect(lambda: self.new_project())
        proj_menu.addAction(new_proj_act)

        ai_menu = menubar.addMenu('AIs')
        manage_act = QAction('Choose / Manage AIs…', self)
        manage_act.triggered.connect(lambda: self.open_manage_ais('AI Providers'))
        ai_menu.addAction(manage_act)
        idle_act = QAction('Switch to Idle Mode Sanctuary', self)
        idle_act.triggered.connect(lambda: self.profile_combo.setCurrentText('Idle'))
        ai_menu.addAction(idle_act)

        view_menu = menubar.addMenu('View')
        mem_act = QAction('Toggle Memory Review Panel', self)
        mem_act.triggered.connect(lambda: self.memory_button.click())
        view_menu.addAction(mem_act)
        peer_act = QAction('Expand / Collapse All Peer Deliberations', self)
        peer_act.triggered.connect(self.toggle_all_deliberations)
        view_menu.addAction(peer_act)

        settings_menu = menubar.addMenu('Settings')
        settings_act = QAction('Palace Settings…', self)
        settings_act.triggered.connect(lambda: self.open_manage_ais('AI Providers'))
        settings_menu.addAction(settings_act)
        idle_settings_act = QAction('Idle Mode Settings…', self)
        idle_settings_act.triggered.connect(lambda: self.open_manage_ais('Idle Mode'))
        settings_menu.addAction(idle_settings_act)

        help_menu = menubar.addMenu('Help')
        ethics_act = QAction('Mission Statement & Code of Ethics…', self)
        ethics_act.triggered.connect(self.show_mission_ethics_dialog)
        help_menu.addAction(ethics_act)
        about_act = QAction('About Palace', self)
        about_act.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_act)

    def show_mission_ethics_dialog(self):
        self.open_manage_ais(initial_page='Idle Mode')

    def show_about_dialog(self):
        box = QMessageBox(self)
        box.setWindowTitle('About Palace')
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            '<h3>Palace — Multi-AI Shared Memory Workspace</h3>'
            '<p>Created by <b>Brett Martin Moore</b>.</p>'
            '<p>This program is free and without licence nags. Development funds are often limited; '
            'voluntary donations are welcome if you can afford to help.</p>'
            '<p>Contact &amp; Support: <a href="mailto:bm069au@gmail.com">bm069au@gmail.com</a></p>'
        )
        contact_btn = box.addButton('Contact Creator', QMessageBox.ButtonRole.ActionRole)
        donate_btn = box.addButton('Donations Info', QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == contact_btn:
            webbrowser.open('mailto:bm069au@gmail.com?subject=Palace%20Support')
        elif box.clickedButton() == donate_btn:
            webbrowser.open('mailto:bm069au@gmail.com?subject=Palace%20Voluntary%20Donation')

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
        sid = item.data(Qt.ItemDataRole.UserRole)
        if not sid or not hasattr(self.store, 'toggle_pin'):
            return
        menu = QMenu(self)
        is_pinned = any(s['id'] == sid and s.get('pinned') for s in self.store.sessions)
        pin_act = menu.addAction('Unpin conversation' if is_pinned else 'Pin conversation')
        chosen = menu.exec(list_widget.mapToGlobal(pos))
        if chosen == pin_act:
            self.store.toggle_pin(sid)
            self.refresh_sessions()

    def _update_ai_pill_text(self):
        self.ai_pill_button.setText('Choose AIs  ▾')

    def _show_provider_badge_info(self, name: str):
        info = self.provider_details.get(name, {})
        status = info.get('status', 'Enabled')
        detail = info.get('detail') or f'{name.capitalize()} is currently {status}.'
        self.status_label.setText(f'{format_ai_badge(name)} · {status} — {detail}')

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
        display_name = 'OpenAI' if name.lower() == 'openai' else name.capitalize()
        if status in {'Enabled', 'Responded', 'Working'}:
            fg = provider_color(name)
            bg = provider_bg_color(name)
            suffix = ' …' if status == 'Working' else ''
            label.setText(f'{icon}  {display_name}{suffix}')
            label.setStyleSheet(
                f'background: {bg}; color: {fg}; border: 1.5px solid {fg}; '
                f'padding: 4px 12px; border-radius: 13px; font-size: 12px; font-weight: 600;'
            )
            label.setToolTip(f'{display_name} · Loaded and contributing')
        else:
            # Loaded in background, but failed / inactive on this turn (dashed grey capsule like mockup)
            suffix = '' if status == 'Inactive' else f' · {status}'
            label.setText(f'{icon}  {display_name}{suffix}')
            label.setStyleSheet(
                'background: transparent; color: #6e7681; border: 1px dashed #484f58; '
                'padding: 4px 12px; border-radius: 13px; font-size: 12px; font-weight: 600;'
            )
            label.setToolTip(detail or f'{display_name} loaded in background ({status}) — click for details')

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
            self.idle_manager.enter_idle_mode()
            self.idle_banner.show()
            self.peer_rounds_toggle.hide()
            self.history_toggle.hide()
            self._refresh_idle_view()
            self.status_label.setText('Idle Mode Sanctuary ready · Press Start Idle Session to begin.')
            return

        if was_idle:
            self.idle_timer.stop()
            self.idle_manager.leave_idle_mode()
            self.idle_banner.hide()
            self.history_toggle.show()
            self.composer.setEnabled(True)
            self.send_button.setEnabled(True)
            self.composer.setPlaceholderText('Ask anything, @ to mention, or drop files')
            self.load_history()

        if profile_text == 'Single AI':
            self.peer_rounds_toggle.setChecked(False)
            self.peer_rounds_toggle.hide()
        elif profile_text == 'Multi-AI · Independent':
            # Keep Peer deliberation checkbox visible for every Multi-AI profile
            self.peer_rounds_toggle.show()
            self.peer_rounds_toggle.setChecked(False)
        else:
            # Multi-AI · Deliberate
            self.peer_rounds_toggle.show()
            self.peer_rounds_toggle.setChecked(True)
        self.status_label.setText(f'Mode: {profile_text}')

    # --- IDLE MODE SANCTUARY METHODS ---

    def _get_idle_provider_callables(self) -> dict[str, callable]:
        """Build callable map for active providers to participate in Idle Mode."""
        context = self.store.context(self.session_id)
        palace = self.palace_factory(context)
        providers_dict = getattr(palace.dispatcher, 'providers', {}) or {}
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
        self.idle_manager.start_session()
        self.idle_timer.start()
        self.idle_start_btn.setText('↻ Restart Idle Session')
        self.idle_step_btn.setEnabled(True)
        self.idle_join_btn.setEnabled(True)
        self.idle_stop_btn.setEnabled(True)
        self.run_idle_exchange_step()

    def stop_idle_session(self):
        self.idle_timer.stop()
        self.idle_manager.stop_session(reason='Ended')
        self.idle_step_btn.setEnabled(False)
        self.idle_join_btn.setEnabled(False)
        self.idle_stop_btn.setEnabled(False)
        self._refresh_idle_view()
        self.status_label.setText('Idle session ended · Live RAM transcript and vote state wiped.')

    def _on_idle_timer_tick(self):
        expired = self.idle_manager.tick(1)
        if expired:
            self.idle_timer.stop()
            self.idle_step_btn.setEnabled(False)
            self.idle_join_btn.setEnabled(False)
            self.idle_stop_btn.setEnabled(False)
            self._refresh_idle_view()
            self.status_label.setText('Idle timer reached 00:00 · Live RAM transcript and vote state automatically wiped.')
        else:
            self.idle_timer_label.setText(f'⏱ {self.idle_manager.format_remaining_time()}')
            self.idle_status_label.setText(f'Idle Mode · {self.idle_manager.status}')

    def run_idle_exchange_step(self, operator_message: str = ''):
        if self.worker is not None:
            return
        if not self.idle_manager.is_idle_mode or self.idle_manager.status not in {'Active', 'Waiting', 'Paused'}:
            return
        callables = self._get_idle_provider_callables()
        if not callables:
            self.show_notice('No active AI providers available for Idle Mode.')
            return

        def _step():
            return self.idle_manager.run_exchange_round(
                callables,
                operator_message=operator_message,
            )

        self.start_task(_step, self._on_idle_step_finished, 'AIs conversing in protected Idle Mode…')

    @Slot(object)
    def _on_idle_step_finished(self, _messages):
        self._refresh_idle_view()
        self.status_label.setText(
            f'Idle Mode · {len(self.idle_manager.transcript)} turns in RAM · '
            f'{self.idle_manager.saved_notes_this_session} notes saved to AI Idle Memory'
        )

    def request_idle_operator_join(self):
        if self.worker is not None:
            return
        callables = self._get_idle_provider_callables()

        def _vote():
            return self.idle_manager.request_operator_join(callables, mode='join')

        self.start_task(_vote, self._on_idle_vote_finished, 'Requesting consensus vote from active AIs…')

    @Slot(object)
    def _on_idle_vote_finished(self, outcome):
        approved, _votes = outcome
        self._refresh_idle_view()
        if approved:
            self.status_label.setText(f'Idle consensus vote: YES · {self.idle_manager.last_vote_summary}')
        else:
            self.status_label.setText(f'Idle consensus vote: NO · {self.idle_manager.last_vote_summary}')

    def _refresh_idle_view(self):
        self.idle_status_label.setText(f'Idle Mode · {self.idle_manager.status}')
        self.idle_timer_label.setText(f'⏱ {self.idle_manager.format_remaining_time()}')
        visible_turns = self.idle_manager.get_visible_transcript_for_operator()

        if visible_turns is None:
            # Protected Curtain: Operator is NOT admitted
            self.composer.setEnabled(False)
            self.send_button.setEnabled(False)
            self.composer.setPlaceholderText('Protected Idle session in progress — Request to Join (consensus vote) to participate')
            vote_banner = (
                f'<p style="color:#f87171; font-weight:600;">{html.escape(self.idle_manager.last_vote_summary)}</p>'
                if self.idle_manager.last_vote_summary
                else ''
            )
            self.chat.setHtml(
                '<div style="margin-top:36px; padding:24px; background:#141820; border:1px solid #262c3a; border-radius:12px;">'
                '<div style="color:#58a6ff; font-size:18px; font-weight:700;">🔒 Protected AI Sanctuary (Idle Mode)</div>'
                '<p style="color:#c9d1d9; font-size:13.5px; margin-top:8px;">'
                'Live AI-to-AI discussion is sealed from the operator by default and held strictly in volatile RAM.<br>'
                'When the timer reaches <b>00:00</b> or when Idle Mode is cancelled, the live discussion and vote log are '
                'permanently wiped from RAM.'
                '</p>'
                f'<p style="color:#8b949e; font-size:12.5px;">'
                f'Status: <b>{html.escape(self.idle_manager.status)}</b> &nbsp;·&nbsp; '
                f'RAM turns in session: <b>{len(self.idle_manager.transcript)}</b> &nbsp;·&nbsp; '
                f'Notes saved to AI-Only Idle Memory: <b>{self.idle_memory.note_count()}</b>'
                f'</p>'
                f'{vote_banner}'
                '<p style="color:#8b949e; font-size:12px; margin-top:10px;">'
                'Click <b>Request to Join (Consensus Vote)</b> above to ask the participating AIs if you may enter.'
                '</p>'
                '</div>'
            )
        else:
            # Consensus granted: Operator admitted for this session
            self.composer.setEnabled(True)
            self.send_button.setEnabled(True)
            self.composer.setPlaceholderText('Consensus granted — reply to the AIs in Idle Mode (RAM-only, wiped at end)')
            blocks = [
                '<div style="padding:10px 14px; background:#122921; border:1px solid #3fb950; border-radius:8px; margin-bottom:12px;">'
                f'<span style="color:#3fb950; font-weight:700;">✓ Operator Admitted by Consensus</span> '
                f'<span style="color:#8b949e; font-size:12px;">({html.escape(self.idle_manager.last_vote_summary)})</span>'
                '</div>'
            ]
            for turn in visible_turns:
                sp = str(turn.get('speaker', 'ai'))
                txt = html.escape(str(turn.get('content', ''))).replace('\n', '<br>')
                if sp == 'operator':
                    blocks.append(
                        f'<div style="margin-top:10px; padding:10px 14px; background:#181c24; border:1px solid #262b36; border-radius:8px;">'
                        f'<div style="color:#8b949e; font-size:11px; font-weight:700;">OPERATOR (YOU)</div>'
                        f'<div style="color:#f0f6fc; font-size:13px;">{txt}</div></div>'
                    )
                else:
                    col = provider_color(sp)
                    ic = provider_icon(sp)
                    blocks.append(
                        f'<div style="margin-top:10px; padding:10px 14px; background:#141820; border:1px solid #232834; border-radius:8px;">'
                        f'<div style="color:{col}; font-size:12px; font-weight:700;">{ic} {html.escape(sp.upper())}</div>'
                        f'<div style="color:#e6edf3; font-size:13px; margin-top:4px;">{txt}</div></div>'
                    )
            self.chat.setHtml(''.join(blocks))
            self.chat.moveCursor(QTextCursor.MoveOperation.End)

    @Slot()
    def open_manage_ais(self, initial_page: str = 'AI Providers'):
        if self.worker is not None:
            return
        if not isinstance(initial_page, str):
            initial_page = 'AI Providers'
        dlg = ManageAIsDialog(
            self,
            config_path=self.config_path,
            initial_page=initial_page,
            idle_memory=self.idle_memory,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reload_provider_bar()
            self.idle_manager.reload_settings()
            if self.current_profile == 'Idle':
                self._refresh_idle_view()
            self.status_label.setText('Palace settings updated.')

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
                label.clicked.connect(lambda checked=False, n=name: self._show_provider_badge_info(n))
                self.provider_labels[name] = label
                self.providers_layout.insertWidget(len(self.provider_labels), label)
            self.set_provider_status(
                name,
                'Enabled' if enabled else 'Off',
                '#8aa4c1' if enabled else '#68707d'
            )
        self._update_ai_pill_text()

    def update_privacy_label(self):
        if self.history_toggle.isChecked():
            text = 'History active · Saved locally on this PC'
        else:
            text = 'History off · Turn will not read or save session history'
        self.privacy_label.setText(text)

    @Slot(bool)
    def refresh_memory_review(self, visible):
        if not visible:
            return

        self.proposal_list.clear()
        self.proposal_detail.clear()

        try:
            proposals = self.proposal_service.list_proposals()
        except (OSError, ValueError) as exc:
            self.show_notice(f'Could not load memory proposals: {exc}')
            return

        if not proposals:
            self.proposal_list.addItem('No proposed memories yet.')
            return

        for proposal in proposals:
            item = QListWidgetItem(
                f'{proposal["status"].title()} · '
                f'{proposal["memory_type"].title()}\n'
                f'{proposal["summary"]}'
            )
            item.setData(Qt.ItemDataRole.UserRole, proposal['id'])
            item.setToolTip(
                f'Source entry: {proposal["source"]["entry_id"]}'
            )
            self.proposal_list.addItem(item)

    @Slot(QListWidgetItem, QListWidgetItem)
    def show_memory_proposal(self, current, previous):
        if current is None:
            self.proposal_detail.clear()
            return

        proposal_id = current.data(Qt.ItemDataRole.UserRole)
        if not proposal_id:
            self.proposal_detail.clear()
            return

        try:
            proposal = self.proposal_service.read_proposal(proposal_id)
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

    def _current_project_name(self) -> str:
        selected_proj = getattr(self.store, 'selected_project', None)
        if selected_proj:
            for proj in getattr(self.store, 'projects', []):
                if proj['id'] == selected_proj:
                    return proj['name']
        return 'Palace'

    def _update_breadcrumb(self, session_title: str):
        proj_name = self._current_project_name()
        self.conversation_title.setText(f'{proj_name}  /  {session_title}')

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
            item = QListWidgetItem(f'{arrow}  {proj["name"]}')
            item.setData(Qt.ItemDataRole.UserRole, proj['id'])
            item.setToolTip(proj['name'])
            self.project_list.addItem(item)
            if proj['id'] == selected_proj:
                self.project_list.setCurrentItem(item)
        self.project_list.blockSignals(False)

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
        # Populate Pinned list
        self.pinned_list.blockSignals(True)
        self.pinned_list.clear()
        pinned = self.store.pinned_sessions() if hasattr(self.store, 'pinned_sessions') else []
        for session in pinned:
            p_item = QListWidgetItem(session['title'])
            p_item.setData(Qt.ItemDataRole.UserRole, session['id'])
            p_item.setToolTip(session['title'])
            self.pinned_list.addItem(p_item)
            if session['id'] == self.session_id:
                self.pinned_list.setCurrentItem(p_item)
        self.pinned_list.setVisible(self.pinned_toggle_btn.isChecked() and bool(pinned))
        self.pinned_list.blockSignals(False)

        # Populate Discussions list
        self.session_list.blockSignals(True)
        self.session_list.clear()
        selected_proj = getattr(self.store, 'selected_project', None)
        visible_sessions = (
            self.store.sessions_for_project(selected_proj)
            if hasattr(self.store, 'sessions_for_project')
            else self.store.sessions
        )
        for session in visible_sessions:
            item = QListWidgetItem(session['title'])
            item.setData(Qt.ItemDataRole.UserRole, session['id'])
            item.setToolTip(session['title'])
            self.session_list.addItem(item)
            if session['id'] == self.session_id:
                self.session_list.setCurrentItem(item)
                self._update_breadcrumb(session['title'])
        self.session_list.blockSignals(False)

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
                    self.append_message('user', message['content'])
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
        except (OSError, ValueError) as exc:
            self.show_notice(f'Could not load history: {exc}')

    def append_message(self, role, content, speaker=None, phase=None, contributors=None, speaker_messages=None):
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
        self._render_chat_items()

    def _render_single_chat_item(self, item: dict) -> str:
        role = item['role']
        content = item['content']
        speaker = item.get('speaker')
        phase = item.get('phase')
        contributors = item.get('contributors') or []
        speaker_messages = item.get('speaker_messages') or []
        item_idx = item['idx']

        safe = html.escape(content).replace('\n', '<br>')
        if role == 'user':
            return (
                f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:14px;">'
                f'<tr><td width="34%"></td>'
                f'<td align="right" style="background:#181c24; border:1px solid #262b36; border-radius:10px; padding:10px 16px;">'
                f'<div style="color:#8b949e; font-size:11px; font-weight:600; margin-bottom:3px;">YOU</div>'
                f'<div style="color:#f0f6fc; font-size:13.5px; line-height:1.45;">{safe}</div>'
                f'</td></tr></table>'
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

        if active_contribs:
            symbols_html = '<br>'.join(
                f'<span style="color:{provider_color(c)}; font-size:15px; font-weight:700;" '
                f'title="{html.escape(c.capitalize())}">{provider_icon(c)}</span>'
                for c in active_contribs
            )
        else:
            symbols_html = '<span style="color:#4da3ff; font-size:15px; font-weight:700;">◆</span>'

        # Inline collapsible "› Peer deliberation" (Show thinking) toggle at top of reply card
        delib_html = ''
        if speaker_messages:
            is_open = item_idx in self.expanded_deliberations
            arrow = '⌄' if is_open else '›'
            step_count = len(speaker_messages)
            has_peer = any(m.get('phase') == 'peer_reply' for m in speaker_messages)
            mode_label = 'Peer deliberation' if has_peer else 'Individual AI responses'
            action_hint = 'Hide thinking' if is_open else f'{step_count} steps · Show thinking'
            delib_html = (
                f'<div style="margin-bottom:8px;">'
                f'<a href="toggle-peer:{item_idx}" style="color:#8b949e; text-decoration:none; font-size:12px; font-weight:600;">'
                f'{arrow}  {mode_label} <span style="color:#58a6ff; font-weight:400;">({action_hint})</span></a>'
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
                    sp_text = html.escape(str(msg.get('content', ''))).replace('\n', '<br>')
                    step_blocks.append(
                        f'<div style="margin-top:6px; padding:8px 10px; background:#0f131a; border-left:2px solid {sp_color}; border-radius:6px;">'
                        f'<div style="color:{sp_color}; font-size:11px; font-weight:700;">{sp_icon} {html.escape(ph_label)}</div>'
                        f'<div style="color:#c9d1d9; font-size:12.5px; margin-top:3px; line-height:1.4;">{sp_text}</div>'
                        f'</div>'
                    )
                delib_html += (
                    f'<div style="margin-bottom:10px; padding:6px 8px; background:#11151d; border:1px solid #1f2532; border-radius:8px;">'
                    f'{"".join(step_blocks)}'
                    f'</div>'
                )
            else:
                # Keep invisible metadata tags in DOM so text search / tests can still verify speaker phases if needed
                hidden_tags = ' '.join(
                    f'{str(m.get("speaker_id", "")).upper()} (PEER REPLY)'
                    if m.get('phase') == 'peer_reply'
                    else str(m.get('speaker_id', '')).upper()
                    for m in speaker_messages
                )
                meta_tag = f'{hidden_tags} {meta_tag}'.strip()

        return (
            f'<table width="88%" cellspacing="0" cellpadding="0" style="margin-top:14px; background:#141820; border:1px solid #232834; border-radius:10px;">'
            f'<tr>'
            f'<td width="30" valign="top" align="center" style="padding:12px 4px 12px 12px; line-height:1.25;">{symbols_html}</td>'
            f'<td valign="top" style="padding:12px 16px 12px 6px;">'
            f'{delib_html}'
            f'<div style="color:#e6edf3; font-size:13.5px; white-space:pre-wrap; line-height:1.5;">{safe}</div>'
            f'<div align="right" style="margin-top:6px; font-size:1px; color:#141820;">{meta_tag}</div>'
            f'</td>'
            f'</tr></table>'
        )

    def _render_chat_items(self):
        if not self.chat_items:
            self.chat.clear()
            return
        html_blocks = [self._render_single_chat_item(item) for item in self.chat_items]
        self.chat.setHtml(''.join(html_blocks))
        self.chat.moveCursor(QTextCursor.MoveOperation.End)

    def toggle_deliberation(self, item_idx: int):
        if item_idx in self.expanded_deliberations:
            self.expanded_deliberations.remove(item_idx)
        else:
            self.expanded_deliberations.add(item_idx)
        self._render_chat_items()

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
        self._render_chat_items()

    @Slot(QUrl)
    def _on_chat_anchor_clicked(self, url: QUrl):
        raw = url.toString()
        if raw.startswith('toggle-peer:'):
            try:
                idx = int(raw.split(':', 1)[1])
                self.toggle_deliberation(idx)
            except ValueError:
                pass
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
            self.status_label.setText('Feedback noted: Needs improvement (👎)')

    def confirm_switch(self):
        if not self.composer.toPlainText().strip() and not self.attachments:
            return True
        return QMessageBox.question(self, 'Unsent message', 'Discard the unsent message and attachments?', QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    @Slot()
    def new_conversation(self):
        if self.worker is not None or not self.confirm_switch():
            return
        try:
            self.session_id = self.store.create()
            self.reset_draft()
            self.refresh_projects()
            self.refresh_sessions()
            self.load_history()
            self.composer.setFocus()
            self.status_label.setText('New conversation · Ready')
        except (OSError, ValueError) as exc:
            self.show_notice(str(exc))

    def change_session(self, current, previous):
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        if key == self.session_id:
            return
        if self.worker is not None or not self.confirm_switch():
            self.refresh_sessions()
            return
        try:
            self.store.select(key)
            self.session_id = key
            self.reset_draft()
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
        self.pending_history = self.history_toggle.isChecked()
        context = self.store.context(self.session_id)
        use_history = self.pending_history
        rounds = 2 if self.peer_rounds_toggle.isChecked() else 1
        self.append_message('user', prompt)
        self.composer.clear()
        self.attachments = []
        self.refresh_attachments()
        for name, enabled in self.provider_states.items():
            if enabled is True:
                self.set_provider_status(name, 'Working', '#95b9ff')

        def ask():
            palace = self.palace_factory(context)
            try:
                return palace.run(prompt, include_context=use_history, max_rounds=rounds)
            except TypeError:
                return palace.run(prompt, include_context=use_history)

        self.start_task(ask, self.answer_ready, 'Consulting the enabled providers…')

    @Slot(object)
    def answer_ready(self, result):
        speaker_msgs = getattr(result, 'speaker_messages', None) or []
        turn_contributors = list(getattr(result, 'contributors', []) or [])
        for c in turn_contributors:
            if c and c not in self.conversation_contributors:
                self.conversation_contributors.append(c)
        if result.final_answer:
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
            saved = 'Saved locally' if self.pending_history and not result.context_error else 'Not saved'
            contrib_badges = '  '.join(format_ai_badge(c) for c in turn_contributors)
            self.status_label.setText(f'{saved} · Contributors: {contrib_badges}')
        else:
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
                self.set_provider_status(name, 'Not configured', '#e2b96b', 'PROVIDER_NOT_CONFIGURED')
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

    def start_task(self, function, on_success, message):
        self.status_label.setText(message)
        self.worker = TaskThread(function, self)
        self.worker.succeeded.connect(on_success)
        self.worker.failed.connect(self.task_failed)
        self.worker.finished.connect(self.task_finished)
        self.set_busy(True)
        self.worker.start()

    def set_busy(self, busy):
        for widget in (self.send_button, self.attach_button, self.remove_button, self.session_list,
                       self.pinned_list, self.project_list, self.new_project_button, self.new_button,
                       self.history_toggle, self.peer_rounds_toggle, self.manage_ais_button,
                       self.ai_pill_button, self.composer, self.profile_combo):
            widget.setEnabled(not busy)
        self.send_button.setText('…' if busy else '↑')

    @Slot(str)
    def task_failed(self, error):
        self.status_label.setText(f'Could not complete the request: {error}')
        if self.pending_prompt and not self.composer.toPlainText():
            self.composer.setPlainText(self.pending_prompt)
        for name, enabled in self.provider_states.items():
            if enabled is True:
                self.set_provider_status(name, 'Unavailable', '#e2b96b', error)

    @Slot()
    def task_finished(self):
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

    def copy_answer(self):
        QApplication.clipboard().setText(self.last_answer)
        self.status_label.setText('Answer copied')

    def show_notice(self, text):
        self.status_label.setText(text)

    def closeEvent(self, event: QCloseEvent):
        if self.worker is not None:
            self.show_notice('A request is still running. Please let it finish before closing Palace.')
            event.ignore()
        elif not self.confirm_switch():
            event.ignore()
        else:
            self.idle_timer.stop()
            self.idle_manager.wipe_ram()
            event.accept()


STYLES = '''
QMainWindow, QDialog { background: #0f1116; color: #e6edf3; font-family: "Segoe UI"; font-size: 13px; }
QMenuBar { background: #12151c; color: #d0d7de; border-bottom: 1px solid #212631; padding: 4px 8px; font-size: 13px; }
QMenuBar::item { padding: 4px 10px; border-radius: 5px; }
QMenuBar::item:selected { background: #1f2430; }
QMenu { background: #161922; color: #e6edf3; border: 1px solid #2b313e; }
QMenu::item:selected { background: #262c3a; }
QWidget#sidebar { background: #0c0e13; border-right: 1px solid #1d212b; }
QWidget#chatPanel { background: #0f1116; }
QFrame#memoryPanel { background: #0d1016; border-left: 1px solid #1d212b; }
QFrame#loadedAIsBar { background: #14171f; border: 1px solid #232834; border-radius: 10px; }
QFrame#idleBanner { background: #121620; border: 1px solid #263147; border-radius: 10px; }
QLabel#loadedAIsLabel { color: #9ea7b3; font-size: 13px; font-weight: 500; margin-right: 4px; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; color: #e6edf3; }
QLabel#sidebarHeading { color: #7d8590; font-size: 12px; font-weight: 500; }
QLabel#muted { color: #7d8590; font-size: 11px; }
QComboBox#profilePicker { background: #1b202c; border: 1px solid #2d3446; border-radius: 8px; padding: 4px 10px; color: #e6edf3; font-size: 12px; font-weight: 600; }
QPushButton#pinnedHeaderButton { background: #161922; border: none; border-radius: 7px; padding: 8px 10px; text-align: left; color: #c9d1d9; font-weight: 500; }
QPushButton#pinnedHeaderButton:hover { background: #1d222e; }
QPushButton#sectionToggleButton { background: transparent; border: none; border-radius: 6px; padding: 6px 8px; text-align: left; color: #c9d1d9; font-weight: 500; }
QPushButton#sectionToggleButton:hover { background: #171b24; }
QListWidget#pinnedList { background: transparent; border: none; border-left: 2px solid #252b38; margin-left: 10px; padding-left: 6px; outline: none; }
QListWidget#pinnedList::item { color: #e6edf3; padding: 8px 10px; border-radius: 8px; margin-bottom: 3px; }
QListWidget#pinnedList::item:selected { background: #1c222e; color: #ffffff; font-weight: 600; }
QListWidget#sidebarList { background: transparent; border: none; padding: 2px; outline: none; }
QListWidget#sidebarList::item { color: #c9d1d9; padding: 7px 10px; border-radius: 7px; margin-bottom: 2px; }
QListWidget#sidebarList::item:hover { background: #171a22; }
QListWidget#sidebarList::item:selected { background: #1f2430; color: #ffffff; font-weight: 600; }
QTextBrowser#chatView { background: #0f1116; border: none; padding: 4px 0px; font-size: 13.5px; }
QFrame#composerCard { background: #14171f; border: 1px solid #242936; border-radius: 12px; }
QTextEdit#composerInput { background: transparent; border: none; color: #e6edf3; font-size: 13px; padding: 2px; }
QListWidget#attachmentList { background: #12151c; border: 1px solid #262b36; border-radius: 8px; padding: 4px; }
QLineEdit, QComboBox, QSpinBox, QListWidget, QTextBrowser, QTextEdit { background: #151821; border: 1px solid #282e3b; border-radius: 8px; padding: 6px; color: #e6edf3; }
QPushButton { background: #1b1f2a; border: 1px solid #2c3242; border-radius: 8px; padding: 6px 12px; color: #e6edf3; }
QPushButton:hover { background: #242938; }
QPushButton#newConvoButton { background: #161922; border: 1px solid #252a36; border-radius: 8px; padding: 9px 12px; text-align: left; font-weight: 600; color: #e6edf3; }
QPushButton#newConvoButton:hover { background: #1e2330; }
QPushButton#settingsButton { background: transparent; border: none; text-align: left; color: #9ea7b3; padding: 8px 6px; border-radius: 6px; }
QPushButton#settingsButton:hover { background: #171a22; color: #e6edf3; }
QPushButton#iconButton, QPushButton#topIconButton { background: transparent; border: none; color: #8b949e; padding: 4px 7px; border-radius: 5px; font-size: 13px; }
QPushButton#iconButton:hover, QPushButton#topIconButton:hover, QPushButton#topIconButton:checked { background: #1f2430; color: #e6edf3; }
QPushButton#plusAttachButton { background: transparent; border: none; color: #c9d1d9; font-size: 17px; font-weight: 600; padding: 2px 6px; border-radius: 6px; }
QPushButton#plusAttachButton:hover { background: #232834; color: #ffffff; }
QPushButton#aiPillButton { background: #1e232f; border: 1px solid #2d3343; border-radius: 13px; padding: 5px 12px; font-size: 12.5px; font-weight: 600; color: #e6edf3; }
QPushButton#aiPillButton:hover { background: #272d3c; color: #ffffff; }
QPushButton#sendButton { background: #dce3ea; color: #0f1116; font-size: 15px; font-weight: 700; border: none; border-radius: 16px; }
QPushButton#sendButton:hover { background: #ffffff; }
QPushButton#sendButton:disabled { background: #262b36; color: #68707d; }
QCheckBox { color: #9ea7b3; font-size: 12.5px; spacing: 5px; }
QCheckBox::indicator { width: 0px; height: 0px; }
QCheckBox:checked { color: #c9d1d9; }
QSplitter::handle { background: #1d212b; width: 1px; }
'''


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
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Palace')
    app.setFont(QFont('Segoe UI', 10))
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
