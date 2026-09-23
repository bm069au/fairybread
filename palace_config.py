import json
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name(
    "palace_config.json"
)


def load_enabled_provider_names() -> list[str]:
    data = json.loads(
        CONFIG_PATH.read_text(
            encoding="utf-8"
        )
    )

    providers = data.get(
        "providers",
        {}
    )

    return [
        name
        for name, settings in providers.items()
        if settings.get("enabled", False)
    ]
