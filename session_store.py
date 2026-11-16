"""Named local conversations and logical projects, independent of UI and permanent memory."""
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from context_service import ContextService, normalize_message_entry


class SessionStore:
    def __init__(self, root: Path | None = None):
        if root is not None:
            self.root = Path(root)
        else:
            try:
                from palace_config import get_palace_data_root
                self.root = get_palace_data_root()
            except Exception:
                self.root = Path(os.environ['LOCALAPPDATA']) / 'Palace'
        self.index_path = self.root / 'conversations.json'
        if self.index_path.exists():
            self.data = json.loads(self.index_path.read_text(encoding='utf-8'))
            self._validate()
        else:
            self.data = {
                'selected': None,
                'selected_project': None,
                'projects': [],
                'sessions': [],
            }
            if (self.root / 'session_context.jsonl').exists():
                self.data['sessions'].append({'id': 'legacy', 'title': 'Earlier Palace conversation', 'project_id': None})
                self.data['selected'] = 'legacy'
            else:
                self._add()
            self.save()

    @staticmethod
    def _is_hex32(value: str) -> bool:
        return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)

    def _validate(self):
        if not isinstance(self.data, dict) or not isinstance(self.data.get('sessions'), list):
            raise ValueError('Conversation list is damaged; it has been left untouched.')
        projects = self.data.get('projects', [])
        if not isinstance(projects, list):
            raise ValueError('Project list is damaged; it has been left untouched.')
        project_ids = []
        for proj in projects:
            if not isinstance(proj, dict):
                raise ValueError('Invalid project entry.')
            pid = proj.get('id', '')
            if not self._is_hex32(pid) or not isinstance(proj.get('name'), str) or not proj['name'].strip() or pid in project_ids:
                raise ValueError('Invalid project identifier or name.')
            project_ids.append(pid)
        selected_project = self.data.get('selected_project')
        if selected_project is not None and selected_project not in project_ids:
            raise ValueError('Selected project is missing.')

        ids = []
        for item in self.data['sessions']:
            if not isinstance(item, dict):
                raise ValueError('Invalid conversation entry.')
            key = item.get('id', '')
            if key != 'legacy' and not self._is_hex32(key):
                raise ValueError('Invalid conversation identifier.')
            if not isinstance(item.get('title'), str) or key in ids:
                raise ValueError('Invalid conversation title or duplicate identifier.')
            pid = item.get('project_id')
            if pid is not None and pid not in project_ids:
                raise ValueError('Conversation references an unknown project.')
            ids.append(key)
        if self.data.get('selected') not in ids:
            raise ValueError('Selected conversation is missing.')

    @property
    def projects(self) -> list[dict]:
        return self.data.setdefault('projects', [])

    @property
    def selected_project(self) -> str | None:
        return self.data.get('selected_project')

    @property
    def sessions(self):
        return self.data['sessions']

    @property
    def selected(self):
        return self.data['selected']

    def sessions_for_project(self, project_id: str | None = None) -> list[dict]:
        if project_id is None:
            return list(self.sessions)
        return [
            item for item in self.sessions
            if item.get('project_id') == project_id
        ]

    def pinned_sessions(self) -> list[dict]:
        return [
            item for item in self.sessions
            if bool(item.get('pinned', False))
        ]

    def toggle_pin(self, session_id: str) -> bool:
        for item in self.sessions:
            if item['id'] == session_id:
                new_state = not bool(item.get('pinned', False))
                item['pinned'] = new_state
                self.save()
                return new_state
        raise ValueError('Unknown conversation.')

    def create_project(self, name: str, folder: str | None = None) -> str:
        clean_name = ' '.join((name or '').split())[:65]
        if not clean_name:
            raise ValueError('Enter a project name.')
        project_id = uuid4().hex
        proj_entry: dict = {'id': project_id, 'name': clean_name}
        if folder:
            proj_entry['folder'] = self._validate_folder_path(folder)
        self.projects.insert(0, proj_entry)
        self.data['selected_project'] = project_id
        self._add(project_id=project_id)
        self.save()
        return project_id

    @staticmethod
    def _validate_folder_path(folder_path: str) -> str:
        raw = (folder_path or '').strip()
        if not raw:
            return ''
        p = Path(raw).resolve()
        drive = p.drive.upper()
        if drive.startswith('M:'):
            raise PermissionError('M: drive is strictly off-limits for Palace project attachments.')
        return str(p)

    def set_project_folder(self, project_id: str, folder_path: str | None) -> str:
        """Attach or detach a local folder to an existing project after creation."""
        for proj in self.projects:
            if proj['id'] == project_id:
                if folder_path and folder_path.strip():
                    clean_folder = self._validate_folder_path(folder_path)
                    proj['folder'] = clean_folder
                else:
                    proj.pop('folder', None)
                    clean_folder = ''
                self.save()
                return clean_folder
        raise ValueError('Unknown project.')

    def get_project_folder(self, project_id: str | None = None) -> str:
        target = self.selected_project if project_id is None else project_id
        if not target:
            return ''
        for proj in self.projects:
            if proj['id'] == target:
                return str(proj.get('folder') or '')
        return ''

    def select_project(self, project_id: str | None):
        if project_id is not None and project_id not in {p['id'] for p in self.projects}:
            raise ValueError('Unknown project.')
        self.data['selected_project'] = project_id
        matching = self.sessions_for_project(project_id)
        if matching:
            if self.selected not in {item['id'] for item in matching}:
                self.data['selected'] = matching[0]['id']
        else:
            self._add(project_id=project_id)
        self.save()

    def assign_session_project(self, session_id: str, project_id: str | None):
        if project_id is not None and project_id not in {p['id'] for p in self.projects}:
            raise ValueError('Unknown project.')
        for item in self.sessions:
            if item['id'] == session_id:
                item['project_id'] = project_id
                self.save()
                return
        raise ValueError('Unknown conversation.')

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_name(f'.conversations-{uuid4().hex}.tmp')
        try:
            temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.index_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _add(self, project_id: str | None = None):
        key = uuid4().hex
        resolved_project = self.selected_project if project_id is None else project_id
        self.sessions.insert(
            0,
            {
                'id': key,
                'title': 'New conversation',
                'project_id': resolved_project,
            }
        )
        self.data['selected'] = key
        return key

    def create(self, project_id: str | None = None):
        key = self._add(project_id=project_id)
        self.save()
        return key

    def select(self, key):
        target = None
        for item in self.sessions:
            if item['id'] == key:
                target = item
                break
        if target is None:
            raise ValueError('Unknown conversation.')
        self.data['selected'] = key
        if 'project_id' in target:
            self.data['selected_project'] = target.get('project_id')
        self.save()

    def session_relative_age(self, key: str) -> str:
        """Return compact Antigravity-style relative age ('now', '2m', '3h', '5d')."""
        try:
            ctx = self.context(key)
            if not ctx.path.exists():
                return 'now'
            delta = max(0.0, time.time() - ctx.path.stat().st_mtime)
            if delta < 60:
                return 'now'
            mins = int(delta // 60)
            if mins < 60:
                return f'{mins}m'
            hours = int(mins // 60)
            if hours < 24:
                return f'{hours}h'
            days = int(hours // 24)
            return f'{days}d'
        except Exception:
            return ''

    def rename_from_question(self, key, question):
        for item in self.sessions:
            if item['id'] == key and item['title'] == 'New conversation':
                item['title'] = ' '.join(question.split())[:65] or 'Conversation'
                self.save()
                break

    def context(self, key):
        if key not in {item['id'] for item in self.sessions}:
            raise ValueError('Unknown conversation.')
        path = self.root / 'session_context.jsonl' if key == 'legacy' else self.root / 'sessions' / f'{key}.jsonl'
        return ContextService(path, session_id=key)

    def messages(self, key):
        ctx = self.context(key)
        path = ctx.path
        if not path.exists():
            return []
        messages = []
        seq = 1
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict) or entry.get('role') not in {'user', 'assistant'} or not isinstance(entry.get('content'), str):
                raise ValueError('Conversation history is damaged; it has been left untouched.')
            messages.append(
                normalize_message_entry(
                    entry,
                    default_session_id=key,
                    default_sequence=seq,
                )
            )
            seq += 1
        return messages
