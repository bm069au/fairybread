from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderResponse:
    text: str
    model: Optional[str] = None
    provider: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0


class AIProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> ProviderResponse:
        """Generate a response for the supplied prompt."""
        raise NotImplementedError

