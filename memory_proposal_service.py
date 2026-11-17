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

    def list_proposals(self) -> list[dict]:
        if not self.path.exists():
            return []

        records = []
        seen = set()
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                proposal = json.loads(line)
                self._validate(proposal)
                if proposal["id"] in seen:
                    raise ValueError("Duplicate memory proposal ID")
                seen.add(proposal["id"])
                records.append({
                    "id": proposal["id"],
                    "created_at": proposal["created_at"],
                    "status": proposal["status"],
                    "memory_type": proposal["memory_type"],
                    "summary": proposal["summary"],
                    "visibility": proposal["visibility"],
                    "source": proposal["source"],
                })

        records.reverse()
        return records

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

    def approve_proposal(
        self,
        proposal_id: str,
        memory_index=None,
        wing: str = "gpt_palace",
        room: str = "general",
        project: str = "",
    ) -> str:
        """Promote a proposed memory into the SQLite FTS5 durable memory index and remove from pending queue."""
        record = self.read_proposal(proposal_id)
        if record is None:
            raise ValueError(f"Proposal {proposal_id!r} not found.")
        if memory_index is None:
            from memory_service import SQLiteMemoryIndex
            memory_index = SQLiteMemoryIndex(self.path.parent / "memory.db")
        mem_id = memory_index.upsert(
            summary=record["summary"],
            body=record["detail"],
            memory_id=record["id"],
            wing=wing,
            room=room,
            project=project,
            memory_type=record["memory_type"],
            visibility=record["visibility"],
            source=record["source"],
        )
        self._remove_from_pending(proposal_id, decision="promoted")
        return mem_id

    def reject_proposal(self, proposal_id: str) -> bool:
        """Reject and remove a pending memory proposal, recording an audit entry."""
        record = self.read_proposal(proposal_id)
        if record is None:
            return False
        self._remove_from_pending(proposal_id, decision="rejected")
        return True

    def _remove_from_pending(self, proposal_id: str, decision: str) -> None:
        if not self.path.exists():
            return
        kept: list[str] = []
        removed_rec = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("id") == proposal_id:
                removed_rec = obj
            else:
                kept.append(json.dumps(obj))
        self.path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
        if removed_rec is not None:
            audit_path = self.path.with_name("memory_promotions_audit.jsonl")
            audit_entry = {
                **removed_rec,
                "status": decision,
                "decided_at": datetime.now().astimezone().isoformat(),
            }
            with audit_path.open("a", encoding="utf-8") as af:
                af.write(json.dumps(audit_entry) + "\n")
