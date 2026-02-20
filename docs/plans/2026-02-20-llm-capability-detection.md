# MCP Router LLM Capability Detection and Selection

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable MCP Router tools to automatically select appropriate LLM providers based on required capabilities (chat, embedding, vision, OCR, code, reasoning) with auto-discovery and manual configuration options.

**Architecture:**
- **Capability-Based Routing**: Tools declare required LLM capabilities, router matches with provider capabilities
- **Three-Tier Discovery**: Predefined model registry → name-based inference → LLM self-description query
- **Async Background Detection**: Providers created immediately with safe defaults, capability detection runs in background
- **WebSocket Notifications**: Real-time updates when capabilities are detected/updated

**Tech Stack:**
- FastAPI, Python 3.10+
- MongoDB (provider config storage)
- WebSockets (real-time notifications)
- httpx (async HTTP for LLM queries)
- Pydantic (data validation)

---

## Task 1: Add capabilities fields to LLMConfig model

**Files:**
- Modify: `src/llm/config_loader.py`

**Step 1: Add capability fields to LLMConfig dataclass**

Add these new fields to the `LLMConfig` class:
```python
capabilities: List[str]  # e.g., ["chat", "vision", "ocr"]
context_window: int = 4096
max_tokens: int = 2048
supports_multimodal: bool = False
supported_formats: List[str] = []  # for vision/ocr: ["png", "jpg"]
embedding_dimensions: Optional[int] = None  # for embedding models
```

**Step 2: Update from_dict factory method**

Modify `from_dict` to handle new fields with defaults:
```python
@classmethod
def from_dict(cls, data: dict) -> "LLMConfig":
    return cls(
        # ... existing fields ...
        capabilities=data.get("capabilities", ["chat"]),
        context_window=data.get("context_window", 4096),
        max_tokens=data.get("max_tokens", 2048),
        supports_multimodal=data.get("supports_multimodal", False),
        supported_formats=data.get("supported_formats", []),
        embedding_dimensions=data.get("embedding_dimensions")
    )
```

**Step 3: Run existing tests**

Run: `python -m pytest tests/ -k "test_config" -v`
Expected: All existing tests pass

**Step 4: Commit**

```bash
git add src/llm/config_loader.py
git commit -m "feat(llm): add capability fields to LLMConfig model"
```

---

## Task 2: Create predefined model capabilities registry

**Files:**
- Create: `src/llm/model_capabilities.py`

**Step 1: Create predefined capabilities mapping**

```python
"""Predefined capabilities for known LLM models"""

PREDEFINED_MODEL_CAPABILITIES = {
    # OpenAI
    "gpt-4o": {
        "capabilities": ["chat", "vision", "ocr", "code", "reasoning", "function_calling"],
        "context_window": 128000,
        "max_tokens": 4096,
        "supports_multimodal": True
    },
    "gpt-4o-mini": {
        "capabilities": ["chat", "vision", "code", "function_calling"],
        "context_window": 128000,
        "max_tokens": 16384,
        "supports_multimodal": True
    },
    "text-embedding-3-small": {
        "capabilities": ["embedding"],
        "embedding_dimensions": 1536
    },
    "text-embedding-3-large": {
        "capabilities": ["embedding"],
        "embedding_dimensions": 3072
    },
    "o1-preview": {
        "capabilities": ["chat", "reasoning", "code"],
        "context_window": 128000,
        "reasoning_model": True
    },
    "o1-mini": {
        "capabilities": ["chat", "reasoning", "code"],
        "context_window": 128000,
        "reasoning_model": True
    },

    # Anthropic
    "claude-3-5-sonnet-20241022": {
        "capabilities": ["chat", "vision", "code", "reasoning", "function_calling"],
        "context_window": 200000,
        "max_tokens": 8192
    },
    "claude-3-5-haiku-20241022": {
        "capabilities": ["chat", "vision", "code"],
        "context_window": 200000,
        "max_tokens": 8192
    },

    # DeepSeek
    "deepseek-chat": {
        "capabilities": ["chat", "code", "reasoning"],
        "context_window": 64000,
        "max_tokens": 4096
    },
    "deepseek-coder": {
        "capabilities": ["chat", "code"],
        "context_window": 64000,
        "max_tokens": 4096
    },

    # Qwen
    "qwen-vl-max": {
        "capabilities": ["chat", "vision", "ocr"],
        "context_window": 32000,
        "max_tokens": 8192
    },
}

def get_predefined_capabilities(model_name: str) -> Optional[dict]:
    """Get predefined capabilities for a model"""
    if model_name in PREDEFINED_MODEL_CAPABILITIES:
        return PREDEFINED_MODEL_CAPABILITIES[model_name].copy()

    # Try fuzzy match for versioned models
    base_name = model_name.split("-")[0]
    for key, caps in PREDEFINED_MODEL_CAPABILITIES.items():
        if key.startswith(base_name):
            result = caps.copy()
            result["_matched_pattern"] = key
            return result

    return None
```

**Step 2: Write unit tests**

Create: `tests/llm/test_model_capabilities.py`

```python
def test_get_predefined_capabilities_exact_match():
    caps = get_predefined_capabilities("gpt-4o")
    assert caps is not None
    assert "chat" in caps["capabilities"]
    assert "vision" in caps["capabilities"]

def test_get_predefined_capabilities_fuzzy_match():
    caps = get_predefined_capabilities("gpt-4o-20240808")
    assert caps is not None
    assert "_matched_pattern" in caps

def test_get_predefined_capabilities_not_found():
    caps = get_predefined_capabilities("unknown-model")
    assert caps is None
```

**Step 3: Run tests**

Run: `python -m pytest tests/llm/test_model_capabilities.py -v`
Expected: All 3 tests pass

**Step 4: Commit**

```bash
git add src/llm/model_capabilities.py tests/llm/test_model_capabilities.py
git commit -m "feat(llm): add predefined model capabilities registry"
```

---

## Task 3: Implement CapabilityDetector with inference

**Files:**
- Create: `src/llm/capability_detector.py`

**Step 1: Create CapabilityDetector class**

```python
import logging
from typing import Optional
from .model_capabilities import get_predefined_capabilities

logger = logging.getLogger(__name__)

class CapabilityDetector:
    """Auto-detect LLM model capabilities"""

    def __init__(self, provider_manager):
        self.provider_manager = provider_manager

    async def detect_capabilities(
        self,
        base_url: str,
        model: str,
        api_key_ref: str,
        auth_token: str
    ) -> dict:
        """
        Detect model capabilities through multi-tier strategy:
        1. Predefined registry (high confidence)
        2. Name-based inference (medium confidence)
        3. LLM self-description query (high confidence)
        """
        logger.info(f"Detecting capabilities for model: {model}")

        # Tier 1: Predefined
        predefined = get_predefined_capabilities(model)
        if predefined:
            predefined["detection_method"] = "predefined"
            predefined["confidence"] = "high"
            logger.info(f"Found predefined config for {model}")
            return predefined

        # Tier 2: Name inference
        inferred = self._infer_from_name(model)
        if inferred:
            inferred["detection_method"] = "name_inference"
            inferred["confidence"] = "medium"
            logger.info(f"Inferred capabilities for {model}")
            return inferred

        # Tier 3: Ask LLM
        discovered = await self._ask_llm_self_description(
            base_url, model, auth_token
        )
        if discovered:
            discovered["detection_method"] = "llm_query"
            discovered["confidence"] = "high"
            return discovered

        # Fallback: Default
        return self._get_default_capabilities()

    def _infer_from_name(self, model: str) -> Optional[dict]:
        """Infer capabilities from model name"""
        name_lower = model.lower()
        capabilities = []

        if "embedding" in name_lower:
            return {
                "capabilities": ["embedding"],
                "embedding_dimensions": 1536,
                "confidence": "high"
            }

        if any(x in name_lower for x in ["vision", "vl-", "multimodal", "4o"]):
            capabilities.extend(["vision", "ocr"])

        if "coder" in name_lower:
            capabilities.append("code")

        if "o1" in name_lower or "reasoning" in name_lower:
            capabilities.append("reasoning")

        capabilities.append("chat")  # Almost all models can chat

        return {
            "capabilities": list(set(capabilities)),
            "context_window": 4096,
            "max_tokens": 2048
        } if capabilities else None

    async def _ask_llm_self_description(
        self,
        base_url: str,
        model: str,
        auth_token: str
    ) -> Optional[dict]:
        """Query LLM to describe its own capabilities"""
        # Will be implemented in Task 5
        pass

    def _get_default_capabilities(self) -> dict:
        """Safe default capabilities"""
        return {
            "capabilities": ["chat"],
            "context_window": 4096,
            "max_tokens": 2048,
            "detection_method": "default",
            "confidence": "low",
            "warning": "Could not auto-detect. Using safe defaults."
        }
```

**Step 2: Write basic tests**

Create: `tests/llm/test_capability_detector.py`

```python
import pytest
from src.llm.capability_detector import CapabilityDetector

@pytest.mark.asyncio
async def test_detect_predefined_model():
    detector = CapabilityDetector(mock_provider_manager)
    result = await detector.detect_capabilities(
        "https://api.openai.com/v1",
        "gpt-4o",
        "OPENAI_API_KEY",
        "sk-test"
    )
    assert result["detection_method"] == "predefined"
    assert "chat" in result["capabilities"]

def test_infer_from_name():
    detector = CapabilityDetector(None)
    result = detector._infer_from_name("text-embedding-3-small")
    assert result["capabilities"] == ["embedding"]
```

**Step 3: Run tests**

Run: `python -m pytest tests/llm/test_capability_detector.py -v`
Expected: Tests pass

**Step 4: Commit**

```bash
git add src/llm/capability_detector.py tests/llm/test_capability_detector.py
git commit -m "feat(llm): add capability detector with inference"
```

---

## Task 4: Implement LLM self-description query

**Files:**
- Modify: `src/llm/capability_detector.py`

**Step 1: Add httpx import**

```python
import httpx
import json
import logging
```

**Step 2: Implement _ask_llm_self_description method**

```python
async def _ask_llm_self_description(
    self,
    base_url: str,
    model: str,
    auth_token: str
) -> Optional[dict]:
    """Query LLM to describe its capabilities"""
    prompt = '''Please describe your capabilities in JSON format:
{
  "model_name": "your exact model name",
  "capabilities": ["chat", "embedding", "vision", "ocr", "code", "reasoning", "multimodal", "function_calling"],
  "context_window": max tokens (integer),
  "max_tokens": max output tokens (integer),
  "supports_multimodal": true/false,
  "supported_formats": ["png", "jpg", "webp"] (if applicable),
  "embedding_dimensions": integer (if embedding model)
}

Only include capabilities you ACTUALLY have. Return valid JSON only.'''

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a helpful AI assistant. Answer with JSON only."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0,
                    "max_tokens": 500
                }
            )

            if response.status_code != 200:
                logger.error(f"LLM query failed: {response.status_code}")
                return None

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Parse JSON response
            parsed = json.loads(content)

            # Validate and return
            return {
                "capabilities": parsed.get("capabilities", ["chat"]),
                "context_window": parsed.get("context_window", 4096),
                "max_tokens": parsed.get("max_tokens", 2048),
                "supports_multimodal": parsed.get("supports_multimodal", False),
                "supported_formats": parsed.get("supported_formats", []),
                "embedding_dimensions": parsed.get("embedding_dimensions")
            }

    except Exception as e:
        logger.error(f"Error querying LLM: {e}")
        return None
```

**Step 3: Write integration test**

Add to `tests/llm/test_capability_detector.py`:

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_llm_self_description():
    # Requires real API key - skip in CI
    detector = CapabilityDetector(None)
    result = await detector._ask_llm_self_description(
        "https://api.openai.com/v1",
        "gpt-4o-mini",
        os.getenv("OPENAI_API_KEY")
    )
    assert result is not None
    assert "chat" in result["capabilities"]
```

**Step 4: Commit**

```bash
git add src/llm/capability_detector.py tests/llm/test_capability_detector.py
git commit -m "feat(llm): implement LLM self-description query"
```

---

## Task 5: Add capability detection status fields to MongoDB schema

**Files:**
- Modify: `src/llm/config_loader.py` (LLMConfig class)
- Create: `src/llm/migrations/add_capability_fields.py`

**Step 1: Add status fields to LLMConfig**

```python
# In LLMConfig class, add:
capabilities_detection_status: str = "pending"  # pending, detecting, completed, failed
capabilities_last_updated: Optional[datetime] = None
capabilities_detection_error: Optional[str] = None
```

**Step 2: Create migration script**

```python
"""Add capability detection status fields to existing providers"""

async def upgrade():
    db = client.nl_tps
    collection = db.llm_providers

    # Add new fields to all existing providers
    await collection.update_many(
        {},  # Empty filter = all documents
        {
            "$set": {
                "capabilities_detection_status": "completed",
                "capabilities": ["chat"],  # Default assumption
                "context_window": 4096,
                "max_tokens": 2048
            }
        }
    )

    print("Migration complete: Added capability fields")
```

**Step 3: Test migration**

Run: `python src/llm/migrations/add_capability_fields.py`
Expected: "Migration complete"

**Step 4: Commit**

```bash
git add src/llm/config_loader.py src/llm/migrations/add_capability_fields.py
git commit -m "feat(llm): add capability detection status fields"
```

---

## Task 6: Implement async capability detection service

**Files:**
- Create: `src/llm/async_capability_detector.py`

**Step 1: Create AsyncCapabilityDetector class**

```python
import asyncio
import logging
from datetime import datetime
from .capability_detector import CapabilityDetector

logger = logging.getLogger(__name__)

class AsyncCapabilityDetector:
    """Async background capability detection"""

    def __init__(self, provider_manager, notification_service):
        self.provider_manager = provider_manager
        self.notification = notification_service
        self.active_tasks = {}

    async def start_detection(
        self,
        provider_name: str,
        provider_data: dict
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

    async def _detect_and_update(self, provider_name: str, provider_data: dict):
        """Background detection task"""

        # Update status: detecting
        await self._update_status(provider_name, "detecting")

        try:
            # Detect capabilities
            detector = CapabilityDetector(self.provider_manager)
            detected = await detector.detect_capabilities(
                provider_data["base_url"],
                provider_data["model"],
                provider_data["api_key_ref"],
                provider_data.get("auth_token")
            )

            # Update provider config
            await self._update_provider_capabilities(provider_name, detected)

            # Update status: completed
            await self._update_status(provider_name, "completed")

            # Notify frontend
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
        db = self.provider_manager.db_client
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
        await self.notification.notify_detection_status(provider_name, status)

    async def _update_provider_capabilities(self, provider_name: str, capabilities: dict):
        """Update provider with detected capabilities"""
        db = self.provider_manager.db_client
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

        # Reload providers in manager
        self.provider_manager.providers = await self.provider_manager.config_loader.load_from_mongodb(
            self.provider_manager.db_client
        )
```

**Step 2: Write unit tests**

Create: `tests/llm/test_async_capability_detector.py`

```python
@pytest.mark.asyncio
async def test_start_detection():
    detector = AsyncCapabilityDetector(mock_manager, mock_notification)
    task_id = await detector.start_detection("test-provider", test_data)
    assert task_id.startswith("detect_test-provider_")
```

**Step 3: Run tests**

Run: `python -m pytest tests/llm/test_async_capability_detector.py -v`
Expected: Tests pass

**Step 4: Commit**

```bash
git add src/llm/async_capability_detector.py tests/llm/test_async_capability_detector.py
git commit -m "feat(llm): add async capability detection service"
```

---

## Task 7: Create WebSocket notification service

**Files:**
- Create: `src/routers/websocket.py`

**Step 1: Create WebSocket manager**

```python
from fastapi import WebSocket
from typing import List
import logging

logger = logging.getLogger(__name__)

class NotificationService:
    """WebSocket notification service"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept and track WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove disconnected WebSocket"""
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def notify_detection_status(self, provider_name: str, status: str):
        """Broadcast detection status change"""
        message = {
            "type": "capability_detection_status",
            "provider_name": provider_name,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._broadcast(message)

    async def notify_capability_update(self, provider_name: str, capabilities: dict):
        """Broadcast capability update"""
        message = {
            "type": "capability_update",
            "provider_name": provider_name,
            "capabilities": capabilities,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._broadcast(message)

    async def _broadcast(self, message: dict):
        """Broadcast to all connected clients"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")
                disconnected.append(connection)

        # Cleanup disconnected
        for conn in disconnected:
            self.active_connections.remove(conn)
```

**Step 2: Add WebSocket endpoint to router**

Modify: `src/routers/llm.py`

```python
from .websocket import NotificationService

# Global notification service
notification_service = NotificationService()

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
```

**Step 3: Write WebSocket tests**

Create: `tests/routers/test_websocket.py`

```python
from fastapi.testclient import TestClient
import pytest

def test_websocket_connection():
    client = TestClient(app)
    with client.websocket_connect("/ws/notifications") as websocket:
        websocket.send_json({"type": "ping"})
        data = websocket.receive_json()
        assert data["type"] == "pong"
```

**Step 4: Commit**

```bash
git add src/routers/websocket.py src/routers/llm.py tests/routers/test_websocket.py
git commit -m "feat(routing): add WebSocket notification service"
```

---

## Task 8: Update POST /providers endpoint to support async detection

**Files:**
- Modify: `src/routers/llm.py`

**Step 1: Modify create_provider endpoint**

```python
@router.post("/providers")
async def create_provider(
    provider: Dict[str, Any],
    manager=Depends(get_provider_manager),
):
    """
    Create LLM provider with optional async capability detection

    If 'capabilities' field is present: Manual configuration
    If missing: Auto-detect in background
    """
    try:
        name = provider.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="Provider name is required")

        # Check for manual or auto mode
        has_manual_capabilities = "capabilities" in provider

        if not has_manual_capabilities:
            # Set default capabilities for immediate use
            provider["capabilities"] = ["chat"]
            provider["context_window"] = 4096
            provider["max_tokens"] = 2048
            provider["capabilities_detection_status"] = "pending"
        else:
            # Manual configuration
            provider["capabilities_detection_status"] = "completed"
            provider["capabilities_last_updated"] = datetime.utcnow()

        # Save to MongoDB
        if manager.db_client:
            db = manager.db_client.nl_tps
            collection = db.llm_providers
            await collection.insert_one(provider)

            # Reload providers
            manager.providers = await manager.config_loader.load_from_mongodb(manager.db_client)
            await manager.initialize(manager.db_client)

        # Start async detection if not manual
        if not has_manual_capabilities:
            from .async_capability_detector import AsyncCapabilityDetector
            detector = AsyncCapabilityDetector(manager, notification_service)
            await detector.start_detection(name, provider)
            logger.info(f"Started async detection for provider: {name}")

        # Return response
        provider_copy = {k: v for k, v in provider.items() if k != "_id"}

        return {
            "success": True,
            "provider": provider_copy,
            "message": "Provider created successfully" + (
                "" if has_manual_capabilities else
                ". Capability detection running in background..."
            ),
            "detection_status": provider.get("capabilities_detection_status")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating provider: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Step 2: Test with curl**

```bash
# Test manual configuration
curl -X POST "http://localhost:8000/api/llm/providers" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-manual",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o",
    "api_key_ref": "OPENAI_API_KEY",
    "capabilities": ["chat", "code"],
    "priority": 1
  }'

# Test auto-detection
curl -X POST "http://localhost:8000/api/llm/providers" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-auto",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o",
    "api_key_ref": "OPENAI_API_KEY",
    "priority": 2
  }'
```

Expected: Both succeed, second starts background detection

**Step 3: Commit**

```bash
git add src/routers/llm.py
git commit -m "feat(llm): support async capability detection in provider creation"
```

---

## Task 9: Implement capability-based provider selection

**Files:**
- Modify: `src/llm/provider_manager.py`

**Step 1: Add select_provider_by_capabilities method**

```python
def select_provider_by_capabilities(
    self,
    required_capabilities: List[str],
    preferred_dimensions: Optional[int] = None,
    min_context_window: Optional[int] = None
) -> Optional[str]:
    """
    Select best provider matching required capabilities

    Selection priority:
    1. Must have ALL required capabilities
    2. Sort by: priority (asc) -> context_window (desc) -> cost (asc)
    3. Return first match
    """
    providers = self.get_providers()

    # Filter by capabilities
    candidates = []
    for name, config in providers.items():
        if not config.enabled:
            continue

        # Check if provider has all required capabilities
        provider_caps = config.capabilities or []
        if not all(cap in provider_caps for cap in required_capabilities):
            continue

        # Check embedding dimensions if specified
        if preferred_dimensions and config.embedding_dimensions != preferred_dimensions:
            continue

        # Check context window if specified
        if min_context_window and (config.context_window or 0) < min_context_window:
            continue

        candidates.append((name, config))

    if not candidates:
        return None

    # Sort by priority -> context window -> cost
    candidates.sort(key=lambda x: (
        x[1].priority,
        -(x[1].context_window or 4096),
        x[1].cost_per_1k_tokens or 0
    ))

    return candidates[0][0]  # Return provider name
```

**Step 2: Write tests**

Create: `tests/llm/test_provider_selection.py`

```python
def test_select_by_capabilities():
    # Setup mock providers
    manager.providers = {
        "embedding-model": LLMConfig(
            name="embedding-model",
            capabilities=["embedding"],
            embedding_dimensions=1536,
            priority=2
        ),
        "chat-model": LLMConfig(
            name="chat-model",
            capabilities=["chat"],
            priority=1
        )
    }

    # Select embedding provider
    selected = manager.select_provider_by_capabilities(["embedding"])
    assert selected == "embedding-model"

    # Select chat provider
    selected = manager.select_provider_by_capabilities(["chat"])
    assert selected == "chat-model"

    # No match for vision
    selected = manager.select_provider_by_capabilities(["vision"])
    assert selected is None
```

**Step 3: Run tests**

Run: `python -m pytest tests/llm/test_provider_selection.py -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/llm/provider_manager.py tests/llm/test_provider_selection.py
git commit -m "feat(llm): add capability-based provider selection"
```

---

## Task 10: Add GET /providers/detect-capabilities endpoint

**Files:**
- Modify: `src/routers/llm.py`

**Step 1: Add detection endpoint**

```python
@router.post("/providers/detect-capabilities")
async def detect_provider_capabilities(
    request: Dict[str, Any],
    manager=Depends(get_provider_manager)
):
    """
    Manually trigger capability detection for a provider config

    Useful for:
    - Previewing capabilities before creating provider
    - Re-detecting after failed detection
    """
    try:
        base_url = request.get("base_url")
        model = request.get("model")
        api_key_ref = request.get("api_key_ref")
        auth_token = request.get("auth_token")

        if not all([base_url, model, api_key_ref]):
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: base_url, model, api_key_ref"
            )

        # Get API key if not provided
        if not auth_token:
            import os
            auth_token = os.getenv(api_key_ref)
            if not auth_token:
                raise HTTPException(
                    status_code=400,
                    detail=f"API key not found in environment: {api_key_ref}"
                )

        # Detect capabilities
        from .capability_detector import CapabilityDetector
        detector = CapabilityDetector(manager)
        capabilities = await detector.detect_capabilities(
            base_url, model, api_key_ref, auth_token
        )

        return {
            "success": True,
            "model": model,
            "detected_capabilities": capabilities,
            "message": f"Capabilities detected via: {capabilities.get('detection_method', 'unknown')}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting capabilities: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Step 2: Test with curl**

```bash
curl -X POST "http://localhost:8000/api/llm/providers/detect-capabilities" \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o",
    "api_key_ref": "OPENAI_API_KEY"
  }'
```

Expected: Returns detected capabilities

**Step 3: Commit**

```bash
git add src/routers/llm.py
git commit -m "feat(llm): add manual capability detection endpoint"
```

---

## Task 11: Add retry detection endpoint

**Files:**
- Modify: `src/routers/llm.py`

**Step 1: Add retry endpoint**

```python
@router.post("/providers/{name}/retry-detection")
async def retry_capability_detection(
    name: str,
    manager=Depends(get_provider_manager)
):
    """Retry capability detection for a provider"""
    try:
        provider = manager.get_provider(name)
        if not provider:
            raise HTTPException(status_code=404, detail=f"Provider {name} not found")

        # Start async detection
        from .async_capability_detector import AsyncCapabilityDetector
        detector = AsyncCapabilityDetector(manager, notification_service)
        await detector.start_detection(name, provider.to_dict())

        return {
            "success": True,
            "message": f"Capability detection restarted for {name}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying detection: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Step 2: Commit**

```bash
git add src/routers/llm.py
git commit -m "feat(llm): add retry capability detection endpoint"
```

---

## Task 12: Update GET /providers to include capability status

**Files:**
- Modify: `src/routers/llm.py`

**Step 1: Modify list_providers to return capability info**

```python
@router.get("/providers")
async def list_providers(manager=Depends(get_provider_manager)):
    """Get list of all LLM providers with capability info"""
    try:
        providers = manager.get_providers()
        provider_list = []

        for name, config in providers.items():
            provider_dict = config.to_dict()
            provider_dict.update({
                "is_current": name == manager.get_current_provider(),
                "is_initialized": name in manager.clients,
                "detection_status": config.capabilities_detection_status,
                "capabilities_last_updated": config.capabilities_last_updated,
                "detection_error": config.capabilities_detection_error
            })
            provider_list.append(provider_dict)

        return {"providers": provider_list}

    except Exception as e:
        logger.error(f"Error listing providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Step 2: Test API response**

```bash
curl -X GET "http://localhost:8000/api/llm/providers"
```

Expected: Returns providers with detection_status field

**Step 3: Commit**

```bash
git add src/routers/llm.py
git commit -m "feat(llm): include capability detection status in provider list"
```

---

## Task 13: Frontend - Add capability badges to provider list

**Files:**
- Modify: `plan2/src/components/LLMProviderManagement.tsx`

**Step 1: Add capability badges component**

```typescript
interface ProviderCardProps {
  provider: Provider;
  detectionStatus: string;
}

function ProviderCard({ provider, detectionStatus }: ProviderCardProps) {
  const getStatusBadge = () => {
    switch (detectionStatus) {
      case "pending":
        return <span className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded">
          ⏳ Pending
        </span>;
      case "detecting":
        return <span className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded animate-pulse">
          🔍 Detecting...
        </span>;
      case "completed":
        return <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded">
          ✓ Auto-detected
        </span>;
      case "failed":
        return <span className="px-2 py-1 bg-red-100 text-red-700 text-xs rounded">
          ✗ Failed
        </span>;
      default:
        return <span className="px-2 py-1 bg-purple-100 text-purple-700 text-xs rounded">
          Manual
        </span>;
    }
  };

  return (
    <div className="border p-4 rounded">
      <div className="flex justify-between items-start mb-2">
        <h3 className="font-semibold">{provider.name}</h3>
        {getStatusBadge()}
      </div>

      {/* Capabilities */}
      <div className="flex flex-wrap gap-1 mb-3">
        {provider.capabilities.map(cap => (
          <span key={cap} className="px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded border border-blue-200">
            {cap}
          </span>
        ))}
      </div>

      {/* Metadata */}
      <div className="text-xs text-gray-600 space-y-1">
        <div>Context: {provider.context_window?.toLocaleString()}</div>
        <div>Max Tokens: {provider.max_tokens?.toLocaleString()}</div>
        {provider.embedding_dimensions && (
          <div>Embedding: {provider.embedding_dimensions}d</div>
        )}
      </div>

      {/* Retry button if failed */}
      {detectionStatus === "failed" && (
        <button
          onClick={() => retryDetection(provider.name)}
          className="mt-2 px-3 py-1 bg-red-500 text-white text-xs rounded hover:bg-red-600"
        >
          Retry Detection
        </button>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
cd plan2
git add src/components/LLMProviderManagement.tsx
git commit -m "feat(ui): add capability badges and detection status indicators"
```

---

## Task 14: Frontend - Add WebSocket notification handler

**Files:**
- Modify: `plan2/src/components/LLMProviderManagement.tsx`

**Step 1: Add WebSocket connection and message handler**

```typescript
useEffect(() => {
  const ws = new WebSocket("ws://localhost:8000/ws/notifications");

  ws.onopen = () => {
    console.log("WebSocket connected");
    // Send ping every 30s to keep alive
    const pingInterval = setInterval(() => {
      ws.send("ping");
    }, 30000);

    return () => clearInterval(pingInterval);
  };

  ws.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      handleWebSocketMessage(message);
    } catch (e) {
      console.error("Failed to parse WebSocket message:", e);
    }
  };

  ws.onerror = (error) => {
    console.error("WebSocket error:", error);
  };

  ws.onclose = () => {
    console.log("WebSocket disconnected, reconnecting in 5s...");
    setTimeout(() => {
      // Reconnection logic would go here
    }, 5000);
  };

  return () => ws.close();
}, []);

const handleWebSocketMessage = (message: any) => {
  switch (message.type) {
    case "capability_detection_status":
      handleDetectionStatusChange(message);
      break;

    case "capability_update":
      handleCapabilityUpdate(message);
      break;

    case "pong":
      // Ignore pong
      break;
  }
};

const handleDetectionStatusChange = (message: any) => {
  const { provider_name, status } = message;

  // Update provider in list
  setProviders(prev => prev.map(p =>
    p.name === provider_name
      ? { ...p, capabilities_detection_status: status }
      : p
  ));

  // Show notification
  switch (status) {
    case "detecting":
      toast.info(`🔍 Detecting capabilities for ${provider_name}...`);
      break;
    case "completed":
      toast.success(`✓ Capabilities detected for ${provider_name}`);
      // Refresh provider list to get updated capabilities
      fetchProviders();
      break;
    case "failed":
      toast.error(`✗ Capability detection failed for ${provider_name}`);
      break;
  }
};

const handleCapabilityUpdate = (message: any) => {
  const { provider_name, capabilities } = message;

  // Refresh provider list
  fetchProviders();

  // Show detailed notification
  toast.success(
    `✓ ${provider_name} updated: ${capabilities.capabilities.join(", ")}`,
    { duration: 5000 }
  );
};
```

**Step 2: Test WebSocket connection**

Open browser console, should see:
```
WebSocket connected
```

**Step 3: Commit**

```bash
cd plan2
git add src/components/LLMProviderManagement.tsx
git commit -m "feat(ui): add WebSocket notification handler for capability updates"
```

---

## Task 15: Add GET /providers/{name} endpoint with capability details

**Files:**
- Modify: `src/routers/llm.py`

**Step 1: Enhance get_provider endpoint**

```python
@router.get("/providers/{name}")
async def get_provider(name: str, manager=Depends(get_provider_manager)):
    """Get detailed provider info including capabilities"""
    try:
        provider = manager.get_provider(name)
        if not provider:
            raise HTTPException(status_code=404, detail=f"Provider {name} not found")

        # Convert to dict
        provider_dict = provider.to_dict()
        provider_dict.update({
            "is_current": name == manager.get_current_provider(),
            "is_initialized": name in manager.clients,
            "detection_status": provider.capabilities_detection_status,
            "capabilities_last_updated": provider.capabilities_last_updated,
            "detection_error": provider.capabilities_detection_error
        })

        return provider_dict

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Step 2: Test endpoint**

```bash
curl -X GET "http://localhost:8000/api/llm/providers/gpt-4o"
```

Expected: Returns full provider config including capabilities

**Step 3: Commit**

```bash
git add src/routers/llm.py
git commit -m "feat(llm): enhance provider detail endpoint with capability info"
```

---

## Task 16: Add integration test for full detection flow

**Files:**
- Create: `tests/integration/test_capability_detection_flow.py`

**Step 1: Create end-to-end test**

```python
import pytest
import asyncio
from httpx import AsyncClient

@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_capability_detection_flow():
    """Test complete async detection flow"""

    # Create provider with auto-detection
    async with AsyncClient() as client:
        # Step 1: Create provider
        response = await client.post(
            "http://localhost:8000/api/llm/providers",
            json={
                "name": "test-detection-flow",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "api_key_ref": "OPENAI_API_KEY",
                "priority": 10
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["detection_status"] == "pending"

        provider_name = data["provider"]["name"]

        # Step 2: Wait for async detection (max 30s)
        for _ in range(30):
            await asyncio.sleep(1)

            response = await client.get(
                f"http://localhost:8000/api/llm/providers/{provider_name}"
            )

            provider_data = response.json()
            status = provider_data.get("detection_status")

            if status == "completed":
                assert "chat" in provider_data.get("capabilities", [])
                break

            if status == "failed":
                pytest.fail("Detection failed")

        else:
            pytest.fail("Detection timeout")
```

**Step 2: Run integration test**

Run: `python -m pytest tests/integration/test_capability_detection_flow.py -v -s`
Expected: Test passes within 30 seconds

**Step 3: Commit**

```bash
git add tests/integration/test_capability_detection_flow.py
git commit -m "test(llm): add integration test for capability detection flow"
```

---

## Task 17: Write documentation

**Files:**
- Create: `docs/LLM_CAPABILITY_DETECTION.md`

**Step 1: Create comprehensive documentation**

```markdown
# LLM Capability Detection and Selection

## Overview

The MCP Router now supports automatic LLM capability detection and intelligent provider selection based on tool requirements.

## Features

### 1. Capability-Based Routing

MCP tools can declare required LLM capabilities:
```json
{
  "name": "membership.embed_document",
  "llm_requirements": {
    "capabilities": ["embedding"],
    "preferred_dimensions": 1536
  }
}
```

### 2. Auto-Detection

Three-tier detection strategy:
1. **Predefined Registry**: Known models (GPT-4o, Claude, etc.)
2. **Name Inference**: Guess from model name (e.g., "text-embedding-3-small" → embedding)
3. **LLM Self-Description**: Query the model itself

### 3. Async Background Detection

Providers created immediately with safe defaults, detection runs in background with WebSocket notifications.

## Configuration

### Manual Configuration

```json
{
  "name": "my-gpt4o",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "api_key_ref": "OPENAI_API_KEY",
  "capabilities": ["chat", "vision", "code"],
  "priority": 1
}
```

### Auto-Detection

```json
{
  "name": "my-gpt4o",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "api_key_ref": "OPENAI_API_KEY"
  // capabilities auto-detected
}
```

## API Endpoints

### POST /api/llm/providers
Create provider (async detection by default)

### POST /api/llm/providers/detect-capabilities
Manual trigger capability detection

### POST /api/llm/providers/{name}/retry-detection
Retry failed detection

### GET /api/llm/providers
List all providers with capability info

### WebSocket /ws/notifications
Real-time capability update notifications

## Standard Capabilities

- `chat`: Conversational AI
- `embedding`: Text vectorization
- `vision`: Image understanding
- `ocr`: Text extraction from images
- `code`: Code generation/understanding
- `reasoning`: Complex reasoning
- `multimodal`: Multi-modal inputs
- `function_calling`: Tool/function use

## Usage Example

```python
# Provider Manager selects appropriate LLM for tool
provider_name = manager.select_provider_by_capabilities(
    required_capabilities=["embedding"],
    preferred_dimensions=1536
)

# Returns: "text-embedding-3-small"
```

## WebSocket Events

### capability_detection_status
```json
{
  "type": "capability_detection_status",
  "provider_name": "gpt-4o",
  "status": "detecting",
  "timestamp": "2026-02-20T12:00:00Z"
}
```

### capability_update
```json
{
  "type": "capability_update",
  "provider_name": "gpt-4o",
  "capabilities": {...},
  "timestamp": "2026-02-20T12:00:05Z"
}
```
```

**Step 2: Commit documentation**

```bash
git add docs/LLM_CAPABILITY_DETECTION.md
git commit -m "docs: add LLM capability detection documentation"
```

---

## Task 18: Final end-to-end testing

**Files:**
- Create: `tests/e2e/test_full_flow.py`

**Step 1: Create comprehensive E2E test**

```python
import pytest
from httpx import AsyncClient

@pytest.mark.e2e
async def test_complete_capability_workflow():
    """End-to-end test of capability detection and selection"""

    async with AsyncClient() as client:
        # 1. Create provider with auto-detection
        response = await client.post(
            "http://localhost:8000/api/llm/providers",
            json={
                "name": "e2e-test-provider",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "api_key_ref": "OPENAI_API_KEY",
                "priority": 99
            }
        )
        assert response.status_code == 200

        # 2. Wait for detection
        provider_name = response.json()["provider"]["name"]
        # ... wait for completed status ...

        # 3. Verify capabilities detected
        response = await client.get(f"http://localhost:8000/api/llm/providers/{provider_name}")
        provider = response.json()
        assert "chat" in provider["capabilities"]

        # 4. Test provider selection
        response = await client.post(
            "http://localhost:8000/api/llm/test",
            json={
                "message": "Hello, world!",
                "provider": provider_name
            }
        )
        assert response.status_code == 200
```

**Step 2: Run E2E test**

Run: `python -m pytest tests/e2e/test_full_flow.py -v -s`
Expected: Full workflow succeeds

**Step 3: Final commit**

```bash
git add tests/e2e/test_full_flow.py
git commit -m "test(llm): add end-to-end capability detection test"
```

---

## Implementation Notes

### Key Design Decisions

1. **Async-First**: Detection runs in background, doesn't block provider creation
2. **Safe Defaults**: Provider immediately usable with `["chat"]` capability
3. **Manual Override**: Users can specify capabilities to skip auto-detection
4. **Progressive Enhancement**: Detection tiers (predefined → inference → query)
5. **Real-Time Updates**: WebSocket keeps UI in sync

### Testing Strategy

- Unit tests per component
- Integration tests for detection flow
- E2E tests for full workflow
- Mock external LLM APIs in tests

### Migration Path

- Existing providers: Migration script adds default capabilities
- New providers: Auto-detect by default
- Manual config: Explicit capabilities respected

---

## Next Steps After Implementation

1. Deploy to staging environment
2. Test with real LLM providers
3. Monitor detection accuracy
4. Expand predefined model registry
5. Add more capability types as needed
6. Performance testing with many providers
