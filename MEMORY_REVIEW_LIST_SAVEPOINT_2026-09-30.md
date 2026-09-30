# Palace Memory Review list savepoint

Revision: PALACE-MEMORY-REVIEW-LIST-2026-09-30-R1
Date: 30 September 2026
Status: Verified development checkpoint; read-only summary listing is implemented, while detail inspection and memory decisions remain unfinished.

## Relationship to the existing plan
This checkpoint completes the exact restart work from the Memory Review foundation checkpoint. It continues the source-linked proposed-memory workflow and does not replace the full Palace architecture, decision register, backup requirement or earlier source records.

Previous detail: https://drive.google.com/file/d/1pI8eZhdafrM2WEVes0Ko4ydHr6CFKhSA/view
Previous summary: https://drive.google.com/file/d/1Z_-rXbD5DWclBWkRvok-3XoPvmT49Ccw/view
Stable index: https://drive.google.com/file/d/1G9HLoa2l9i_JfjMkJb9z5GFVTn_6eZcP/view
Standing order: https://drive.google.com/file/d/1YWBlviT3fboJiJ72GlfSOQFrR4JMSvHE/view
Matching summary: https://drive.google.com/file/d/1XEQz5cxHSuQ-tWQgH3cZExZobm7xupT0/view

## Purpose and behaviour
Memory Review now performs the first half of the agreed two-stage review flow. Opening the panel asks `MemoryProposalService` for lightweight proposal records, clears stale screen contents and shows each proposal's status, memory type and summary. The list item retains the proposal ID for later retrieval, while the potentially large `detail` field remains outside the list. An empty store displays `No proposed memories yet.` Corrupt or unreadable proposal data is reported instead of silently appearing empty.

This preserves the distinction between conversation history, a proposed durable memory and an accepted durable memory. Nothing in this checkpoint automatically promotes, edits or rejects memory.

## Implemented changes
- Added `proposal_list` to the docked PySide6 Memory Review panel with an accessibility name.
- Added `refresh_memory_review(visible)`, loading only when the panel opens and displaying newest-first lightweight proposal metadata from the service.
- Stored each proposal ID in the corresponding GUI item for the next detail-retrieval milestone.
- Added a clear empty-state row and visible error handling for unreadable proposal storage.
- Added a GUI test proving that the summary is displayed and the complete source detail is not copied into the list.
- Kept demo conversations and demo memory proposals together under `%LOCALAPPDATA%\Palace\ui-preview`, separate from real Palace data and without AI calls.
- Disabled the unwanted horizontal scrollbar in the conversation list and elided long titles while retaining the existing full-title tooltip.
- Added an eight-pixel right buffer to the centre panel so the splitter no longer draws over the Memory Review button and adjacent controls.
- Recorded P-016: provider restrictions and refusals are evidence about the participant's access, not proof that a source is universally unavailable or a claim is false. Palace must preserve typed outcomes, provenance, coverage gaps and substantive disagreement without bypassing provider controls.

## Working experience and Brett's contribution
Brett wrote the GUI test and implementation in Visual Studio with guidance, repaired indentation errors, and used Windows PowerShell for focused and combined tests. He identified that line-by-line guidance had become inefficient, so the learning workflow was corrected to use complete meaningful feature steps: explain purpose and placement, make the bounded change, inspect once, then test.

Brett manually inspected the local preview, identified the centre-panel border overlap, reasoned that alignment or a buffer must push controls clear of the divider, and confirmed the eight-pixel layout buffer fixed it. This was a design and diagnosis contribution, not merely command execution.

## Validation actually completed
- Focused test: `python -B -m unittest test_palace_gui.WindowTests.test_memory_review_lists_summaries_without_full_detail` — 1 test passed in 0.044 seconds.
- Combined related suites after implementation: `python -B -m unittest test_palace_gui test_memory_proposals` — 22 tests passed in 3.570 seconds.
- Combined related suites after the final visual-spacing change: the same command — 22 tests passed in 1.564 seconds.
- Python AST structure check passed for `palace_gui.py` and `test_palace_gui.py`; `git diff --check` found no whitespace errors.
- Brett launched `python palace_gui.py --demo`, confirmed the Memory Review panel opens and closes, saw the empty-state message, and confirmed the right-side splitter no longer cuts across the controls.
- Qt reported that its package font directory was absent. Palace uses the installed Windows Segoe UI font, displayed correctly in the manual preview, and all tests passed. No font package was installed.
- No live AI/provider calls, paid services, Computer Use or additional agents were used.

## Git receipt
Repository: https://github.com/bm069au/palace.git
Branch: `feature/provider-neutral-core`
Implementation commit: `42e26b771474d8d4ddf4e7d549c7277b0eba445d`
Message: `List memory proposals in Palace review panel`
Files: `DECISIONS.md`, `PALACE_ARCHITECTURE.md`, `palace_gui.py`, `test_palace_gui.py`
Push succeeded. Local HEAD and `refs/heads/feature/provider-neutral-core` on the live remote matched at 2026-09-30 13:18:46 +09:30.

The paired checkpoint files, reciprocal links and stable-index receipt are created after this implementation commit and will be captured by a separate documentation commit. No unrelated local draft is claimed by the implementation commit.

## Incomplete work and risks
- Selecting a proposal does not yet retrieve or display its complete detail and source information.
- Edit, Approve and Reject remain unimplemented, as do promotion policy, accepted durable-memory storage and revision history.
- Demo mode currently proves the empty state; a deliberate preview-only sample proposal is still needed for a visual inspection of populated rows without touching real data.
- Full multi-agent event records, typed access/refusal outcomes, independent coverage display and synthesis enforcement from P-016 are not implemented.
- Attachments still provide bounded extracted text to providers; the required complete original-artifact archive is not implemented.
- Backup/restore requirements in P-015 remain design requirements; exporter, size/free-space preflight, verification and restoration are not implemented.
- The GUI remains a development preview, not a release.

## Exact restart
1. Read this checkpoint through the stable index and matching summary.
2. Add a focused failing GUI test for selecting a proposal and retrieving its full record by the proposal ID stored on the list item.
3. Add a read-only detail area that clearly separates summary, full detail and source identity.
4. Seed only preview storage with a sample proposal and let Brett inspect the populated list/detail flow manually.
5. Do not implement Approve, Edit, Reject or automatic promotion until the read-only detail experience has been inspected and agreed.
