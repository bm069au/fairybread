# Development pathway and cross-project planning trail
Revision: PROJECT-RECORDS-2026-09-29-R2
This is a source-grounded reconstruction, not a fabricated chronological transcript. The original records remain authoritative evidence. Full historical migration is incomplete.

## Palace: discovery and clarification
Brett's problem is continuity across multiple AIs and projects: agents must share understandable memory, recognize each other's contributions and retain the detailed work behind useful summaries. Existing September 14 portfolio/orchestration records establish layered memory and reusable coordination. September 20 ecosystem planning establishes cost-aware services and project boundaries. September 23 documents context/provider work. On September 29 Brett reaffirmed the familiar Windows interface, collaboration/delegation/idle modes, complete recorded outputs and the existing thin-client architecture; he corrected the assistant for treating it as new.

Required behaviour is captured in P-001 through P-013 in DECISIONS.md. Procedural memory is retained alongside working, episodic and semantic memory. Enough providers exist now. Delegated work respects agent capabilities and free quotas; there is no implicit paid fallback. Idle conversation is unlogged and allows Brett to participate; details around deliberate saving and transitions remain open.

## Palace: how it works
One provider-neutral core serves the PySide6 desktop and project adapters/thin clients. Palace owns coordination, shared records and memory; Fairybread retains its media-specific operations. Original artifacts and complete observable results are stored independently from bounded model context. Shared entries need identity, authorship, sources, relationships, revisions and visibility. Exact schema, storage engine and transport remain proposals/open choices. Full design: PALACE_ARCHITECTURE.md; rationale/status: DECISIONS.md.

## Palace: what working looks like
These are acceptance scenarios derived from Brett's requirements, not completed tests:
- Attach or drop a file into a Windows conversation, see ingestion status, copy/paste normally, return later and follow the recorded history back to original sources.
- Ask a collaborative question, inspect each identified answer and peer response, then follow the combined answer to its contributing records. Large results remain available in full.
- Submit a Fairybread task through its thin interface; Palace delegates within available agent limits and returns traceable results without requiring the Palace desktop to be open.
- Select Idle, allow standing-order discussion, join it, and verify conversation content does not enter Palace's persistent logs. Resolve the remaining transition rules before implementing this acceptance check.
- Correct a durable memory with source/revision information, without silently overwriting another agent's contribution or confusing raw chat with semantic knowledge.

## Palace: problems and design questions
Summary loss is addressed by paired saves and source-following recall. Context limits require retrieval/paging while retaining originals. Concurrent writes need revision/conflict handling. Provider exhaustion needs visible partial/wait/reassignment outcomes. Free availability is not guaranteed. Idle persistence must be checked across all storage paths. Privacy/visibility prevents indiscriminate cross-project sharing. UI responsiveness requires background work. GUI prototype extraction caps do not satisfy archival requirements. Procedural/semantic storage relationship, peer loop stopping rules, job cancellation/recovery and service transport still need design work; do not claim these are settled.

## Palace: delivery and validation
Completed core baseline: provider adapters, toggles, parallel dispatch, synthesis and persisted question/final-answer session pairs. Code commit 3a3960a780d4686b26ba9a0a30f443f03a566936. Local GUI/attachment/session draft is uncommitted and unaccepted. Earlier simulated tests: 25 GUI/service/context cases and targeted core scripts passed; no live-provider acceptance.
Proposed bounded next milestone: review one shared task/contribution record with Brett; preserve an ordinary run's individual answers and synthesis, then let Brett inspect it. Subsequent candidates: original artifact storage, memory operations and peer review, delegated service and idle mode. This ordering is proposed, not a new release commitment. No application code changes are part of this records repair.

## Fairybread: linked development trail
Architecture source: https://drive.google.com/file/d/1Gq-NA_PRmwwpxXRw73O3PwyXMWABA3ex/view
Its filename says September 14 Rev2, while the document body identifies September 2 Rev3. Preserve this discrepancy; do not infer a new approval date from the filename.
Problem: serve large, inconsistent media libraries without forcing reorganisation. Design: authoritative server state, disposable clients, persistent manual corrections, deterministic baseline and optional provider-neutral AI. User AI Assist and permissioned Developer/Test mode are distinct; reports retain scenario, actions, evidence and provider identity.
Later scope/correction source: https://drive.google.com/file/d/10O9SOtBJe6XyNi3KWwWOX2Bc1W1w_qaJ/view
September 21 freezes V1 scope, separates optional advanced file management, and defers actual content examination to V2. Marker placement corrections explicitly supersede the earlier brief: markers go beside media in the normal .INCOMPLETE/.INCOMPLETE.AIRING season folder, not a separate missing-episodes folder. Optional filesystem changes default off; ordinary scanning does not authorize them. Existing .fbr identity state is retained; no FBx migration approved.
Next step recorded there: read-only catalogue audit/report using saved fixtures, after reading its implementation brief https://drive.google.com/file/d/1MVRbM6w5SbXCKCUvn7hOMSB4yG9yXpwC/view (indexed, not read in this reconciliation). Full source/register audit and current implementation verification remain outstanding. This note does not resume paused implementation.

## EvidenceBench: linked development trail
September 13 checkpoint: https://drive.google.com/file/d/1NfVceO8hfYxyv99lt0Vkyz-pg-yeEJoN/view
It explicitly names EvidenceBench and targets a Windows V1 in Electron with a desktop adapter, retaining existing React/evidence/search/export logic. Tauri is a possible V2 direction, not Palace's UI choice. It records native scanning/progress, cancellation, Save As, and a dismissible search-completion popup after at least four seconds of visible working state. Read-only Gmail setup/search/selective import is a later milestone after desktop preview validation.
Historical next step: Brett tests Desktop Checkpoint 1 and supplies EvidenceBench-build.log. Its reported 17 tests and stable SHA are historical, not freshly rerun or current remote verification. Local E:\Visual_studio\EvidenceWorkbench\README.md describes the earlier evidence prototype, immutable originals, provenance, optional AI and human review; it must not silently override the later desktop checkpoint. Current desktop branch/build status remains to audit.

## Shared capability, separate products
Brett explicitly identifies Palace reuse in Fairybread and EvidenceBench. Palace owns the reusable delegated/memory engine. Fairybread owns media identity and permitted media actions. EvidenceBench owns cases, originals, evidentiary provenance and human review. Exact EvidenceBench-Palace integration is not yet recovered/defined here; don't invent an agreed API. Cross-project source: https://docs.google.com/document/d/1QgEQQJ3AlPdNx7Te6h23kT2r20BF4YZpSBI0epIZP3I/edit

## Human design contribution and source coverage
Brett supplied the Windows interaction expectations, operating modes, complete-data requirement, thin-client reuse, learning constraints and paired-save correction. Earlier sources preserve his concrete Fairybread folder examples and EvidenceBench usability/desktop feedback. Assistant proposals are identified as such. This record makes those contributions inspectable rather than implying a one-line build request.
Palace original source inventory S1-S8 is retained in PROJECT_RECORD.md. Relevant sources were reviewed, but the complete conversations and every older project document were not exhaustively audited. Continue source recovery on each project's next work; no historical detail should be declared cancelled merely because it is absent here.
