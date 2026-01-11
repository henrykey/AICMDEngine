# MCP Knowledge Service Integration Guide

**Status**: Planning Phase - Detailed Design Document
**Date**: 2026-01-09
**Related**: task_plan.md, PROGRESS.md

---

## Overview

Your existing knowledge service infrastructure (MongoDB, MinIO, Elasticsearch, Milvus) can significantly enhance the MCP architecture by:

1. **Centralizing API Knowledge**: Single source of truth for all API specifications
2. **Enabling Intelligent Suggestions**: Using embeddings and semantic search
3. **Auto-Correction**: Learning from failed patterns
4. **Knowledge Reuse**: All MCPs benefit from shared learning

---

## Architecture

### System Components

```
┌──────────────────────────────────────────────────────────┐
│            Task Planning Engine (LLM)                    │
└────────────────────┬─────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
┌───────────────┐        ┌──────────────────┐
│ MCP Registry  │        │ Knowledge Client │
└───────────────┘        └────────┬─────────┘
        │                         │
        ▼                         ▼
┌────────────────────────────────────────────────┐
│       Unified Knowledge Service Layer           │
├────────────────────────────────────────────────┤
│                                                │
│  ┌──────────────────────────────────────────┐ │
│  │ MongoDB: Specs & Metadata                │ │
│  │ - Command definitions                    │ │
│  │ - Response schemas                       │ │
│  │ - Parameter descriptions                 │ │
│  │ - Error patterns & solutions             │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  ┌──────────────────────────────────────────┐ │
│  │ MinIO: Documentation & Examples          │ │
│  │ - API docs (README, guides)              │ │
│  │ - Code examples & snippets               │ │
│  │ - Troubleshooting guides                 │ │
│  │ - Response examples                      │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  ┌──────────────────────────────────────────┐ │
│  │ Elasticsearch: Full-Text Search          │ │
│  │ - Indexed docs & examples                │ │
│  │ - Field-level search                     │ │
│  │ - Query: "how to extract user ID?"       │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  ┌──────────────────────────────────────────┐ │
│  │ Milvus: Vector Embeddings (Phase 3+)    │ │
│  │ - Endpoint embeddings                    │ │
│  │ - JSONPath pattern embeddings            │ │
│  │ - Task embeddings                        │ │
│  │ - Similar request detection              │ │
│  └──────────────────────────────────────────┘ │
│                                                │
└────────────────────────────────────────────────┘
        │              │              │            │
┌───────▼──┐    ┌──────▼──┐    ┌────▼────┐   ┌──▼────┐
│Membership │    │ Orders  │    │ Billing  │   │ ...   │
│MCP Server │    │MCP Srv  │    │MCP Server│   │MCPs   │
└───────────┘    └─────────┘    └─────────┘   └───────┘
```

---

## Phase-by-Phase Integration

### Phase 1: Basic Knowledge Service (Membership MCP)

**Goal**: Establish foundation for knowledge service usage

**Implementation**:

#### 1.1 MongoDB Integration

Store in a `knowledge` collection:

```javascript
{
  _id: ObjectId(),
  api_name: "membership",
  command: "GET /v2/members",

  // Command metadata
  method: "GET",
  path: "/v2/members",
  description: "Retrieve all members for tenant",

  // Parameters
  parameters: {
    query: {
      page: { type: "integer", required: false },
      limit: { type: "integer", required: false }
    },
    path: {},
    body: null
  },

  // Response schema
  response_schema: {
    type: "object",
    properties: {
      data: {
        type: "array",
        items: {
          type: "object",
          properties: {
            id: { type: "integer" },
            name: { type: "string" },
            email: { type: "string" },
            status: { type: "string" }
          }
        }
      },
      pagination: { ... }
    }
  },

  // Common extraction paths
  common_extractions: [
    { path: "data[0].id", description: "First member's ID" },
    { path: "data[*].id", description: "All member IDs" },
    { path: "pagination.total", description: "Total count" }
  ],

  // Error patterns
  error_patterns: [
    {
      error: "401 Unauthorized",
      cause: "Invalid or expired token",
      solution: "Refresh authentication token"
    },
    {
      error: "403 Forbidden",
      cause: "Insufficient permissions",
      solution: "Request admin access for tenant"
    }
  ]
}
```

**MCP Code**:

```python
# mcp_servers/membership_mcp.py

class MembershipMCPServer(BaseMCPServer):
    def __init__(self, knowledge_service):
        self.knowledge_service = knowledge_service
        # Load Membership API specs on startup
        self.specs = knowledge_service.load_specs("membership")

    async def list_commands(self):
        # Return all commands for this API
        return self.specs["commands"]

    async def analyze_response(self, response, field_needed=None):
        """Suggest extraction paths for response"""
        # Use response schema from knowledge service
        schema = self.specs["response_schema"]

        # Suggest common paths
        suggestions = self.specs["common_extractions"]

        if field_needed:
            # Search for similar fields
            candidates = [s for s in suggestions
                         if field_needed.lower() in s["description"].lower()]
            return candidates

        return suggestions
```

#### 1.2 Elasticsearch Integration

Index all command documentation:

```python
# In knowledge service setup
es_client.index(
    index="api_commands",
    id="membership_get_members",
    body={
        "api": "membership",
        "command": "GET /v2/members",
        "description": "Retrieve all members for tenant",
        "parameters": "page, limit - pagination parameters",
        "response_example": json.dumps(example_response),
        "extraction_tips": "Use data[0].id for first member ID",
        "timestamp": datetime.now()
    }
)
```

**Search Usage in MCP**:

```python
async def suggest_extraction_path(self, response_structure, field_needed):
    """Suggest JSONPath based on ES search"""

    # Search for similar fields in documentation
    search_result = self.es_client.search(
        index="api_commands",
        body={
            "query": {
                "multi_match": {
                    "query": field_needed,
                    "fields": ["description", "extraction_tips"]
                }
            }
        }
    )

    # Extract suggestions from search results
    suggestions = [hit["_source"]["extraction_tips"]
                   for hit in search_result["hits"]["hits"]]

    return suggestions
```

---

### Phase 2: Enhanced Knowledge Service (Multi-MCP Support)

**Goal**: Support multiple MCPs with shared knowledge

**Key Additions**:

#### 2.1 Knowledge Sync Across MCPs

When adding second MCP (Orders API):

```python
# Knowledge service manages all API specs
knowledge_specs = {
    "membership": [...],
    "orders": [...],
    # Extracted common patterns across both
    "common_patterns": {
        "pagination": {...},
        "error_handling": {...},
        "authentication": {...}
    }
}

# Both MCPs access shared patterns
membership_mcp = MembershipMCP(specs=knowledge_specs["membership"])
orders_mcp = OrdersMCP(specs=knowledge_specs["orders"])

# They also share common patterns
shared_patterns = knowledge_specs["common_patterns"]
```

#### 2.2 Learning from Execution

Track successful and failed extraction patterns:

```python
# When JSONPath extraction succeeds
await knowledge_service.track_success(
    api="membership",
    path_used="data[0].id",
    response_structure=response,
    use_case="extract_member_id"
)

# When JSONPath extraction fails
await knowledge_service.track_failure(
    api="membership",
    path_attempted="data.items[0].id",
    actual_structure=response,
    suggestion="data[0].id"
)

# Build pattern database for auto-correction
```

---

### Phase 3: Semantic Search & Auto-Correction (Milvus Integration)

**Goal**: Intelligent suggestions and auto-correction

#### 3.1 Create Vector Embeddings

For each API specification:

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

# Embed API endpoint descriptions
endpoints = [
    ("membership_get", "Retrieve all members for tenant - GET /v2/members"),
    ("membership_create", "Create new member - POST /v2/members"),
    ("orders_list", "List all orders - GET /v1/orders"),
    ("orders_create", "Create new order - POST /v1/orders")
]

embeddings = [
    {"id": name, "vector": model.encode(desc).tolist()}
    for name, desc in endpoints
]

# Store in Milvus
milvus_client.insert("api_endpoints", embeddings)
```

#### 3.2 Semantic Search for Similar Endpoints

```python
async def find_similar_endpoints(self, query: str, limit: int = 5):
    """Find endpoints similar to query"""

    # Embed the query
    query_vector = self.encoder.encode(query).tolist()

    # Search Milvus for similar endpoints
    results = self.milvus_client.search(
        collection_name="api_endpoints",
        data=[query_vector],
        limit=limit
    )

    # Return matching endpoints with their specs
    return [self.specs[result.id] for result in results[0]]
```

#### 3.3 JSONPath Auto-Correction

```python
async def auto_correct_jsonpath(self,
                                failed_path: str,
                                actual_response: dict) -> str:
    """Suggest correct JSONPath based on patterns"""

    # Find similar successful extractions
    path_vector = self.encoder.encode(failed_path).tolist()

    similar_patterns = self.milvus_client.search(
        collection_name="successful_extractions",
        data=[path_vector],
        limit=3
    )

    # Get actual structure and suggest fix
    for pattern in similar_patterns:
        if matches_structure(pattern.structure, actual_response):
            return pattern.correct_path

    return None  # No match found
```

---

## Data Storage Strategy

### MongoDB Collections

```javascript
// 1. API Specifications
db.api_specs.insertOne({
  api: "membership",
  version: "2.0",
  commands: [...],
  response_schemas: {...},
  error_patterns: [...]
})

// 2. Execution Patterns (Learning)
db.execution_patterns.insertOne({
  api: "membership",
  success: true,
  jsonpath: "data[0].id",
  response_structure_hash: "abc123",
  timestamp: ISODate(),
  user_id: "tenant_123"
})

// 3. Error Solutions
db.error_solutions.insertOne({
  api: "membership",
  error_code: 400,
  message: "Invalid parameter",
  common_causes: [...],
  solutions: [...]
})
```

### MinIO Buckets

```
api-docs/
├── membership/
│   ├── README.md
│   ├── authentication.md
│   ├── examples/
│   │   ├── list_members.json
│   │   ├── create_member.json
│   │   └── ...
│   └── troubleshooting.md
├── orders/
│   └── ...
└── shared/
    ├── pagination-guide.md
    ├── error-handling.md
    └── authentication-best-practices.md
```

### Elasticsearch Indices

```
api_commands/
  ├── document: "membership_get_members"
  ├── api: "membership"
  ├── description: "..."
  ├── parameters: "..."
  └── examples: "..."

error_solutions/
  ├── document: "membership_401_token"
  ├── error_code: 401
  ├── solution: "Refresh token..."
  └── tags: ["auth", "token"]

extraction_patterns/
  ├── document: "member_id_extraction"
  ├── pattern: "data[0].id"
  ├── api: "membership"
  └── success_rate: 0.95
```

### Milvus Collections (Phase 3+)

```
api_endpoints/
  ├── id: "membership_get"
  ├── vector: [0.1, 0.2, ..., 0.8]  # 384 dimensions
  └── metadata: {api: "membership", endpoint: "GET /v2/members"}

extraction_patterns/
  ├── id: "pattern_1"
  ├── vector: [...] # Embedding of JSONPath pattern
  └── metadata: {path: "data[0].id", api: "membership", success: true}

task_templates/
  ├── id: "task_1"
  ├── vector: [...] # Embedding of task description
  └── metadata: {description: "Create member and get ID", apis: ["membership"]}
```

---

## API Examples

### Phase 1: Load API Specs

```python
# MCP startup
async def __init__(self):
    # Load from MongoDB
    self.specs = await self.knowledge_service.load_api_specs("membership")

    # Cache in memory (TTL: 300 seconds)
    self.cache = TTLCache(
        ttl=300,
        loader=lambda: self.knowledge_service.load_api_specs("membership")
    )
```

### Phase 2: Track Execution Patterns

```python
# After successful step execution
await self.knowledge_service.track_pattern(
    api="membership",
    command="GET /v2/members",
    jsonpath_used="data[0].id",
    response_structure=response,
    success=True
)
```

### Phase 3: Auto-Correct Failed Paths

```python
# When JSONPath extraction fails
if not extracted_value:
    suggestion = await self.knowledge_service.suggest_jsonpath(
        api="membership",
        response=actual_response,
        field_needed="member_id"
    )

    if suggestion:
        # Try suggested path
        extracted_value = extract_jsonpath(actual_response, suggestion)
```

---

## Implementation Timeline

| Phase | Feature | Timeline | Effort |
|-------|---------|----------|--------|
| 1 | MongoDB + ES basic lookup | Week 1 | 1-2 days |
| 1 | Response schema validation | Week 1 | 0.5 days |
| 2 | Pattern learning (success/fail) | Week 2 | 1 day |
| 2 | Shared pattern extraction | Week 2 | 0.5 days |
| 3 | Milvus embeddings setup | Week 3 | 1.5 days |
| 3 | Semantic search integration | Week 3 | 1 day |
| 3 | Auto-correction using patterns | Week 3 | 1 day |

---

## Success Metrics for Knowledge Service

### Phase 1
- ✅ All API specs loaded correctly from MongoDB
- ✅ ES search finds relevant docs 100% of the time
- ✅ Response schema validation catches structural errors
- ✅ < 100ms latency for spec lookups (with caching)

### Phase 2
- ✅ Pattern database grows by 50+ entries/week
- ✅ Common patterns identified across 2+ APIs
- ✅ Error solution suggestions accurate > 80%

### Phase 3
- ✅ Milvus semantic search finds similar patterns
- ✅ JSONPath auto-correction success rate > 75%
- ✅ System learns from failures and improves over time
- ✅ Latency for semantic search < 200ms

---

## Questions for Team Discussion

1. **Data Privacy**: Should pattern learning include examples of actual user data?
   - Recommendation: Store only structure/schema, not actual values

2. **Update Frequency**: How often should API specs be refreshed?
   - Recommendation: Real-time on API change, cache with 5-min TTL

3. **Versioning**: How to handle API version changes in knowledge service?
   - Recommendation: Store specs per API version, migrate patterns

4. **Permissions**: Who can contribute to shared patterns and error solutions?
   - Recommendation: Any team member, reviewed before going live

---

**Status**: Ready for team review and discussion
**Next**: Await decisions from PROGRESS.md before implementation
