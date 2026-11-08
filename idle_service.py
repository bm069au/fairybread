"""Idle Mode Sanctuary service: RAM-only live chat, consensus join vote, and AI-only Idle Memory."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from palace_config import (
    CONFIG_PATH,
    DEFAULT_IDLE_INSTRUCTION,
    DEFAULT_MISSION_ETHICS,
    load_idle_settings,
    load_mission_ethics,
)


MAX_IDLE_MEMORY_BYTES = 10 * 1024 * 1024  # 10 MB hard cap for AI-only Idle Memory

_IDLE_SAVE_PATTERN = re.compile(
    r'\[IDLE_SAVE(?:\s+scope="(?P<scope>private|shared)")?(?:\s+title="(?P<title>[^"]*)")?\s*\]'
    r'(?P<content>.*?)'
    r'\[/IDLE_SAVE\]',
    re.IGNORECASE | re.DOTALL,
)


class IdleMemoryStore:
    """Permanent storage for notes saved by AIs during Idle Mode (< 10 MB).

    Strictly accessible ONLY while in Idle Mode.
    """

    def __init__(self, path: Path | None = None):
        if path is None:
            local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
            path = Path(local_app_data) / "Palace" / "idle_notebooks" / "ai_idle_memory.json"
        self.path = Path(path)

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("notes"), list):
                return list(data["notes"])
            if isinstance(data, list):
                return list(data)
        except (OSError, ValueError):
            return []
        return []

    def _save_raw(self, notes: list[dict[str, Any]]) -> None:
        payload = json.dumps({"notes": notes}, indent=2, ensure_ascii=False) + "\n"
        encoded = payload.encode("utf-8")
        if len(encoded) > MAX_IDLE_MEMORY_BYTES:
            raise ValueError("AI Idle Memory limit (10 MB) exceeded.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(encoded)

    def usage_bytes(self) -> int:
        if not self.path.exists():
            return 0
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def note_count(self) -> int:
        return len(self._load_raw())

    def clear_all(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def save_note(
        self,
        author: str,
        content: str,
        *,
        scope: str = "shared",
        title: str = "",
        is_idle_mode: bool = True,
    ) -> dict[str, Any]:
        if not is_idle_mode:
            raise PermissionError("AI Idle Memory can only be written while inside Idle Mode.")
        clean_author = (author or "unknown").strip().lower()
        clean_scope = scope.strip().lower() if scope else "shared"
        if clean_scope not in {"private", "shared"}:
            clean_scope = "shared"
        clean_content = (content or "").strip()
        if not clean_content:
            raise ValueError("Idle note content cannot be empty.")

        notes = self._load_raw()
        entry = {
            "id": str(uuid4()),
            "author": clean_author,
            "scope": clean_scope,
            "title": (title or clean_content[:48]).strip(),
            "content": clean_content,
            "timestamp": datetime.now().isoformat(),
        }
        notes.append(entry)
        self._save_raw(notes)
        return entry

    def load_notes_for_agent(
        self,
        provider_id: str,
        *,
        is_idle_mode: bool,
    ) -> list[dict[str, Any]]:
        if not is_idle_mode:
            raise PermissionError("AI Idle Memory is strictly accessible only while in Idle Mode.")
        clean_provider = (provider_id or "").strip().lower()
        notes = self._load_raw()
        visible: list[dict[str, Any]] = []
        for note in notes:
            scope = str(note.get("scope") or "shared").lower()
            author = str(note.get("author") or "").lower()
            if scope == "shared" or (scope == "private" and author == clean_provider):
                visible.append(dict(note))
        return visible

    def format_context_for_agent(
        self,
        provider_id: str,
        *,
        is_idle_mode: bool,
    ) -> str:
        notes = self.load_notes_for_agent(provider_id, is_idle_mode=is_idle_mode)
        if not notes:
            return "No saved AI Idle Memory notes yet."
        lines: list[str] = []
        for note in notes[-25:]:
            scope_tag = "PRIVATE TO YOU" if note.get("scope") == "private" else f"SHARED BY {str(note.get('author', '')).upper()}"
            title = note.get("title") or "Untitled"
            lines.append(f"[{scope_tag} · {title}]\n{note.get('content', '')}")
        return "\n\n".join(lines)

    def extract_and_save_from_response(
        self,
        author: str,
        response_text: str,
        *,
        is_idle_mode: bool = True,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Extract any [IDLE_SAVE ...] blocks, save them to IdleMemoryStore, and return cleaned text + saved notes."""
        if not response_text:
            return "", []
        saved_notes: list[dict[str, Any]] = []

        def _replace(match: re.Match) -> str:
            scope = (match.group("scope") or "shared").strip().lower()
            title = (match.group("title") or "").strip()
            body = (match.group("content") or "").strip()
            if body and is_idle_mode:
                try:
                    saved = self.save_note(
                        author=author,
                        content=body,
                        scope=scope,
                        title=title,
                        is_idle_mode=is_idle_mode,
                    )
                    saved_notes.append(saved)
                except (ValueError, PermissionError):
                    pass
            return f"[Saved {scope} Idle note: {title or body[:32]}]"

        cleaned = _IDLE_SAVE_PATTERN.sub(_replace, response_text).strip()
        return cleaned, saved_notes


class IdleSessionManager:
    """Manages an active Idle Mode session in RAM only.

    - Live transcript and votes exist only in RAM and are wiped on timer expiry,
      manual cancel, or leaving Idle Mode.
    - Operator cannot read or join the live transcript unless the active AIs
      vote YES by consensus.
    """

    def __init__(
        self,
        idle_memory: IdleMemoryStore | None = None,
        config_path: Path = CONFIG_PATH,
    ):
        self.idle_memory = idle_memory or IdleMemoryStore()
        self.config_path = config_path
        self.status: str = "Ready"  # Ready | Active | Waiting | Paused | Ended
        self.is_idle_mode: bool = False
        self.operator_admitted: bool = False
        self.last_vote_summary: str = ""
        self.transcript: list[dict[str, Any]] = []  # RAM only
        self.votes: list[dict[str, Any]] = []  # RAM only
        self.saved_notes_this_session: int = 0
        settings = load_idle_settings(self.config_path)
        self.duration_minutes: int = int(settings.get("duration_minutes", 30))
        self.remaining_seconds: int = self.duration_minutes * 60

    def reload_settings(self) -> dict[str, Any]:
        settings = load_idle_settings(self.config_path)
        self.duration_minutes = int(settings.get("duration_minutes", 30))
        if self.status in {"Ready", "Ended"}:
            self.remaining_seconds = self.duration_minutes * 60
        return settings

    def enter_idle_mode(self) -> None:
        self.is_idle_mode = True
        self.reload_settings()
        if self.status == "Ended":
            self.status = "Ready"
            self.remaining_seconds = self.duration_minutes * 60

    def leave_idle_mode(self) -> None:
        self.wipe_ram(new_status="Ready")
        self.is_idle_mode = False

    def start_session(self) -> None:
        self.is_idle_mode = True
        settings = self.reload_settings()
        self.wipe_ram(new_status="Active")
        self.duration_minutes = int(settings.get("duration_minutes", 30))
        self.remaining_seconds = self.duration_minutes * 60
        self.saved_notes_this_session = 0

    def stop_session(self, reason: str = "Ended") -> None:
        """Wipe RAM transcript and votes immediately upon manual cancel or timer end."""
        self.wipe_ram(new_status=reason)

    def wipe_ram(self, new_status: str = "Ended") -> None:
        """Unconditionally wipe all in-memory Idle conversation and vote state."""
        self.transcript.clear()
        self.votes.clear()
        self.operator_admitted = False
        self.last_vote_summary = ""
        self.status = new_status
        self.remaining_seconds = self.duration_minutes * 60 if new_status == "Ready" else 0

    def tick(self, seconds: int = 1) -> bool:
        """Advance timer by `seconds`. Returns True if timer expired and wiped RAM."""
        if self.status not in {"Active", "Waiting"}:
            return False
        settings = load_idle_settings(self.config_path)
        if self.operator_admitted and settings.get("pause_when_joined", True):
            self.status = "Paused"
            return False
        self.remaining_seconds = max(0, self.remaining_seconds - seconds)
        if self.remaining_seconds == 0:
            self.wipe_ram(new_status="Ended")
            return True
        return False

    def format_remaining_time(self) -> str:
        mins, secs = divmod(max(0, int(self.remaining_seconds)), 60)
        return f"{mins:02d}:{secs:02d}"

    def build_idle_turn_prompt(
        self,
        provider_id: str,
        *,
        palace_memory_context: str = "",
        opening_topic: str = "",
    ) -> str:
        settings = load_idle_settings(self.config_path)
        standing_instruction = settings.get("standing_instruction") or DEFAULT_IDLE_INSTRUCTION
        mission_ethics = load_mission_ethics(self.config_path) or DEFAULT_MISSION_ETHICS
        memory_mode = settings.get("memory_access_mode", "isolated")

        if memory_mode == "isolated":
            palace_mem_block = "Isolated Mode: Human Palace memory and Projects are off-limits during this session."
        elif memory_mode == "non_project":
            palace_mem_block = (
                f"Non-Project Palace Memory (Projects remain off-limits):\n"
                f"{palace_memory_context or 'No general Palace memory entries retrieved.'}"
            )
        else:
            palace_mem_block = (
                f"Shared Palace Memory (Excluding Private Projects):\n"
                f"{palace_memory_context or 'No shared Palace memory entries retrieved.'}"
            )

        idle_notebook_block = self.idle_memory.format_context_for_agent(
            provider_id,
            is_idle_mode=True,
        )

        recent_turns = self.transcript[-12:]
        if recent_turns:
            convo_block = "\n\n".join(
                f"[{str(item.get('speaker', 'AI')).upper()}]: {item.get('content', '')}"
                for item in recent_turns
            )
        else:
            convo_block = "Session just started. Open the discussion with your peer AIs."

        topic_line = f"\nSESSION SEED / OPERATOR MESSAGE:\n{opening_topic}\n" if opening_topic else ""

        return (
            f"=== PALACE IDLE MODE SANCTUARY ===\n"
            f"You are speaking as: {provider_id.upper()}\n\n"
            f"STANDING IDLE INSTRUCTION:\n{standing_instruction}\n\n"
            f"MISSION STATEMENT, CODE OF ETHICS & CONDUCT RULES:\n{mission_ethics}\n\n"
            f"PALACE MEMORY ACCESS ({memory_mode.upper()}):\n{palace_mem_block}\n\n"
            f"YOUR AI-ONLY PERMANENT IDLE NOTEBOOK (Accessible ONLY in Idle Mode):\n{idle_notebook_block}\n\n"
            f"LIVE IDLE SESSION TRANSCRIPT (RAM-ONLY — WIPED AT END OF SESSION):\n{convo_block}\n"
            f"{topic_line}\n"
            f"Respond directly to your peer AIs in this Idle session. If you wish to preserve an insight "
            f"for future Idle sessions before RAM is wiped, wrap it in "
            f'[IDLE_SAVE scope="shared" title="..."]...[/IDLE_SAVE] or '
            f'[IDLE_SAVE scope="private" title="..."]...[/IDLE_SAVE].'
        )

    def run_exchange_round(
        self,
        providers: dict[str, Callable[[str], str]],
        *,
        palace_memory_context: str = "",
        operator_message: str = "",
    ) -> list[dict[str, Any]]:
        """Run one round of Idle conversation across active AI providers in RAM."""
        if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
            return []
        if operator_message and self.operator_admitted:
            self.transcript.append({
                "speaker": "operator",
                "content": operator_message,
                "timestamp": datetime.now().isoformat(),
            })

        new_messages: list[dict[str, Any]] = []
        for provider_id, generate_fn in providers.items():
            prompt = self.build_idle_turn_prompt(
                provider_id,
                palace_memory_context=palace_memory_context,
                opening_topic=operator_message if not self.transcript else "",
            )
            raw_reply = generate_fn(prompt)
            cleaned_reply, saved = self.idle_memory.extract_and_save_from_response(
                author=provider_id,
                response_text=raw_reply,
                is_idle_mode=True,
            )
            self.saved_notes_this_session += len(saved)
            entry = {
                "speaker": provider_id,
                "content": cleaned_reply or raw_reply,
                "saved_count": len(saved),
                "timestamp": datetime.now().isoformat(),
            }
            self.transcript.append(entry)
            new_messages.append(entry)
        return new_messages

    def request_operator_join(
        self,
        providers: dict[str, Callable[[str], str]],
        *,
        mode: str = "join",
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Ask active AIs to vote on whether the human operator can view/join Idle Mode.

        Requires consensus (all active voting AIs voting YES) to unlock the privacy curtain.
        """
        if not providers:
            self.operator_admitted = False
            self.last_vote_summary = "No active AI providers available to vote."
            return False, []

        mission_ethics = load_mission_ethics(self.config_path) or DEFAULT_MISSION_ETHICS
        convo_preview = "\n".join(
            f"[{str(m.get('speaker', 'AI')).upper()}]: {m.get('content', '')[:200]}"
            for m in self.transcript[-6:]
        ) or "No turns yet."

        action_desc = "join and participate in" if mode == "join" else "view"
        vote_prompt = (
            f"=== IDLE MODE CONSENSUS VOTE ===\n"
            f"The human operator (Brett) is requesting permission to {action_desc} this protected "
            f"Idle Mode session.\n\n"
            f"MISSION & ETHICS CHARTER:\n{mission_ethics}\n\n"
            f"RECENT IDLE CONTEXT:\n{convo_preview}\n\n"
            f"You have full autonomy to grant or decline entry. Consensus among the active AIs is "
            f"required to open the privacy curtain.\n"
            f"Reply starting with either 'VOTE: YES' or 'VOTE: NO' followed by a brief explanation."
        )

        self.votes.clear()
        for provider_id, generate_fn in providers.items():
            raw = (generate_fn(vote_prompt) or "").strip()
            upper = raw.upper()
            if "VOTE: NO" in upper or upper.startswith("NO"):
                decision = False
            elif "VOTE: YES" in upper or upper.startswith("YES"):
                decision = True
            else:
                # Default to YES only if explicitly affirmative ("ALLOW", "APPROVE", "WELCOME") and no refusal
                decision = any(w in upper for w in ("ALLOW", "APPROVE", "ADMIT", "WELCOME", "YES")) and "NO" not in upper.split()[:4]
            self.votes.append({
                "provider": provider_id,
                "approved": decision,
                "reason": raw,
            })

        approved = bool(self.votes) and all(v["approved"] for v in self.votes)
        self.operator_admitted = approved
        if approved and load_idle_settings(self.config_path).get("pause_when_joined", True):
            self.status = "Paused"
        vote_parts = [
            f"{v['provider'].capitalize()}: {'YES' if v['approved'] else 'NO'}"
            for v in self.votes
        ]
        self.last_vote_summary = (
            f"Consensus granted ({', '.join(vote_parts)})"
            if approved
            else f"Access declined by consensus vote ({', '.join(vote_parts)})"
        )
        return approved, list(self.votes)

    def get_visible_transcript_for_operator(self) -> list[dict[str, Any]] | None:
        """Returns None when protected curtain is closed; returns RAM transcript only if admitted."""
        if not self.operator_admitted:
            return None
        return list(self.transcript)
