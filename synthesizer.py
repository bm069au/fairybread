from dataclasses import dataclass
from typing import Optional

from provider_result import ProviderResult
from providers import AIProvider


@dataclass
class SynthesisResult:
    text: Optional[str]
    provider_name: str
    contributors: tuple[str, ...]
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.text is not None and self.error is None


class PalaceSynthesizer:
    def __init__(
        self,
        provider_name: str,
        provider: AIProvider
    ):
        self.provider_name = provider_name
        self.provider = provider

    def synthesize(
        self,
        question: str,
        provider_results: dict[str, ProviderResult]
    ) -> SynthesisResult:

        successful = [
            (
                name,
                result.response.text
            )
            for name, result in provider_results.items()
            if (
                result.succeeded
                and result.response is not None
            )
        ]

        contributors = tuple(
            name
            for name, _ in successful
        )

        if not successful:
            return SynthesisResult(
                text=None,
                provider_name=self.provider_name,
                contributors=contributors,
                error="No successful provider responses."
            )

        # No need to spend another API call when only
        # one provider produced an answer.
        if len(successful) == 1:
            name, text = successful[0]

            return SynthesisResult(
                text=text,
                provider_name=name,
                contributors=contributors
            )

        responses = "\n\n".join(
            f"--- {name.upper()} ---\n{text}"
            for name, text in successful
        )

        prompt = f"""
You are the synthesis agent inside Palace.

ORIGINAL USER QUESTION:
{question}

INDEPENDENT AI RESPONSES:
{responses}

Create one strong final answer for the user.

Rules:
- Preserve useful points of agreement.
- Resolve differences using careful reasoning.
- Do not invent consensus where the agents disagree.
- Remove unnecessary repetition.
- Correct obvious errors when possible.
- Be direct and useful.
- Do not describe the synthesis process unless it matters to the answer.
""".strip()

        try:
            response = self.provider.generate(
                prompt
            )

            return SynthesisResult(
                text=response.text,
                provider_name=self.provider_name,
                contributors=contributors
            )

        except Exception as exc:
            return SynthesisResult(
                text=None,
                provider_name=self.provider_name,
                contributors=contributors,
                error=str(exc)
            )
