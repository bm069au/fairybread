# Palace architecture — working specification

Recorded 2026-09-29 from Brett's requirements. This is a specification, not a claim that the features already exist.

Current index: PROJECT_RECORD.md. Stable decisions and original sources: DECISIONS.md. Read these before treating this narrative as the entire historical plan.

## Product and learning workflow
Palace is a Windows desktop workspace for human/AI and AI/AI collaboration, with familiar drag/drop, attachments, copy/paste, readable conversation history and the underlying Palace memory architecture. PySide6 is the recovered UI framework choice.
Brett participates in implementation and hands-on testing. Explain and deliver bounded steps; do not take over the whole exercise. No Computer Use or credit-consuming services unless requested.

## Required operating modes
1. Collaborative answer: multiple AIs collaborate on the question, exchange identifiable contributions, produce a combined answer and record the query and work.
2. Delegated collaboration: a coordinator divides the question into tasks assigned according to each participating free agent's capabilities and actual limits. Preserve task dependencies, agent results, review and the final answer. Provider exhaustion must allow an explicit wait, reassignment or incomplete result; no silent paid fallback.
3. Idle conversation: agents follow a standing discussion order and converse among themselves. Brett can enter and participate in that same conversation. Idle conversation is not logged.
4. Logging is a cross-cutting facility for all non-idle activity, available through the GUI.

Proposed idle interpretation to confirm while implementing: idle conversation stays in volatile working memory, including Brett's contributions while the mode remains Idle. It is not written to history, transcripts, semantic memory, crash reports or content telemetry. Mode configuration and the standing order may be saved without saving conversation content. Joining alone does not turn logging on. A deliberate visible switch to a recorded mode starts logging from that point; it does not retroactively save earlier idle content. Explicitly saving a selected idle insight would be a separate user-directed action.
Palace can control its own storage, not an external AI provider's retention practices. Local-only participants are needed if conversation content must never leave the machine.

## Delegated Palace behind project thin clients
Established design, reaffirmed by Brett: delegated work is the Palace capability used by other projects, especially Fairybread. It sits behind the thin client. This was previously discussed and documented; today's reaffirmation is not a new architecture decision.

Confirmed architectural boundary:
Fairybread or another project -> thin client/adapter -> Palace delegated-work service -> participating agents, shared records, memory and artifacts.

The thin client presents the project's user experience, submits work and displays progress/results. Palace owns task decomposition, agent selection according to capabilities and limits, dependencies, peer review, synthesis and the corresponding recorded history. This service must be usable independently of the Palace desktop GUI; the desktop GUI is another interface to Palace, not a dependency of Fairybread.

Proposed service contract for implementation: submit a structured project task with relevant source/artifact references and permitted actions; receive a job identifier, progress/events, inspectable results and proposed actions. Keep project/task identity and visibility explicit so one project's context does not accidentally leak into another. Agree the transport and deployment separately rather than prematurely choosing HTTP, local IPC or hosting.

Fairybread-specific media operations remain in the appropriate project adapter/service. An AI's suggested action does not by itself authorize changing files or other external state. Preserve the existing thin-interface/private-Palace boundary; do not copy the orchestration and memory internals into each client.

This clarification makes delegated execution a primary reusable Palace capability, not merely an optional desktop chat mode. Build shared records and service boundaries to support it from the outset.

## Memory layers and source material
- Working context: the bounded set of current questions, referenced material, recent turns and task state provided for a particular agent call.
- Episodic history: full observable messages, task events, independent answers, peer responses, synthesis, errors and relevant source references for recorded work.
- Semantic memory: durable decisions, facts, rules and reusable knowledge, separate from the raw transcript, carrying source provenance, versions and visibility.
- Procedural memory: recurring workflows, instructions and preferences. Explicitly recorded in the September 14 portfolio register; omitted from later recaps without an explicit cancellation. Preserve the requirement. Its exact storage relationship to semantic memory remains open.
- Source/artifact store: original attachments, extraction results, generated files and large outputs. Full stored artifacts remain available through stable identifiers. This supports the memory layers rather than treating every file as permanent knowledge.

## Shared agent-readable structure
All participating agents need a common, documented Palace interface for reading permitted material and writing contributions. It must work across the existing providers.
Proposed operations: list/search records, describe schema, read a record, read an artifact range/page, append a contribution, propose a memory, update a record with its expected version, and inspect links/task state.
Prefer a typed service interface over letting agents rewrite the storage directly. Providers with different tool capabilities need adapters to the same operations, with validated requests/results. Do not assume every provider implements identical native tool calling.
Writes retain authorship and revisions; peer contributions are never silently overwritten. Shared material is readable to the participating agents, subject to the established explicit private/local-only/provider visibility rules.

Proposed contribution envelope:
- record/event ID and schema version
- conversation ID, run ID and task ID
- agent identity, provider and model identity
- contribution type: question, task, source, answer, critique, synthesis, decision, error
- timestamp and status: partial, complete, failed, superseded
- reply-to, dependencies and cited source/artifact IDs
- full content or a content/artifact reference
- visibility and revision
This lets agents recognize who said what, which question it answers, which peer message it responds to, and where the full evidence lives.

## Full results versus model context limits
Do not apply arbitrary truncation that loses returned answers or original attachment data. Preserve complete observable outputs for recorded work. If a provider indicates generation was cut off, mark the result incomplete and continue where supported; do not label it complete silently.
No finite model can receive unlimited data in one request. Separate durable full storage from each call's context window. Supply a manifest, relevant excerpts, summaries with links, and operations for retrieving further ranges/pages. Summaries supplement source records rather than replace them. Large generated answers can be assembled in sections with stable references and displayed/exported in full.
Delegation uses provider context/output limits, current quota/rate constraints, availability and capability. Unknown quota is unknown, not assumed free capacity. These controls manage calls without silently deleting the user's data.

## GUI behaviour
- Familiar chat composer and transcript, standard Windows clipboard and drag/drop/file selection.
- Conversations can be followed chronologically, with task branches and peer replies inspectable.
- Combined answer is easy to find; independent contributions and provenance remain accessible.
- Clear mode selector, agent status and pause/stop controls, especially for idle operation.
- Attachments show ingestion state and supported capabilities; never imply unread files were understood.
- Inspectable recorded history/logs and memory; active context remains distinguishable from semantic memory.
- Worker execution keeps the UI responsive.

## Logging boundary
For non-idle modes log the observable work: user requests, attachment/artifact references, dispatch/task decisions, actual agent responses, peer exchanges, synthesis, memory read/write events, failures and usage information when provided. Do not log credentials or authorization headers. 'Everything' does not promise access to a provider's hidden internal reasoning.
For idle mode enforce the no-content-persistence policy across every component rather than only hiding a transcript in the UI. In-memory context must still allow participants to understand the ongoing conversation.

## Current implementation and gaps
Committed and synced core: 3a3960a780d4686b26ba9a0a30f443f03a566936 on feature/provider-neutral-core, https://github.com/bm069au/palace.git. Last independently verified remote match: 2026-09-29 13:55:27 +09:30.
The existing dispatcher asks providers in parallel and synthesis combines results. The current stored session history contains the user question and final answer only; it does not preserve all peer contributions or implement the common Palace read/write interface.
Local uncommitted GUI work: palace_gui.py, attachment_service.py, session_store.py, test_palace_gui.py, and changes to palace_cli.py and requirements.txt. The desktop/session suite passed 25 automated tests; existing targeted core regression scripts passed. A preview window was visually inspected, then Brett stopped Computer Use.
Prototype attachments currently extract bounded excerpts and do not archive original files. Those limits do not meet the full artifact-preservation requirement above. The prototype is not the complete architecture.
No delegated/idle mode or durable semantic-memory workflow has been implemented. No new implementation is claimed by this specification.

## Proposed implementation order with Brett
1. Review this structure and implement the shared event/record schema and store with a small, inspectable example.
2. Route one ordinary question through it, preserving all agent contributions, synthesis and sources; display that history in the GUI.
3. Replace excerpt-only attachments with preserved artifacts and range-based access.
4. Add controlled semantic-memory read/write operations and peer reply/review rounds.
5. Add delegated execution using agent limits, then idle operation with a tested no-persistence boundary and human participation.
Use bounded milestones, explain the change, let Brett perform the hands-on check, and save checkpoints with accurate Git sync status.

## Save status
Consult PROJECT_RECORD_LINKS.md for the verified paired Drive checkpoint and Git receipt. Historical blocked uploads were not successful saves. GUI code remains a separate local draft.
