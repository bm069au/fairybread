import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from context_service import ContextService
from memory_proposal_service import MemoryProposalService


class MemoryProposalTests(unittest.TestCase):
    def test_proposal_preserves_detail_and_source_across_restart(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            context = ContextService(root / "session.jsonl")
            source_id = context.append("user", "Palace uses PySide6. é")
            proposals = MemoryProposalService(root / "proposals.jsonl")
            proposal_id = proposals.propose_from_session(
                context, source_id, "Palace Windows UI uses PySide6"
            )

            code = (
                "from memory_proposal_service import MemoryProposalService; "
                "import sys,json; print(json.dumps("
                "MemoryProposalService(sys.argv[1]).read_proposal(sys.argv[2])))"
            )
            run = subprocess.run(
                [sys.executable, "-B", "-c", code, str(proposals.path), proposal_id],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            record = json.loads(run.stdout)
            self.assertEqual(record["status"], "proposed")
            self.assertEqual(record["memory_type"], "semantic")
            self.assertEqual(record["detail"], "Palace uses PySide6. é")
            self.assertEqual(record["source"]["entry_id"], source_id)
            self.assertNotIn("store", record["source"])
            self.assertEqual(
                ContextService(root / "session.jsonl")
                    .read_entry(source_id)["content"],
                record["detail"],
            )

    def test_invalid_or_missing_source_does_not_write(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            context = ContextService(root / "session.jsonl")
            proposals = MemoryProposalService(root / "proposals.jsonl")
            with self.assertRaisesRegex(ValueError, "not found"):
                proposals.propose_from_session(context, "missing", "Summary")
            self.assertFalse(proposals.path.exists())

            source_id = context.append("user", "Decision")
            for summary, memory_type, visibility in [
                ("", "semantic", "private"),
                ("Summary", "episodic", "private"),
                ("Summary", "semantic", "shared"),
            ]:
                with self.assertRaises(ValueError):
                    proposals.propose_from_session(
                        context, source_id, summary, memory_type, visibility
                    )
            self.assertFalse(proposals.path.exists())

    def test_duplicate_and_corrupt_proposals_fail_visibly(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            context = ContextService(root / "session.jsonl")
            source_id = context.append("user", "Decision")
            proposals = MemoryProposalService(root / "proposals.jsonl")
            proposal_id = proposals.propose_from_session(context, source_id, "Decision")
            valid = proposals.path.read_text(encoding="utf-8")
            proposals.path.write_text(valid + valid, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                proposals.read_proposal(proposal_id)
            proposals.path.write_text(valid + "{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                proposals.read_proposal(proposal_id)


if __name__ == "__main__":
    unittest.main()
