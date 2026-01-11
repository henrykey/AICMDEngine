"""
LLM Configuration Loader - supports MongoDB, YAML, and .env files.
"""

from typing import Dict, List, Optional, Any
import os
import yaml
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LLMConfig:
    """Represents an LLM provider configuration."""

    def __init__(
        self,
        name: str,
        type: str,
        base_url: str,
        model: str,
        api_key_ref: str,
        timeout: int = 30,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float = 1.0,
        cost_per_1k_tokens: float = 0.001,
        priority: int = 1,
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Initialize LLM configuration."""
        self.name = name
        self.type = type
        self.base_url = base_url
        self.model = model
        self.api_key_ref = api_key_ref
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.cost_per_1k_tokens = cost_per_1k_tokens
        self.priority = priority
        self.enabled = enabled
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "type": self.type,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_ref": self.api_key_ref,
            "timeout": self.timeout,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "cost_per_1k_tokens": self.cost_per_1k_tokens,
            "priority": self.priority,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMConfig":
        """Create from dictionary."""
        return cls(**data)


class LLMConfigLoader:
    """Loads LLM provider configurations from MongoDB or YAML files."""

    def __init__(self, use_mongodb: bool = False, yaml_path: Optional[str] = None):
        """
        Initialize the config loader.

        Args:
            use_mongodb: Whether to load from MongoDB (requires async context)
            yaml_path: Path to YAML configuration file
        """
        self.use_mongodb = use_mongodb
        self.yaml_path = yaml_path or "config/llm_providers.yaml"
        self.cache: Dict[str, LLMConfig] = {}
        self.cache_loaded = False

    def load_from_yaml(self) -> Dict[str, LLMConfig]:
        """Load configurations from YAML file."""
        configs = {}

        if not os.path.exists(self.yaml_path):
            logger.warning(f"YAML config file not found: {self.yaml_path}")
            return configs

        try:
            with open(self.yaml_path, "r") as f:
                data = yaml.safe_load(f)

            if not data or "providers" not in data:
                logger.warning("No providers found in YAML config")
                return configs

            for provider_name, provider_config in data.get("providers", {}).items():
                try:
                    config = LLMConfig(
                        name=provider_name,
                        type=provider_config.get("type", "openai_compatible"),
                        base_url=provider_config.get("base_url", ""),
                        model=provider_config.get("model", ""),
                        api_key_ref=provider_config.get("api_key_ref", ""),
                        timeout=provider_config.get("timeout", 30),
                        temperature=provider_config.get("temperature", 0.7),
                        max_tokens=provider_config.get("max_tokens", 2048),
                        top_p=provider_config.get("top_p", 1.0),
                        cost_per_1k_tokens=provider_config.get("cost_per_1k_tokens", 0.001),
                        priority=provider_config.get("priority", 1),
                        enabled=provider_config.get("enabled", True),
                        metadata=provider_config.get("metadata"),
                    )
                    configs[provider_name] = config
                except Exception as e:
                    logger.error(f"Error loading provider {provider_name}: {e}")

            logger.info(f"Loaded {len(configs)} providers from YAML")
            return configs

        except Exception as e:
            logger.error(f"Error loading YAML config: {e}")
            return configs

    async def load_from_mongodb(self, db_client) -> Dict[str, LLMConfig]:
        """Load configurations from MongoDB."""
        configs = {}

        try:
            db = db_client.nl_tps  # Use the main database
            collection = db.llm_providers

            documents = await collection.find({}).to_list(None)

            for doc in documents:
                try:
                    provider_name = doc.get("name")
                    config = LLMConfig(
                        name=provider_name,
                        type=doc.get("type", "openai_compatible"),
                        base_url=doc.get("base_url", ""),
                        model=doc.get("model", ""),
                        api_key_ref=doc.get("api_key_ref", ""),
                        timeout=doc.get("timeout", 30),
                        temperature=doc.get("temperature", 0.7),
                        max_tokens=doc.get("max_tokens", 2048),
                        top_p=doc.get("top_p", 1.0),
                        cost_per_1k_tokens=doc.get("cost_per_1k_tokens", 0.001),
                        priority=doc.get("priority", 1),
                        enabled=doc.get("enabled", True),
                        metadata=doc.get("metadata"),
                    )
                    configs[provider_name] = config
                except Exception as e:
                    logger.error(f"Error loading provider from MongoDB: {e}")

            logger.info(f"Loaded {len(configs)} providers from MongoDB")
            return configs

        except Exception as e:
            logger.error(f"Error loading from MongoDB: {e}")
            return configs

    def get_api_key(self, api_key_ref: str) -> Optional[str]:
        """
        Get API key from environment variables or return as-is if it looks like a real API key.

        Args:
            api_key_ref: Either an environment variable name or a direct API key value

        Returns:
            API key string or None
        """
        # Check if it's an environment variable reference (contains only letters, numbers, underscores)
        if api_key_ref.replace('_', '').isalnum():
            # It might be an environment variable name
            env_key = os.environ.get(api_key_ref)
            if env_key:
                return env_key

        # Return as-is - it might be a real API key value
        if api_key_ref and len(api_key_ref) > 10:
            return api_key_ref

        return None

    def get_enabled_providers(
        self, providers: Dict[str, LLMConfig]
    ) -> List[LLMConfig]:
        """Get list of enabled providers sorted by priority."""
        enabled = [p for p in providers.values() if p.enabled]
        enabled.sort(key=lambda p: p.priority)
        return enabled

    def get_provider_by_name(
        self, name: str, providers: Dict[str, LLMConfig]
    ) -> Optional[LLMConfig]:
        """Get a provider by name."""
        return providers.get(name)
