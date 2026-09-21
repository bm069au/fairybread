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
            provider_results={
                "openai": SimpleNamespace(
                    succeeded=True,
                    response=SimpleNamespace(
                        text="Fake Palace answer"
                    ),
                    error=None
                )
            }
        )


def test_load_api_key():
    with patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "test-key"}
    ):
        key = palace_cli.load_api_key()

    assert key == "test-key"

def test_missing_api_key():
    with patch.dict(
        "os.environ",
        {},
        clear=True
    ):
        try:
            palace_cli.load_api_key()

            assert False, "Expected RuntimeError"

        except RuntimeError as exc:
            assert str(exc) == (
                "OPENAI_API_KEY environment variable is not set."
            )

def test_main():
    fake_palace = FakePalace()

    with patch(
        "palace_cli.load_api_key",
        return_value="test-key"
    ), patch(
        "palace_cli.build_palace",
        return_value=fake_palace
    ) as mock_build, patch(
        "builtins.input",
        return_value="Hello Palace"
    ):

        palace_cli.main()

    mock_build.assert_called_once_with(
        api_key="test-key"
    )

    assert fake_palace.last_question == "Hello Palace"


def test_empty_question():
    fake_palace = FakePalace()

    with patch(
        "palace_cli.load_api_key",
        return_value="test-key"
    ), patch(
        "palace_cli.build_palace",
        return_value=fake_palace
    ), patch(
        "builtins.input",
        return_value="   "
    ):

        palace_cli.main()

    assert fake_palace.last_question is None


if __name__ == "__main__":
    test_load_api_key()
    test_missing_api_key()
    test_main()
    test_empty_question()

    print("Palace CLI tests passed.")
