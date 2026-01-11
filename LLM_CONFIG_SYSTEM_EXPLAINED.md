# LLM 配置系统详解

## 📋 配置文件位置

### YAML 配置文件
**文件**: `config/llm_providers.yaml`

这是 LLM 提供商的 **默认配置模板**，包含：
- 6 个预设的 LLM 提供商（OpenAI, DeepSeek, Qwen, Kimi, GLM, Local）
- 每个提供商的参数：base_url, model, temperature, max_tokens 等
- API 密钥的环境变量名引用（不是实际密钥）

**用途**：
- ✅ 开发环境的默认配置
- ✅ 生产环境的备用配置（当 MongoDB 失败时）
- ✅ 版本控制（通过 git 管理）

### API 密钥文件
**文件**: `.env`

存储实际的 API 密钥：
```bash
OPENAI_API_KEY=sk-proj-xxxxx
DEEPSEEK_API_KEY=sk-xxxxx
QWEN_API_KEY=xxxxx
# 等等...
```

**用途**：
- 不存储在版本控制中（Git ignored）
- 系统启动时从 `.env` 读取，映射到环境变量

---

## 🔄 配置加载流程

### 启动时的决策流程

```
系统启动 (src/main.py)
    ↓
LLMConfigLoader(use_mongodb=True)  ← 第 47 行：明确设置为 True
    ↓
provider_manager.initialize(db_client)
    ↓
    ├─ 尝试从 MongoDB 加载提供商
    │  ├─ 成功 ✅ → 使用 MongoDB 数据
    │  └─ 失败或为空 ❌ → 继续
    │
    └─ 回退到 YAML
       ├─ 加载 config/llm_providers.yaml
       └─ 使用默认提供商配置
```

### 代码位置和确定逻辑

**1. 哪里确定使用 MongoDB/YAML?**

**文件**: `src/main.py` 第 47 行
```python
config_loader = LLMConfigLoader(use_mongodb=True)
                                               ↑↑↑
                        # 这里决定：True = 优先 MongoDB，False = 仅 YAML
```

**2. 加载逻辑**

**文件**: `src/llm/provider_manager.py` 第 44-52 行
```python
if db_client and self.config_loader.use_mongodb:
    # 尝试从 MongoDB 加载
    self.providers = await self.config_loader.load_from_mongodb(db_client)

    # 如果 MongoDB 为空或失败，回退到 YAML
    if not self.providers:
        logger.info("MongoDB is empty, falling back to YAML")
        self.providers = self.config_loader.load_from_yaml()
else:
    # use_mongodb=False，直接使用 YAML
    self.providers = self.config_loader.load_from_yaml()
```

**3. 改进的回退逻辑**

**文件**: `src/llm/provider_manager.py` 第 73-95 行
```python
# 如果 MongoDB 中的提供商都无法初始化（API 密钥问题等）
# 则自动回退到 YAML
if successfully_initialized == 0 and db_client and use_mongodb:
    logger.warning("No valid providers in MongoDB, falling back to YAML")
    self.providers = self.config_loader.load_from_yaml()
    # ... 重新初始化
```

---

## 📊 配置优先级

### 当前优先级（推荐）

```
优先级 1: MongoDB (如果有有效的提供商)
  ↓ (如果 MongoDB 为空或无有效提供商)
优先级 2: YAML (config/llm_providers.yaml)
  ↓ (如果 YAML 加载失败)
优先级 3: 无提供商（系统警告）
```

### 配置来源对比

| 特性 | YAML | MongoDB |
|------|------|---------|
| 文件位置 | `config/llm_providers.yaml` | 数据库集合 `llm_providers` |
| 版本控制 | ✅ 支持 (Git 管理) | ❌ 不适合 |
| 动态修改 | ❌ 需要重启 | ✅ 实时更新 |
| 开发/测试 | ✅ 推荐 | ⚠️ 需要数据库 |
| 生产环境 | ✅ 作为备份 | ✅ 推荐 |
| 持久化 | ❌ 文件系统 | ✅ 数据库 |

---

## ⚙️ 如何修改配置？

### 修改 YAML（开发环境）

1. 编辑 `config/llm_providers.yaml`
2. 修改提供商参数（如 temperature, max_tokens 等）
3. 重启后端：`python -m src.main`

**示例**：
```yaml
providers:
  openai:
    model: gpt-4-turbo  # 改动：从 gpt-5 改为 gpt-4-turbo
    temperature: 0.8    # 改动：从 0.7 改为 0.8
```

### 修改 MongoDB（生产环境）

1. 通过前端 LLM Management 界面：
   - 点击 "Edit" 修改现有提供商
   - 或点击 "+ Add Provider" 创建新提供商

2. 修改自动保存到 MongoDB
3. 无需重启，立即生效

### 修改 API 密钥（.env）

1. 编辑 `.env` 文件
2. 添加或更新密钥：
   ```bash
   OPENAI_API_KEY=sk-new-key-here
   DEEPSEEK_API_KEY=sk-new-key-here
   ```
3. 重启后端使新密钥生效

---

## 🔐 API 密钥管理

### 配置格式

```yaml
# ❌ 错误方式：直接存储密钥
providers:
  openai:
    api_key_ref: sk-proj-actual-key-here  # 不要这样！

# ✅ 正确方式：使用环境变量名
providers:
  openai:
    api_key_ref: OPENAI_API_KEY  # 从 .env 读取
```

### 运行时匹配

系统启动时：
```python
# 从 YAML
api_key_ref: "OPENAI_API_KEY"
     ↓
# 从环境变量读取
os.environ.get("OPENAI_API_KEY")
     ↓
# 得到实际密钥
api_key = "sk-proj-actual-key-here"
```

---

## 📍 文件关系图

```
.env (Git ignored)
├── OPENAI_API_KEY=sk-proj-xxxxx
├── DEEPSEEK_API_KEY=sk-xxxxx
└── ...

config/llm_providers.yaml (Git tracked)
├── providers:
│   ├── openai:
│   │   ├── api_key_ref: OPENAI_API_KEY ← 指向 .env
│   │   ├── base_url: https://api.openai.com/v1
│   │   └── ...
│   └── deepseek:
│       ├── api_key_ref: DEEPSEEK_API_KEY ← 指向 .env
│       └── ...

MongoDB (nl_tps.llm_providers collection)
├── 由前端 UI 创建/修改
├── 优先使用（如果有效）
└── 自动回退到 YAML（如果无效）
```

---

## 🔧 实际工作流

### 开发环境

1. **YAML 配置**：修改 `config/llm_providers.yaml`
2. **API 密钥**：添加到 `.env`
3. **启动**：`python -m src.main`
4. **测试**：使用默认 YAML 提供商

### 生产环境

1. **部署时**：部署 YAML 作为备份
2. **运行时**：通过前端 UI 在 MongoDB 中管理提供商
3. **故障转移**：如果 MongoDB 失败，自动使用 YAML

### 添加新提供商

**方式 1**：编辑 YAML（适合已知提供商）
```yaml
providers:
  claude:  # 新提供商
    type: openai_compatible
    base_url: https://api.anthropic.com/v1
    model: claude-3-sonnet
    api_key_ref: ANTHROPIC_API_KEY  # 需要在 .env 中配置
```

**方式 2**：前端 UI（更灵活）
1. 点击 "+ Add Provider"
2. 填写表单：
   - Name: `claude`
   - Base URL: `https://api.anthropic.com/v1`
   - Model: `claude-3-sonnet`
   - API Key Ref: `ANTHROPIC_API_KEY` ← **重要：环境变量名，不是密钥！**
3. 保存到 MongoDB

---

## ⚡ 快速参考

### 切换配置来源

```python
# src/main.py 第 47 行

# 仅使用 YAML（开发/测试）
config_loader = LLMConfigLoader(use_mongodb=False)

# 优先 MongoDB，备用 YAML（生产）
config_loader = LLMConfigLoader(use_mongodb=True)
```

### 查看当前加载的提供商

```bash
# 查看 API 列表
curl http://localhost:8000/api/llm/providers | jq '.providers'

# 查看当前活跃的提供商
curl http://localhost:8000/api/llm/current | jq '.name'
```

### 查看启动日志

```bash
# 查看配置加载过程
tail -f /tmp/backend.log | grep -i "provider\|yaml\|mongodb"

# 输出示例：
# - Loaded 0 providers from MongoDB
# - No valid providers in MongoDB, falling back to YAML
# - Loaded 6 providers from YAML
# - Initialized client for provider openai
# - Set default provider: openai
```

---

## 🎯 总结

| 问题 | 答案 |
|------|------|
| YAML 文件在哪? | `config/llm_providers.yaml` |
| 如何确定用 MongoDB/YAML? | `src/main.py` 第 47 行 `use_mongodb=True/False` |
| 开发时用什么? | YAML (开箱即用) |
| 生产时用什么? | MongoDB (通过 UI 管理) |
| 密钥存在哪? | `.env` 文件中 |
| 配置持久化吗? | YAML 不持久，MongoDB 持久 |
| 修改后需要重启吗? | YAML 需要，MongoDB 不需要 |

