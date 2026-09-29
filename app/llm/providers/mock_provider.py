from typing import Optional, Dict, Any, Callable
import json
from app.llm.providers.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """
    Mock LLM provider for deterministic unit testing without external API calls.
    """

    def __init__(self, response_override: Optional[str] = None):
        self.response_override = response_override

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        if self.response_override is not None:
            return self.response_override
        # Return empty list JSON by default
        return "[]"
