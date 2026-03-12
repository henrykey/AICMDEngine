"""
Add capability detection status fields to existing LLM providers in MongoDB.
Run this migration script to update existing provider records.
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from motor.motor_async_core import AsyncIOMotorClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def upgrade():
    """Add capability fields to existing providers"""
    # Connect to MongoDB
    mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    database_name = os.getenv("DATABASE_NAME", "nl_tps")
    client = AsyncIOMotorClient(mongo_uri)
    db = client[database_name]
    collection = db.llm_providers

    try:
        # Count existing providers
        total = await collection.count_documents({})
        logger.info(f"Found {total} existing providers")

        # Add new fields to all existing providers
        result = await collection.update_many(
            {},  # Empty filter = all documents
            {
                "$set": {
                    "capabilities_detection_status": "completed",
                    "capabilities": ["chat"],  # Default assumption
                    "context_window": 4096,
                    "max_tokens": 2048,
                    "supports_multimodal": False,
                    "supported_formats": [],
                    "embedding_dimensions": None
                }
            }
        )

        logger.info(f"Migration complete: Updated {result.modified_count} providers")
        logger.info("Added capability fields to all existing providers")

        # Show sample of updated providers
        sample = await collection.find_one({})
        if sample:
            logger.info(f"Sample provider after migration: {sample.get('name')}")
            logger.info(f"  - capabilities: {sample.get('capabilities')}")
            logger.info(f"  - detection_status: {sample.get('capabilities_detection_status')}")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(upgrade())
