from openai import AsyncOpenAI
from openai import RateLimitError, APIError, APIConnectionError, AuthenticationError
import json
import logging
from typing import Any, Dict, Optional
from src.core.config import settings

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self):
        # 定义AI提供商优先级列表
        self.providers = [
            {
                'name': 'deepseek',
                'client': AsyncOpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url
                ),
                'model': settings.deepseek_model_name
            },
            {
                'name': 'openai',
                'client': AsyncOpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url
                ),
                'model': settings.openai_model_name
            }
        ]

        # 过滤掉没有配置API key的提供商
        self.providers = [p for p in self.providers if p['client'].api_key]
        if not self.providers:
            raise ValueError("No AI provider configured with API key")

        # 当前使用的提供商索引
        self.current_provider_index = 0

    async def generate_response(
        self,
        messages: list[Dict[str, str]],
        temperature: float = 0.0,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4000
    ) -> str:
        """
        Generate LLM response with automatic fallback mechanism.
        """
        last_error = None

        # 尝试所有可用的提供商
        for attempt in range(len(self.providers)):
            current_provider = self.providers[self.current_provider_index]

            try:
                kwargs = {
                    "model": current_provider['model'],
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format:
                    kwargs["response_format"] = response_format

                logger.info(f"Attempting LLM call with provider='{current_provider['name']}', "
                           f"model='{current_provider['model']}', "
                           f"base_url='{current_provider['client'].base_url}'")

                response = await current_provider['client'].chat.completions.create(**kwargs)

                finish_reason = None
                content = ""
                if response.choices:
                    finish_reason = response.choices[0].finish_reason
                    content = response.choices[0].message.content or ""

                logger.info(
                    f"Successfully got response from provider='{current_provider['name']}', "
                    f"finish_reason='{finish_reason}', content_len={len(content)}"
                )
                return content

            except RateLimitError as e:
                last_error = e
                logger.warning(f"Rate limit error with provider='{current_provider['name']}': {e}")
                # 重试下一个提供商
                self._switch_to_next_provider()

            except AuthenticationError as e:
                last_error = e
                logger.error(f"Authentication error with provider='{current_provider['name']}': {e}")
                # 认证错误通常不会恢复，直接重试下一个
                self._switch_to_next_provider()

            except APIConnectionError as e:
                last_error = e
                logger.warning(f"Connection error with provider='{current_provider['name']}': {e}")
                # 连接错误，重试下一个提供商
                self._switch_to_next_provider()

            except APIError as e:
                last_error = e
                logger.warning(f"API error with provider='{current_provider['name']}': {e}")

                # 检查是否是可恢复的API错误
                if self._is_recoverable_api_error(e):
                    self._switch_to_next_provider()
                else:
                    # 对于某些API错误，可能不需要切换提供商
                    raise e

            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error with provider='{current_provider['name']}': {e}", exc_info=True)
                self._switch_to_next_provider()

        # 所有提供商都尝试过了
        error_msg = f"All AI providers failed. Last error: {last_error}"
        logger.error(error_msg)
        raise Exception(error_msg)

    def _switch_to_next_provider(self):
        """切换到下一个可用的提供商"""
        self.current_provider_index = (self.current_provider_index + 1) % len(self.providers)
        next_provider = self.providers[self.current_provider_index]
        logger.info(f"Switched to provider='{next_provider['name']}' (index={self.current_provider_index})")

    def _is_recoverable_api_error(self, error: APIError) -> bool:
        """判断API错误是否应该切换提供商"""
        # 检查错误消息是否包含需要切换提供商的关键词
        error_message = str(error).lower()

        # 如果错误消息提到限制、配额等，应该切换
        if any(keyword in error_message for keyword in ['rate limit', 'quota', 'limit', 'throttled', 'exceeded']):
            return True

        # 如果错误消息提到服务器内部错误，可能应该重试
        if any(keyword in error_message for keyword in ['internal server error', 'timeout', 'service unavailable']):
            return True

        return False

llm_client = LLMClient()
