from typing import Optional
import logging
import sys
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Configuration
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    openai_model_name: str = Field(default="gpt-4", env="OPENAI_MODEL_NAME")

    # Database Configuration
    mongodb_uri: str = Field(default="mongodb://localhost:27017", env="MONGODB_URI")
    database_name: str = Field(default="nl_tps", env="DATABASE_NAME")

    # Tenant Configuration
    fixed_tenant_id: Optional[int] = Field(default=None, env="FIXED_TENANT_ID")

    # Logging Configuration
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables


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
