# Project recording agreement

Established 2026-09-29 after repeated failures to recover agreed project plans. Applies to project design and implementation work with Brett. Use an existing living register when present; do not create a competing source of truth.

## Maintain the plan, not just a stopping-point summary

Each project needs one stable START HERE/current record pointing to its full plan, decision history, task register, source material and latest verified checkpoint. Dated savepoints are historical evidence, not replacements for this record.

For each meaningful design decision preserve: a stable identifier, precise requirement, rationale, relationships/dependencies, source/date, status and any explicit replacement decision. Keep functional details, exceptions and rejected alternatives when they explain why the decision exists. Concision must not erase unique requirements. User corrections update the relevant entry and change history immediately; do not merely acknowledge them in chat.

Distinguish AGREED, RECOVERED PRIOR RECORD, PROPOSED, SUPERSEDED and OPEN. Track implementation separately as NOT STARTED, LOCAL DRAFT, COMMITTED, VERIFIED or RELEASED. A proposal is not agreement; agreement is not implementation; passing simulated tests is not live acceptance. Missing from a newer summary does not mean cancelled. Keep a source link or recoverable conversation title/ID and exact message anchor for consequential decisions.

## Resume protocol

1. Resolve the actual project; do not assume the task's working folder is correct.
2. Read its current record, decisions, full relevant design and standing instructions. Check the index of older source records for relevant omissions.
3. Compare the local state, latest Drive record and Git. Record discrepancies, not assumptions. Read relevant original material before proposing a replacement design.
4. Briefly state the established direction, actual implementation state and next bounded step. Do not ask Brett to repeat a documented decision just because it is absent from recent chat.
5. If a source cannot be recovered, label the gap and continue independent work. Do not invent recall or say the audit is complete.

## During work and at a pause

Maintain the current plan as decisions are made, including design-only sessions. At a meaningful change, milestone, handoff or stop, update decisions, tasks, implementation state, remaining work and the exact restart point. Keep old source documents intact. If a later decision supersedes an older one, record which decision replaced it and why.

Preserve the full agreed design separately from the short handover. Track cross-project contracts in both projects' indexes, linking to a single owner for the detailed design. Do not copy Palace internals into client projects through divergent descriptions.

## Verified save receipt

Use explicit independent states:
- Local: path, revision/date and readback result.
- Git: repository, branch, commit SHA/message, pushed or not, live remote comparison and verification time. Dirty/untracked work is listed separately. Never call the whole project synchronized while relevant local drafts are excluded.
- Google Drive: exact file ID/URL, verified folder, revision/date and content readback result. A blocked or failed write remains BLOCKED/NOT SAVED; it is not a save.

Prefer updating a stable current-record Drive file in place once created. Keep dated checkpoints as history where useful and preserve links to them. Compare a revision marker and required decision IDs after readback so an empty/wrong/stale file is detected. Do not promise that saving a file guarantees future recall; the resume protocol is also required.

When a tool blocks a save, finish the local record, state precisely which copy remains unsaved, and obtain the needed approval without pretending the checkpoint completed. Do not bypass an approval rejection. Do not repeat broad assurances such as 'everything is recorded' when source coverage is partial.

## Learning and budget

Brett wants to participate, not have the assistant do everything. Explain bounded changes and hand over the relevant manual checks. Do not use Computer Use, consume external credits, start agents or make live AI calls unless authorized. Documentation maintenance should reduce Brett's repetition, not create a review burden for every routine save.

## Coverage and portability

Retain a project source inventory with audited/unreviewed coverage and unresolved inconsistencies. A new framework does not mean all old project histories have been migrated. Keep startup instructions short and point them to the records. Other apps and web conversations must be given the current-record link; repository instructions are not a universal memory guarantee.
