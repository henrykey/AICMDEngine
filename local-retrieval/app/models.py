from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CommandDocument(BaseModel):
    external_id: str = Field(..., alias="externalId")
    title: str
    category: str
    content: str
    classification: int = 0
    include_in_kb: bool = Field(default=False, alias="includeInKb")
    tags: Optional[List[str]] = None
    version: Optional[str] = None
    metadata: Dict[str, Any]


class CommandCorpusSyncRequest(BaseModel):
    documents: List[CommandDocument]


class CommandCorpusDeleteRequest(BaseModel):
    external_ids: List[str] = Field(..., alias="externalIds")


class CommandSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=20, alias="topK")
    search_mode: Optional[str] = Field(default="TWO_STAGE", alias="searchMode")
    source_types: Optional[List[str]] = Field(default=None, alias="sourceTypes")
    source_names: Optional[List[str]] = Field(default=None, alias="sourceNames")
    categories: Optional[List[str]] = None
    entity_type: Optional[str] = Field(default="command", alias="entityType")


class CommandSearchResult(BaseModel):
    document_id: str = Field(..., alias="documentId")
    title: str
    category: str
    total_score: float = Field(..., alias="totalScore")
    content: str
    metadata: Dict[str, Any]


class CommandSearchResponse(BaseModel):
    results: List[CommandSearchResult]
    total: int
