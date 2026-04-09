"""
LLM Provider Manager - manages multiple LLM providers with OpenAI-compatible interface.
"""

from typing import Dict, Optional, List, Any
import logging
from openai import AsyncOpenAI
from urllib.parse import urlparse
from src.llm.config_loader import LLMConfig, LLMConfigLoader

logger = logging.getLogger(__name__)


def _classify_base_url(base_url: Optional[str]) -> str:
    raw = str(base_url or "")
    try:
        host = (urlparse(raw).hostname or "").lower()
    except Exception:
        host = raw.lower()

    if host in {"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"}:
        return "local"
    if "ollama" in host:
        return "local"
    return "remote"


class LLMProviderManager:
    """
    Manages multiple LLM providers with OpenAI-compatible interface.

    Supports provider selection, cost tracking, and fallback strategies.
    """

    def __init__(self, config_loader: LLMConfigLoader):
        """
        Initialize the provider manager.

        Args:
            config_loader: LLMConfigLoader instance for loading configurations
        """
        self.config_loader = config_loader
        self.providers: Dict[str, LLMConfig] = {}
        self.clients: Dict[str, AsyncOpenAI] = {}
        self.current_provider: Optional[str] = None
        self.cost_tracker: Dict[str, float] = {}
        self.db_client: Optional[Any] = None

    async def initialize(self, db_client=None):
        """
        Initialize providers from configuration.

        Strategy:
        1. Try MongoDB if enabled and has valid providers
        2. If MongoDB is empty or all invalid, load from YAML
        3. Only keep providers with valid API keys

        Args:
            db_client: MongoDB client for loading from database
        """
        # Store db_client for later use in CRUD operations
        self.db_client = db_client

        # Step 1: Try to load from MongoDB
        mongodb_providers = {}
        if db_client and self.config_loader.use_mongodb:
            mongodb_providers = await self.config_loader.load_from_mongodb(db_client)
            if mongodb_providers:
                logger.info(f"Loaded {len(mongodb_providers)} providers from MongoDB")
            else:
                logger.info("MongoDB is empty")

        # Step 2: Try to initialize clients from MongoDB providers
        successfully_initialized_from_mongodb = self._initialize_clients(mongodb_providers, "MongoDB")

        # Step 3: If MongoDB is empty or all providers are invalid, use YAML
        if successfully_initialized_from_mongodb == 0:
            logger.info("No valid providers in MongoDB, loading from YAML configuration")
            yaml_providers = self.config_loader.load_from_yaml()
            self._initialize_clients(yaml_providers, "YAML")
            self.providers = yaml_providers
        else:
            self.providers = mongodb_providers
            logger.info(f"Using {successfully_initialized_from_mongodb} valid providers from MongoDB")

        # Step 4: Remove providers that don't have initialized clients
        # This ensures only providers with valid API keys are available
        self.providers = {
            name: config for name, config in self.providers.items()
            if name in self.clients
        }
        logger.info(f"Final provider list: {list(self.providers.keys())}")

        # Step 5: Set default provider (first enabled one with a client)
        enabled = self.config_loader.get_enabled_providers(self.providers)
        if enabled:
            self.current_provider = enabled[0].name
            logger.info(f"Set default provider: {self.current_provider}")
        else:
            logger.warning("No enabled providers found!")

    def _initialize_clients(self, providers: Dict[str, LLMConfig], source: str) -> int:
        """
        Initialize AsyncOpenAI clients for all providers with valid API keys.

        Args:
            providers: Dictionary of provider configurations
            source: Source name for logging ("MongoDB" or "YAML")

        Returns:
            Number of successfully initialized providers
        """
        successfully_initialized = 0

        for name, config in providers.items():
            api_key = self.config_loader.get_api_key(config.api_key_ref)
            if not api_key:
                logger.warning(f"[{source}] API key not found for provider '{name}': {config.api_key_ref}")
                continue

            try:
                self.clients[name] = AsyncOpenAI(
                    api_key=api_key,
                    base_url=config.base_url,
                )
                self.cost_tracker[name] = 0.0
                logger.info(f"[{source}] Initialized client for provider '{name}'")
                successfully_initialized += 1
            except Exception as e:
                logger.error(f"[{source}] Failed to initialize client for '{name}': {e}")

        return successfully_initialized

    def get_providers(self) -> Dict[str, LLMConfig]:
        """Get all providers."""
        return self.providers

    def get_provider(self, name: str) -> Optional[LLMConfig]:
        """Get a specific provider by name."""
        return self.providers.get(name)

    def get_current_provider(self) -> Optional[str]:
        """Get the current active provider name."""
        return self.current_provider

    def set_current_provider(self, name: str) -> bool:
        """
        Set the current active provider.

        Args:
            name: Provider name

        Returns:
            True if successful, False otherwise
        """
        if name not in self.providers:
            logger.error(f"Provider {name} not found")
            return False

        if name not in self.clients:
            logger.error(f"Client not initialized for provider {name}")
            return False

        self.current_provider = name
        logger.info(f"Set current provider to {name}")
        return True

    def get_enabled_providers(self) -> List[LLMConfig]:
        """Get all enabled providers sorted by priority."""
        return self.config_loader.get_enabled_providers(self.providers)

    def get_client(self, provider_name: Optional[str] = None) -> Optional[AsyncOpenAI]:
        """
        Get a client for the specified provider (or current provider).

        Args:
            provider_name: Provider name (uses current if not specified)

        Returns:
            AsyncOpenAI client or None
        """
        name = provider_name or self.current_provider
        if not name:
            logger.error("No provider specified and no current provider set")
            return None

        return self.clients.get(name)

    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Generate a completion using the specified or current provider.

        Args:
            messages: List of messages in OpenAI format
            model: Model to use (uses provider's default if not specified)
            provider: Provider name (uses current if not specified)
            temperature: Temperature override
            max_tokens: Max tokens override
            **kwargs: Additional parameters to pass to the API

        Returns:
            Generated text or None
        """
        provider_name = provider or self.current_provider
        if not provider_name:
            logger.error("No provider available")
            return None

        provider_config = self.providers.get(provider_name)
        if not provider_config:
            logger.error(f"Provider {provider_name} not found")
            return None

        client = self.clients.get(provider_name)
        if not client:
            logger.error(f"Client not initialized for {provider_name}")
            return None

        try:
            route = _classify_base_url(provider_config.base_url)
            logger.info(
                "ProviderManager call start route=%s provider=%s model=%s base_url=%s messages=%s max_tokens=%s temperature=%s",
                route,
                provider_name,
                model or provider_config.model,
                provider_config.base_url,
                len(messages),
                max_tokens or provider_config.max_tokens,
                temperature or provider_config.temperature,
            )
            response = await client.chat.completions.create(
                model=model or provider_config.model,
                messages=messages,
                temperature=temperature or provider_config.temperature,
                max_tokens=max_tokens or provider_config.max_tokens,
                top_p=provider_config.top_p,
                timeout=provider_config.timeout,
                **kwargs,
            )

            result = response.choices[0].message.content

            # Track cost (simple approximation)
            if response.usage:
                total_tokens = response.usage.total_tokens
                cost = (total_tokens / 1000) * provider_config.cost_per_1k_tokens
                self.cost_tracker[provider_name] += cost
                logger.debug(
                    f"Provider {provider_name}: "
                    f"{total_tokens} tokens, ${cost:.6f} cost"
                )

            logger.info(
                "ProviderManager call success route=%s provider=%s model=%s content_len=%s",
                route,
                provider_name,
                model or provider_config.model,
                len(result or ""),
            )
            return result

        except Exception as e:
            logger.error(f"Error calling {provider_name}: {e}")
            # Could implement fallback strategy here
            return None

    def get_cost_summary(self) -> Dict[str, float]:
        """Get cost summary for all providers."""
        return self.cost_tracker.copy()

    def reset_costs(self, provider_name: Optional[str] = None):
        """
        Reset cost tracking.

        Args:
            provider_name: Reset only this provider (all if not specified)
        """
        if provider_name:
            self.cost_tracker[provider_name] = 0.0
        else:
            for name in self.cost_tracker:
                self.cost_tracker[name] = 0.0

    def get_provider_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get provider information including cost and status."""
        provider = self.providers.get(name)
        if not provider:
            return None

        return {
            **provider.to_dict(),
            "cost_accumulated": self.cost_tracker.get(name, 0.0),
            "is_current": name == self.current_provider,
            "is_initialized": name in self.clients,
        }

    def select_provider_by_capabilities(
        self,
        required_capabilities: List[str],
        min_context_window: Optional[int] = None,
        embedding_dimensions: Optional[int] = None,
    ) -> Optional[str]:
        """
        Select the best provider based on required capabilities.

        Selection strategy:
        1. Filter providers that have all required capabilities
        2. Filter by embedding dimensions if specified (for embedding models)
        3. Filter by minimum context window if specified
        4. Sort candidates by: priority (desc), context_window (desc), cost (asc)
        5. Return the highest-ranked provider

        Args:
            required_capabilities: List of required capabilities (e.g., ["chat", "vision"])
            min_context_window: Minimum context window required
            embedding_dimensions: Required embedding dimensions (for embedding models)

        Returns:
            Best matching provider name, or None if no suitable provider found
        """
        candidates = []

        for name, config in self.providers.items():
            # Skip if client not initialized
            if name not in self.clients:
                continue

            # Check if provider has all required capabilities
            provider_caps = config.capabilities or []
            if not all(cap in provider_caps for cap in required_capabilities):
                continue

            # Check embedding dimensions if specified
            if embedding_dimensions is not None:
                if config.embedding_dimensions != embedding_dimensions:
                    continue

            # Check minimum context window if specified
            if min_context_window is not None:
                if (config.context_window or 0) < min_context_window:
                    continue

            # Provider meets all criteria
            candidates.append({
                "name": name,
                "priority": config.priority or 0,
                "context_window": config.context_window or 0,
                "cost": config.cost_per_1k_tokens or 0.0,
            })

        if not candidates:
            logger.warning(
                f"No provider found matching requirements: "
                f"capabilities={required_capabilities}, "
                f"context_window>={min_context_window}, "
                f"embedding_dimensions={embedding_dimensions}"
            )
            return None

        # Sort by: priority (desc), context_window (desc), cost (asc)
        candidates.sort(
            key=lambda x: (
                -x["priority"],      # Higher priority first
                -x["context_window"], # Larger context window first
                x["cost"]             # Lower cost first
            )
        )

        best = candidates[0]
        logger.info(
            f"Selected provider '{best['name']}' for capabilities {required_capabilities}. "
            f"Matched {len(candidates)} candidates, "
            f"priority={best['priority']}, "
            f"context_window={best['context_window']}, "
            f"cost=${best['cost']}/1k tokens"
        )

        return best["name"]
