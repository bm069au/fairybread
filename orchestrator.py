from dataclasses import dataclass
from typing import Optional

from dispatcher import ProviderDispatcher
from memory_service import MemoryService
from provider_result import ProviderResult
from synthesizer import PalaceSynthesizer, SynthesisResult


@dataclass
class PalaceRunResult:
    question: str
    prompt: str
    memory_context: str
    memory_error: Optional[str]
    provider_results: dict[str, ProviderResult]
    synthesis: Optional[SynthesisResult] = None

    @property
    def contributors(self) -> list[str]:
        return [
            name
            for name, result
            in self.provider_results.items()
            if result.succeeded
        ]

    @property
    def final_answer(self) -> Optional[str]:
        if (
            self.synthesis
            and self.synthesis.succeeded
        ):
            return self.synthesis.text

        for result in self.provider_results.values():
            if (
                result.succeeded
                and result.response is not None
            ):
                return result.response.text

        return None


class PalaceOrchestrator:
    def __init__(
        self,
        memory_service: MemoryService,
        dispatcher: ProviderDispatcher,
        synthesizer: Optional[
            PalaceSynthesizer
        ] = None
    ):
        self.memory_service = memory_service
        self.dispatcher = dispatcher
        self.synthesizer = synthesizer

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
        provider_names: list[str] | None = None,
        include_memory: bool = False
    ) -> PalaceRunResult:

        if include_memory:
            memory_result = self.memory_service.search(
                question
            )

            if memory_result.succeeded:
                memory_context = (
                    memory_result.context
                )
                memory_error = (
                    memory_result.error
                )
            else:
                memory_context = (
                    "Memory unavailable."
                )
                memory_error = (
                    memory_result.error
                )

        else:
            memory_context = (
                "Memory not included."
            )
            memory_error = None

        prompt = self._build_prompt(
            question,
            memory_context
        )

        provider_results = (
            self.dispatcher.dispatch(
                prompt,
                provider_names=provider_names
            )
        )

        synthesis = None

        if self.synthesizer:
            synthesis = (
                self.synthesizer.synthesize(
                    question,
                    provider_results
                )
            )

        return PalaceRunResult(
            question=question,
            prompt=prompt,
            memory_context=memory_context,
            memory_error=memory_error,
            provider_results=provider_results,
            synthesis=synthesis
        )
