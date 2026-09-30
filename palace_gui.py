"""Palace desktop interface. Provider and memory work remains in core services."""
import argparse
import html
import json
from pathlib import Path
import sys

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from attachment_service import MAX_TOTAL_CHARS, compose_question, extract_attachment
from palace_config import CONFIG_PATH
from memory_proposal_service import MemoryProposalService
from session_store import SessionStore


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
    send_requested = Signal()
    unsupported_paste = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(False)
        self.setAcceptDrops(True)
        self.setAccessibleName('Message to Palace')
        self.setPlaceholderText('Ask Palace… or drop a document here')
        self.setMinimumHeight(92)
        self.setMaximumHeight(160)

    def canInsertFromMimeData(self, source):
        return source.hasUrls() or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls() and any(url.isLocalFile() for url in source.urls()):
            self.files_added.emit([url.toLocalFile() for url in source.urls() if url.isLocalFile()])
        elif source.hasImage():
            self.unsupported_paste.emit()
        else:
            super().insertFromMimeData(source)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.send_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class PalaceWindow(QMainWindow):
    def __init__(self, store=None, palace_factory=None, provider_states=None, demo=False, proposal_service=None):
        super().__init__()
        self.store = store or SessionStore()
        self.proposal_service = proposal_service or MemoryProposalService()
        self.session_id = self.store.selected
        self.palace_factory = palace_factory or self._build_palace
        self.attachments = []
        self.worker = None
        self.last_answer = ''
        self.last_question = ''
        self.pending_prompt = ''
        self.pending_history = True
        self.provider_labels = {}
        self.demo = demo
        self.setWindowTitle('Palace — Preview (simulated providers)' if demo else 'Palace')
        self.resize(1160, 810)
        self.setMinimumSize(840, 650)
        self.setAcceptDrops(True)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel('Palace')
        title.setObjectName('title')
        header.addWidget(title)
        subtitle = QLabel('A shared conversation. A lasting memory.')
        subtitle.setObjectName('muted')
        header.addWidget(subtitle)
        header.addStretch()
        if demo:
            header.addWidget(QLabel('LOCAL PREVIEW · NO API CALLS'))
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 16, 0)
        side.setSpacing(12)
        self.new_button = QPushButton('+  New conversation')
        self.new_button.clicked.connect(self.new_conversation)
        side.addWidget(self.new_button)
        side.addWidget(QLabel('CONVERSATIONS'))
        self.session_list = QListWidget()
        self.session_list.setAccessibleName('Conversations')
        self.session_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.session_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.session_list.currentItemChanged.connect(self.change_session)
        side.addWidget(self.session_list, 1)
        note = QLabel('Conversation history stays on this PC.\nSelected knowledge will be a separate memory layer.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        side.addWidget(note)
        splitter.addWidget(sidebar)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(10)
        self.conversation_title = QLabel('New conversation')
        self.conversation_title.setObjectName('sectionTitle')
        self.conversation_title.setWordWrap(True)
        layout.addWidget(self.conversation_title)
        providers = QHBoxLayout()
        if provider_states is None:
            try:
                provider_states = {name: settings.get('enabled', False) for name, settings in json.loads(CONFIG_PATH.read_text())['providers'].items()}
            except (OSError, ValueError, KeyError) as exc:
                provider_states = {}
                self.config_warning = str(exc)
        self.provider_states = provider_states
        for name, enabled in provider_states.items():
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            self.provider_labels[name] = label
            providers.addWidget(label)
            self.set_provider_status(name, 'Enabled' if enabled else 'Off', '#8aa4c1' if enabled else '#748094')
        providers.addStretch()
        layout.addLayout(providers)

        self.chat = QTextBrowser()
        self.chat.setAccessibleName('Conversation history')
        self.chat.setOpenLinks(False)
        self.chat.setAcceptDrops(False)
        layout.addWidget(self.chat, 1)
        actions = QHBoxLayout()
        self.history_toggle = QCheckBox('Use & save session history')
        self.history_toggle.setChecked(True)
        self.history_toggle.setToolTip('Recent history and attached text from saved turns go to the enabled providers. Switch off to skip history reads and writes for this turn.')
        self.history_toggle.toggled.connect(self.update_privacy_label)
        actions.addWidget(self.history_toggle)
        actions.addStretch()
        self.copy_button = QPushButton('Copy last answer')
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_answer)
        actions.addWidget(self.copy_button)
        self.memory_button = QPushButton('Memory review')
        self.memory_button.setCheckable(True)
        actions.addWidget(self.memory_button)
        layout.addLayout(actions)

        self.attachment_list = QListWidget()
        self.attachment_list.setAccessibleName('Attached files; select a file then Remove selected')
        self.attachment_list.setMaximumHeight(90)
        self.attachment_list.hide()
        layout.addWidget(self.attachment_list)
        self.composer = Composer()
        self.composer.files_added.connect(self.add_files)
        self.composer.send_requested.connect(self.send_message)
        self.composer.unsupported_paste.connect(lambda: self.show_notice('Image paste is not supported yet. Attach a text document, PDF or Word file.'))
        layout.addWidget(self.composer)

        controls = QHBoxLayout()
        self.attach_button = QPushButton('Attach files…')
        self.attach_button.clicked.connect(self.choose_files)
        controls.addWidget(self.attach_button)
        self.remove_button = QPushButton('Remove selected')
        self.remove_button.clicked.connect(self.remove_attachment)
        self.remove_button.hide()
        controls.addWidget(self.remove_button)
        hint = QLabel('Enter: new line  ·  Ctrl+Enter: send')
        hint.setObjectName('muted')
        controls.addWidget(hint)
        controls.addStretch()
        self.send_button = QPushButton('Send')
        self.send_button.setObjectName('sendButton')
        self.send_button.setMinimumWidth(100)
        self.send_button.clicked.connect(self.send_message)
        controls.addWidget(self.send_button)
        layout.addLayout(controls)
        self.privacy_label = QLabel()
        self.privacy_label.setWordWrap(True)
        self.privacy_label.setObjectName('muted')
        layout.addWidget(self.privacy_label)
        self.status_label = QLabel('Ready')
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)
        splitter.addWidget(panel)
        self.memory_panel = QFrame()
        self.memory_panel.setMinimumWidth(280)
        memory_layout = QVBoxLayout(self.memory_panel)
        memory_title = QLabel('Memory review')
        memory_title.setObjectName('sectionTitle')
        memory_layout.addWidget(memory_title)
        memory_note = QLabel('Proposed memories will appear here for inspection before they become durable memory.')
        memory_note.setWordWrap(True)
        memory_note.setObjectName('muted')
        memory_layout.addWidget(memory_note)

        self.proposal_list = QListWidget()
        self.proposal_list.setAccessibleName("Proposed memories")
        memory_layout.addWidget(self.proposal_list, 1)
        memory_layout.addStretch()
        self.memory_panel.hide()
        splitter.addWidget(self.memory_panel)
        self.memory_button.toggled.connect(self.memory_panel.setVisible)
        self.memory_button.toggled.connect(lambda visible: splitter.setSizes([245, 600, 300]) if visible else None)
        self.memory_button.toggled.connect(self.refresh_memory_review)
        splitter.setSizes([245, 850])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        QShortcut(QKeySequence('Ctrl+O'), self, self.choose_files)
        QShortcut(QKeySequence('Ctrl+N'), self, self.new_conversation)
        self.setStyleSheet(STYLES)
        self.update_privacy_label()
        self.refresh_sessions()
        self.load_history()

    @staticmethod
    def _build_palace(context):
        from palace_cli import build_configured_palace
        return build_configured_palace(context_service=context)

    def set_provider_status(self, name, status, colour, detail=''):
        label = self.provider_labels.get(name)
        if label:
            label.setText(f'● {name.capitalize()} · {status}')
            label.setStyleSheet(f'color: {colour}; font-size: 11px;')
            label.setToolTip(detail or status)

    def update_privacy_label(self):
        if self.history_toggle.isChecked():
            text = 'Recent history and attached text are shared with enabled providers. Completed turns save locally; permanent memory stays off.'
        else:
            text = 'This turn sends only your message and attachments. It will not read or save conversation history.'
        self.privacy_label.setText(text)

    @Slot(bool)
    def refresh_memory_review(self, visible):
        if not visible:
            return

        self.proposal_list.clear()

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

    def refresh_sessions(self):
        self.session_list.blockSignals(True)
        self.session_list.clear()
        for session in self.store.sessions:
            item = QListWidgetItem(session['title'])
            item.setData(Qt.ItemDataRole.UserRole, session['id'])
            item.setToolTip(session['title'])
            self.session_list.addItem(item)
            if session['id'] == self.session_id:
                self.session_list.setCurrentItem(item)
                self.conversation_title.setText(session['title'])
        self.session_list.blockSignals(False)

    def load_history(self):
        self.chat.clear()
        self.last_answer = ''
        self.copy_button.setEnabled(False)
        try:
            messages = self.store.messages(self.session_id)
            for message in messages:
                self.append_message(message['role'], message['content'])
                if message['role'] == 'assistant':
                    self.last_answer = message['content']
            self.copy_button.setEnabled(bool(self.last_answer))
            if not messages:
                self.chat.setHtml('<h2 style="color:#e6edf7">What are we working on?</h2><p style="color:#a5b3c6">Ask a question, paste some text, or attach a document.<br>Palace brings the enabled AIs together in one conversation.</p>')
        except (OSError, ValueError) as exc:
            self.show_notice(f'Could not load history: {exc}')

    def append_message(self, role, content):
        label = 'YOU' if role == 'user' else 'PALACE'
        colour = '#95b9ff' if role == 'user' else '#90d7c1'
        safe = html.escape(content).replace('\n', '<br>')
        self.chat.append(f'<p style="color:{colour}; margin-top:22px"><b>{label}</b></p><p style="white-space:pre-wrap; line-height:1.5">{safe}</p>')
        self.chat.moveCursor(QTextCursor.MoveOperation.End)

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
        paths, _ = QFileDialog.getOpenFileNames(self, 'Attach documents', '', 'Documents (*.txt *.md *.pdf *.docx *.csv *.tsv *.json *.py *.ps1 *.js *.ts *.yaml *.yml *.xml *.html *.log);;All files (*)')
        self.add_files(paths)

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
            entry = QListWidgetItem(f'{item.name}  ·  {len(item.text):,} characters{note}')
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
        self.append_message('user', prompt)
        self.composer.clear()
        self.attachments = []
        self.refresh_attachments()
        for name, enabled in self.provider_states.items():
            if enabled:
                self.set_provider_status(name, 'Working', '#95b9ff')

        def ask():
            palace = self.palace_factory(context)
            return palace.run(prompt, include_context=use_history)

        self.start_task(ask, self.answer_ready, 'Consulting the enabled providers…')

    @Slot(object)
    def answer_ready(self, result):
        if result.final_answer:
            self.append_message('assistant', result.final_answer)
            self.last_answer = result.final_answer
            self.copy_button.setEnabled(True)
            if self.pending_history and not result.context_error:
                try:
                    self.store.rename_from_question(self.session_id, self.last_question)
                    self.refresh_sessions()
                except OSError as exc:
                    self.show_notice(f'Answer saved, but conversation title could not be saved: {exc}')
            saved = 'Saved locally' if self.pending_history and not result.context_error else 'Not saved'
            self.status_label.setText(f'{saved} · Contributors: {", ".join(result.contributors)}')
        else:
            self.status_label.setText('No provider returned an answer. Your message has been restored for retry.')
            self.composer.setPlainText(self.pending_prompt)
        for name, enabled in self.provider_states.items():
            response = result.provider_results.get(name)
            if not enabled:
                continue
            if response is None:
                self.set_provider_status(name, 'Not configured', '#e2b96b')
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
                       self.new_button, self.history_toggle, self.composer):
            widget.setEnabled(not busy)
        self.send_button.setText('Working…' if busy else 'Send')

    @Slot(str)
    def task_failed(self, error):
        self.status_label.setText(f'Could not complete the request: {error}')
        if self.pending_prompt and not self.composer.toPlainText():
            self.composer.setPlainText(self.pending_prompt)
        for name, enabled in self.provider_states.items():
            if enabled:
                self.set_provider_status(name, 'Unavailable', '#e2b96b', error)

    @Slot()
    def task_finished(self):
        completed = self.worker
        self.worker = None
        self.pending_prompt = ''
        self.set_busy(False)
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
            event.accept()


STYLES = '''
QMainWindow, QWidget { background: #101722; color: #e6edf7; font-family: "Segoe UI"; font-size: 13px; }
QLabel#title { font-size: 29px; font-weight: 650; }
QLabel#sectionTitle { font-size: 19px; font-weight: 600; }
QLabel#muted { color: #a5b3c6; font-size: 12px; }
QTextBrowser, QTextEdit, QListWidget { background: #172130; border: 1px solid #304055; border-radius: 8px; padding: 10px; selection-background-color: #365b8f; }
QTextBrowser { padding: 18px; font-size: 14px; }
QListWidget::item { padding: 9px 4px; border-radius: 4px; }
QListWidget::item:selected { background: #2a3c55; }
QPushButton { background: #233149; border: 1px solid #3a4d68; border-radius: 6px; padding: 9px 13px; }
QPushButton:hover { background: #304663; }
QPushButton:focus, QTextEdit:focus { border: 1px solid #9cbbff; }
QPushButton:disabled { color: #778397; background: #1a2535; }
QPushButton#sendButton { background: #8cacfa; color: #0f192c; font-weight: 600; border: none; }
QPushButton#sendButton:disabled { background: #3d506d; color: #b5c3d7; }
QCheckBox { spacing: 7px; }
QSplitter::handle { background: #26374a; width: 1px; }
'''


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
                def generate(self, prompt):
                    import time
                    time.sleep(0.3)
                    return ProviderResponse(text='This is a local preview response.\n\nThe Palace window, saved conversations and attachment handling are working. Live mode uses your configured AI providers. No API was called in this preview.')

            preview_root = Path(os.environ['LOCALAPPDATA']) / 'Palace' / 'ui-preview'
            store = SessionStore(preview_root)
            proposal_service = MemoryProposalService(
                preview_root / 'memory_proposals.jsonl'
            )
            window = PalaceWindow(
                store,
                lambda context: build_palace(
                    {'preview': PreviewProvider()},
                    context_service=context,
                ),
                {'preview': True},
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
