# Phase 1 执行启动清单

**状态**: 🚀 准备启动
**开始日期**: 2026-01-10 (预计)
**目标完成**: 2026-01-14 (3-4工作日)
**关键里程碑**: Membership API → MCP + LLM Provider Management

---

## 📋 前置准备 (Pre-Execution - 需要立即完成)

### 1. 最终决策确认

**必须确认的待决项**：

- [ ] **第二个API选择** (Phase 2)
  - 选项: Orders API / Billing API / 其他
  - 决定: _________

- [ ] **监控级别** (Phase 1)
  - 选项: 基础指标 / 完整分布式追踪
  - 决定: _________

- [ ] **MCP部署模式** (Phase 1)
  - 选项: 进程内 / 独立服务
  - 决定: _________

- [ ] **项目负责人** (整个项目)
  - 分配给: _________

### 2. 团队分工确认

```
Role                          | 负责人      | 联系方式
------------------------------|-----------|----------
Phase 1 Lead                  | _________ | _________
Backend Developer (MCP)       | _________ | _________
LLM Integration Developer     | _________ | _________
Integration Tester           | _________ | _________
DevOps/Monitoring            | _________ | _________
```

### 3. 环境准备

- [ ] MongoDB 连接信息
  - Host: _________
  - Port: _________
  - Database: _________
  - Auth: _________

- [ ] MinIO 连接信息
  - Host: _________
  - Port: _________
  - Access Key: _________
  - Secret Key: _________

- [ ] Flowable (如需使用)
  - Host: _________
  - Version: _________

- [ ] LLM API密钥
  - OPENAI_API_KEY: ✓ (需在.env中)
  - DEEPSEEK_API_KEY: _________ (可选)

---

## 🏗️ Phase 1 实施任务分解

### **Day 1: MCP Framework 基础 (1.5天)**

#### Task 1.1: MCP框架设计和实现 (0.5天)
- [ ] 创建目录结构
  ```
  src/
  ├── mcp/
  │   ├── __init__.py
  │   ├── base_server.py          # BaseMCPServer类
  │   ├── registry.py             # MCPRegistry
  │   ├── tool.py                 # Tool定义
  │   └── result.py               # ToolResult定义
  ├── mcp_servers/
  │   ├── __init__.py
  │   ├── membership_mcp.py        # Membership MCP Server
  │   └── __init__.py
  └── llm/
      ├── __init__.py
      ├── provider_manager.py      # LLMProviderManager
      └── config_loader.py         # LLMConfigLoader
  ```

- [ ] 实现 BaseMCPServer 基类
  - [ ] 继承接口
  - [ ] 工具注册机制
  - [ ] 执行方法

- [ ] 实现 MCPRegistry
  - [ ] MCP注册
  - [ ] MCP查询
  - [ ] MCP执行路由

- [ ] 实现 Tool 和 ToolResult 数据结构
  - [ ] Tool定义（名称、描述、参数模式、处理器）
  - [ ] ToolResult定义（成功/失败、内容、数据）

**验收标准**:
- [ ] 可以注册一个简单的测试MCP
- [ ] 可以通过registry调用已注册的工具

---

#### Task 1.2: Membership MCP 实现 (1天)
- [ ] 实现 MembershipMCPServer
  - [ ] 从MongoDB加载API规范
  - [ ] 从MinIO加载文档
  - [ ] 内存缓存（TTL 5分钟）

- [ ] 实现所有Membership API命令为MCP工具
  - [ ] GET /v2/members (list_members)
  - [ ] GET /v2/members/{id} (get_member)
  - [ ] POST /v2/members (create_member)
  - [ ] PUT /v2/members/{id} (update_member)
  - [ ] DELETE /v2/members/{id} (delete_member)
  - [ ] GET /v2/roles (list_roles)
  - [ ] 其他必要端点

- [ ] 实现错误处理
  - [ ] JSONPath提取
  - [ ] 错误分类（可重试vs永久性）
  - [ ] 重试逻辑（指数退避）

- [ ] 集成HTTP客户端
  - [ ] Bearer token认证
  - [ ] 超时处理
  - [ ] 响应解析

**验收标准**:
- [ ] 所有Membership API命令都可作为MCP工具调用
- [ ] 错误处理完整（包括超时、auth失败、解析错误）
- [ ] 响应时间 < 1s (不包括网络延迟)

---

### **Day 2: LLM Provider Management (1天)**

#### Task 2.1: MongoDB配置管理 (0.5天)
- [ ] 创建MongoDB集合和索引
  ```javascript
  db.createCollection("llm_providers")
  db.llm_providers.createIndex({name: 1}, {unique: true})
  db.llm_providers.createIndex({enabled: 1})
  ```

- [ ] 实现 LLMConfigLoader
  - [ ] MongoDB加载逻辑
  - [ ] YAML加载逻辑 (开发用)
  - [ ] .env变量注入
  - [ ] 提供商缓存

- [ ] 初始化default提供商配置
  - [ ] OpenAI (GPT-5)
  - [ ] DeepSeek v3.2
  - [ ] 可选：Qwen, Kimi, GLM, Local

**验收标准**:
- [ ] 可以从MongoDB读取提供商配置
- [ ] 可以从YAML读取配置
- [ ] API密钥从.env正确注入

---

#### Task 2.2: LLM Provider Manager 实现 (0.5天)
- [ ] 实现 LLMProviderManager
  - [ ] 提供商选择逻辑
  - [ ] OpenAI兼容API调用
  - [ ] 成本追踪
  - [ ] Fallback策略

- [ ] 实现FastAPI路由
  - [ ] GET /api/llm/providers (列表)
  - [ ] POST /api/llm/providers (创建)
  - [ ] PUT /api/llm/providers/{name} (更新)
  - [ ] DELETE /api/llm/providers/{name} (删除)
  - [ ] POST /api/llm/providers/{name}/test (测试连接)
  - [ ] GET /api/llm/providers/{name}/select (选择)

- [ ] 实现React前端组件
  - [ ] 提供商卡片列表
  - [ ] 新建/编辑表单
  - [ ] 测试连接按钮
  - [ ] 选择提供商按钮

**验收标准**:
- [ ] Web UI可以看到所有提供商
- [ ] 可以添加新提供商
- [ ] 可以测试提供商连接
- [ ] 可以选择当前使用的提供商

---

### **Day 3-4: 集成与测试 (1.5-2天)**

#### Task 3.1: 与Planning Engine集成 (0.5天)
- [ ] 更新Planning Engine系统提示
  - [ ] 包含所有Membership MCP命令
  - [ ] 描述每个命令的参数和返回值

- [ ] 实现MCP命令执行
  - [ ] Planning Engine识别MCP命令
  - [ ] 路由到正确的MCP
  - [ ] 执行并返回结果

- [ ] 实现multi-step工作流
  - [ ] Step 1 执行，提取响应数据
  - [ ] Step 2 使用Step 1的数据
  - [ ] JSONPath提取验证

**验收标准**:
- [ ] Planning Engine可以调用Membership MCP
- [ ] Multi-step任务可以工作
- [ ] 数据正确从Step 1流向Step 2

---

#### Task 3.2: 集成测试 (1天)
- [ ] 单元测试
  - [ ] BaseMCPServer 测试
  - [ ] MembershipMCPServer 各命令测试
  - [ ] LLMConfigLoader 测试
  - [ ] LLMProviderManager 测试

- [ ] 集成测试
  ```python
  # 示例：完整的请求流程
  1. Planning Engine接收任务: "获取member ID 123的信息"
  2. LLM规划步骤
  3. 执行: mcp.membership.get_member(id=123)
  4. Membership MCP 调用API
  5. 返回结果给Planning Engine
  ```

- [ ] 性能测试
  - [ ] Membership MCP: 平均响应时间
  - [ ] 与原始HTTP客户端对比
  - [ ] 目标: < 10% 变慢

**验收标准**:
- [ ] 所有单元测试通过
- [ ] 集成测试通过（完整的任务流程）
- [ ] 性能符合目标

---

#### Task 3.3: 文档和验收 (0.5天)
- [ ] 创建开发者文档
  - [ ] MCP框架使用说明
  - [ ] 如何创建新MCP
  - [ ] API文档

- [ ] 用户验收测试
  - [ ] 业务功能验证
  - [ ] 用户场景测试
  - [ ] 反馈收集

- [ ] 更新README和文档
  - [ ] 更新PROGRESS.md标记Phase 1完成
  - [ ] 创建Phase 1总结
  - [ ] 列出Phase 2的前置条件

**验收标准**:
- [ ] 文档清晰完整
- [ ] 用户验收通过
- [ ] 可交付物完成

---

## 🔧 关键代码结构

### MCP框架核心类

```python
# src/mcp/base_server.py

class Tool:
    def __init__(self, name: str, description: str,
                 input_schema: dict, handler: callable):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

class ToolResult:
    def __init__(self, is_error: bool, content: str,
                 data: dict = None, error_code: str = None):
        self.is_error = is_error
        self.content = content
        self.data = data or {}
        self.error_code = error_code

class BaseMCPServer:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version
        self.tools: Dict[str, Tool] = {}

    def register_tool(self, tool: Tool):
        self.tools[tool.name] = tool

    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        if tool_name not in self.tools:
            return ToolResult(
                is_error=True,
                content=f"Tool '{tool_name}' not found",
                error_code="TOOL_NOT_FOUND"
            )

        tool = self.tools[tool_name]
        return await tool.handler(**kwargs)

    def get_tools(self) -> List[Tool]:
        return list(self.tools.values())

# src/mcp/registry.py

class MCPRegistry:
    def __init__(self):
        self.mcps: Dict[str, BaseMCPServer] = {}

    def register_mcp(self, mcp: BaseMCPServer):
        self.mcps[mcp.name] = mcp

    def get_mcp(self, mcp_name: str) -> BaseMCPServer:
        return self.mcps.get(mcp_name)

    async def execute_command(self, mcp_name: str,
                             tool_name: str, **kwargs) -> ToolResult:
        mcp = self.get_mcp(mcp_name)
        if not mcp:
            return ToolResult(
                is_error=True,
                content=f"MCP '{mcp_name}' not found",
                error_code="MCP_NOT_FOUND"
            )

        return await mcp.execute_tool(tool_name, **kwargs)
```

### Membership MCP 示例

```python
# src/mcp_servers/membership_mcp.py

class MembershipMCPServer(BaseMCPServer):
    def __init__(self, db_repo, http_client, minio_client):
        super().__init__("membership", "2.0")
        self.db_repo = db_repo
        self.http_client = http_client
        self.minio_client = minio_client

        # 加载API规范和文档
        self.api_spec = self._load_api_spec()
        self.documentation = self._load_documentation()

        # 注册所有工具
        self._register_tools()

    def _register_tools(self):
        """注册所有Membership API命令为工具"""
        self.register_tool(Tool(
            name="list_members",
            description="列出所有成员",
            input_schema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "default": 1},
                    "limit": {"type": "integer", "default": 10}
                }
            },
            handler=self.list_members
        ))

        # ... 其他工具

    async def list_members(self, page: int = 1, limit: int = 10) -> ToolResult:
        """实现 GET /v2/members"""
        try:
            response = await self.http_client.execute(
                method="GET",
                url=f"{self.api_spec['base_url']}/v2/members",
                params={"page": page, "limit": limit},
                auth_token=os.environ.get("MEMBERSHIP_API_TOKEN")
            )

            return ToolResult(
                is_error=False,
                content=f"Found {len(response.get('members', []))} members",
                data=response
            )
        except Exception as e:
            return ToolResult(
                is_error=True,
                content=str(e),
                error_code="LIST_MEMBERS_FAILED"
            )
```

---

## 📊 进度追踪模板

### 每日站会 (每日更新)

```
日期: 2026-01-10
完成的工作:
- [ ] Task 1.1: MCP框架 (30% 完成)
  - [x] 创建目录结构
  - [x] BaseMCPServer实现
  - [ ] MCPRegistry实现

阻碍:
- 无

次日优先事项:
- 完成MCPRegistry
- 开始Membership MCP

---
```

### 每周进度 (周五更新)

```
周数: Week 1 (2026-01-10 to 2026-01-14)

完成的里程碑:
- [ ] MCP Framework 完成 (Day 1)
- [ ] Membership MCP 完成 (Day 2)
- [ ] LLM Provider Management 完成 (Day 2)
- [ ] 集成测试通过 (Day 3)
- [ ] 用户验收通过 (Day 4)

总体进度: __%

阻碍及缓解:
- (如有)

下周计划:
- Phase 2: 第二个API迁移

---
```

---

## ✅ 完成标准

### Phase 1 Success Criteria

1. **功能完整性**
   - [ ] 所有Membership API命令都可作为MCP工具工作
   - [ ] LLM Provider Management系统完整
   - [ ] Planning Engine可以调用MCP命令

2. **质量标准**
   - [ ] 所有单元测试通过 (目标: > 85% 覆盖率)
   - [ ] 集成测试通过
   - [ ] 性能 < 10% 变慢 vs 原始HTTP客户端

3. **文档完整**
   - [ ] 开发者文档完整
   - [ ] MCP框架文档
   - [ ] Membership MCP文档
   - [ ] LLM配置文档

4. **用户验收**
   - [ ] 业务用户验收通过
   - [ ] 无关键bug
   - [ ] 用户满意度 > 4/5

---

## 🚀 启动指令

### 如果你已准备好执行，请确认：

1. ✅ 所有前置决策已做出
2. ✅ 团队成员已分配
3. ✅ 环境信息已准备
4. ✅ 代码库已准备
5. ✅ 测试环境已设置

**如果上述全部✅，可以开始Phase 1执行。**

---

**下一步**:
1. 填写此清单中的所有 [ ] 项
2. 确认所有前置条件
3. 更新PROGRESS.md标记Phase 1已启动
4. 开始Day 1任务

**预计完成**: 2026-01-14
**关键里程碑**: Membership MCP + LLM Management完全可用