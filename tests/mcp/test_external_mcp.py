"""
Tests for External MCP Server Adapter
"""

import pytest
import asyncio
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
