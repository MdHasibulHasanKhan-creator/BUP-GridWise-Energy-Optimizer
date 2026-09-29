import logging
from typing import Optional
import httpx
from app.llm.providers.base import BaseLLMProvider
from app.config import settings

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(BaseLLMProvider):
    """
    OpenAI-compatible API provider (OpenAI, Groq, OpenRouter, Ollama, etc.).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = (base_url or settings.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        self.model = model or settings.OPENAI_MODEL

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")

        timeout = timeout_seconds or settings.LLM_TIMEOUT_SECONDS
        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error("OpenAI-compatible API error (%d): %s", response.status_code, response.text)
                raise RuntimeError(f"OpenAI-compatible API returned status {response.status_code}")

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("No choices returned from LLM provider.")

            content = choices[0].get("message", {}).get("content", "[]")
            return content
