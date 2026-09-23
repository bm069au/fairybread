# Palace Project Savepoint — 2026-09-23

## Current milestone

Palace now has a working multi-provider council, provider runtime toggles, existing MemPalace retrieval mapped, and the first persistent session-context service working.

## Working live provider pipeline

Current flow:

credentials
→ provider loader
→ provider registry
→ concurrent dispatcher
→ independent provider answers
→ synthesis
→ Palace CLI

Provider modules currently present:

- Gemini
- Groq
- Mistral
- Cerebras
- Cohere
- OpenAI

Provider loader successfully loads:

- gemini
- groq
- mistral
- cerebras
- cohere

## Runtime provider toggles

Added:

- palace_config.json
- palace_config.py

Current enabled providers:

- Gemini: ON
- Groq: ON
- Mistral: ON
- Cohere: ON

Current disabled providers:

- Cerebras: OFF
- OpenAI: OFF

Important design decision:

Build the provider-toggle mechanism first.
Rules governing paid/free/idle/work modes will be decided later.

Credentials and provider enable/disable state remain separate.

## Provider investigation

Full Palace smoke test worked successfully.

Successful contributors during initial full run:

- Gemini
- Groq
- Cohere

Mistral failed during multi-provider use with HTTP 429 rate limit.
Its standalone provider test passes.

Cerebras failed during multi-provider use with HTTP 402 payment/quota.
Its standalone provider test had passed.

Astra researched this separately.

Current conclusion:

- Keep Mistral provisionally.
- Do not treat its 429 as a Palace code bug.
- Cerebras is unsuitable as a required permanently-free Palace agent under its current access model.
- Cloudflare Workers AI / GLM-4.7-Flash is the strongest candidate replacement.
- OpenRouter may be useful as a low-volume fallback.
- No provider replacement work has yet been implemented.

## Existing MemPalace system

Current installed package:

C:\Users\moore\AppData\Roaming\Python\Python313\site-packages\mempalace

Current old wings:

- gpt_palace — 79 drawers
- grok_palace — 1 drawer
- test_palace — 1 drawer

Palace MemoryService can successfully call:

python -m mempalace search

The current Palace orchestrator already supports optional memory retrieval through:

include_memory=True

The current Palace CLI does NOT enable memory by default.

## Old memory architecture findings

Old gpt_palace memory is mixed-purpose.

It contains:

- useful distilled memories
- interaction/Q&A records
- generated AI answers
- Python source code
- stale indexed files
- multiple historical capture streams
- build/dist copies

Important discovery:

The old MemPalace indexed .py files as readable project knowledge.
This caused source code such as ask_gpt.py to be returned during memory retrieval.

Therefore:

DO NOT simply enable the old gpt_palace wing globally as Palace conversational memory.

The old system should be treated as historical/source material while the new memory architecture is designed.

## Memory architecture direction

Palace needs separate layers.

### 1. Active / working context

Current conversation and current task state.

Small and fast.

### 2. Episodic / session memory

Durable record of:

- what happened
- what changed
- decisions
- failures
- current project state
- next step

Allows Palace to resume work after a break or restart.

### 3. Long-term semantic memory

Distilled durable information such as:

- decisions
- rules
- preferences
- architecture
- facts
- reusable patterns
- lessons

Raw conversation/context must NOT automatically become semantic memory.

Future memory/catalogue design may include:

- catalogue/call cards
- source provenance
- type
- summary
- importance
- wing/domain
- links/cross references
- visibility/privacy
- allowed providers
- local-only memory
- sensitivity
- recency/relevance

Goal:

Large persistent Palace memory with only a small relevant working set loaded into active context.

## Session Context Service

Created:

context_service.py

Current functionality:

- appends conversation/context turns to persistent JSONL
- records timestamp
- records role
- records content
- loads recent context up to a character limit

Default storage:

%LOCALAPPDATA%\Palace\session_context.jsonl

Persistence test succeeded across separate Python processes.

Test content:

USER: Context test

This proves basic durable session-context persistence.

The context service is NOT yet connected to PalaceOrchestrator or Palace CLI.

## Security / visibility principle

Long-term design must not automatically send every retrieved memory to every external provider.

Future memories/context may require visibility rules such as:

- shared
- local-only
- provider-specific
- private
- secret

Provider access policy will be designed later.

## Paid-provider principle

Paid AI APIs may eventually be available inside Palace.

However:

- toggles are being built first
- usage rules will be designed later
- paid agents must eventually be controllable independently
- normal/idle chat must not accidentally create uncontrolled API cost

No automatic paid-provider policy has been implemented yet.

## Current files changed/added today

Likely relevant current changes:

- provider_loader.py
- palace_cli.py
- palace_config.json
- palace_config.py
- context_service.py
- Palace_Project_Savepoint_2026-09-23.md

Existing provider files/tests were also exercised.

## Verification completed

Confirmed:

- credentials JSON valid
- Cohere provider standalone test passed
- Mistral provider standalone test passed
- Cerebras provider standalone test passed
- provider_loader imports successfully
- all configured providers can be instantiated
- full Palace CLI pipeline works
- provider toggle reader works
- Palace respects provider toggles
- ContextService writes persistent context
- ContextService reads persistent context in a separate Python process

pytest is not currently installed in the active Python 3.13 environment, so the complete pytest suite was not run.

## Immediate restart point

Continue from context_service.py.

Next task:

Design and implement the clean integration of persistent session context into Palace without conflating it with long-term semantic memory.

Do not reconnect the old whole-Q&A memory-save pipeline.

Preserve the existing privacy behaviour where long-term memory is not queried unless explicitly enabled.

After session context is working, design promotion from session history into clean durable Palace memory.
