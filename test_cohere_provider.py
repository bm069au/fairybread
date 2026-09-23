from types import SimpleNamespace

from cohere_provider import CohereProvider


class FakeClient:
    def chat(self, model, messages):
        assert model == "command-a-03-2025"

        assert messages == [
            {
                "role": "user",
                "content": "Hello Palace"
            }
        ]

        return SimpleNamespace(
            message=SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text="Fake Cohere response"
                    )
                ]
            )
        )


def test_cohere_provider():
    provider = CohereProvider("test-key")
    provider.client = FakeClient()

    response = provider.generate(
        "Hello Palace"
    )

    assert response.text == "Fake Cohere response"
    assert response.model == "command-a-03-2025"
    assert response.provider == "cohere"


if __name__ == "__main__":
    test_cohere_provider()
    print("Cohere provider test passed.")
