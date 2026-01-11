# LLM提供商管理策略 - 详细设计

**状态**: 设计文档
**日期**: 2026-01-09
**基础**: OpenAI兼容接口标准
**关键决策**: Phase 1实现多LLM支持框架

---

## 用户需求确认

### 当前支持
- ✅ **GPT-5** (OpenAI)
- ✅ **DeepSeek v3.2** (OpenAI兼容)

### 未来扩展计划
- ⏳ **Qwen** (阿里, OpenAI兼容)
- ⏳ **Kimi** (Moonshot, OpenAI兼容)
- ⏳ **GLM 4.7** (智谱, OpenAI兼容)
- ⏳ **开源模型自部署** (Llama/Mistral等)

### 不考虑的标准
- ❌ **Claude API** (不同标准,暂不支持)
- ❌ **Gemini** (不同标准,暂不支持)

### 核心需求
- ✅ **OpenAI兼容接口** (标准化)
- ✅ **多LLM并行管理** (可配置)
- ✅ **动态选择** (运行时决策)
- ✅ **成本区分** (不同场景用不同模型)
- ✅ **MCP双向交互** (MCP ↔ LLM)

---

## 架构设计

### 整体系统架构

```
┌─────────────────────────────────────────────────┐
│         Task Planning Engine                    │
│  (使用LLM生成计划,调用MCP执行)                 │
└────────┬────────────────────────────────────────┘
         │
    ┌────┴─────────────────────────────┐
    │                                  │
┌───▼────────────────┐         ┌──────▼──────────┐
│   LLM Provider     │         │  MCP Cluster    │
│   Manager          │         │  (Execution)    │
└───┬────────────────┘         └─────┬───────────┘
    │                                │
    │ Manages:                       │
    ├─ Provider Registry            │ Executes:
    ├─ Model Selection              ├─ Membership
    ├─ Configuration                ├─ Orders
    ├─ Fallback Strategy            ├─ Billing
    └─ Cost Tracking                └─ ...

    │                                │
    ▼                                ▼
┌─────────────┬──────────────┬─────────────┐
│   GPT-5     │  DeepSeek    │   Qwen      │
│  (OpenAI)   │  (OpenAI     │  (OpenAI    │
│             │   compatible)│   compatible)
└─────────────┴──────────────┴─────────────┘
```

### LLM Provider Manager - 详细设计

```python
# src/llm/provider_manager.py

class LLMProviderManager:
    """
    统一管理多个LLM提供商
    - 支持OpenAI兼容接口
    - 动态提供商配置
    - 自动降级和切换
    """

    def __init__(self, config: dict):
        """
        初始化提供商管理器

        config示例:
        {
            "providers": {
                "openai": {
                    "type": "openai_compatible",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-...",
                    "models": ["gpt-5"],
                    "cost_per_1k_tokens": 0.003,  # $0.003/1K tokens
                    "priority": 1,
                    "enabled": True
                },
                "deepseek": {
                    "type": "openai_compatible",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-...",
                    "models": ["deepseek-v3.2"],
                    "cost_per_1k_tokens": 0.0001,
                    "priority": 2,
                    "enabled": True
                },
                "qwen": {
                    "type": "openai_compatible",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "sk-...",
                    "models": ["qwen-plus"],
                    "cost_per_1k_tokens": 0.0005,
                    "priority": 3,
                    "enabled": False  # 未来启用
                },
                "local": {
                    "type": "openai_compatible",
                    "base_url": "http://localhost:8000/v1",  # 自部署vLLM
                    "api_key": "local",
                    "models": ["llama-2-70b"],
                    "cost_per_1k_tokens": 0.0,  # 本地成本
                    "priority": 4,
                    "enabled": False  # 未来启用
                }
            },
            "default_provider": "openai",
            "fallback_strategy": "priority"  # priority / round_robin / cost_aware
        }
        """
        self.config = config
        self.providers = {}
        self._init_providers()

    def _init_providers(self):
        """初始化所有提供商"""
        for name, provider_config in self.config["providers"].items():
            if provider_config.get("enabled", True):
                self.providers[name] = self._create_provider(
                    name, provider_config
                )

    def select_provider(self, task_type: str, **constraints) -> "LLMProvider":
        """
        选择合适的LLM提供商

        策略:
        1. 成本优先: 用最便宜的能完成任务的
        2. 质量优先: 用最好的模型
        3. 延迟优先: 用最快的
        4. 平衡: 根据任务权衡
        """

        # 根据任务类型选择
        task_config = self.config.get("task_strategies", {}).get(
            task_type, {}
        )

        preferred_provider = task_config.get("provider")
        if preferred_provider and preferred_provider in self.providers:
            return self.providers[preferred_provider]

        # 降级到成本最低的
        return self._select_by_priority(**constraints)

    def _select_by_priority(self, **constraints) -> "LLMProvider":
        """按优先级选择 (默认策略)"""
        sorted_providers = sorted(
            self.providers.items(),
            key=lambda x: x[1].priority
        )

        for name, provider in sorted_providers:
            if self._check_constraints(provider, constraints):
                return provider

        raise RuntimeError("No available LLM provider")

    def _check_constraints(self, provider, constraints):
        """检查提供商是否满足约束"""
        # 成本约束
        if "max_cost" in constraints:
            if provider.cost_per_1k_tokens > constraints["max_cost"]:
                return False

        # 质量约束
        if "min_quality" in constraints:
            if provider.quality_score < constraints["min_quality"]:
                return False

        # 隐私约束 (本地优先)
        if constraints.get("require_local", False):
            if not provider.is_local:
                return False

        return True

    async def call_llm(
        self,
        prompt: str,
        task_type: str = "general",
        **kwargs
    ) -> str:
        """
        调用LLM并自动选择提供商

        支持降级: 如果选中提供商失败,自动尝试备选
        """

        provider = self.select_provider(task_type, **kwargs.get("constraints", {}))

        try:
            response = await provider.call(prompt, **kwargs)
            self._track_usage(provider.name, response.usage)
            return response.content

        except Exception as e:
            logger.error(f"Provider {provider.name} failed: {e}")
            # 尝试备选提供商
            alternative = self._get_fallback_provider(provider.name)
            if alternative:
                logger.warn(f"Falling back to {alternative.name}")
                return await alternative.call(prompt, **kwargs)
            raise

    def _track_usage(self, provider_name: str, usage: dict):
        """追踪使用情况和成本"""
        provider = self.providers[provider_name]
        tokens = usage.get("total_tokens", 0)
        cost = tokens / 1000 * provider.cost_per_1k_tokens

        # 记录到数据库
        log_entry = {
            "provider": provider_name,
            "tokens": tokens,
            "cost": cost,
            "timestamp": datetime.now()
        }
        # 保存到MongoDB或其他存储
```

### MCP与LLM的双向交互

```
┌─────────────────────────────────────────┐
│  Task Planning Engine (用LLM规划)        │
└────────┬────────────────────────────────┘
         │
         │ 1. 生成执行计划
         ▼
    ┌─────────────────┐
    │  LLM Provider   │  (选择合适的提供商)
    │  Manager        │
    └────────┬────────┘
             │
             │ 2. 返回计划
             │ (Step 1: GET /api/v1/members
             │  Step 2: DELETE /api/v1/members/{id})
             ▼
    ┌────────────────────────────┐
    │   MCP Cluster             │
    │   - Membership MCP        │
    │   - Orders MCP           │
    │   - Billing MCP          │
    └────┬──────────────────────┘
         │
         │ 3. 执行步骤并返回结果
         │ (Step 1 Response: {data: [{id: 123}]})
         ▼
    ┌─────────────────────────────┐
    │   LLM Provider Manager      │
    │   (分析响应结构)            │
    └────────┬────────────────────┘
             │
             │ 4. 响应分析与调整
             │ (JSONPath: $.data[0].id)
             ▼
    ┌──────────────────────────────┐
    │  Task Planning Engine        │
    │  (下一步决策或修正)          │
    └──────────────────────────────┘

双向流:
LLM → MCP: 生成计划,执行命令
MCP → LLM: 返回结果,用于分析和迭代
```

---

## OpenAI兼容接口标准

### 统一API接口

```python
# 所有提供商都兼容这个接口

async def call_llm_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict],
    temperature: float = 0.7,
    max_tokens: int = 2048
) -> Dict:
    """
    OpenAI兼容接口调用

    这个接口对所有提供商都适用:
    - OpenAI (GPT-5)
    - DeepSeek (v3.2)
    - Qwen (阿里)
    - Kimi (Moonshot)
    - GLM (智谱)
    - 开源自部署 (vLLM)
    """

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 1.0
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload
        )

    result = response.json()
    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": result["usage"]
    }
```

### 配置管理方案：MongoDB + YAML + .env

支持两种配置方式：

#### 方式1：MongoDB管理（推荐用于生产）

所有LLM提供商配置存储在MongoDB，通过Web UI管理：

```javascript
// MongoDB: llm_providers collection

db.llm_providers.insertOne({
  _id: ObjectId(),
  name: "openai",
  type: "openai_compatible",
  base_url: "https://api.openai.com/v1",
  model: "gpt-5",
  api_key_ref: "OPENAI_API_KEY",  // 引用.env中的KEY

  // 常用参数
  timeout: 30,
  temperature: 0.7,
  max_tokens: 2048,
  top_p: 1.0,

  // 成本追踪
  cost_per_1k_tokens: 0.003,

  // 管理参数
  priority: 1,
  enabled: true,
  created_at: ISODate(),
  updated_at: ISODate(),

  // 元数据
  metadata: {
    provider_name: "OpenAI",
    region: "Global",
    max_qps: 3500,
    description: "GPT-5 from OpenAI"
  }
})
```

#### 方式2：YAML配置文件（开发环境）

```yaml
# config/llm_providers.yaml

providers:
  openai:
    type: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-5
    api_key_ref: OPENAI_API_KEY

    # 通用参数
    timeout: 30
    temperature: 0.7
    max_tokens: 2048
    top_p: 1.0

    # 成本追踪
    cost_per_1k_tokens: 0.003
    priority: 1
    enabled: true

    metadata:
      provider_name: "OpenAI"
      region: "Global"
      max_qps: 3500

  deepseek:
    type: openai_compatible
    base_url: https://api.deepseek.com/v1
    model: deepseek-v3.2
    api_key_ref: DEEPSEEK_API_KEY

    timeout: 30
    temperature: 0.7
    max_tokens: 2048
    top_p: 1.0

    cost_per_1k_tokens: 0.0001
    priority: 2
    enabled: true

    metadata:
      provider_name: "DeepSeek"
      region: "China"
      max_qps: 2000

  qwen:
    type: openai_compatible
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    model: qwen-plus
    api_key_ref: QWEN_API_KEY

    timeout: 30
    temperature: 0.7
    max_tokens: 2048

    cost_per_1k_tokens: 0.0005
    priority: 3
    enabled: false

    metadata:
      provider_name: "Alibaba Qwen"
      region: "China"

  kimi:
    type: openai_compatible
    base_url: https://api.moonshot.cn/openai/v1
    model: moonshot-v1-128k
    api_key_ref: KIMI_API_KEY

    timeout: 30
    temperature: 0.7
    max_tokens: 2048

    cost_per_1k_tokens: 0.0002
    priority: 4
    enabled: false

    metadata:
      provider_name: "Moonshot Kimi"
      region: "China"

  glm:
    type: openai_compatible
    base_url: https://open.bigmodel.cn/api/paas/v4
    model: glm-4.7
    api_key_ref: GLM_API_KEY

    timeout: 30
    temperature: 0.7
    max_tokens: 2048

    cost_per_1k_tokens: 0.0003
    priority: 5
    enabled: false

    metadata:
      provider_name: "Zhipu GLM"
      region: "China"

  local:
    type: openai_compatible
    base_url: http://localhost:8000/v1
    model: llama-2-70b
    api_key_ref: LOCAL_API_KEY

    timeout: 60
    temperature: 0.7
    max_tokens: 4096

    cost_per_1k_tokens: 0.0
    priority: 6
    enabled: false

    metadata:
      provider_name: "Local Deployment"
      region: "Local"
      hardware: "GPU 4x A100"

# 全局设置
default_provider: openai
fallback_strategy: priority
max_retries: 3
cost_tracking_enabled: true
cost_budget_per_day: 1000
```

#### Token管理：.env 文件

```bash
# .env

# OpenAI
OPENAI_API_KEY=sk-...

# DeepSeek
DEEPSEEK_API_KEY=sk-...

# Qwen
QWEN_API_KEY=sk-...

# Kimi
KIMI_API_KEY=sk-...

# GLM
GLM_API_KEY=...

# Local
LOCAL_API_KEY=local
```

### 配置加载器实现

```python
# src/llm/config_loader.py

class LLMConfigLoader:
    """支持MongoDB和YAML两种配置"""

    def __init__(self, use_mongodb=True):
        self.use_mongodb = use_mongodb

    async def load_providers(self) -> Dict[str, LLMProvider]:
        """加载所有LLM提供商配置"""

        if self.use_mongodb:
            return await self._load_from_mongodb()
        else:
            return self._load_from_yaml()

    async def _load_from_mongodb(self) -> Dict[str, LLMProvider]:
        """从MongoDB加载提供商配置"""

        db = get_mongodb()
        collection = db.llm_providers

        providers = {}

        # 查询所有启用的提供商
        cursor = collection.find({"enabled": True})

        async for doc in cursor:
            provider = LLMProvider(
                name=doc["name"],
                type=doc["type"],
                base_url=doc["base_url"],
                model=doc["model"],
                api_key=os.getenv(doc["api_key_ref"]),  # 从.env读取
                timeout=doc.get("timeout", 30),
                temperature=doc.get("temperature", 0.7),
                max_tokens=doc.get("max_tokens", 2048),
                cost_per_1k_tokens=doc.get("cost_per_1k_tokens", 0),
                priority=doc.get("priority", 999),
                metadata=doc.get("metadata", {})
            )
            providers[doc["name"]] = provider

        return providers

    def _load_from_yaml(self) -> Dict[str, LLMProvider]:
        """从YAML文件加载提供商配置"""

        with open("config/llm_providers.yaml", "r") as f:
            config = yaml.safe_load(f)

        providers = {}

        for name, provider_config in config["providers"].items():
            if not provider_config.get("enabled", True):
                continue

            provider = LLMProvider(
                name=name,
                type=provider_config["type"],
                base_url=provider_config["base_url"],
                model=provider_config["model"],
                api_key=os.getenv(provider_config["api_key_ref"]),
                timeout=provider_config.get("timeout", 30),
                temperature=provider_config.get("temperature", 0.7),
                max_tokens=provider_config.get("max_tokens", 2048),
                cost_per_1k_tokens=provider_config.get("cost_per_1k_tokens", 0),
                priority=provider_config.get("priority", 999),
                metadata=provider_config.get("metadata", {})
            )
            providers[name] = provider

        return providers

    async def update_provider(self, name: str, updates: dict):
        """更新MongoDB中的提供商配置"""

        db = get_mongodb()
        collection = db.llm_providers

        await collection.update_one(
            {"name": name},
            {
                "$set": {
                    **updates,
                    "updated_at": datetime.utcnow()
                }
            }
        )

    async def add_provider(self, provider_config: dict):
        """添加新的LLM提供商"""

        db = get_mongodb()
        collection = db.llm_providers

        provider_config["created_at"] = datetime.utcnow()
        provider_config["updated_at"] = datetime.utcnow()

        result = await collection.insert_one(provider_config)
        return result.inserted_id

    async def delete_provider(self, name: str):
        """删除LLM提供商"""

        db = get_mongodb()
        collection = db.llm_providers

        await collection.delete_one({"name": name})
```

---

### Web UI 管理接口

FastAPI后端API：

```python
# src/api/routes/llm_providers.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/llm", tags=["LLM Providers"])

class LLMProviderSchema(BaseModel):
    name: str
    type: str
    base_url: str
    model: str
    api_key_ref: str
    timeout: int = 30
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 1.0
    cost_per_1k_tokens: float = 0.0
    priority: int = 999
    enabled: bool = True
    metadata: dict = {}

@router.get("/providers")
async def list_providers(db=Depends(get_mongodb)):
    """获取所有LLM提供商"""
    collection = db.llm_providers
    providers = await collection.find().to_list(None)
    # 不返回api_key_ref,只返回配置
    return [
        {
            **provider,
            "_id": str(provider["_id"])
        }
        for provider in providers
    ]

@router.post("/providers")
async def create_provider(provider: LLMProviderSchema, db=Depends(get_mongodb)):
    """创建新的LLM提供商"""
    collection = db.llm_providers

    # 检查名称唯一性
    existing = await collection.find_one({"name": provider.name})
    if existing:
        raise HTTPException(status_code=400, detail="Provider already exists")

    provider_dict = provider.dict()
    provider_dict["created_at"] = datetime.utcnow()
    provider_dict["updated_at"] = datetime.utcnow()

    result = await collection.insert_one(provider_dict)
    return {"id": str(result.inserted_id), **provider_dict}

@router.put("/providers/{name}")
async def update_provider(
    name: str,
    updates: LLMProviderSchema,
    db=Depends(get_mongodb)
):
    """更新LLM提供商配置"""
    collection = db.llm_providers

    update_dict = updates.dict()
    update_dict["updated_at"] = datetime.utcnow()

    result = await collection.update_one(
        {"name": name},
        {"$set": update_dict}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Provider not found")

    return {"updated": True, **update_dict}

@router.delete("/providers/{name}")
async def delete_provider(name: str, db=Depends(get_mongodb)):
    """删除LLM提供商"""
    collection = db.llm_providers

    result = await collection.delete_one({"name": name})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Provider not found")

    return {"deleted": True}

@router.post("/providers/{name}/test")
async def test_provider(name: str, db=Depends(get_mongodb)):
    """测试LLM提供商连接"""
    collection = db.llm_providers
    provider_doc = await collection.find_one({"name": name})

    if not provider_doc:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        # 获取API Key
        api_key = os.getenv(provider_doc["api_key_ref"])
        if not api_key:
            return {
                "success": False,
                "error": f"API Key not found: {provider_doc['api_key_ref']}"
            }

        # 发送测试请求
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": provider_doc["model"],
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 10
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{provider_doc['base_url']}/chat/completions",
                headers=headers,
                json=payload,
                timeout=provider_doc.get("timeout", 30)
            )

        if response.status_code == 200:
            return {
                "success": True,
                "provider": name,
                "response_time": response.elapsed.total_seconds()
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@router.get("/providers/{name}/select")
async def select_provider(
    name: str,
    db=Depends(get_mongodb)
):
    """选择指定的LLM提供商作为当前使用的提供商"""
    collection = db.llm_providers

    provider = await collection.find_one({"name": name})
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # 更新为当前选中的提供商
    # 这可以存储在应用配置或缓存中
    return {
        "selected": name,
        "provider": {
            "name": provider["name"],
            "model": provider["model"],
            "provider_name": provider.get("metadata", {}).get("provider_name")
        }
    }
```

前端UI（React示例）：

```jsx
// components/LLMProviderManager.jsx

import React, { useState, useEffect } from 'react';
import axios from 'axios';

export function LLMProviderManager() {
  const [providers, setProviders] = useState([]);
  const [selectedProvider, setSelectedProvider] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    type: 'openai_compatible',
    base_url: '',
    model: '',
    api_key_ref: '',
    timeout: 30,
    temperature: 0.7,
    max_tokens: 2048,
    cost_per_1k_tokens: 0,
    priority: 999,
    enabled: true
  });

  // 加载所有提供商
  useEffect(() => {
    fetchProviders();
  }, []);

  const fetchProviders = async () => {
    try {
      const response = await axios.get('/api/llm/providers');
      setProviders(response.data);
    } catch (error) {
      console.error('Failed to load providers:', error);
    }
  };

  // 创建新提供商
  const handleCreate = async () => {
    try {
      await axios.post('/api/llm/providers', formData);
      fetchProviders();
      setShowForm(false);
      resetForm();
    } catch (error) {
      console.error('Failed to create provider:', error);
    }
  };

  // 更新提供商
  const handleUpdate = async (name) => {
    try {
      await axios.put(`/api/llm/providers/${name}`, formData);
      fetchProviders();
      setShowForm(false);
      resetForm();
    } catch (error) {
      console.error('Failed to update provider:', error);
    }
  };

  // 删除提供商
  const handleDelete = async (name) => {
    if (window.confirm(`Delete provider "${name}"?`)) {
      try {
        await axios.delete(`/api/llm/providers/${name}`);
        fetchProviders();
      } catch (error) {
        console.error('Failed to delete provider:', error);
      }
    }
  };

  // 测试提供商
  const handleTest = async (name) => {
    try {
      const response = await axios.post(`/api/llm/providers/${name}/test`);
      if (response.data.success) {
        alert(`✓ Provider ${name} is working (${response.data.response_time.toFixed(2)}s)`);
      } else {
        alert(`✗ Provider ${name} failed: ${response.data.error}`);
      }
    } catch (error) {
      console.error('Test failed:', error);
    }
  };

  // 选择提供商
  const handleSelect = async (name) => {
    try {
      await axios.get(`/api/llm/providers/${name}/select`);
      setSelectedProvider(name);
    } catch (error) {
      console.error('Failed to select provider:', error);
    }
  };

  const resetForm = () => {
    setFormData({
      name: '',
      type: 'openai_compatible',
      base_url: '',
      model: '',
      api_key_ref: '',
      timeout: 30,
      temperature: 0.7,
      max_tokens: 2048,
      cost_per_1k_tokens: 0,
      priority: 999,
      enabled: true
    });
  };

  return (
    <div className="llm-provider-manager">
      <h2>LLM Provider Management</h2>

      {/* 提供商列表 */}
      <div className="provider-list">
        {providers.map((provider) => (
          <div key={provider.name} className="provider-card">
            <div className="provider-header">
              <h3>{provider.name}</h3>
              {selectedProvider === provider.name && <span className="badge">Selected</span>}
              {!provider.enabled && <span className="badge disabled">Disabled</span>}
            </div>

            <div className="provider-info">
              <p><strong>Model:</strong> {provider.model}</p>
              <p><strong>Base URL:</strong> {provider.base_url}</p>
              <p><strong>Timeout:</strong> {provider.timeout}s</p>
              <p><strong>Temperature:</strong> {provider.temperature}</p>
              <p><strong>Cost:</strong> ${provider.cost_per_1k_tokens}/1K tokens</p>
            </div>

            <div className="provider-actions">
              <button onClick={() => handleTest(provider.name)}>Test</button>
              <button onClick={() => handleSelect(provider.name)}>Select</button>
              <button onClick={() => {
                setFormData(provider);
                setShowForm(true);
              }}>Edit</button>
              <button onClick={() => handleDelete(provider.name)} className="btn-danger">Delete</button>
            </div>
          </div>
        ))}
      </div>

      {/* 新建/编辑表单 */}
      {showForm && (
        <div className="provider-form">
          <h3>{formData._id ? 'Edit Provider' : 'New Provider'}</h3>

          <div className="form-group">
            <label>Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({...formData, name: e.target.value})}
            />
          </div>

          <div className="form-group">
            <label>Base URL</label>
            <input
              type="text"
              value={formData.base_url}
              onChange={(e) => setFormData({...formData, base_url: e.target.value})}
            />
          </div>

          <div className="form-group">
            <label>Model</label>
            <input
              type="text"
              value={formData.model}
              onChange={(e) => setFormData({...formData, model: e.target.value})}
            />
          </div>

          <div className="form-group">
            <label>API Key Reference (env var)</label>
            <input
              type="text"
              value={formData.api_key_ref}
              onChange={(e) => setFormData({...formData, api_key_ref: e.target.value})}
              placeholder="e.g., OPENAI_API_KEY"
            />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Timeout (seconds)</label>
              <input
                type="number"
                value={formData.timeout}
                onChange={(e) => setFormData({...formData, timeout: parseInt(e.target.value)})}
              />
            </div>

            <div className="form-group">
              <label>Temperature</label>
              <input
                type="number"
                step="0.1"
                value={formData.temperature}
                onChange={(e) => setFormData({...formData, temperature: parseFloat(e.target.value)})}
              />
            </div>
          </div>

          <div className="form-group">
            <label>
              <input
                type="checkbox"
                checked={formData.enabled}
                onChange={(e) => setFormData({...formData, enabled: e.target.checked})}
              />
              Enabled
            </label>
          </div>

          <div className="form-actions">
            <button onClick={() => formData._id ? handleUpdate(formData.name) : handleCreate()} className="btn-primary">
              {formData._id ? 'Update' : 'Create'}
            </button>
            <button onClick={() => {
              setShowForm(false);
              resetForm();
            }}>Cancel</button>
          </div>
        </div>
      )}

      {!showForm && (
        <button onClick={() => setShowForm(true)} className="btn-primary btn-large">
          + Add Provider
        </button>
      )}
    </div>
  );
}
```

## Phase 1实施方案

### 任务分解

```
Phase 1 (Week 1): 建立LLM Provider Manager框架

1.1 设计和实现LLMProviderManager类
   - [ ] Provider注册机制
   - [ ] 配置加载和验证
   - [ ] OpenAI兼容接口调用
   - 时间: 1天

1.2 实现提供商选择逻辑
   - [ ] 优先级策略
   - [ ] 成本感知选择
   - [ ] 约束验证
   - 时间: 0.5天

1.3 实现降级和故障转移
   - [ ] 失败自动重试
   - [ ] 提供商切换
   - [ ] 错误处理
   - 时间: 0.5天

1.4 成本追踪和监控
   - [ ] Token使用记录
   - [ ] 成本计算
   - [ ] MongoDB存储
   - 时间: 0.5天

1.5 集成测试
   - [ ] 单元测试
   - [ ] 集成测试
   - [ ] 故障场景测试
   - 时间: 1天

总计: 3.5天 (在Phase 1的3-4天内完成)
```

### 与Membership MCP集成

```python
# mcp_servers/membership_mcp.py

class MembershipMCPServer(BaseMCPServer):
    def __init__(self, llm_manager: LLMProviderManager):
        self.llm_manager = llm_manager
        self.spec = load_from_mongodb("membership")

    async def analyze_response(self, response, field_needed=None):
        """使用LLM分析响应结构"""

        # 生成提示
        prompt = f"""
        API响应:
        {json.dumps(response, indent=2)}

        需要提取的字段: {field_needed}

        请建议正确的JSONPath表达式
        """

        # 调用LLM (自动选择提供商)
        suggestion = await self.llm_manager.call_llm(
            prompt=prompt,
            task_type="analyze_response",
            constraints={"max_cost": 0.0005}
        )

        return suggestion

    async def execute_command(self, cmd, params, auth):
        """执行命令,可能需要LLM辅助"""

        try:
            result = await self.http_client.execute(cmd, params, auth)

            # 如果有问题,用LLM辅助诊断
            if not result.get("success"):
                diagnosis = await self.llm_manager.call_llm(
                    prompt=f"诊断这个API错误: {result}",
                    task_type="diagnose_error"
                )
                logger.warn(f"Error diagnosis: {diagnosis}")

            return result

        except Exception as e:
            # 用LLM尝试理解错误
            error_analysis = await self.llm_manager.call_llm(
                prompt=f"分析这个异常: {str(e)}",
                task_type="analyze_error"
            )
            raise
```

---

## 成本优化策略

### 按任务类型选择模型

```python
# 成本矩阵
COST_MATRIX = {
    "complex_planning": {
        "model": "gpt-5",
        "cost": "~$0.05",
        "frequency": "少",
        "total_monthly": "$10-50"
    },
    "response_analysis": {
        "model": "deepseek-v3.2",
        "cost": "~$0.001",
        "frequency": "每个API调用",
        "total_monthly": "$50-100"
    },
    "error_diagnosis": {
        "model": "qwen-plus",
        "cost": "~$0.0005",
        "frequency": "偶发",
        "total_monthly": "$10-20"
    },
    "simple_extraction": {
        "model": "local",
        "cost": "$0",
        "frequency": "高",
        "total_monthly": "$0"
    }
}

# 预期成本
# 高端需求 (GPT-5): $50-200/月
# 中端需求 (DeepSeek): $50-100/月
# 成本优化 (Qwen/Local): $0-50/月
```

### 预算告警机制

```python
class CostMonitor:
    def __init__(self, daily_budget=1000, monthly_budget=20000):
        self.daily_budget = daily_budget
        self.monthly_budget = monthly_budget
        self.daily_spent = 0
        self.monthly_spent = 0

    async def track_usage(self, provider, tokens):
        cost = tokens / 1000 * provider.cost_per_1k_tokens
        self.daily_spent += cost
        self.monthly_spent += cost

        # 日预算告警
        if self.daily_spent > self.daily_budget:
            logger.error(f"Daily budget exceeded: ${self.daily_spent:.2f}")
            # 触发成本优化策略
            await self.enable_cost_optimization()

        # 月预算告警
        if self.monthly_spent > self.monthly_budget * 0.8:
            logger.warn(f"Monthly budget 80% used: ${self.monthly_spent:.2f}")
```

---

## 未来扩展计划

### Phase 2: 多提供商支持
```
- [ ] 启用Qwen支持
- [ ] 启用Kimi支持
- [ ] 启用GLM支持
- [ ] 性能对比测试
```

### Phase 3: 自部署支持
```
- [ ] vLLM部署
- [ ] Llama-2微调
- [ ] 本地推理优化
- [ ] 性能基准测试
```

### Phase 4: 智能路由
```
- [ ] 机器学习优化路由
- [ ] 动态负载均衡
- [ ] 预测性降级
- [ ] 自适应成本控制
```

---

## 对Phase 1-4的影响

### Phase 1: MCP Framework & Membership (影响: 中等)
```
✅ 添加LLMProviderManager
✅ 与Membership MCP集成
✅ 成本追踪实现
✓ 按时交付 (不会延期)
```

### Phase 2: Multi-MCP Support (影响: 中等)
```
✅ 所有MCPs都支持LLM分析
✅ 跨MCP智能协调可基于LLM
✓ 架构已支持
```

### Phase 3: Real-time Feedback (影响: 高)
```
✅ 自动纠正需要LLM分析
✅ 动态调整需要LLM决策
✓ 架构完美支持
```

### Phase 4: Framework Maturity (影响: 低)
```
✅ LLM路由规则文档化
✅ 成本优化最佳实践
✓ 监控和告警
```

---

## 实施清单 (Phase 1)

### Week 1 Day 1-2: 框架实现
- [ ] 设计LLMProviderManager类结构
- [ ] 实现Provider基类
- [ ] 实现OpenAI兼容客户端
- [ ] 配置系统设计

### Week 1 Day 2-3: 集成与测试
- [ ] 与Membership MCP集成
- [ ] 单元测试 (>80%覆盖)
- [ ] 集成测试
- [ ] 故障转移测试

### Week 1 Day 3-4: 优化与文档
- [ ] 成本追踪实现
- [ ] 监控和告警
- [ ] 文档编写
- [ ] code review

---

## 成功标准

### Phase 1成功条件
- ✅ 支持2个以上提供商 (GPT-5, DeepSeek)
- ✅ 自动故障转移工作正常
- ✅ 成本追踪准确
- ✅ 所有测试通过
- ✅ 文档完整

### 性能指标
- ✅ 提供商切换延迟 < 100ms
- ✅ 单次调用 < 5s (包括网络)
- ✅ 99.5% 可用性
- ✅ 成本精度 > 99%

---

## 结论

这个设计实现了:
1. **灵活的多LLM管理** - 支持无限提供商
2. **成本优化** - 按任务智能选择
3. **高可用性** - 自动故障转移
4. **可观测性** - 完整的成本追踪
5. **未来扩展** - 易于添加新提供商

**与Phase 1兼容** ✓
**不延期实施** ✓
**为Phase 2-4做好准备** ✓
