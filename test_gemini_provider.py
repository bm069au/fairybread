from gemini_provider import GeminiProvider


class FakeAPIResponse:
    text = "Fake Gemini response"


class FakeModels:
    def generate_content(self, model, contents):
        assert model == "gemini-2.5-flash-lite"
        assert contents == "Hello Palace"

        return FakeAPIResponse()


class FakeClient:
    def __init__(self):
        self.models = FakeModels()


def test_gemini_provider():
    provider = GeminiProvider("test-key")
    provider.client = FakeClient()

    response = provider.generate("Hello Palace")

    assert response.text == "Fake Gemini response"
    assert response.model == "gemini-2.5-flash-lite"
    assert response.provider == "gemini"


if __name__ == "__main__":
    test_gemini_provider()
    print("Gemini provider test passed.")
