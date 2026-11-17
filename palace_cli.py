import argparse
import sys

from context_service import ContextService

from bootstrap import build_palace
from credential_store import CredentialStore
from provider_loader import load_configured_providers
from palace_config import load_enabled_provider_names, load_provider_configs

def build_configured_palace(*, include_context=True, context_service=None):
    credentials = CredentialStore()
    provider_configs = load_provider_configs()

    providers = load_configured_providers(
        credentials,
        provider_configs=provider_configs
    )
    enabled_names = load_enabled_provider_names()

    providers = {
        name: provider
        for name, provider in providers.items()
        if name in enabled_names
    }

    if not providers:
        raise RuntimeError(
            "No AI providers are configured."
        )

    return build_palace(
        providers=providers,
        context_service=(context_service if context_service is not None else ContextService()) if include_context else None
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask Palace a question.")
    parser.add_argument("--no-context", action="store_true",
                        help="Do not read or save session history for this question.")
    args = parser.parse_args(argv)
    try:
        palace = build_configured_palace(include_context=not args.no_context)

    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    print("Palace")
    print("=" * 60)

    if not args.no_context:
        print("Recent session history is shared with enabled providers and saved locally.")
        print("Use --no-context for a question without saved history.")

    question = input(
        "Ask Palace: "
    ).strip()

    if not question:
        print("No question entered.")
        return

    print(
        "\nConsulting configured providers...\n"
    )

    result = palace.run(
        question
    )

    if getattr(result, "context_error", None):
        print(f"Context warning: {result.context_error}\n")

    if result.memory_error:
        print(
            f"Memory warning: "
            f"{result.memory_error}"
        )
        print()

    print("=" * 60)
    print("PALACE")
    print("=" * 60)

    if result.final_answer:
        print(
            result.final_answer
        )
    else:
        print(
            "No provider produced "
            "a usable response."
        )

    if result.contributors:
        print()
        print(
            "Contributors: "
            + ", ".join(
                result.contributors
            )
        )

    if (
        result.synthesis
        and not result.synthesis.succeeded
    ):
        print()
        print(
            "Synthesis warning: "
            f"{result.synthesis.error}"
        )


if __name__ == "__main__":
    main()
