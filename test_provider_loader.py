from unittest.mock import patch

from provider_loader import load_configured_providers


class FakeCredentialStore:
    def __init__(self, keys):
        self.keys = keys

    def get_api_key(self, provider_name: str):
        return self.keys.get(provider_name)


def test_provider_loader_with_gemini():
    credentials = FakeCredentialStore(
        {
            "gemini": "test-gemini-key"
        }
    )

    with patch(
        "provider_loader.GeminiProvider"
    ) as mock_gemini_provider:

        fake_provider = object()
        mock_gemini_provider.return_value = fake_provider

        providers = load_configured_providers(
            credentials
        )

        mock_gemini_provider.assert_called_once_with(
            api_key="test-gemini-key"
        )

        assert providers == {
            "gemini": fake_provider
        }


def test_provider_loader_with_no_keys():
    credentials = FakeCredentialStore({})

    with patch(
        "provider_loader.GeminiProvider"
    ) as mock_gemini_provider:

        providers = load_configured_providers(
            credentials
        )

        mock_gemini_provider.assert_not_called()
        assert providers == {}


if __name__ == "__main__":
    test_provider_loader_with_gemini()
    test_provider_loader_with_no_keys()

    print("Provider loader tests passed.")
