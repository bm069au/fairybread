import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4


class ContextService:
    def __init__(self, path: Path | None = None):
        if path is None:
            local_app_data = os.environ["LOCALAPPDATA"]

            path = (
                Path(local_app_data)
                / "Palace"
                / "session_context.jsonl"
            )

        self.path = Path(path)

    def append(
        self,
        role: str,
        content: str
    ) -> str:
        entry = {
            "id": str(uuid4()),
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open(
            "a",
            encoding="utf-8"
        ) as file:
            file.write(
                json.dumps(entry)
                + "\n"
            )

        return entry["id"]

    def append_exchange(self, question: str, answer: str) -> tuple[str, str]:
        """Persist only the user's question and the answer Palace displayed."""
        timestamp = datetime.now().isoformat()
        question_id, answer_id = str(uuid4()), str(uuid4())
        entries = [
            {"id": question_id, "timestamp": timestamp, "role": "user", "content": question},
            {"id": answer_id, "reply_to": question_id, "timestamp": timestamp,
             "role": "assistant", "content": answer},
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write("".join(json.dumps(entry) + "\n" for entry in entries))

        return question_id, answer_id

    def read_entry(self, entry_id: str) -> dict | None:
        """Resolve a source ID to its full stored entry, without prompt clipping.

        Older entries without IDs remain readable as context. They are not
        rewritten or assigned unstable IDs during a read.
        """
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise ValueError("A non-empty source ID is required")
        if not self.path.exists():
            return None
        found = None
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if (not isinstance(entry, dict)
                        or entry.get("role") not in {"user", "assistant"}
                        or not isinstance(entry.get("content"), str)):
                    raise ValueError("Invalid session history entry")
                if entry.get("id") == entry_id:
                    if found is not None:
                        raise ValueError("Duplicate session source ID")
                    found = entry
        return found

    def load_recent(self, max_chars: int = 12000) -> str:
        """Return the newest history within a strict prompt character budget."""
        if max_chars <= 0 or not self.path.exists():
            return ""
        entries = []
        remaining = max_chars
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            entry = json.loads(line)
            if (not isinstance(entry, dict)
                    or entry.get("role") not in {"user", "assistant"}
                    or not isinstance(entry.get("content"), str)):
                raise ValueError("Invalid session history entry")
            prefix = f"{entry['role'].upper()}: "
            separator = 2 if entries else 0
            available = remaining - separator
            if available <= len(prefix):
                break
            text = prefix + entry["content"]
            clipped = len(text) > available
            if clipped:
                text = prefix + entry["content"][:available - len(prefix)]
            entries.append(text)
            remaining -= separator + len(text)
            if clipped or remaining <= 0:
                break
        return "\n\n".join(reversed(entries))
