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


def test_mistral_multimodal_chunks_override_and_fallback(tmp_path=None):
    import tempfile
    from pathlib import Path

    calls = []

    class MultiChat:
        def complete(self, model, messages):
            calls.append((model, messages))
            if model == "mistral-large-latest":
                raise RuntimeError("Status 403 tier_not_allowed")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=[
                                SimpleNamespace(type="thinking", text="internal step"),
                                SimpleNamespace(type="text", text="Visible clean answer"),
                            ]
                        )
                    )
                ]
            )

    with tempfile.TemporaryDirectory() as td:
        img_p = Path(td) / "sample.png"
        img_p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        prov = MistralProvider("test-key", model="mistral-medium-latest")
        prov.client = SimpleNamespace(chat=MultiChat())
        resp = prov.generate(
            "Describe screenshot",
            images=[img_p],
            system_prompt="Be concise.",
            history_messages=[{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
            model_override="mistral-large-latest",
        )
        assert resp.text == "Visible clean answer"
        assert resp.model == "mistral-medium-latest"
        assert calls[0][0] == "mistral-large-latest"
        assert calls[1][0] == "mistral-medium-latest"
        msgs = calls[1][1]
        assert msgs[0] == {"role": "system", "content": "Be concise."}
        assert msgs[1]["role"] == "user"
        assert isinstance(msgs[-1]["content"], list)
        assert msgs[-1]["content"][1]["type"] == "image_url"

    # Fail fast on 402 billing block without falling back to secondary models
    bill_calls = []

    class BillingChat:
        def complete(self, model, messages):
            bill_calls.append(model)
            raise RuntimeError("Status 402 billing_no_api_budget_configured")

    p402 = MistralProvider("test-key", model="mistral-large-latest")
    p402.client = SimpleNamespace(chat=BillingChat())
    raised = False
    try:
        p402.generate("Hi")
    except RuntimeError as exc:
        raised = ("402" in str(exc))
    assert raised and bill_calls == ["mistral-large-latest"]


if __name__ == "__main__":
    test_mistral_provider()
    test_mistral_multimodal_chunks_override_and_fallback()
    print("Mistral provider tests passed.")
