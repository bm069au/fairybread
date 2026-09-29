"""Offline learning exercise: save once, then retrieve in another process."""
import argparse
from pathlib import Path
from context_service import ContextService
from memory_proposal_service import MemoryProposalService

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['save', 'read', 'propose', 'read-proposal'])
parser.add_argument('identifier', nargs='?')
args = parser.parse_args()
store = ContextService(Path(__file__).parent / '.learning' / 'source-id-demo.jsonl')
proposals = MemoryProposalService(Path(__file__).parent / '.learning' / 'memory-proposals.jsonl')
if args.action == 'save':
    identifier = store.append('user', 'LEARNING EXAMPLE: Palace uses PySide6 for its Windows interface.')
    print('Saved locally. No AI calls were made.')
    print('Source ID:', identifier)
    print('Next run: python source_id_demo.py read ' + identifier)
elif args.action == 'read':
    if not args.identifier:
        parser.error('read needs the source ID printed by save')
    entry = store.read_entry(args.identifier)
    if entry is None:
        parser.exit(1, 'Source not found. Check the ID.\n')
    print('Source ID:', entry['id'])
    print('Original text:', entry['content'])
elif args.action == 'propose':
    if not args.identifier:
        parser.error('propose needs the source ID printed by save')
    proposal_id = proposals.propose_from_session(
        store,
        args.identifier,
        summary='Palace Windows UI uses PySide6',
        memory_type='semantic',
    )
    print('Proposed only; it has not been accepted as durable memory.')
    print('Proposal ID:', proposal_id)
    print('Next run: python source_id_demo.py read-proposal ' + proposal_id)
else:
    if not args.identifier:
        parser.error('read-proposal needs the proposal ID printed by propose')
    proposal = proposals.read_proposal(args.identifier)
    if proposal is None:
        parser.exit(1, 'Proposal not found. Check the ID.\n')
    source = store.read_entry(proposal['source']['entry_id'])
    print('Proposal ID:', proposal['id'])
    print('Status:', proposal['status'])
    print('Type:', proposal['memory_type'])
    print('Summary:', proposal['summary'])
    print('Detail:', proposal['detail'])
    print('Source ID:', proposal['source']['entry_id'])
    print('Source verified:', source is not None and source['content'] == proposal['detail'])
