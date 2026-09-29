import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from context_service import ContextService

class SourceIdTests(unittest.TestCase):
    def test_full_source_survives_restart_and_context_clipping(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'history.jsonl'
            store = ContextService(path)
            original = 'Detailed decision é\n' * 1500
            question, answer = store.append_exchange(original, 'Acknowledged')
            self.assertNotEqual(question, answer)
            self.assertLessEqual(len(store.load_recent(40)), 40)
            code = 'from context_service import ContextService; import sys,json; print(json.dumps(ContextService(sys.argv[1]).read_entry(sys.argv[2])))'
            run = subprocess.run([sys.executable, '-B', '-c', code, str(path), question], capture_output=True, text=True, cwd=Path(__file__).parent)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['content'], original)
            self.assertEqual(ContextService(path).read_entry(answer)['reply_to'], question)

    def test_legacy_history_preserved_and_identical_messages_are_distinct(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'history.jsonl'
            legacy = '{"timestamp":"old","role":"user","content":"Older decision"}\n'
            path.write_text(legacy, encoding='utf-8')
            store = ContextService(path)
            one = store.append('user', 'Same text')
            two = store.append('user', 'Same text')
            self.assertNotEqual(one, two)
            self.assertTrue(path.read_text(encoding='utf-8').startswith(legacy))
            self.assertIn('Older decision', store.load_recent())
            before = path.read_bytes()
            self.assertIsNone(store.read_entry('unknown'))
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                store.read_entry('')

    def test_duplicate_or_corrupt_sources_fail_visibly(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'history.jsonl'
            store = ContextService(path)
            identifier = store.append('user', 'Decision')
            text = path.read_text(encoding='utf-8')
            path.write_text(text + text, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                store.read_entry(identifier)
            path.write_text(text + '{broken', encoding='utf-8')
            with self.assertRaises(ValueError):
                store.read_entry(identifier)

if __name__ == '__main__':
    unittest.main()
