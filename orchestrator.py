from dataclasses import dataclass
from typing import Optional

from dispatcher import ProviderDispatcher
from memory_service import MemoryService
from provider_result import ProviderResult


@dataclass
class PalaceRunResult:
    question: str
    prompt: str
    memory_context: str
    memory_error: Optional[str]
    provider_results: dict[str, ProviderResult]


class PalaceOrchestrator:
    def __init__(
        self,
        memory_service: MemoryService,
        dispatcher: ProviderDispatcher
    ):
        self.memory_service = memory_service
        self.dispatcher = dispatcher

    def _build_prompt(
        self,
        question: str,
        memory_context: str
    ) -> str:
        return f"""
You are an AI working inside the Palace system.

MEMORY CONTEXT:
{memory_context}

USER QUESTION:
{question}

Rules:
- Use the memory context when it is relevant.
- Do not pretend information came from memory when it did not.
- If the memory is weak or unrelated, answer normally.
- Be accurate and practical.
""".strip()

    def run(
        self,
        question: str,
        provider_names: list[str] | None = None
    ) -> PalaceRunResult:

        memory_result = self.memory_service.search(question)

        if memory_result.succeeded:
            memory_context = memory_result.context
        else:
            memory_context = "Memory unavailable."

        prompt = self._build_prompt(
            question,
            memory_context
        )

        provider_results = self.dispatcher.dispatch(
            prompt,
            provider_names=provider_names
        )

        return PalaceRunResult(
            question=question,
            prompt=prompt,
            memory_context=memory_context,
            memory_error=memory_result.error,
            provider_results=provider_results
        )
