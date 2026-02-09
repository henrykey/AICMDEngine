# AICMDEngine Examples

这个目录包含使用 AICMDEngine 的示例脚本。

## 如何使用外部 MCP 服务器

AICMDEngine 支持集成第三方 MCP (Model Context Protocol) 服务器来扩展功能。

### 快速开始

1. **选择并安装第三方 MCP 服务器**

   例如，安装文件系统 MCP：
   ```bash
   npm install -g @modelcontextprotocol/server-filesystem
   ```

   更多 MCP 服务器请查看：
   - [MCP 官方服务器列表](https://github.com/modelcontextprotocol/servers)
   - [社区 MCP 服务器](https://www.npmjs.com/search?q=%40modelcontextprotocol)

2. **配置 `.env` 文件**

   添加 `EXTERNAL_MCPS` 配置：
   ```bash
   EXTERNAL_MCPS='{
     "filesystem": {
       "command": "npx",
       "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
       "transport": "stdio",
       "timeout": 30
     }
   }'
   ```

3. **启动 AICMDEngine**

   ```bash
   python -m src.main
   ```

   查看日志确认 MCP 已加载：
   ```
   INFO: Loading 1 external MCP servers from configuration
   INFO: Successfully registered external MCP 'filesystem'
   ```

4. **在执行计划中使用**

   ```python
   from src.services.execution_engine import ExecutionEngine

   plan = [{
       "step": 1,
       "command": "filesystem.read_file",
       "description": "读取配置文件",
       "params": {
           "path": "/allowed/path/config.json"
       }
   }]

   engine = ExecutionEngine()
   result = await engine.execute_plan(plan)
   ```

### 常用第三方 MCP 服务器

#### 1. 文件系统 MCP

访问和管理文件系统。

```bash
# 安装
npm install -g @modelcontextprotocol/server-filesystem

# 配置
EXTERNAL_MCPS='{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"],
    "transport": "stdio"
  }
}'
```

#### 2. Git MCP

执行 Git 操作。

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

#### 3. SQLite MCP

操作 SQLite 数据库。

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

#### 4. GitHub MCP

与 GitHub API 交互。

```bash
# 安装
npm install -g @modelcontextprotocol/server-github

# 配置（需要 GITHUB_TOKEN）
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

#### 5. Office Word MCP

创建和操作 Microsoft Word 文档。

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

### 使用示例

#### 示例 1：读取文件

```python
plan = [{
    "step": 1,
    "command": "filesystem.read_file",
    "description": "读取配置文件",
    "params": {
        "path": "/home/user/projects/config.json"
    }
}]
```

#### 示例 2：创建 Word 文档

```python
plan = [
    {
        "step": 1,
        "command": "word.create_document",
        "description": "创建文档",
        "params": {
            "filename": "/home/user/Documents/report.docx",
            "title": "月度报告"
        }
    },
    {
        "step": 2,
        "command": "word.add_heading",
        "description": "添加标题",
        "params": {
            "filename": "/home/user/Documents/report.docx",
            "text": "2024年1月报告",
            "level": 1
        }
    },
    {
        "step": 3,
        "command": "word.add_paragraph",
        "description": "添加内容",
        "params": {
            "filename": "/home/user/Documents/report.docx",
            "text": "本月业务进展顺利。"
        }
    }
]
```

#### 示例 3：Git 操作

```python
plan = [{
    "step": 1,
    "command": "git.clone",
    "description": "克隆仓库",
    "params": {
        "url": "https://github.com/user/repo.git",
        "path": "/tmp/repo"
    }
}]
```

### 安全注意事项

⚠️ **重要**：

1. **限制文件系统访问** - 只配置必要的目录路径
   ```bash
   # ✅ 安全 - 限制特定目录
   "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]

   # ❌ 危险 - 允许访问整个系统
   "args": ["-y", "@modelcontextprotocol/server-filesystem", "/"]
   ```

2. **环境变量隔离** - 为外部 MCP 提供独立环境
   ```bash
   "env": {
     "GITHUB_TOKEN": "ghp_xxx",
     "HOME": "/tmp/mcp-github"
   }
   ```

3. **权限控制** - 使用最小权限原则

### 故障排除

#### 问题：npx 命令未找到

**解决**：使用完整路径
```bash
"command": "/usr/local/bin/npx"
```

#### 问题：权限被拒绝

**解决**：检查文件路径权限
```bash
ls -la /path/to/file
chmod +r /path/to/file
```

#### 问题：MCP 进程卡死

**解决**：调整超时时间
```bash
"timeout": 60  # 增加到 60 秒
```

### 更多文档

- [MCP 安装指南](../docs/mcp/MCP_INSTALLATION_GUIDE.md) - 内嵌式 vs 外部 MCP 对比
- [外部 MCP 示例](../docs/mcp/EXTERNAL_MCP_EXAMPLES.md) - 详细的配置示例和用法
- [外部 MCP 实现总结](../docs/mcp/EXTERNAL_MCP_IMPLEMENTATION_SUMMARY.md) - 技术实现细节

### 参考资源

- [MCP 官方网站](https://modelcontextprotocol.io/)
- [MCP 服务器列表](https://github.com/modelcontextprotocol/servers)
- [MCP SDK 文档](https://github.com/modelcontextprotocol/typescript-sdk)
