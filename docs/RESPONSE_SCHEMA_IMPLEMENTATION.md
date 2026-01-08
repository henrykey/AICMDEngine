# Response Schema Implementation - Spec-Driven API Parsing

## Overview

This document describes the response schema infrastructure that enables accurate API response parsing in the execution engine. Instead of hardcoded logic to handle different response formats, the system now uses OpenAPI specifications to automatically extract and document response structures.

## Architecture

### Three-Layer Response Parsing

```
OpenAPI Spec (v2.4)
    ↓
Response Schema Extraction (command_sets.py)
    ↓
Command Model Storage (response_schema field)
    ↓
Planning Engine (includes schema in LLM context)
    ↓
Execution Engine (uses schema for JSONPath resolution)
```

## Response Schema Format

The system defines response schemas in a standardized internal format:

### 1. Wrapped Array Response
```json
{
  "type": "wrapped",
  "wrapper": "data",
  "items": "array",
  "metadata_wrapper": "meta",
  "description": "Response wrapped in 'data' array with optional 'meta' pagination"
}
```

**Example**: Membership API `GET /v2/members`
```json
{
  "data": [
    { "id": "123", "username": "john", ... },
    { "id": "456", "username": "jane", ... }
  ],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 2,
    "total_pages": 1
  }
}
```

### 2. Wrapped Object Response
```json
{
  "type": "wrapped",
  "wrapper": "data",
  "items": "object",
  "description": "Response wrapped in 'data' object with optional metadata"
}
```

### 3. Direct Object Response
```json
{
  "type": "object",
  "root": "body",
  "description": "Direct object response in body"
}
```

**Example**: Membership API `POST /v2/members`
```json
{
  "id": "789",
  "username": "newuser",
  "email": "user@example.com",
  ...
}
```

### 4. Status-Only Response
```json
{
  "type": "status_code",
  "success_codes": [200, 204],
  "description": "Status-only response, no content"
}
```

**Example**: Membership API `DELETE /v2/members/{id}` returns HTTP 204 with no body

## Implementation Details

### Files Modified

1. **src/models/command.py**
   - Added `response_schema: Optional[Dict[str, Any]]` field to Command model
   - Stores the response structure metadata for each command

2. **src/routers/command_sets.py**
   - Added `_extract_response_schema_from_openapi()`: Main extraction function
   - Added `_analyze_schema_structure()`: Analyzes schemas to detect patterns
   - Added `_resolve_schema_ref()`: Resolves OpenAPI $ref references
   - Updated `smart_import_commands()` to automatically extract and store schemas

3. **src/services/planning_engine.py**
   - Modified `get_available_commands()` to include responseSchema in LLM context
   - Updated LLM instructions to guide JSONPath generation based on response structure

4. **src/services/execution_engine.py**
   - Modified `_resolve_params()` to use response_schemas for accurate JSONPath extraction
   - Added response schema as first priority, fallback to smart detection
   - Enhanced error messages to include available paths and field information

### Schema Extraction Process

```python
# 1. Load OpenAPI spec from YAML/JSON
spec = yaml.safe_load(openapi_document)

# 2. For each endpoint, extract response schema
for path, methods in spec['paths'].items():
    for method, operation in methods.items():
        # 3. Extract from operation.responses.200/201/204.content.application/json.schema
        schema = _extract_response_schema_from_openapi(operation, method.upper(), spec)

        # 4. Handle $ref references (e.g., '#/components/schemas/PageMembers')
        if '$ref' in schema:
            schema = _resolve_schema_ref(schema['$ref'], spec)

        # 5. Analyze structure to determine pattern
        analyzed = _analyze_schema_structure(schema)

        # 6. Store with command
        command['response_schema'] = analyzed
```

### Schema Reference Resolution

OpenAPI specs often use `$ref` to avoid duplication:

```yaml
# In endpoint definition
responses:
  '200':
    content:
      application/json:
        schema:
          $ref: '#/components/schemas/PageMembers'

# In components/schemas section
schemas:
  PageMembers:
    type: object
    properties:
      data:
        type: array
        items:
          $ref: '#/components/schemas/Member'
      meta:
        $ref: '#/components/schemas/PageMeta'
```

The resolver extracts the JSON pointer path (`#/components/schemas/PageMembers`) and navigates the spec document to retrieve the actual schema definition.

## Usage Examples

### Example 1: Extracting JSONPath from Wrapped Array Response

**Command**: `GET /v2/members`
**Response Schema**:
```json
{
  "type": "wrapped",
  "wrapper": "data",
  "items": "array"
}
```

**API Response**:
```json
{
  "data": [
    { "id": "user-123", "username": "alice", ... },
    { "id": "user-456", "username": "bob", ... }
  ],
  "meta": { "page": 1, "page_size": 20, "total": 2 }
}
```

**Correct JSONPath** (for first user ID):
```
$.steps[0].response.data[0].id
```

The execution engine uses the response schema to know:
1. Response is wrapped in "data" field (type: wrapped, wrapper: data)
2. Data contains array items (items: array)
3. So JSONPath should navigate `response.data[0]` not `response[0]`

### Example 2: Extracting from Direct Object Response

**Command**: `POST /v2/members`
**Response Schema**:
```json
{
  "type": "object",
  "root": "body"
}
```

**API Response**:
```json
{
  "id": "new-user-123",
  "username": "newmember",
  "email": "user@example.com"
}
```

**Correct JSONPath** (for user ID):
```
$.steps[0].response.id
```

Direct access to response fields without wrapper navigation.

## Membership API v2.4 Supported Endpoints

All member-related endpoints have been tested and support response schema extraction:

| Endpoint | Method | Response Type | Schema |
|----------|--------|---------------|--------|
| /v2/members | GET | Wrapped Array | `{type: "wrapped", wrapper: "data", items: "array", metadata_wrapper: "meta"}` |
| /v2/members | POST | Direct Object | `{type: "object", root: "body"}` |
| /v2/members/{id} | GET | Direct Object | `{type: "object", root: "body"}` |
| /v2/members/{id} | PUT | Direct Object | `{type: "object", root: "body"}` |
| /v2/members/{id} | DELETE | Status Only | `{type: "status_code", success_codes: [200, 204]}` |

## Error Handling

When JSONPath extraction fails:

1. **Primary**: Try using response schema if available
2. **Fallback**: Check if value is in "data" wrapper field (for backward compatibility)
3. **Error**: If both fail, report which paths/fields are available in the response

Example error message:
```
Failed to extract value from JSONPath: $.steps[0].response.member.id
Available keys in response: ['data', 'meta', 'error']
Available keys in data: ['id', 'username', 'email', 'status']
Suggestion: Try $.steps[0].response.data[0].id
```

## Testing

Test files verify:
1. Schema extraction from synthetic OpenAPI definitions
2. Schema reference resolution for $ref patterns
3. Pattern detection for all schema types (wrapped array, object, direct, status-only)
4. End-to-end command import with schema population
5. Integration with actual Membership v2.4 OpenAPI spec

```bash
# Run tests
python3 /tmp/test_response_schema.py        # Unit tests
python3 /tmp/test_schema_resolution.py      # Reference resolution
python3 /tmp/test_all_membership_schemas.py # All endpoints
python3 /tmp/test_e2e_command_import.py     # End-to-end flow
```

## Future Enhancements

1. **Nested Schema Resolution**: Handle deeply nested $ref chains
2. **Array Item Type Detection**: Extract item schemas from nested objects
3. **Error Response Schemas**: Document expected error response structures
4. **Schema Caching**: Cache resolved schemas to improve performance
5. **Manual Schema Override**: Allow users to specify schemas for non-standard APIs
6. **Schema Validation**: Validate actual responses against extracted schemas

## See Also

- [Command Model Documentation](../src/models/command.py)
- [Execution Engine Documentation](../src/services/execution_engine.py)
- [Planning Engine Documentation](../src/services/planning_engine.py)
- [Membership API v2.4 OpenAPI Spec](./membership_v2.4_openapi.yaml)
