from types import SimpleNamespace

from groq_provider import GroqProvider


class FakeCompletions:
    def create(self, model, messages):
        assert model == "openai/gpt-oss-120b"

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
                        content="Fake Groq response"
                    )
                )
            ]
        )


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self):
        self.chat = FakeChat()


def test_groq_provider():
    provider = GroqProvider("test-key")
    provider.client = FakeClient()

    response = provider.generate(
        "Hello Palace"
    )

    assert response.text == "Fake Groq response"
    assert response.model == "openai/gpt-oss-120b"
    assert response.provider == "groq"


if __name__ == "__main__":
    test_groq_provider()
    print("Groq provider test passed.")
