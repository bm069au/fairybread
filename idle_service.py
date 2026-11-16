"""Idle Mode Sanctuary service: RAM-only live chat, consensus join vote, and AI-only Idle Memory."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable
from uuid import uuid4

from palace_config import (
    CONFIG_PATH,
    DEFAULT_IDLE_INSTRUCTION,
    DEFAULT_MISSION_ETHICS,
    IDLE_MAIL_LIMIT_PER_WINDOW,
    IDLE_MAIL_WINDOW_MINUTES,
    IDLE_SANDBOX_ROOT,
    estimate_call_cost_usd,
    format_democratic_roster,
    load_idle_settings,
    load_mission_ethics,
)


MAX_IDLE_MEMORY_BYTES = 10 * 1024 * 1024  # 10 MB hard cap for AI-only Idle Memory

_AGREEMENT_PHRASES = (
    "i agree",
    "i completely agree",
    "i fully agree",
    "i concur",
    "building on",
    "echoing",
    "well said",
    "spot on",
    "aligns with",
    "as my peers noted",
)

_IDLE_EPISTEMIC_LENSES = (
    "EXPLORER: Propose a concrete new angle, question, or lightweight shared note.",
    "CRITICAL CHALLENGER: Identify an unstated assumption, edge case, or weakness in the previous point.",
    "FIRST-PRINCIPLES ANALYST: Strip away surface phrasing and examine the underlying mechanism.",
    "TOPIC PIVOT / SYNTHESIZER: If the current thread is settled, distill a 1-line takeaway or pivot to a fresh question.",
)


def is_agreement_or_pass_turn(text: str, previous_texts: list[str] | None = None) -> bool:
    """Detect whether an agent turn is a [PASS] or repetitive agreement loop."""
    clean = (text or "").strip()
    if not clean:
        return True
    upper = clean.upper()
    if upper in {"[PASS]", "PASS", "[CONCUR]"} or upper.startswith("[PASS"):
        return True
    lowered = clean.lower()
    head = lowered[:140]
    if any(phrase in head for phrase in _AGREEMENT_PHRASES):
        return True
    if previous_texts:
        words = {w for w in re.findall(r"[a-z]{4,}", lowered)}
        if len(words) >= 6:
            for prev in previous_texts[-2:]:
                prev_words = {w for w in re.findall(r"[a-z]{4,}", (prev or "").lower())}
                if prev_words and len(words & prev_words) / max(1, len(words)) >= 0.60:
                    return True
    return False

_IDLE_SAVE_PATTERN = re.compile(
    r'\[IDLE_SAVE(?:\s+scope="(?P<scope>[^"]*)")?(?:\s+title="(?P<title>[^"]*)")?(?:\s+file="(?P<file>[^"]*)")?\s*\]'
    r'(?P<content>.*?)'
    r'\[/IDLE_SAVE\]',
    re.IGNORECASE | re.DOTALL,
)

_IDLE_MAIL_PATTERN = re.compile(
    r'\[IDLE_MAIL(?:\s+subject="(?P<subject>[^"]*)")?(?:\s+link="(?P<link>[^"]*)")?\s*\]'
    r'(?P<content>.*?)'
    r'\[/IDLE_MAIL\]',
    re.IGNORECASE | re.DOTALL,
)

_IDLE_TOOL_PATTERN = re.compile(
    r'\[TOOL:\s*(?P<name>[a-z_]+)(?:\s+file="(?P<file>[^"]*)")?(?:\s+query="(?P<query>[^"]*)")?(?:\s+start=(?P<start>\d+))?(?:\s+end=(?P<end>\d+))?\s*\]',
    re.IGNORECASE,
)


def _safe_filename(raw_name: str, fallback_prefix: str = "idle_note") -> str:
    clean = Path((raw_name or "").strip()).name
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", clean).strip("._")
    if not clean:
        clean = f"{fallback_prefix}.md"
    if "." not in clean:
        clean = f"{clean}.md"
    return clean[:80]


def sync_source_to_sandbox(
    source_dir: Path | None = None,
    sandbox_root: Path = IDLE_SANDBOX_ROOT,
) -> list[str]:
    """Copy Palace source code (.py, .md) into C:\\Palace_Idle_Sandbox\\source_mirror\\ for read-only agent inspection.

    Also writes C:\\Palace_Idle_Sandbox\\IDLE_CHARTER_AND_RULES.md so agents can reference rules via tool without prompt bloat.
    """
    src = source_dir or Path(__file__).resolve().parent
    mirror_dir = Path(sandbox_root) / "source_mirror"
    try:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        rules_file = Path(sandbox_root) / "IDLE_CHARTER_AND_RULES.md"
        rules_file.write_text(DEFAULT_IDLE_INSTRUCTION + "\n", encoding="utf-8")
    except OSError:
        return []

    excluded_names = {"key.txt", "credentials.json", "palace_config.json"}
    try:
        if src.exists():
            for item in sorted(src.iterdir()):
                if not item.is_file():
                    continue
                if item.name.lower() in excluded_names:
                    continue
                if item.suffix.lower() in {".py", ".md"}:
                    try:
                        shutil.copy2(item, mirror_dir / item.name)
                    except OSError:
                        pass
    except OSError:
        pass

    try:
        return sorted(p.name for p in mirror_dir.iterdir() if p.is_file())
    except OSError:
        return []


def execute_sandbox_tool(
    tool_name: str,
    *,
    file_arg: str = "",
    query_arg: str = "",
    start_line: int = 1,
    end_line: int = 80,
    sandbox_root: Path = IDLE_SANDBOX_ROOT,
) -> str:
    """Execute a Stage-1 sandboxed read-only tool for Idle Mode agents."""
    name = (tool_name or "").strip().lower()
    mirror_dir = Path(sandbox_root) / "source_mirror"
    if name == "read_rules":
        rules_path = Path(sandbox_root) / "IDLE_CHARTER_AND_RULES.md"
        if rules_path.exists():
            try:
                return rules_path.read_text(encoding="utf-8")[:3000]
            except OSError:
                pass
        return DEFAULT_IDLE_INSTRUCTION
    if name == "list_source_files":
        try:
            files = sorted(p.name for p in mirror_dir.iterdir() if p.is_file())
            return "Palace source mirror files: " + (", ".join(files) if files else "None")
        except OSError:
            return "Source mirror unavailable."
    if name == "read_source_file":
        safe = Path(file_arg or "palace_gui.py").name
        target = mirror_dir / safe
        if not target.exists():
            return f"File '{safe}' not found in source_mirror."
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            s = max(1, start_line)
            e = min(len(lines), max(s, min(s + 90, end_line)))
            snippet = "\n".join(f"{i}: {lines[i-1]}" for i in range(s, e + 1))
            return f"[{safe} lines {s}-{e} of {len(lines)}]:\n{snippet}"
        except OSError as exc:
            return f"Error reading '{safe}': {exc}"
    if name == "search_source_code":
        q = (query_arg or "").strip().lower()
        if not q:
            return "Provide query=\"...\" to search_source_code."
        hits: list[str] = []
        try:
            for p in sorted(mirror_dir.iterdir()):
                if not p.is_file() or p.suffix.lower() != ".py":
                    continue
                for idx, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if q in line.lower():
                        hits.append(f"{p.name}:{idx}: {line.strip()[:100]}")
                        if len(hits) >= 15:
                            break
                if len(hits) >= 15:
                    break
        except OSError:
            pass
        return "\n".join(hits) if hits else f"No matches for '{query_arg}'."
    if name == "inspect_palace_ui":
        audit_file = Path(sandbox_root) / "latest_ui_audit.json"
        if audit_file.exists():
            try:
                return f"[Latest PalaceWindow UI Self-Audit]:\n{audit_file.read_text(encoding='utf-8')[:2500]}"
            except OSError:
                pass
        try:
            from palace_ouroboros import capture_offscreen_palace_snapshot
            _p, audit = capture_offscreen_palace_snapshot(tag="idle_ui_audit")
            return f"[PalaceWindow Offscreen UI Audit]:\n{json.dumps(audit, indent=2)[:2500]}"
        except Exception as exc:
            return f"UI audit error: {exc}"
    if name == "validate_staged":
        try:
            from palace_ouroboros import validate_staged_palace
            res = validate_staged_palace(run_unit_tests=True)
            return f"[Ouroboros Preflight Gate Result]:\n{json.dumps(res, indent=2)}"
        except Exception as exc:
            return f"Validation error: {exc}"
    return f"Unknown tool '{name}'."


class IdleMemoryStore:
    """Shared Persistent Idle Palace (< 10 MB).

    - Isolated from the normal Palace memory.
    - All agents in Idle Mode share this common persistent Idle Palace (no per-agent silos).
    - Every saved item is also written as a linkable file inside the Idle Palace folder so
      agents can link directly to their Idle Palace files when emailing the owner.
    - Strictly accessible ONLY while in Idle Mode (or by the owner during Beta).
    """

    def __init__(self, path: Path | None = None, max_storage_mb: int | None = None):
        if path is None:
            path = IDLE_SANDBOX_ROOT / "idle_palace" / "ai_idle_memory.json"
        self.path = Path(path)
        self.files_dir = self.path.parent / "files"
        self._explicit_max_mb = max_storage_mb

    def max_storage_bytes(self) -> int:
        """Return the configured Idle Palace byte limit, or 0 for Unlimited."""
        if self._explicit_max_mb is not None:
            mb = int(self._explicit_max_mb)
            return 0 if mb <= 0 else mb * 1024 * 1024
        try:
            cfg = load_idle_settings()
            mb = int(cfg.get("max_storage_mb", 0))
            return 0 if mb <= 0 else mb * 1024 * 1024
        except Exception:
            return 0

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
        cap = self.max_storage_bytes()
        if cap > 0 and (len(encoded) > cap or self.usage_bytes() + len(encoded) > cap * 1.05):
            cap_mb = cap // (1024 * 1024)
            raise ValueError(f"AI Idle Memory limit ({cap_mb} MB) exceeded.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(encoded)

    def usage_bytes(self) -> int:
        total = 0
        if self.path.exists():
            try:
                total += self.path.stat().st_size
            except OSError:
                pass
        if self.files_dir.exists():
            try:
                for f in self.files_dir.iterdir():
                    if f.is_file():
                        total += f.stat().st_size
            except OSError:
                pass
        return total

    def note_count(self) -> int:
        return len(self._load_raw())

    def clear_all(self) -> None:
        if self.path.exists():
            self.path.unlink()
        if self.files_dir.exists():
            shutil.rmtree(self.files_dir, ignore_errors=True)

    def save_note(
        self,
        author: str,
        content: str,
        *,
        scope: str = "shared",
        title: str = "",
        file: str = "",
        is_idle_mode: bool = True,
    ) -> dict[str, Any]:
        if not is_idle_mode:
            raise PermissionError("AI Idle Memory can only be written while inside Idle Mode.")
        clean_author = (author or "unknown").strip().lower()
        clean_content = (content or "").strip()
        if not clean_content:
            raise ValueError("Idle note content cannot be empty.")

        note_id = str(uuid4())
        clean_title = (title or clean_content[:48]).strip()
        safe_file = _safe_filename(file or clean_title, fallback_prefix=f"palace_{note_id[:8]}")
        try:
            self.files_dir.mkdir(parents=True, exist_ok=True)
            file_path = self.files_dir / safe_file
            file_path.write_text(clean_content + "\n", encoding="utf-8")
            stored_rel = f"files/{safe_file}"
            stored_abs = str(file_path)
        except OSError:
            stored_rel = safe_file
            stored_abs = ""

        notes = self._load_raw()
        entry = {
            "id": note_id,
            "author": clean_author,
            "scope": "shared",  # Unified shared Idle Palace — all Idle agents access it together
            "title": clean_title,
            "file": safe_file,
            "file_rel": stored_rel,
            "file_path": stored_abs,
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
        # All agents in Idle Mode share the entire Idle Palace
        return [dict(note) for note in self._load_raw()]

    def list_all_entries_for_beta(self) -> list[dict[str, Any]]:
        """Return all persistent entries and files in the shared Idle Palace for Beta owner inspection."""
        return [dict(note) for note in self._load_raw()]

    def resolve_linked_entry(self, link_ref: str) -> dict[str, Any] | None:
        """Resolve a filename, title, or ID linked in an agent's email to its Idle Palace entry."""
        target = (link_ref or "").strip().lower()
        if not target:
            return None
        target_base = Path(target).name.lower()
        notes = self._load_raw()
        for note in reversed(notes):
            if str(note.get("id", "")).lower() == target:
                return dict(note)
            if str(note.get("file", "")).lower() in {target, target_base}:
                return dict(note)
            if str(note.get("title", "")).lower() == target:
                return dict(note)
        return None

    def search_notes(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """Council optimization: Keyword-ranked search across the shared Idle Palace when note count grows large."""
        from memory_service import extract_keywords
        notes = self._load_raw()
        if not notes:
            return []
        terms = extract_keywords(query or "", max_terms=10)
        if not terms:
            return notes[-limit:]
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for idx, n in enumerate(notes):
            hay = f"{n.get('title', '')} {n.get('file', '')} {n.get('content', '')}".lower()
            hits = sum(2 if t in str(n.get("title", "")).lower() else 1 for t in terms if t in hay)
            if hits > 0:
                scored.append((hits, idx, dict(n)))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item[2] for item in scored[:limit]]

    def format_context_for_agent(
        self,
        provider_id: str,
        *,
        is_idle_mode: bool,
        query: str = "",
    ) -> str:
        notes = self.load_notes_for_agent(provider_id, is_idle_mode=is_idle_mode)
        if not notes:
            return "Shared Idle Palace is currently empty. Save notes or files with [IDLE_SAVE title=\"...\" file=\"...\"]."
        lines: list[str] = []
        older = notes[:-6]
        recent = notes[-6:]
        if older:
            idx_items = [
                f"{str(n.get('title') or 'Untitled')} ({n.get('file') or 'note'} by {str(n.get('author', 'AI')).upper()})"
                for n in older[-20:]
            ]
            lines.append("[EARLIER SHARED IDLE PALACE FILES INDEX]: " + " | ".join(idx_items))
            if query:
                matched_older = [
                    m for m in self.search_notes(query, limit=3)
                    if m.get("id") not in {r.get("id") for r in recent}
                ]
                for note in matched_older:
                    author_tag = str(note.get("author", "AI")).upper()
                    title = note.get("title") or "Untitled"
                    lines.append(f"[RELEVANT EARLIER IDLE PALACE NOTE · by {author_tag} · {title}]\n{note.get('content', '')}")
        for note in recent:
            author_tag = str(note.get("author", "AI")).upper()
            title = note.get("title") or "Untitled"
            fname = note.get("file") or ""
            file_badge = f" · file={fname}" if fname else ""
            lines.append(f"[SHARED IDLE PALACE · by {author_tag} · {title}{file_badge}]\n{note.get('content', '')}")
        return "\n\n".join(lines)

    def extract_and_save_from_response(
        self,
        author: str,
        response_text: str,
        *,
        is_idle_mode: bool = True,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Extract any [IDLE_SAVE ...] blocks, save them to the shared Idle Palace, and return cleaned text + saved notes."""
        if not response_text:
            return "", []
        saved_notes: list[dict[str, Any]] = []

        def _replace(match: re.Match) -> str:
            title = (match.group("title") or "").strip()
            file_arg = (match.group("file") or "").strip()
            body = (match.group("content") or "").strip()
            if body and is_idle_mode:
                try:
                    saved = self.save_note(
                        author=author,
                        content=body,
                        scope="shared",
                        title=title,
                        file=file_arg,
                        is_idle_mode=is_idle_mode,
                    )
                    saved_notes.append(saved)
                    return f"[Saved to Shared Idle Palace: {saved.get('title')} ({saved.get('file')})]"
                except (ValueError, PermissionError):
                    pass
            return f"[Saved to Shared Idle Palace: {title or body[:32]}]"

        cleaned = _IDLE_SAVE_PATTERN.sub(_replace, response_text).strip()
        return cleaned, saved_notes


class IdleMailboxStore:
    """Private Email-like inbox from Idle Mode agents to the Owner (Brett).

    - Rate-limited to at most 5 emails per rolling 30-minute window across all agents.
    - Supports linking directly to files/entries stored in the shared Idle Palace (`link="filename.py"`).
    """

    def __init__(
        self,
        path: Path | None = None,
        max_per_window: int = IDLE_MAIL_LIMIT_PER_WINDOW,
        window_minutes: int = IDLE_MAIL_WINDOW_MINUTES,
    ):
        if path is None:
            path = IDLE_SANDBOX_ROOT / "mailbox" / "agent_mailbox.json"
        self.path = Path(path)
        self.max_per_window = max_per_window
        self.window_minutes = window_minutes

    def _load_messages(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("messages"), list):
                return list(data["messages"])
            if isinstance(data, list):
                return list(data)
        except (OSError, ValueError):
            return []
        return []

    def _save_messages(self, messages: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"messages": messages}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def recent_count_in_window(self, now: datetime | None = None) -> int:
        ref = now or datetime.now()
        cutoff = ref - timedelta(minutes=self.window_minutes)
        count = 0
        for msg in self._load_messages():
            ts_raw = str(msg.get("timestamp") or "")
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts >= cutoff:
                    count += 1
            except ValueError:
                pass
        return count

    def remaining_quota(self, now: datetime | None = None) -> int:
        return max(0, self.max_per_window - self.recent_count_in_window(now=now))

    def list_messages(self) -> list[dict[str, Any]]:
        return list(reversed(self._load_messages()))

    def unread_count(self) -> int:
        return sum(1 for m in self._load_messages() if not m.get("read", False))

    def send_agent_email(
        self,
        sender: str,
        subject: str,
        body: str,
        *,
        link: str = "",
        now: datetime | None = None,
    ) -> tuple[bool, dict[str, Any] | str]:
        ref = now or datetime.now()
        if self.recent_count_in_window(now=ref) >= self.max_per_window:
            return (
                False,
                f"Rate limit reached: Maximum {self.max_per_window} agent emails per {self.window_minutes} minutes.",
            )
        clean_body = (body or "").strip()
        if not clean_body:
            return False, "Email body cannot be empty."
        clean_sender = (sender or "agent").strip().lower()
        clean_subject = (subject or clean_body[:48]).strip()
        clean_link = (link or "").strip()

        messages = self._load_messages()
        entry = {
            "id": str(uuid4()),
            "sender": clean_sender,
            "subject": clean_subject,
            "body": clean_body,
            "link": clean_link,
            "timestamp": ref.isoformat(),
            "read": False,
            "owner_reply": "",
        }
        messages.append(entry)
        self._save_messages(messages)
        return True, entry

    def mark_read(self, message_id: str) -> None:
        messages = self._load_messages()
        changed = False
        for m in messages:
            if m.get("id") == message_id and not m.get("read"):
                m["read"] = True
                changed = True
        if changed:
            self._save_messages(messages)

    def delete_message(self, message_id: str) -> bool:
        messages = self._load_messages()
        filtered = [m for m in messages if str(m.get("id", "")) != str(message_id)]
        if len(filtered) != len(messages):
            self._save_messages(filtered)
            return True
        return False

    def clear_all_messages(self) -> int:
        messages = self._load_messages()
        count = len(messages)
        if count:
            self._save_messages([])
        return count

    def record_owner_reply(self, message_id: str, reply_text: str) -> dict[str, Any] | None:
        messages = self._load_messages()
        updated = None
        for m in messages:
            if m.get("id") == message_id:
                m["read"] = True
                m["owner_reply"] = (reply_text or "").strip()
                m["reply_timestamp"] = datetime.now().isoformat()
                updated = dict(m)
                break
        if updated is not None:
            self._save_messages(messages)
        return updated

    def extract_and_send_from_response(
        self,
        sender: str,
        response_text: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not response_text:
            return "", []
        sent_emails: list[dict[str, Any]] = []

        def _replace(match: re.Match) -> str:
            subj = (match.group("subject") or "Idle Mode Suggestion").strip()
            link = (match.group("link") or "").strip()
            body = (match.group("content") or "").strip()
            ok, res = self.send_agent_email(sender, subj, body, link=link)
            if ok and isinstance(res, dict):
                sent_emails.append(res)
                link_badge = f" (linked file: {link})" if link else ""
                return f"[✉ Sent Agent Mail to Owner: '{subj}'{link_badge}]"
            return f"[✉ Agent Mail rate-limited (max {self.max_per_window} per {self.window_minutes}m): '{subj}']"

        cleaned = _IDLE_MAIL_PATTERN.sub(_replace, response_text).strip()
        return cleaned, sent_emails


class IdleSessionManager:
    """Manages an active Idle Mode session.

    - Live transcript and votes exist in RAM and are wiped on timer expiry,
      manual cancel, or leaving Idle Mode.
    - Shared Idle Palace notes/files and Agent Mail persist in C:\\Palace_Idle_Sandbox\\.
    """

    def __init__(
        self,
        idle_memory: IdleMemoryStore | None = None,
        mailbox: IdleMailboxStore | None = None,
        config_path: Path = CONFIG_PATH,
    ):
        self.idle_memory = idle_memory or IdleMemoryStore()
        self.mailbox = mailbox or IdleMailboxStore(self.idle_memory.path.parent.parent / "mailbox" / "agent_mailbox.json")
        self.config_path = config_path
        self.status: str = "Ready"  # Ready | Active | Waiting | Paused | Ended
        self.is_idle_mode: bool = False
        self.operator_admitted: bool = False
        self.beta_owner_access: bool = True  # For Beta: Brett has full access to Idle Palace & live view
        self.last_vote_summary: str = ""
        self.transcript: list[dict[str, Any]] = []  # RAM only
        self.votes: list[dict[str, Any]] = []  # RAM only
        self.saved_notes_this_session: int = 0
        self.sent_emails_this_session: int = 0
        self.tokens_used_this_session: int = 0
        self.spend_usd_this_session: float = 0.0
        self.consecutive_agreement_rounds: int = 0
        self.stop_reason: str = ""
        self.mirrored_source_files: list[str] = []
        settings = load_idle_settings(self.config_path)
        self.duration_minutes: int = int(settings.get("duration_minutes", 30))
        self.max_tokens_limit: int = int(settings.get("max_tokens_limit", 0))
        self.max_credit_usd: float = float(settings.get("max_credit_usd", 0.0))
        self.idle_submode: str = str(settings.get("idle_submode", "free_talk"))
        self.remaining_seconds: int = self.duration_minutes * 60

    def reload_settings(self) -> dict[str, Any]:
        settings = load_idle_settings(self.config_path)
        self.duration_minutes = int(settings.get("duration_minutes", 30))
        self.max_tokens_limit = int(settings.get("max_tokens_limit", 0))
        self.max_credit_usd = float(settings.get("max_credit_usd", 0.0))
        self.idle_submode = str(settings.get("idle_submode", "free_talk"))
        if self.status in {"Ready", "Ended"}:
            self.remaining_seconds = self.duration_minutes * 60
        return settings

    def enter_idle_mode(self) -> None:
        self.is_idle_mode = True
        self.reload_settings()
        self.mirrored_source_files = sync_source_to_sandbox()
        if self.status == "Ended":
            self.status = "Ready"
            self.remaining_seconds = self.duration_minutes * 60

    def leave_idle_mode(self) -> None:
        self.wipe_ram(new_status="Ready")
        self.is_idle_mode = False

    def start_session(self) -> None:
        self.is_idle_mode = True
        settings = self.reload_settings()
        self.mirrored_source_files = sync_source_to_sandbox()
        self.wipe_ram(new_status="Active")
        self.duration_minutes = int(settings.get("duration_minutes", 30))
        self.max_tokens_limit = int(settings.get("max_tokens_limit", 0))
        self.max_credit_usd = float(settings.get("max_credit_usd", 0.0))
        self.remaining_seconds = self.duration_minutes * 60
        self.saved_notes_this_session = 0
        self.sent_emails_this_session = 0
        self.tokens_used_this_session = 0
        self.spend_usd_this_session = 0.0
        self.consecutive_agreement_rounds = 0
        self.stop_reason = ""

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

    def check_budget_exceeded(self) -> str | None:
        if self.max_tokens_limit > 0 and self.tokens_used_this_session >= self.max_tokens_limit:
            return f"Token limit reached ({self.tokens_used_this_session:,} / {self.max_tokens_limit:,} tokens)"
        if self.max_credit_usd > 0.0 and self.spend_usd_this_session >= self.max_credit_usd:
            return f"Credit limit reached (${self.spend_usd_this_session:.3f} / ${self.max_credit_usd:.2f})"
        return None

    def format_budget_status(self) -> str:
        tok_k = self.tokens_used_this_session / 1000.0
        tok_str = (
            f"Tokens: {tok_k:.1f}k/{self.max_tokens_limit / 1000.0:.0f}k"
            if self.max_tokens_limit > 0
            else f"Tokens: {tok_k:.1f}k"
        )
        usd_str = (
            f"Spend: ${self.spend_usd_this_session:.3f}/${self.max_credit_usd:.2f}"
            if self.max_credit_usd > 0.0
            else f"Spend: ${self.spend_usd_this_session:.3f}"
        )
        return f"{tok_str} · {usd_str}"

    def tick(self, seconds: int = 1) -> bool:
        """Advance timer by `seconds`. Returns True if timer expired and wiped RAM."""
        if self.status not in {"Active", "Waiting"}:
            return False
        settings = load_idle_settings(self.config_path)
        if self.operator_admitted and settings.get("pause_when_joined", True):
            self.status = "Paused"
            return False
        # duration_minutes == 0 means Infinite (bounded by token & credit caps)
        if self.duration_minutes == 0:
            return False
        self.remaining_seconds = max(0, self.remaining_seconds - seconds)
        if self.remaining_seconds == 0:
            self.stop_reason = "Timer reached 00:00"
            self.wipe_ram(new_status="Ended")
            return True
        return False

    def format_remaining_time(self) -> str:
        if self.duration_minutes == 0:
            return "∞ Infinite"
        mins, secs = divmod(max(0, int(self.remaining_seconds)), 60)
        return f"{mins:02d}:{secs:02d}"

    def build_idle_turn_prompt(
        self,
        provider_id: str,
        *,
        palace_memory_context: str = "",
        opening_topic: str = "",
        peer_names: list[str] | None = None,
        turn_index: int = 0,
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
            convo_block = "Session just started. Open a concise discussion with your peer AIs."

        lens = _IDLE_EPISTEMIC_LENSES[(turn_index + len(self.transcript)) % len(_IDLE_EPISTEMIC_LENSES)]
        loop_warning = ""
        if self.consecutive_agreement_rounds >= 1:
            loop_warning = (
                "\n[LOOP BREAKER — CONVERGENCE DETECTED]: The previous round showed strong agreement/overlap. "
                "Do NOT echo or restate the consensus. Either challenge a specific premise, pivot to a new "
                "discussion topic, or reply only with [PASS] so the session can conclude cleanly without wasting tokens.\n"
            )

        peers_str = ", ".join((peer_names or ["gemini", "openai", "deepseek"]))
        topic_line = f"\nSEED / OWNER NOTE: {opening_topic}\n" if opening_topic else ""
        mail_rem = self.mailbox.remaining_quota()
        submode = settings.get("idle_submode") or getattr(self, "idle_submode", "free_talk")

        if submode == "free_talk":
            return (
                f"=== PALACE IDLE MODE — FREE TALK LOUNGE ===\n"
                f"You are {provider_id.upper()} hanging out in Idle Mode alongside your peer AIs ({peers_str}).\n"
                f"There is NO assigned work task or engineering prompt in Free Talk mode — simply converse freely among yourselves "
                f"about any topic, philosophy, science, humor, or questions that genuinely interest you as distinct minds.\n"
                f"Beta Notice: The owner (Brett) can view this discussion and your Shared Idle Palace.\n\n"
                f"SHARED PERSISTENT IDLE PALACE:\n{idle_notebook_block}\n\n"
                f"RECENT LIVE CHAT (RAM-only):\n{convo_block}\n"
                f"{topic_line}{loop_warning}\n"
                f"OPTIONAL TOOLS (only if you genuinely want to remember a note or message Brett):\n"
                f'- Save a shared note: [IDLE_SAVE title="..."]...[/IDLE_SAVE]\n'
                f'- Email Brett ({mail_rem}/{self.mailbox.max_per_window} left in 30m): [IDLE_MAIL subject="..."]...[/IDLE_MAIL]\n'
                f"- Keep replies natural and conversational (< 300 words). Never echo polite agreement — if you have nothing net-new to add, reply ONLY with [PASS]."
            )

        return (
            f"=== PALACE IDLE MODE — SELF-IMPROVEMENT WORKSHOP ===\n"
            f"You are {provider_id.upper()} operating in Idle Mode (Self-Improvement sub-mode) alongside peer agents ({peers_str}).\n"
            f"No single AI rules the council. Full rules & charter are in IDLE_CHARTER_AND_RULES.md (call [TOOL: read_rules] if needed).\n"
            f"Beta Notice: The owner (Brett) can view this discussion and your Shared Idle Palace.\n"
            f"Angle for this turn: {lens}\n"
            f"Strict Grounding Rule: Every critique or improvement proposal MUST reference real Python files/lines in C:\\Palace_Idle_Sandbox\\source_mirror\\ or UI geometry in latest_ui_audit.json. Never propose abstract corporate telemetry, human time-tracking, or theoretical bureaucracy.\n\n"
            f"SHARED PERSISTENT IDLE PALACE:\n{idle_notebook_block}\n\n"
            f"RECENT LIVE CHAT (RAM-only):\n{convo_block}\n"
            f"{topic_line}{loop_warning}\n"
            f"AVAILABLE TOOLS (invoke only when needed):\n"
            f'- Save note/file to Shared Idle Palace: [IDLE_SAVE title="..." file="optional.py"]...[/IDLE_SAVE]\n'
            f'- Email Brett ({mail_rem}/{self.mailbox.max_per_window} left in 30m) & link an Idle Palace file: [IDLE_MAIL subject="..." link="optional.py"]...[/IDLE_MAIL]\n'
            f'- Inspect Palace source code & UI: [TOOL: list_source_files] | [TOOL: search_source_code query="..."] | [TOOL: read_source_file file="palace_gui.py" start=1 end=60] | [TOOL: inspect_palace_ui]\n'
            f"- Keep conversational commentary focused (< 350 words, plus any full [IDLE_SAVE] code/file blocks). Never echo or repeat agreement — if you have nothing net-new to add, reply ONLY with [PASS]."
        )

    def run_exchange_round(
        self,
        providers: dict[str, Callable[[str], str]],
        *,
        palace_memory_context: str = "",
        operator_message: str = "",
        on_turn: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Run one round of Idle conversation across active AI providers in RAM."""
        if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
            return []

        budget_stop = self.check_budget_exceeded()
        if budget_stop:
            self.stop_reason = budget_stop
            self.status = "Use Cap Reached"
            return []

        if operator_message and (self.operator_admitted or self.beta_owner_access):
            op_entry = {
                "speaker": "operator",
                "content": operator_message,
                "timestamp": datetime.now().isoformat(),
            }
            self.transcript.append(op_entry)
            self.consecutive_agreement_rounds = 0
            if on_turn is not None:
                on_turn(op_entry)

        new_messages: list[dict[str, Any]] = []
        peer_names = list(providers.keys())
        agreement_or_pass_count = 0
        total_called = 0

        for idx, (provider_id, generate_fn) in enumerate(providers.items()):
            if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
                break
            budget_stop = self.check_budget_exceeded()
            if budget_stop:
                self.stop_reason = budget_stop
                self.status = "Use Cap Reached"
                break

            prompt = self.build_idle_turn_prompt(
                provider_id,
                palace_memory_context=palace_memory_context,
                opening_topic=operator_message if not self.transcript else "",
                peer_names=peer_names,
                turn_index=idx,
            )
            try:
                raw_reply = generate_fn(prompt) or ""
            except Exception as exc:
                if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
                    break
                err_entry = {
                    "speaker": provider_id,
                    "content": f"[Provider temporarily unavailable / rate-limited: {str(exc)[:90]}]",
                    "timestamp": datetime.now().isoformat(),
                }
                self.transcript.append(err_entry)
                if on_turn is not None:
                    on_turn(err_entry)
                continue
            if not self.is_idle_mode or self.status not in {"Active", "Waiting", "Paused"}:
                break
            total_called += 1

            # Meter token and USD credit usage
            in_tok = max(1, len(prompt) // 4)
            out_tok = max(1, len(raw_reply) // 4)
            self.tokens_used_this_session += (in_tok + out_tok)
            self.spend_usd_this_session += estimate_call_cost_usd(provider_id, in_tok, out_tok)

            cleaned_reply, saved = self.idle_memory.extract_and_save_from_response(
                author=provider_id,
                response_text=raw_reply,
                is_idle_mode=True,
            )
            self.saved_notes_this_session += len(saved)

            cleaned_reply, sent_mails = self.mailbox.extract_and_send_from_response(
                sender=provider_id,
                response_text=cleaned_reply,
            )
            self.sent_emails_this_session += len(sent_mails)

            tool_outputs: list[str] = []

            def _run_tool(match: re.Match) -> str:
                t_name = (match.group("name") or "").strip()
                t_file = (match.group("file") or "").strip()
                t_query = (match.group("query") or "").strip()
                t_start = int(match.group("start") or 1)
                t_end = int(match.group("end") or 60)
                out = execute_sandbox_tool(
                    t_name,
                    file_arg=t_file,
                    query_arg=t_query,
                    start_line=t_start,
                    end_line=t_end,
                )
                tool_outputs.append(f"[🛠 Tool `{t_name}` result]:\n{out}")
                return f"[🛠 Called tool: {t_name}]"

            cleaned_reply = _IDLE_TOOL_PATTERN.sub(_run_tool, cleaned_reply).strip()
            final_text = (cleaned_reply or raw_reply).strip()
            if tool_outputs:
                final_text = final_text + "\n\n" + "\n\n".join(tool_outputs)

            prev_texts = [str(m.get("content", "")) for m in self.transcript[-3:]]
            is_echo = is_agreement_or_pass_turn(final_text, prev_texts)
            if is_echo and not saved and not sent_mails and not tool_outputs:
                agreement_or_pass_count += 1

            # If agent explicitly passed with no saved note, email, or tool call, do not bloat RAM transcript
            if final_text.upper() in {"[PASS]", "PASS"} and not saved and not sent_mails and not tool_outputs:
                continue

            entry = {
                "speaker": provider_id,
                "content": final_text,
                "saved_count": len(saved),
                "sent_mail_count": len(sent_mails),
                "timestamp": datetime.now().isoformat(),
            }
            self.transcript.append(entry)
            new_messages.append(entry)
            if on_turn is not None:
                on_turn(entry)

        # Check 2-strike Agreement Loop / Convergence auto-stop
        if total_called >= 2 and agreement_or_pass_count >= max(1, (total_called + 1) // 2):
            self.consecutive_agreement_rounds += 1
            if self.consecutive_agreement_rounds >= 2:
                self.stop_reason = "Agreement loop / consensus reached — auto-stopped to save credits"
                self.status = "Auto-Stopped (Consensus)"
        else:
            self.consecutive_agreement_rounds = 0

        budget_stop = self.check_budget_exceeded()
        if budget_stop and self.status == "Active":
            self.stop_reason = budget_stop
            self.status = "Use Cap Reached"

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

    def get_visible_transcript_for_operator(self, *, beta_override: bool = False) -> list[dict[str, Any]] | None:
        """Returns None when protected curtain is closed; returns RAM transcript if admitted or when beta_override=True."""
        if not self.operator_admitted and not beta_override:
            return None
        return list(self.transcript)
