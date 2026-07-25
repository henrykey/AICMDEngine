"""Canonical runtime composition without deployment-side effects."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from pymongo import MongoClient

from .docintel import HttpDocIntelProvider
from .extraction import (
  OpenAIStructuredExtractionClient,
  PageFactExtractor,
  ScopedExtractionRunner,
)
from .graph_store import GraphPublisher, GraphQueryService
from .lifecycle import (
  BuildCoordinator,
  BuildRecord,
  VolatileModelConfigRegistry,
  VolatileServiceTokenRegistry,
)
from .mongo_graph_store import MongoGraphStore
from .mongo_repository import MongoBuildRepository
from .tools import create_mcp


@dataclass(frozen=True)
class RuntimeConfig:
  mongo_uri: str
  mongo_database: str | None
  membership_api_url: str
  llm_api_key: str
  llm_base_url: str | None
  llm_model: str
  max_workers: int = 2
  mcp_host: str = "127.0.0.1"
  mcp_port: int = 9013

  @classmethod
  def from_env(cls) -> "RuntimeConfig":
    return cls(
      mongo_uri=_required_env(
        "K_GRAPH_MCP_MONGODB_URI",
        fallback="DOCS_MONGODB_URI",
      ),
      mongo_database=os.getenv("K_GRAPH_MCP_MONGODB_DATABASE"),
      membership_api_url=_required_env("MEMBERSHIP_API_URL"),
      llm_api_key=_required_env("OPENAI_API_KEY"),
      llm_base_url=os.getenv("OPENAI_BASE_URL") or None,
      llm_model=_required_env("K_GRAPH_MCP_LLM_MODEL"),
      max_workers=int(os.getenv("K_GRAPH_MCP_MAX_WORKERS", "2")),
      mcp_host=os.getenv("MCP_HOST", "127.0.0.1"),
      mcp_port=int(os.getenv("MCP_PORT", "9013")),
    )


class BasinGraphRuntime:
  def __init__(self, config: RuntimeConfig):
    self._mongo = MongoClient(config.mongo_uri, tz_aware=True)
    if config.mongo_database:
      database = self._mongo[config.mongo_database]
    else:
      try:
        database = self._mongo.get_default_database()
      except Exception as exception:
        raise ValueError(
          "Mongo URI must include a database or "
          "K_GRAPH_MCP_MONGODB_DATABASE must be set"
        ) from exception

    build_repository = MongoBuildRepository(database["basin_kg_builds"])
    graph_store = MongoGraphStore(
      versions=database["basin_kg_versions"],
      nodes=database["basin_kg_nodes"],
      edges=database["basin_kg_edges"],
      evidence=database["basin_kg_evidence"],
      gaps=database["basin_kg_gaps"],
    )
    build_repository.ensure_indexes()
    graph_store.ensure_indexes()

    self._http = httpx.Client(timeout=30)
    self._openai = OpenAI(
      api_key=config.llm_api_key,
      base_url=config.llm_base_url,
    )
    credentials = VolatileServiceTokenRegistry()
    model_configs = VolatileModelConfigRegistry()
    provider = HttpDocIntelProvider(
      base_url=config.membership_api_url,
      token_provider=credentials,
      client=self._http,
    )
    extractor = PageFactExtractor(
      client=OpenAIStructuredExtractionClient(
        client=self._openai,
        model=config.llm_model,
        base_url=config.llm_base_url,
      )
    )
    publisher = GraphPublisher(store=graph_store)
    runner = ScopedExtractionRunner(
      provider=provider,
      extractor_factory=lambda record: self._extractor_for(
        record,
        model_configs=model_configs,
        fallback=extractor,
      ),
      publisher=publisher,
    )
    self._coordinator = BuildCoordinator(
      repository=build_repository,
      runner=runner,
      max_workers=config.max_workers,
      credential_registry=credentials,
      model_config_registry=model_configs,
      graph_query=GraphQueryService(
        store=graph_store,
        build_repository=build_repository,
      ),
    )
    self.mcp: FastMCP = create_mcp(
      backend=self._coordinator,
      host=config.mcp_host,
      port=config.mcp_port,
    )

  @staticmethod
  def _extractor_for(
    record: BuildRecord,
    *,
    model_configs: VolatileModelConfigRegistry,
    fallback: PageFactExtractor,
  ) -> PageFactExtractor:
    config = model_configs.get(record.build_id)
    if config is None:
      return fallback
    api_key = _required_config(config, "api_key")
    model = _required_config(config, "model")
    base_url = config.get("base_url")
    client = OpenAI(
      api_key=api_key,
      base_url=base_url if isinstance(base_url, str) and base_url.strip() else None,
      timeout=config.get("timeout_sec"),
    )
    return PageFactExtractor(
      client=OpenAIStructuredExtractionClient(
        client=client,
        model=model,
        provider=(
          config.get("provider")
          if isinstance(config.get("provider"), str)
          else None
        ),
        base_url=(
          base_url
          if isinstance(base_url, str) and base_url.strip()
          else None
        ),
      )
    )

  def close(self) -> None:
    self._coordinator.close()
    self._http.close()
    close_openai = getattr(self._openai, "close", None)
    if callable(close_openai):
      close_openai()
    self._mongo.close()


def create_runtime_from_env() -> BasinGraphRuntime:
  return BasinGraphRuntime(RuntimeConfig.from_env())


def _required_env(name: str, *, fallback: str | None = None) -> str:
  value = os.getenv(name)
  if (value is None or not value.strip()) and fallback is not None:
    value = os.getenv(fallback)
  if value is None or not value.strip():
    suffix = f" or {fallback}" if fallback else ""
    raise ValueError(f"{name}{suffix} is required")
  return value.strip()


def _required_config(config: dict[str, object], name: str) -> str:
  value = config.get(name)
  if not isinstance(value, str) or not value.strip():
    raise ValueError(f"runtime model config {name} is required")
  return value.strip()
