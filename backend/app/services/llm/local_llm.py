import httpx

from app.core.config import settings


class LocalLLMService:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.LOCAL_LLM_BASE_URL).rstrip("/")

    async def generate(self, prompt: str, model: str | None = None) -> str:
        if settings.MOCK_LLM_RESPONSES:
            return "Mock local response from Qwen3-8B 4-bit on Colab. Route selected: local."

        selected_model = model or settings.LOCAL_LLM_MODEL
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": selected_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
