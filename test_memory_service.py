from types import SimpleNamespace
from unittest.mock import patch

from memory_service import MemoryService


def test_memory_service():
    service = MemoryService(
        wing="test_wing",
        memory_limit=10
    )

    # Successful search
    with patch("memory_service.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout="1234567890EXTRA",
            stderr=""
        )

        result = service.search("test query")

        assert result.succeeded
        assert result.error is None
        assert result.context == "1234567890"

        mock_run.assert_called_once()

        args, kwargs = mock_run.call_args

        assert args[0] == [
            "python",
            "-m",
            "mempalace",
            "search",
            "test query",
            "--wing",
            "test_wing"
        ]

        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "ignore"

        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"

    # Successful search with no results
    with patch("memory_service.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout="",
            stderr=""
        )

        result = service.search("nothing here")

        assert result.succeeded
        assert result.context == "No relevant memory found."

    # Memory Palace reports an error
    with patch("memory_service.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Simulated memory failure"
        )

        result = service.search("broken search")

        assert not result.succeeded
        assert result.context == ""
        assert result.error == "Simulated memory failure"

    # subprocess itself fails
    with patch("memory_service.subprocess.run") as mock_run:
        mock_run.side_effect = RuntimeError(
            "Simulated subprocess failure"
        )

        result = service.search("crash test")

        assert not result.succeeded
        assert result.context == ""
        assert result.error == "Simulated subprocess failure"


if __name__ == "__main__":
    test_memory_service()
    print("Memory service tests passed.")
