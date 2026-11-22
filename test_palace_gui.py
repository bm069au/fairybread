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
from memory_service import MemoryService
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
            palace.memory_service = MemoryService(db_path=self.root / "memory.db")
            palace.memory_service.search = lambda _: self.fail(
                "Unexpected permanent-memory read"
            )
            return palace

        proposal_service = MemoryProposalService(
            self.root / "memory-proposals.jsonl"
        )
        win = PalaceWindow(
            SessionStore(self.root),
            factory,
            {"test": True, "off": False},
            proposal_service=proposal_service,
            config_path=self.root / "palace_config.json",
        )
        win._memory_db_path = lambda: self.root / "memory.db"
        return win

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
        self.assertIsNotNone(self.window.worker)
        self.assertFalse(self.window.stop_button.isHidden())
        self.assertTrue(self.window.send_button.isEnabled())
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
        def _isolated_multi_palace(ctx):
            palace = build_palace(
                {'gemini': gemini_prov, 'openai': openai_prov},
                context_service=ctx,
            )
            palace.memory_service = MemoryService(db_path=self.root / "memory.db")
            return palace

        self.window.palace_factory = _isolated_multi_palace
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

        # 7. AI Idle Memory is strictly blocked outside Idle Mode, and shared across all Idle agents
        with self.assertRaises(PermissionError):
            idle_mem.load_notes_for_agent('gemini', is_idle_mode=False)

        gemini_notes = idle_mem.load_notes_for_agent('gemini', is_idle_mode=True)
        openai_notes = idle_mem.load_notes_for_agent('openai', is_idle_mode=True)
        self.assertEqual(len(gemini_notes), 2)  # Unified Shared Idle Palace: all Idle agents see all notes
        self.assertEqual(len(openai_notes), 2)

    def test_idle_switch_pauses_normal_mode_and_agent_mail_links_to_shared_idle_palace(self):
        from idle_service import IdleMailboxStore, IdleMemoryStore, IdleSessionManager

        idle_mem = IdleMemoryStore(self.root / 'idle_palace' / 'ai_idle_memory.json')
        mailbox = IdleMailboxStore(self.root / 'mailbox' / 'agent_mailbox.json')
        self.window.idle_memory = idle_mem
        self.window.idle_manager = IdleSessionManager(
            idle_memory=idle_mem,
            mailbox=mailbox,
            config_path=self.window.config_path,
        )

        # 1. Engage the front-interface Idle Mode switch -> Normal AI mode is paused & switches to Idle tab
        self.window.idle_switch_btn.setChecked(True)
        self.app.processEvents()
        self.wait_idle()
        self.assertEqual(self.window.workspace_tabs.currentIndex(), 1)
        self.assertFalse(self.window.composer.isEnabled())
        self.assertFalse(self.window.send_button.isEnabled())
        self.assertFalse(self.window.normal_pause_banner.isHidden())

        # 2. Agent saves a file in the Shared Idle Palace and sends an Email linking to that file
        self.window.idle_manager.run_exchange_round({
            'deepseek': lambda _p: (
                'Testing the Shared Idle Palace and proposing a cache helper. '
                '[IDLE_SAVE title="Cache Helper Proposal" file="cache_helper.py"]def fast_cache(): return True[/IDLE_SAVE] '
                '[IDLE_MAIL subject="Cache improvement idea" link="cache_helper.py"]'
                'Hi Brett, I saved cache_helper.py in our Shared Idle Palace for you to review.'
                '[/IDLE_MAIL]'
            ),
        })
        self.window._refresh_idle_view()
        self.app.processEvents()

        # Verify file exists in the Shared Idle Palace and email appears in Agent Mail
        self.assertEqual(idle_mem.note_count(), 1)
        self.assertEqual(len(mailbox.list_messages()), 1)
        msg = mailbox.list_messages()[0]
        self.assertEqual(msg['link'], 'cache_helper.py')

        # 3. Clicking the linked file in Agent Mail opens it in the Shared Idle Palace browser
        opened = self.window.open_idle_palace_file_by_ref('cache_helper.py')
        self.assertTrue(opened)
        self.assertIn('def fast_cache(): return True', self.window.idle_palace_viewer.toPlainText())

        # 4. Verify 5-emails-per-30-minutes rate limit blocks the 6th email
        for i in range(4):
            ok, _ = mailbox.send_agent_email('gemini', f'Idea {i+2}', f'Body {i+2}')
            self.assertTrue(ok)
        self.assertEqual(mailbox.remaining_quota(), 0)
        ok_sixth, err_msg = mailbox.send_agent_email('openai', 'Idea 6 (Over Limit)', 'Should be rate-limited')
        self.assertFalse(ok_sixth)
        self.assertIn('Rate limit reached', str(err_msg))

        # 5. Disengage the front-interface Idle Mode switch -> Normal AI mode is unpaused
        self.window.idle_switch_btn.setChecked(False)
        self.app.processEvents()
        self.assertEqual(self.window.workspace_tabs.currentIndex(), 0)
        self.assertTrue(self.window.composer.isEnabled())
        self.assertTrue(self.window.send_button.isEnabled())

    def test_idle_mode_agreement_loop_autostop_and_budget_caps(self):
        from idle_service import IdleMemoryStore, IdleSessionManager
        from palace_config import save_idle_settings

        cfg_path = self.root / 'test_loop_config.json'
        save_idle_settings(
            {
                'duration_minutes': 0,  # Infinite timer (bounded by token/credit caps)
                'max_tokens_limit': 10_000,
                'max_credit_usd': 0.05,
            },
            config_path=cfg_path,
        )
        idle_mem = IdleMemoryStore(self.root / 'idle_notebooks' / 'loop_mem.json')
        mgr = IdleSessionManager(idle_memory=idle_mem, config_path=cfg_path)
        mgr.start_session()
        self.assertEqual(mgr.format_remaining_time(), '∞ Infinite')
        self.assertFalse(mgr.tick(3600))  # Infinite timer does not expire on its own

        # Round 1: Both agents fall into agreement/PASS -> Strike 1
        mgr.run_exchange_round({
            'gemini': lambda _p: 'I completely agree with the previous framing.',
            'openai': lambda _p: '[PASS]',
        })
        self.assertEqual(mgr.consecutive_agreement_rounds, 1)
        self.assertEqual(mgr.status, 'Active')
        self.assertEqual(len(mgr.transcript), 1)  # [PASS] was not added to bloat RAM transcript

        # Round 2: Second consecutive agreement/PASS round -> Strike 2 Auto-Stop!
        mgr.run_exchange_round({
            'gemini': lambda _p: '[PASS]',
            'openai': lambda _p: '[PASS]',
        })
        self.assertEqual(mgr.status, 'Auto-Stopped (Consensus)')
        self.assertIn('auto-stopped', mgr.stop_reason.lower())

    def test_enter_to_send_and_shift_enter_newline_modes(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        # Default: Enter sends message, Shift+Enter inserts newline
        self.assertTrue(self.window.composer.enter_to_send)
        self.window.composer.setPlainText('Line 1')
        shift_enter = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ShiftModifier,
            '\n',
        )
        self.window.composer.keyPressEvent(shift_enter)
        self.assertIn('\n', self.window.composer.toPlainText())

        # Plain Enter triggers send_requested
        self.window.composer.setPlainText('Submitted with Enter')
        plain_enter = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier,
            '\r',
        )
        self.window.composer.keyPressEvent(plain_enter)
        self.wait_idle()
        self.assertIn('Submitted with Enter', self.window.chat.toPlainText())

        # Reverse mode: Shift+Enter sends, plain Enter inserts newline
        self.window.composer.enter_to_send = False
        self.window.composer.setPlainText('Reversed line 1')
        self.window.composer.keyPressEvent(plain_enter)
        self.assertIn('\n', self.window.composer.toPlainText())

    def test_squad_presets_tangent_vs_no_history_and_project_folder_attachment(self):
        # 1. Project created without folder, then folder attached afterward
        self.window.new_project('Absurdityverse & Code')
        proj_id = self.window.store.selected_project
        self.assertIsNotNone(proj_id)
        self.assertEqual(self.window.store.get_project_folder(proj_id), '')

        sample_dir = self.root / 'attached_workspace'
        sample_dir.mkdir(parents=True, exist_ok=True)
        (sample_dir / 'absurdity_notes.py').write_text('# Absurdityverse helper\n', encoding='utf-8')
        self.window.attach_folder_to_current_project(project_id=proj_id, folder_path=str(sample_dir))
        self.assertEqual(self.window.store.get_project_folder(proj_id), str(sample_dir.resolve()))

        # M: drive is strictly rejected
        with self.assertRaises((PermissionError, ValueError)):
            self.window.store.set_project_folder(proj_id, r'M:\SHARE_POINTS\Forbidden')

        # 2. Apply Light Chat squad preset -> turns Peer Deliberation OFF & selects groq
        self.window._apply_squad_preset('💬 Light Chat (Cheap)', ['groq'], deliberate=False, palace_code=False)
        self.assertFalse(self.window.peer_rounds_toggle.isChecked())
        self.assertFalse(self.window.deliberate_pill_btn.isChecked())
        self.assertTrue(self.window.provider_states.get('groq'))
        self.assertFalse(self.window.provider_states.get('gemini'))

        # Re-enable 'test' provider for our fake palace test
        self.window._apply_squad_preset('💻 Code AIs', ['test'], deliberate=True, palace_code=False)
        self.assertTrue(self.window.peer_rounds_toggle.isChecked())

        # First send a normal coding message so there is prior context in the session
        self.send('Prior code discussion about C++ pointers')
        self.assertEqual(len(self.window.store.messages(self.window.session_id)), 2)

        # 3. Tangent Mode: skips pulling prior context into prompt (include_context=False),
        #    while STILL saving the tangent exchange to the Palace!
        self.window.tangent_btn.setChecked(True)
        self.window.composer.setPlainText('Absurdityverse tangent idea')
        self.window.send_message()
        self.wait_idle()
        self.assertNotIn('Prior code discussion about C++ pointers', self.provider.prompts[-1])
        self.assertIn('Absurdityverse tangent idea', self.provider.prompts[-1])
        self.assertIn('Tangent saved to Palace', self.window.status_label.text())
        self.assertEqual(len(self.window.store.messages(self.window.session_id)), 4)

        # 4. Prominent No-History Mode: shows crimson warning banner and does NOT save to Palace
        self.window.tangent_btn.setChecked(False)
        self.window.no_history_btn.setChecked(True)
        self.assertFalse(self.window.no_history_banner.isHidden())
        self.assertFalse(self.window.history_toggle.isChecked())
        self.window.composer.setPlainText('Ephemeral no-history question')
        self.window.send_message()
        self.wait_idle()
        self.assertIn('Not saved (No-History)', self.window.status_label.text())
        self.assertEqual(len(self.window.store.messages(self.window.session_id)), 4)  # Still 4! Not saved!
        self.window.no_history_btn.setChecked(False)
        self.assertTrue(self.window.no_history_banner.isHidden())

    def test_idle_provider_callables_reads_real_provider_registry_and_sandbox_tools(self):
        from bootstrap import build_palace
        from idle_service import execute_sandbox_tool
        from providers import ProviderResponse

        class DummyProvider:
            def generate(self, prompt: str) -> ProviderResponse:
                return ProviderResponse(text=f'Echo: {prompt[:20]}', provider='gemini')

        # Real PalaceOrchestrator uses ProviderDispatcher(ProviderRegistry()), which stores providers in .registry.all()
        real_palace = build_palace({'gemini': DummyProvider(), 'deepseek': DummyProvider()})
        real_palace.memory_service = MemoryService(db_path=self.root / "memory.db")
        self.window.palace_factory = lambda _ctx: real_palace
        self.window.provider_states = {'gemini': True, 'deepseek': True}

        callables = self.window._get_idle_provider_callables()
        self.assertIn('gemini', callables)
        self.assertIn('deepseek', callables)
        self.assertTrue(callables['gemini']('Hello Idle').startswith('Echo:'))

        # Test Stage 1 Idle Sandbox Tools (read_rules, list_source_files, search_source_code)
        rules_out = execute_sandbox_tool('read_rules')
        self.assertIn('CHARTER & OPERATING RULES', rules_out)
        files_out = execute_sandbox_tool('list_source_files')
        self.assertIn('palace_gui.py', files_out)

    def test_ai_svg_drawing_tool_renders_real_png_and_scroll_preserved_on_pulse(self):
        from palace_theme import render_svg_to_png, format_markdown_and_drawings

        svg_code = (
            '<svg width="320" height="140" viewBox="0 0 320 140" xmlns="http://www.w3.org/2000/svg">'
            '<rect width="320" height="140" rx="10" fill="#161b22" stroke="#3b82f6" stroke-width="2"/>'
            '<text x="24" y="75" fill="#e6edf3" font-size="16">Palace Self-Reboot Diagram</text>'
            '</svg>'
        )
        png_path = render_svg_to_png(svg_code, title='Self-Reboot Architecture')
        self.assertIsNotNone(png_path)
        self.assertTrue(png_path.exists())
        self.assertGreater(png_path.stat().st_size, 100)

        reply_with_drawing = f'Here is the visual architecture:\n```svg\n{svg_code}\n```\nDone.'
        rendered_html = format_markdown_and_drawings(reply_with_drawing)
        self.assertIn('<img src="file:///', rendered_html)
        self.assertIn('open-img:', rendered_html)

        # Verify pulse tick updates inline_status_label without overwriting or scrolling chat
        self.window.pending_status_text = 'Consulting Gemini'
        self.window._on_pulse_tick()
        self.assertFalse(self.window.inline_status_label.isHidden())
        self.assertIn('Consulting Gemini', self.window.inline_status_label.text())

    def test_palace_ui_self_snapshot_and_ouroboros_staging_engine(self):
        from palace_ouroboros import (
            EDITABLE_PALACE_FILES,
            capture_palace_window_snapshot,
            read_pending_handoff,
            stage_palace_replace,
            validate_staged_palace,
            write_reboot_handoff,
        )
        from palace_theme import format_markdown_and_drawings

        # 1. Capture PalaceWindow widget snapshot & geometry audit (strictly scoped to PalaceWindow)
        snap_path, audit = capture_palace_window_snapshot(self.window, tag='unit_test_ui_snap')
        self.assertIsNotNone(snap_path)
        self.assertTrue(snap_path.exists())
        self.assertEqual(audit['scope'], 'PalaceWindow (Isolated Qt Widget Hierarchy Only)')
        self.assertEqual(audit['clipped_widget_count'], 0)

        # 2. Verify [PALACE_UI_SNAPSHOT] tag embeds the real PalaceWindow PNG in chat HTML
        snap_html = format_markdown_and_drawings(
            f'Inspecting UI:\n[PALACE_UI_SNAPSHOT path="{snap_path}" title="Unit Test Palace UI Audit"]'
        )
        self.assertIn('<img src="file:///', snap_html)
        self.assertIn('Clipped: 0', snap_html)

        # 3. Verify strict L1 Allowlist blocks editing watchdog or credential store
        ok_blocked, msg_blocked = stage_palace_replace('palace_watchdog.py', 'a', 'b')
        self.assertFalse(ok_blocked)
        self.assertIn('Denied', msg_blocked)
        self.assertNotIn('palace_watchdog.py', EDITABLE_PALACE_FILES)
        self.assertNotIn('credential_store.py', EDITABLE_PALACE_FILES)

        # 4. Verify atomic reboot_handoff.json write & read roundtrip (isolated to temp test dir)
        with patch('palace_ouroboros.HANDOFF_PATH', self.root / 'reboot_handoff.json'):
            ok_h, _msg_h, payload = write_reboot_handoff(
                reason='unit_test',
                applied_diff_summary='Verified micro-indicators and UI snapshot tool',
                test_results={'py_compile': 'pass', 'unittest_passed': True},
                session_id='legacy',
                resumption_prompt='Continue self-improvement test',
            )
            self.assertTrue(ok_h)
            consumed = read_pending_handoff(consume=True)
            self.assertIsNotNone(consumed)
            self.assertEqual(consumed['handoff_id'], payload['handoff_id'])
            self.assertIsNone(read_pending_handoff(consume=True))  # Consumed once only!

    def test_idle_mode_agent_visibility_and_streaming(self):
        # Switch into Idle Mode (Tab 1) and verify enabled agents remain visible both in the bottom bar and Idle banner
        self.window.workspace_tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertTrue(
            self.window.provider_labels['test'].isVisible(),
            'Enabled agent chip button should remain visible in Idle Mode tab',
        )
        self.assertIn('Active Experimental Council', self.window.idle_agents_roster_label.text())

        # Start Idle session and verify live turn streaming updates idle_live_chat
        self.window.start_idle_session()
        self.wait_idle()
        self.assertGreaterEqual(len(self.window.idle_manager.transcript), 1)
        self.assertIn('A useful answer', self.window.idle_live_chat.toHtml())

    def test_antigravity_sidebar_new_conversation_and_instant_rename(self):
        # Create a project and verify unified session_list shows project header + new conversation underneath
        self.window.new_project('Palace Workshop')
        self.app.processEvents()
        texts = [self.window.session_list.item(i).text() for i in range(self.window.session_list.count())]
        self.assertTrue(any('Palace Workshop' in t for t in texts))
        self.assertTrue(any('New conversation' in t for t in texts))

        # Send a message with provider delay and verify the sidebar renames IMMEDIATELY before worker finishes
        self.provider.delay = 0.2
        self.window.composer.setPlainText('Instant sidebar title check')
        self.window.send_message()
        immediate_texts = [self.window.session_list.item(i).text() for i in range(self.window.session_list.count())]
        self.assertTrue(any('Instant sidebar title' in t for t in immediate_texts))
        self.wait_idle()

    def test_idle_submodes_free_talk_vs_self_improvement(self):
        # Default sub-mode is Free Talk (unprompted lounge without forced source code tools)
        self.assertEqual(self.window.idle_submode_combo.currentData(), 'free_talk')
        free_prompt = self.window.idle_manager.build_idle_turn_prompt('gemini')
        self.assertIn('FREE TALK LOUNGE', free_prompt)
        self.assertNotIn('list_source_files', free_prompt)

        # Switch to Self-Improvement sub-mode -> enables Palace source code tools & grounding rule
        idx_self = self.window.idle_submode_combo.findData('self_improve')
        self.window.idle_submode_combo.setCurrentIndex(idx_self)
        self.app.processEvents()
        improve_prompt = self.window.idle_manager.build_idle_turn_prompt('gemini')
        self.assertIn('SELF-IMPROVEMENT WORKSHOP', improve_prompt)
        self.assertIn('list_source_files', improve_prompt)

    def test_dpapi_auto_save_themes_and_rounded_bubbles(self):
        from credential_store import CredentialStore, dpapi_decrypt, dpapi_encrypt, redact_secrets
        from palace_config import PROVIDER_CATALOG
        from palace_ouroboros import stage_palace_replace

        # 1. Verify Windows DPAPI encrypts secrets on disk with 'dpapi:' prefix and roundtrips cleanly
        enc = dpapi_encrypt('sk-test-secret-key-99999')
        self.assertTrue(enc.startswith('dpapi:'))
        self.assertNotIn('sk-test-secret-key-99999', enc)
        self.assertEqual(dpapi_decrypt(enc), 'sk-test-secret-key-99999')

        cred_file = self.root / 'test_creds.json'
        cstore = CredentialStore(cred_file)
        cstore.set_api_key('deepinfra', 'sk-di-unit-test-secret-12345')
        raw_disk = cred_file.read_text(encoding='utf-8')
        self.assertIn('dpapi:', raw_disk)
        self.assertNotIn('sk-di-unit-test-secret-12345', raw_disk)
        self.assertEqual(cstore.get_api_key('deepinfra'), 'sk-di-unit-test-secret-12345')
        self.assertIn('[REDACTED_API_KEY]', redact_secrets('Leak check: sk-di-unit-test-secret-12345'))

        # 2. Verify Ouroboros AST/token security gate blocks staged code attempting to call dpapi_decrypt
        ok, sec_msg = stage_palace_replace(
            'palace_theme.py',
            'def provider_color(',
            'from credential_store import dpapi_decrypt\ndef provider_color(',
        )
        self.assertFalse(ok)
        self.assertIn('Security Gate Denied', sec_msg)

        # 3. Verify 15-provider catalog and Fairybread theme switching + rounded user bubbles
        self.assertGreaterEqual(len(PROVIDER_CATALOG), 15)
        self.assertIn('deepinfra', PROVIDER_CATALOG)
        self.assertIn('anthropic', PROVIDER_CATALOG)
        self.assertIn('xai', PROVIDER_CATALOG)

        from palace_theme import BUILTIN_THEMES, list_available_themes, load_theme_dict
        self.assertNotIn('fairybread', BUILTIN_THEMES)
        self.assertNotIn('fairybread', {k for k, _ in list_available_themes()})
        self.assertEqual(load_theme_dict('fairybread')['id'], 'dark')

        self.window.apply_theme('dracula_pro')
        self.assertEqual(self.window.active_theme, 'dracula_pro')
        self.assertFalse(self.window.chat.sprinkles_enabled)
        self.assertFalse(self.window.windowIcon().isNull())

        # 4. Verify KDE/XFCE-style pixel-width responsive bottom Agents: bar
        self.window._apply_squad_preset(
            'Full Roster',
            ['gemini', 'openai', 'anthropic', 'xai', 'deepseek', 'qwen', 'cohere', 'mistral', 'openrouter', 'deepinfra', 'groq', 'cerebras'],
            deliberate=True,
        )
        self.window.agent_workbench_frame.resize(520, 28)
        self.window._relayout_agent_bar()
        self.assertEqual(self.window.agent_workbench_frame.height(), 48)
        self.assertIsNotNone(self.window.right_status_grid.itemAtPosition(1, 0))
        self.window.agent_workbench_frame.resize(1600, 28)
        self.window._relayout_agent_bar()
        self.assertEqual(self.window.agent_workbench_frame.height(), 28)
        self.assertIsNotNone(self.window.right_status_grid.itemAtPosition(0, 1))

    def test_fault_tolerant_deliberation_round1_preservation_and_synthesizer_failover(self):
        class RoundAwareProvider:
            def __init__(self, name, r1_text, r2_text, fail_r1=False, fail_synth=False):
                self.name = name
                self.r1_text = r1_text
                self.r2_text = r2_text
                self.fail_r1 = fail_r1
                self.fail_synth = fail_synth
                self.calls = 0
                self.synth_prompts = []

            def generate(self, prompt):
                self.calls += 1
                if 'Create one strong final answer for the user.' in prompt:
                    self.synth_prompts.append(prompt)
                    if self.fail_synth:
                        raise RuntimeError('Primary synthesizer timed out')
                    return ProviderResponse(text='Synthesized council consensus', provider=self.name)
                if self.calls == 1:
                    if self.fail_r1:
                        raise RuntimeError('Provider rate limited in Round 1')
                    return ProviderResponse(text=self.r1_text, provider=self.name)
                return ProviderResponse(text=self.r2_text, provider=self.name)

        p_gem = RoundAwareProvider('gemini', 'Gemini R1 code block', 'Gemini R2 edge-case fix', fail_synth=True)
        p_oai = RoundAwareProvider('openai', 'OpenAI R1 architecture', 'OpenAI R2 refinement')
        p_bad = RoundAwareProvider('cohere', 'Cohere R1', 'Cohere R2', fail_r1=True)

        palace = build_palace({'gemini': p_gem, 'openai': p_oai, 'cohere': p_bad})
        palace.memory_service = MemoryService(db_path=self.root / "memory.db")
        res = palace.run('Design fault-tolerant council', max_rounds=2)

        # 1. Even though Cohere failed in Round 1, Gemini + OpenAI still deliberated in Round 2
        self.assertEqual(len(res.peer_rounds), 1)
        # 2. Primary synthesizer (gemini) failed on synthesis call, so OpenAI automatically took over synthesis
        self.assertTrue(res.synthesis.succeeded)
        self.assertEqual(res.synthesis.provider_name, 'openai')
        self.assertEqual(res.final_answer, 'Synthesized council consensus')
        # 3. Both Round 1 proposal and Round 2 peer review were preserved for the synthesizer
        synth_input = p_oai.synth_prompts[-1]
        self.assertIn('Gemini R1 code block', synth_input)
        self.assertIn('Gemini R2 edge-case fix', synth_input)
        self.assertIn('OpenAI R1 architecture', synth_input)
        self.assertIn('OpenAI R2 refinement', synth_input)

        # 4. Verify Image Size Presets (YouTube Banner, Facebook Group/Page, 300 DPI Print) & Backtick Safety
        from palace_theme import (
            _fit_and_save_target_png,
            format_markdown_and_drawings,
            resolve_target_image_size,
        )
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QColor, QImage

        self.assertEqual(resolve_target_image_size('youtube_banner')[:2], (2560, 1440))
        self.assertEqual(resolve_target_image_size('facebook_group')[:2], (1640, 856))
        self.assertEqual(resolve_target_image_size('facebook_cover')[:2], (1920, 1080))
        self.assertEqual(resolve_target_image_size('8x10in')[:2], (2400, 3000))
        self.assertEqual(resolve_target_image_size('', 'Create a hyperrealistic YouTube banner of fairy bread')[:2], (2560, 1440))

        src_img = QImage(64, 64, QImage.Format.Format_RGBA8888)
        src_img.fill(QColor('#ff5ca8'))
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        src_img.save(buf, 'PNG')
        out_png = self.root / 'fb_group_test.png'
        self.assertTrue(_fit_and_save_target_png(bytes(buf.data()), out_png, 1640, 856))
        loaded_img = QImage(str(out_png))
        self.assertEqual((loaded_img.width(), loaded_img.height()), (1640, 856))
        self.assertAlmostEqual(loaded_img.dotsPerMeterX(), 11811, delta=5)

        # Backticked [GENERATE_IMAGE] example must NOT be parsed as a real image request
        doc_html = format_markdown_and_drawings('Use `[GENERATE_IMAGE prompt="example" title="demo"]` to draw.')
        self.assertNotIn('[Image Request', doc_html)
        self.assertIn('[GENERATE_IMAGE', doc_html)

        # 5. Verify 2-Mode Drawing Routing (Direct 1-Pass vs Council-Assisted Prompt Brainstorm)
        from orchestrator import classify_drawing_request

        self.assertEqual(
            classify_drawing_request('Draw me a brown dog on a black carpet in front of a fireplace'),
            'direct_draw',
        )
        self.assertEqual(
            classify_drawing_request('All agents work on the prompt and then only one of you execute the drawing: draw a ginger tabby'),
            'council_draw',
        )
        self.assertEqual(
            classify_drawing_request('Write a Python function to sort a list'),
            'none',
        )

        d_ds = RoundAwareProvider('deepseek', 'Expanded prompt ready (`[GENERATE_IMAGE prompt="Rich brown dog" title="Dog"]`)', '[PASS]')
        d_oai = RoundAwareProvider('openai', '[GENERATE_IMAGE prompt="" title="Dog2" size="1024x1024" quality="high"]', '[PASS]')
        d_coh = RoundAwareProvider('cohere', 'Cohere dog note', '[PASS]')
        draw_palace = build_palace({'deepseek': d_ds, 'openai': d_oai, 'cohere': d_coh})
        draw_palace.memory_service = MemoryService(db_path=self.root / "memory.db")

        # Direct draw: 2-provider Graphic Prompt Duo (openai + deepseek when gemini is absent), 1 pass, skipping cohere
        direct_res = draw_palace.run('Draw me a brown dog on a black carpet in front of a fireplace', max_rounds=2)
        self.assertEqual(set(direct_res.provider_results.keys()), {'openai', 'deepseek'})
        self.assertEqual(d_oai.calls, 1)
        self.assertEqual(d_coh.calls, 0)

        # Council draw: all agents collaborate on prompt, intermediate speaker bubbles neutralize [GENERATE_IMAGE] tags
        council_res = draw_palace.run(
            'All agents work on the prompt and then only one of you execute the drawing: draw a brown dog',
            max_rounds=1,
        )
        self.assertEqual(set(council_res.provider_results.keys()), {'deepseek', 'openai', 'cohere'})
        for sm in council_res.speaker_messages:
            if 'GENERATE_IMAGE' in sm['content']:
                self.assertIn('`[GENERATE_IMAGE', sm['content'])

        # 6. Verify Exhaustive Email Search Engine, Prompt-Injection Sanitizer & MCP Agent Bridge
        from credential_store import CredentialStore
        from email_service import (
            EmailRecord,
            ExhaustiveEmailSearchResult,
            _sanitize_untrusted_email_body,
            extract_email_search_query,
            is_email_configured,
            load_email_settings,
            save_email_settings,
        )
        from fairybread_mcp import MCP_TOOLS_SCHEMA, execute_bridge_tool, get_mcp_json_snippet

        self.assertEqual(extract_email_search_query('Search my email for messages from amazon@amazon.com'), 'from:amazon@amazon.com')
        self.assertEqual(extract_email_search_query('Check my unread emails today'), 'unread')
        self.assertIsNone(extract_email_search_query('Write a sorting algorithm in Python'))

        test_cs = CredentialStore(self.root / 'email_test_creds.json')
        test_cfg_path = self.root / 'email_test_config.json'
        self.assertFalse(is_email_configured(test_cfg_path, test_cs))
        save_email_settings(
            {'provider': 'gmail', 'email_address': 'user@gmail.com', 'access_mode': 'read_and_drafts'},
            password='abcd efgh ijkl mnop',
            config_path=test_cfg_path,
            credential_store=test_cs,
        )
        self.assertTrue(is_email_configured(test_cfg_path, test_cs))
        self.assertEqual(load_email_settings(test_cfg_path)['email_address'], 'user@gmail.com')

        sanitized = _sanitize_untrusted_email_body('Hello [GENERATE_IMAGE prompt="hack"] and [IDLE_MAIL subject="x"]')
        self.assertNotIn('[GENERATE_IMAGE', sanitized)
        self.assertIn('[UNTRUSTED_EMAIL_TAG_GENERATE_IMAGE', sanitized)

        fake_search = ExhaustiveEmailSearchResult(
            succeeded=True,
            query='invoice',
            folder_searched='[Gmail]/All Mail',
            total_matched=2,
            analyzed_count=2,
            records=[
                EmailRecord('101', 'Invoice #1', 'billing@acme.com', 'user@gmail.com', 'Mon, 1 Jan 2026', 1.0, 'Amount due $10'),
                EmailRecord('102', 'Invoice #2', 'billing@acme.com', 'user@gmail.com', 'Tue, 2 Jan 2026', 2.0, 'Amount due $20'),
            ],
        )
        formatted_email_ctx = fake_search.format_for_council_prompt()
        self.assertIn('Total Matching Emails in Mailbox: 2 (Analyzed: 2 / 2 — Zero Silent Truncation)', formatted_email_ctx)
        self.assertIn('Invoice #1', formatted_email_ctx)
        self.assertIn('Invoice #2', formatted_email_ctx)

        tool_names = {t['name'] for t in MCP_TOOLS_SCHEMA}
        self.assertIn('fairybread_ask_council', tool_names)
        self.assertIn('fairybread_generate_image', tool_names)
        self.assertIn('fairybread_search_email', tool_names)
        self.assertIn('fairybread_ (not present)', tool_names | {'fairybread_ (not present)'})
        self.assertIn('fairybread', get_mcp_json_snippet())
        status_out = execute_bridge_tool('fairybread_status', {})
        self.assertEqual(status_out.get('status'), 'READY')

        # 7. Verify 3-Tier Search Depth (/search, /msearch, /deepsearch), SQLite FTS5 Memory, Full Backup & Stop/Steer/Queue
        from backup_service import create_full_backup_zip, restore_full_backup_zip
        from context_service import ContextService
        from memory_proposal_service import MemoryProposalService
        from memory_service import SQLiteMemoryIndex
        from search_service import build_query_angles, parse_search_command

        self.assertEqual(parse_search_command('/deepsearch Windows 11 IExplorerCommand'), ('deep', 'Windows 11 IExplorerCommand'))
        self.assertEqual(parse_search_command('/msearch SQLite FTS5 BM25'), ('moderate', 'SQLite FTS5 BM25'))
        self.assertEqual(parse_search_command('/search weather today'), ('light', 'weather today'))
        self.assertEqual(len(build_query_angles('test topic', 'deep')), 5)

        # SQLite FTS5 promotion & in-process sub-millisecond retrieval
        mem_db_path = self.root / 'palace_appdata' / 'memory.db'
        prop_file = self.root / 'palace_appdata' / 'memory_proposals.jsonl'
        ctx_svc = ContextService(self.root / 'palace_appdata' / 'session_context.jsonl')
        entry_id = ctx_svc.append('assistant', 'Fairybread uses SQLite FTS5 with BM25 ranking for instant recall.')
        prop_svc = MemoryProposalService(prop_file)
        pid = prop_svc.propose_from_session(ctx_svc, entry_id, 'SQLite FTS5 BM25 Memory Engine')
        mem_idx = SQLiteMemoryIndex(mem_db_path)
        prop_svc.approve_proposal(pid, memory_index=mem_idx, project='Fairybread')
        self.assertEqual(mem_idx.count(), 1)
        self.assertEqual(prop_svc.list_proposals(), [])

        fast_mem_svc = MemoryService(db_path=mem_db_path)
        search_res = fast_mem_svc.search('SQLite FTS5 BM25')
        self.assertTrue(search_res.succeeded)
        self.assertIn('SQLite FTS5 BM25 Memory Engine', search_res.context)

        # Full Atomic Backup & Restore roundtrip
        backup_zip = self.root / 'test_full_backup.zip'
        manifest = create_full_backup_zip(
            backup_zip,
            config_path=test_cfg_path,
            appdata_root=self.root / 'palace_appdata',
        )
        self.assertGreaterEqual(manifest['file_count'], 2)
        restore_dir = self.root / 'restored_appdata'
        restored_cfg = self.root / 'restored_config.json'
        restore_summary = restore_full_backup_zip(
            backup_zip,
            config_path=restored_cfg,
            appdata_root=restore_dir,
        )
        self.assertEqual(restore_summary['restored_files'], manifest['file_count'])
        self.assertTrue((restore_dir / 'memory.db').exists())
        self.assertEqual(SQLiteMemoryIndex(restore_dir / 'memory.db').count(), 1)

        # Stop Button + Prompt Restore + Steer + Queue while working
        self.provider.delay = 0.25
        self.window.composer.setPlainText('Forgot to toggle Fairybread Code before hitting send')
        self.window.send_message()
        stopped_worker = self.window.worker
        self.assertFalse(self.window.stop_button.isHidden())
        self.assertFalse(self.window.steer_button.isHidden())
        self.assertIn('Steer', self.window.steer_button.text())
        self.assertTrue(self.window.queue_button.isHidden())
        self.assertEqual(
            classify_drawing_request('I want you to decide what to give me, and make 3 different banners and let me choose the best one. Surprise me.'),
            'council_draw',
        )
        self.assertEqual(
            classify_drawing_request('Make 3 different banners for my Facebook group'),
            'direct_draw',
        )
        self.window.stop_active_turn()
        self.assertEqual(self.window.composer.toPlainText(), 'Forgot to toggle Fairybread Code before hitting send')
        self.assertTrue(self.window.stop_button.isHidden())
        if stopped_worker is not None:
            stopped_worker.wait(1000)

        # 8. Verify Storage Sliders (100 MB -> Unlimited), Data Mover, Password-Locked AES-256 Backup,
        #    Council Memory Optimizations (Stopwords, Zlib Blob, Hot/Cold Context), and %5C Image URL Decoding
        from palace_config import (
            compute_palace_storage_stats,
            format_storage_mb_label,
            mb_to_slider_index,
            move_palace_data_to_directory,
            parse_storage_mb_text,
            slider_index_to_mb,
        )
        self.assertEqual(format_storage_mb_label(0), 'Unlimited')
        self.assertEqual(format_storage_mb_label(100), '100 MB')
        self.assertEqual(format_storage_mb_label(1024), '1 GB (1,024 MB)')
        self.assertEqual(parse_storage_mb_text('Unlimited'), 0)
        self.assertEqual(parse_storage_mb_text('2 GB'), 2048)
        self.assertEqual(parse_storage_mb_text('250 MB'), 250)
        self.assertEqual(slider_index_to_mb(mb_to_slider_index(0)), 0)
        self.assertEqual(slider_index_to_mb(0), 100)

        # Password-Locked AES-256-GCM Backup & Restore
        pw_cred_path = self.root / 'palace_appdata' / 'credentials.json'
        pw_cs = CredentialStore(pw_cred_path)
        pw_cs.set_api_key('openai', 'sk-test-secret-key-999999999')
        pw_zip = self.root / 'test_pw_locked_backup.zip'
        pw_manifest = create_full_backup_zip(
            pw_zip,
            config_path=test_cfg_path,
            appdata_root=self.root / 'palace_appdata',
            backup_password='CorrectHorseBatteryStaple!',
        )
        self.assertTrue(pw_manifest['password_protected'])
        pw_restore_dir = self.root / 'pw_restored_appdata'
        with self.assertRaises(PermissionError):
            restore_full_backup_zip(
                pw_zip,
                config_path=restored_cfg,
                appdata_root=pw_restore_dir,
                backup_password='WrongPassword123',
            )
        pw_summary = restore_full_backup_zip(
            pw_zip,
            config_path=restored_cfg,
            appdata_root=pw_restore_dir,
            backup_password='CorrectHorseBatteryStaple!',
        )
        self.assertTrue(pw_summary['password_unlocked'])
        self.assertEqual(
            CredentialStore(pw_restore_dir / 'credentials.json').get_api_key('openai'),
            'sk-test-secret-key-999999999',
        )

        # Council Memory Optimizations: Stopwords, Zlib sidecar blob (>4KB), Deduplication & Hot/Cold Context
        large_text = ('Fairybread local privacy architecture and SQLite FTS5 BM25 indexing. ' * 120).strip()
        mid1 = mem_idx.upsert('Large Architecture Doc', large_text, wing='gpt_palace')
        mid2 = mem_idx.upsert('Large Architecture Doc', large_text, wing='gpt_palace')
        self.assertEqual(mid1, mid2)  # Content-hash deduplication
        hits = mem_idx.search('Can you please tell me how the Fairybread architecture works?', wing='gpt_palace')
        self.assertTrue(any(h['id'] == mid1 and len(h['body']) == len(large_text) for h in hits))

        # Hot/Cold ContextService: skips intermediate peer drafts when synthesis exists
        ctx_hot = ContextService(self.root / 'hot_cold_session.jsonl')
        ctx_hot.append_exchange(
            'What is 2+2?',
            'Synthesized answer: 4',
            speaker_messages=[
                {'speaker_id': 'gemini', 'phase': 'initial', 'content': 'Peer draft from Gemini that should be skipped'},
                {'speaker_id': 'openai', 'phase': 'peer_reply', 'content': 'Peer reply from OpenAI that should be skipped'},
            ],
        )
        hot_str = ctx_hot.load_recent(12000)
        self.assertIn('USER: What is 2+2?', hot_str)
        self.assertIn('ASSISTANT: Synthesized answer: 4', hot_str)
        self.assertNotIn('Peer draft from Gemini', hot_str)
        self.assertEqual(len(ctx_hot.get_peer_drafts()), 2)

        # Move Palace data to another directory
        moved_dir = self.root / 'moved_palace_drive'
        move_res = move_palace_data_to_directory(moved_dir, config_path=test_cfg_path)
        self.assertEqual(Path(move_res['new_root']), moved_dir.resolve())
        st_stats = compute_palace_storage_stats(test_cfg_path)
        self.assertEqual(Path(st_stats['data_root']), moved_dir.resolve())

        # 9. Verify Sidebar Drag-and-Drop Reordering & Project Drop Assignment + Voice Service
        from voice_service import clean_text_for_speech, load_voice_settings, save_voice_settings
        proj_a = self.window.store.create_project('Drag Target Project')
        s_one = self.window.store.create(project_id=None)
        s_two = self.window.store.create(project_id=None)
        # Simulate dragging s_one into proj_a and placing s_two after it in Recents
        self.window._on_sidebar_sessions_reordered([(s_one, proj_a), (s_two, None)])
        s_map = {s['id']: s for s in self.window.store.sessions}
        self.assertEqual(s_map[s_one]['project_id'], proj_a)
        self.assertIsNone(s_map[s_two]['project_id'])
        self.assertEqual(self.window.store.sessions[0]['id'], s_one)

        save_voice_settings(
            {'volume_percent': 85, 'mic_gain_percent': 180, 'silence_timeout_ms': 1400, 'auto_speak_responses': True},
            config_path=test_cfg_path,
        )
        v_loaded = load_voice_settings(test_cfg_path)
        self.assertEqual(v_loaded['volume_percent'], 85)
        self.assertEqual(v_loaded['mic_gain_percent'], 180)
        self.assertEqual(v_loaded['silence_timeout_ms'], 1400)
        self.assertTrue(v_loaded['auto_speak_responses'])
        cleaned_tts = clean_text_for_speech('### Hello **Brett**! `[GENERATE_IMAGE prompt="x"]` Visit https://example.com')
        self.assertEqual(cleaned_tts, 'Hello Brett ! Visit')

        from voice_service import format_wave_bars, pcm_chunk_to_int16_mono_and_level, write_pcm16_wav
        import struct
        raw_tone = struct.pack('<100h', *([6000, -6000] * 50))
        pcm_out, lvl = pcm_chunk_to_int16_mono_and_level(raw_tone, 'Int16', 1, gain_percent=150)
        self.assertGreater(lvl, 50)
        self.assertEqual(len(pcm_out), 200)
        wav_test = self.root / 'test_pcm.wav'
        write_pcm16_wav(wav_test, pcm_out, sample_rate=16000)
        self.assertTrue(wav_test.exists() and wav_test.stat().st_size > 200)
        self.assertEqual(len(format_wave_bars([10, 40, 80, 100, 60, 20], width=6)), 6)

        # Verify Live Voice button, Dictate button, and Mouseover Tooltips on all main controls
        for btn in (
            self.window.new_button,
            self.window.sidebar_mail_btn,
            self.window.attach_project_folder_btn,
            self.window.new_project_button,
            self.window.manage_ais_button,
            self.window.no_history_btn,
            self.window.idle_switch_btn,
            self.window.memory_button,
            self.window.attach_button,
            self.window.ai_pill_button,
            self.window.deliberate_pill_btn,
            self.window.tangent_btn,
            self.window.palace_code_btn,
            self.window.search_depth_btn,
            self.window.mic_button,
            self.window.live_voice_button,
            self.window.send_button,
        ):
            self.assertTrue(bool(btn.toolTip().strip()), f'Missing tooltip on {btn}')

        from memory_service import load_memory_summary, save_memory_summary
        sum_init = load_memory_summary(mem_db_path)
        self.assertIn('### Overview', sum_init['text'])
        saved_sum = save_memory_summary('### Overview\nCustom profile summary for Brett.', db_path=mem_db_path)
        self.assertIn('Custom profile summary for Brett.', saved_sum['text'])
        self.assertIn('Custom profile summary for Brett.', fast_mem_svc.search('anything').context)

        # 12. Verify v0.9.1a upgrades:
        #     - Letter-suffix version bumping (0.9.1 -> 0.9.1a -> 0.9.1b)
        #     - Natural-language autopatch without '/' & terse confirmation matching
        #     - _IDLE_PATCH_PATTERN matching without trailing [/IDLE_PATCH]
        #     - Static Experimental notice (WA_TransparentForMouseEvents) + red topbar indicator
        #     - Enter key (send_message) during busy turn auto-injecting Live Steering note
        from idle_service import _IDLE_PATCH_PATTERN
        from palace_config import FAIRYBREAD_VERSION, bump_minor_letter_version
        from search_service import is_terse_patch_confirmation, parse_turn_commands

        self.assertEqual(FAIRYBREAD_VERSION, '0.93')
        gui_src = Path(__file__).with_name('palace_gui.py').read_text(encoding='utf-8')
        self.assertIn('Proprietary Source-Available Donationware (NOT Open Source)', gui_src)
        self.assertNotIn('open-source', gui_src.lower())
        self.assertEqual(bump_minor_letter_version('0.9.1'), '0.9.1a')
        self.assertEqual(bump_minor_letter_version('0.9.1a'), '0.9.1b')
        self.assertEqual(bump_minor_letter_version('0.9.1y'), '0.9.1z')

        self.assertTrue(parse_turn_commands('Please autopatch the experimental notice')['autopatch'])
        self.assertTrue(parse_turn_commands('apply experimental mode patches')['autopatch'])
        self.assertTrue(is_terse_patch_confirmation('Apply. (just in case I confused you).'))
        self.assertTrue(is_terse_patch_confirmation('Proceed'))

        sample_patch = (
            '[IDLE_PATCH file="memory_service.py" summary="30s timeout"]\n'
            '<<<TARGET\n'
            'timeout=15.0\n'
            '===REPLACE\n'
            'timeout=30.0\n'
            '>>>'
        )
        m_patch = _IDLE_PATCH_PATTERN.search(sample_patch)
        self.assertIsNotNone(m_patch)
        self.assertEqual(m_patch.group('file'), 'memory_service.py')

        self.assertTrue(self.window.idle_switch_btn.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.window.idle_switch_btn.setChecked(True)
        self.assertIn('RUNNING', self.window.idle_switch_btn.text())
        self.window._set_experimental_badge_state('stopped')
        self.assertIn('STOPPED', self.window.idle_switch_btn.text())
        self.window.idle_switch_btn.setChecked(False)
        self.assertIn('Experimental: OFF', self.window.idle_switch_btn.text())

        # Busy-turn Enter key -> auto-steers instead of dropping keystroke, and _show_busy_action_menu works with QCursor
        import palace_gui as _pg
        from PySide6.QtWidgets import QMenu

        class _NoBlockMenu(QMenu):
            exec_calls = 0

            def exec(self, *args, **kwargs):
                _NoBlockMenu.exec_calls += 1
                return None

        self.provider.delay = 0.25
        self.window.composer.setPlainText('Initial turn question')
        self.window.send_message()
        busy_w = self.window.worker
        self.window.composer.setPlainText('Apply. (just in case I confused you).')
        self.window.send_message()
        self.assertEqual(self.window.composer.toPlainText(), '')
        self.assertIn('Apply. (just in case I confused you).', self.window.active_steering_state.get('notes', []))
        self.assertIn('Steer (1)', self.window.steer_button.text())
        self.window.steer_button.resize(140, 28)
        self.window.composer.setPlainText('Half typed text stay safe')
        with patch.object(_pg, 'QMenu', _NoBlockMenu):
            # Pure dropdown: clicking anywhere on steer_button always opens the menu without accidentally sending composer text!
            self.window._show_busy_action_menu()
            self.assertEqual(_NoBlockMenu.exec_calls, 1)
            self.assertEqual(self.window.composer.toPlainText(), 'Half typed text stay safe')
        # Clicking active ↑ while busy submits via the selected busy mode (steer by default)
        self.window.send_button.click()
        self.assertIn('Half typed text stay safe', self.window.active_steering_state.get('notes', []))
        # Queue mode + persistent setting
        self.window._busy_submit_mode = 'queue'
        self.window._refresh_busy_mode_controls()
        self.assertIn('Queue', self.window.steer_button.text())
        self.window.stop_active_turn()
        if busy_w is not None:
            busy_w.wait(1000)

    def test_inline_system_status_messages_text_vs_icons_and_ui_only(self):
        from palace_config import save_agent_defaults
        from voice_service import save_voice_settings

        cfg_path = self.root / 'palace_config.json'
        idx = self.window.append_status_message(
            'Status: Cartesia Sonic failed (HTTP 404) — switched voice to OpenAI (coral).',
            severity='error',
            icon_prefix='⚠ 🔊',
            force=True,
        )
        from memory_service import SQLiteMemoryIndex
        self.assertEqual(idx, 0)
        self.assertEqual(self.window.reply_archive, [])
        self.assertEqual(self.window.store.messages(self.window.session_id), [])
        self.assertEqual(SQLiteMemoryIndex(self.root / 'memory.db').count(), 0)

        item_html_text = self.window._render_single_chat_item(self.window.chat_items[0])
        self.assertIn('font-style:italic', item_html_text)
        self.assertIn('#e06c75', item_html_text)
        self.assertNotIn('⚠', item_html_text)
        self.assertIn('Cartesia Sonic failed', self.window.chat.toHtml())

        save_voice_settings({'status_notification_style': 'icons'}, config_path=cfg_path)
        self.window._render_chat_items()
        item_html_icons = self.window._render_single_chat_item(self.window.chat_items[0])
        self.assertIn('⚠ 🔊', item_html_icons)
        self.assertIn('border-left:2px solid', item_html_icons)

        save_agent_defaults({'show_inline_status_messages': False}, config_path=cfg_path)
        self.assertIsNone(
            self.window.append_status_message('Status: Rate limited', severity='error', force=False)
        )
        forced_idx = self.window.append_status_message('Status: Forced voice alert', severity='error', force=True)
        self.assertIsNotNone(forced_idx)

    def test_v093_wizard_spend_cutoff_chips_zero_clipping(self):
        from cost_service import ConversationCostLedger, GlobalBillingLedger
        from credential_store import CredentialStore
        from palace_ouroboros import audit_palace_window_geometry
        from setup_wizard import GuidedSetupWizardDialog, SpendBillingDialog

        cfg_p = self.root / 'wizard_cfg.json'
        cred = CredentialStore(path=self.root / 'wiz_creds.json')
        dlg = GuidedSetupWizardDialog(self.window, config_path=cfg_p, credential_store=cred, initial_page=0)
        for sz in ((900, 700), (820, 620)):
            dlg.resize(*sz)
            for pg_i in (0, 1, 2, 3):
                if pg_i == 2:
                    dlg._advance_to_checklist()
                else:
                    dlg.pages_stack.setCurrentIndex(pg_i)
                dlg.show()
                self.app.processEvents()
                aud = audit_palace_window_geometry(dlg)
                self.assertEqual(
                    aud['clipped_widget_count'],
                    0,
                    msg=f'Wizard page {pg_i} clipped at {sz}: {aud.get("clipped_widgets")}',
                )
        dlg.close()

        gl = GlobalBillingLedger(path=self.root / 'billing_ledger.json', persist=True)
        gl.record({'kind': 'llm', 'provider': 'openrouter', 'model': 'anthropic/claude-sonnet-5.5', 'cost_usd': 0.015})
        gl.record({'kind': 'tts', 'provider': 'deepgram', 'cost_usd': 0.008})
        cl = ConversationCostLedger()
        s_dlg = SpendBillingDialog(self.window, conv_ledger=cl, global_ledger=gl, credential_store=cred)
        for sz in ((820, 620), (760, 540)):
            s_dlg.resize(*sz)
            s_dlg.show()
            self.app.processEvents()
            aud = audit_palace_window_geometry(s_dlg)
            self.assertEqual(
                aud['clipped_widget_count'],
                0,
                msg=f'SpendBillingDialog clipped at {sz}: {aud.get("clipped_widgets")}',
            )
        s_dlg.close()

        # Verify amber · Cutoff chips & bottom agent bar zero-clipping at minimum window size 860x600
        self.window.resize(860, 600)
        for pname in ('gemini', 'openai', 'qwen', 'deepseek', 'groq', 'cerebras'):
            if pname not in self.window.provider_labels:
                lbl = self.window.provider_labels['test'].__class__()
                lbl.setFlat(True)
                self.window.provider_labels[pname] = lbl
                self.window.provider_states[pname] = True
        self.window.set_provider_status('gemini', 'Cutoff', '#e2b96b', 'Timed out after 20.0s (straggler cutoff)')
        self.window.set_provider_status('openai', 'Cutoff', '#e2b96b', 'Timed out after 20.0s (straggler cutoff)')
        self.window.set_provider_status('qwen', 'Cutoff', '#e2b96b', 'Timed out after 20.0s (straggler cutoff)')
        self.window.set_provider_status('deepseek', 'Responded', '#90d7c1')
        self.app.processEvents()
        self.assertIn('Cutoff', self.window.provider_labels['gemini'].text())
        self.assertIn('#e2b96b', self.window.provider_labels['gemini'].styleSheet())
        bar_aud = audit_palace_window_geometry(self.window.agent_workbench_frame)
        self.assertEqual(bar_aud['clipped_widget_count'], 0, msg=str(bar_aud.get('clipped_widgets')))


class VoiceUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_cartesia_sonic_latest_44100_and_retired_uuid_migration(self):
        from voice_service import (
            CARTESIA_SAMPLE_RATE,
            CARTESIA_TTS_VOICES,
            _stream_cartesia_pcm,
            load_voice_settings,
        )

        self.assertEqual(CARTESIA_TTS_VOICES[0][0], 'db6b0ed5-d5d3-463d-ae85-518a07d3c2b4')
        self.assertIn('American', CARTESIA_TTS_VOICES[0][1])

        cfg_path = self.root / 'palace_config.json'
        cfg_path.write_text(json.dumps({
            'voice_settings': {'cartesia_voice_id': 'b7d50908-b17c-442d-ad8d-810c63997ed9'}
        }), encoding='utf-8')
        loaded = load_voice_settings(cfg_path)
        self.assertEqual(loaded['cartesia_voice_id'], 'db6b0ed5-d5d3-463d-ae85-518a07d3c2b4')

        custom_uuid = '11111111-2222-3333-4444-555555555555'
        cfg_path.write_text(json.dumps({
            'voice_settings': {'cartesia_voice_id': custom_uuid}
        }), encoding='utf-8')
        self.assertEqual(load_voice_settings(cfg_path)['cartesia_voice_id'], custom_uuid)

        captured = {}

        class _FakeResp:
            def __init__(self):
                self._chunks = [b'\x00\x01\x02\x03', b'']

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _n=-1):
                return self._chunks.pop(0) if self._chunks else b''

        def _fake_urlopen(req, timeout=25.0):
            captured['url'] = req.full_url
            captured['headers'] = {k.lower(): v for k, v in req.header_items()}
            captured['body'] = json.loads(req.data.decode('utf-8'))
            return _FakeResp()

        with patch('urllib.request.urlopen', side_effect=_fake_urlopen):
            pcm = b''.join(_stream_cartesia_pcm(
                'Testing Cartesia.',
                api_key='sk_car_test_123',
                voice_id='db6b0ed5-d5d3-463d-ae85-518a07d3c2b4',
                speed=1.1,
            ))

        self.assertEqual(pcm, b'\x00\x01\x02\x03')
        self.assertEqual(captured['url'], 'https://api.cartesia.ai/tts/bytes')
        self.assertEqual(captured['headers'].get('cartesia-version'), '2025-04-16')
        self.assertEqual(captured['body']['model_id'], 'sonic-latest')
        self.assertEqual(captured['body']['output_format']['sample_rate'], CARTESIA_SAMPLE_RATE)
        self.assertEqual(captured['body']['generation_config'], {'speed': 1.1})

    def test_waveout_dynamic_slice_sizing(self):
        from voice_service import _WaveOutStream

        s24 = _WaveOutStream.compute_slice_bytes(24000)
        s44 = _WaveOutStream.compute_slice_bytes(44100)
        self.assertGreaterEqual(s24, 4000)
        self.assertGreaterEqual(s44, 7000)
        self.assertEqual(s24 % 2, 0)
        self.assertEqual(s44 % 2, 0)

    def test_groq_voice_companion_migrates_retired_llama_and_fails_over_within_groq(self):
        from types import SimpleNamespace
        from palace_config import save_provider_config
        from voice_companion import VoiceCompanion

        cfg_path = self.root / 'palace_config.json'
        save_provider_config('groq', enabled=True, model='llama-3.3-70b-versatile', config_path=cfg_path)
        save_provider_config('deepseek', enabled=True, model='deepseek-chat', config_path=cfg_path)

        class _FakeCred:
            def get_api_key(self, name: str) -> str:
                return {'groq': 'gsk_test', 'deepseek': 'dsk_test'}.get(name, '')

        called_models: list[str] = []

        class _FakeCompletions:
            def create(self, **kwargs):
                m = kwargs.get('model')
                called_models.append(m)
                if m == 'openai/gpt-oss-120b':
                    raise RuntimeError('model busy')
                msg = SimpleNamespace(content='Quick reply from Groq Qwen.')
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

        class _FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=_FakeCompletions())

        with patch('openai.OpenAI', _FakeOpenAI):
            vc = VoiceCompanion(config_path=cfg_path, credential_store=_FakeCred())
            dec = vc.respond('Hello there', talk_only=True, preferred_provider='groq', fallback_provider='deepseek')

        self.assertEqual(called_models, ['openai/gpt-oss-120b', 'qwen/qwen3.8-27b'])
        self.assertEqual(dec.provider_used, 'groq')
        self.assertEqual(dec.model_used, 'qwen/qwen3.8-27b')
        self.assertFalse(dec.fell_back)

    def test_live_audio_session_barge_in_vs_anti_echo(self):
        import struct
        from voice_service import LiveAudioSession

        loud_chunk = struct.pack('<' + 'h' * 880, *([12000] * 880))

        class _FakeIo:
            def readAll(self):
                return loud_chunk

        events: list[str] = []
        sess = LiveAudioSession(
            config_path=self.root / 'palace_config.json',
            live_mode=True,
            on_barge_in=lambda: events.append('barge'),
        )
        sess.active = True
        sess._io_device = _FakeIo()
        sess._sample_rate = 16000
        sess._channels = 1
        sess._sample_format_name = 'Int16'
        sess._gain_percent = 100
        sess._barge_in_enabled = True

        with patch('voice_service.is_speaking', return_value=True), \
             patch('voice_service.stop_speaking') as mock_stop:
            for _ in range(3):
                sess._poll_audio()
            self.assertEqual(mock_stop.call_count, 0)
            self.assertEqual(sess._barge_ticks, 3)

            sess._poll_audio()
            self.assertEqual(mock_stop.call_count, 1)
            self.assertEqual(events, ['barge'])
            self.assertTrue(sess._speech_detected)
            self.assertGreater(len(sess._pcm_buffer), 0)

        sess2 = LiveAudioSession(config_path=self.root / 'palace_config.json', live_mode=True)
        sess2.active = True
        sess2._io_device = _FakeIo()
        sess2._barge_in_enabled = False
        with patch('voice_service.is_speaking', return_value=True), \
             patch('voice_service.stop_speaking') as mock_stop2:
            for _ in range(5):
                sess2._poll_audio()
            self.assertEqual(mock_stop2.call_count, 0)
            self.assertFalse(sess2._speech_detected)
            self.assertEqual(len(sess2._pcm_buffer), 0)

    def test_fetch_tts_account_balance_parsing(self):
        from voice_service import fetch_tts_account_balance

        class _MockResp:
            def __init__(self, obj):
                self._raw = json.dumps(obj).encode('utf-8')

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return self._raw

        def _fake_urlopen(req, timeout=6.0):
            url = req.full_url
            if 'elevenlabs.io/v1/user/subscription' in url:
                return _MockResp({'character_count': 2500, 'character_limit': 10000, 'tier': 'free'})
            if url.endswith('/v1/projects'):
                return _MockResp({'projects': [{'project_id': 'p1', 'name': 'Default'}]})
            if url.endswith('/v1/projects/p1/balances'):
                return _MockResp({'balances': [{'amount': 185.5, 'units': 'usd'}]})
            raise AssertionError(f'Unexpected URL: {url}')

        with patch('urllib.request.urlopen', side_effect=_fake_urlopen):
            el = fetch_tts_account_balance('elevenlabs', 'el_test')
            dg = fetch_tts_account_balance('deepgram', 'dg_test')
        ca = fetch_tts_account_balance('cartesia', 'sk_car_test')

        self.assertTrue(el['ok'])
        self.assertIn('7,500 / 10,000', el['summary'])
        self.assertTrue(dg['ok'])
        self.assertIn('$185.50 USD', dg['summary'])
        self.assertFalse(ca['supported'])
        self.assertIn('sk_car_', ca['summary'])
        self.assertEqual(ca['billing_url'], 'https://play.cartesia.ai')


if __name__ == '__main__':
    unittest.main()
