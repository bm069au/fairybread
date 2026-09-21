import threading
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

class SynchronisedProvider(AIProvider):
    def __init__(self, name: str, barrier: threading.Barrier):
        self.name = name
        self.barrier = barrier

    def generate(self, prompt: str) -> ProviderResponse:
        self.barrier.wait(timeout=2)

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

    barrier = threading.Barrier(3)

    parallel_registry = ProviderRegistry()
    parallel_registry.register(
        "one",
        SynchronisedProvider("one", barrier)
    )
    parallel_registry.register(
        "two",
        SynchronisedProvider("two", barrier)
    )
    parallel_registry.register(
        "three",
        SynchronisedProvider("three", barrier)
    )

    parallel_dispatcher = ProviderDispatcher(
        parallel_registry,
        max_workers=3
    )

    parallel_results = parallel_dispatcher.dispatch(
        "Parallel test"
    )

    assert all(
        result.succeeded
        for result in parallel_results.values()
    )


if __name__ == "__main__":
    test_dispatcher()
    print("Dispatcher tests passed.")
