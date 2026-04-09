from typing import Optional, Dict, Any, Union
import logging
import sys
import json
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, model_validator
from dotenv import load_dotenv

# Load .env file
load_dotenv()

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # AI Provider Configuration
    deepseek_api_key: str = Field(default="", env="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1", env="DEEPSEEK_BASE_URL")
    deepseek_model_name: str = Field(default="deepseek-chat", env="DEEPSEEK_MODEL_NAME")

    # Legacy OpenAI Configuration (for fallback)
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    openai_model_name: str = Field(default="gpt-4", env="OPENAI_MODEL_NAME")

    # Database Configuration - primitive fields (Python assembles the URI)
    mongo_user: Optional[str] = Field(default=None, env="MONGO_USER")
    mongo_password: Optional[str] = Field(default=None, env="MONGO_PASSWORD")
    mongo_host: str = Field(default="localhost", env="MONGO_HOST")
    mongo_port: int = Field(default=27017, env="MONGO_PORT")
    mongo_auth_source: str = Field(default="admin", env="MONGO_AUTH_SOURCE")
    # mongodb_uri is assembled by the validator below; MONGODB_URI in .env is for shell/Docker only
    mongodb_uri: str = Field(default="mongodb://localhost:27017", env="MONGODB_URI")
    database_name: str = Field(default="nl_tps", env="DATABASE_NAME")

    @model_validator(mode="after")
    def assemble_mongodb_uri(self) -> "Settings":
        """Build mongodb_uri from primitive MONGO_* fields when available, ignoring any
        shell-expansion expressions that python-dotenv cannot evaluate."""
        if self.mongo_host and self.mongo_host != "localhost":
            if self.mongo_user:
                pwd = f":{self.mongo_password}" if self.mongo_password else ""
                auth = f"{self.mongo_user}{pwd}@"
                query = f"?authSource={self.mongo_auth_source}"
            else:
                auth = ""
                query = ""
            self.mongodb_uri = (
                f"mongodb://{auth}{self.mongo_host}:{self.mongo_port}"
                f"/{self.database_name}{query}"
            )
        return self

    # Tenant Configuration
    fixed_tenant_id: Optional[int] = Field(default=None, env="FIXED_TENANT_ID")

    # Membership Service Configuration
    membership_service_url: str = Field(default="http://localhost:8080", env="MEMBERSHIP_SERVICE_URL")

    # Knowledge Base Configuration
    kb_base_url: str = Field(default="http://localhost:8001", env="KB_BASE_URL")
    kb_api_key: str = Field(default="", env="KB_API_KEY")

    # Elasticsearch / Command Retrieval
    elasticsearch_url: str = Field(default="", env="ELASTICSEARCH_URL")
    elasticsearch_api_key: str = Field(default="", env="ELASTICSEARCH_API_KEY")
    command_search_index: str = Field(default="cmdengine_commands_v1", env="COMMAND_SEARCH_INDEX")
    command_search_index_alias: str = Field(default="cmdengine_commands", env="COMMAND_SEARCH_INDEX_ALIAS")
    command_retrieval_enabled: bool = Field(default=False, env="COMMAND_RETRIEVAL_ENABLED")
    command_retrieval_fallback_to_full_inventory: bool = Field(
        default=True,
        env="COMMAND_RETRIEVAL_FALLBACK_TO_FULL_INVENTORY"
    )
    command_retrieval_top_k: int = Field(default=30, env="COMMAND_RETRIEVAL_TOP_K")
    command_prompt_top_k: int = Field(default=15, env="COMMAND_PROMPT_TOP_K")
    docintel_enabled: bool = Field(default=False, env="DOCINTEL_ENABLED")
    docintel_base_url: str = Field(default="", env="DOCINTEL_BASE_URL")
    docintel_api_key: str = Field(default="", env="DOCINTEL_API_KEY")
    docintel_timeout_ms: int = Field(default=10000, env="DOCINTEL_TIMEOUT_MS")
    docintel_search_path: str = Field(default="/v2/documents/search", env="DOCINTEL_SEARCH_PATH")
    docintel_command_sync_path: str = Field(
        default="/v2/documents/commands/sync/batch",
        env="DOCINTEL_COMMAND_SYNC_PATH"
    )
    docintel_command_delete_path: str = Field(
        default="/v2/documents/commands/delete",
        env="DOCINTEL_COMMAND_DELETE_PATH"
    )
    docintel_command_category_prefix: str = Field(
        default="cmdengine.command",
        env="DOCINTEL_COMMAND_CATEGORY_PREFIX"
    )
    docintel_prefer_remote_retrieval: bool = Field(
        default=True,
        env="DOCINTEL_PREFER_REMOTE_RETRIEVAL"
    )
    docintel_remote_min_results: int = Field(default=1, env="DOCINTEL_REMOTE_MIN_RESULTS")
    docintel_remote_min_top_score: float = Field(default=0.0, env="DOCINTEL_REMOTE_MIN_TOP_SCORE")
    docintel_sync_enabled: bool = Field(default=False, env="DOCINTEL_SYNC_ENABLED")
    docintel_default_user_id: str = Field(default="system", env="DOCINTEL_DEFAULT_USER_ID")
    local_retrieval_enabled: bool = Field(default=False, env="LOCAL_RETRIEVAL_ENABLED")
    local_retrieval_base_url: str = Field(default="", env="LOCAL_RETRIEVAL_BASE_URL")
    local_retrieval_timeout_ms: int = Field(default=10000, env="LOCAL_RETRIEVAL_TIMEOUT_MS")
    local_retrieval_search_path: str = Field(
        default="/v2/documents/search/commands",
        env="LOCAL_RETRIEVAL_SEARCH_PATH"
    )
    local_retrieval_command_sync_path: str = Field(
        default="/v2/documents/commands/sync/batch",
        env="LOCAL_RETRIEVAL_COMMAND_SYNC_PATH"
    )
    local_retrieval_command_delete_path: str = Field(
        default="/v2/documents/commands/delete",
        env="LOCAL_RETRIEVAL_COMMAND_DELETE_PATH"
    )

    # Logging Configuration
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    # JWT Configuration for MCP Router
    jwt_secret_key: str = Field(default="", env="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    jwt_expected_issuer: Optional[str] = Field(default=None, env="JWT_EXPECTED_ISSUER")
    jwt_expected_audience: Optional[str] = Field(default=None, env="JWT_EXPECTED_AUDIENCE")

    # WebSocket Configuration
    ws_ping_interval: int = Field(default=20, env="WS_PING_INTERVAL")
    ws_ping_timeout: int = Field(default=20, env="WS_PING_TIMEOUT")
    ws_max_connections: int = Field(default=1000, env="WS_MAX_CONNECTIONS")

    # MCP Configuration
    mcp_required_scope: str = Field(default="mcp", env="MCP_REQUIRED_SCOPE")

    # External MCPs Configuration
    external_mcps: Any = Field(default={}, env="EXTERNAL_MCPS")

    # Environment
    environment: str = Field(default="development", env="ENVIRONMENT")

    @field_validator('external_mcps', mode='before')
    @classmethod
    def parse_external_mcps(cls, v: Union[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Parse EXTERNAL_MCPS from YAML string or return dict."""
        if isinstance(v, str):
            try:
                import yaml
                result = yaml.safe_load(v)
                return result if isinstance(result, dict) else {}
            except Exception as e:
                logger.warning(f"Failed to parse EXTERNAL_MCPS as YAML: {e}, using empty dict")
                return {}
        return v if isinstance(v, dict) else {}

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables

    @classmethod
    async def load_llm_from_mongodb(cls, db) -> None:
        """Load LLM configuration from MongoDB llm_providers collection and update global settings."""
        try:
            collection = db.llm_providers
            
            # Find the highest priority enabled provider
            doc = await collection.find_one(
                {"enabled": True},
                sort=[("priority", 1)]  # Ascending order, so priority 1 comes first
            )
            
            if doc:
                logger.info(f"Loading LLM config from MongoDB: provider={doc.get('name')}")
                
                # Update settings fields based on MongoDB document
                provider_name = doc.get("name", "").lower()
                
                # Map provider name to settings
                if "deepseek" in provider_name:
                    settings.deepseek_base_url = doc.get("base_url", settings.deepseek_base_url)
                    settings.deepseek_model_name = doc.get("model", settings.deepseek_model_name)
                    if doc.get("api_key"):
                        settings.deepseek_api_key = doc.get("api_key")
                    logger.info(f"Updated Deepseek config from MongoDB: {doc.get('name')}")
                    
                elif "openai" in provider_name:
                    settings.openai_base_url = doc.get("base_url", settings.openai_base_url)
                    settings.openai_model_name = doc.get("model", settings.openai_model_name)
                    if doc.get("api_key"):
                        settings.openai_api_key = doc.get("api_key")
                    logger.info(f"Updated OpenAI config from MongoDB: {doc.get('name')}")
                else:
                    # Generic update for other providers
                    if "deepseek" in doc.get("base_url", "").lower() or "deepseek" in doc.get("model", "").lower():
                        settings.deepseek_base_url = doc.get("base_url", settings.deepseek_base_url)
                        settings.deepseek_model_name = doc.get("model", settings.deepseek_model_name)
                        if doc.get("api_key"):
                            settings.deepseek_api_key = doc.get("api_key")
                    else:
                        settings.openai_base_url = doc.get("base_url", settings.openai_base_url)
                        settings.openai_model_name = doc.get("model", settings.openai_model_name)
                        if doc.get("api_key"):
                            settings.openai_api_key = doc.get("api_key")
                    logger.info(f"Updated config from MongoDB: {doc.get('name')}")
            else:
                logger.warning("No enabled LLM provider found in MongoDB, using environment variables")
                
        except Exception as e:
            logger.warning(f"Failed to load LLM config from MongoDB: {e}, using environment variables")


def setup_logging(settings: Settings):
    """Configure application logging."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


# Global settings instance
settings = Settings()


# Backward compatibility: provide uppercase aliases
def __getattr__(name: str):
    """Provide backward compatibility for old uppercase attribute names."""
    settings_instance = settings
    lower_name = name.lower()

    # Map old names to new names
    name_mapping = {
        "MONGODB_URI": "mongodb_uri",
        "DATABASE_NAME": "database_name",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_BASE_URL": "openai_base_url",
        "OPENAI_MODEL_NAME": "openai_model_name",
        "FIXED_TENANT_ID": "fixed_tenant_id",
    }

    if name in name_mapping:
        return getattr(settings_instance, name_mapping[name])

    raise AttributeError(f"'{type(settings_instance).__name__}' object has no attribute '{name}'")
