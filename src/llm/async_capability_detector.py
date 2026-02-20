"""
Async background capability detection service.
Runs detection in background without blocking provider creation.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
from .capability_detector import CapabilityDetector

logger = logging.getLogger(__name__)


class AsyncCapabilityDetector:
    """Async background capability detection"""

    def __init__(self, provider_manager, notification_service=None):
        self.provider_manager = provider_manager
        self.notification = notification_service
        self.active_tasks = {}

    async def start_detection(
        self,
        provider_name: str,
        provider_data: Dict[str, Any]
    ) -> str:
        """Start async detection task"""
        task_id = f"detect_{provider_name}_{datetime.now().timestamp()}"

        # Create background task
        task = asyncio.create_task(
            self._detect_and_update(provider_name, provider_data)
        )

        self.active_tasks[task_id] = task
        logger.info(f"Started async detection: {task_id}")
        return task_id

    async def _detect_and_update(self, provider_name: str, provider_data: Dict[str, Any]):
        """Background detection task"""

        # Update status: detecting
        await self._update_status(provider_name, "detecting")

        try:
            # Detect capabilities
            detector = CapabilityDetector(self.provider_manager)
            detected = await detector.detect_capabilities(
                provider_data.get("base_url", ""),
                provider_data.get("model", ""),
                provider_data.get("api_key_ref", ""),
                provider_data.get("auth_token")
            )

            # Update provider config (including status to completed)
            await self._update_provider_capabilities(provider_name, detected)

            # Update status: completed
            await self._update_status(provider_name, "completed")

            # Notify frontend
            if self.notification:
                await self.notification.notify_capability_update(
                    provider_name,
                    detected
                )

            logger.info(f"Detection completed: {provider_name}")

        except Exception as e:
            logger.error(f"Detection failed: {provider_name}: {e}")
            await self._update_status(
                provider_name,
                "failed",
                error=str(e)
            )

    async def _update_status(self, provider_name: str, status: str, error: str = None):
        """Update detection status in DB"""
        if not self.provider_manager.db_client:
            logger.warning("No database client, skipping status update")
            return

        db = self.provider_manager.db_client.nl_tps
        collection = db.llm_providers

        update_data = {
            "capabilities_detection_status": status,
            "capabilities_last_updated": datetime.utcnow()
        }

        if error:
            update_data["capabilities_detection_error"] = error

        await collection.update_one(
            {"name": provider_name},
            {"$set": update_data}
        )

        # Notify frontend
        if self.notification:
            await self.notification.notify_detection_status(provider_name, status)

    async def _update_provider_capabilities(self, provider_name: str, capabilities: Dict[str, Any]):
        """Update provider with detected capabilities"""
        if not self.provider_manager.db_client:
            logger.warning("No database client, skipping capability update")
            return

        db = self.provider_manager.db_client.nl_tps
        collection = db.llm_providers

        update_data = {
            "capabilities": capabilities.get("capabilities", ["chat"]),
            "context_window": capabilities.get("context_window", 4096),
            "max_tokens": capabilities.get("max_tokens", 2048),
            "supports_multimodal": capabilities.get("supports_multimodal", False),
            "supported_formats": capabilities.get("supported_formats", []),
            "embedding_dimensions": capabilities.get("embedding_dimensions")
        }

        await collection.update_one(
            {"name": provider_name},
            {"$set": update_data}
        )

        # Note: Don't reload providers here to avoid race conditions
        # The reload will happen when _update_status is called next
