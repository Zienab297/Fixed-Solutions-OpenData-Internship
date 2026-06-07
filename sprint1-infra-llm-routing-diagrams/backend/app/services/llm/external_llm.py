import httpx

from app.core.config import settings


class ExternalLLMService:
    async def generate(self, prompt: str) -> str:
        if settings.MOCK_LLM_RESPONSES or not settings.GEMINI_API_KEY:
            return "Mock Gemini 3.5 Flash response. Route selected: api."

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.API_LLM_MODEL}:generateContent"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
