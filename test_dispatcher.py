from dispatcher import ProviderDispatcher
from provider_registry import ProviderRegistry
from providers import AIProvider, ProviderResponse


class FakeProvider(AIProvider):
    def __init__(self, name: str):
        self.name = name

    def generate(self, prompt: str) -> ProviderResponse:
        return ProviderResponse(
            text=f"{self.name}: {prompt}",
            model=f"{self.name}-model",
            provider=self.name
        )


def test_dispatcher():
    registry = ProviderRegistry()

    registry.register("openai", FakeProvider("openai"))
    registry.register("gemini", FakeProvider("gemini"))
    registry.register("claude", FakeProvider("claude"))

    dispatcher = ProviderDispatcher(registry)

    all_responses = dispatcher.dispatch("Hello Palace")

    assert len(all_responses) == 3
    assert all_responses["openai"].text == "openai: Hello Palace"
    assert all_responses["gemini"].text == "gemini: Hello Palace"
    assert all_responses["claude"].text == "claude: Hello Palace"

    selected_responses = dispatcher.dispatch(
        "Selective test",
        provider_names=["openai", "claude"]
    )

    assert len(selected_responses) == 2
    assert "openai" in selected_responses
    assert "claude" in selected_responses
    assert "gemini" not in selected_responses


if __name__ == "__main__":
    test_dispatcher()
    print("Dispatcher test passed.")
