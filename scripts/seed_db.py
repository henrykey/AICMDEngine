import asyncio
import json
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "nl_tps")
TENANT_ID = "tenant-dev-001"

async def seed():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]

    # Clean up
    await db["command_sets"].delete_many({"tenant_id": TENANT_ID})
    await db["commands"].delete_many({"tenant_id": TENANT_ID})
    
    print(f"Cleaned up tenant {TENANT_ID}")

    # Create Set
    cs_res = await db["command_sets"].insert_one({
        "name": "membership-v2",
        "description": "Core membership management API (Seeded)",
        "tenant_id": TENANT_ID,
        "source_type": "manual",
        "version": "1.0.0"
    })
    cs_id = cs_res.inserted_id
    print(f"Created Command Set: {cs_id}")

    # Load Commands
    with open("seed_commands.json", "r") as f:
        cmds = json.load(f)

    for cmd in cmds:
        cmd["command_set_id"] = str(cs_id)
        cmd["tenant_id"] = TENANT_ID
        cmd["riskLevel"] = "normal"
        await db["commands"].insert_one(cmd)
    
    print(f"Inserted {len(cmds)} commands.")
    client.close()

if __name__ == "__main__":
    asyncio.run(seed())
