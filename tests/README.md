# Testing Guide

## 运行测试

### 安装测试依赖

```bash
pip install -r requirements.txt
```

### 运行所有测试

```bash
pytest
```

### 运行特定测试文件

```bash
pytest tests/test_config.py
pytest tests/test_planning_engine.py
```

### 运行特定测试

```bash
pytest tests/test_config.py::TestSettings::test_settings_creation
```

### 查看测试覆盖率

```bash
pytest --cov=src --cov-report=html
open htmlcov/index.html  # macOS
```

### 运行测试并显示详细输出

```bash
pytest -v
```

### 运行测试但不运行慢速测试

```bash
pytest -m "not slow"
```

## 测试结构

```
tests/
├── __init__.py
├── conftest.py           # Pytest fixtures
├── test_config.py        # Configuration tests
├── test_planning_engine.py  # Core business logic tests
└── README.md            # This file
```

## 编写测试

### 创建新的测试文件

1. 在 `tests/` 目录下创建 `test_<module>.py`
2. 导入必要的模块和 fixtures
3. 创建测试类或测试函数

### 示例

```python
import pytest
from src.services.my_service import MyService

class TestMyService:
    @pytest.mark.asyncio
    async def test_my_function(self, test_db):
        service = MyService(test_db)
        result = await service.my_function()
        assert result is not None
```

### 使用 Fixtures

可用的 fixtures（在 conftest.py 中定义）：

- `test_db`: 测试数据库连接
- `test_app`: FastAPI 测试应用
- `sample_command_set`: 示例命令集数据
- `sample_commands`: 示例命令数据
- `populated_test_db`: 包含示例数据的测试数据库

### 标记测试

```python
@pytest.mark.slow
async def test_slow_operation():
    ...

@pytest.mark.integration
async def test_integration():
    ...
```

## 注意事项

1. **测试数据库**: 测试使用独立的数据库（`{DATABASE_NAME}_test`），不会影响生产数据
2. **LLM 调用**: 涉及 LLM 调用的测试应该被标记为 `integration` 或使用 mock
3. **异步测试**: 使用 `@pytest.mark.asyncio` 装饰器
4. **清理**: 每个 test 函数后，fixtures 会自动清理测试数据

## 持续集成

在 CI/CD 环境中运行：

```bash
# 设置环境变量
export MONGODB_URI="mongodb://localhost:27017"
export OPENAI_API_KEY="test_key"

# 运行测试
pytest --cov=src --cov-report=xml
```
