# Palace session continuity

Run `python palace_cli.py` to ask a question. Recent session history is included for the enabled providers and the synthesis step. The CLI still handles one question per launch; launch it again to continue the conversation.

Completed exchanges are saved locally at `%LOCALAPPDATA%\Palace\session_context.jsonl`. Only the user question and the final displayed answer are stored, not each provider's draft. Runs with no usable answer do not add an exchange.

Use `python palace_cli.py --no-context` to skip reading and saving history for that question. This does not erase earlier history. Session history is shared with the providers enabled for the current run; provider-specific history permissions are not implemented yet.

Session history is separate from permanent semantic memory. Long-term retrieval remains opt-in, and nothing here promotes conversations into MemPalace.

The prompt includes at most 12,000 characters of recent history. Storage/read errors produce a warning while the answer remains available. Malformed recent history is left untouched. The history file is a single local conversation stream; simultaneous writers and multiple named sessions are not supported by this milestone.

## Verification

With the project dependencies installed:

```
python -B -m unittest test_session_context -v
python -B test_palace_cli.py
python -B test_orchestrator.py
python -B test_bootstrap.py
python -B test_synthesizer.py
python -B test_dispatcher.py
python -B test_memory_service.py
```

The session suite uses simulated providers and temporary storage, including two separate CLI processes. It does not contact model APIs or modify real conversation history.
