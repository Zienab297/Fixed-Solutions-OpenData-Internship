"""Local LLM via Ollama — for sensitive/internal domain queries."""
import httpx
from app.core.config import settings


class LocalLLMService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL

    async def generate(self, prompt: str, model: str = None) -> str:
        model = model or settings.GENERATION_MODEL
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            return response.json()["response"]
