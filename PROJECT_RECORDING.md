# Standing order: project planning, recall and paired saves

Revision: PROJECT-RECORDS-2026-09-29-R2
Authority: Brett's explicit instruction in task 01a0eb48-e3a9-78b1-95c6-cd91ca6071c9, 29 September 2026, beginning "OK so lets solve this". Applies across development projects. Google Drive is the durable project-memory home; local/Git copies support development and recovery.

## Every detailed checkpoint has a summary
At every meaningful design change, implementation milestone, handoff or pause, save BOTH a detailed checkpoint and a short matching summary on Google Drive. Use the same project/checkpoint/revision identifier. The summary links directly to the detailed checkpoint and its important sections. The detailed checkpoint links back to its summary and lists its predecessors and original sources. Maintain a stable START HERE index pointing to the latest verified pair. Do not leave the only current plan in chat.

The summary contains purpose, established direction, changes since the previous checkpoint, actual implementation status, key open issues, exact restart step and links. It is an index, not a replacement for source material. No arbitrary summary length limit may erase unique requirements from the detailed record.

## Recall before action
Read START HERE and the latest summary, then follow links into the full relevant plan, decision history and original evidence before proposing or changing work. Search older project records and task history when a requirement is missing, ambiguous or contradictory. A missing item in a recap is not a cancellation. An older decision changes only through an explicit superseding decision. Do not ask Brett to repeat material that can be recovered. Report inaccessible sources and unresolved gaps specifically; never invent recall or claim a complete audit from a partial search.

## Normal development pathway
Each project maintains these linked sections, reusing existing living plans/registers:
1. Discovery/brainstorm: problem, users, examples, candidate ideas and their origin.
2. Clarification: precise behaviour, scope, exclusions, constraints and open questions.
3. Design: architecture, data ownership, interfaces, memory/storage, integrations and alternatives with rationale.
4. Working experience: user journeys, screens, interactions and concrete acceptance examples.
5. Problems and tradeoffs: failure cases, privacy, costs, limits, conflicts and mitigations.
6. Delivery: bounded milestones, dependencies, learning/manual work, task states and restart step.
7. Validation: tests actually run, results, limitations and user acceptance separately.
8. History: dated decisions, corrections, rejected/superseded alternatives, source links and verified save receipts.
Unknown sections stay explicitly open; never backfill invented discussions to make the plan look complete.

## Attribution and state
Give consequential requirements stable IDs. Preserve Brett's contributions, examples and corrections, assistant proposals, rationale, date/source and changes over time. Distinguish AGREED, RECOVERED, PROPOSED, OPEN and SUPERSEDED; track implementation separately. Preserve original sources. Do not promote an assistant suggestion into user agreement. Cross-project interfaces have one owning design with references from each client project; do not merge product scopes or copy divergent specifications.

## Save transaction and verification
1. Reconcile sources and local changes. Update the full plan, decisions and task register.
2. Write a dated detailed checkpoint and matching summary locally; validate identifiers, source links and encoding.
3. Upload the detail, obtain its real URL, then upload the summary with that URL. Complete the reverse link and read back BOTH files. Check matching revision, required sections/decision IDs and both links. Never guess IDs.
4. Synchronize only appropriate authorized Git files; list excluded drafts. Record repository, branch, exact SHA, message, push result and live remote equality with timezone/time. Do not imply Git sync for a non-repository or files excluded from the commit.
5. Record the receipt and update stable START HERE only after the pair is verified. Read back the index and confirm it points to the verified pair. A failed partial save is INCOMPLETE, with its exact remaining step; preserve the last complete checkpoint pointer.
6. Keep historical pairs; corrections create a new revision with a supersedes link. Stable indexes/current summaries may be updated in place. Verify actual content, not just existence or metadata. Never claim success for a blocked write.

Routine authorized documentation saves do not need repeated permission. New external sharing, publication, credentials and protected actions still follow their applicable authorization rules. Save within the established private project-memory destination; do not change sharing settings.

## Learning and portability
Brett participates in bounded development steps and manual UI checks. No Computer Use, paid services, live AI calls or extra agents unless authorized. Saving is not proof every future assistant will retrieve a file: local startup instructions point to this index, and other interfaces must be given the START HERE link. No background automation is implied by this standing order.

## Earlier recording agreement (retained context)

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

## Education first; budget second

Brett's primary goal is to learn what is being built, how it is built and especially why each choice is made. Saving credits is secondary. Explain bounded changes before implementation, including purpose, alternatives and tradeoffs. Give Brett meaningful design, coding, inspection and testing work; running a completed command alone is not adequate participation. Do not use Computer Use, consume external credits, start agents or make live AI calls unless authorized. Documentation maintenance should reduce Brett's repetition, not create a review burden for every routine save.

Education is the standing default. An explicit request for shortcuts or more assistant-led work due to tiredness or reduced capacity is a session-only exception. It expires with that session and must not be carried into later work as a permanent preference.

## Coverage and portability

Retain a project source inventory with audited/unreviewed coverage and unresolved inconsistencies. A new framework does not mean all old project histories have been migrated. Keep startup instructions short and point them to the records. Other apps and web conversations must be given the current-record link; repository instructions are not a universal memory guarantee.
