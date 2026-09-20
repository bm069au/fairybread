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


class FailingProvider(AIProvider):
    def generate(self, prompt: str) -> ProviderResponse:
        raise RuntimeError("Simulated provider failure")


def test_dispatcher():
    registry = ProviderRegistry()

    registry.register("openai", FakeProvider("openai"))
    registry.register("gemini", FailingProvider())
    registry.register("claude", FakeProvider("claude"))

    dispatcher = ProviderDispatcher(registry)

    results = dispatcher.dispatch("Hello Palace")

    assert len(results) == 3

    assert results["openai"].succeeded
    assert results["openai"].response.text == "openai: Hello Palace"

    assert not results["gemini"].succeeded
    assert results["gemini"].response is None
    assert results["gemini"].error == "Simulated provider failure"

    assert results["claude"].succeeded
    assert results["claude"].response.text == "claude: Hello Palace"

    selected_results = dispatcher.dispatch(
        "Selective test",
        provider_names=["openai", "claude"]
    )

    assert len(selected_results) == 2
    assert "openai" in selected_results
    assert "claude" in selected_results
    assert "gemini" not in selected_results


if __name__ == "__main__":
    test_dispatcher()
    print("Dispatcher failure-isolation test passed.")
