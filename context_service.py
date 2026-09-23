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

        self.path = path
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

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

        with self.path.open(
            "a",
            encoding="utf-8"
        ) as file:
            file.write(
                json.dumps(entry)
                + "\n"
            )

    def load_recent(
        self,
        max_chars: int = 12000
    ) -> str:
        if not self.path.exists():
            return ""

        lines = self.path.read_text(
            encoding="utf-8"
        ).splitlines()

        entries = []

        for line in reversed(lines):
            if not line.strip():
                continue

            entry = json.loads(line)

            text = (
                f"{entry['role'].upper()}: "
                f"{entry['content']}"
            )

            entries.append(text)

            if sum(
                len(item)
                for item in entries
            ) >= max_chars:
                break

        entries.reverse()

        return "\n\n".join(entries)
