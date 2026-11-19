from gemini_provider import GeminiProvider


class FakeInteraction:
    output_text = "Fake Gemini response"


class FakeInteractions:
    def create(self, model, input):
        assert model == "gemini-3.5-flash-lite"
        assert input == "Hello Palace"

        return FakeInteraction()


class FakeClient:
    def __init__(self):
        self.interactions = FakeInteractions()


def test_gemini_provider():
    provider = GeminiProvider("test-key")
    provider.client = FakeClient()

    response = provider.generate("Hello Palace")

    assert response.text == "Fake Gemini response"
    assert response.model == "gemini-3.5-flash-lite"
    assert response.provider == "gemini"


if __name__ == "__main__":
    test_gemini_provider()
    print("Gemini provider test passed.")
