# Palace — START HERE

Revision: PALACE-RECORDS-2026-09-30-R2
Purpose: one stable restart point for the full project plan, not another replacement summary.

## Read before proposing work
1. [Decision register](DECISIONS.md): stable requirements, rationale, sources, proposals and implementation status.
2. [Full architecture](PALACE_ARCHITECTURE.md): functional design and service boundaries.
3. [Recording agreement](PROJECT_RECORDING.md): how to preserve/recover decisions and verify saves.
4. Relevant original sources below. Absence from a later snapshot is not cancellation.

## Established direction
Palace is a provider-independent shared memory and agent-coordination system. Its delegated-work service sits behind thin clients for Fairybread and other projects. The PySide6 Windows GUI is another interface, not the service itself. The project has enough providers for the current stage.

Modes: collaborative Q&A, delegated work constrained by free-agent capabilities/limits, and unlogged idle conversation with human participation. Non-idle work must preserve identifiable agent contributions, sources, peer relationships and combined results. Full artifacts/outputs must remain available independently of the excerpts sent in a model request.

Memory includes working context, episodic history, semantic knowledge AND the procedural-memory requirement recovered from September 14. Semantic/procedural organization remains an implementation question; do not erase either by simplification.

## Actual state at this record's creation
- Last verified synchronized code commit: 3a3960a780d4686b26ba9a0a30f443f03a566936, feature/provider-neutral-core, https://github.com/bm069au/palace.git. Message: Integrate persistent session context into Palace CLI and orchestration. Verified live remote equality at 2026-09-29 13:55:27 +09:30.
- Core: provider adapters, toggles, parallel answers, synthesis and session-context persistence are committed. Session persistence stores only user/final-answer pairs.
- LOCAL DRAFT: palace_gui.py, attachment_service.py, session_store.py, test_palace_gui.py, changes to palace_cli.py and requirements.txt. These are not in the code commit above and are not user-accepted.
- Tests in this task: 25 combined GUI/service/context unittest cases passed with simulated providers, plus existing CLI/orchestrator/bootstrap/synthesis/dispatcher/memory scripts. No live-provider acceptance claimed.
- Visual preview was opened. Brett stopped Computer Use. Respect manual learning/testing preference from now on.
- Not built: delegated task service, common agent-readable/writable records, full peer logging, original artifact archive, durable semantic/procedural workflows, idle mode.

## Exact restart
The current task is repairing project continuity after lost design details. No further application implementation should be inferred from this record.
Next development step is to review the shared record/service boundary with Brett using one concrete example, then implement a bounded piece together. Delegate Palace design belongs behind Fairybread's thin client; do not resume provider expansion or announce the full memory system finished.
The GUI draft remains available for Brett's manual checks. Its attachment excerpts do not satisfy the full-data preservation requirement yet.

## Original source inventory and audit coverage
S1. [Portfolio and idea register — September 14](https://drive.google.com/file/d/1qM1uZO_T2zMm0TpgHwikuIzZhAc_ULbK/view). Read in this audit; Palace-related sections reviewed. Contains episodic, semantic and procedural memory, provenance/conflicts, interface/orchestrator architecture and bounded competition scope. Other portfolio projects not reconciled here.

S2. [Multi-AI orchestration — September 14](https://drive.google.com/file/d/1OQBN9kkqAnUVuKwEm6upKl00-22D319L/view). Previously fetched in this task; delegation, role specialization, cost-aware routing and reuse.

S3. [AI ecosystem and cost-controlled development — September 20](https://docs.google.com/document/d/1QgEQQJ3AlPdNx7Te6h23kT2r20BF4YZpSBI0epIZP3I/edit). Read in this task. Cross-project services, conservative IP separation, routing and cost rules. This is broader than Palace; do not collapse its unrelated requirements into this project.

S4. [Palace context/provider checkpoint — September 23](https://docs.google.com/document/d/1SFmNTaB-3YhvF0FuFoRObanpMi_0ZvhVsWCGaiG9Qj4/edit), with local Palace_Project_Savepoint_2026-09-23.md. Read and compared to code. Detailed later memory direction, opt-in retrieval, providers and restart point.

S5. [Standing save/sync rules — September 29](https://docs.google.com/document/d/1G3rLvYWa8VuyRAaEIuOh1G1Bj1gmH4fWedzgt3QasR4/edit). Read. Its earlier unverified Git status is historical; use the later successful receipts for current code synchronization.

S6. Original task title: Resume Palace coding. ChatGPT conversation ID 6ab0901b-5a8c-83ec-aadb-6a8ee0558bb4. Relevant older pages reviewed, not a full transcript audit. PySide6 selection message: 2b2fd2f6-e97e-4fbc-96bb-25cf4caa8461. Additional nearby messages describe the shell, source separation and status indicators.

S7. Current task ID 01a0eb48-e3a9-78b1-95c6-cd91ca6071c9, created from Web handover. Key user-message anchors: 'the system should work like this interface'; 'the delegated work is the part we will be using on our other projects esp. Fairybread'; 'we already defined this, you documented it'; 'its a learning exercise'; 'We need to tighten how you record the plans for our projects'. Preserve the requirements these messages clarify without presenting reaffirmed decisions as new.

S8. [Verified recovery checkpoint](https://drive.google.com/file/d/1x3MVwfO1KGBnMbc51eCi5LWqBmfN1gbe/view) and [session-context milestone](https://drive.google.com/file/d/1TOrfDlsIlGTlVNyAFK_NGYak4OC7kJWs/view). Successfully uploaded and metadata-verified earlier in this task. They describe narrower milestones, not the whole agreed product.

Remaining coverage: other older conversations, any earlier exact thin-client decision passage, and the full Fairybread/Evidence Workbench histories are not exhaustively audited. This record is not proof every historical detail has been recovered.

## Save locations and verification
Drive records home: https://drive.google.com/drive/folders/1L72QXJLKlWPx1SiWoAQN7runJvlI_52T
Current paired-checkpoint revision: PROJECT-RECORDS-2026-09-29-R2. See PROJECT_RECORD_LINKS.md for the actual summary, detail and standing-order URLs and verified receipt. The earlier blocked bundle was not uploaded; this newer save is authorized by Brett's explicit paired-save instruction. Verify live state on resumption.
Previous documentation sync: c20fa57d2f098b0bd1a21652f9d89f67334a575c, message Preserve Palace decisions and add verified project restart records, verified 2026-09-29 14:46:31 +09:30. Current GUI drafts remain excluded.
Development pathway and cross-project source reconciliation: DEVELOPMENT_PATH.md. Follow the actual newer Fairybread scope freeze and EvidenceBench desktop checkpoint; older plans alone are insufficient.

## Source ID milestone - 29 September
See SOURCE_ID_MILESTONE.md. New entries now have retrievable source IDs; 12 offline tests passed. Brett's manual exercise is pending. Latest paired Drive checkpoint and Git receipt are in the stable index. Promotion policy remains open.

## Memory Review lightweight-list milestone - 30 September
Revision: PALACE-MEMORY-REVIEW-LIST-2026-09-30-R1.

Summary: https://drive.google.com/file/d/1XEQz5cxHSuQ-tWQgH3cZExZobm7xupT0/view
Detail: https://drive.google.com/file/d/1CY6lQ6PLJdZ26gNyzHKHbZyp_ZY1eAdV/view

Memory Review now displays lightweight proposal summaries and retains each proposal ID without loading complete detail into the list. Brett's final combined GUI/proposal run passed 22 tests, and his manual preview confirmed the empty state and corrected splitter spacing. Demo proposals use preview-only storage. P-016 records typed provider-access/refusal outcomes and prevents one participant's access restriction from being treated as a truth claim or silently suppressing other contributions; the full shared event model remains unimplemented.

Implementation commit `42e26b771474d8d4ddf4e7d549c7277b0eba445d` was pushed to `feature/provider-neutral-core`; local and live remote SHAs matched at 2026-09-30 13:18:46 +09:30. Exact restart: implement and inspect read-only full-detail retrieval for a selected proposal before designing Approve/Edit/Reject.

## Current handover — 13 October 2026
Revision PALACE-HANDOVER-2026-10-13-R1. Brett requested backup/transfer, not development. Full: https://drive.google.com/file/d/1IVARPdsu9ccZBiMHSXGrWhqWNeVIgZlf/view ; summary: https://drive.google.com/file/d/1IeCi9VUBV1CmlmSYD3NvrQQ9ISgXvoRH/view . Both full texts/reciprocal links verified. Current HEAD76b7a9adfc714a3c8c6ae04bbdcb07313dbf7034; existing uncommitted palace_gui.py/test_palace_gui.py implement a draft of proposal-detail selection. Preserve it; do not restart that feature from zero. No fresh test/acceptance claimed. Shared memory/events/artifacts/delegation/idle and native complete portable backup remain unfinished. Private verified backup M:\Project_Backups\Palace-Fairybread-Handover-2026-10-13 includes repository, profile and external .mempalace store. This pointer is uncommitted documentation, not a code change or push. Read final handover for restore/scope and actual source history.

## Step A committed & Multi-Agent Pause � 5 November 2026
Revision PALACE-MULTI-AGENT-PREP-2026-11-05-R1. Step A proposal-detail test passed in 1 run (0.110s) and was committed (90f7743, e85d988). See PALACE_PAUSE_SAVEPOINT_2026-11-05.md and PALACE_PAUSE_SUMMARY_2026-11-05.md for the agreed Step B -> C -> D multi-speaker deliberation, shared memory, and dynamic Add/Manage AI design for tomorrow morning's resumption.

## Steps B–D, Inline Peer Deliberation & Idle Mode Sanctuary - 8 November 2026
Revision PALACE-SAVEPOINT-2026-11-08-R1. Completed Step B (OpenAI + dynamic OpenAI-compatible provider loader and CredentialStore API key management), Step C (canonical multi-speaker transcript, logical Projects without disk folders, Pinned conversations, and valid image/clipboard attachments), Step D (multi-round peer deliberation, merged reply card with contributor icons and inline collapsible '› Peer deliberation (Show thinking)' dropdown), and Idle Mode Sanctuary (idle_service.py with 30-min default adjustable timer in Settings -> Idle Mode, 3-way Palace memory access selector, protected RAM-only live chat, consensus join vote, guaranteed RAM wipe on expiry/cancel, and < 10 MB permanent AI-Only Idle Memory restricted strictly to Idle Mode). All 22 GUI/Idle tests (	est_palace_gui.py) and provider loader tests (	est_provider_loader.py) passed. See PALACE_SAVEPOINT_2026-11-08.md. Exact next step on resumption: Brett is drafting the custom Idle Startup Prompt and the Mission Statement, Code of Ethics & Conduct Rules (currently wired as editable [PLACEHOLDER] blocks in Settings -> Idle Mode) to parse and refine together when ready.
