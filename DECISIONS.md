# Palace decision register

Revision: PALACE-RECORDS-2026-09-29-R1. This preserves established decisions; it does not declare the full historical audit finished. Source keys resolve in PROJECT_RECORD.md. Implementation status is independent of design status.

## P-001 — Reusable delegated service behind thin clients
Status: AGREED, reiterated by Brett on 2026-09-29 as an existing decision, not a new proposal.
Palace owns delegated work for other projects, especially Fairybread. Thin clients/adapters submit tasks and expose results; Palace handles agent coordination and memory. Keep Palace usable without its own GUI being open. Share capabilities without making all projects one monolithic app. Fairybread-specific actions remain in its adapter/service.
Sources: S1, S2, S3; S7 messages 'the delegated work is the part we will be using on our other projects esp. Fairybread. That is the part that goes behind the thin client' and 'we already defined this, you documented it'. The exact earliest thin-client wording has not yet been located; do not fabricate its original date.
Implementation: NOT STARTED as a delegated-service contract. Existing parallel dispatch is not task delegation.

## P-002 — Windows GUI in PySide6
Status: RECOVERED PRIOR DECISION, reaffirmed direction in S7.
Use PySide6 and keep GUI widgets separate from Palace services. Familiar drag/drop, file attachment, copy/paste, readable history, simple visible state, optional details and background execution are requirements. Provider status needs meaning beyond colour alone.
Source: S6 assistant message 2b2fd2f6-e97e-4fbc-96bb-25cf4caa8461 explicitly chooses PySide6; S7 user requirements.
Implementation: LOCAL DRAFT with simulated tests; incomplete user acceptance. Proposed shell from S6 was not previously implemented.

## P-003 — Memory is layered, with provenance
Status: RECORDED DESIGN across S1/S2/S4 and current S7.
Working context is the small relevant active set. Episodic memory records events and conversations. Semantic memory carries distilled facts/decisions. PROCEDURAL MEMORY holds repeatable workflows, instructions and preferences; it appears explicitly in S1 and was omitted from later recaps without a documented cancellation. Preserve this requirement. Decide its storage relationship to semantic memory during implementation rather than silently deleting it.
Keep provenance, source/agent identity, conflicting interpretations and correction/version history. Raw Q&A is not automatically semantic memory. Original sources/artifacts support these memory layers.
Implementation: basic persisted session context exists. Durable semantic/procedural workflows, common record structure and full episodic event capture are NOT STARTED.

## P-004 — Provider independence and failure isolation
Status: RECORDED DESIGN, S2/S4/S6; enough current providers reaffirmed in S7.
Agents/providers are replaceable and failures must not collapse the group. Direct integrations are preferred; gateway/model identity must not be confused with independent intelligence. Keep credentials separate from enablement. Preserve contributor identity and disagreement in synthesis. Do not expand the provider roster instead of advancing memory/UI.
Implementation: core adapters, parallel dispatch, toggles and synthesis COMMITTED. Detailed agent identity/peer interaction remains incomplete.

## P-005 — Collaboration mode
Status: AGREED requirement, S7 'the system should work like this interface...' message.
Multiple AIs collaborate on questions, recognize and respond to each other's contributions, and produce a combined answer. Record the query, individual work and result.
Implementation: parallel answers plus synthesis exists; iterative peer exchanges and full recorded contribution history do not.

## P-006 — Delegated mode respects free-agent limits
Status: AGREED requirement, S7, with routing rationale in S2/S3.
Decompose work and assign it according to each free agent's capabilities and limits. Preserve task dependencies, partial/failed results and review. The eventual compute economy uses the cheapest reliable agent and escalates only under explicit policy. No silent paid fallback.
Implementation: NOT STARTED. Do not present parallel identical prompts as delegation.

## P-007 — Idle mode with human participation, no log
Status: AGREED core requirement, S7.
Agents converse under a standing instruction; Brett can drop into their conversation. Idle conversation is not logged. Other modes are logged.
OPEN detail: whether joining remains unlogged was proposed as the default but not separately confirmed. Also open: explicit saving of selected insights, recording transitions, persistence of standing orders and restart behaviour. Do not silently convert assistant proposals into agreement.
Implementation: NOT STARTED.

## P-008 — Shared readable/writable Palace structure
Status: AGREED requirement, S7; shared state/provenance direction in S1/S2.
All participating AIs must be able to understand the shared data and structure and read/write Palace through consistent operations. Preserve author, source, task/reply relationships and revisions. Earlier private/local-only/provider visibility requirements still apply.
PROPOSED implementation: typed service API, contribution envelope, version-checked updates. Exact schema, transport and backing database are open. A graph database discussed for a competition MVP is not automatically the selected production store.
Implementation: NOT STARTED.

## P-009 — Preserve full data; bounded context is not data loss
Status: AGREED functional requirement, S7.
Large answers and peer outputs must remain recognizable and accessible. Do not arbitrarily discard returned content. Preserve original attachments and full recorded outputs; summaries/excerpts are access aids, not replacements. Model request/output limits still require paging, references or continuation rather than claiming infinite context.
Implementation: prototype attachment caps are a LOCAL DRAFT limitation, not the final policy. Original artifacts/full agent histories are not yet archived.

## P-010 — Record all non-idle observable work
Status: AGREED requirement, S7.
Logs/history must cover questions, sources, agent contributions, peer replies, synthesis and relevant operations/failures. Keep it navigable in the GUI. Never store credentials in logs or claim access to hidden model reasoning. Apply the idle exception throughout persistence paths.
Implementation: only question/final-answer session pairs are stored in the committed core. Full logging is NOT STARTED.

## P-011 — Protect privacy, actions and IP boundaries
Status: RECORDED DESIGN, S3/S4.
Long-term retrieval remains opt-in. Memories need visibility such as shared, private, provider-specific and local-only; do not send every retrieved record to every provider indiscriminately. Discussion does not grant authority for external actions. Keep valuable orchestration/memory internals behind deliberate private/service boundaries and do not publish them accidentally through client or competition code.
Implementation: opt-in long-term retrieval exists. Per-record visibility and action authorization services are not complete.

## P-012 — Education is the primary working purpose
Status: AGREED working instruction, S7.
This is an education exercise, not 'Ash does everything'. Its primary purpose is to teach Brett what is being built, how it is built and especially why each decision is made. Reduced credit use is a secondary benefit. Explain a bounded step before implementing it, including its purpose, relevant alternatives and tradeoffs. Give Brett a meaningful role in design, coding, inspection or hands-on testing; merely asking him to run finished code is insufficient. No Computer Use or credit-consuming services unless requested. A stated session window is not authorization for autonomous idle work or spend.

Correction 2026-09-29: Brett explicitly corrected the priority after the source-ID exercise: "To reduce credit usage but Primarily so I CAN LEARN. This is an education exercise to teach me what we do, how we do it and specially.. WHY we do it." This supersedes any wording that frames participation mainly as a cost-saving measure.

## P-013 — Save and actually recover the full plan
Status: AGREED standing requirement, S5/S7.
Save meaningful changes and pauses in the existing Google Drive project-memory area, synchronize appropriate Git work, and record verified sync results. Keep a current plan and decision register with original source links; resumptions must read/reconcile them. Do not merely accumulate snapshots or promise memory without a verified save.

## Corrections and open work
- 2026-09-29: recovered P-002 from original conversation; absent from prior handover.
- 2026-09-29: restored procedural memory in P-003 from S1. Later omission did not supersede it.
- 2026-09-29: corrected P-001 from 'new clarification' to established design reaffirmed by Brett.
- 2026-09-29: classified idle persistence details and typed API as proposals/open, not agreed implementation.
- Still needed: audit remaining older Palace conversations and project-specific records. Preserve the source inventory's incomplete status until done.

## P-014 - Mandatory paired summaries and detailed checkpoints
Status: AGREED standing instruction, Brett 2026-09-29, current task message beginning "OK so lets solve this". Every detailed savepoint must create a matching linked summary on Google Drive. Keep the normal development pathway, rationale, human contributions and cross-project links. Recall must follow relevant source detail before acting; brevity is not authority to drop decisions. Implementation: documentation workflow and startup pointers, not a running background service. See PROJECT_RECORDING.md.
