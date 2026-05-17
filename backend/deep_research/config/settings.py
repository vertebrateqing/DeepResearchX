from __future__ import annotations

"""Configuration management for DeepResearchX.

Settings precedence (highest first):
1. Environment variables (e.g. ``LLM_API_KEY``)
2. ``.env`` file at the project root (loaded once at import time)
3. Defaults defined in ``config/default.yaml``
4. Field defaults declared on the pydantic models below
"""

import os
import re
from pathlib import Path
from typing import Any, Literal, Optional, Union

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path(__file__).parent / "default.yaml"
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # backend/

# Load .env once at import. Look in the backend dir, then the repo root.
for env_dir in (PROJECT_ROOT, PROJECT_ROOT.parent):
    env_file = env_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)
        break


# ---------------------------------------------------------------------------
# Sub-config models
# ---------------------------------------------------------------------------


class LLMConfig(BaseSettings):
    provider: Literal["openai", "local"] = "openai"
    model: str = "gpt-4o"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: int = 120

    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")


class EmbeddingConfig(BaseSettings):
    provider: Literal["openai", "local"] = "openai"
    model: str = "text-embedding-3-large"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 60
    local_model_path: Optional[str] = None
    batch_size: int = 32
    device: Literal["auto", "cpu", "cuda"] = "auto"

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", extra="ignore")


class VectorDBConfig(BaseSettings):
    path: str = "./deep_research/data/vector_db"
    collection_name: str = "research_documents"
    distance_fn: Literal["cosine", "l2", "ip"] = "cosine"


class BM25Config(BaseSettings):
    index_path: str = "./deep_research/data/bm25_index"
    k1: float = 1.5
    b: float = 0.75


class TextSplitterConfig(BaseSettings):
    chunk_size: int = 512
    chunk_overlap: int = 64
    separators: list[str] = Field(default_factory=lambda: ["\n\n", "\n", "。", "；", "，", " ", ""])


class RetrievalConfig(BaseSettings):
    top_k_vector: int = 20
    top_k_bm25: int = 20
    top_k_final: int = 10
    rerank: bool = True
    rerank_top_k: int = 5


class RAGConfig(BaseSettings):
    vector_db: VectorDBConfig = Field(default_factory=VectorDBConfig)
    bm25: BM25Config = Field(default_factory=BM25Config)
    text_splitter: TextSplitterConfig = Field(default_factory=TextSplitterConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)


class WebSearchConfig(BaseSettings):
    provider: Literal["tavily", "duckduckgo"] = "tavily"
    api_key: Optional[str] = None
    max_results: int = 10


class WebScraperConfig(BaseSettings):
    enabled: bool = True
    timeout: int = 30
    concurrency: int = 5
    max_pages: int = 5
    chunk_size: int = 2048
    chunk_overlap: int = 128
    max_text_length: int = 30000
    max_chunks_for_embedding: int = 50


class DataSourcesConfig(BaseSettings):
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    web_scraper: WebScraperConfig = Field(default_factory=WebScraperConfig)


class AgentConfig(BaseSettings):
    model: str = "gpt-4o"
    system_prompt: str = ""


class VLMConfig(BaseSettings):
    enabled: bool = False

    model_config = SettingsConfigDict(env_prefix="VLM_", extra="ignore")


class AgentsConfig(BaseSettings):
    orchestrator: AgentConfig = Field(default_factory=AgentConfig)
    rag_agent: AgentConfig = Field(default_factory=AgentConfig)


class LoggingConfig(BaseSettings):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "console"] = "json"
    file: Optional[str] = None


class OutputConfig(BaseSettings):
    output_dir: str = "./deep_research/data/output"


class LangfuseConfig(BaseSettings):
    enabled: bool = False
    public_key: Optional[str] = None
    secret_key: Optional[str] = None
    host: str = "http://localhost:3000"
    dataset_name: str = "deepresearchx-production"
    flush_at: int = 15
    flush_interval: float = 0.5
    record_dataset: bool = False
    dataset_max_items: int = 1

    model_config = SettingsConfigDict(env_prefix="LANGFUSE_", extra="ignore")


# ---------------------------------------------------------------------------
# Top-level settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Application settings loaded from YAML + environment variables."""

    model_config = SettingsConfigDict(extra="ignore")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    data_sources: DataSourcesConfig = Field(default_factory=DataSourcesConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    vlm: VLMConfig = Field(default_factory=VLMConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)

    @classmethod
    def from_yaml(cls, path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> "Settings":
        """Load settings from YAML, expanding ``${VAR}`` / ``${VAR:-default}`` patterns."""
        path = Path(path)
        if not path.exists():
            return cls()

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        return cls(**_expand_env_vars(raw))

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_ENV_PATTERN = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _expand_env_vars(obj: Any) -> Any:
    """Recursively expand ``${VAR}`` / ``${VAR:-default}`` in nested data."""
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(v) for v in obj]
    if isinstance(obj, str):
        return _ENV_PATTERN.sub(_replace_env, obj)
    return obj


def _replace_env(match: re.Match) -> str:
    var_name = match.group(1)
    default = match.group(2)
    value = os.environ.get(var_name)
    if value is not None:
        return value
    if default is not None:
        return default
    return match.group(0)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
    return _settings


def reload_settings() -> Settings:
    """Force reload — useful in tests."""
    global _settings
    _settings = Settings.from_yaml()
    return _settings
