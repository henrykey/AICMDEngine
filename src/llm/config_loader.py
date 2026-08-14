"""
LLM Configuration Loader - supports MongoDB, YAML, and .env files.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import os
import yaml
import logging
from pathlib import Path
from src.core.config import settings

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
        # Capability detection fields
        capabilities: List[str] = None,
        context_window: int = 4096,
        dual_output_max_tokens: int = 4096,
        supports_multimodal: bool = False,
        supported_formats: List[str] = None,
        embedding_dimensions: Optional[int] = None,
        # Detection status fields
        capabilities_detection_status: Optional[str] = "pending",
        capabilities_last_updated: Optional[datetime] = None,
        capabilities_detection_error: Optional[str] = None,
        capabilities_mode: Optional[str] = None,
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
        # Capability fields
        self.capabilities = capabilities or ["chat"]
        self.context_window = context_window
        self.dual_output_max_tokens = dual_output_max_tokens
        self.supports_multimodal = supports_multimodal
        self.supported_formats = supported_formats or []
        self.embedding_dimensions = embedding_dimensions
        # Detection status fields
        self.capabilities_detection_status = capabilities_detection_status
        self.capabilities_last_updated = capabilities_last_updated
        self.capabilities_detection_error = capabilities_detection_error
        self.capabilities_mode = capabilities_mode

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
            # Capability fields
            "capabilities": self.capabilities,
            "context_window": self.context_window,
            "dual_output_max_tokens": self.dual_output_max_tokens,
            "supports_multimodal": self.supports_multimodal,
            "supported_formats": self.supported_formats,
            "embedding_dimensions": self.embedding_dimensions,
            # Detection status fields
            "capabilities_detection_status": self.capabilities_detection_status,
            "capabilities_last_updated": self.capabilities_last_updated.isoformat() if self.capabilities_last_updated else None,
            "capabilities_detection_error": self.capabilities_detection_error,
            "capabilities_mode": self.capabilities_mode,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMConfig":
        """Create from dictionary with capability field defaults."""
        # Handle datetime conversion
        last_updated = data.get("capabilities_last_updated")
        if last_updated and isinstance(last_updated, str):
            from datetime import datetime
            try:
                last_updated = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            except:
                last_updated = None

        # Detection status: only default to "pending" if capabilities_mode is "auto"
        # If capabilities_mode is "manual" or not specified, keep as None (manual mode)
        capabilities_mode = data.get("capabilities_mode")
        if capabilities_mode == "auto":
            detection_status_default = "pending"
        else:
            # Manual mode or not specified: no default, use None
            detection_status_default = None

        return cls(
            # Required fields
            name=data.get("name"),
            type=data.get("type", "openai_compatible"),
            base_url=data.get("base_url", ""),
            model=data.get("model", ""),
            api_key_ref=data.get("api_key_ref", ""),
            # Optional fields with defaults
            timeout=data.get("timeout", 30),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 2048),
            top_p=data.get("top_p", 1.0),
            cost_per_1k_tokens=data.get("cost_per_1k_tokens", 0.001),
            priority=data.get("priority", 1),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata"),
            # Capability fields with defaults
            capabilities=data.get("capabilities", ["chat"]),
            context_window=data.get("context_window", 4096),
            dual_output_max_tokens=data.get("dual_output_max_tokens", 4096),
            supports_multimodal=data.get("supports_multimodal", False),
            supported_formats=data.get("supported_formats", []),
            embedding_dimensions=data.get("embedding_dimensions"),
            # Detection status fields
            capabilities_detection_status=data.get("capabilities_detection_status", detection_status_default),
            capabilities_last_updated=last_updated,
            capabilities_detection_error=data.get("capabilities_detection_error"),
            capabilities_mode=capabilities_mode,
        )


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
                        # Capability fields
                        capabilities=provider_config.get("capabilities"),
                        context_window=provider_config.get("context_window", 4096),
                        dual_output_max_tokens=provider_config.get("dual_output_max_tokens", 4096),
                        supports_multimodal=provider_config.get("supports_multimodal", False),
                        supported_formats=provider_config.get("supported_formats"),
                        embedding_dimensions=provider_config.get("embedding_dimensions"),
                        # Detection status
                        capabilities_detection_status=provider_config.get("capabilities_detection_status", "completed"),
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
            db = db_client[settings.database_name]
            collection = db.llm_providers

            documents = await collection.find({}).to_list(None)

            for doc in documents:
                try:
                    provider_name = doc.get("name")
                    # Convert MongoDB doc to dict, excluding _id
                    doc_dict = {k: v for k, v in doc.items() if k != '_id'}
                    # Use from_dict to properly handle datetime conversion
                    config = LLMConfig.from_dict(doc_dict)
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
