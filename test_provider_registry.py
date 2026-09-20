from provider_registry import ProviderRegistry
from providers import AIProvider, ProviderResponse


class FakeProvider(AIProvider):
    def __init__(self, name: str):
        self.name = name

    def generate(self, prompt: str) -> ProviderResponse:
        return ProviderResponse(
            text=f"{self.name}: {prompt}",
            model="fake-model",
            provider=self.name
        )


def test_provider_registry():
    registry = ProviderRegistry()

    openai = FakeProvider("openai")
    gemini = FakeProvider("gemini")

    registry.register("openai", openai)
    registry.register("gemini", gemini)

    assert registry.get("openai") is openai
    assert registry.get("gemini") is gemini
    assert registry.names() == ["openai", "gemini"]

    providers = registry.all()

    assert len(providers) == 2

    responses = [
        provider.generate("Hello Palace")
        for provider in providers.values()
    ]

    assert responses[0].text == "openai: Hello Palace"
    assert responses[1].text == "gemini: Hello Palace"
    try:
        registry.register("", FakeProvider("invalid"))
        assert False, "Empty provider name should have failed."
    except ValueError:
        pass

    try:
        registry.register("openai", FakeProvider("duplicate"))
        assert False, "Duplicate provider name should have failed."
    except ValueError:
        pass

    try:
        registry.get("missing")
        assert False, "Missing provider lookup should have failed."
    except KeyError:
        pass

if __name__ == "__main__":
    test_provider_registry()
    print("Provider registry test passed.")
