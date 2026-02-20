"""
LLM Provider Management API routes.
"""

from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any, Optional
import logging

from src.llm.config_loader import LLMConfig
from src.llm.async_capability_detector import AsyncCapabilityDetector
from .websocket import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"])

# Global provider manager instance (will be set during app startup)
_provider_manager = None

# Global notification service
notification_service = NotificationService()

# Global async capability detector
async_detector = None


def set_async_detector(detector):
    """Set the global async capability detector instance."""
    global async_detector
    async_detector = detector


def set_provider_manager(manager):
    """Set the global provider manager instance."""
    global _provider_manager
    _provider_manager = manager


async def get_provider_manager():
    """Dependency to get the provider manager."""
    if not _provider_manager:
        raise HTTPException(status_code=500, detail="Provider manager not initialized")
    return _provider_manager


@router.get("/providers")
async def list_providers(manager=Depends(get_provider_manager)):
    """Get list of all LLM providers."""
    try:
        providers = manager.get_providers()
        provider_list = [
            {
                **config.to_dict(),
                "is_current": name == manager.get_current_provider(),
                "is_initialized": name in manager.clients,
            }
            for name, config in providers.items()
        ]
        return {"providers": provider_list}
    except Exception as e:
        logger.error(f"Error listing providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers/{name}")
async def get_provider(name: str, manager=Depends(get_provider_manager)):
    """Get details of a specific provider."""
    try:
        info = manager.get_provider_info(name)
        if not info:
            raise HTTPException(status_code=404, detail=f"Provider {name} not found")
        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/providers")
async def create_provider(
    provider: Dict[str, Any],
    manager=Depends(get_provider_manager),
):
    """Create a new LLM provider or update if exists (upsert)."""
    try:
        name = provider.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="Provider name is required")

        # Check if provider already exists
        existing_providers = manager.get_providers()

        if name in existing_providers:
            # Provider exists - update it instead of creating
            logger.info(f"Provider {name} already exists, updating...")

            if manager.db_client:
                db = manager.db_client.nl_tps
                collection = db.llm_providers

                # Update existing provider
                result = await collection.update_one(
                    {"name": name},
                    {"$set": provider}
                )

                if result.matched_count == 0:
                    logger.warning(f"Provider {name} found in memory but not in database")

                # Reload providers
                manager.providers = await manager.config_loader.load_from_mongodb(manager.db_client)
                await manager.initialize(manager.db_client)
            else:
                raise HTTPException(status_code=500, detail="Database client not initialized")

            # Return the updated provider info
            provider_copy = {k: v for k, v in provider.items() if k != "_id"}
            return {"success": True, "provider": provider_copy, "action": "updated"}

        else:
            # Create new provider
            # Determine if manual or auto-detection mode
            capabilities_provided = "capabilities" in provider

            if not capabilities_provided:
                # Auto-detection mode: set safe defaults
                provider["capabilities"] = ["chat"]  # Default capability
                provider["capabilities_detection_status"] = "pending"
                provider["context_window"] = provider.get("context_window", 4096)
                provider["max_tokens"] = provider.get("max_tokens", 2048)
                provider["supports_multimodal"] = provider.get("supports_multimodal", False)
                provider["supported_formats"] = provider.get("supported_formats", [])
                provider["embedding_dimensions"] = provider.get("embedding_dimensions")
                provider["capabilities_last_updated"] = None

            if manager.db_client:
                db = manager.db_client.nl_tps
                collection = db.llm_providers
                await collection.insert_one(provider)

                # Reload providers
                manager.providers = await manager.config_loader.load_from_mongodb(manager.db_client)
                await manager.initialize(manager.db_client)

                # Start async detection if auto mode
                if not capabilities_provided and async_detector:
                    task_id = await async_detector.start_detection(name, provider)
                    logger.info(f"Started async capability detection: {task_id}")
            else:
                raise HTTPException(status_code=500, detail="Database client not initialized")

            # Return the created provider info without MongoDB's _id field
            provider_copy = {k: v for k, v in provider.items() if k != "_id"}

            response = {
                "success": True,
                "provider": provider_copy,
                "action": "created"
            }

            # Add detection status if auto mode
            if not capabilities_provided:
                response["capabilities_detection_status"] = provider.get("capabilities_detection_status", "pending")
                response["capabilities_mode"] = "auto"

            return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating/updating provider: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/providers/{name}")
async def update_provider(
    name: str,
    provider_data: Dict[str, Any],
    manager=Depends(get_provider_manager),
):
    """Update an existing LLM provider."""
    try:
        # Check if provider exists
        if name not in manager.get_providers():
            raise HTTPException(status_code=404, detail=f"Provider {name} not found")

        # Update in MongoDB
        if manager.db_client:
            db = manager.db_client.nl_tps
            collection = db.llm_providers
            result = await collection.update_one(
                {"name": name},
                {"$set": provider_data}
            )

            if result.matched_count == 0:
                raise HTTPException(status_code=404, detail=f"Provider {name} not found in database")

            # Reload providers
            manager.providers = await manager.config_loader.load_from_mongodb(manager.db_client)
            await manager.initialize(manager.db_client)
        else:
            raise HTTPException(status_code=500, detail="Database client not initialized")

        return {"success": True, "message": f"Provider {name} updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/providers/{name}")
async def delete_provider(
    name: str,
    manager=Depends(get_provider_manager),
):
    """Delete an LLM provider."""
    try:
        # Check if provider exists
        if name not in manager.get_providers():
            raise HTTPException(status_code=404, detail=f"Provider {name} not found")

        # Can't delete if it's the current provider
        if name == manager.get_current_provider():
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete the active provider '{name}'. Please select another provider first."
            )

        # Delete from MongoDB
        if manager.db_client:
            db = manager.db_client.nl_tps
            collection = db.llm_providers
            result = await collection.delete_one({"name": name})

            if result.deleted_count == 0:
                raise HTTPException(status_code=404, detail=f"Provider {name} not found in database")

            # Reload providers
            manager.providers = await manager.config_loader.load_from_mongodb(manager.db_client)
            await manager.initialize(manager.db_client)
        else:
            raise HTTPException(status_code=500, detail="Database client not initialized")

        return {"success": True, "message": f"Provider {name} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers/{name}/select")
async def select_provider(
    name: str,
    manager=Depends(get_provider_manager),
):
    """Select a provider as the current active provider."""
    try:
        if not manager.set_current_provider(name):
            raise HTTPException(
                status_code=400,
                detail=f"Failed to select provider {name}"
            )
        return {"success": True, "current_provider": name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error selecting provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/providers/{name}/test")
async def test_provider(
    name: str,
    test_data: Dict[str, str],
    manager=Depends(get_provider_manager),
):
    """Test a provider connection with a simple message."""
    try:
        message = test_data.get("message", "Hello, this is a test message.")

        result = await manager.complete(
            messages=[{"role": "user", "content": message}],
            provider=name,
        )

        if result is None:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get response from provider {name}"
            )

        return {
            "success": True,
            "provider": name,
            "message": result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/providers/{name}/retry-detection")
async def retry_provider_detection(
    name: str,
    manager=Depends(get_provider_manager),
):
    """
    Retry capability detection for a provider.

    Useful when previous detection failed or capabilities need to be refreshed.
    Restarts async detection task.
    """
    try:
        # Check if provider exists
        provider = manager.get_provider(name)
        if not provider:
            raise HTTPException(status_code=404, detail=f"Provider {name} not found")

        # Check if async detector is available
        if not async_detector:
            raise HTTPException(
                status_code=500,
                detail="Async capability detector not initialized"
            )

        # Start async detection
        provider_data = provider.to_dict()
        task_id = await async_detector.start_detection(name, provider_data)

        logger.info(f"Restarted capability detection for provider {name}: {task_id}")

        return {
            "success": True,
            "message": f"Capability detection restarted for provider {name}",
            "task_id": task_id,
            "provider": name
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying detection for provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers/{name}/costs")
async def get_provider_costs(
    name: str,
    manager=Depends(get_provider_manager),
):
    """Get cost information for a provider."""
    try:
        if name not in manager.get_providers():
            raise HTTPException(status_code=404, detail=f"Provider {name} not found")

        cost = manager.cost_tracker.get(name, 0.0)
        return {
            "provider": name,
            "cost_accumulated": cost,
            "cost_per_1k_tokens": manager.get_provider(name).cost_per_1k_tokens,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting costs for {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/providers/detect-capabilities")
async def detect_provider_capabilities(
    provider_data: Dict[str, Any],
    manager=Depends(get_provider_manager),
):
    """
    Manually detect capabilities for a provider configuration.

    Useful for previewing capabilities before creating a provider.
    Does not save the provider to the database.
    """
    try:
        from src.llm.capability_detector import CapabilityDetector

        # Validate required fields
        base_url = provider_data.get("base_url", "")
        model = provider_data.get("model", "")
        api_key_ref = provider_data.get("api_key_ref", "")
        auth_token = provider_data.get("auth_token")

        if not base_url or not model:
            raise HTTPException(
                status_code=400,
                detail="base_url and model are required"
            )

        # Get API key
        api_key = manager.config_loader.get_api_key(api_key_ref) if api_key_ref else auth_token
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="API key not found. Provide either api_key_ref or auth_token"
            )

        # Detect capabilities
        detector = CapabilityDetector(manager)
        detected = await detector.detect_capabilities(
            base_url=base_url,
            model=model,
            api_key=api_key,
            auth_token=None  # Already have the key
        )

        return {
            "success": True,
            "capabilities": detected,
            "provider_preview": {
                "name": provider_data.get("name", "preview"),
                "base_url": base_url,
                "model": model,
                "capabilities": detected.get("capabilities", ["chat"]),
                "context_window": detected.get("context_window", 4096),
                "max_tokens": detected.get("max_tokens", 2048),
                "supports_multimodal": detected.get("supports_multimodal", False),
                "supported_formats": detected.get("supported_formats", []),
                "embedding_dimensions": detected.get("embedding_dimensions"),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting capabilities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current")
async def get_current_provider(manager=Depends(get_provider_manager)):
    """Get the current active provider."""
    try:
        current = manager.get_current_provider()
        if not current:
            raise HTTPException(status_code=404, detail="No provider currently selected")

        info = manager.get_provider_info(current)
        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current provider: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/costs")
async def get_all_costs(manager=Depends(get_provider_manager)):
    """Get cost summary for all providers."""
    try:
        costs = manager.get_cost_summary()
        return {
            "costs": costs,
            "total_cost": sum(costs.values()),
        }
    except Exception as e:
        logger.error(f"Error getting costs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time notifications"""
    await notification_service.connect(websocket)

    try:
        while True:
            # Keep connection alive, handle ping/pong
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        notification_service.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        notification_service.disconnect(websocket)
