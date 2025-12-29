from fastapi import APIRouter, Depends, HTTPException, Request, Body
from typing import List
from src.models.command_set import CommandSet
from src.models.command import Command
from src.core.deps import get_tenant_id
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

router = APIRouter()

def get_db(request: Request) -> AsyncIOMotorDatabase:
    return request.app.mongodb

# --- Command Sets ---

@router.post("/", response_model=CommandSet)
async def create_command_set(
    command_set: CommandSet,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    # Enforce tenant_id from context
    command_set.tenant_id = tenant_id
    
    # Store
    command_set_dict = command_set.model_dump(by_alias=True, exclude={"id"})
    result = await db["command_sets"].insert_one(command_set_dict)
    
    # Return with ID
    stored_set = await db["command_sets"].find_one({"_id": result.inserted_id})
    return CommandSet(**stored_set)

@router.get("/", response_model=List[CommandSet])
async def list_command_sets(
    tenant_id: str = Depends(get_tenant_id),
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
    tenant_id: str = Depends(get_tenant_id),
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
    tenant_id: str = Depends(get_tenant_id),
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
    tenant_id: str = Depends(get_tenant_id),
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
    tenant_id: str = Depends(get_tenant_id),
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
                    
                    cmd =  {
                        "command": f"{method.upper()} {path}",
                        "summary": operation.get('summary', f"{method.upper()} {path}"),
                        "description": operation.get('description', ''),
                        "parameters": operation.get('parameters', []),
                        "riskLevel": "high" if method.upper() in ['POST', 'PUT', 'DELETE'] else "normal"
                    }
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
