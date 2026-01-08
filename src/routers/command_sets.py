from fastapi import APIRouter, Depends, HTTPException, Request, Body
from typing import List
from datetime import datetime
from src.models.command_set import CommandSet
from src.models.command import Command
from src.core.deps import get_tenant_id
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

router = APIRouter()

def get_db(request: Request) -> AsyncIOMotorDatabase:
    return request.app.mongodb

# --- Helper Functions ---

def _extract_response_schema_from_openapi(operation: dict, method: str, spec: dict = None) -> dict:
    """
    Extract response schema from OpenAPI operation definition.

    Returns schema in internal format:
    - {"type": "wrapped", "wrapper": "data", "items": "array"} - wrapped in 'data' array
    - {"type": "wrapped", "wrapper": "data", "items": "object"} - wrapped in 'data' object
    - {"type": "object", "root": "body"} - direct object response
    - {"type": "status_code", "success_codes": [200, 204]} - status-only response
    """
    responses = operation.get('responses', {})
    if not responses:
        return None

    # Look for successful responses (2xx codes)
    success_response = None
    for code in ['200', '201', '204']:
        if code in responses:
            success_response = responses[code]
            break

    if not success_response:
        # Try to find any 2xx response
        for code, resp in responses.items():
            if code.startswith('2'):
                success_response = resp
                break

    if not success_response:
        return None

    # Handle status-only responses (204 No Content, or 200 with no content)
    if 'content' not in success_response:
        return {
            "type": "status_code",
            "success_codes": [200, 204],
            "description": "Status-only response, no content"
        }

    content = success_response.get('content', {})
    if not content:
        return None

    # Try JSON content first
    json_content = content.get('application/json', {})
    if not json_content:
        return None

    schema = json_content.get('schema', {})
    if not schema:
        return None

    # Resolve schema references if needed
    if '$ref' in schema and spec:
        schema = _resolve_schema_ref(schema['$ref'], spec)

    # Analyze the schema to determine response structure
    return _analyze_schema_structure(schema)

def _resolve_schema_ref(ref: str, spec: dict) -> dict:
    """
    Resolve OpenAPI schema references like '#/components/schemas/PageMembers'
    """
    if not ref.startswith('#/'):
        return {}

    parts = ref[2:].split('/')  # Remove '#/' and split
    current = spec

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return {}

    return current if isinstance(current, dict) else {}

def _analyze_schema_structure(schema: dict) -> dict:
    """
    Analyze OpenAPI schema to determine response structure.

    Detects patterns like:
    - Direct object response
    - Array wrapped in a property (e.g., "data")
    - Object wrapped in a property
    """
    schema_type = schema.get('type', '')

    # Case 1: Direct array
    if schema_type == 'array':
        return {
            "type": "array",
            "items": "array",
            "description": "Direct array response"
        }

    # Case 2: Direct object
    if schema_type == 'object' or schema_type == '':
        # Check if it has standard wrapping pattern (data + meta)
        properties = schema.get('properties', {})

        if 'data' in properties:
            data_schema = properties['data']
            data_type = data_schema.get('type', '')

            # Wrapped array response
            if data_type == 'array':
                return {
                    "type": "wrapped",
                    "wrapper": "data",
                    "items": "array",
                    "metadata_wrapper": "meta" if 'meta' in properties else None,
                    "description": "Response wrapped in 'data' array with optional 'meta' pagination"
                }

            # Wrapped object response
            if data_type == 'object':
                return {
                    "type": "wrapped",
                    "wrapper": "data",
                    "items": "object",
                    "metadata_wrapper": "meta" if 'meta' in properties else None,
                    "description": "Response wrapped in 'data' object with optional 'meta' info"
                }

        # No wrapping - direct object response
        return {
            "type": "object",
            "root": "body",
            "description": "Direct object response in body"
        }

    # Default: unknown structure
    return None

# --- Command Sets ---

@router.post("/", response_model=CommandSet)
async def create_command_set(
    command_set: CommandSet,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    # Enforce tenant_id from X-Tenant-ID header
    command_set.tenant_id = tenant_id

    # Validate required fields
    if not command_set.name:
        raise HTTPException(status_code=400, detail="Command set name is required")

    # Store in database
    command_set_dict = command_set.model_dump(by_alias=True, exclude={"id"})
    result = await db["command_sets"].insert_one(command_set_dict)

    # Return with ID
    stored_set = await db["command_sets"].find_one({"_id": result.inserted_id})
    return CommandSet(**stored_set)

@router.get("/", response_model=List[CommandSet])
async def list_command_sets(
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    cursor = db["command_sets"].find({"tenant_id": tenant_id})
    results = []
    async for doc in cursor:
        results.append(CommandSet(**doc))
    return results

@router.delete("/{set_id}")
async def delete_command_set(
    set_id: str,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    # Check ownership
    result = await db["command_sets"].delete_one({"_id": ObjectId(set_id), "tenant_id": tenant_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Command set not found")

    # Also delete commands belonging to this set
    await db["commands"].delete_many({"command_set_id": set_id})

    return {"status": "deleted"}

# --- Commands Sub-resource ---

@router.post("/{set_id}/commands", response_model=Command)
async def create_command(
    set_id: str,
    command: Command,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    # Verify parent set existence and ownership
    parent_set = await db["command_sets"].find_one({"_id": ObjectId(set_id), "tenant_id": tenant_id})
    if not parent_set:
        raise HTTPException(status_code=404, detail="Command Set not found")

    command.command_set_id = set_id
    command.tenant_id = tenant_id

    command_dict = command.model_dump(by_alias=True, exclude={"id"})
    result = await db["commands"].insert_one(command_dict)

    stored_cmd = await db["commands"].find_one({"_id": result.inserted_id})
    return Command(**stored_cmd)

@router.get("/{set_id}/commands", response_model=List[Command])
async def list_commands(
    set_id: str,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    # Verify parent set
    parent_set = await db["command_sets"].find_one({"_id": ObjectId(set_id), "tenant_id": tenant_id})
    if not parent_set:
        raise HTTPException(status_code=404, detail="Command Set not found")

    cursor = db["commands"].find({"command_set_id": set_id})
    results = []
    async for doc in cursor:
        results.append(Command(**doc))
    return results

# --- Smart Import (AI-Powered Documentation Parser) ---

@router.post("/{set_id}/import/smart")
async def smart_import_commands(
    set_id: str,
    document: str = Body(..., embed=True),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Smart Import: Detects document type and extracts commands.
    - OpenAPI/Swagger YAML → Direct parsing (no LLM)
    - Other formats → LLM-powered extraction
    """
    from src.services.llm_client import llm_client
    import json
    import yaml

    # Verify parent set existence
    parent_set = await db["command_sets"].find_one({"_id": ObjectId(set_id), "tenant_id": tenant_id})
    if not parent_set:
        raise HTTPException(status_code=404, detail="Command Set not found")
    
    try:
        # Try to detect if it's OpenAPI/Swagger YAML
        is_openapi = False
        try:
            parsed_yaml = yaml.safe_load(document)
            if isinstance(parsed_yaml, dict) and ('openapi' in parsed_yaml or 'swagger' in parsed_yaml):
                is_openapi = True
        except:
            pass
        
        commands_data = []
        
        if is_openapi:
            # Direct OpenAPI parsing (no LLM needed)
            spec = parsed_yaml
            paths = spec.get('paths', {})

            for path, methods in paths.items():
                for method, operation in methods.items():
                    if method.upper() not in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
                        continue

                    # Extract response schema from OpenAPI spec
                    response_schema = _extract_response_schema_from_openapi(
                        operation, method.upper(), spec
                    )

                    cmd = {
                        "command": f"{method.upper()} {path}",
                        "summary": operation.get('summary', f"{method.upper()} {path}"),
                        "description": operation.get('description', ''),
                        "parameters": operation.get('parameters', []),
                        "riskLevel": "high" if method.upper() in ['POST', 'PUT', 'DELETE'] else "normal"
                    }

                    # Add response schema if available
                    if response_schema:
                        cmd["response_schema"] = response_schema

                    commands_data.append(cmd)
                    
        else:
            # Use LLM for non-OpenAPI documents
            # Limit document size for LLM
            doc_preview = document[:10000]  # Only send first 10k chars to avoid token limits
            
            extraction_prompt = f"""Extract commands from this documentation. Return ONLY a JSON array.

Document:
{doc_preview}

Return format:
[
  {{
    "command": "command_name",
    "summary": "one-line description",
    "description": "detailed info",
    "parameters": {{}},
    "riskLevel": "normal"
  }}
]"""

            llm_response = await llm_client.generate_response(
                messages=[{"role": "user", "content": extraction_prompt}],
                temperature=0.0
            )
            
            # Clean markdown
            cleaned = llm_response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                if len(lines) >= 3:
                    cleaned = "\n".join(lines[1:-1])
            
            commands_data = json.loads(cleaned)
        
        if not isinstance(commands_data, list):
            raise HTTPException(status_code=400, detail="Invalid command data format")
        
        # Insert commands
        inserted_count = 0
        for cmd_data in commands_data:
            cmd_data["command_set_id"] = set_id
            cmd_data["tenant_id"] = tenant_id
            await db["commands"].insert_one(cmd_data)
            inserted_count += 1

        # Update command set metadata
        if inserted_count > 0:
            # Parse current version and increment
            current_version = parent_set.get("version", "1.0.0")
            version_parts = current_version.split(".")
            try:
                major = int(version_parts[0])
                minor = int(version_parts[1]) if len(version_parts) > 1 else 0
                patch = int(version_parts[2]) if len(version_parts) > 2 else 0
                # Increment minor version on re-import
                minor += 1
                # Preserve original format (with or without patch)
                if len(version_parts) >= 3:
                    new_version = f"{major}.{minor}.{patch}"
                else:
                    new_version = f"{major}.{minor}"
            except:
                new_version = "1.0.0"

            # Update command set with new timestamp and version
            await db["command_sets"].update_one(
                {"_id": ObjectId(set_id)},
                {
                    "$set": {
                        "updated_at": datetime.utcnow(),
                        "version": new_version
                    }
                }
            )

        return {
            "status": "success",
            "commands_extracted": inserted_count,
            "method": "openapi_parser" if is_openapi else "llm_extraction",
            "message": f"Successfully extracted {inserted_count} commands."
        }
        
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse response: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
