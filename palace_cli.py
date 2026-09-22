import sys

from bootstrap import build_palace
from credential_store import CredentialStore
from provider_loader import load_configured_providers


def build_configured_palace():
    credentials = CredentialStore()

    providers = load_configured_providers(
        credentials
    )

    if not providers:
        raise RuntimeError(
            "No AI providers are configured."
        )

    return build_palace(
        providers=providers
    )


def main():
    try:
        palace = build_configured_palace()

    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    print("Palace")
    print("=" * 60)

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
