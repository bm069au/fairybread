"""Named local conversations, independent of UI and permanent memory."""
import json
import os
from pathlib import Path
from uuid import uuid4

from context_service import ContextService


class SessionStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else Path(os.environ['LOCALAPPDATA']) / 'Palace'
        self.index_path = self.root / 'conversations.json'
        if self.index_path.exists():
            self.data = json.loads(self.index_path.read_text(encoding='utf-8'))
            self._validate()
        else:
            self.data = {'selected': None, 'sessions': []}
            if (self.root / 'session_context.jsonl').exists():
                self.data['sessions'].append({'id': 'legacy', 'title': 'Earlier Palace conversation'})
                self.data['selected'] = 'legacy'
            else:
                self._add()
            self.save()

    def _validate(self):
        if not isinstance(self.data, dict) or not isinstance(self.data.get('sessions'), list):
            raise ValueError('Conversation list is damaged; it has been left untouched.')
        ids = []
        for item in self.data['sessions']:
            if not isinstance(item, dict):
                raise ValueError('Invalid conversation entry.')
            key = item.get('id', '')
            if key != 'legacy' and (len(key) != 32 or any(c not in '0123456789abcdef' for c in key)):
                raise ValueError('Invalid conversation identifier.')
            if not isinstance(item.get('title'), str) or key in ids:
                raise ValueError('Invalid conversation title or duplicate identifier.')
            ids.append(key)
        if self.data.get('selected') not in ids:
            raise ValueError('Selected conversation is missing.')

    @property
    def sessions(self):
        return self.data['sessions']

    @property
    def selected(self):
        return self.data['selected']

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_name(f'.conversations-{uuid4().hex}.tmp')
        try:
            temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.index_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _add(self):
        key = uuid4().hex
        self.sessions.insert(0, {'id': key, 'title': 'New conversation'})
        self.data['selected'] = key
        return key

    def create(self):
        key = self._add()
        self.save()
        return key

    def select(self, key):
        if key not in {item['id'] for item in self.sessions}:
            raise ValueError('Unknown conversation.')
        self.data['selected'] = key
        self.save()

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
        return ContextService(path)

    def messages(self, key):
        path = self.context(key).path
        if not path.exists():
            return []
        messages = []
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict) or entry.get('role') not in {'user', 'assistant'} or not isinstance(entry.get('content'), str):
                raise ValueError('Conversation history is damaged; it has been left untouched.')
            messages.append(entry)
        return messages
