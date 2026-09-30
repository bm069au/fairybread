# Palace Memory Review list — summary

Revision: PALACE-MEMORY-REVIEW-LIST-2026-09-30-R1
Detail: https://drive.google.com/file/d/1CY6lQ6PLJdZ26gNyzHKHbZyp_ZY1eAdV/view

Palace's docked Memory Review panel now lists lightweight proposed-memory records when opened. Each row shows status, memory type and summary, retains the proposal ID for later retrieval, and deliberately excludes full detail. Empty storage displays a clear message. Demo conversations and proposals now share separate preview-only storage, and an eight-pixel centre-panel buffer prevents the splitter from drawing over controls.

Brett wrote and repaired the bounded GUI change, ran the focused and combined tests, diagnosed the visual overlap and confirmed the spacing fix in the no-API Windows preview. The final combined run passed 22 tests. The Qt bundled-font warning did not affect Windows Segoe UI rendering.

P-016 now records that a provider or tool refusal describes that participant's access boundary; Palace must not silently convert it into a truth claim or suppress other agents' independently permitted contributions. Typed event records and synthesis enforcement remain unimplemented.

Git implementation checkpoint: `42e26b771474d8d4ddf4e7d549c7277b0eba445d`, branch `feature/provider-neutral-core`, message `List memory proposals in Palace review panel`. Push succeeded and the live remote matched at 2026-09-30 13:18:46 +09:30.

Exact restart: add the failing selection/detail test, retrieve the complete proposal by its stored ID, add a clearly separated read-only detail area, and inspect the populated preview before designing Approve/Edit/Reject.
