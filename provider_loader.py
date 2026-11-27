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

    from palace_config import CONFIG_PATH as _DEFAULT_CFG_PATH, resolve_provider_timeout_policy
    eff_cfg_for_policy = config_path if config_path is not None else _DEFAULT_CFG_PATH

    def _policy_for(p_name: str) -> tuple[float, float]:
        try:
            pol = resolve_provider_timeout_policy(p_name, config_path=eff_cfg_for_policy)
            return float(pol.get("thinking_ceiling_sec", 0)), float(pol.get("handshake_sec", 15))
        except Exception:
            return 0.0, 15.0

    def _build_openai(api_key: str) -> AIProvider:
        cfg = configs.get("openai", {})
        tc, hs = _policy_for("openai")
        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": tc, "handshake_timeout": hs}
        if cfg.get("model"):
            kwargs["model"] = cfg["model"]
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return OpenAIProvider(**kwargs)

    def _build_mistral(api_key: str) -> AIProvider:
        cfg = configs.get("mistral", {})
        tc, hs = _policy_for("mistral")
        if cfg.get("model"):
            return MistralProvider(api_key=api_key, model=str(cfg["model"]).strip(), timeout=tc, handshake_timeout=hs)
        return MistralProvider(api_key=api_key, model="mistral-medium-latest", timeout=tc, handshake_timeout=hs)

    def _build_gemini(api_key: str) -> AIProvider:
        cfg = configs.get("gemini", {})
        tc, hs = _policy_for("gemini")
        if cfg.get("model"):
            return GeminiProvider(api_key=api_key, model=str(cfg["model"]).strip(), timeout=tc, handshake_timeout=hs)
        return GeminiProvider(api_key=api_key, timeout=tc, handshake_timeout=hs)

    def _build_groq(api_key: str) -> AIProvider:
        cfg = configs.get("groq", {})
        if cfg.get("model"):
            return GroqProvider(api_key=api_key, model=str(cfg["model"]).strip())
        return GroqProvider(api_key=api_key)

    def _build_cerebras(api_key: str) -> AIProvider:
        cfg = configs.get("cerebras", {})
        tc, hs = _policy_for("cerebras")
        if cfg.get("model"):
            return CerebrasProvider(api_key=api_key, model=str(cfg["model"]).strip(), timeout=tc, handshake_timeout=hs)
        return CerebrasProvider(api_key=api_key, timeout=tc, handshake_timeout=hs)

    def _build_cohere(api_key: str) -> AIProvider:
        cfg = configs.get("cohere", {})
        tc, hs = _policy_for("cohere")
        if cfg.get("model"):
            return CohereProvider(api_key=api_key, model=str(cfg["model"]).strip(), timeout=tc, handshake_timeout=hs)
        return CohereProvider(api_key=api_key, timeout=tc, handshake_timeout=hs)

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
        tc_c, hs_c = _policy_for(custom_name)
        if max_tokens is not None:
            factories[custom_name] = (
                lambda api_key, m=model, b=base_url, n=custom_name, mt=int(max_tokens), tc=tc_c, hs=hs_c: OpenAIProvider(
                    api_key=api_key,
                    model=m,
                    base_url=b,
                    provider_name=n,
                    max_tokens=mt,
                    timeout=tc,
                    handshake_timeout=hs,
                )
            )
        else:
            factories[custom_name] = (
                lambda api_key, m=model, b=base_url, n=custom_name, tc=tc_c, hs=hs_c: OpenAIProvider(
                    api_key=api_key,
                    model=m,
                    base_url=b,
                    provider_name=n,
                    timeout=tc,
                    handshake_timeout=hs,
                )
            )

    providers: dict[str, AIProvider] = {}
    configs_lower = {str(k).strip().lower(): v for k, v in configs.items()}

    for provider_name, factory in factories.items():
        cfg_entry = configs_lower.get(provider_name, {})
        if isinstance(cfg_entry, dict) and cfg_entry.get("use_openrouter"):
            continue
        api_key = credentials.get_api_key(
            provider_name
        )

        if api_key:
            providers[provider_name] = factory(
                api_key
            )

    # Hybrid OpenRouter support: direct keys take priority unless a seat explicitly selects use_openrouter=True;
    # when openrouter_hub.auto_fill_seats is enabled, fill any missing enabled/preset seats via OpenRouter.
    openrouter_key = credentials.get_api_key("openrouter")
    if openrouter_key:
        try:
            from palace_config import (
                CONFIG_PATH,
                OPENROUTER_PRESET_TIERS,
                PROVIDER_CATALOG,
                load_openrouter_hub_settings,
                resolve_profile_model_override,
            )

            eff_cfg_path = config_path if config_path is not None else CONFIG_PATH
            hub = load_openrouter_hub_settings(eff_cfg_path)
            tier_map = OPENROUTER_PRESET_TIERS.get(hub.get("tier", "balanced"), OPENROUTER_PRESET_TIERS["balanced"])

            def _resolve_openrouter_seat_model(
                seat_name: str,
                pcfg: dict[str, Any] | None,
                tier_entry: dict[str, Any] | None,
            ) -> str:
                cfg_dict = pcfg if isinstance(pcfg, dict) else {}
                explicit_or = str(cfg_dict.get("openrouter_model") or "").strip()
                if explicit_or:
                    return resolve_profile_model_override(seat_name, explicit_or, is_openrouter=True)
                raw_model = str(cfg_dict.get("model") or "").strip()
                tier_model = str((tier_entry or {}).get("model") or "").strip()
                cat_default = str(PROVIDER_CATALOG.get(seat_name, {}).get("default_model") or "").strip()
                # When a seat (such as Mistral, whose direct free default is 'codestral-latest') is routed via
                # OpenRouter without a custom OpenRouter slug, upgrade untouched direct-API defaults to the
                # OpenRouter tier preset (e.g. full Mistral Medium 3.1 / Mistral Large).
                if not raw_model or (
                    "/" not in raw_model
                    and tier_model
                    and raw_model.lower() in {cat_default.lower(), "codestral-latest"}
                ):
                    if tier_model:
                        return tier_model
                if raw_model:
                    return resolve_profile_model_override(seat_name, raw_model, is_openrouter=True)
                if tier_model:
                    return tier_model
                return f"{seat_name}/auto" if "/" not in seat_name else seat_name

            # 1) Explicit per-seat use_openrouter overrides
            for pname, pcfg in configs_lower.items():
                if pname == "openrouter" or not isinstance(pcfg, dict):
                    continue
                if pcfg.get("use_openrouter") and pcfg.get("enabled", True):
                    tier_entry = tier_map.get(pname, {})
                    or_model = _resolve_openrouter_seat_model(pname, pcfg, tier_entry)
                    tc_or, hs_or = _policy_for(pname)
                    providers[pname] = OpenAIProvider(
                        api_key=openrouter_key,
                        model=or_model,
                        base_url="https://openrouter.ai/api/v1",
                        provider_name=pname,
                        timeout=tc_or,
                        handshake_timeout=hs_or,
                    )

            # 2) Hub auto-fill for seats without a direct key
            if hub.get("auto_fill_seats"):
                for seat_name, meta in tier_map.items():
                    if seat_name in providers:
                        continue
                    pcfg = configs_lower.get(seat_name)
                    if isinstance(pcfg, dict) and pcfg.get("enabled") is False:
                        continue
                    or_model = _resolve_openrouter_seat_model(seat_name, pcfg, meta)
                    if or_model:
                        tc_or, hs_or = _policy_for(seat_name)
                        providers[seat_name] = OpenAIProvider(
                            api_key=openrouter_key,
                            model=or_model,
                            base_url="https://openrouter.ai/api/v1",
                            provider_name=seat_name,
                            timeout=tc_or,
                            handshake_timeout=hs_or,
                        )
        except Exception:
            pass

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
                    tc_cli, hs_cli = _policy_for(prov_key)
                    providers[prov_key] = LocalCLIProvider(
                        platform_key,
                        cli_path=cli_path,
                        timeout_sec=int(tc_cli),
                        handshake_sec=int(hs_cli),
                    )
        except Exception:
            pass

    return providers
