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

    question = input("Ask Palace: ").strip()

    if not question:
        print("No question entered.")
        return

    print(
        "\nConsulting configured providers...\n"
    )

    result = palace.run(question)

    if result.memory_error:
        print(
            f"Memory warning: {result.memory_error}"
        )
        print()

    for provider_name, provider_result in (
        result.provider_results.items()
    ):
        print("=" * 60)
        print(provider_name.upper())
        print("=" * 60)

        if provider_result.succeeded:
            print(provider_result.response.text)
        else:
            print(
                f"Provider failed: "
                f"{provider_result.error}"
            )

        print()


if __name__ == "__main__":
    main()
