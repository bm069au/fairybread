# Palace â€” START HERE

Revision: PALACE-RECORDS-2026-09-29-R1
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
S1. [Portfolio and idea register â€” September 14](https://drive.google.com/file/d/1qM1uZO_T2zMm0TpgHwikuIzZhAc_ULbK/view). Read in this audit; Palace-related sections reviewed. Contains episodic, semantic and procedural memory, provenance/conflicts, interface/orchestrator architecture and bounded competition scope. Other portfolio projects not reconciled here.

S2. [Multi-AI orchestration â€” September 14](https://drive.google.com/file/d/1OQBN9kkqAnUVuKwEm6upKl00-22D319L/view). Previously fetched in this task; delegation, role specialization, cost-aware routing and reuse.

S3. [AI ecosystem and cost-controlled development â€” September 20](https://docs.google.com/document/d/1QgEQQJ3AlPdNx7Te6h23kT2r20BF4YZpSBI0epIZP3I/edit). Read in this task. Cross-project services, conservative IP separation, routing and cost rules. This is broader than Palace; do not collapse its unrelated requirements into this project.

S4. [Palace context/provider checkpoint â€” September 23](https://docs.google.com/document/d/1SFmNTaB-3YhvF0FuFoRObanpMi_0ZvhVsWCGaiG9Qj4/edit), with local Palace_Project_Savepoint_2026-09-23.md. Read and compared to code. Detailed later memory direction, opt-in retrieval, providers and restart point.

S5. [Standing save/sync rules â€” September 29](https://docs.google.com/document/d/1G3rLvYWa8VuyRAaEIuOh1G1Bj1gmH4fWedzgt3QasR4/edit). Read. Its earlier unverified Git status is historical; use the later successful receipts for current code synchronization.

S6. Original task title: Resume Palace coding. ChatGPT conversation ID 6ab0901b-5a8c-83ec-aadb-6a8ee0558bb4. Relevant older pages reviewed, not a full transcript audit. PySide6 selection message: 2b2fd2f6-e97e-4fbc-96bb-25cf4caa8461. Additional nearby messages describe the shell, source separation and status indicators.

S7. Current task ID 01a0eb48-e3a9-78b1-95c6-cd91ca6071c9, created from Web handover. Key user-message anchors: 'the system should work like this interface'; 'the delegated work is the part we will be using on our other projects esp. Fairybread'; 'we already defined this, you documented it'; 'its a learning exercise'; 'We need to tighten how you record the plans for our projects'. Preserve the requirements these messages clarify without presenting reaffirmed decisions as new.

S8. [Verified recovery checkpoint](https://drive.google.com/file/d/1x3MVwfO1KGBnMbc51eCi5LWqBmfN1gbe/view) and [session-context milestone](https://drive.google.com/file/d/1TOrfDlsIlGTlVNyAFK_NGYak4OC7kJWs/view). Successfully uploaded and metadata-verified earlier in this task. They describe narrower milestones, not the whole agreed product.

Remaining coverage: other older conversations, any earlier exact thin-client decision passage, and the full Fairybread/Evidence Workbench histories are not exhaustively audited. This record is not proof every historical detail has been recovered.

## Save locations and verification
Local owner: E:\Visual_studio\Palace. These four records and AGENTS.md are project documentation.
Established Drive folder: [01 â€” Portfolio & App Ideas](https://drive.google.com/drive/folders/13uazeSHKXk2k8Ifn4cupSzoHcng41aFZ), verified by metadata. Keep existing historical files in place.
Stable current Drive record: BLOCKED / NOT UPLOADED. On 2026-09-29 automatic approval review rejected the consolidated private project-record upload to the established folder because it requires explicit authorization for this new payload/destination. A complete upload-ready bundle is at C:\Users\moore\AppData\Local\Temp\PALACE_CURRENT_PROJECT_RECORD.md. Earlier UI-plan upload was also blocked. No Drive file ID was created for this bundle.
New documentation Git sync: pending at drafting. The verified code baseline above is not a claim the later GUI draft or these docs have been pushed.
The external save receipt must identify the documentation commit separately from unsynchronized UI code. Future restarts must inspect current Git state rather than rely on a stale timestamp here.
