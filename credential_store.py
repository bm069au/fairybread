import json
import os
from pathlib import Path
from typing import Optional


class CredentialStore:
    def __init__(self, path: Optional[Path] = None):
        if path is None:
            local_app_data = os.environ.get("LOCALAPPDATA")

            if not local_app_data:
                raise RuntimeError(
                    "LOCALAPPDATA environment variable is not available."
                )

            path = (
                Path(local_app_data)
                / "Palace"
                / "credentials.json"
            )

        self.path = path

    def get_api_key(self, provider_name: str) -> Optional[str]:
        if not self.path.exists():
            return None

        try:
            data = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Unable to read Palace credentials: {exc}"
            ) from exc

        provider = (
            data
            .get("providers", {})
            .get(provider_name, {})
        )

        api_key = provider.get("api_key")

        if not api_key:
            return None

        return api_key.strip()

    def has_api_key(self, provider_name: str) -> bool:
        return bool(self.get_api_key(provider_name))

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        normalized_name = provider_name.strip().lower()
        if not normalized_name:
            raise ValueError("Provider name cannot be empty.")

        data: dict = {"providers": {}}
        if self.path.exists():
            try:
                loaded = json.loads(
                    self.path.read_text(encoding="utf-8")
                )
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Unable to read Palace credentials: {exc}"
                ) from exc

        providers = data.setdefault("providers", {})
        entry = providers.setdefault(normalized_name, {})
        entry["api_key"] = api_key.strip()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, indent=2) + "\n",
            encoding="utf-8"
        )
