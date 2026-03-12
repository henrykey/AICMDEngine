
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from src.services.mock_data import get_membership_commands

load_dotenv()

async def seed():
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    db_name = os.getenv("DATABASE_NAME", "nl_tps")
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    tenant_id = "tenant-dev-001"
    
    # 1. Create a Default Command Set for Membership
    cs_name = "Membership Management"
    
    # Check if exists
    existing_cs = await db["command_sets"].find_one({"tenant_id": tenant_id, "name": cs_name})
    
    if existing_cs:
        print(f"Command set '{cs_name}' already exists. ID: {existing_cs['_id']}")
        cs_id = str(existing_cs["_id"])
        
        # Clear existing commands for this set to re-seed cleanly
        await db["commands"].delete_many({"command_set_id": cs_id})
        print("Cleared old commands.")
        
    else:
        print(f"Creating command set '{cs_name}'...")
        result = await db["command_sets"].insert_one({
            "name": cs_name,
            "description": "Standard Membership Service operations (v2.4)",
            "tenant_id": tenant_id
        })
        cs_id = str(result.inserted_id)

    # 2. Add Commands
    mock_cmds = get_membership_commands()
    
    for cmd_data in mock_cmds:
        cmd_data["command_set_id"] = cs_id
        cmd_data["tenant_id"] = tenant_id
        await db["commands"].insert_one(cmd_data)
        print(f"Inserted command: {cmd_data['command']}")

    print("\nSeeding complete!")

if __name__ == "__main__":
    asyncio.run(seed())
