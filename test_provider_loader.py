import tempfile
from pathlib import Path
from unittest.mock import patch

from credential_store import CredentialStore
from palace_config import (
    load_enabled_provider_names,
    load_provider_configs,
    save_provider_config,
    set_provider_enabled,
)
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


def test_provider_loader_with_openai_and_custom_ai():
    credentials = FakeCredentialStore(
        {
            "gemini": "test-gemini-key",
            "openai": "test-openai-key",
            "deepseek": "test-deepseek-key",
        }
    )
    provider_configs = {
        "gemini": {"enabled": True},
        "openai": {"enabled": True},
        "deepseek": {
            "enabled": True,
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }

    with patch("provider_loader.GeminiProvider") as mock_gemini, patch(
        "provider_loader.OpenAIProvider"
    ) as mock_openai:
        fake_gemini = object()
        fake_openai = object()
        fake_deepseek = object()
        mock_gemini.return_value = fake_gemini
        mock_openai.side_effect = [fake_openai, fake_deepseek]

        providers = load_configured_providers(
            credentials,
            provider_configs=provider_configs,
        )

        mock_gemini.assert_called_once_with(api_key="test-gemini-key")
        assert mock_openai.call_count == 2
        mock_openai.assert_any_call(api_key="test-openai-key")
        mock_openai.assert_any_call(
            api_key="test-deepseek-key",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            provider_name="deepseek",
        )
        assert providers == {
            "gemini": fake_gemini,
            "openai": fake_openai,
            "deepseek": fake_deepseek,
        }


def test_credential_store_and_palace_config_helpers():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cred_path = Path(tmp_dir) / "credentials.json"
        cfg_path = Path(tmp_dir) / "palace_config.json"

        store = CredentialStore(path=cred_path)
        assert not store.has_api_key("openai")
        store.set_api_key("openai", "  sk-test-123  ")
        assert store.has_api_key("openai")
        assert store.get_api_key("openai") == "sk-test-123"

        save_provider_config(
            "gemini",
            enabled=True,
            config_path=cfg_path,
        )
        save_provider_config(
            "openai",
            enabled=True,
            model="gpt-5-mini",
            config_path=cfg_path,
        )
        save_provider_config(
            "qwen",
            enabled=False,
            model="qwen-max",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            config_path=cfg_path,
        )

        assert load_enabled_provider_names(config_path=cfg_path) == [
            "gemini",
            "openai",
        ]
        set_provider_enabled("qwen", True, config_path=cfg_path)
        assert load_enabled_provider_names(config_path=cfg_path) == [
            "gemini",
            "openai",
            "qwen",
        ]
        configs = load_provider_configs(config_path=cfg_path)
        assert configs["qwen"]["model"] == "qwen-max"
        assert (
            configs["qwen"]["base_url"]
            == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )


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
    test_provider_loader_with_openai_and_custom_ai()
    test_credential_store_and_palace_config_helpers()
    test_provider_loader_with_no_keys()

    print("Provider loader tests passed.")
