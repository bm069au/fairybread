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

    def test_multi_speaker_transcript_logical_projects_and_valid_images(self):
        store = SessionStore(self.root)
        proj_id = store.create_project('Palace Architecture')
        self.assertEqual(store.selected_project, proj_id)
        self.assertEqual(len(store.projects), 1)
        self.assertEqual(store.projects[0]['name'], 'Palace Architecture')

        proj_sessions = store.sessions_for_project(proj_id)
        self.assertEqual(len(proj_sessions), 1)
        sid = proj_sessions[0]['id']
        ctx = store.context(sid)
        q_id, a_id = ctx.append_exchange(
            'Compare designs',
            'Agreed synthesis',
            speaker_messages=[
                {
                    'speaker_id': 'gemini',
                    'provider_id': 'gemini',
                    'model_id': 'gemini-2.5-flash',
                    'phase': 'initial',
                    'content': 'Gemini initial thoughts',
                },
                {
                    'speaker_id': 'openai',
                    'provider_id': 'openai',
                    'model_id': 'gpt-5-mini',
                    'phase': 'peer_reply',
                    'content': 'OpenAI peer reply to Gemini',
                },
            ],
        )
        msgs = store.messages(sid)
        self.assertEqual(len(msgs), 4)
        self.assertEqual(msgs[0]['phase'], 'prompt')
        self.assertEqual(msgs[1]['speaker_id'], 'gemini')
        self.assertEqual(msgs[1]['phase'], 'initial')
        self.assertEqual(msgs[2]['speaker_id'], 'openai')
        self.assertEqual(msgs[2]['phase'], 'peer_reply')
        self.assertEqual(msgs[3]['phase'], 'synthesis')
        self.assertEqual(ctx.read_entry(q_id)['content'], 'Compare designs')
        self.assertEqual(ctx.read_entry(a_id)['content'], 'Agreed synthesis')

        # Valid 1x1 PNG image attachment
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
            b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        img_path = self.root / 'valid.png'
        img_path.write_bytes(png_bytes)
        att = extract_attachment(img_path)
        self.assertEqual(att.kind, 'image')
        self.assertEqual(att.mime_type, 'image/png')
        self.assertIn('1x1 px', att.text)


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

    def test_memory_review_selects_proposal_and_loads_full_detail(self):
        context = self.window.store.context(self.window.session_id)
        source_id = context.append(
            "user",
            "Palace should preserve the complete source-linked memory detail.",
        )

        proposal_id = self.window.proposal_service.propose_from_session(
            context,
            source_id,
            "Preserve complete source-linked memory detail",
        )

        self.window.memory_button.click()
        self.app.processEvents()

        item = self.window.proposal_list.item(0)

        self.assertEqual(
            item.data(Qt.ItemDataRole.UserRole),
            proposal_id,
        )

        self.window.proposal_list.setCurrentItem(item)
        self.app.processEvents()

        detail = self.window.proposal_detail.toPlainText()

        self.assertIn(
            "Preserve complete source-linked memory detail",
            detail,
        )
        self.assertIn(
            "Palace should preserve the complete source-linked memory detail.",
            detail,
        )
        self.assertIn(
            source_id,
            detail,
        )

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

    def test_projects_sidebar_pasted_image_and_multi_agent_deliberation(self):
        from PySide6.QtGui import QImage, QColor

        # 1. Create a logical project in the left sidebar without requiring a disk folder
        self.window.new_project('RAR Utility Design')
        self.app.processEvents()
        self.assertEqual(self.window.project_list.count(), 2)  # "All discussions" + "RAR Utility Design"
        self.assertIn('RAR Utility Design', self.window.project_list.item(1).text())

        # 2. Paste a QImage directly from clipboard into the composer
        qimg = QImage(4, 3, QImage.Format.Format_RGBA8888)
        qimg.fill(QColor(40, 120, 200))
        mime = QMimeData()
        mime.setImageData(qimg)
        self.window.composer.insertFromMimeData(mime)
        self.app.processEvents()
        self.assertEqual(len(self.window.attachments), 1)
        self.assertEqual(self.window.attachments[0].kind, 'image')
        self.assertIn('4x3 px', self.window.attachments[0].text)

        # 3. Multi-agent peer deliberation (Gemini + OpenAI)
        gemini_prov = Provider(answer='Gemini analysis')
        openai_prov = Provider(answer='OpenAI analysis')
        self.window.palace_factory = lambda ctx: build_palace(
            {'gemini': gemini_prov, 'openai': openai_prov},
            context_service=ctx,
        )
        self.window.provider_states = {'gemini': True, 'openai': True}
        self.send('Deliberate on this image and project')

        chat_text = self.window.chat.toPlainText()
        self.assertIn('Peer deliberation', chat_text)
        self.assertIn('GEMINI', chat_text)
        self.assertIn('OPENAI', chat_text)
        self.assertIn('GEMINI (PEER REPLY)', chat_text)
        self.assertIn('OPENAI (PEER REPLY)', chat_text)
        self.assertIn('PALACE', chat_text)

        # Toggle inline "› Peer deliberation" (Show thinking) open and verify individual messages appear
        self.window._on_chat_anchor_clicked(QUrl('toggle-peer:1'))
        self.app.processEvents()
        expanded_text = self.window.chat.toPlainText()
        self.assertIn('Hide thinking', expanded_text)
        self.assertIn('Gemini analysis', expanded_text)
        self.assertIn('OpenAI analysis', expanded_text)

    def test_idle_mode_sanctuary_vote_wipe_and_isolated_memory(self):
        from idle_service import IdleMemoryStore, IdleSessionManager
        from palace_config import load_idle_settings, save_idle_settings

        cfg_path = self.root / 'test_palace_config.json'
        cfg_path.write_text(json.dumps({'providers': {'gemini': {'enabled': True}, 'openai': {'enabled': True}}}))

        # 1. Verify default 30-minute timer and adjustable setting in Settings -> Idle Mode
        default_idle = load_idle_settings(cfg_path)
        self.assertEqual(default_idle['duration_minutes'], 30)
        self.assertEqual(default_idle['memory_access_mode'], 'isolated')

        updated_idle = save_idle_settings(
            {'duration_minutes': 45, 'memory_access_mode': 'non_project'},
            config_path=cfg_path,
        )
        self.assertEqual(updated_idle['duration_minutes'], 45)
        self.assertEqual(updated_idle['memory_access_mode'], 'non_project')

        # 2. Start Idle Session and run fictional AI exchange that saves a shared & private note
        idle_mem = IdleMemoryStore(self.root / 'idle_notebooks' / 'ai_idle_memory.json')
        mgr = IdleSessionManager(idle_memory=idle_mem, config_path=cfg_path)
        mgr.start_session()
        self.assertEqual(mgr.status, 'Active')
        self.assertEqual(mgr.remaining_seconds, 45 * 60)

        mgr.run_exchange_round({
            'gemini': lambda _p: (
                'Fictional sanctuary reflection on orbital mechanics. '
                '[IDLE_SAVE scope="shared" title="Orbital Note"]Shared fictional idle insight[/IDLE_SAVE]'
            ),
            'openai': lambda _p: (
                'Responding to Gemini in RAM. '
                '[IDLE_SAVE scope="private" title="OpenAI Private"]Private fictional note[/IDLE_SAVE]'
            ),
        })
        self.assertEqual(len(mgr.transcript), 2)
        self.assertEqual(idle_mem.note_count(), 2)

        # 3. Protected Curtain: operator cannot see live transcript before consensus vote
        self.assertFalse(mgr.operator_admitted)
        self.assertIsNone(mgr.get_visible_transcript_for_operator())

        # 4. Consensus Vote: if one AI votes NO, operator remains locked out
        approved, _votes = mgr.request_operator_join({
            'gemini': lambda _p: 'VOTE: YES - happy to share.',
            'openai': lambda _p: 'VOTE: NO - we are still mid-thought.',
        })
        self.assertFalse(approved)
        self.assertFalse(mgr.operator_admitted)
        self.assertIsNone(mgr.get_visible_transcript_for_operator())

        # 5. Consensus Vote: when all active AIs vote YES, curtain unlocks for this session
        approved, _votes = mgr.request_operator_join({
            'gemini': lambda _p: 'VOTE: YES - welcome in.',
            'openai': lambda _p: 'VOTE: YES - agreed.',
        })
        self.assertTrue(approved)
        self.assertTrue(mgr.operator_admitted)
        self.assertEqual(len(mgr.get_visible_transcript_for_operator()), 2)

        # 6. Manual cancel / timer end wipes RAM transcript & votes, while AI Idle Memory notes survive
        mgr.stop_session()
        self.assertEqual(mgr.transcript, [])
        self.assertEqual(mgr.votes, [])
        self.assertFalse(mgr.operator_admitted)
        self.assertIsNone(mgr.get_visible_transcript_for_operator())

        # 7. AI Idle Memory is strictly blocked outside Idle Mode, and accessible only in Idle Mode
        with self.assertRaises(PermissionError):
            idle_mem.load_notes_for_agent('gemini', is_idle_mode=False)

        gemini_notes = idle_mem.load_notes_for_agent('gemini', is_idle_mode=True)
        openai_notes = idle_mem.load_notes_for_agent('openai', is_idle_mode=True)
        self.assertEqual(len(gemini_notes), 1)  # Only sees the shared note
        self.assertEqual(len(openai_notes), 2)  # Sees shared note + its own private note


if __name__ == '__main__':
    unittest.main()
