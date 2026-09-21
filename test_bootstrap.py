from unittest.mock import patch

from bootstrap import build_palace
from orchestrator import PalaceOrchestrator


def test_build_palace():
    with patch("bootstrap.OpenAIProvider") as mock_provider:
        fake_provider = object()
        mock_provider.return_value = fake_provider

        palace = build_palace(
            api_key="test-key",
            model="test-model",
            wing="test-wing",
            memory_limit=1234,
            max_workers=2
        )

        assert isinstance(palace, PalaceOrchestrator)

        mock_provider.assert_called_once_with(
            api_key="test-key",
            model="test-model"
        )

        assert palace.memory_service.wing == "test-wing"
        assert palace.memory_service.memory_limit == 1234

        assert palace.dispatcher.max_workers == 2

        assert palace.dispatcher.registry.names() == [
            "openai"
        ]

        assert (
            palace.dispatcher.registry.get("openai")
            is fake_provider
        )


def test_build_palace_rejects_empty_key():
    try:
        build_palace(api_key="   ")

        assert False, "Expected ValueError"

    except ValueError as exc:
        assert str(exc) == "API key cannot be empty."


if __name__ == "__main__":
    test_build_palace()
    test_build_palace_rejects_empty_key()

    print("Bootstrap tests passed.")
