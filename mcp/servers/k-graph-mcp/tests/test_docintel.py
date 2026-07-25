from datetime import datetime, timezone

import httpx
import pytest

from k_graph_mcp.contracts import BuildStatus
from k_graph_mcp.docintel import (
  DocIntelSourceChangedError,
  HttpDocIntelProvider,
  SourceInvariantError,
)
from k_graph_mcp.lifecycle import (
  AuthorizationRequiredError,
  BuildRecord,
  RetryableBuildError,
)


HASH_A = "sha256:" + "a" * 64
FINGERPRINT = "sha256:" + "f" * 64


def test_reads_all_pages_with_fresh_service_token_and_exact_scope() -> None:
  requests: list[httpx.Request] = []

  def handler(request: httpx.Request) -> httpx.Response:
    requests.append(request)
    body = __import__("json").loads(request.content)
    page_no = 1 if body["cursor"] is None else 2
    return httpx.Response(200, json={
      "scope_fingerprint": FINGERPRINT,
      "pages": [{
        "tenant_id": "12",
        "document_id": "doc-1",
        "version": 3,
        "content_hash": HASH_A,
        "page_no": page_no,
        "page_text": f"page {page_no}",
        "semantic_desc": None,
        "chunks": [{
          "chunk_id": f"chunk-{page_no}",
          "page_no": page_no,
          "chunk_text": f"page {page_no}",
        }],
      }],
      "next_cursor": "next" if page_no == 1 else None,
    })

  tokens = RecordingTokenProvider()
  provider = HttpDocIntelProvider(
    base_url="http://membership",
    token_provider=tokens,
    client=httpx.Client(transport=httpx.MockTransport(handler)),
    page_size=1,
  )

  pages = tuple(provider.iter_pages(build_record()))

  assert [page.page_no for page in pages] == [1, 2]
  assert tokens.tenants == ["12", "12"]
  assert requests[0].headers["Authorization"] == "Bearer service-token-1"
  assert requests[1].headers["Authorization"] == "Bearer service-token-2"
  first_body = __import__("json").loads(requests[0].content)
  assert first_body["document_group"] == [{
    "document_id": "doc-1",
    "version": 3,
    "content_hash": HASH_A,
  }]
  assert first_body["tenant_id"] == "12"
  assert requests[0].headers["X-Tenant-ID"] == "12"


def test_trusts_docintel_document_and_chunk_scope_contract() -> None:
  provider = provider_for(httpx.Response(200, json={
    "scope_fingerprint": "docintel-owned-response-id",
    "pages": [{
      "tenant_id": "docintel-tenant",
      "document_id": "doc-2",
      "version": 3,
      "content_hash": HASH_A,
      "page_no": 1,
      "page_text": "DocIntel contract content",
      "semantic_desc": None,
      "chunks": [{
        "chunk_id": "chunk-2",
        "page_no": 2,
        "chunk_text": "DocIntel contract chunk",
      }],
    }],
    "next_cursor": None,
  }))

  pages = tuple(provider.iter_pages(build_record()))

  assert pages[0].document_id == "doc-2"
  assert pages[0].chunks[0].page_no == 2


@pytest.mark.parametrize(
  ("status", "expected"),
  [
    (401, AuthorizationRequiredError),
    (403, AuthorizationRequiredError),
    (429, RetryableBuildError),
    (503, RetryableBuildError),
    (409, DocIntelSourceChangedError),
    (422, SourceInvariantError),
  ],
)
def test_classifies_docintel_failure_boundaries(status, expected) -> None:
  provider = provider_for(httpx.Response(status))

  with pytest.raises(expected):
    tuple(provider.iter_pages(build_record()))


def provider_for(response: httpx.Response) -> HttpDocIntelProvider:
  return HttpDocIntelProvider(
    base_url="http://membership",
    token_provider=RecordingTokenProvider(),
    client=httpx.Client(
      transport=httpx.MockTransport(lambda request: response)
    ),
  )


class RecordingTokenProvider:
  def __init__(self):
    self.tenants: list[str] = []

  def get_token(self, tenant_id: str) -> str:
    self.tenants.append(tenant_id)
    return f"service-token-{len(self.tenants)}"


def build_record() -> BuildRecord:
  now = datetime(2026, 7, 24, tzinfo=timezone.utc)
  return BuildRecord(
    build_id="build-1",
    tenant_id="12",
    scope_fingerprint=FINGERPRINT,
    request_id="request-1",
    requested_by="42",
    project_id="project-1",
    source_scope={
      "tenant_id": "12",
      "project_id": "project-1",
      "document_group": [{
        "document_id": "doc-1",
        "version": 3,
        "content_hash": HASH_A,
      }],
      "graph_schema_version": "1",
      "extractor_version": "g29.1",
      "normalization_version": "docintel-normalized-v1",
    },
    status=BuildStatus.RUNNING,
    phase="BUILDING",
    attempt=1,
    prior_build_id=None,
    retry_count=0,
    completed_unit_ids=(),
    cancel_requested=False,
    lease_owner="worker-1",
    lease_expires_at=now,
    lease_reclaims=0,
    next_attempt_at=now,
    created_at=now,
    updated_at=now,
  )
