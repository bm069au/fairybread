# Palace memory-review foundation — summary

Revision: PALACE-MEMORY-REVIEW-2026-09-29-R1
Detail: https://drive.google.com/file/d/1pI8eZhdafrM2WEVes0Ko4ydHr6CFKhSA/view

Brett built and manually checked the first read-only Memory Review foundation in the existing PySide6 draft. A checkable button opens and hides a docked right-hand panel. `MemoryProposalService.list_proposals()` now supplies validated newest-first metadata without copying full detail into the list; complete detail remains retrievable by proposal ID. GUI tests use disposable proposal storage rather than Brett's real Palace data.

Validation: 4 memory-proposal tests and 17 GUI tests passed. Brett manually confirmed panel open/hide behaviour in the local no-API preview. No live providers, paid services, Computer Use or additional agents were used. A harmless Qt fallback-font warning remains a packaging concern.

Git: `bm069au/palace`, branch `feature/provider-neutral-core`, implementation checkpoint `ee315dd2e0198b3944b5a9f3ff894e53cf4d5902`, message `Add Palace GUI and memory review foundation`. Push succeeded and the live remote matched at 2026-09-29 20:07:38 +09:30.

The panel does not yet display records. Exact restart: add the already-defined failing GUI test for summary-only listing, create `proposal_list`, refresh it when the panel opens, rerun tests, and let Brett inspect the result before implementing detail display or Approve/Edit/Reject.

Brett's education-first workflow was tightened: unfamiliar architecture terms must be explained with their meaning, place in the full flow, purpose, example and unfinished behaviour before coding begins.
