from types import SimpleNamespace
from unittest.mock import patch

import palace_cli


class FakePalace:
    def __init__(self):
        self.last_question = None

    def run(self, question):
        self.last_question = question

        return SimpleNamespace(
            memory_error=None,
            final_answer="Fake Palace answer",
            contributors=[
                "gemini",
                "groq"
            ],
            synthesis=SimpleNamespace(
                succeeded=True,
                error=None
            ),
            provider_results={}
        )


def test_build_configured_palace():
    fake_credentials = object()
    fake_provider = object()
    fake_palace = object()
    fake_context = object()

    with patch(
        "palace_cli.CredentialStore",
        return_value=fake_credentials
    ), patch(
        "palace_cli.load_configured_providers",
        return_value={
            "gemini": fake_provider
        }
    ) as mock_load, patch(
        "palace_cli.ContextService", return_value=fake_context
    ), patch(
        "palace_cli.load_enabled_provider_names", return_value=["gemini"]
    ), patch(
        "palace_cli.build_palace",
        return_value=fake_palace
    ) as mock_build:

        palace = (
            palace_cli
            .build_configured_palace()
        )

    mock_load.assert_called_once_with(
        fake_credentials
    )

    mock_build.assert_called_once_with(
        providers={
            "gemini": fake_provider
        },
        context_service=fake_context
    )

    assert palace is fake_palace


def test_build_configured_palace_rejects_no_providers():
    with patch(
        "palace_cli.CredentialStore"
    ), patch(
        "palace_cli.load_configured_providers",
        return_value={}
    ):

        try:
            palace_cli.build_configured_palace()

            assert False, (
                "Expected RuntimeError"
            )

        except RuntimeError as exc:
            assert str(exc) == (
                "No AI providers are configured."
            )


def test_main():
    fake_palace = FakePalace()

    with patch(
        "palace_cli.build_configured_palace",
        return_value=fake_palace
    ), patch(
        "builtins.input",
        return_value="Hello Palace"
    ):

        palace_cli.main([])

    assert fake_palace.last_question == (
        "Hello Palace"
    )


def test_empty_question():
    fake_palace = FakePalace()

    with patch(
        "palace_cli.build_configured_palace",
        return_value=fake_palace
    ), patch(
        "builtins.input",
        return_value="   "
    ):

        palace_cli.main([])

    assert fake_palace.last_question is None


if __name__ == "__main__":
    test_build_configured_palace()
    test_build_configured_palace_rejects_no_providers()
    test_main()
    test_empty_question()

    print("Palace CLI tests passed.")
