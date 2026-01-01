# AICMDEngine 重构计划

**创建日期**: 2026-01-01
**目标**: 修复设计问题，提升代码质量和可维护性

---

## 📋 决策摘要

基于架构审查，我们确认了以下优化方向：

### ✅ 已确定的决策

1. **tenant_id 类型统一** → 统一为 `int`
2. **API 密钥存储** → 环境变量 + .env（pydantic-settings）
3. **性能优化** → Commands 查询添加 limit，智能筛选
4. **可维护性** → 添加测试、日志、错误处理、API 文档
5. **可扩展性** → 清理硬编码配置
6. **功能缺失** → 审计使用 Membership，速率限制以后考虑

---

## 🔴 高优先级修改（必须做）

### 修改 1: tenant_id 类型统一为 int

**问题**: 当前 tenant_id 在 Pydantic 模型中定义为 `str`，但 MongoDB 存储为 `int`，导致类型转换复杂且容易出错。

**影响文件**:
- `src/models/command.py`
- `src/models/command_set.py`
- `src/core/deps.py`
- `src/routers/command_sets.py`
- `src/routers/tasks.py`
- `src/services/planning_engine.py`
- `src/models/models.py` (如果存在 tenant_id 字段)

**具体修改**:

#### 1.1 修改 `src/models/command.py`

```python
# 修改前
class Command(BaseModel):
    tenant_id: str

# 修改后
class Command(BaseModel):
    tenant_id: int
```

**移除或简化 model_validator**:
```python
# 修改前
@model_validator(mode='before')
@classmethod
def convert_objectid(cls, data: Any) -> Any:
    if isinstance(data, dict):
        if '_id' in data and isinstance(data['_id'], ObjectId):
            data['_id'] = str(data['_id'])
        # Convert tenant_id to string if it's an integer
        if 'tenant_id' in data and isinstance(data['tenant_id'], int):
            data['tenant_id'] = str(data['tenant_id'])
    return data

# 修改后（只保留 ObjectId 转换）
@model_validator(mode='before')
@classmethod
def convert_objectid(cls, data: Any) -> Any:
    if isinstance(data, dict):
        if '_id' in data and isinstance(data['_id'], ObjectId):
            data['_id'] = str(data['_id'])
    return data
```

#### 1.2 修改 `src/models/command_set.py`

```python
# 修改前
class CommandSet(BaseModel):
    tenant_id: str

    @model_validator(mode='before')
    @classmethod
    def convert_objectid(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if '_id' in data and isinstance(data['_id'], ObjectId):
                data['_id'] = str(data['_id'])
            # Convert tenant_id to string if it's an integer
            if 'tenant_id' in data and isinstance(data['tenant_id'], int):
                data['tenant_id'] = str(data['tenant_id'])
        return data

# 修改后
class CommandSet(BaseModel):
    tenant_id: int

    @model_validator(mode='before')
    @classmethod
    def convert_objectid(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if '_id' in data and isinstance(data['_id'], ObjectId):
                data['_id'] = str(data['_id'])
        return data
```

#### 1.3 修改 `src/core/deps.py`

```python
# 修改前
async def get_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")
) -> str:
    if settings.FIXED_TENANT_ID is not None:
        return str(settings.FIXED_TENANT_ID)
    if x_tenant_id:
        return x_tenant_id
    raise HTTPException(...)

# 修改后
async def get_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")
) -> int:
    # 1. 优先检查强制配置
    if settings.FIXED_TENANT_ID is not None:
        return int(settings.FIXED_TENANT_ID)

    # 2. 检查请求头
    if x_tenant_id:
        try:
            return int(x_tenant_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid tenant ID format: '{x_tenant_id}'. Must be an integer."
            )

    # 3. 均未找到，拒绝请求
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Missing 'X-Tenant-ID' header. Please specify the tenant context."
    )
```

#### 1.4 修改 `src/routers/command_sets.py`

**移除所有类型转换代码**:

```python
# 修改前（line 22-28）
tenant_id_int = int(tenant_id) if tenant_id.isdigit() else tenant_id
command_set.tenant_id = str(tenant_id_int)
command_set_dict = command_set.model_dump(by_alias=True, exclude={"id"})
command_set_dict['tenant_id'] = tenant_id_int

# 修改后
command_set.tenant_id = tenant_id  # 已经是 int
command_set_dict = command_set.model_dump(by_alias=True, exclude={"id"})
```

**所有涉及 tenant_id 的查询都直接使用**:
```python
# 修改前
result = await db["command_sets"].delete_one({"_id": ObjectId(set_id), "tenant_id": tenant_id})  # ❌ 类型不匹配
parent_set = await db["command_sets"].find_one({"_id": ObjectId(set_id), "tenant_id": tenant_id})  # ❌ 类型不匹配

# 修改后（直接使用，不需要转换）
result = await db["command_sets"].delete_one({"_id": ObjectId(set_id), "tenant_id": tenant_id})  # ✅
parent_set = await db["command_sets"].find_one({"_id": ObjectId(set_id), "tenant_id": tenant_id})  # ✅
```

**需要修改的地方**:
- Line 23-28 (create_command_set)
- Line 41 (list_command_sets - 移除转换)
- Line 55 (delete_command_set - 直接使用)
- Line 74 (create_command - 直接使用)
- Line 79 (create_command - 直接使用)
- Line 94 (list_commands - 直接使用)
- Line 123 (smart_import - 直接使用)
- Line 200 (smart_import - 直接使用)

#### 1.5 修改 `src/routers/tasks.py`

```python
# 修改前
async def create_task(
    request: TaskRequest,
    tenant_id: str = Depends(get_tenant_id),
    ...
):
    response = await engine.plan_task(request, tenant_id)

# 修改后
async def create_task(
    request: TaskRequest,
    tenant_id: int = Depends(get_tenant_id),
    ...
):
    response = await engine.plan_task(request, tenant_id)
```

#### 1.6 修改 `src/services/planning_engine.py`

```python
# 修改前
async def get_available_commands(self, tenant_id: str, command_set_names: List[str] = None):
    tenant_id_int = int(tenant_id) if tenant_id.isdigit() else tenant_id
    query = {"tenant_id": tenant_id_int}
    ...

async def plan_task(self, request: TaskRequest, tenant_id: str, user_id: str = None):
    ...

def _build_prompt(self, user_goal: str, commands: List[Dict[str, Any]], tenant_id, ...):
    # 大量的类型转换逻辑
    if isinstance(tenant_id, int):
        tenant_id_value = tenant_id
    elif isinstance(tenant_id, str) and tenant_id.isdigit():
        tenant_id_value = int(tenant_id)
    else:
        tenant_id_value = tenant_id

# 修改后
async def get_available_commands(self, tenant_id: int, command_set_names: List[str] = None):
    query = {"tenant_id": tenant_id}  # 直接使用
    ...

async def plan_task(self, request: TaskRequest, tenant_id: int, user_id: str = None):
    ...

def _build_prompt(self, user_goal: str, commands: List[Dict[str, Any]], tenant_id: int, ...):
    # 直接使用，不需要转换
    system_prompt = f"""
    ...
    Current User's Tenant ID: {tenant_id}
    ...
    """
```

**风险点**:
- 数据库中已存在的数据如果 tenant_id 是字符串会有问题
- 需要数据迁移脚本

**测试验证**:
1. 创建新的 command_set，验证 tenant_id 存储为 int
2. 查询现有数据，验证能正确读取
3. 多租户隔离测试

---

### 修改 2: API 密钥安全存储（环境变量 + .env）

**问题**: config.yml 中明文存储 API Key，存在安全风险。

**影响文件**:
- `requirements.txt` (添加依赖)
- `src/core/config.py` (重构)
- `.env` (创建)
- `.gitignore` (更新)
- `config.yml` (清理敏感信息)

**具体修改**:

#### 2.1 添加依赖

```bash
# requirements.txt 添加
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
```

#### 2.2 创建 `.env` 文件

```bash
# .env
OPENAI_API_KEY=sk-503b9d7cd900429c9215027fad9071cc
MONGODB_URI=mongodb://jnuc2
DATABASE_NAME=nl_tps
OPENAI_MODEL_NAME=deepseek-chat
OPENAI_BASE_URL=https://api.deepseek.com/v1
# FIXED_TENANT_ID=  # 生产环境不设置，开发环境可以设置
```

#### 2.3 更新 `.gitignore`

```
# .gitignore 添加
.env
.env.local
.env.*.local
```

#### 2.4 重构 `src/core/config.py`

```python
# 修改前
from typing import Optional
from pydantic import BaseModel

class Settings(BaseModel):
    MONGODB_URI: str
    DATABASE_NAME: str = "nl_tps"
    OPENAI_API_KEY: str
    OPENAI_MODEL_NAME: str = "gpt-4"
    OPENAI_BASE_URL: Optional[str] = None
    FIXED_TENANT_ID: Optional[int] = None

# 从 config.yml 读取...

# 修改后
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # API 配置
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    openai_model_name: str = Field(default="gpt-4", env="OPENAI_MODEL_NAME")

    # 数据库配置
    mongodb_uri: str = Field(..., env="MONGODB_URI")
    database_name: str = Field(default="nl_tps", env="DATABASE_NAME")

    # 租户配置
    fixed_tenant_id: Optional[int] = Field(default=None, env="FIXED_TENANT_ID")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # 忽略额外的环境变量

settings = Settings()
```

**更新所有使用配置的地方**:
```python
# 修改前
from src.core.config import settings
settings.OPENAI_API_KEY

# 修改后（属性名改为小写）
from src.core.config import settings
settings.openai_api_key
```

#### 2.5 清理 `config.yml`

```yaml
# config.yml - 移除敏感信息
backend:
  # mongodb_uri: "mongodb://jnuc2"  # 移除，使用环境变量
  # openai_api_key: "sk-xxx"  # 移除
  # openai_model_name: "deepseek-chat"  # 移除
  # openai_base_url: "https://api.deepseek.com/v1"  # 移除
  # fixed_tenant_id: 1  # 移除，使用环境变量

  # 保留非敏感配置（如果有的话）
  # 或者完全移除此文件，改用 .env
```

**风险点**:
- 需要在所有环境设置环境变量
- 部署时需要配置环境变量注入

**测试验证**:
1. 本地开发环境：从 .env 加载配置
2. 移除 config.yml 后服务能正常启动
3. 所有 API 能正常调用

---

### 修改 3: 修复类型不匹配 Bug（数据查询错误）

**问题**: 部分路由直接用字符串 tenant_id 查询数据库（但数据库中存储为 int）

**影响文件**:
- `src/routers/command_sets.py`

**具体修改**:

已在 **修改 1** 中统一处理，tenant_id 改为 int 后自动修复。

**Bug 位置**:
- Line 55: `delete_one({"tenant_id": tenant_id})` ❌ → ✅ (修改后正确)
- Line 74: `find_one({"tenant_id": tenant_id})` ❌ → ✅ (修改后正确)
- Line 94: `find_one({"tenant_id": tenant_id})` ❌ → ✅ (修改后正确)
- Line 123: `find_one({"tenant_id": tenant_id})` ❌ → ✅ (修改后正确)

---

### 修改 4: Commands 查询优化（添加 limit）

**问题**: 查询所有 commands，如果数量过大可能导致内存和性能问题。

**影响文件**:
- `src/services/planning_engine.py`

**具体修改**:

```python
# 修改前
cursor = self.db["commands"].find(query)
commands = []
async for doc in cursor:
    commands.append(cmd_dict)

# 修改后
cursor = self.db["commands"].find(query).limit(1000)  # 最多查询 1000 条
commands = []
async for doc in cursor:
    commands.append(cmd_dict)
```

**可选优化**（如果需要更智能的筛选）:
```python
# 根据用户目标的关键词筛选 commands
async def get_available_commands(self, tenant_id: int, command_set_names: List[str] = None, keywords: List[str] = None):
    query = {"tenant_id": tenant_id}
    if command_set_names:
        cs_cursor = self.db["command_sets"].find(
            {"tenant_id": tenant_id, "name": {"$in": command_set_names}},
            {"_id": 1}
        )
        cs_ids = [str(doc["_id"]) async for doc in cs_cursor]
        query["command_set_id"] = {"$in": cs_ids}

    # 如果提供了关键词，添加文本搜索
    if keywords:
        query["$or"] = [
            {"command": {"$regex": "|".join(keywords), "$options": "i"}},
            {"summary": {"$regex": "|".join(keywords), "$options": "i"}},
            {"description": {"$regex": "|".join(keywords), "$options": "i"}}
        ]

    cursor = self.db["commands"].find(query).limit(500)  # 降低到 500
    ...
```

**风险点**:
- 如果限制太小，可能过滤掉需要的 commands
- 需要根据实际使用情况调整 limit 值

**测试验证**:
1. 查询少量 commands (< 100)，验证正常
2. 查询大量 commands (> 1000)，验证只返回 limit 数量
3. 验证 LLM 提示词长度合理

---

### 修改 5: 删除重复文件

**问题**: `src/deps.py` 是旧文件，`src/core/deps.py` 是新文件，造成混乱。

**影响文件**:
- `src/deps.py` (删除)

**具体修改**:

```bash
# 检查是否有文件引用了 src.deps
grep -r "from src.deps import" src/
grep -r "from src import deps" src/

# 如果没有引用，直接删除
rm src/deps.py
```

**风险点**:
- 如果有文件还在引用旧路径，会导致导入错误

**测试验证**:
1. 启动服务，验证没有导入错误
2. 运行所有测试（如果有）

---

## 🟡 中优先级修改（应该做）

### 修改 6: 添加基础日志系统

**问题**: 代码中使用 `print` 输出日志，不适合生产环境。

**影响文件**:
- `src/core/config.py` (添加日志配置)
- `src/services/planning_engine.py`
- `src/routers/*.py`
- `requirements.txt` (添加依赖)

**具体修改**:

#### 6.1 添加日志配置

```python
# src/core/config.py 添加
import logging
import sys

class Settings(BaseSettings):
    ...

    # 日志配置
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

def setup_logging(settings: Settings):
    """配置日志系统"""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

# 在应用启动时调用
# src/main.py
from src.core.config import settings, setup_logging

setup_logging(settings)
logger = logging.getLogger(__name__)
logger.info(f"Starting AICMDEngine with log level: {settings.log_level}")
```

#### 6.2 替换 print 为 logging

```python
# src/services/planning_engine.py
# 修改前
except Exception as e:
    print(f"Planning Error: {e}")

# 修改后
import logging
logger = logging.getLogger(__name__)

except Exception as e:
    logger.error(f"Planning failed: {e}", exc_info=True)
```

**在关键位置添加日志**:
```python
# 查询开始
logger.info(f"Loading commands for tenant {tenant_id}")

# LLM 调用
logger.debug(f"Sending request to LLM, prompt length: {len(prompt)}")

# 查询完成
logger.info(f"Loaded {len(commands)} commands for tenant {tenant_id}")
```

**风险点**:
- 无

**测试验证**:
1. 启动服务，观察日志输出
2. 触发错误，验证错误日志正常
3. 调整日志级别，验证不同级别的输出

---

### 修改 7: 添加基础测试

**问题**: 没有任何测试，核心业务逻辑缺乏保障。

**影响文件**:
- `requirements.txt` (添加依赖)
- `tests/` (创建测试目录)
- `tests/test_planning_engine.py` (创建)
- `tests/test_config.py` (创建)
- `pytest.ini` (创建)

**具体修改**:

#### 7.1 添加测试依赖

```bash
# requirements.txt 添加
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
httpx>=0.25.0  # 用于测试 FastAPI
```

#### 7.2 创建测试配置

```ini
# pytest.ini
[pytest]
testpaths = tests
asyncio_mode = auto
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --cov=src
    --cov-report=term-missing
    --cov-report=html
```

#### 7.3 创建测试目录结构

```
tests/
├── __init__.py
├── conftest.py  # pytest fixtures
├── test_planning_engine.py
├── test_command_sets.py
└── test_config.py
```

#### 7.4 创建 fixtures

```python
# tests/conftest.py
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from src.main import app
from src.core.config import settings

@pytest.fixture
async def mongodb():
    """测试数据库连接"""
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.database_name + "_test"]

    yield db

    # 清理
    await client.drop_database(settings.database_name + "_test")
    client.close()

@pytest.fixture
async def test_app(mongodb):
    """测试应用"""
    app.mongodb = mongodb
    return app
```

#### 7.5 创建核心测试

```python
# tests/test_planning_engine.py
import pytest
from src.services.planning_engine import PlanningEngine
from src.models.models import TaskRequest, TaskContext

@pytest.mark.asyncio
async def test_get_available_commands(mongodb):
    """测试命令加载"""
    engine = PlanningEngine(mongodb)

    # 准备测试数据
    await mongodb["command_sets"].insert_one({
        "name": "test_set",
        "tenant_id": 1,
        "version": "1.0.0"
    })

    await mongodb["commands"].insert_many([
        {
            "command": "GET /test",
            "summary": "Test command",
            "tenant_id": 1,
            "command_set_id": "test_set_id",
            "risk_level": "normal"
        }
    ])

    # 执行测试
    commands = await engine.get_available_commands(1, ["test_set"])

    # 验证
    assert len(commands) == 1
    assert commands[0]["command"] == "GET /test"

@pytest.mark.asyncio
async def test_plan_task_basic(mongodb):
    """测试基本任务规划"""
    engine = PlanningEngine(mongodb)

    # 准备测试数据
    ...

    # 执行测试
    request = TaskRequest(
        goal="创建一个用户",
        context=TaskContext(
            tenant_id=1,
            command_set_names=["user_management"]
        )
    )

    response = await engine.plan_task(request, 1)

    # 验证
    assert response.type in ["plan_ready", "clarification_needed"]
    assert 0.0 <= response.confidence <= 1.0
```

**风险点**:
- 需要独立的测试数据库
- 测试数据准备可能比较复杂

**测试验证**:
```bash
# 运行测试
pytest

# 查看覆盖率
pytest --cov=src --cov-report=html
open htmlcov/index.html
```

---

### 修改 8: 清理硬编码配置

**问题**: 检查并移除代码中的硬编码值。

**影响文件**: 待检查

**具体修改**:

先检查硬编码位置:
```bash
# 搜索可能的硬编码
grep -r "localhost" src/
grep -r "8000" src/
grep -r "timeout" src/
grep -r "300\|30\|60" src/  # 可能的超时时间
```

将发现的硬编码移到配置:
```python
# src/core/config.py 添加
class Settings(BaseSettings):
    ...
    # API 配置
    api_timeout: int = Field(default=30, env="API_TIMEOUT")
    api_retry_count: int = Field(default=3, env="API_RETRY_COUNT")
```

**风险点**:
- 无

**测试验证**:
1. 检查所有可能的硬编码位置
2. 验证配置可以正常覆盖

---

### 修改 9: 优化错误处理

**问题**: 错误信息过于简单，用户难以理解问题。

**影响文件**:
- `src/services/planning_engine.py`
- `src/routers/command_sets.py`
- `src/routers/tasks.py`

**具体修改**:

```python
# src/services/planning_engine.py
# 修改前
except json.JSONDecodeError:
     return TaskPlanResponse(
        type="clarification_needed",
        confidence=0.0,
        question="The system failed to generate a valid plan (JSON Error). Please try rephrasing."
    )
except Exception as e:
    print(f"Planning Error: {e}")
    return TaskPlanResponse(
        type="clarification_needed",
        confidence=0.0,
        question=f"An internal error occurred: {str(e)}"
    )

# 修改后
import logging
logger = logging.getLogger(__name__)

except json.JSONDecodeError as e:
    logger.error(f"Failed to parse LLM response as JSON: {e}")
    return TaskPlanResponse(
        type="clarification_needed",
        confidence=0.0,
        question="I couldn't understand the AI response format. This might be due to an unexpected data structure. Please try rephrasing your request or contact support if the issue persists."
    )
except Exception as e:
    logger.error(f"Planning failed unexpectedly: {e}", exc_info=True)
    return TaskPlanResponse(
        type="clarification_needed",
        confidence=0.0,
        question=f"An unexpected error occurred while processing your request. Our team has been notified. Please try again later or contact support with reference: {id(e)}."
    )
```

**为路由添加更详细的错误**:
```python
# src/routers/command_sets.py
@router.post("/{set_id}/import/smart")
async def smart_import_commands(...):
    try:
        ...
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM extraction: {e}")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_response_format",
                "message": "The AI couldn't extract commands in the expected format. Please try a different document or check if the format is supported.",
                "details": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Smart import failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "import_failed",
                "message": "Failed to import commands. Please try again or contact support.",
                "details": str(e) if settings.debug else None
            }
        )
```

**风险点**:
- 错误信息不应暴露敏感信息（如完整堆栈）

**测试验证**:
1. 触发各种错误，验证错误信息友好
2. 验证日志记录正确

---

### 修改 10: 优化 API 文档

**问题**: FastAPI 自带 Swagger，但可能需要优化描述。

**影响文件**:
- `src/routers/command_sets.py`
- `src/routers/tasks.py`
- `src/main.py`

**具体修改**:

#### 10.1 添加路由描述

```python
# src/routers/tasks.py
@router.post(
    "/",
    response_model=TaskPlanResponse,
    summary="Plan a task from natural language",
    description="""
    Convert a user's natural language goal into a step-by-step execution plan.

    **Features**:
    - Multi-turn dialogue support
    - Risk assessment
    - Automatic command mapping

    **Example**:
    - Goal: "Create a new user account"
    - Response: Step-by-step plan with API calls
    """,
    responses={
        200: {"description": "Plan generated successfully"},
        400: {"description": "Invalid request"},
        500: {"description": "Internal server error"}
    }
)
async def create_task(...):
    ...
```

#### 10.2 添加应用元数据

```python
# src/main.py
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="AICMDEngine API",
    description="""
    AI-powered Command Engine for Natural Language Task Planning

    ## Features
    * **NL-TPS**: Natural Language Task Planning Service
    * **Smart Import**: Import commands from OpenAPI specs or documentation
    * **Multi-tenant**: Support for multiple tenants

    ## Authentication
    All endpoints require `X-Tenant-ID` header.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="AICMDEngine API",
        version="1.0.0",
        description="AI-powered Command Engine",
        routes=app.routes,
    )
    # 添加认证信息
    openapi_schema["components"]["securitySchemes"] = {
        "tenantIdHeader": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Tenant-ID",
            "description": "Tenant ID for multi-tenancy"
        }
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
```

**风险点**:
- 无

**测试验证**:
1. 访问 `http://localhost:8000/docs`，验证文档正常
2. 检查每个路由的描述是否清晰
3. 验证示例是否正确

---

## 🟢 低优先级修改（可以做）

### 修改 11: 性能优化（缓存）

**说明**: 当前优先级较低，可以先观察实际使用情况再决定。

**影响文件**:
- `src/services/planning_engine.py`
- `requirements.txt` (可选：Redis)

**可选方案**:

#### 方案 A: 内存缓存（简单）

```python
from cachetools import TTLCache

class PlanningEngine:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.commands_cache = TTLCache(maxsize=100, ttl=3600)  # 1小时

    async def get_available_commands(self, tenant_id: int, command_set_names: List[str] = None):
        cache_key = f"{tenant_id}:{','.join(command_set_names or [])}"

        # 尝试从缓存获取
        if cache_key in self.commands_cache:
            return self.commands_cache[cache_key]

        # 从数据库查询
        commands = await self._load_commands_from_db(tenant_id, command_set_names)

        # 存入缓存
        self.commands_cache[cache_key] = commands
        return commands
```

#### 方案 B: Redis 缓存（生产环境）

```python
import aioredis

class PlanningEngine:
    def __init__(self, db: AsyncIOMotorDatabase, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def get_available_commands(self, tenant_id: int, command_set_names: List[str] = None):
        cache_key = f"commands:{tenant_id}:{','.join(command_set_names or [])}"

        # 尝试从 Redis 获取
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)

        # 从数据库查询
        commands = await self._load_commands_from_db(tenant_id, command_set_names)

        # 存入 Redis
        await self.redis.setex(cache_key, 3600, json.dumps(commands))
        return commands
```

**测试验证**:
1. 第一次请求查询数据库
2. 第二次请求命中缓存
3. 缓存过期后重新查询

---

## 📝 实施顺序建议

### 阶段 1: 修复关键 Bug（必须）
1. 修改 1: tenant_id 类型统一
2. 修改 3: 修复类型不匹配 Bug（包含在修改 1 中）
3. 修改 5: 删除重复文件

### 阶段 2: 安全性改进（必须）
4. 修改 2: API 密钥安全存储
5. 修改 4: Commands 查询优化

### 阶段 3: 可维护性提升（应该）
6. 修改 6: 添加基础日志系统
7. 修改 7: 添加基础测试
8. 修改 8: 清理硬编码配置
9. 修改 9: 优化错误处理
10. 修改 10: 优化 API 文档

### 阶段 4: 性能优化（可选）
11. 修改 11: 性能优化（缓存）

---

## ⚠️ 风险评估

### 高风险项
- **tenant_id 类型统一**: 涉及数据迁移，需要仔细测试
- **配置系统重构**: 影响所有模块，需要全面测试

### 中风险项
- **日志系统引入**: 可能影响性能
- **测试框架添加**: 需要准备测试数据

### 低风险项
- **删除重复文件**: 简单清理
- **API 文档优化**: 只修改文档字符串
- **错误处理优化**: 只影响错误场景

---

## 🧪 测试策略

### 单元测试
- `PlanningEngine` 核心逻辑
- 配置加载
- 类型转换

### 集成测试
- API 端到端测试
- 多租户隔离测试
- LLM 调用测试

### 回归测试
- 每个阶段完成后运行完整测试套件
- 确保没有引入新的 Bug

---

## 📊 预期收益

### 立即收益
- ✅ 修复类型不匹配 Bug（查询错误）
- ✅ 提升安全性（API 密钥保护）
- ✅ 简化代码（移除类型转换）

### 短期收益（1-2周）
- ✅ 更好的可维护性（日志、测试）
- ✅ 更友好的错误提示
- ✅ 完整的 API 文档

### 长期收益
- ✅ 更容易添加新功能
- ✅ 更少的 Bug
- ✅ 更好的性能（如果实施缓存）

---

## ✅ 审核清单

在开始实施前，请确认：

- [ ] 所有决策都已确认
- [ ] 备份当前代码（创建新分支）
- [ ] 准备测试环境
- [ ] 通知团队成员（如果有的话）
- [ ] 预留足够的时间（估计 2-3 天）

---

**下一步**: 审查此计划，确认无误后开始实施。
