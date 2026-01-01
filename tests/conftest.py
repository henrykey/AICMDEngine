import pytest
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from src.main import app
from src.core.config import settings


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db():
    """Create a test database connection."""
    # Use a separate test database
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.database_name + "_test"]

    yield db

    # Cleanup: drop test database after tests
    await client.drop_database(settings.database_name + "_test")
    client.close()


@pytest.fixture
async def test_app(test_db):
    """Create a test application with test database."""
    app.mongodb = test_db
    return app


@pytest.fixture
def sample_command_set():
    """Sample command set data for testing."""
    return {
        "name": "test_user_management",
        "description": "Test command set for user management",
        "tenant_id": 1,
        "source_type": "manual",
        "version": "1.0.0"
    }


@pytest.fixture
def sample_commands():
    """Sample command data for testing."""
    return [
        {
            "command": "POST /users",
            "summary": "Create a new user",
            "description": "Creates a new user account",
            "tenant_id": 1,
            "command_set_id": "test_set_id",
            "parameters": {
                "body": {
                    "username": "string",
                    "email": "string",
                    "password": "string"
                }
            },
            "risk_level": "normal"
        },
        {
            "command": "GET /users/{id}",
            "summary": "Get user by ID",
            "description": "Retrieves a user by their ID",
            "tenant_id": 1,
            "command_set_id": "test_set_id",
            "parameters": {
                "path": {
                    "id": "user ID"
                }
            },
            "risk_level": "normal"
        },
        {
            "command": "DELETE /users/{id}",
            "summary": "Delete user",
            "description": "Deletes a user account",
            "tenant_id": 1,
            "command_set_id": "test_set_id",
            "parameters": {
                "path": {
                    "id": "user ID"
                }
            },
            "risk_level": "high"
        }
    ]


@pytest.fixture
async def populated_test_db(test_db, sample_command_set, sample_commands):
    """Create a test database with sample data."""
    # Insert command set
    cs_result = await test_db["command_sets"].insert_one(sample_command_set)
    command_set_id = str(cs_result.inserted_id)

    # Update commands with the actual command set ID
    for cmd in sample_commands:
        cmd["command_set_id"] = command_set_id

    # Insert commands
    await test_db["commands"].insert_many(sample_commands)

    return test_db, command_set_id
