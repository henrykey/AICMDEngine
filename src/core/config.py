import os
import yaml
from typing import Optional
from dotenv import load_dotenv

# Still load dotenv for potential secrets not in YAML (or overrides)
load_dotenv()

class Settings:
    def __init__(self):
        # Default values
        self.MONGODB_URI = "mongodb://localhost:27017"
        self.DATABASE_NAME = "nl_tps"
        self.OPENAI_API_KEY = ""
        self.OPENAI_BASE_URL: Optional[str] = None
        self.OPENAI_MODEL_NAME = "gpt-4-turbo-preview"
        self.FIXED_TENANT_ID: Optional[str] = None

        self.load_from_yaml()
        
        # Env vars override YAML
        self.override_from_env()

    def load_from_yaml(self):
        config_path = os.path.join(os.getcwd(), "config.yml")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    data = yaml.safe_load(f)
                    backend_config = data.get("backend", {})
                    
                    if "mongodb_uri" in backend_config:
                        self.MONGODB_URI = backend_config["mongodb_uri"]
                    if "database_name" in backend_config:
                        self.DATABASE_NAME = backend_config["database_name"]
                    if "openai_api_key" in backend_config:
                         self.OPENAI_API_KEY = backend_config["openai_api_key"]
                    if "openai_base_url" in backend_config:
                         self.OPENAI_BASE_URL = backend_config["openai_base_url"] or None
                    if "openai_model_name" in backend_config:
                         self.OPENAI_MODEL_NAME = backend_config["openai_model_name"]
                    if "fixed_tenant_id" in backend_config:
                         self.FIXED_TENANT_ID = backend_config["fixed_tenant_id"] or None
                         
            except Exception as e:
                print(f"Warning: Failed to load config.yml: {e}")

    def override_from_env(self):
        if os.getenv("MONGODB_URI"): self.MONGODB_URI = os.getenv("MONGODB_URI")
        if os.getenv("DATABASE_NAME"): self.DATABASE_NAME = os.getenv("DATABASE_NAME")
        if os.getenv("OPENAI_API_KEY"): self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        if os.getenv("OPENAI_BASE_URL"): self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
        if os.getenv("OPENAI_MODEL_NAME"): self.OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")
        if os.getenv("FIXED_TENANT_ID"): self.FIXED_TENANT_ID = os.getenv("FIXED_TENANT_ID")

settings = Settings()
