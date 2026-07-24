"""DocIntel client for the workflow-selected document content contract."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .lifecycle import (
  AuthorizationRequiredError,
  BuildRecord,
  RetryableBuildError,
)


class DocIntelSourceError(RuntimeError):
  """Non-retryable DocIntel contract or source failure."""


class DocIntelSourceChangedError(DocIntelSourceError):
  """The normalized source no longer matches the frozen content hash."""


class SourceInvariantError(DocIntelSourceError):
  """DocIntel response could not be consumed as the declared contract."""


class ServiceTokenProvider(Protocol):
  def get_token(self, tenant_id: str) -> str: ...


class SourceModel(BaseModel):
  model_config = ConfigDict(extra="forbid", frozen=True)


class ScopedChunk(SourceModel):
  chunk_id: str = Field(min_length=1)
  page_no: int = Field(ge=1)
  chunk_text: str | None = None


class ScopedPage(SourceModel):
  tenant_id: str = Field(min_length=1)
  document_id: str = Field(min_length=1)
  version: int = Field(ge=1)
  content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
  page_no: int = Field(ge=1)
  page_text: str
  semantic_desc: str | None = None
  chunks: tuple[ScopedChunk, ...] = ()

  def source_locator(self, chunk_id: str | None = None) -> str:
    base = (
      f"document:{self.document_id}/version:{self.version}/page:{self.page_no}"
    )
    return base if chunk_id is None else f"{base}/chunk:{chunk_id}"


class ScopedContentResponse(SourceModel):
  scope_fingerprint: str
  pages: tuple[ScopedPage, ...]
  next_cursor: str | None = None


class HttpDocIntelProvider:
  def __init__(
    self,
    *,
    base_url: str,
    token_provider: ServiceTokenProvider,
    client: httpx.Client | None = None,
    page_size: int = 20,
  ):
    if not base_url or not base_url.strip():
      raise ValueError("base_url is required")
    if page_size < 1 or page_size > 100:
      raise ValueError("page_size must be between 1 and 100")
    self._url = (
      base_url.rstrip("/") + "/v2/documents/scoped-content:read"
    )
    self._token_provider = token_provider
    self._client = client or httpx.Client(timeout=30)
    self._page_size = page_size

  def iter_pages(self, build: BuildRecord) -> Iterator[ScopedPage]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
      response = self._read_page(build, cursor)
      for page in response.pages:
        yield page

      cursor = response.next_cursor
      if cursor is None:
        return
      if cursor in seen_cursors:
        raise SourceInvariantError("DocIntel pagination cursor repeated")
      seen_cursors.add(cursor)

  def _read_page(
    self,
    build: BuildRecord,
    cursor: str | None,
  ) -> ScopedContentResponse:
    token = self._token_provider.get_token(build.tenant_id)
    scope = build.source_scope
    payload = {
      "project_id": scope.get("project_id"),
      "document_group": scope["document_group"],
      "graph_schema_version": scope["graph_schema_version"],
      "extractor_version": scope["extractor_version"],
      "normalization_version": scope["normalization_version"],
      "scope_fingerprint": build.scope_fingerprint,
      "cursor": cursor,
      "page_size": self._page_size,
    }
    try:
      response = self._client.post(
        self._url,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
      )
    except (httpx.TimeoutException, httpx.NetworkError) as exception:
      raise RetryableBuildError("DocIntel connection failed") from exception

    if response.status_code in (401, 403):
      raise AuthorizationRequiredError(
        "DocIntel service authorization is required"
      )
    if response.status_code in (408, 429) or response.status_code >= 500:
      raise RetryableBuildError("DocIntel is temporarily unavailable")
    if response.status_code == 409:
      raise DocIntelSourceChangedError(
        "DocIntel normalized source changed"
      )
    if response.status_code == 422:
      raise SourceInvariantError(
        "DocIntel rejected the frozen source invariant"
      )
    if response.status_code >= 400:
      raise DocIntelSourceError(
        f"DocIntel rejected scoped content request ({response.status_code})"
      )
    try:
      return ScopedContentResponse.model_validate(response.json())
    except (ValueError, TypeError) as exception:
      raise SourceInvariantError(
        "DocIntel returned an invalid scoped content response"
      ) from exception
