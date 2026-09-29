import logging
from typing import Optional
import httpx
from app.llm.providers.base import BaseLLMProvider
from app.config import settings

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini API provider using official REST endpoint with JSON mode.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        timeout = timeout_seconds or settings.LLM_TIMEOUT_SECONDS
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.0,
            }
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error("Gemini API error (%d): %s", response.status_code, response.text)
                raise RuntimeError(f"Gemini API returned status {response.status_code}")

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("No candidate responses returned from Gemini.")

            content_parts = candidates[0].get("content", {}).get("parts", [])
            if not content_parts:
                raise RuntimeError("Empty response parts from Gemini.")

            return content_parts[0].get("text", "[]")
