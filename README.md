# AICMDEngine - AI Code Management Development Engine

**AICMDEngine** (AI Code Management Development Engine) 是一个智能中间件，将自然语言目标转化为可执行的计划。它通过整合 AI 能力和多租户组织管理，提供端到端的任务规划、命令执行和结果反馈系统。

## 📋 项目概述

### 核心功能

- **自然语言任务规划**：将用户的自然语言目标转化为具体的执行计划
- **多步骤工作流执行**：支持复杂的多步骤命令序列执行
- **多租户支持**：完整的多租户隔离和组织层级管理
- **API 集成**：与第三方 API（如 Membership Service）深度集成
- **执行追踪**：完整的执行历史记录和状态跟踪

### 技术栈

**后端：**
- FastAPI - Web 框架
- MongoDB - 数据库
- Motor - 异步 MongoDB 驱动
- Python 3.x

**前端：**
- React 19.2
- TypeScript
- Vite - 构建工具
- Tailwind CSS - 样式框架
- React Router - 路由
- TanStack Query - 数据管理

### 项目结构

```
AICMDEngine/
├── src/                          # 后端源代码
│   ├── main.py                   # 应用入口
│   ├── core/
│   │   └── config.py            # 配置管理
│   ├── models/                   # 数据模型
│   ├── routers/                  # API 路由
│   │   ├── tasks.py             # 任务相关 API
│   │   ├── command_sets.py       # 命令集 API
│   │   └── executions.py        # 执行相关 API
│   └── services/                 # 业务逻辑服务
│       ├── llm_client.py        # LLM 集成
│       ├── planning_engine.py    # 规划引擎
│       └── http_client.py       # HTTP 请求客户端
├── ui/                           # 前端源代码
│   ├── src/
│   │   ├── pages/               # React 页面组件
│   │   ├── lib/                 # 工具和 API 客户端
│   │   ├── App.tsx
│   │   └── main.tsx
│   └── package.json             # 前端依赖
├── tests/                        # 测试文件
├── docs/                         # 文档和设计文档
├── config.yml                    # 应用配置文件
├── requirements.txt              # Python 依赖
└── README.md                     # 本文件
```

## 🚀 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+
- npm 或 pnpm
- MongoDB 6.0+（本地或远程）

### 后端安装

1. **安装 Python 依赖**
   ```bash
   pip install -r requirements.txt
   ```

2. **配置环境变量**

   创建 `.env` 文件在项目根目录：
   ```env
   DEEPSEEK_API_KEY=your_deepseek_api_key_here
   OPENAI_API_KEY=your_openai_api_key_here
   MONGODB_URI=mongodb://localhost:27017
   ```

3. **验证配置**

   `config.yml` 中的主要配置项：
   - `backend.host` / `backend.port` - API 服务器地址
   - `database.host` / `database.port` - MongoDB 连接
   - `services.membership` - Membership Service 地址
   - `services.ai_providers` - AI 提供商配置

### 后端运行

启动 FastAPI 开发服务器（推荐）：

```bash
# 推荐：以模块方式运行（避免导入错误）
python -m src.main
```

或者直接使用 `uvicorn`（常用的开发方式）：

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

> 注意：直接运行 `python src/main.py` 可能导致 `ModuleNotFoundError: No module named 'src'`，原因是以脚本方式运行时，Python 会把 `src/` 目录作为脚本目录加入 `sys.path`，导致顶层包 `src` 无法正确导入。
>
> 临时解决方法：
>
```bash
# 把项目根目录加入 PYTHONPATH：
PYTHONPATH=. python src/main.py
```

或者在项目根创建一个运行脚本 `run.py` 来启动应用：

```python
# run.py
from src.main import app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
```

服务器将在 `http://localhost:8000` 启动。检查健康状态：

```bash
curl http://localhost:8000/health
```

### 前端安装

1. **进入前端目录**
   ```bash
   cd ui
   ```

2. **安装依赖**
   ```bash
   npm install
   ```

### 前端开发

启动 Vite 开发服务器：

```bash
cd ui
npm run dev
```

前端将在 `http://localhost:5173` 启动（具体端口请查看终端输出）。

### 前端构建

编译生产版本：

```bash
cd ui
npm run build
```

构建输出在 `ui/dist/` 目录。

## 📡 API 概览

### 核心端点

**任务管理**
- `POST /v1/tasks` - 创建任务
- `GET /v1/tasks` - 列出任务
- `GET /v1/tasks/{task_id}` - 获取任务详情

**命令集管理**
- `POST /v1/command-sets` - 创建命令集
- `GET /v1/command-sets` - 列出命令集
- `GET /v1/command-sets/{command_set_id}` - 获取命令集详情

**执行管理**
- `POST /v1/executions` - 创建执行
- `GET /v1/executions` - 列出执行
- `GET /v1/executions/{execution_id}` - 获取执行详情

### 请求头要求

所有 API 请求需要包含租户标识：

```bash
curl -H "X-Tenant-ID: 1" http://localhost:8000/v1/tasks
```

## 🔧 配置详解

### config.yml 配置说明

```yaml
# 应用基本信息
app:
  name: "AICMDEngine"
  version: "1.0.0"

# 后端服务器配置
backend:
  host: "localhost"       # 监听地址
  port: 8000             # 监听端口
  base_path: "/v1"       # API 基础路径

# 外部服务配置
services:
  membership:
    host: "localhost"
    port: 8080
    base_path: "/api/v1"  # Membership Service API 路径

  ai_providers:
    - name: "deepseek"
      base_url: "https://api.deepseek.com/v1"
      model_name: "deepseek-chat"
      api_key_env: "DEEPSEEK_API_KEY"

# 数据库配置
database:
  host: "jnuc2"          # MongoDB 主机
  port: 27017            # MongoDB 端口
  name: "nl_tps"         # 数据库名称

# 开发配置
development:
  auto_reload: true      # 自动重载
  debug: true            # 调试模式
```

### 多租户支持

系统采用租户隔离模式：

- 每个 API 请求必须指定 `X-Tenant-ID` 请求头
- 数据库中所有记录都关联特定租户 ID
- Membership Service 提供租户的组织结构信息

## 📚 常见任务

### 使用自然语言创建和管理用户

AICMDEngine 最强大的功能是使用自然语言命令来创建、修改和删除用户。以下是完整的工作流程：

#### 步骤 1: 从 Membership Service 获取认证令牌

```bash
curl -X POST http://localhost:8080/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123"
  }'
```

响应将包含 `access_token`。

#### 步骤 2: 使用自然语言规划任务

```bash
curl -X POST http://localhost:8000/v1/tasks/ \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 1" \
  -d '{
    "goal": "Create a new user testuser333 with email testuser333@example.com",
    "conversationHistory": []
  }'
```

系统将返回一个执行计划或澄清问题。

#### 步骤 3: 执行计划创建用户

```bash
curl -X POST http://localhost:8000/v1/executions/ \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 1" \
  -H "Authorization: Bearer <your-access-token>" \
  -d '{
    "plan": [
      {
        "step": 1,
        "description": "Create a new user",
        "command": "POST /v2/members",
        "params": {
          "headers": {"X-Tenant-ID": 1},
          "body": {
            "username": "testuser333",
            "email": "testuser333@example.com"
          }
        }
      }
    ],
    "global_timeout": 60
  }'
```

系统将返回执行 ID。

#### 步骤 4: 查询执行状态

```bash
curl -X GET http://localhost:8000/v1/executions/<execution-id> \
  -H "X-Tenant-ID: 1"
```

#### 步骤 5: 删除用户

使用相同的流程，但改为删除命令：

```bash
curl -X POST http://localhost:8000/v1/tasks/ \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 1" \
  -d '{
    "goal": "Delete the user testuser333",
    "conversationHistory": []
  }'
```

### 数据库初始化

清空并重新初始化数据库（谨慎使用）：

```bash
python seed_db.py
```

### 测试 LLM 连接

快速验证 LLM 提供商连接：

```bash
node test_llm.js
```

### 运行测试

执行项目测试：

```bash
pytest tests/ -v
```

### 代码 Linting

检查前端代码风格：

```bash
cd ui
npm run lint
```

## 🏗️ 架构说明

### 请求流程

```
用户请求
    ↓
FastAPI 应用 (main.py)
    ↓
路由层 (routers/)
    ↓
服务层 (services/)
    ├── LLM 客户端 (llm_client.py)        → AI 规划生成
    ├── 规划引擎 (planning_engine.py)     → 计划解析
    ├── HTTP 客户端 (http_client.py)     → 外部 API 调用
    └── 执行引擎 (execution_engine.py)    → 执行管理
    ↓
模型层 (models/)
    ↓
数据库 (MongoDB)
```

### 执行引擎

执行引擎负责：

1. **计划解析**：解析 LLM 生成的执行计划
2. **步骤执行**：按顺序执行计划中的各个步骤
3. **API 调用**：通过 HTTP 客户端调用 Membership Service 或其他 API
4. **状态管理**：维护执行状态和结果
5. **错误处理**：捕获和记录执行过程中的错误

## 🔐 安全性

- API 密钥存储在环境变量或 `.env` 文件中
- 不要在代码中硬编码敏感信息
- 租户隔离确保多租户环境的数据安全
- CORS 配置允许跨域请求（生产环境应改为特定域名）

## 🐛 故障排除

### MongoDB 连接失败
- 确保 MongoDB 服务正在运行
- 检查 `config.yml` 中的数据库配置
- 验证 `MONGODB_URI` 环境变量（如果设置）

### API 请求返回 401/403
- 确保请求包含有效的 `X-Tenant-ID` 请求头
- 检查认证令牌是否过期

### Membership Service 连接失败
- 确保 Membership Service 在 `config.yml` 中配置的地址运行
- 检查网络连接和防火墙设置

### LLM API 错误
- 验证 `DEEPSEEK_API_KEY` 和 `OPENAI_API_KEY` 环境变量
- 检查 API 密钥是否有效和配额充足

## 📖 进阶文档

详细的技术文档位于 `docs/` 目录：

- `NL_TASK_PLANNING_SERVICE_DESIGN.md` - 系统设计文档（中文）
- `NL_TASK_PLANNING_SERVICE_DESIGN_EN.md` - 系统设计文档（英文）
- `NATURAL_LANGUAGE_COMMAND_FRAMEWORK.md` - 自然语言框架说明
- `MEMBERSHIP_USAGE_MANUAL.md` - Membership Service 使用手册
- `EXECUTION_ENGINE_AUDIT_REPORT.md` - 执行引擎审计报告

## 🤝 贡献指南

### 代码风格

**Python：**
- 遵循 PEP 8 标准
- 使用 `snake_case` 命名函数和变量
- 2 空格缩进

**TypeScript/React：**
- 遵循 ESLint 配置
- 使用 `PascalCase` 命名组件
- 使用有意义的变量名

### 提交规范

提交信息格式（驼峰首字母小写）：
- `feat: 新功能说明`
- `fix: 修复说明`
- `refactor: 重构说明`
- `docs: 文档更新`
- `test: 测试相关`

## 📄 许可证

[在此添加许可证信息]

## 👥 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 Issue
- 提交 Pull Request
- 查看项目文档

## 📝 更新日志

### v1.0.0 (2026-01-03)

- ✅ 执行引擎核心功能完成
- ✅ 多租户支持和测试完成
- ✅ 组织结构 API 集成完成
- ✅ 前端 UI 框架搭建完成

---

**最后更新**: 2026-01-03
