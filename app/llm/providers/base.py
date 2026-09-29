from abc import ABC, abstractmethod
from typing import Optional


class BaseLLMProvider(ABC):
    """
    Abstract Base Class for LLM providers.
    """

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        system_instruction: str,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        """
        Sends prompt and system instruction to the model and returns the raw JSON string response.
        """
        pass
