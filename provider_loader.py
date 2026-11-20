from pathlib import Path
from typing import Any, Callable

from credential_store import CredentialStore
from gemini_provider import GeminiProvider
from groq_provider import GroqProvider
from local_cli_provider import (
    PLATFORM_TO_CLI_PROVIDER,
    LocalCLIProvider,
    find_cli_binary,
    get_mcp_depth,
)
from openai_provider import OpenAIProvider
from providers import AIProvider
from cerebras_provider import CerebrasProvider
from cohere_provider import CohereProvider
from mistral_provider import MistralProvider


def load_configured_providers(
    credentials: CredentialStore,
    provider_configs: dict[str, dict[str, Any]] | None = None,
    *,
    config_path: Path | None = None,
    include_local_cli: bool = True,
) -> dict[str, AIProvider]:
    configs = provider_configs or {}

    def _build_openai(api_key: str) -> AIProvider:
        cfg = configs.get("openai", {})
        kwargs: dict[str, Any] = {"api_key": api_key}
        if cfg.get("model"):
            kwargs["model"] = cfg["model"]
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return OpenAIProvider(**kwargs)

    def _build_mistral(api_key: str) -> AIProvider:
        cfg = configs.get("mistral", {})
        if cfg.get("model"):
            return MistralProvider(api_key=api_key, model=str(cfg["model"]).strip())
        return MistralProvider(api_key=api_key)

    def _build_gemini(api_key: str) -> AIProvider:
        cfg = configs.get("gemini", {})
        if cfg.get("model"):
            return GeminiProvider(api_key=api_key, model=str(cfg["model"]).strip())
        return GeminiProvider(api_key=api_key)

    def _build_groq(api_key: str) -> AIProvider:
        cfg = configs.get("groq", {})
        if cfg.get("model"):
            return GroqProvider(api_key=api_key, model=str(cfg["model"]).strip())
        return GroqProvider(api_key=api_key)

    def _build_cerebras(api_key: str) -> AIProvider:
        cfg = configs.get("cerebras", {})
        if cfg.get("model"):
            return CerebrasProvider(api_key=api_key, model=str(cfg["model"]).strip())
        return CerebrasProvider(api_key=api_key)

    def _build_cohere(api_key: str) -> AIProvider:
        cfg = configs.get("cohere", {})
        if cfg.get("model"):
            return CohereProvider(api_key=api_key, model=str(cfg["model"]).strip())
        return CohereProvider(api_key=api_key)

    factories: dict[
        str,
        Callable[[str], AIProvider]
    ] = {
        "gemini": _build_gemini,
        "openai": _build_openai,
        "groq": _build_groq,
        "mistral": _build_mistral,
        "cerebras": _build_cerebras,
        "cohere": _build_cohere,
    }

    for custom_name, cfg in configs.items():
        if custom_name in factories:
            continue
        model = cfg.get("model") or "gpt-4o-mini"
        base_url = cfg.get("base_url")
        max_tokens = cfg.get("max_tokens")
        if max_tokens is not None:
            factories[custom_name] = (
                lambda api_key, m=model, b=base_url, n=custom_name, mt=int(max_tokens): OpenAIProvider(
                    api_key=api_key,
                    model=m,
                    base_url=b,
                    provider_name=n,
                    max_tokens=mt
                )
            )
        else:
            factories[custom_name] = (
                lambda api_key, m=model, b=base_url, n=custom_name: OpenAIProvider(
                    api_key=api_key,
                    model=m,
                    base_url=b,
                    provider_name=n
                )
            )

    providers: dict[str, AIProvider] = {}

    for provider_name, factory in factories.items():
        api_key = credentials.get_api_key(
            provider_name
        )

        if api_key:
            providers[provider_name] = factory(
                api_key
            )

    if include_local_cli and get_mcp_depth() < 1:
        try:
            from fairybread_mcp import get_council_cli_platforms

            council_cli = (
                get_council_cli_platforms(config_path=config_path)
                if config_path is not None
                else get_council_cli_platforms()
            )
            for platform_key in council_cli:
                prov_key = PLATFORM_TO_CLI_PROVIDER.get(platform_key)
                if not prov_key or prov_key in providers:
                    continue
                cli_path = find_cli_binary(platform_key)
                if cli_path:
                    providers[prov_key] = LocalCLIProvider(platform_key, cli_path=cli_path)
        except Exception:
            pass

    return providers
