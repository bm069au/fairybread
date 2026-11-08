import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


VALID_ROLES = {"user", "assistant"}
VALID_PHASES = {"prompt", "initial", "peer_reply", "synthesis"}


def normalize_message_entry(
    entry: dict[str, Any],
    default_session_id: str = "default",
    default_sequence: int = 1
) -> dict[str, Any]:
    if (
        not isinstance(entry, dict)
        or entry.get("role") not in VALID_ROLES
        or not isinstance(entry.get("content"), str)
    ):
        raise ValueError("Invalid session history entry")

    role = entry["role"]
    msg_id = str(entry.get("message_id") or entry.get("id") or "")
    reply_to = (
        entry.get("reply_to_message_id")
        if "reply_to_message_id" in entry
        else entry.get("reply_to")
    )
    phase = entry.get("phase")
    if phase not in VALID_PHASES:
        phase = "prompt" if role == "user" else "synthesis"

    speaker_id = entry.get("speaker_id")
    if not isinstance(speaker_id, str) or not speaker_id.strip():
        speaker_id = "user" if role == "user" else str(
            entry.get("provider_id") or "palace"
        )

    provider_id = str(entry.get("provider_id") or ("" if role == "user" else speaker_id))
    model_id = str(entry.get("model_id") or "")
    context_ids = entry.get("context_message_ids")
    if not isinstance(context_ids, list):
        context_ids = [reply_to] if isinstance(reply_to, str) and reply_to else []

    normalized = dict(entry)
    if msg_id:
        normalized["id"] = msg_id
        normalized["message_id"] = msg_id
    normalized.setdefault("session_id", default_session_id)
    normalized.setdefault("exchange_id", str(entry.get("exchange_id") or msg_id or "legacy"))
    normalized.setdefault("sequence", int(entry.get("sequence") or default_sequence))
    normalized["speaker_id"] = speaker_id
    normalized["role"] = role
    normalized["provider_id"] = provider_id
    normalized["model_id"] = model_id
    normalized["phase"] = phase
    normalized["reply_to_message_id"] = reply_to
    if reply_to and "reply_to" not in normalized:
        normalized["reply_to"] = reply_to
    normalized["context_message_ids"] = list(context_ids)
    contributors = entry.get("contributors")
    if isinstance(contributors, list):
        normalized["contributors"] = [str(c) for c in contributors if c]
    else:
        normalized["contributors"] = []
    normalized.setdefault("timestamp", "")
    return normalized


class ContextService:
    def __init__(self, path: Path | None = None, session_id: str | None = None):
        if path is None:
            local_app_data = os.environ["LOCALAPPDATA"]

            path = (
                Path(local_app_data)
                / "Palace"
                / "session_context.jsonl"
            )

        self.path = Path(path)
        self.session_id = session_id or self.path.stem

    def append(
        self,
        role: str,
        content: str,
        *,
        speaker_id: str | None = None,
        provider_id: str = "",
        model_id: str = "",
        phase: str | None = None,
        exchange_id: str | None = None,
        sequence: int = 1,
        reply_to_message_id: str | None = None,
        context_message_ids: list[str] | None = None
    ) -> str:
        message_id = str(uuid4())
        resolved_phase = phase or ("prompt" if role == "user" else "synthesis")
        resolved_speaker = speaker_id or (
            "user" if role == "user" else (provider_id or "palace")
        )
        entry: dict[str, Any] = {
            "id": message_id,
            "message_id": message_id,
            "session_id": self.session_id,
            "exchange_id": exchange_id or message_id,
            "sequence": sequence,
            "speaker_id": resolved_speaker,
            "role": role,
            "provider_id": provider_id,
            "model_id": model_id,
            "phase": resolved_phase,
            "reply_to_message_id": reply_to_message_id,
            "context_message_ids": list(context_message_ids or []),
            "timestamp": datetime.now().isoformat(),
            "content": content,
        }
        if reply_to_message_id:
            entry["reply_to"] = reply_to_message_id

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open(
            "a",
            encoding="utf-8"
        ) as file:
            file.write(
                json.dumps(entry)
                + "\n"
            )

        return message_id

    def append_exchange(
        self,
        question: str,
        answer: str,
        *,
        speaker_messages: list[dict[str, Any]] | None = None,
        contributors: list[str] | None = None
    ) -> tuple[str, str]:
        """Persist the user's question, any peer speaker messages, and the final answer."""
        timestamp = datetime.now().isoformat()
        exchange_id = str(uuid4())
        question_id = str(uuid4())
        answer_id = str(uuid4())
        resolved_contributors = list(contributors or [])
        if not resolved_contributors and speaker_messages:
            for item in speaker_messages:
                sp = str(item.get("provider_id") or item.get("speaker_id") or "")
                if sp and sp not in resolved_contributors:
                    resolved_contributors.append(sp)

        entries: list[dict[str, Any]] = [
            {
                "id": question_id,
                "message_id": question_id,
                "session_id": self.session_id,
                "exchange_id": exchange_id,
                "sequence": 1,
                "speaker_id": "user",
                "role": "user",
                "provider_id": "",
                "model_id": "",
                "phase": "prompt",
                "reply_to_message_id": None,
                "context_message_ids": [],
                "timestamp": timestamp,
                "content": question,
            }
        ]

        seq = 2
        peer_ids: list[str] = []
        for item in speaker_messages or []:
            msg_id = str(item.get("message_id") or item.get("id") or uuid4())
            peer_ids.append(msg_id)
            reply_to = item.get("reply_to_message_id") or question_id
            ctx_ids = list(item.get("context_message_ids") or [question_id])
            speaker_id = str(item.get("speaker_id") or item.get("provider_id") or "assistant")
            entries.append(
                {
                    "id": msg_id,
                    "message_id": msg_id,
                    "session_id": self.session_id,
                    "exchange_id": exchange_id,
                    "sequence": seq,
                    "speaker_id": speaker_id,
                    "role": "assistant",
                    "provider_id": str(item.get("provider_id") or speaker_id),
                    "model_id": str(item.get("model_id") or ""),
                    "phase": str(item.get("phase") or "initial"),
                    "reply_to": reply_to,
                    "reply_to_message_id": reply_to,
                    "context_message_ids": ctx_ids,
                    "timestamp": item.get("timestamp") or timestamp,
                    "content": str(item.get("content") or ""),
                }
            )
            seq += 1

        entries.append(
            {
                "id": answer_id,
                "message_id": answer_id,
                "session_id": self.session_id,
                "exchange_id": exchange_id,
                "sequence": seq,
                "speaker_id": "palace",
                "role": "assistant",
                "provider_id": "palace",
                "model_id": "",
                "phase": "synthesis",
                "reply_to": question_id,
                "reply_to_message_id": question_id,
                "context_message_ids": [question_id, *peer_ids],
                "contributors": resolved_contributors,
                "timestamp": timestamp,
                "content": answer,
            }
        )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write("".join(json.dumps(entry) + "\n" for entry in entries))

        return question_id, answer_id

    def read_messages(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        messages: list[dict[str, Any]] = []
        seq = 1
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                raw = json.loads(line)
                messages.append(
                    normalize_message_entry(
                        raw,
                        default_session_id=self.session_id,
                        default_sequence=seq,
                    )
                )
                seq += 1
        return messages

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
        seq = 1
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                raw = json.loads(line)
                entry = normalize_message_entry(
                    raw,
                    default_session_id=self.session_id,
                    default_sequence=seq,
                )
                seq += 1
                if entry.get("id") == entry_id or entry.get("message_id") == entry_id:
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
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(reversed(lines), start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            entry = normalize_message_entry(
                raw,
                default_session_id=self.session_id,
                default_sequence=idx,
            )
            speaker = entry.get("speaker_id") or entry["role"]
            label = (
                "USER"
                if entry["role"] == "user"
                else (
                    "ASSISTANT"
                    if speaker in {"assistant", "palace"}
                    else f"ASSISTANT ({speaker.upper()})"
                )
            )
            prefix = f"{label}: "
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
