from dataclasses import dataclass
from typing import Optional

from providers import ProviderResponse


@dataclass
class ProviderResult:
    provider_name: str
    response: Optional[ProviderResponse] = None
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.response is not None and self.error is None
