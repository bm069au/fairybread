import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from context_service import ContextService


class MemoryProposalService:
    """Store reviewable durable-memory proposals separately from session history."""

    ALLOWED_TYPES = {"semantic", "procedural"}

    def __init__(self, path: Path | None = None):
        if path is None:
            path = (
                Path(os.environ["LOCALAPPDATA"])
                / "Palace"
                / "memory_proposals.jsonl"
            )
        self.path = Path(path)

    def propose_from_session(
        self,
        context: ContextService,
        source_id: str,
        summary: str,
        memory_type: str = "semantic",
        visibility: str = "private",
    ) -> str:
        """Copy one exact session entry into a proposed durable-memory record."""
        summary = summary.strip() if isinstance(summary, str) else ""
        if not summary:
            raise ValueError("A non-empty memory summary is required")
        if memory_type not in self.ALLOWED_TYPES:
            raise ValueError("Memory type must be semantic or procedural")
        if visibility != "private":
            raise ValueError("Only private proposals are supported in this milestone")
        source = context.read_entry(source_id)
        if source is None:
            raise ValueError("Session source ID was not found")

        proposal_id = str(uuid4())
        proposal = {
            "id": proposal_id,
            "schema_version": 1,
            "created_at": datetime.now().astimezone().isoformat(),
            "status": "proposed",
            "memory_type": memory_type,
            "summary": summary,
            "detail": source["content"],
            "visibility": visibility,
            "source": {
                "kind": "session_entry",
                "entry_id": source["id"],
                "role": source["role"],
                "timestamp": source["timestamp"],
            },
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(proposal) + "\n")
        return proposal_id

    def read_proposal(self, proposal_id: str) -> dict | None:
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise ValueError("A non-empty proposal ID is required")
        if not self.path.exists():
            return None

        found = None
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                proposal = json.loads(line)
                self._validate(proposal)
                if proposal["id"] == proposal_id:
                    if found is not None:
                        raise ValueError("Duplicate memory proposal ID")
                    found = proposal
        return found

    @classmethod
    def _validate(cls, proposal: object) -> None:
        if not isinstance(proposal, dict):
            raise ValueError("Invalid memory proposal")
        required = {
            "id", "schema_version", "created_at", "status", "memory_type",
            "summary", "detail", "visibility", "source",
        }
        if not required.issubset(proposal):
            raise ValueError("Invalid memory proposal")
        if proposal["status"] != "proposed":
            raise ValueError("Unsupported memory proposal status")
        if proposal["memory_type"] not in cls.ALLOWED_TYPES:
            raise ValueError("Invalid memory proposal type")
        source = proposal["source"]
        if (not isinstance(source, dict)
                or source.get("kind") != "session_entry"
                or not isinstance(source.get("entry_id"), str)):
            raise ValueError("Invalid memory proposal source")
