import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from bootstrap import build_palace
from context_service import ContextService
from memory_service import MemoryService
from providers import ProviderResponse
import palace_cli


class RecordingProvider:
    def __init__(self, answer="Displayed answer", fail=False):
        self.prompts = []
        self.answer = answer
        self.fail = fail

    def generate(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("Provider unavailable")
        return ProviderResponse(text=self.answer)


class SessionContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "session.jsonl"
        self.context = ContextService(self.path)

    def palace(self, provider, **kwargs):
        palace = build_palace({"fake": provider}, context_service=self.context, **kwargs)
        palace.memory_service = MemoryService(db_path=Path(self.directory.name) / "memory.db")
        palace.memory_service.search = unittest.mock.Mock(
            side_effect=AssertionError("Long-term memory must remain opt-in"))
        return palace

    def test_exchange_is_saved_once_and_used_on_next_run(self):
        provider = RecordingProvider()
        palace = self.palace(provider)
        first = palace.run("Remember the blue door")
        self.assertEqual(first.session_context, "")
        second = palace.run("Which door?")
        self.assertIn("USER: Remember the blue door", second.prompt)
        self.assertIn("ASSISTANT: Displayed answer", second.prompt)
        self.assertEqual(second.prompt.count("Which door?"), 1)
        records = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual([r['role'] for r in records], ['user', 'assistant'] * 2)
        self.assertEqual(records[-1]['content'], second.final_answer)
        palace.memory_service.search.assert_not_called()

    def test_no_context_does_not_read_or_write(self):
        self.context.append_exchange("Secret", "Earlier answer")
        original = self.path.read_bytes()
        with patch.object(self.context, 'load_recent', side_effect=AssertionError), patch.object(
                self.context, 'append_exchange', side_effect=AssertionError):
            result = self.palace(RecordingProvider()).run("New question", include_context=False)
        self.assertNotIn("Secret", result.prompt)
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_providers_do_not_save_an_exchange(self):
        result = self.palace(RecordingProvider(fail=True)).run("Question")
        self.assertIsNone(result.final_answer)
        self.assertFalse(self.path.exists())

    def test_corrupt_history_warns_and_preserves_file(self):
        self.path.write_text('{incomplete', encoding='utf-8')
        result = self.palace(RecordingProvider()).run("Question")
        self.assertEqual(result.final_answer, "Displayed answer")
        self.assertIn("could not be loaded", result.context_error)
        self.assertEqual(self.path.read_text(), '{incomplete')

    def test_write_failure_keeps_answer_and_reports_warning(self):
        with patch.object(self.context, 'append_exchange', side_effect=PermissionError('denied')):
            result = self.palace(RecordingProvider()).run("Question")
        self.assertEqual(result.final_answer, "Displayed answer")
        self.assertIn("could not be saved", result.context_error)

    def test_synthesis_receives_history_and_only_final_answer_is_saved(self):
        self.context.append_exchange("Our colour is blue", "Understood")
        one, two = RecordingProvider("Final synthesis"), RecordingProvider("Independent answer")
        palace = build_palace({'one': one, 'two': two}, context_service=self.context)
        palace.memory_service = MemoryService(db_path=Path(self.directory.name) / "memory.db")
        result = palace.run("What is our colour?")
        self.assertEqual(len(one.prompts), 2)
        self.assertIn("Our colour is blue", one.prompts[-1])
        self.assertEqual(result.final_answer, "Final synthesis")
        self.assertNotIn("Independent answer", self.path.read_text())

    def test_bounds_unicode_order_and_missing_history(self):
        self.assertEqual(self.context.load_recent(), '')
        self.context.append_exchange("old", "older")
        self.context.append_exchange("new", "é" * 200)
        text = self.context.load_recent(40)
        self.assertLessEqual(len(text), 40)
        self.assertTrue(text.startswith('ASSISTANT: é'))
        self.assertEqual(self.context.load_recent(0), '')
        self.assertEqual(self.context.load_recent(-1), '')
        whole = self.context.load_recent()
        self.assertLess(whole.index('USER: old'), whole.index('USER: new'))

    def test_cli_filters_disabled_providers_and_no_context_skips_store(self):
        enabled, disabled = RecordingProvider(), RecordingProvider()
        with patch('palace_cli.CredentialStore'), patch(
                'palace_cli.load_configured_providers', return_value={'on': enabled, 'off': disabled}), patch(
                'palace_cli.load_enabled_provider_names', return_value=['on']), patch(
                'palace_cli.ContextService') as store:
            palace = palace_cli.build_configured_palace(include_context=False)
        store.assert_not_called()
        self.assertIsNone(palace.context_service)
        self.assertEqual(palace.dispatcher.registry.names(), ['on'])
        with patch('palace_cli.build_configured_palace', return_value=palace) as build, patch(
                'builtins.input', return_value='Question'), patch('sys.stdout', new_callable=io.StringIO):
            palace_cli.main(['--no-context'])
        build.assert_called_once_with(include_context=False)

    def test_cli_continues_history_in_separate_processes(self):
        # Exercise the actual CLI builder and default path, replacing only remote providers/credentials.
        code = '''
import sys
from unittest.mock import patch
import palace_cli
from providers import ProviderResponse
class Provider:
    def generate(self, prompt):
        if sys.argv[1] == "second":
            assert "USER: The codeword is apricot" in prompt
            assert "ASSISTANT: I will remember apricot" in prompt
            answer = "The codeword is apricot"
        else:
            answer = "I will remember apricot"
        return ProviderResponse(text=answer)
question = "The codeword is apricot" if sys.argv[1] == "first" else "What is the codeword?"
with patch("palace_cli.CredentialStore"), patch("palace_cli.load_configured_providers", return_value={"fake": Provider()}), patch("palace_cli.load_enabled_provider_names", return_value=["fake"]), patch("builtins.input", return_value=question):
    palace_cli.main([])
'''
        env = dict(os.environ, LOCALAPPDATA=self.directory.name, PYTHONDONTWRITEBYTECODE='1')
        for step in ('first', 'second'):
            run = subprocess.run([sys.executable, '-c', code, step], cwd=Path(__file__).parent,
                                 env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('The codeword is apricot', run.stdout)
        saved = Path(self.directory.name) / 'Palace' / 'session_context.jsonl'
        self.assertEqual(len(saved.read_text().splitlines()), 4)


if __name__ == '__main__':
    unittest.main()
