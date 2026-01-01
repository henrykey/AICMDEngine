from openai import AsyncOpenAI
import json
import logging
from typing import Any, Dict, Optional
from src.core.config import settings

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url
        )
        self.model = settings.openai_model_name

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

            logger.debug(f"Calling LLM with model={self.model}, base_url={self.client.base_url}")
            response = await self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM Error: {e}", exc_info=True)
            raise e

llm_client = LLMClient()
