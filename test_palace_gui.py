import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QMimeData, Qt, QUrl, QPoint, QPointF
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from attachment_service import Attachment, MAX_TEXT_CHARS, compose_question, extract_attachment
from bootstrap import build_palace
from memory_proposal_service import MemoryProposalService
from palace_gui import PalaceWindow
from providers import ProviderResponse
from session_store import SessionStore


class Provider:
    def __init__(self, answer='A useful answer', fail=False, delay=0):
        self.answer, self.fail, self.delay = answer, fail, delay
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError('429 rate limited')
        return ProviderResponse(text=self.answer)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_text_snapshot_unicode_and_limits(self):
        path = self.root / 'notes.md'
        path.write_text('é' * (MAX_TEXT_CHARS + 2), encoding='utf-8')
        item = extract_attachment(path)
        path.write_text('changed', encoding='utf-8')
        self.assertTrue(item.truncated)
        self.assertEqual(item.text, 'é' * MAX_TEXT_CHARS)
        prompt = compose_question('Summarise', [item])
        self.assertIn('first 24,000 characters only', prompt)
        self.assertNotIn(str(self.root), prompt)
        with self.assertRaises(ValueError):
            compose_question('Question', [item] * 3)

    def test_unsupported_binary_directory_and_empty(self):
        with self.assertRaises(ValueError):
            extract_attachment(self.root)
        for name, data in [('image.png', b'image'), ('empty.txt', b''), ('binary.txt', b'a\x00b')]:
            path = self.root / name
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                extract_attachment(path)

    def test_word_paragraph_table_order(self):
        from docx import Document
        doc = Document()
        doc.add_paragraph('Before table')
        doc.add_table(rows=1, cols=1).cell(0, 0).text = 'Table value'
        doc.add_paragraph('After table')
        path = self.root / 'test.docx'
        doc.save(path)
        text = extract_attachment(path).text
        self.assertLess(text.index('Before'), text.index('Table'))
        self.assertLess(text.index('Table'), text.index('After'))

    def test_pdf_blank_and_encrypted_rejected(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        path = self.root / 'blank.pdf'
        writer.write(path)
        with self.assertRaisesRegex(ValueError, 'No readable text'):
            extract_attachment(path)
        writer.encrypt('test-password')
        writer.write(path)
        with self.assertRaisesRegex(ValueError, 'Password-protected'):
            extract_attachment(path)

    def test_named_sessions_isolate_history_and_restore_selection(self):
        store = SessionStore(self.root)
        first = store.selected
        store.context(first).append_exchange('First question', 'First answer')
        store.rename_from_question(first, 'First question')
        second = store.create()
        self.assertEqual(store.messages(second), [])
        store.context(second).append_exchange('Second question', 'Second answer')
        restored = SessionStore(self.root)
        self.assertEqual(restored.selected, second)
        self.assertEqual(restored.messages(first)[0]['content'], 'First question')
        self.assertNotIn('First', restored.context(second).load_recent())
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_legacy_history_reused_without_modification(self):
        legacy = self.root / 'session_context.jsonl'
        original = json.dumps({'role': 'user', 'content': 'Earlier message'}) + '\n'
        legacy.write_text(original)
        store = SessionStore(self.root)
        self.assertEqual(store.selected, 'legacy')
        self.assertEqual(store.messages('legacy')[0]['content'], 'Earlier message')
        self.assertEqual(legacy.read_text(), original)

    def test_bad_index_and_path_traversal_preserved_and_rejected(self):
        path = self.root / 'conversations.json'
        original = json.dumps({'selected': '../escape', 'sessions': [{'id': '../escape', 'title': 'bad'}]})
        path.write_text(original)
        with self.assertRaises(ValueError):
            SessionStore(self.root)
        self.assertEqual(path.read_text(), original)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.provider = Provider()
        self.window = self.make_window()
        self.window.show()
        self.app.processEvents()

    def make_window(self):
        def factory(context):
            palace = build_palace(
                {"test": self.provider},
                context_service=context,
            )
            palace.memory_service.search = lambda _: self.fail(
                "Unexpected permanent-memory read"
            )
            return palace

        proposal_service = MemoryProposalService(
            self.root / "memory-proposals.jsonl"
        )
        return PalaceWindow(
            SessionStore(self.root),
            factory,
            {"test": True, "off": False},
            proposal_service=proposal_service,
        )

    def tearDown(self):
        self.wait_idle()
        self.window.reset_draft()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_idle(self):
        deadline = time.monotonic() + 8
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIsNone(self.window.worker, 'Background work did not finish')

    def send(self, text='Hello Palace'):
        self.window.composer.setPlainText(text)
        QTest.keyClick(self.window.composer, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.wait_idle()

    def test_memory_review_panel_toggles(self):
        self.assertFalse(self.window.memory_panel.isVisible())
        self.window.memory_button.click()
        self.app.processEvents()
        self.assertTrue(self.window.memory_panel.isVisible())
        self.window.memory_button.click()
        self.app.processEvents()
        self.assertFalse(self.window.memory_panel.isVisible())

    def test_memory_review_lists_summaries_without_full_detail(self):
        context = self.window.store.context(self.window.session_id)
        source_id = context.append(
            "user",
            "Full PySide6 decision detail",
        )
        self.window.proposal_service.propose_from_session(
            context,
            source_id,
            "Palace uses PySide6",
        )

        self.window.memory_button.click()
        self.app.processEvents()

        displayed = self.window.proposal_list.item(0).text()
        self.assertIn("Palace uses PySide6", displayed)
        self.assertNotIn("Full PySide6 decision detail", displayed)

    def test_send_copy_and_window_restart_restores_history(self):
        self.send('Remember apricot')
        self.assertIn('A useful answer', self.window.chat.toPlainText())
        self.window.copy_answer()
        self.assertEqual(self.app.clipboard().text(), 'A useful answer')
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.window = self.make_window()
        self.assertIn('Remember apricot', self.window.chat.toPlainText())
        self.send('What did I say?')
        self.assertIn('Remember apricot', self.provider.prompts[-1])

    def test_new_conversation_does_not_inherit_previous(self):
        self.send('Private to first conversation')
        old_id = self.window.session_id
        self.window.new_conversation()
        self.assertNotEqual(old_id, self.window.session_id)
        self.send('Another conversation')
        self.assertNotIn('Private to first conversation', self.provider.prompts[-1])

    def test_history_off_neither_reads_nor_saves(self):
        self.send('Old context')
        path = self.window.store.context(self.window.session_id).path
        original = path.read_bytes()
        self.window.history_toggle.setChecked(False)
        self.send('Unrecorded question')
        self.assertNotIn('Old context', self.provider.prompts[-1])
        self.assertEqual(original, path.read_bytes())
        self.assertIn('Not saved', self.window.status_label.text())

    def test_attachment_dialog_sends_snapshot_and_preserves_source(self):
        path = self.root / 'attach.md'
        path.write_text('The chosen door is blue.')
        with patch.object(QFileDialog, 'getOpenFileNames', return_value=([str(path)], '')):
            self.window.choose_files()
        self.wait_idle()
        self.assertEqual(len(self.window.attachments), 1)
        self.assertEqual(self.provider.prompts, [])
        self.send('Which door?')
        self.assertIn('The chosen door is blue.', self.provider.prompts[-1])
        self.assertEqual(path.read_text(), 'The chosen door is blue.')
        self.assertEqual(self.window.attachments, [])

    def test_file_clipboard_and_text_clipboard(self):
        path = self.root / 'paste.txt'
        path.write_text('pasted document')
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        self.window.composer.insertFromMimeData(mime)
        self.wait_idle()
        self.assertEqual(self.window.attachments[0].text, 'pasted document')
        text = QMimeData()
        text.setText('pasted question')
        self.window.composer.insertFromMimeData(text)
        self.assertEqual(self.window.composer.toPlainText(), 'pasted question')
        self.window.remove_attachment()
        self.assertFalse(self.window.attachments)

    def test_drag_drop_local_file(self):
        path = self.root / 'drop.txt'
        path.write_text('dropped document')
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.window, enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.window, drop)
        self.wait_idle()
        self.assertEqual(self.window.attachments[0].text, 'dropped document')

    def test_provider_failure_restores_message_and_no_history(self):
        self.provider.fail = True
        self.send('Retry me')
        self.assertIn('Retry me', self.window.composer.toPlainText())
        self.assertFalse(self.window.store.context(self.window.session_id).path.exists())
        self.assertIn('Limited', self.window.provider_labels['test'].text())

    def test_ui_responsive_and_close_is_safe_during_work(self):
        self.provider.delay = 0.25
        self.window.composer.setPlainText('Wait a moment')
        self.window.send_message()
        self.assertFalse(self.window.send_button.isEnabled())
        self.assertFalse(self.window.close())
        self.assertTrue(self.window.isVisible())
        self.app.processEvents()
        self.wait_idle()
        self.assertTrue(self.window.send_button.isEnabled())

    def test_untrusted_answer_is_rendered_as_text_not_html(self):
        self.provider.answer = '<img src="file:///private.png"> <script>alert(1)</script>'
        self.send()
        self.assertIn('<img src=', self.window.chat.toPlainText())
        self.assertIn('<script>', self.window.chat.toPlainText())


if __name__ == '__main__':
    unittest.main()
