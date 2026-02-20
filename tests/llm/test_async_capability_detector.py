"""Tests for async capability detector"""

import pytest
import asyncio
from src.llm.async_capability_detector import AsyncCapabilityDetector


class MockProviderManager:
    def __init__(self):
        self.db_client = None
        self.providers = {}
        self.config_loader = None

    async def reload_providers(self):
        pass


class MockNotificationService:
    def __init__(self):
        self.notifications = []

    async def notify_capability_update(self, provider_name, capabilities):
        self.notifications.append({
            "type": "capability_update",
            "provider": provider_name,
            "capabilities": capabilities
        })

    async def notify_detection_status(self, provider_name, status):
        self.notifications.append({
            "type": "status",
            "provider": provider_name,
            "status": status
        })


@pytest.mark.asyncio
async def test_start_detection():
    """Test starting async detection"""
    manager = MockProviderManager()
    notification = MockNotificationService()
    detector = AsyncCapabilityDetector(manager, notification)

    provider_data = {
        "name": "test-provider",
        "base_url": "https://api.test.com",
        "model": "gpt-4o",
        "api_key_ref": "TEST_KEY",
        "auth_token": "test-token"
    }

    task_id = await detector.start_detection("test-provider", provider_data)

    assert task_id.startswith("detect_test-provider_")
    # Wait a bit for background task to start
    await asyncio.sleep(0.1)
    # Check notification was sent
    assert len(notification.notifications) > 0


@pytest.mark.asyncio
async def test_update_status_without_db():
    """Test status update without database client"""
    manager = MockProviderManager()
    manager.db_client = None
    notification = MockNotificationService()
    detector = AsyncCapabilityDetector(manager, notification)

    # Should not raise error
    await detector._update_status("test", "detecting")


@pytest.mark.asyncio
async def test_update_capabilities_without_db():
    """Test capability update without database client"""
    manager = MockProviderManager()
    manager.db_client = None
    detector = AsyncCapabilityDetector(manager)

    # Should not raise error
    await detector._update_provider_capabilities("test", {"capabilities": ["chat"]})
