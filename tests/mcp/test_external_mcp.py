"""
Tests for External MCP Server Adapter
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch
import json

from src.mcp.external_mcp import ExternalMCPServer
from src.mcp.result import ToolResult


class TestExternalMCPServer:
    """测试外部MCP服务器适配器"""

    @pytest.fixture
    def sample_tools_response(self):
        """示例工具列表响应"""
        return {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a file",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "File path"
                                }
                            },
                            "required": ["path"]
                        }
                    },
                    {
                        "name": "write_file",
                        "description": "Write to a file",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "File path"
                                },
                                "content": {
                                    "type": "string",
                                    "description": "File content"
                                }
                            },
                            "required": ["path", "content"]
                        }
                    }
                ]
            }
        }

    @pytest.fixture
    def sample_tool_call_response(self):
        """示例工具调用响应"""
        return {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": "Hello, World!"
                    }
                ],
                "isError": False
            }
        }

    def test_init(self):
        """测试初始化"""
        mcp = ExternalMCPServer(
            name="test_mcp",
            command="node",
            args=["test.js"],
            transport="stdio",
            timeout=30
        )

        assert mcp.name == "test_mcp"
        assert mcp.command == "node"
        assert mcp.args == ["test.js"]
        assert mcp.transport == "stdio"
        assert mcp.timeout == 30
        assert mcp.process is None
        assert len(mcp.tools) == 0

    @pytest.mark.asyncio
    async def test_next_request_id(self):
        """测试请求ID生成"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )

        id1 = mcp._next_request_id()
        id2 = mcp._next_request_id()
        id3 = mcp._next_request_id()

        assert id1 == 1
        assert id2 == 2
        assert id3 == 3

    @pytest.mark.asyncio
    async def test_register_external_tool(self):
        """测试外部工具注册"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )

        tool_def = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string"}
                }
            }
        }

        await mcp._register_external_tool(tool_def)

        # 验证工具已注册
        assert "test_tool" in mcp.tools
        assert mcp.tools["test_tool"].name == "test_tool"
        assert mcp.tools["test_tool"].description == "Test tool"

        # 验证工具已缓存
        assert "test_tool" in mcp.tools_cache

    @pytest.mark.asyncio
    async def test_execute_external_tool_success(self, sample_tool_call_response):
        """测试成功执行外部工具"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )

        # Mock _send_request
        with patch.object(
            mcp,
            '_send_request',
            new=AsyncMock(return_value=sample_tool_call_response)
        ):
            result = await mcp._execute_external_tool(
                "test_tool",
                {"param1": "value"}
            )

            # 验证结果
            assert isinstance(result, ToolResult)
            assert not result.is_error
            assert "Hello, World!" in result.content

    @pytest.mark.asyncio
    async def test_execute_external_tool_embedded_json_error_is_promoted(self):
        """测试文本内容中的JSON错误对象会被提升为ToolResult.error"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )

        embedded_error_response = {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "task_id": "task_123",
                            "page_no": 7,
                            "error": "VLM token quota exhausted"
                        })
                    }
                ],
                "isError": False
            }
        }

        with patch.object(
            mcp,
            '_send_request',
            new=AsyncMock(return_value=embedded_error_response)
        ):
            result = await mcp._execute_external_tool(
                "process_task_page",
                {"task_id": "task_123", "page_no": 7}
            )

            assert isinstance(result, ToolResult)
            assert result.is_error
            assert "token quota exhausted" in result.content

    def test_build_tool_result_logs_model_engine_summary(self, caplog):
        """测试外部工具JSON结果会记录实际模型/引擎摘要"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )
        result_payload = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "tool": "extract_page_tables",
                            "model_calls": {"glm_ocr": 0, "vlm_ocr": 1},
                            "items": [{"source": "vlm_ocr"}],
                        }
                    ),
                }
            ],
            "isError": False,
        }

        with caplog.at_level("INFO", logger="src.mcp.external_mcp"):
            result = mcp._build_tool_result_from_response_result("extract_page_tables", result_payload)

        assert not result.is_error
        assert "Tool 'extract_page_tables' engine summary" in caplog.text
        assert "engine=vlm_ocr" in caplog.text
        assert "model_calls={'glm_ocr': 0, 'vlm_ocr': 1}" in caplog.text

    def test_build_tool_result_logs_revise_vlm_summary(self, caplog):
        """测试revise_page_markdown返回的vlm调试信息会进入日志"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )
        result_payload = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "pageText": "修订后正文",
                            "vlm": {
                                "enabled": True,
                                "provider": "multmode",
                                "model": "qwen-vl",
                                "base_url": "http://llm",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            "isError": False,
        }

        with caplog.at_level("INFO", logger="src.mcp.external_mcp"):
            result = mcp._build_tool_result_from_response_result("revise_page_markdown", result_payload)

        assert not result.is_error
        assert "Tool 'revise_page_markdown' engine summary" in caplog.text
        assert "engine=vlm_ocr" in caplog.text
        assert "'provider': 'multmode'" in caplog.text

    @pytest.mark.asyncio
    async def test_execute_external_tool_error(self):
        """测试外部工具返回错误"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )

        error_response = {
            "jsonrpc": "2.0",
            "id": 3,
            "error": {
                "code": -32601,
                "message": "Method not found"
            }
        }

        with patch.object(
            mcp,
            '_send_request',
            new=AsyncMock(return_value=error_response)
        ):
            result = await mcp._execute_external_tool(
                "unknown_tool",
                {}
            )

            # 验证错误结果
            assert isinstance(result, ToolResult)
            assert result.is_error
            assert "Method not found" in result.content

    @pytest.mark.asyncio
    async def test_execute_external_tool_timeout(self):
        """测试外部工具超时"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo",
            timeout=1
        )

        with patch.object(
            mcp,
            '_send_request',
            new=AsyncMock(side_effect=asyncio.TimeoutError())
        ):
            result = await mcp._execute_external_tool(
                "slow_tool",
                {}
            )

            # 验证超时错误
            assert result.is_error
            assert "timed out" in result.content.lower()

    @pytest.mark.asyncio
    async def test_get_info(self):
        """测试获取MCP信息"""
        mcp = ExternalMCPServer(
            name="test_mcp",
            command="node",
            args=["test.js"],
            transport="stdio"
        )

        info = mcp.get_info()

        assert info["name"] == "test_mcp"
        assert info["version"] == "1.0"
        assert info["transport"] == "stdio"
        assert info["command"] == "node"
        assert info["args"] == ["test.js"]
        assert info["is_running"] == False  # Process not started

    @pytest.mark.asyncio
    async def test_close_without_process(self):
        """测试关闭未启动的MCP"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )

        # 不应该抛出异常
        await mcp.close()

        assert mcp.process is None

    def test_handle_message_response(self):
        """测试处理响应消息"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )

        # 创建一个Future
        future = asyncio.Future()
        mcp.pending_requests[1] = future

        # 响应消息
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        }

        # 处理消息
        asyncio.run(mcp._handle_message(message))

        # 验证Future已完成
        assert future.done()
        assert future.result() == message

        # 验证已从pending中移除
        assert 1 not in mcp.pending_requests

    def test_handle_message_notification(self):
        """测试处理通知消息"""
        mcp = ExternalMCPServer(
            name="test",
            command="echo"
        )

        # 通知消息（没有id）
        message = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"reason": "test"}
        }

        # 不应该抛出异常
        asyncio.run(mcp._handle_message(message))

    @pytest.mark.asyncio
    async def test_disconnect_reconnects_and_restores_tools(self):
        mcp = ExternalMCPServer(
            name="recovering",
            url="ws://recovering.example/mcp",
            transport="websocket",
        )
        mcp.is_initialized = True
        mcp._reconnect_enabled = True
        attempts = 0

        async def reconnect_once():
            nonlocal attempts
            attempts += 1
            await mcp._replace_discovered_tools([
                {
                    "name": "restored_tool",
                    "description": "restored",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ])

        mcp._connect_transport = reconnect_once
        mcp._reconnect_base_delay = 0
        mcp._reconnect_max_delay = 0

        class ClosedWebSocket:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        mcp.websocket = ClosedWebSocket()
        await mcp._read_websocket_messages_loop()
        await mcp._reconnect_task

        assert attempts == 1
        assert mcp.is_initialized is True
        assert set(mcp.tools) == {"restored_tool"}
        await mcp.close()

    @pytest.mark.asyncio
    async def test_reconnect_failures_back_off_and_do_not_duplicate_task(self):
        mcp = ExternalMCPServer(
            name="recovering",
            url="ws://recovering.example/mcp",
            transport="websocket",
        )
        attempts = 0
        delays = []

        async def flaky_connect():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("still offline")

        async def record_sleep(delay):
            delays.append(delay)

        mcp._connect_transport = flaky_connect
        mcp._sleep = record_sleep
        mcp._reconnect_enabled = True
        mcp._reconnect_base_delay = 1
        mcp._reconnect_max_delay = 2

        mcp.schedule_reconnect()
        reconnect_task = mcp._reconnect_task
        mcp.schedule_reconnect()

        assert mcp._reconnect_task is reconnect_task
        await reconnect_task
        assert attempts == 3
        assert delays == [1, 2, 2]
        assert mcp.is_initialized is True
        await mcp.close()

    @pytest.mark.asyncio
    async def test_reconnect_failures_are_quiet_until_one_recovery_log(self, caplog):
        mcp = ExternalMCPServer(
            name="recovering",
            url="ws://recovering.example/mcp",
            transport="websocket",
        )
        attempts = 0

        async def flaky_connect():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                mcp._log_connection_attempt_failure(
                    "error", "transport unavailable for %s", mcp.name
                )
                raise ConnectionError("still offline")

        async def no_wait(_delay):
            return None

        mcp._connect_transport = flaky_connect
        mcp._sleep = no_wait
        mcp._reconnect_enabled = True
        mcp._reconnect_base_delay = 0
        mcp._reconnect_max_delay = 0

        with caplog.at_level(logging.INFO, logger="src.mcp.external_mcp"):
            mcp.schedule_reconnect()
            await mcp._reconnect_task

        messages = [record.getMessage() for record in caplog.records]
        assert not any("transport unavailable" in message for message in messages)
        assert messages.count("Reconnected external MCP 'recovering'") == 1
        await mcp.close()

    @pytest.mark.asyncio
    async def test_health_check_failure_is_quiet_before_reconnect(self, caplog):
        mcp = ExternalMCPServer(name="recovering", command="echo")
        mcp.is_initialized = True
        mcp._reconnect_enabled = True
        mcp._health_interval = 0

        async def unavailable_tools():
            raise ConnectionError("server stopped")

        mcp._discover_tools = unavailable_tools
        mcp.schedule_reconnect = Mock()

        with caplog.at_level(logging.INFO, logger="src.mcp.external_mcp"):
            await mcp._health_check_loop()

        assert not any("health check failed" in record.getMessage() for record in caplog.records)
        mcp.schedule_reconnect.assert_called_once()
        await mcp.close()

    @pytest.mark.asyncio
    async def test_tool_refresh_replaces_registration_without_duplicates(self):
        mcp = ExternalMCPServer(name="test", command="echo")
        await mcp._replace_discovered_tools([
            {"name": "old", "description": "old", "inputSchema": {}},
        ])

        await mcp._replace_discovered_tools([
            {"name": "new", "description": "new", "inputSchema": {}},
            {"name": "new", "description": "newer", "inputSchema": {}},
        ])

        assert set(mcp.tools) == {"new"}
        assert set(mcp.tools_cache) == {"new"}
        assert mcp.tools["new"].description == "newer"


class TestExternalMCPIntegration:
    """集成测试 - 需要真实的外部MCP进程"""

    @pytest.mark.skipif(
        True,  # 默认跳过，需要真实MCP
        reason="Requires real external MCP server"
    )
    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """测试完整的生命周期"""
        # 使用echo命令作为简单的测试
        mcp = ExternalMCPServer(
            name="echo_test",
            command="echo"
        )

        try:
            # 初始化（会失败，因为echo不是真正的MCP）
            await mcp.initialize()
        except Exception:
            pass  # 预期会失败
        finally:
            await mcp.close()
