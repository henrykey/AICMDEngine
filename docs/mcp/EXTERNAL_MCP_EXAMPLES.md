# 外部MCP服务器使用示例

本文档展示如何配置和使用外部MCP服务器。

## 快速开始

### 1. 安装Node.js MCP服务器

```bash
# 安装文件系统MCP
npm install -g @modelcontextprotocol/server-filesystem

# 安装Git MCP
npm install -g @modelcontextprotocol/server-git
```

### 2. 配置环境变量

在 `.env` 文件中添加：

```bash
# JSON格式配置外部MCP
EXTERNAL_MCPS='{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/username/projects"],
    "transport": "stdio",
    "timeout": 30
  },
  "git": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-git", "/Users/username/projects"],
    "transport": "stdio",
    "timeout": 30
  }
}'
```

### 3. 启动服务

```bash
python -m src.main
```

查看日志输出：

```
INFO: Loading 2 external MCP servers from configuration
INFO: Starting external MCP 'filesystem': npx -y @modelcontextprotocol/server-filesystem /Users/username/projects
INFO: Connected to external MCP 'filesystem': File Server v1.0.0
INFO: Discovered 5 tools from external MCP 'filesystem'
INFO: Successfully registered external MCP 'filesystem'
INFO: Starting external MCP 'git': npx -y @modelcontextprotocol/server-git /Users/username/projects
INFO: Connected to external MCP 'git': Git Server v1.0.0
INFO: Discovered 8 tools from external MCP 'git'
INFO: Successfully registered external MCP 'git'
INFO: Initialized MCP Registry with 7 servers:
INFO:   - membership (v2.0): 8 tools
INFO:   - test (v1.0): 2 tools
INFO:   - kb (v1.0): 3 tools
INFO:   - bpmn (v1.0): 5 tools
INFO:   - form (v1.0): 4 tools
INFO:   - filesystem (v1.0): 5 tools
INFO:   - git (v1.0): 8 tools
```

## 使用示例

### 示例1：在计划中使用文件系统工具

```python
# 创建执行计划
plan = [
    {
        "step": 1,
        "command": "filesystem.read_file",
        "description": "读取配置文件",
        "params": {
            "path": "/Users/username/projects/config.json"
        }
    },
    {
        "step": 2,
        "command": "filesystem.write_file",
        "description": "写入更新后的配置",
        "params": {
            "path": "/Users/username/projects/config.json",
            "content": "{\"key\": \"value\"}"
        }
    }
]

# 执行计划
result = await execution_engine.execute_plan(plan)
```

### 示例2：使用Git工具

```python
plan = [
    {
        "step": 1,
        "command": "git.clone",
        "description": "克隆仓库",
        "params": {
            "url": "https://github.com/user/repo.git",
            "path": "/tmp/repo"
        }
    },
    {
        "step": 2,
        "command": "git.commit",
        "description": "提交更改",
        "params": {
            "path": "/tmp/repo",
            "message": "Update config",
            "files": ["config.json"]
        }
    }
]

result = await execution_engine.execute_plan(plan)
```

### 示例3：直接调用MCP

```python
from src.mcp.registry import get_mcp_registry

# 获取MCP registry
mcp_registry = get_mcp_registry()

# 调用文件系统MCP的工具
result = await mcp_registry.execute_command(
    mcp_name="filesystem",
    tool_name="read_file",
    path="/Users/username/projects/config.json"
)

print(result.content)
```

## 常用社区MCP服务器

### 1. 文件系统MCP

```bash
# 安装
npm install -g @modelcontextprotocol/server-filesystem

# 配置
EXTERNAL_MCPS='{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
    "transport": "stdio"
  }
}'
```

**可用工具**:
- `read_file` - 读取文件
- `write_file` - 写入文件
- `list_directory` - 列出目录
- `create_directory` - 创建目录
- `move_file` - 移动文件

### 2. Git MCP

```bash
# 安装
npm install -g @modelcontextprotocol/server-git

# 配置
EXTERNAL_MCPS='{
  "git": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-git", "/path/to/repo"],
    "transport": "stdio"
  }
}'
```

**可用工具**:
- `clone` - 克隆仓库
- `commit` - 提交更改
- `create_branch` - 创建分支
- `switch_branch` - 切换分支
- `get_diff` - 获取差异

### 3. SQLite MCP

```bash
# 安装
npm install -g @modelcontextprotocol/server-sqlite

# 配置
EXTERNAL_MCPS='{
  "sqlite": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "./mydb.sqlite"],
    "transport": "stdio"
  }
}'
```

**可用工具**:
- `query` - 执行SQL查询
- `execute` - 执行SQL语句

### 4. GitHub MCP

```bash
# 安装
npm install -g @modelcontextprotocol/server-github

# 配置（需要GITHUB_TOKEN环境变量）
EXTERNAL_MCPS='{
  "github": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "transport": "stdio",
    "env": {
      "GITHUB_TOKEN": "ghp_your_token_here"
    }
  }
}'
```

**可用工具**:
- `get_repo` - 获取仓库信息
- `create_issue` - 创建Issue
- `create_pull_request` - 创建PR
- `push_files` - 推送文件

### 5. Postgres MCP

```bash
# 安装
npm install -g @modelcontextprotocol/server-postgres

# 配置
EXTERNAL_MCPS='{
  "postgres": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost/db"],
    "transport": "stdio"
  }
}'
```

**可用工具**:
- `query` - 执行查询
- `execute` - 执行语句

### 6. Office Word MCP

```bash
# 安装
git clone https://github.com/MaoTouHU/Office-Word-MCP-Server.git
cd Office-Word-MCP-Server
pip install -r requirements.txt

# 配置
EXTERNAL_MCPS='{
  "word": {
    "command": "python",
    "args": ["/absolute/path/to/Office-Word-MCP-Server/word_mcp_server.py"],
    "transport": "stdio",
    "timeout": 60
  }
}'
```

**可用工具** (50+):
- `create_document` - 创建Word文档
- `add_heading` - 添加标题
- `add_paragraph` - 添加段落
- `add_table` - 创建表格
- `format_text` - 格式化文本
- `convert_to_pdf` - 转换为PDF
- 更多工具请查看项目文档

**示例**:
```python
plan = [{
    "step": 1,
    "command": "word.create_document",
    "description": "创建文档",
    "params": {
        "filename": "/path/to/document.docx",
        "title": "我的文档"
    }
}, {
    "step": 2,
    "command": "word.add_heading",
    "description": "添加标题",
    "params": {
        "filename": "/path/to/document.docx",
        "text": "欢迎使用Word MCP",
        "level": 1
    }
}]
```

## 安全注意事项

### 文件系统访问限制

⚠️ **重要**: 只允许访问必要的目录

```bash
# ❌ 危险 - 允许访问整个根目录
EXTERNAL_MCPS='{"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/"]}}'

# ✅ 安全 - 限制访问特定目录
EXTERNAL_MCPS='{"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]}}'
```

### 环境变量隔离

```bash
# 为外部MCP提供独立的环境变量
EXTERNAL_MCPS='{
  "github": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {
      "GITHUB_TOKEN": "ghp_xxx",
      "HOME": "/tmp/mcp-github"
    }
  }
}'
```

### 只读模式

某些MCP支持只读模式：

```bash
# Git只读模式
EXTERNAL_MCPS='{
  "git": {
    "command": "git",  # 使用git命令而非npx
    "args": ["--no-optional-locks"],
    "transport": "stdio"
  }
}'
```

## 故障排除

### 问题1：npx命令未找到

**错误**: `[Errno 2] No such file or directory: 'npx'`

**解决**:
```bash
# 使用完整路径
EXTERNAL_MCPS='{
  "filesystem": {
    "command": "/usr/local/bin/npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
  }
}'

# 或使用node模块
EXTERNAL_MCPS='{
  "filesystem": {
    "command": "node",
    "args": ["/usr/local/lib/node_modules/@modelcontextprotocol/server-filesystem/index.js", "/path"]
  }
}'
```

### 问题2：权限不足

**错误**: `Permission denied: /path/to/file`

**解决**:
```bash
# 检查目录权限
ls -la /path/to/directory

# 确保用户有读权限
chmod +r /path/to/file

# 或更改allowed path
EXTERNAL_MCPS='{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/allowed-dir"]
  }
}'
```

### 问题3：MCP进程卡死

**症状**: 工具调用无响应

**解决**:
```bash
# 减小超时时间（默认30秒）
EXTERNAL_MCPS='{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
    "timeout": 10
  }
}'
```

### 问题4：JSON解析错误

**错误**: `Failed to parse EXTERNAL_MCPS as JSON`

**解决**:
```bash
# 使用单引号包裹整个JSON字符串
EXTERNAL_MCPS='{"key": "value"}'

# 或使用环境变量文件
cat > .env << EOF
EXTERNAL_MCPS={"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]}}
EOF
```

## 性能优化

### 1. 延迟启动

对于不常用的MCP，可以按需启动：

```python
# 在main.py中添加开关
ENABLE_EXTERNAL_MCPS = os.getenv("ENABLE_EXTERNAL_MCPS", "false").lower() == "true"

if ENABLE_EXTERNAL_MCPS:
    # 注册外部MCP
    pass
```

### 2. 连接池管理

对于频繁调用的MCP，可以增加超时时间：

```bash
EXTERNAL_MCPS='{
  "database": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres", "..."],
    "timeout": 60  # 增加到60秒
  }
}'
```

### 3. 资源限制

限制外部MCP的资源使用：

```bash
# 使用ulimit限制
ulimit -u 50  # 限制进程数
ulimit -v 1048576  # 限制内存使用(1GB)

# 然后启动服务
python -m src.main
```

## 高级用法

### 自定义MCP包装器

如果需要为外部MCP添加额外逻辑：

```python
# src/mcp_servers/wrapped_filesystem_mcp.py
from src.mcp.external_mcp import ExternalMCPServer

class WrappedFilesystemMCP(ExternalMCPServer):
    """带权限检查的文件系统MCP"""

    async def _execute_external_tool(self, tool_name, arguments):
        # 添加权限检查
        if tool_name in ["write_file", "delete_file"]:
            if not self._check_permission(arguments["path"]):
                return ToolResult.error("Permission denied", "ACCESS_DENIED")

        # 调用父类方法
        return await super()._execute_external_tool(tool_name, arguments)

    def _check_permission(self, path):
        # 实现权限检查逻辑
        return True
```

### 多实例配置

同一MCP的多个实例：

```bash
EXTERNAL_MCPS='{
  "fs_home": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
  },
  "fs_tmp": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
  }
}'
```

使用：
```python
# 访问home目录
await mcp_registry.execute_command("fs_home", "read_file", path="/config.json")

# 访问tmp目录
await mcp_registry.execute_command("fs_tmp", "write_file", path="/test.txt", content="test")
```

## 参考资源

- [MCP官方服务器列表](https://github.com/modelcontextprotocol/servers)
- [MCP SDK文档](https://github.com/modelcontextprotocol/typescript-sdk)
- [社区MCP服务器](https://www.npmjs.com/search?q=%40modelcontextprotocol)
