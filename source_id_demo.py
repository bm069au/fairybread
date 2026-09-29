"""Offline learning exercise: save once, then retrieve in another process."""
import argparse
from pathlib import Path
from context_service import ContextService

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['save', 'read'])
parser.add_argument('source_id', nargs='?')
args = parser.parse_args()
store = ContextService(Path(__file__).parent / '.learning' / 'source-id-demo.jsonl')
if args.action == 'save':
    identifier = store.append('user', 'LEARNING EXAMPLE: Palace uses PySide6 for its Windows interface.')
    print('Saved locally. No AI calls were made.')
    print('Source ID:', identifier)
    print('Next run: python source_id_demo.py read ' + identifier)
else:
    if not args.source_id:
        parser.error('read needs the source ID printed by save')
    entry = store.read_entry(args.source_id)
    if entry is None:
        parser.exit(1, 'Source not found. Check the ID.\n')
    print('Source ID:', entry['id'])
    print('Original text:', entry['content'])
