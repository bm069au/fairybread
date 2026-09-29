# Palace memory-review foundation savepoint

Revision: PALACE-MEMORY-REVIEW-2026-09-29-R1
Date: 29 September 2026
Status: Development checkpoint; Memory Review listing and approval actions remain unfinished.

## Purpose and relationship to the existing plan
This checkpoint continues the source-linked memory-proposal milestone. It does not replace the full Palace architecture, decision register, or previous memory-proposal checkpoint. Palace still uses layered working, episodic, semantic and procedural memory; proposed memory is the quality-control stage between recorded history and accepted durable memory.

Previous detail: https://drive.google.com/file/d/1V8U_1agBps8ScF5zcSbbhqc9yBBWfvkt/view
Previous summary: https://drive.google.com/file/d/1SUGLu6rA-594yhqkKZGSzl6ZFvpihbG0/view
Stable index: https://drive.google.com/file/d/1G9HLoa2l9i_JfjMkJb9z5GFVTn_6eZcP/view
Matching summary: PENDING DRIVE UPLOAD

## Behaviour and architecture clarified
A proposal is a candidate durable memory, not the raw conversation and not accepted memory. It preserves a summary, complete detail, type, status and exact source-entry identity. Semantic proposals describe facts or decisions; procedural proposals describe how work should be done. Edit, Approve and Reject remain unimplemented.

The agreed efficient review flow is two-stage: the GUI first lists lightweight proposal metadata, then retrieves the complete record only when a proposal is selected. This does not discard or truncate stored detail. It prevents a screen containing many proposals from loading every potentially large answer at once.

The project continues to require exact sources, full underlying records, revisions, identifiable agent contributions, platform-neutral references and complete verified backup. The GUI is an interface to the provider-neutral Palace core, not the owner of memory rules or storage.

## Implemented in this checkpoint
- Corrected the portability assertion so it lives in `test_memory_proposals.py`, not production code. The correction was committed and remotely verified as `2d2fed2da443ddc768fd5149713935e1c0c3090a`.
- Added `MemoryProposalService.list_proposals()`. It validates stored records, rejects duplicate proposal IDs, returns newest records first and omits full `detail` from list results. `read_proposal()` still retrieves the complete record by ID.
- Added a test proving an absent store returns an empty list, newest-first ordering, lightweight list results and full-detail retrieval by ID.
- Advanced the existing PySide6 draft into a visible Memory Review foundation: a checkable button opens and hides a docked right-hand panel inside the Palace window. The splitter returns space to the conversation when the panel closes.
- Added a GUI test covering the panel's hidden/open/closed behaviour.
- Prepared dependency injection for `MemoryProposalService`, allowing normal Palace to use its default store while GUI tests use disposable temporary storage.
- Preserved the existing GUI draft functions: named conversations, local history control, copy/paste, drag-and-drop attachments, provider status, background work and local simulated preview.
- Added an explicit continuity rule: unfamiliar architecture terms must be explained before Brett is asked to design, edit or test them. Explanations must cover meaning, place in the complete flow, purpose, a concrete example and unfinished related behaviour.

## Learning and human contribution
Brett performed the edits and checks in Visual Studio and Windows PowerShell. He chose Windows PowerShell as the clearer command environment, used Tab and Shift+Tab to control Python indentation, wrote the new GUI and service tests, saw an expected test-first failure for the missing list operation, implemented the operation and turned the same test green.

Brett also identified a communication failure: he was asked to build a proposal UI before the term and full memory flow were explained. The correction is a refinement of the already-agreed education-first workflow, not a new project direction. Coding remains intentionally slow so Brett learns the implementation and has time to discover additional desirable behaviour.

## Validation actually completed
- Brett ran `python -B -m unittest test_memory_proposals`: 4 tests passed in 0.102 seconds.
- Brett ran `python -B -m unittest test_palace_gui`: 17 tests passed in 2.440 seconds using simulated providers and temporary files.
- A Qt warning reported a missing bundled font directory. Tests passed and Qt used an available fallback; packaging/fonts remain a later deployment concern.
- Brett manually ran `python palace_gui.py --demo`, confirmed the Memory Review button stays selected, confirmed the right-hand panel opens inside Palace, and confirmed closing it returns space to the conversation.
- No live AI/provider calls, paid services, Computer Use or additional agents were used.

## Incomplete work and risks
- The Memory Review panel currently contains explanatory text only. It does not yet list proposals.
- The planned GUI test `test_memory_review_lists_summaries_without_full_detail` was explained but deliberately not added after Brett requested the savepoint.
- Selecting a proposal and showing full detail/source are not implemented.
- Edit, Approve, Reject, promotion rules, accepted durable-memory storage and revision history remain open.
- The existing attachment draft passes text excerpts to providers; it is not the required complete original-artifact archive.
- Backup/restore requirements are recorded in P-015 but the exporter, preflight, verification and restore workflow are not implemented.
- The GUI remains a development preview. The Qt font warning must be resolved before packaging.

## Exact restart
1. Re-read this detail through the stable index and matching summary.
2. Add `test_memory_review_lists_summaries_without_full_detail` to `test_palace_gui.py` using the already-injected temporary proposal service.
3. Run that single test and confirm its expected failure because `proposal_list` does not exist.
4. Add a proposal list to the right-hand panel and refresh it when the panel opens.
5. Make the test pass, rerun the GUI and proposal suites, then let Brett inspect the list manually before implementing full-detail selection.

Do not begin Approve/Edit/Reject or automatic promotion at restart. First complete and inspect the read-only lightweight list.
