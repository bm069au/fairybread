from providers import AIProvider, ProviderResponse


class FakeProvider(AIProvider):
    def generate(self, prompt: str) -> ProviderResponse:
        return ProviderResponse(
            text=f"Echo: {prompt}",
            model="fake-model",
            provider="fake"
        )


def test_fake_provider():
    provider = FakeProvider()
    response = provider.generate("Hello Palace")

    assert response.text == "Echo: Hello Palace"
    assert response.model == "fake-model"
    assert response.provider == "fake"


if __name__ == "__main__":
    test_fake_provider()
    print("Provider interface test passed.")




