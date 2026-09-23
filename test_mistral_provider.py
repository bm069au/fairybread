from types import SimpleNamespace

from mistral_provider import MistralProvider


class FakeChat:
    def complete(self, model, messages):
        assert model == "mistral-small-latest"

        assert messages == [
            {
                "role": "user",
                "content": "Hello Palace"
            }
        ]

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Fake Mistral response"
                    )
                )
            ]
        )


class FakeClient:
    def __init__(self):
        self.chat = FakeChat()


def test_mistral_provider():
    provider = MistralProvider("test-key")
    provider.client = FakeClient()

    response = provider.generate(
        "Hello Palace"
    )

    assert response.text == "Fake Mistral response"
    assert response.model == "mistral-small-latest"
    assert response.provider == "mistral"


if __name__ == "__main__":
    test_mistral_provider()
    print("Mistral provider test passed.")
