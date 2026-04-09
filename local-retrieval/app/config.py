from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8088, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    data_dir: str = Field(default="/data", alias="DATA_DIR")
    sqlite_db_path: str = Field(default="/data/retrieval.db", alias="SQLITE_DB_PATH")
    ollama_base_url: str = Field(default="http://host.docker.internal:11434", alias="OLLAMA_BASE_URL")
    ollama_embedding_model: str = Field(default="qwen3-embedding:0.6b", alias="OLLAMA_EMBEDDING_MODEL")
    ollama_timeout_ms: int = Field(default=15000, alias="OLLAMA_TIMEOUT_MS")
    vector_search_enabled: bool = Field(default=True, alias="VECTOR_SEARCH_ENABLED")
    vector_score_weight: float = Field(default=0.55, alias="VECTOR_SCORE_WEIGHT")
    keyword_score_weight: float = Field(default=0.45, alias="KEYWORD_SCORE_WEIGHT")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
