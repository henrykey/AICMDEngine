# MCP Tools UI Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 Task Playground 中添加 MCP 选择功能，并创建新的 MCP Tools 浏览器菜单来替代老的 Command Sets。

**Architecture:**
1. 在 PlannerExecutorPanel 顶部添加 MCP 选择下拉菜单
2. 创建新的 MCPTools.tsx 页面作为 MCP Tools 浏览器
3. 添加后端 API 来获取可用的 MCP 服务器列表和它们的工具
4. 在 Dashboard 中替换 "Command Sets" 菜单项为 "MCP Tools"
5. 保持向后兼容性，继续支持 Command Sets（隐藏但不删除）

**Tech Stack:**
- Frontend: React 18 + TypeScript + Tailwind CSS
- Backend: FastAPI (已有 MCP API 端点)
- State Management: React Context (TaskContext)
- HTTP Client: axios via `lib/api`

---

## Phase 1: 后端 API 支持

### Task 1: 验证现有 MCP API 端点

**Files:**
- Check: `src/routers/mcp.py`
- Reference: `/v1/mcp/servers` endpoint

**Step 1: 验证 MCP 列表端点**

当前应该已经有 `GET /v1/mcp/servers` 端点。运行：
```bash
curl -H "Authorization: Bearer <token>" \
     -H "X-Tenant-ID: 1" \
     http://localhost:8000/v1/mcp/servers
```

预期响应格式：
```json
{
  "success": true,
  "data": [
    {
      "name": "membership",
      "version": "1.0.0",
      "description": "Membership API MCP",
      "status": "running",
      "tools": [
        {
          "name": "list_members",
          "description": "List all members",
          "input_schema": {...}
        }
      ]
    }
  ]
}
```

**Step 2: 验证端点返回的数据结构**

确保 `/v1/mcp/servers` 返回的每个服务器包含：
- `name`: 服务器名称
- `version`: 版本
- `description`: 描述
- `status`: 运行状态 (running/stopped/error)
- `tools`: 工具数组（每个工具包含 name, description, input_schema）

如果数据结构不符合，需要在 `src/routers/mcp.py` 中修改 API 响应。

---

## Phase 2: 前端 - MCP 选择组件

### Task 2: 创建 MCPSelector 组件

**Files:**
- Create: `plan2/src/components/MCPSelector.tsx`
- Modify: `plan2/src/components/PlannerExecutorPanel.tsx`
- Reference: `plan2/src/contexts/TaskContext.tsx` (扩展上下文)

**Step 1: 扩展 TaskContext 以支持 MCP 选择**

在 `plan2/src/contexts/TaskContext.tsx` 中添加：

```typescript
interface TaskContextType {
  // ... existing fields ...
  selectedMcp: string | null;
  setSelectedMcp: (mcp: string | null) => void;
  availableMcps: MCPServerInfo[];
  setAvailableMcps: (mcps: MCPServerInfo[]) => void;
}

interface MCPServerInfo {
  name: string;
  version: string;
  description: string;
  status: 'running' | 'stopped' | 'error';
  tools: MCPToolInfo[];
}

interface MCPToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, any>;
}
```

更新 Context Provider 来初始化这些字段。

**Step 2: 创建 MCPSelector.tsx 组件**

创建 `plan2/src/components/MCPSelector.tsx`：

```typescript
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useTask } from '../contexts/TaskContext';

interface MCPServerInfo {
  name: string;
  version: string;
  description: string;
  status: 'running' | 'stopped' | 'error';
  tools: Array<{ name: string; description: string }>;
}

const MCPSelector: React.FC = () => {
  const { selectedMcp, setSelectedMcp, availableMcps, setAvailableMcps } = useTask();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载可用的 MCP 服务器列表
  useEffect(() => {
    const loadMCPs = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.get<{ success: boolean; data: MCPServerInfo[] }>(
          '/v1/mcp/servers'
        );
        if (response.data.success) {
          setAvailableMcps(response.data.data);
          // 自动选择第一个运行中的 MCP
          const runningMcp = response.data.data.find(m => m.status === 'running');
          if (runningMcp && !selectedMcp) {
            setSelectedMcp(runningMcp.name);
          }
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load MCP servers');
      } finally {
        setLoading(false);
      }
    };

    loadMCPs();
  }, [setAvailableMcps, setSelectedMcp, selectedMcp]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running':
        return 'bg-green-100 text-green-800 border-green-300';
      case 'stopped':
        return 'bg-gray-100 text-gray-800 border-gray-300';
      case 'error':
        return 'bg-red-100 text-red-800 border-red-300';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-300';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running':
        return '🟢';
      case 'stopped':
        return '⚪';
      case 'error':
        return '🔴';
      default:
        return '⚪';
    }
  };

  return (
    <div className="bg-white p-4 border-b border-slate-200 rounded-lg">
      <div className="flex items-center gap-4">
        <label className="text-sm font-semibold text-slate-700 whitespace-nowrap">
          Select MCP:
        </label>

        {loading ? (
          <div className="text-sm text-slate-500">Loading MCPs...</div>
        ) : error ? (
          <div className="text-sm text-red-500">{error}</div>
        ) : availableMcps.length === 0 ? (
          <div className="text-sm text-slate-500">No MCPs available</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {availableMcps.map((mcp) => (
              <button
                key={mcp.name}
                onClick={() => setSelectedMcp(mcp.name)}
                disabled={mcp.status !== 'running'}
                className={`px-3 py-2 rounded-lg border-2 transition-all ${
                  selectedMcp === mcp.name
                    ? 'ring-2 ring-blue-500 border-blue-500'
                    : 'border-slate-200 hover:border-slate-300'
                } ${
                  mcp.status !== 'running'
                    ? 'opacity-50 cursor-not-allowed'
                    : 'cursor-pointer'
                } ${getStatusColor(mcp.status)}`}
                title={`${mcp.description} (${mcp.status})`}
              >
                <span className="mr-1">{getStatusIcon(mcp.status)}</span>
                {mcp.name} ({mcp.tools.length} tools)
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedMcp && availableMcps.length > 0 && (
        <div className="mt-3 text-xs text-slate-600">
          {availableMcps.find(m => m.name === selectedMcp)?.description}
        </div>
      )}
    </div>
  );
};

export default MCPSelector;
```

**Step 3: 更新 PlannerExecutorPanel 集成 MCPSelector**

在 `plan2/src/components/PlannerExecutorPanel.tsx` 的顶部添加：

```typescript
import MCPSelector from './MCPSelector';

const PlannerExecutorPanel: React.FC = () => {
  // ... existing code ...

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* 添加 MCP 选择器 */}
      <MCPSelector />

      {/* 现有的规划和执行界面 */}
      <div className="flex-1 overflow-auto">
        {/* ... existing content ... */}
      </div>
    </div>
  );
};
```

---

## Phase 3: 前端 - MCP Tools 浏览器页面

### Task 3: 创建 MCPTools 页面

**Files:**
- Create: `plan2/src/pages/MCPTools.tsx`
- Modify: `plan2/src/pages/Dashboard.tsx`

**Step 1: 创建 MCPTools.tsx 页面**

创建 `plan2/src/pages/MCPTools.tsx`：

```typescript
import { useState, useEffect } from 'react';
import { api } from '../lib/api';

interface MCPToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, any>;
}

interface MCPServerInfo {
  name: string;
  version: string;
  description: string;
  status: 'running' | 'stopped' | 'error';
  tools: MCPToolInfo[];
}

const MCPTools = () => {
  const [mcps, setMcps] = useState<MCPServerInfo[]>([]);
  const [selectedMcp, setSelectedMcp] = useState<string | null>(null);
  const [selectedTool, setSelectedTool] = useState<MCPToolInfo | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载 MCP 列表
  useEffect(() => {
    const loadMCPs = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.get<{ success: boolean; data: MCPServerInfo[] }>(
          '/v1/mcp/servers'
        );
        if (response.data.success) {
          setMcps(response.data.data);
          if (response.data.data.length > 0) {
            setSelectedMcp(response.data.data[0].name);
          }
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load MCP servers');
      } finally {
        setLoading(false);
      }
    };

    loadMCPs();
  }, []);

  const currentMcp = mcps.find(m => m.name === selectedMcp);
  const tools = currentMcp?.tools || [];

  // 过滤工具
  const filteredTools = tools.filter(tool =>
    tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    tool.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getStatusBadge = (status: string) => {
    const statusConfig: Record<string, { icon: string; color: string }> = {
      running: { icon: '🟢', color: 'bg-green-100 text-green-800' },
      stopped: { icon: '⚪', color: 'bg-gray-100 text-gray-800' },
      error: { icon: '🔴', color: 'bg-red-100 text-red-800' }
    };
    const config = statusConfig[status] || statusConfig.stopped;
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${config.color}`}>
        {config.icon} {status}
      </span>
    );
  };

  return (
    <div className="flex flex-col gap-6 h-full p-6 bg-slate-50">
      {/* 标题 */}
      <div>
        <h1 className="text-2xl font-bold text-slate-800">MCP Tools Browser</h1>
        <p className="text-sm text-slate-600 mt-1">
          Browse and test MCP tools from available MCP servers
        </p>
      </div>

      <div className="flex gap-6 flex-1 overflow-hidden">
        {/* 左侧：MCP 服务器列表 */}
        <div className="w-64 bg-white rounded-lg border border-slate-200 p-4 flex flex-col gap-4 overflow-hidden">
          <h2 className="font-semibold text-slate-800">MCP Servers</h2>

          {loading ? (
            <div className="text-sm text-slate-500">Loading...</div>
          ) : error ? (
            <div className="text-sm text-red-500">{error}</div>
          ) : mcps.length === 0 ? (
            <div className="text-sm text-slate-500">No MCP servers available</div>
          ) : (
            <div className="space-y-2 overflow-auto flex-1">
              {mcps.map((mcp) => (
                <button
                  key={mcp.name}
                  onClick={() => {
                    setSelectedMcp(mcp.name);
                    setSelectedTool(null);
                    setSearchQuery('');
                  }}
                  disabled={mcp.status !== 'running'}
                  className={`w-full text-left px-3 py-2 rounded-lg border-2 transition-all ${
                    selectedMcp === mcp.name
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-slate-200 hover:border-slate-300'
                  } ${
                    mcp.status !== 'running'
                      ? 'opacity-50 cursor-not-allowed'
                      : 'cursor-pointer'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm text-slate-800 truncate">
                        {mcp.name}
                      </div>
                      <div className="text-xs text-slate-600 truncate">
                        {mcp.tools.length} tools
                      </div>
                    </div>
                    <div className="text-xs flex-shrink-0">
                      {getStatusBadge(mcp.status).props.children[0]}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 中间：工具列表 */}
        <div className="w-72 bg-white rounded-lg border border-slate-200 p-4 flex flex-col gap-4 overflow-hidden">
          <div>
            <h2 className="font-semibold text-slate-800 mb-3">Tools</h2>
            <input
              type="text"
              placeholder="Search tools..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {currentMcp ? (
            <div className="space-y-2 overflow-auto flex-1">
              {filteredTools.length === 0 ? (
                <div className="text-sm text-slate-500">No tools found</div>
              ) : (
                filteredTools.map((tool) => (
                  <button
                    key={tool.name}
                    onClick={() => setSelectedTool(tool)}
                    className={`w-full text-left px-3 py-2 rounded-lg border-2 transition-all ${
                      selectedTool?.name === tool.name
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-slate-200 hover:border-slate-300'
                    } cursor-pointer`}
                  >
                    <div className="font-medium text-sm text-slate-800">
                      {tool.name}
                    </div>
                    <div className="text-xs text-slate-600 line-clamp-2">
                      {tool.description}
                    </div>
                  </button>
                ))
              )}
            </div>
          ) : (
            <div className="text-sm text-slate-500">Select an MCP server</div>
          )}
        </div>

        {/* 右侧：工具详情 */}
        <div className="flex-1 bg-white rounded-lg border border-slate-200 p-4 flex flex-col gap-4 overflow-hidden">
          {selectedTool ? (
            <>
              <div>
                <h3 className="text-lg font-semibold text-slate-800">
                  {selectedTool.name}
                </h3>
                <p className="text-sm text-slate-600 mt-2">
                  {selectedTool.description}
                </p>
              </div>

              <div>
                <h4 className="font-medium text-slate-800 mb-2">Input Schema</h4>
                <pre className="bg-slate-100 p-3 rounded-lg text-xs overflow-auto max-h-96 border border-slate-300">
                  {JSON.stringify(selectedTool.input_schema, null, 2)}
                </pre>
              </div>

              <div className="mt-auto">
                <button
                  className="w-full px-4 py-2 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 transition-colors"
                >
                  Test Tool
                </button>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-slate-500">
              Select a tool to view details
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default MCPTools;
```

---

## Phase 4: 更新 Dashboard 菜单

### Task 4: 替换 Command Sets 菜单

**Files:**
- Modify: `plan2/src/pages/Dashboard.tsx`

**Step 1: 更新 NAV_ITEMS**

在 `plan2/src/pages/Dashboard.tsx` 中修改 NAV_ITEMS：

```typescript
const NAV_ITEMS: NavItem[] = [
  { id: 'planner', label: 'Task Playground', icon: '🚀' },
  { id: 'mcp-tools', label: 'MCP Tools', icon: '🔧' },  // 替换 'commands'
  { id: 'settings', label: 'Settings', icon: '⚙️' },
  { id: 'analytics', label: 'Analytics', icon: '📊' },
  { id: 'documentation', label: 'Docs', icon: '📖' },
];
```

**Step 2: 导入 MCPTools 组件**

在 `Dashboard.tsx` 顶部添加：

```typescript
import MCPTools from './MCPTools';
```

**Step 3: 更新条件渲染**

在 Dashboard 的主体部分，将：

```typescript
{activeNav === 'commands' && <CommandSets />}
```

替换为：

```typescript
{activeNav === 'mcp-tools' && <MCPTools />}
```

**Step 4: 更新头部描述**

在头部工作区标题部分，添加 mcp-tools 的描述：

```typescript
{activeNav === 'mcp-tools' && 'Browse and test MCP tools from available servers'}
```

---

## Phase 5: 集成和验证

### Task 5: 测试整个流程

**Files:**
- Test: 所有前端组件

**Step 1: 验证编译**

```bash
cd plan2
npm run build
```

预期：编译成功，无错误

**Step 2: 启动开发服务器**

```bash
npm run dev
```

预期：应用在 localhost:5173 运行

**Step 3: 验证 MCP 选择器**

1. 登录到应用
2. 进入 "Task Playground"
3. 应该在上方看到 MCP 选择器
4. 验证能看到 "membership" MCP 和它的工具数量

**Step 4: 验证 MCP Tools 页面**

1. 从菜单选择 "MCP Tools"
2. 左侧应该显示可用的 MCP 服务器
3. 点击服务器，中间应该显示工具列表
4. 点击工具，右侧应该显示工具的详情和 input schema

**Step 5: 验证后向兼容性**

1. 确保旧的 CommandSets 页面仍然存在（可以通过直接导航到它）
2. 它应该像以前一样工作

---

## Phase 6: 文档更新

### Task 6: 更新文档

**Files:**
- Modify: `docs/mcp/development-guide.md`
- Modify: `docs/NL_TASK_PLANNING_SERVICE_DESIGN.md`

**Step 1: 在 MCP 开发指南中添加 UI 使用说明**

在 `docs/mcp/development-guide.md` 中添加一个新的部分：

```markdown
## Using MCP Tools UI

### Task Playground - MCP Selection

When planning tasks, you must first select which MCP to use:

1. Go to "Task Playground"
2. At the top, you'll see the "Select MCP" dropdown
3. Choose the desired MCP (only running MCPs can be selected)
4. Enter your natural language task
5. The LLM will generate a plan using tools from the selected MCP

### MCP Tools Browser

For developers and debugging:

1. Go to "MCP Tools" from the main menu
2. Left panel: Select an MCP server
3. Middle panel: Browse available tools
4. Right panel: View tool details and input schema
5. Use "Test Tool" button to test tools directly (Phase 2)

```

**Step 2: 在规划设计文档中记录 MCP 选择流程**

在 `docs/NL_TASK_PLANNING_SERVICE_DESIGN.md` 的架构部分添加：

```markdown
## MCP Selection in Planning

The planning process now includes an explicit MCP selection step:

1. **User selects MCP** - In Task Playground, user chooses which MCP to use
2. **User enters goal** - Natural language task description
3. **Planning Engine loads commands** - From selected MCP only
4. **LLM generates plan** - Using commands from that MCP
5. **Plan execution** - Execution engine executes the plan

This allows better control and clearer multi-MCP support in the future.
```

---

## 总结

这个计划包含以下交付物：

✅ **后端支持** - 验证现有 MCP API 端点工作正常

✅ **MCP 选择器组件** - 在 Task Playground 中让用户选择 MCP

✅ **MCP Tools 浏览器页面** - 新的菜单项来浏览和检查 MCP 工具

✅ **Dashboard 更新** - 替换"Command Sets"为"MCP Tools"

✅ **后向兼容性** - Command Sets 页面仍然存在

✅ **文档更新** - 说明如何使用新的 MCP 选择功能

**预计工作量**: 1.5-2 天（取决于后端 API 的现有完整性）

**关键风险**:
- 如果现有 MCP API 返回数据结构不符合预期，需要调整后端
- React Context 扩展需要小心避免破坏现有功能
