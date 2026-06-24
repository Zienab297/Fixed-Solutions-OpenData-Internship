import re

import httpx

from app.core.config import settings


class LocalLLMTimeoutError(RuntimeError):
    pass


class LocalLLMService:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.LOCAL_LLM_BASE_URL).rstrip("/")

    async def generate(self, prompt: str, model: str | None = None) -> str:
        if settings.MOCK_LLM_RESPONSES:
            return "Mock local response from Qwen3-8B 4-bit on Colab. Route selected: local."

        selected_model = model or settings.LOCAL_LLM_MODEL
        timeout = httpx.Timeout(settings.LOCAL_LLM_TIMEOUT_SECONDS, connect=10.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": selected_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens": settings.LOCAL_LLM_MAX_TOKENS,
                        "chat_template_kwargs": {"enable_thinking": False},  # ← ADD: disable qwen3 thinking mode
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]

                # qwen3 may still emit reasoning inside <think>...</think> — strip it out
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()  # ← ADD
                return content
        except httpx.TimeoutException as exc:
            raise LocalLLMTimeoutError(
                f"Local LLM timed out after {settings.LOCAL_LLM_TIMEOUT_SECONDS:.0f}s"
            ) from exc