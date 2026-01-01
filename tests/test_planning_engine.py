import pytest
from src.services.planning_engine import PlanningEngine
from src.models.models import TaskRequest, TaskContext


class TestPlanningEngine:
    """Test PlanningEngine core functionality."""

    @pytest.mark.asyncio
    async def test_engine_creation(self, test_db):
        """Test that PlanningEngine can be instantiated."""
        engine = PlanningEngine(test_db)
        assert engine is not None
        assert engine.db == test_db

    @pytest.mark.asyncio
    async def test_get_available_commands_empty_db(self, test_db):
        """Test loading commands from empty database."""
        engine = PlanningEngine(test_db)

        commands = await engine.get_available_commands(tenant_id=1)

        assert commands == []
        assert isinstance(commands, list)

    @pytest.mark.asyncio
    async def test_get_available_commands_with_data(self, populated_test_db):
        """Test loading commands from populated database."""
        test_db, command_set_id = populated_test_db
        engine = PlanningEngine(test_db)

        commands = await engine.get_available_commands(tenant_id=1)

        assert len(commands) == 3
        assert commands[0]["command"] == "POST /users"
        assert commands[1]["command"] == "GET /users/{id}"
        assert commands[2]["command"] == "DELETE /users/{id}"

    @pytest.mark.asyncio
    async def test_get_available_commands_filter_by_tenant(self, populated_test_db):
        """Test that commands are filtered by tenant_id."""
        test_db, command_set_id = populated_test_db
        engine = PlanningEngine(test_db)

        # Query for tenant 1 (should return 3 commands)
        commands_tenant1 = await engine.get_available_commands(tenant_id=1)
        assert len(commands_tenant1) == 3

        # Query for tenant 2 (should return 0 commands)
        commands_tenant2 = await engine.get_available_commands(tenant_id=2)
        assert len(commands_tenant2) == 0

    @pytest.mark.asyncio
    async def test_get_available_commands_with_command_set_names(self, populated_test_db, sample_command_set):
        """Test filtering by command set names."""
        test_db, command_set_id = populated_test_db
        engine = PlanningEngine(test_db)

        # Filter by command set name
        commands = await engine.get_available_commands(
            tenant_id=1,
            command_set_names=["test_user_management"]
        )

        assert len(commands) == 3

    @pytest.mark.asyncio
    async def test_get_available_commands_limit(self, test_db, sample_command_set):
        """Test that command query is limited (performance test)."""
        # Insert many commands
        command_set_id = (await test_db["command_sets"].insert_one(sample_command_set)).inserted_id

        many_commands = []
        for i in range(1500):  # More than the limit of 1000
            many_commands.append({
                "command": f"GET /test/{i}",
                "summary": f"Test command {i}",
                "description": "Test",
                "tenant_id": 1,
                "command_set_id": str(command_set_id),
                "parameters": {},
                "risk_level": "normal"
            })

        await test_db["commands"].insert_many(many_commands)

        engine = PlanningEngine(test_db)
        commands = await engine.get_available_commands(tenant_id=1)

        # Should return at most 1000 commands (the limit)
        assert len(commands) <= 1000

    @pytest.mark.asyncio
    async def test_plan_task_no_commands(self, test_db):
        """Test planning with no available commands."""
        engine = PlanningEngine(test_db)

        request = TaskRequest(
            goal="Create a user",
            context=TaskContext(
                tenant_id=1,
                command_set_names=["non_existent"]
            )
        )

        response = await engine.plan_task(request, tenant_id=1)

        assert response.type == "clarification_needed"
        assert response.confidence == 0.0
        assert "No available commands" in response.question

    @pytest.mark.asyncio
    async def test_plan_task_with_commands(self, populated_test_db):
        """Test planning with available commands."""
        test_db, command_set_id = populated_test_db
        engine = PlanningEngine(test_db)

        request = TaskRequest(
            goal="Create a new user account",
            context=TaskContext(
                tenant_id=1,
                command_set_names=["test_user_management"]
            )
        )

        # Note: This test will make an actual LLM call
        # In a real test environment, you'd mock the LLM client
        # For now, we'll skip this test or mark it as integration test
        pytest.skip("Requires LLM mocking - mark as integration test")

    @pytest.mark.asyncio
    async def test_build_prompt_structure(self, populated_test_db):
        """Test that prompt is built correctly."""
        test_db, command_set_id = populated_test_db
        engine = PlanningEngine(test_db)

        commands = await engine.get_available_commands(tenant_id=1)

        prompt = engine._build_prompt(
            user_goal="Create a user",
            commands=commands,
            tenant_id=1,
            conversation_history=None
        )

        assert isinstance(prompt, list)
        assert len(prompt) >= 2  # At least system and user message
        assert prompt[0]["role"] == "system"
        assert "Current User's Tenant ID: 1" in prompt[0]["content"]

    def test_build_prompt_includes_tenant_id(self):
        """Test that tenant_id is included in prompt."""
        engine = PlanningEngine(None)

        prompt = engine._build_prompt(
            user_goal="Test",
            commands=[],
            tenant_id=123,
            conversation_history=None
        )

        system_content = prompt[0]["content"]
        assert "123" in system_content
        assert "Current User's Tenant ID: 123" in system_content
