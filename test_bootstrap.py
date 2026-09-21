from bootstrap import build_palace
from orchestrator import PalaceOrchestrator
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


def test_build_palace():
    provider_one = FakeProvider("one")
    provider_two = FakeProvider("two")

    palace = build_palace(
        providers={
            "one": provider_one,
            "two": provider_two
        },
        wing="test-wing",
        memory_limit=1234,
        max_workers=2
    )

    assert isinstance(palace, PalaceOrchestrator)

    assert palace.memory_service.wing == "test-wing"
    assert palace.memory_service.memory_limit == 1234

    assert palace.dispatcher.max_workers == 2

    assert palace.dispatcher.registry.names() == [
        "one",
        "two"
    ]

    assert (
        palace.dispatcher.registry.get("one")
        is provider_one
    )

    assert (
        palace.dispatcher.registry.get("two")
        is provider_two
    )


def test_build_palace_rejects_empty_provider_set():
    try:
        build_palace(
            providers={}
        )

        assert False, "Expected ValueError"

    except ValueError as exc:
        assert str(exc) == (
            "At least one AI provider is required."
        )


if __name__ == "__main__":
    test_build_palace()
    test_build_palace_rejects_empty_provider_set()

    print("Bootstrap tests passed.")
