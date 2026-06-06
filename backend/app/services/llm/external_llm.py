"""External API LLM — for general/non-sensitive queries."""
import anthropic
from app.core.config import settings


class ExternalLLMService:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.EXTERNAL_LLM_API_KEY)

    async def generate(self, prompt: str) -> str:
        message = self.client.messages.create(
            model=settings.EXTERNAL_LLM_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
