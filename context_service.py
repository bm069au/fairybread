import json
import os
from datetime import datetime
from pathlib import Path


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
    ) -> None:
        entry = {
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

    def append_exchange(self, question: str, answer: str) -> None:
        """Persist only the user's question and the answer Palace displayed."""
        timestamp = datetime.now().isoformat()
        entries = [
            {"timestamp": timestamp, "role": "user", "content": question},
            {"timestamp": timestamp, "role": "assistant", "content": answer},
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write("".join(json.dumps(entry) + "\n" for entry in entries))

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
