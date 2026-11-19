from openai_provider import OpenAIProvider


class FakeAPIResponse:
    output_text = "Fake OpenAI response"


class FakeResponses:
    def create(self, model, input):
        assert model == "gpt-5-mini"
        assert input == "Hello Palace"
        return FakeAPIResponse()


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


def test_openai_provider():
    provider = OpenAIProvider("test-key")
    provider.client = FakeClient()

    response = provider.generate("Hello Palace")

    assert response.text == "Fake OpenAI response"
    assert response.model == "gpt-5-mini"
    assert response.provider == "openai"


if __name__ == "__main__":
    test_openai_provider()
    print("OpenAI provider test passed.")


