from provider_result import ProviderResult
from providers import ProviderResponse
from synthesizer import PalaceSynthesizer


class FakeProvider:
    def __init__(self):
        self.last_prompt = None

    def generate(self, prompt):
        self.last_prompt = prompt

        return ProviderResponse(
            text="Combined Palace answer",
            model="fake-model",
            provider="fake"
        )


def test_multiple_responses():
    provider = FakeProvider()

    synthesizer = PalaceSynthesizer(
        "gemini",
        provider
    )

    results = {
        "gemini": ProviderResult(
            provider_name="gemini",
            response=ProviderResponse(
                text="Gemini answer",
                provider="gemini"
            )
        ),
        "groq": ProviderResult(
            provider_name="groq",
            response=ProviderResponse(
                text="Groq answer",
                provider="groq"
            )
        )
    }

    result = synthesizer.synthesize(
        "Test question",
        results
    )

    assert result.succeeded
    assert result.text == (
        "Combined Palace answer"
    )

    assert result.contributors == (
        "gemini",
        "groq"
    )

    assert "Gemini answer" in (
        provider.last_prompt
    )

    assert "Groq answer" in (
        provider.last_prompt
    )

    assert "Test question" in (
        provider.last_prompt
    )


def test_single_response():
    provider = FakeProvider()

    synthesizer = PalaceSynthesizer(
        "gemini",
        provider
    )

    results = {
        "gemini": ProviderResult(
            provider_name="gemini",
            response=ProviderResponse(
                text="Only answer",
                provider="gemini"
            )
        )
    }

    result = synthesizer.synthesize(
        "Test question",
        results
    )

    assert result.succeeded
    assert result.text == "Only answer"

    # No synthesis API call needed.
    assert provider.last_prompt is None


if __name__ == "__main__":
    test_multiple_responses()
    test_single_response()

    print("Synthesizer tests passed.")
