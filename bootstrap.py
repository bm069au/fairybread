from context_service import ContextService
from dispatcher import ProviderDispatcher
from memory_service import MemoryService
from orchestrator import PalaceOrchestrator
from provider_registry import ProviderRegistry
from providers import AIProvider
from synthesizer import PalaceSynthesizer


def build_palace(
    providers: dict[str, AIProvider],
    wing: str = "gpt_palace",
    memory_limit: int = 7500,
    max_workers: int = 16,
    synthesis_provider_name: str | None = None,
    context_service: ContextService | None = None
) -> PalaceOrchestrator:

    if not providers:
        raise ValueError(
            "At least one AI provider is required."
        )

    registry = ProviderRegistry()

    for name, provider in providers.items():
        registry.register(
            name,
            provider
        )

    dispatcher = ProviderDispatcher(
        registry,
        max_workers=max_workers
    )

    memory_service = MemoryService(
        wing=wing,
        memory_limit=memory_limit
    )

    if synthesis_provider_name is None:
        try:
            from palace_config import load_agent_defaults
            synth_mode = str(load_agent_defaults().get("synthesizer_mode") or "auto_fast").strip().lower()
        except Exception:
            synth_mode = "auto_fast"
        if synth_mode == "match_primary":
            synthesis_provider_name = next(iter(providers))
        elif synth_mode in providers:
            synthesis_provider_name = synth_mode
        else:
            synthesis_provider_name = next(
                (p for p in ("deepseek", "cerebras", "groq", "gemini", "openai") if p in providers),
                next(iter(providers)),
            )

    if synthesis_provider_name not in providers:
        raise ValueError(
            f"Synthesis provider "
            f"'{synthesis_provider_name}' "
            f"is not configured."
        )

    synthesizer = PalaceSynthesizer(
        provider_name=synthesis_provider_name,
        provider=providers[
            synthesis_provider_name
        ],
        fallback_providers=providers,
    )

    return PalaceOrchestrator(
        memory_service,
        dispatcher,
        synthesizer=synthesizer,
        context_service=context_service
    )
