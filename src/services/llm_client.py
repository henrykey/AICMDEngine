from openai import AsyncOpenAI
import json
from typing import Any, Dict, Optional
from src.core.config import settings

class LLMClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        self.model = settings.OPENAI_MODEL_NAME

    async def generate_response(
        self, 
        messages: list[Dict[str, str]], 
        temperature: float = 0.0,
        response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Wrapper for OpenAI chat completion.
        """
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }
            if response_format:
                kwargs["response_format"] = response_format

            print(f"DEBUG: Calling LLM with model={self.model}, base_url={self.client.base_url}")
            response = await self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            # In a real app, log error here
            print(f"LLM Error: {e}")
            raise e

llm_client = LLMClient()
