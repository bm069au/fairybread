import json
from pathlib import Path
from tempfile import TemporaryDirectory

from credential_store import CredentialStore


def test_credential_store():
    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "credentials.json"

        path.write_text(
            json.dumps(
                {
                    "providers": {
                        "gemini": {
                            "api_key": "test-gemini-key"
                        }
                    }
                }
            ),
            encoding="utf-8"
        )

        store = CredentialStore(path=path)

        assert store.get_api_key("gemini") == "test-gemini-key"
        assert store.get_api_key("groq") is None


if __name__ == "__main__":
    test_credential_store()
    print("Credential store tests passed.")
