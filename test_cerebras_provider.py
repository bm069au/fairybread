from types import SimpleNamespace

from cerebras_provider import CerebrasProvider


class FakeCompletions:
    def create(self, model, messages):
        assert model == "qwen-3.8-27b"

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
                        content="Fake Cerebras response"
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


def test_cerebras_provider():
    provider = CerebrasProvider("test-key")
    provider.client = FakeClient()

    response = provider.generate(
        "Hello Palace"
    )

    assert response.text == "Fake Cerebras response"
    assert response.model == "qwen-3.8-27b"
    assert response.provider == "cerebras"


if __name__ == "__main__":
    test_cerebras_provider()
    print("Cerebras provider test passed.")
