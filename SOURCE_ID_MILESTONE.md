# Source ID milestone
Revision: PALACE-SOURCE-IDS-2026-09-29-R1

Brett confirmed September 23 was the last coding day before September 29. Today he requested a bounded learning session with around one hour available. This milestone implements the source-reference foundation described in the existing planning record, not automatic memory promotion.

New session entries have UUID source IDs. append returns its ID; append_exchange returns question/answer IDs and the answer stores reply_to. read_entry resolves an ID to the full stored entry independently of prompt character limits. IDs persist across processes. Identical messages have distinct IDs. Duplicate IDs and corrupt records raise errors rather than returning an ambiguous source. Unknown IDs return None.

Older ID-less history remains readable as context and is not rewritten. Migration of old entries is deferred. A source reference currently requires both the owning session store and entry ID; no global multi-project resolver, agent-facing retrieval tool or permission system is claimed. Full peer history, concurrency control and durable-memory promotion remain unfinished. Existing privacy opt-in and provider behaviour are unchanged.

Validation: python -B -m unittest test_source_ids test_session_context: 12 tests passed offline. Includes separate-process full Unicode retrieval, context clipping, reply relationships, legacy preservation, duplicate/corrupt handling and existing orchestration/CLI context regressions. No live providers or paid services used.

Brett's hands-on step: from E:\Visual_studio\Palace run python source_id_demo.py save, then run the read command printed by the script. It stores a labelled learning example in ignored .learning/source-id-demo.jsonl, separate from normal session history. Confirm the same source ID and original text return. Manual acceptance is pending.

Next bounded step after that check: define a proposed durable-memory record referencing the source store/entry ID, summary and full detail. Human-review versus rule-based automatic promotion remains OPEN; Brett's agreement to start did not settle that question. Preserve the existing P-001 through P-014 requirements.

Previous full planning record: https://drive.google.com/file/d/1Bo_aQxUdyA43AHCxEoZT6ceuo48nuPi0/view
Stable index/receipt: https://drive.google.com/file/d/1G9HLoa2l9i_JfjMkJb9z5GFVTn_6eZcP/view
Matching summary: supplied in the Drive copy after its ID is assigned.
