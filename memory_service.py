import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class MemorySearchResult:
    context: str
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class MemoryService:
    def __init__(
        self,
        wing: str = "gpt_palace",
        memory_limit: int = 4000
    ):
        self.wing = wing
        self.memory_limit = memory_limit

    def search(self, query: str) -> MemorySearchResult:
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "mempalace",
                    "search",
                    query,
                    "--wing",
                    self.wing
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )

            if result.returncode != 0:
                error = result.stderr.strip()

                if not error:
                    error = (
                        f"Memory Palace exited with code "
                        f"{result.returncode}"
                    )

                return MemorySearchResult(
                    context="",
                    error=error
                )

            context = result.stdout[:self.memory_limit].strip()

            if not context:
                context = "No relevant memory found."

            return MemorySearchResult(
                context=context
            )

        except Exception as exc:
            return MemorySearchResult(
                context="",
                error=str(exc)
            )
