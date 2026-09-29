# Memory proposal and portability milestone

Revision: PALACE-MEMORY-PROPOSAL-2026-09-29-R1
Date: 29 September 2026

## Purpose and learning path
Brett's primary purpose is education. In this session he set up Visual Studio Folder View, learned the editor/tool-window/terminal layout, edited the source and test himself, found the boundary between production behaviour and assertions, and ran the focused test. Reduced credit use was secondary.

## Implemented local behaviour
`MemoryProposalService` stores reviewable private proposals separately from raw session history and accepted durable memory. A proposal has its own UUID, schema version, timestamp, `proposed` status, semantic/procedural type, summary, full detail, visibility and a source reference. Creation resolves an existing session entry first; a missing or invalid source writes nothing. Duplicate/corrupt proposal records fail visibly.

The learning demo can create and read a proposal but does not approve it. Human-review versus defined-rule automatic promotion remains open. No proposal is treated as accepted long-term memory.

## Portability correction
The first draft stored the absolute path of the session JSONL in each proposal. Brett's complete-backup/cross-platform requirement exposed that as wrong before Version 1. Brett removed the path. Proposals now relate to the source through the logical `session_entry` kind and UUID entry ID. A reopened context service resolves the source from installation-owned storage; physical paths are not durable relationships.

This is a foundation, not the complete Palace resolver. A common record catalogue, conversation identity, backup exporter, restore process, artifact archive and Linux validation remain unimplemented.

## Backup requirement captured
Decision P-015 records complete verified backup, first-start destination selection, different-drive/cloud preference, preflight size/free-space notification, platform-neutral restore and disaster-safe replacement. Credentials in portable/cloud backups remain an explicit security question. Idle content remains excluded because it is never logged.

## Validation
Brett ran `python -B -m unittest test_memory_proposals`: 3 tests passed in 0.095 seconds. Earlier combined proposal/source/session testing passed 15 tests before the portability edit. A final combined offline regression is recorded in the save receipt. No provider calls, Computer Use or paid services were used.

## Restart point
Review the proposed-memory record in the PySide6 GUI using a collapsible details/review area, preserving Windows conventions. Teach the layout and tradeoffs before coding. The review UI needs Proposed status, summary, full detail, type, exact source, and future Edit/Approve/Reject operations. Backup architecture must shape all new persistent references.

Matching Drive summary: https://drive.google.com/file/d/1SUGLu6rA-594yhqkKZGSzl6ZFvpihbG0/view
Previous planning detail: https://drive.google.com/file/d/1Bo_aQxUdyA43AHCxEoZT6ceuo48nuPi0/view
