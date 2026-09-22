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
