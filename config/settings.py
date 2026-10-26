import os
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class AppSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # LLM Settings
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    
    local_llm_base_url: str = Field(default_factory=lambda: os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1"))
    local_llm_api_key: str = Field(default_factory=lambda: os.getenv("LOCAL_LLM_API_KEY", "EMPTY"))
    local_llm_model: str = Field(default_factory=lambda: os.getenv("LOCAL_LLM_MODEL", "qwen2.5-7b-instruct"))
    
    default_llm_provider: str = Field(default_factory=lambda: os.getenv("DEFAULT_LLM_PROVIDER", "gemini"))
    allow_mock_fallback: bool = Field(default_factory=lambda: os.getenv("ALLOW_MOCK_FALLBACK", "true").lower() in ("true", "1", "yes"))
    
    # Storage Paths
    storage_dir: Path = BASE_DIR / "data" / "storage"
    law_dir: Path = BASE_DIR / "data" / "mock_law"
    hsmt_dir: Path = BASE_DIR / "data" / "mock_hsmt"
    hsdt_dir: Path = BASE_DIR / "data" / "mock_hsdt"

settings = AppSettings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
