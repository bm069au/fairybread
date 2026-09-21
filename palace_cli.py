import os
import sys

from bootstrap import build_palace


def load_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not set."
        )

    return api_key


def main():
    try:
        api_key = load_api_key()
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    palace = build_palace(
        api_key=api_key
    )

    print("Palace")
    print("=" * 60)

    question = input("Ask Palace: ").strip()

    if not question:
        print("No question entered.")
        return

    print("\nSearching memory and consulting providers...\n")

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
