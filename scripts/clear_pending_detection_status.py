#!/usr/bin/env python
"""
Clear incorrect pending status from existing providers.

Manual Mode Providers (should NOT have pending status):
1. Old existing configurations (created before auto-detection feature)
2. New providers created with Manual mode (user manually selected capabilities)

Auto-Detection Mode Providers (should have detection status):
1. New providers created with Auto-detect mode
2. Status flow: pending → detecting → completed/failed

This script clears incorrect 'pending' status from manual mode providers.
"""

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()


async def clear_pending_status():
    """Clear pending status from providers that already have capabilities"""

    mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
    database_name = os.getenv('DATABASE_NAME', 'nl_tps')
    client = AsyncIOMotorClient(mongo_uri)
    db = client[database_name]
    collection = db.llm_providers

    # Find all providers with pending status
    pending_providers = await collection.find({
        'capabilities_detection_status': 'pending'
    }).to_list(None)

    if not pending_providers:
        print('No providers with pending status found.')
        await client.close()
        return

    print(f'Found {len(pending_providers)} providers with pending status:\n')

    for provider in pending_providers:
        name = provider.get('name')
        capabilities = provider.get('capabilities', [])

        print(f'Provider: {name}')
        print(f'  Capabilities: {capabilities}')

        # Clear pending status for manual configurations
        # These providers were manually configured, not auto-detected
        await collection.update_one(
            {'_id': provider['_id']},
            {'$unset': {
                'capabilities_detection_status': '',
                'capabilities_detection_error': '',
                'capabilities_last_updated': '',
                'capabilities_mode': ''
            }}
        )

        print(f'  ✓ Cleared pending status (manual configuration)')
        print()

    print('✓ All pending statuses cleared!')
    print('\nUpdated providers:')
    print('  - Will now show "Manual" badge')
    print('  - Will display their configured capabilities')
    print('  - Can still use "Detect" button to run auto-detection')

    await client.close()


if __name__ == '__main__':
    print('=' * 60)
    print('Clear Pending Detection Status')
    print('=' * 60)
    print()

    asyncio.run(clear_pending_status())
