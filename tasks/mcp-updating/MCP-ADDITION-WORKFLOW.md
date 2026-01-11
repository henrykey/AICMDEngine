# MCP Addition Workflow (新增MCP工作流程)

**Date**: 2026-01-09
**Status**: Planning Phase Complete - Ready for Phase 1 Execution
**Reference**: Phase 1 will implement this workflow with Membership API

---

## 📋 Quick Checklist (Quick Start for Developers)

When adding a new MCP, follow this checklist in order:

### Pre-Implementation (1 hour)
- [ ] **1. Prepare API Specification**
  - [ ] Gather current API documentation
  - [ ] Document all endpoints (GET, POST, PUT, DELETE, etc.)
  - [ ] Document request/response schemas
  - [ ] Note authentication requirements

- [ ] **2. Set Up Knowledge Base**
  - [ ] Insert API spec into MongoDB collection `api_specs`
  - [ ] Upload documentation to MinIO bucket `api-docs/{api_name}/`
  - [ ] Create example payloads in MinIO

- [ ] **3. Set Up Configuration**
  - [ ] Add API credentials to `.env` file
  - [ ] If production: Add provider config to MongoDB `llm_providers` (if API needs special LLM handling)

### MCP Implementation (2-3 days)
- [ ] **4. Create MCP Server Skeleton**
  - [ ] Create `mcp_servers/{api_name}_mcp.py`
  - [ ] Extend `BaseMCPServer` class
  - [ ] Implement required methods

- [ ] **5. Implement API Commands**
  - [ ] Load API spec from MongoDB
  - [ ] Implement all command tools from spec
  - [ ] Add request validation
  - [ ] Add response parsing

- [ ] **6. Add Error Handling**
  - [ ] Implement JSONPath extraction for responses
  - [ ] Add error classification
  - [ ] Implement retry logic for transient failures

### Integration & Testing (1-2 days)
- [ ] **7. Integrate with Planning Engine**
  - [ ] Register MCP with MCPRegistry
  - [ ] Update planning engine to recognize new MCP commands
  - [ ] Add MCP to LLM context for planning decisions

- [ ] **8. Integration Testing**
  - [ ] Test all command execution paths
  - [ ] Test error handling
  - [ ] Test with actual Planning Engine task execution
  - [ ] Test cross-MCP workflows (if applicable)

### Validation & Deployment (1 day)
- [ ] **9. Performance Testing**
  - [ ] Measure command execution time
  - [ ] Measure response parsing time
  - [ ] Compare against original HTTP client baseline
  - [ ] Should be < 10% slower

- [ ] **10. User Acceptance Testing**
  - [ ] Run sample tasks using new MCP
  - [ ] Verify error handling in realistic scenarios
  - [ ] Document any anomalies

- [ ] **11. Documentation**
  - [ ] Create MCP-specific documentation
  - [ ] Document command tool schemas
  - [ ] Document error codes and handling
  - [ ] Add to system documentation

- [ ] **12. Deployment**
  - [ ] Update docker-compose or k8s configs
  - [ ] Set up monitoring/logging
  - [ ] Deploy to staging
  - [ ] Deploy to production with rollback plan

---

## 🔧 Detailed Workflow

### Phase 1: Preparation (1 hour)

#### 1.1 Gather API Specification

**Input**: Raw API documentation (usually REST API docs, OpenAPI/Swagger, or internal docs)

**Tasks**:
```
1. Identify all API endpoints
   ├─ List all HTTP methods (GET, POST, PUT, DELETE, PATCH, etc.)
   ├─ Document path parameters
   ├─ Document query parameters
   ├─ Document request body schema (if applicable)
   └─ Document response schema

2. Identify authentication
   ├─ API key location (header, query param, body)
   ├─ Token format (Bearer, Custom header, etc.)
   ├─ Token refresh requirements
   └─ Rate limiting policies

3. Identify error handling
   ├─ HTTP status codes returned
   ├─ Error response format
   ├─ Retry-able vs permanent errors
   └─ Timeout expectations
```

**Output**: Structured API spec document (will be stored in MongoDB)

**Example for Membership API**:
```json
{
  "api_name": "membership",
  "version": "2.0",
  "base_url": "https://api.example.com",
  "authentication": {
    "type": "bearer_token",
    "header": "Authorization",
    "env_var": "MEMBERSHIP_API_TOKEN"
  },
  "endpoints": [
    {
      "method": "GET",
      "path": "/v2/members",
      "description": "List all members",
      "parameters": {
        "query": [
          {"name": "page", "type": "integer", "required": false, "default": 1}
        ]
      },
      "response_schema": {
        "type": "object",
        "properties": {
          "members": {"type": "array"},
          "total": {"type": "integer"}
        }
      }
    }
  ]
}
```

#### 1.2 Store API Specification in MongoDB

**Action**: Insert spec into MongoDB collection

```bash
# MongoDB shell or Python driver
db.api_specs.insertOne({
  api_name: "membership",
  version: "2.0",
  base_url: "https://api.example.com",
  # ... (full spec as above)
  created_at: new Date(),
  updated_at: new Date()
})
```

**Why MongoDB?**
- Phase 1 scale: 1-2 APIs (perfect for MongoDB)
- Access pattern: Load once on startup, cache in memory
- Updates: Infrequent (when API spec changes)
- Cost: Already deployed, zero additional cost

#### 1.3 Upload Documentation to MinIO

**Structure**:
```
api-docs/
├── {api_name}/
│   ├── README.md                 (main documentation)
│   ├── authentication.md         (how to auth)
│   ├── examples/
│   │   ├── list_members.json     (request/response example)
│   │   ├── create_member.json
│   │   └── error_response.json
│   └── troubleshooting.md        (common issues)
```

**Why MinIO?**
- Designed for large files (documentation, examples)
- Easy to organize hierarchically
- Already deployed for other purposes
- Access via S3 API

**Example Upload** (Python):
```python
from minio import Minio

minio_client = Minio("minio.example.com",
                     access_key="...",
                     secret_key="...")

# Upload main README
minio_client.fput_object(
    "api-docs",
    "membership/README.md",
    "/local/path/membership_README.md"
)
```

#### 1.4 Configure API Credentials

**Action**: Add to `.env` file (never commit to repo)

```bash
# .env file
MEMBERSHIP_API_BASE_URL=https://api.example.com
MEMBERSHIP_API_TOKEN=sk_live_xxxxxxxxxxxxx
MEMBERSHIP_API_TIMEOUT=30
```

**Why .env?**
- Keeps secrets out of code repositories
- Easy to manage per-environment (dev/staging/prod)
- Standard practice for credentials

---

### Phase 2: MCP Implementation (2-3 days)

#### 2.1 Create MCP Server File

**Location**: `src/mcp_servers/{api_name}_mcp.py`

**Base Structure**:
```python
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
from mcp_sdk import BaseMCPServer, Tool, ToolResult
from src.services.http_client import HTTPClient
from src.repositories.database import DatabaseRepository

logger = logging.getLogger(__name__)


class MembershipMCPServer(BaseMCPServer):
    """MCP Server for Membership API management"""

    def __init__(self, db_repo: DatabaseRepository, http_client: HTTPClient):
        super().__init__("membership", "2.0")
        self.db_repo = db_repo
        self.http_client = http_client

        # Load API spec from MongoDB
        self.api_spec = self._load_api_spec()

        # Load documentation from MinIO
        self.documentation = self._load_documentation()

        # Register all commands as tools
        self._register_tools()

    def _load_api_spec(self) -> Dict[str, Any]:
        """Load API specification from MongoDB"""
        spec = self.db_repo.find_one(
            "api_specs",
            {"api_name": "membership"}
        )
        if not spec:
            raise ValueError("API spec not found in MongoDB")
        return spec

    def _load_documentation(self) -> str:
        """Load main documentation from MinIO"""
        # TODO: Implement MinIO fetch
        pass

    def _register_tools(self):
        """Register all API endpoints as MCP tools"""
        for endpoint in self.api_spec.get("endpoints", []):
            tool = Tool(
                name=self._generate_tool_name(endpoint),
                description=endpoint.get("description", ""),
                input_schema=self._build_input_schema(endpoint),
                handler=self._create_handler(endpoint)
            )
            self.register_tool(tool)

    # ... implementation details follow
```

#### 2.2 Implement Command Tools

For each API endpoint, create a tool that:
1. Accepts user input matching the endpoint's parameters
2. Validates parameters against the schema
3. Makes HTTP request to the API
4. Parses the response
5. Returns structured result or error

**Example: List Members Tool**
```python
async def list_members(self, page: int = 1) -> ToolResult:
    """
    List all members (GET /v2/members)

    Args:
        page: Page number (default: 1)

    Returns:
        ToolResult with members list
    """
    try:
        # Build request
        params = {"page": page}

        # Execute via HTTPClient
        response = await self.http_client.execute(
            method="GET",
            url=f"{self.api_spec['base_url']}/v2/members",
            params=params,
            auth_token=os.environ.get("MEMBERSHIP_API_TOKEN")
        )

        # Parse response
        members = response.get("members", [])
        total = response.get("total", 0)

        return ToolResult(
            is_error=False,
            content=f"Found {total} members",
            data={
                "members": members,
                "total": total,
                "page": page
            }
        )

    except Exception as e:
        logger.error(f"Failed to list members: {str(e)}")
        return ToolResult(
            is_error=True,
            content=f"Error listing members: {str(e)}",
            error_code="LIST_MEMBERS_FAILED"
        )
```

#### 2.3 Add Response Parsing (JSONPath Extraction)

The execution engine will need to extract values from MCP responses for multi-step workflows.

**Built-in Support**:
```python
# When LLM returns: Extract: response.data[0].member_id
# Extraction should handle:
# - Nested objects: response.user.profile.name
# - Array access: response.members[0].id
# - Multi-step: response.data[0].nested.value

def _parse_response(self, response_text: str, schema: Dict) -> Dict:
    """Parse API response according to schema"""
    import json
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        # Handle error
        pass
```

#### 2.4 Error Handling Strategy

**Error Classification** (for auto-recovery):

```python
class APIError:
    """Structured error from API execution"""

    RETRYABLE_ERRORS = {
        "timeout",                    # Network timeout
        "rate_limit_exceeded",        # Hit rate limit
        "temporary_unavailable",      # 503 Service Unavailable
        "connection_reset"            # Network reset
    }

    PERMANENT_ERRORS = {
        "invalid_request",            # 400 Bad Request
        "authentication_failed",      # 401 Unauthorized
        "not_found",                  # 404 Not Found
        "permission_denied"           # 403 Forbidden
    }

# Example error handling
async def _execute_with_retry(self, func, max_retries=3):
    """Execute with automatic retry for transient failures"""
    for attempt in range(max_retries):
        try:
            return await func()
        except APIError as e:
            if e.type in APIError.RETRYABLE_ERRORS:
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"Retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)
            else:
                raise  # Permanent error, don't retry
```

---

### Phase 3: Integration (1-2 days)

#### 3.1 Register MCP with System

**In MCPRegistry**:
```python
from src.mcp_registry import MCPRegistry

# Register new MCP
registry = MCPRegistry()
registry.register_mcp(
    name="membership",
    mcp_class=MembershipMCPServer,
    enabled=True,
    description="Membership API management"
)
```

#### 3.2 Update Planning Engine

**In LLM Prompt Context**:
```python
# Update system prompt to include new MCP commands
def build_system_prompt(registry: MCPRegistry) -> str:
    prompt = """
You are an AI task planning engine with access to multiple APIs through MCP servers.

Available MCPs and their commands:
"""

    for mcp in registry.get_all_mcps():
        prompt += f"\n## {mcp.name} API\n"
        prompt += f"Description: {mcp.description}\n"
        prompt += f"Commands:\n"

        for tool in mcp.get_tools():
            prompt += f"- {tool.name}: {tool.description}\n"

    return prompt
```

#### 3.3 Enable Cross-MCP Workflows

**Pattern**: When Task 2 uses output from Task 1

```python
# Example: Order workflow using Membership + Billing MCPs
task1 = {
    "description": "Get member details",
    "mcp": "membership",
    "command": "get_member",
    "params": {"member_id": 123}
}

task2 = {
    "description": "Create order for that member",
    "mcp": "billing",
    "command": "create_order",
    "params": {
        "customer_id": "${task1.response.customer_id}",  # JSONPath extraction
        "items": [...]
    }
}
```

---

### Phase 4: Testing (1-2 days)

#### 4.1 Unit Tests

**File**: `tests/mcp_servers/test_membership_mcp.py`

```python
import pytest
from src.mcp_servers.membership_mcp import MembershipMCPServer

@pytest.fixture
def mcp_server():
    return MembershipMCPServer(db_repo=mock_db, http_client=mock_http)

async def test_list_members_success(mcp_server):
    """Test successful member list"""
    result = await mcp_server.list_members(page=1)

    assert not result.is_error
    assert result.data["total"] > 0
    assert "members" in result.data

async def test_list_members_with_pagination(mcp_server):
    """Test pagination parameters"""
    result = await mcp_server.list_members(page=2)
    assert not result.is_error

async def test_list_members_api_error(mcp_server):
    """Test error handling"""
    # Mock HTTP client to return error
    mock_http.side_effect = APIError("Connection timeout")

    result = await mcp_server.list_members()
    assert result.is_error
    assert result.error_code == "LIST_MEMBERS_FAILED"
```

#### 4.2 Integration Tests

**Pattern**: Test MCP within Planning Engine

```python
async def test_planning_with_membership_mcp():
    """Test Planning Engine using Membership MCP"""

    task_description = "Get member details for member ID 123"

    plan = await planning_engine.create_plan(task_description)

    # Should recognize Membership MCP command
    assert any(step.mcp_name == "membership" for step in plan.steps)

    # Execute plan
    result = await planning_engine.execute_plan(plan)

    assert result.success
    assert "member" in result.final_output
```

#### 4.3 Performance Testing

**Baseline**: Compare against original HTTP client execution time

```python
# Original approach (HTTP client direct)
original_time = measure_http_client_performance(100_iterations)

# New approach (via MCP)
mcp_time = measure_mcp_performance(100_iterations)

# MCP should be < 10% slower
assert mcp_time < original_time * 1.10
```

---

### Phase 5: Deployment (1 day)

#### 5.1 Configuration Management

**Development** (local .env):
```bash
MEMBERSHIP_API_TOKEN=dev_token_xxxxx
MEMBERSHIP_API_BASE_URL=https://dev-api.example.com
```

**Staging** (environment variable):
```bash
export MEMBERSHIP_API_TOKEN=${STAGING_MEMBERSHIP_TOKEN}
export MEMBERSHIP_API_BASE_URL=https://staging-api.example.com
```

**Production** (K8s secret or vault):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: membership-api
data:
  token: <base64-encoded-production-token>
  base_url: <base64-encoded-production-url>
```

#### 5.2 Monitoring Setup

**Metrics to Collect**:
```python
# For each MCP command
metrics = {
    "command_execution_time": histogram,      # Time to execute command
    "response_parsing_time": histogram,       # Time to parse response
    "error_rate": counter,                    # % of executions that fail
    "retry_rate": counter,                    # % of retries attempted
    "cache_hit_rate": counter,                # MongoDB/MinIO cache effectiveness
}

# Logging
logger.info(f"MCP: membership.list_members executed in {duration}ms")
logger.error(f"MCP: membership.list_members failed: {error_type}")
```

#### 5.3 Rollback Plan

**If Issues Detected**:
1. Disable new MCP in MCPRegistry
2. Planning Engine falls back to original HTTP client (if enabled as fallback)
3. Investigate root cause
4. Fix and redeploy

---

## 📊 Timeline Estimate by Phase

| Phase | Duration | Key Activities |
|-------|----------|-----------------|
| **Preparation** | 1 hour | Spec gathering, MongoDB/MinIO setup |
| **MCP Development** | 2-3 days | Server skeleton, tools, error handling |
| **Integration** | 1-2 days | Registry, planning engine, workflows |
| **Testing** | 1-2 days | Unit, integration, performance tests |
| **Deployment** | 1 day | Config, monitoring, rollback setup |
| **Total** | 5-9 days | End-to-end new MCP addition |

**Note**: This assumes the MCP framework and base infrastructure (MongoDB, MinIO, HTTPClient) are already in place from Phase 1.

---

## 🔄 Reference: Phase 1 Implementation (Membership MCP)

Phase 1 will implement this exact workflow with Membership API as the first MCP.

**Membership API Characteristics**:
- REST API with standard GET/POST/PUT/DELETE endpoints
- Bearer token authentication
- JSON request/response format
- Standard error codes (400, 401, 403, 404, 500)
- ~10-15 core endpoints
- Perfect case study for MCP pattern

**Phase 1 Deliverables**:
1. ✅ MCP Base Framework (BaseMCPServer, MCPRegistry, Tool system)
2. ✅ Membership MCP Implementation (all endpoints as tools)
3. ✅ Planning Engine Integration (recognizes Membership commands)
4. ✅ Error Handling & Retry Logic
5. ✅ Documentation & Monitoring

**After Phase 1, this workflow becomes repeatable**: Adding MCP 2, 3, 4... follows the same pattern.

---

## ❓ FAQ: Adding New MCPs

**Q: Can we add multiple MCPs in parallel?**
A: Not recommended. Phase 1 proves the pattern with one MCP (Membership). Phase 2 adds second MCP (TBD) with learnings from Phase 1. After that, teams can work in parallel.

**Q: What if API doesn't have OpenAPI/Swagger spec?**
A: Create spec from raw documentation or API exploration. Follow the same JSON schema structure.

**Q: How do we handle API changes (breaking)?**
A: Version the API spec in MongoDB. MCPRegistry can support multiple versions. Plan version migration.

**Q: What if MCP performance is too slow?**
A: Phase 1 includes performance testing (< 10% slower target). If exceeded, profile and optimize:
- Add response caching
- Implement connection pooling
- Batch requests where possible
- Consider async/concurrent execution

**Q: Who owns the MCP after creation?**
A: Recommendation: Team that owns the API owns the corresponding MCP. They maintain the spec, docs, and MCP implementation.

**Q: Can MCPs call each other?**
A: Not directly. Planning Engine coordinates multi-MCP workflows by:
1. Execute Step 1 (MCP A)
2. Extract response values with JSONPath
3. Pass to Step 2 (MCP B)
4. Continue until complete

---

**Last Updated**: 2026-01-09
**Next Phase**: Phase 1 Execution - Implement Membership MCP following this workflow
