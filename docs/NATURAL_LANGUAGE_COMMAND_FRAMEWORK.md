# 自然语言命令执行框架

## 概述

这是一个通用的自然语言到命令转换框架，可以将用户的自然语言输入智能匹配到预定义的命令并执行。适用于任何需要自然语言交互的应用场景。

## 核心理念

### 传统方式的问题
```
用户输入 → 硬编码的关键词匹配 → 执行命令
❌ 只能识别固定关键词
❌ 无法理解语义
❌ 维护成本高
```

### 改进方案
```
用户输入 → AI语义匹配 → 置信度判断 → 执行/确认/询问
✅ 理解自然语言表达
✅ 支持多语言
✅ 自动降级策略
✅ 多轮对话支持
```

## 架构设计

### 1. 命令定义层（Command Definition）

**核心原则：单一真相来源**

每个命令包含：
- `command`: 实际执行的命令字符串
- `descriptions`: 语义描述（多语言、多种表达方式）
- `params`: 参数定义（可选）
- `examples`: 使用示例
- `category`: 分类（用于辅助匹配）

```javascript
const commandRegistry = [
  // 示例 1: 内部直接处理的命令
  {
    command: "/monitor on",
    category: "monitoring",
    descriptions: [
      "Enable conversation monitoring to view customer chats",
      "开启对话监控功能，实时查看客人的聊天记录",
      "启动监控",
      "打开会话监听"
    ],
    params: [],
    examples: [
      "我想看客人的聊天",
      "开启监控",
      "enable monitoring"
    ]
  },
  // 示例 2: 需要参数的命令
  {
    command: "/setwifi",
    category: "configuration",
    descriptions: [
      "Set WiFi network name and password",
      "设置WiFi网络名称和密码",
      "修改无线网络信息"
    ],
    params: [
      { 
        name: "wifi_name", 
        type: "string", 
        required: true,
        description: "无线网络名称(SSID)"
      },
      { 
        name: "wifi_password", 
        type: "string", 
        required: true,
        description: "无线网络密码"
      }
    ],
    examples: [
      "修改WiFi密码为abc123",
      "把WiFi改成MyNetwork，密码是pass123",
      "change wifi to MyNet with password secure123"
    ],
    // 对于需要外部系统处理的命令，可以定义 webhook
    webhookUrl: "https://your-service.com/api/actions/set-wifi" 
  }
];

// 命令处理器注册表 (与定义分离)
const commandHandlers = {
  "/monitor on": async (params, context) => {
    // 执行开启监控的逻辑
    console.log("Executing /monitor on", { params, context });
    return { success: true, message: "监控已开启" };
  },
  // 对于 webhookUrl 类型的命令，执行器会调用该 URL
};

```

### 2. 语义匹配层（Semantic Matching）

使用 AI 模型进行语义相似度匹配：

```javascript
async function matchCommand(userInput, commandRegistry, conversationContext = null) {
  // 构建 AI prompt
  const prompt = buildMatchingPrompt(userInput, commandRegistry, conversationContext);
  
  // 调用 AI
  const aiResponse = await callAI(prompt);
  
  // 解析结果
  return {
    matchedCommand: aiResponse.command,
    confidence: aiResponse.confidence,
    extractedParams: aiResponse.params,
    clarifyingQuestion: aiResponse.question,
    suggestions: aiResponse.alternatives
  };
}
```

**AI Prompt 模板：**

```
你是一个命令匹配助手。用户输入一句话，你需要找到最匹配的命令。

可用命令列表：
${commandRegistry.map((cmd, idx) => `
${idx + 1}. ${cmd.command}
   描述: ${cmd.descriptions.join(' / ')}
   示例: ${cmd.examples.join(' / ')}
`).join('\n')}

${conversationContext ? `上下文: ${conversationContext}` : ''}

用户输入: "${userInput}"

请返回 JSON:
{
  "command": "最匹配的命令的 command 字段值（例如 '/setwifi'），如果不确定则为 null",
  "confidence": 0.0-1.0 的置信度分数,
  "params": { 
    "param_name": "extracted_value",
    "flag_name": true // 如果用户的意图包含了某个开关（flag），则将其值设为 true
  },
  "question": "如果需要更多信息，提出的问题（可选）",
  "alternatives": ["其他可能的命令列表"]
}
```

### 3. 决策层（Decision Layer）

根据置信度采取不同策略：

```javascript
async function executeWithConfidence(matchResult, context) {
  const { matchedCommand, confidence, extractedParams, clarifyingQuestion } = matchResult;
  
  // 高置信度：直接执行
  if (confidence >= 0.85 && hasAllRequiredParams(matchedCommand, extractedParams)) {
    return await executeCommand(matchedCommand, extractedParams, context);
  }
  
  // 中置信度：请求确认
  if (confidence >= 0.5) {
    return {
      type: 'confirmation_required',
      command: matchedCommand,
      message: `您是想执行「${matchedCommand.descriptions[0]}」吗？`,
      params: extractedParams
    };
  }
  
  // 低置信度：提供选项
  return {
    type: 'clarification_needed',
    message: clarifyingQuestion || "抱歉，我不太确定您的意思。您是想：",
    suggestions: matchResult.alternatives.map(cmd => ({
      command: cmd,
      description: cmd.descriptions[0]
    }))
  };
}
```

### 4. 会话管理层（Conversation Management）

支持多轮对话：

```javascript
class ConversationSession {
  constructor(userId) {
    this.userId = userId;
    this.state = 'idle'; // idle, awaiting_confirmation, collecting_params
    this.pendingCommand = null;
    this.collectedParams = {};
    this.conversationHistory = [];
    this.createdAt = Date.now();
  }
  
  async processMessage(userInput) {
    // 添加到历史
    this.conversationHistory.push({ role: 'user', content: userInput });
    
    // 根据当前状态处理
    switch (this.state) {
      case 'idle':
        return await this.handleNewCommand(userInput);
      
      case 'awaiting_confirmation':
        return await this.handleConfirmation(userInput);
      
      case 'collecting_params':
        return await this.handleParamCollection(userInput);
    }
  }
  
  async handleNewCommand(userInput) {
    const matchResult = await matchCommand(userInput, commandRegistry, this.getContext());
    const decision = await executeWithConfidence(matchResult, this);
    
    if (decision.type === 'confirmation_required') {
      this.state = 'awaiting_confirmation';
      this.pendingCommand = decision.command;
      this.collectedParams = decision.params;
    } else if (decision.type === 'clarification_needed') {
      // 保持 idle 状态，等待用户选择
    }
    
    return decision;
  }
  
  async handleConfirmation(userInput) {
    const isConfirmed = await matchConfirmation(userInput); // "是"/"yes"/"确认"等
    
    if (isConfirmed) {
      const result = await executeCommand(this.pendingCommand, this.collectedParams, this);
      this.reset();
      return result;
    } else {
      this.reset();
      return { type: 'cancelled', message: '已取消操作' };
    }
  }
  
  async handleParamCollection(userInput) {
    // 使用 AI 从用户输入中提取缺失的参数
    const extractedParams = await extractParams(userInput, this.pendingCommand.params);
    this.collectedParams = { ...this.collectedParams, ...extractedParams };
    
    // 检查是否还有缺失参数
    const missingParams = getMissingParams(this.pendingCommand, this.collectedParams);
    
    if (missingParams.length === 0) {
      const result = await executeCommand(this.pendingCommand, this.collectedParams, this);
      this.reset();
      return result;
    } else {
      return {
        type: 'param_request',
        message: `请提供${missingParams[0].name}：`,
        missingParam: missingParams[0]
      };
    }
  }
  
  getContext() {
    return this.conversationHistory.slice(-3).map(h => h.content).join('\n');
  }
  
  reset() {
    this.state = 'idle';
    this.pendingCommand = null;
    this.collectedParams = {};
  }
}
```

## 实现步骤

### Step 1: 定义命令注册表

从现有的命令系统（如 /help）中提取命令定义：

```javascript
// 从 /help 输出自动生成
function buildCommandRegistry(helpText) {
  const commands = parseHelpText(helpText);
  return commands.map(cmd => ({
    command: cmd.name,
    descriptions: [cmd.description, cmd.descriptionChinese],
    params: cmd.parameters || [],
    handler: getCommandHandler(cmd.name)
  }));
}
```

### Step 2: 实现语义匹配

```javascript
async function semanticMatch(userInput, commandRegistry) {
  const systemPrompt = buildSystemPrompt(commandRegistry);
  const userPrompt = `用户输入: "${userInput}"\n\n请返回匹配结果的JSON:`;
  
  const aiResponse = await callAI({
    systemPrompt,
    userPrompt,
    temperature: 0.3, // 降低随机性
    maxTokens: 500
  });
  
  return parseAIResponse(aiResponse);
}
```

### Step 3: 构建会话管理器

```javascript
class NLCommandEngine {
  constructor(commandRegistry, aiClient) {
    this.commandRegistry = commandRegistry;
    this.aiClient = aiClient;
    this.sessions = new Map(); // userId -> ConversationSession
  }
  
  async processUserInput(userId, userInput) {
    // 获取或创建会话
    let session = this.sessions.get(userId);
    if (!session) {
      session = new ConversationSession(userId);
      this.sessions.set(userId, session);
    }
    
    // 处理消息
    const result = await session.processMessage(userInput);
    
    // 清理过期会话
    this.cleanupExpiredSessions();
    
    return result;
  }
  
  cleanupExpiredSessions() {
    const now = Date.now();
    const TIMEOUT = 10 * 60 * 1000; // 10分钟
    
    for (const [userId, session] of this.sessions.entries()) {
      if (now - session.createdAt > TIMEOUT && session.state === 'idle') {
        this.sessions.delete(userId);
      }
    }
  }
}
```

### Step 4: 集成到现有系统

```javascript
// 在你的 webhook 或消息处理器中
const nlEngine = new NLCommandEngine(commandRegistry, aiClient);

async function handleUserMessage(userId, message) {
  // 检查是否是传统命令格式
  if (message.startsWith('/')) {
    return await handleTraditionalCommand(message);
  }
  
  // 使用自然语言引擎
  const result = await nlEngine.processUserInput(userId, message);
  
  switch (result.type) {
    case 'command_executed':
      return result.message;
    
    case 'confirmation_required':
      return result.message;
    
    case 'clarification_needed':
      return formatSuggestions(result.message, result.suggestions);
    
    case 'param_request':
      return result.message;
    
    default:
      return "抱歉，我不理解您的请求。";
  }
}
```

## REST API 设计

### 独立服务架构

```
┌─────────────┐
│   Client    │
│  (Any App)  │
└──────┬──────┘
       │ HTTP Request
       ↓
┌─────────────────────────┐
│  NL Command API Server  │
│  ┌──────────────────┐   │
│  │ Command Registry │   │
│  └──────────────────┘   │
│  ┌──────────────────┐   │
│  │ Session Manager  │   │
│  └──────────────────┘   │
│  ┌──────────────────┐   │
│  │   AI Client      │   │
│  └──────────────────┘   │
└────────┬────────────────┘
         │
         ↓
    ┌────────┐
    │   AI   │
    │ Model  │
    └────────┘
```

### API 端点定义

#### 1. 初始化会话

```http
POST /api/nlc/sessions
Content-Type: application/json

{
  "userId": "user123",
  "context": {
    "language": "zh",
    "userRole": "landlord"
  }
}

Response:
{
  "sessionId": "sess_abc123",
  "expiresAt": "2025-10-18T12:00:00Z"
}
```

#### 2. 处理用户输入

```http
POST /api/nlc/sessions/:sessionId/messages
Content-Type: application/json

{
  "message": "我想看客人的聊天记录"
}

Response (直接执行):
Response (匹配成功，可直接执行):
{
  "type": "command_executed",
  "command": "/monitor on",
  "result": {
    "success": true,
    "message": "✅ 监控已开启"
  }
  "type": "command_ready",
  "command": "GET /v2/members", // 匹配到的命令标识
  "description": "查询成员列表", // 命令的描述
  "confidence": 0.95,
  "pathParams": {}, // 从自然语言中提取并填充到路径中的参数
  "queryParams": {   // 从自然语言中提取的查询参数
    "status": "active"
  },
  "body": null, // 如果是POST/PATCH/PUT，这里是请求体
  "headers": { // 可选，如果需要特定头信息
    "X-Tenant-ID": "tenant-123"
  } 
}

Response (需要确认):
{
  "type": "confirmation_required",
  "command": "/monitor on",
  "message": "您是想开启对话监控吗？",
  "options": [
    { "value": "yes", "label": "是" },
    { "value": "no", "label": "否" }
  ]
}

Response (需要澄清):
{
  "type": "clarification_needed",
  "message": "您想执行以下哪个操作？",
  "suggestions": [
    {
      "command": "/monitor on",
      "description": "开启对话监控",
      "confidence": 0.65
    },
    {
      "command": "/sessions",
      "description": "查看活跃会话",
      "confidence": 0.58
    }
  ]
}

Response (需要参数):
{
  "type": "param_request",
  "command": "/setwifi",
  "message": "请提供WiFi密码：",
  "collectedParams": {
    "wifi_name": "MyNetwork"
  },
  "missingParams": [
    {
      "name": "wifi_password",
      "type": "string",
      "description": "WiFi密码"
    }
  ]
}
```

#### 3. 管理命令集

##### 创建命令集
```http
POST /api/nlc/command-sets
Content-Type: application/json

{
  "name": "IoT Device Controls",
  "description": "Commands for controlling smart home devices."
}

Response:
{
  "id": "cs_655b6a4f7b2d7b1d7f01a2b3",
  "name": "IoT Device Controls",
  "success": true
}
```

##### 在指定命令集中注册新命令
```http
POST /api/nlc/command-sets/:setId/commands
Content-Type: application/json

{
  "command": "/turn_light_on",
  "category": "lighting",
  "descriptions": ["Turn on the light", "开灯"],
  "params": [{ "name": "room", "type": "string", "required": false, "description": "房间名称" }],
  "examples": ["打开客厅的灯", "turn on the light in the living room"],
  "webhookUrl": "https://iot-hub.com/api/actions"
}

Response:
{
  "success": true,
  "commandId": "cmd_xyz789"
}
```

#### 4. 获取可用命令

```http
GET /api/nlc/commands?category=monitoring

Response:
{
  "commands": [
    {
      "command": "/monitor on",
      "category": "monitoring",
      "descriptions": ["开启监控", "Enable monitoring"],
      "examples": ["我想看客人聊天", "start monitoring"]
    }
  ]
}
```

#### 5. 获取会话状态

```http
GET /api/nlc/sessions/:sessionId

Response:
{
  "sessionId": "sess_abc123",
  "userId": "user123",
  "state": "awaiting_confirmation",
  "pendingCommand": "/monitor on",
  "conversationHistory": [
    { "role": "user", "content": "我想看客人聊天" },
    { "role": "assistant", "content": "您是想开启监控吗？" }
  ],
  "createdAt": "2025-10-18T10:00:00Z",
  "expiresAt": "2025-10-18T12:00:00Z"
}
```

## 配置选项

### AI 模型配置

```javascript
const config = {
  ai: {
    provider: 'openai', // 'openai' | 'anthropic' | 'deepseek'
    model: 'gpt-4',
    temperature: 0.3,
    maxTokens: 500,
    timeout: 10000
  },
  matching: {
    highConfidenceThreshold: 0.85,
    mediumConfidenceThreshold: 0.5,
    maxSuggestions: 3
  },
  session: {
    timeoutMinutes: 10,
    maxHistoryLength: 10,
    cleanupInterval: 60000
  },
  commands: {
    autoRegisterFromHelp: true,
    allowCustomCommands: true,
    validateParams: true
  }
};
```

## 性能优化

### 1. 缓存策略

```javascript
// 缓存常见查询
const cache = new Map();

async function matchCommandWithCache(userInput, commandRegistry) {
  const cacheKey = `${userInput.toLowerCase()}:${commandRegistry.version}`;
  
  if (cache.has(cacheKey)) {
    return cache.get(cacheKey);
  }
  
  const result = await semanticMatch(userInput, commandRegistry);
  cache.set(cacheKey, result);
  
  return result;
}
```

### 2. 批量处理

```javascript
// 批量处理多个用户输入
async function batchProcessMessages(messages) {
  const results = await Promise.all(
    messages.map(msg => matchCommand(msg.text, commandRegistry))
  );
  return results;
}
```

### 3. 降级策略

```javascript
// AI 服务不可用时的降级
async function matchCommandWithFallback(userInput, commandRegistry) {
  try {
    return await semanticMatch(userInput, commandRegistry);
  } catch (error) {
    console.error('AI matching failed, using keyword fallback', error);
    return keywordMatch(userInput, commandRegistry);
  }
}

function keywordMatch(userInput, commandRegistry) {
  // 简单的关键词匹配作为降级
  const keywords = userInput.toLowerCase().split(/\s+/);
  
  for (const cmd of commandRegistry) {
    const cmdKeywords = cmd.descriptions.join(' ').toLowerCase();
    if (keywords.some(kw => cmdKeywords.includes(kw))) {
      return {
        matchedCommand: cmd,
        confidence: 0.6,
        method: 'keyword_fallback'
      };
    }
  }
  
  return { matchedCommand: null, confidence: 0 };
}
```

## 安全考虑

### 1. 命令白名单

```javascript
const commandWhitelist = new Set([
  '/monitor on',
  '/monitor off',
  '/sessions',
  // ... 其他允许的命令
]);

function validateCommand(command) {
  if (!commandWhitelist.has(command)) {
    throw new Error('Command not in whitelist');
  }
}
```

### 2. 参数验证

```javascript
function validateParams(command, params) {
  for (const paramDef of command.params) {
    const value = params[paramDef.name];
    
    if (paramDef.required && !value) {
      throw new Error(`Missing required parameter: ${paramDef.name}`);
    }
    
    if (paramDef.pattern && !paramDef.pattern.test(value)) {
      throw new Error(`Invalid parameter format: ${paramDef.name}`);
    }
    
    if (paramDef.maxLength && value.length > paramDef.maxLength) {
      throw new Error(`Parameter too long: ${paramDef.name}`);
    }
  }
}
```

### 3. 速率限制

```javascript
class RateLimiter {
  constructor(maxRequests, windowMs) {
    this.maxRequests = maxRequests;
    this.windowMs = windowMs;
    this.requests = new Map();
  }
  
  checkLimit(userId) {
    const now = Date.now();
    const userRequests = this.requests.get(userId) || [];
    
    // 清除过期请求
    const validRequests = userRequests.filter(time => now - time < this.windowMs);
    
    if (validRequests.length >= this.maxRequests) {
      throw new Error('Rate limit exceeded');
    }
    
    validRequests.push(now);
    this.requests.set(userId, validRequests);
  }
}
```

## 测试策略

### 单元测试

```javascript
describe('Command Matching', () => {
  it('should match exact command', async () => {
    const result = await matchCommand('开启监控', commandRegistry);
    expect(result.matchedCommand.command).toBe('/monitor on');
    expect(result.confidence).toBeGreaterThan(0.85);
  });
  
  it('should handle ambiguous input', async () => {
    const result = await matchCommand('改一下', commandRegistry);
    expect(result.matchedCommand).toBeNull();
    expect(result.suggestions.length).toBeGreaterThan(0);
  });
  
  it('should extract parameters', async () => {
    const result = await matchCommand('把WiFi改成MyNet密码是abc123', commandRegistry);
    expect(result.matchedCommand.command).toBe('/setwifi');
    expect(result.extractedParams).toEqual({
      wifi_name: 'MyNet',
      wifi_password: 'abc123'
    });
  });
});
```

### 集成测试

```javascript
describe('Conversation Flow', () => {
  it('should handle multi-turn conversation', async () => {
    const session = new ConversationSession('user123');
    
    // Turn 1: 模糊输入
    let result = await session.processMessage('我想改点东西');
    expect(result.type).toBe('clarification_needed');
    
    // Turn 2: 选择命令
    result = await session.processMessage('WiFi');
    expect(result.type).toBe('param_request');
    
    // Turn 3: 提供参数
    result = await session.processMessage('名称MyNet密码abc123');
    expect(result.type).toBe('command_executed');
  });
});
```

## 监控和日志

```javascript
class CommandLogger {
  async logCommandExecution(userId, command, params, result) {
    await db.insert('command_logs', {
      userId,
      command: command.command,
      params: JSON.stringify(params),
      success: result.success,
      confidence: result.confidence,
      executionTime: result.executionTime,
      timestamp: new Date()
    });
  }
  
  async getCommandStats(timeRange) {
    return await db.query(`
      SELECT 
        command,
        COUNT(*) as total_executions,
        AVG(confidence) as avg_confidence,
        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
        AVG(executionTime) as avg_execution_time
      FROM command_logs
      WHERE timestamp >= ?
      GROUP BY command
      ORDER BY total_executions DESC
    `, [timeRange.start]);
  }
}
```

## 最佳实践

### 1. 命令描述编写

✅ **好的描述：**
- "开启对话监控功能，实时查看客人的聊天记录"
- "Enable conversation monitoring to view customer chats in real-time"

❌ **不好的描述：**
- "监控开"
- "monitor"

### 2. 示例编写

提供多样化的真实用户输入示例：
```javascript
examples: [
  "我想看看客人在说什么",
  "帮我打开监控",
  "能不能看到客人的消息",
  "start monitoring",
  "enable chat viewing"
]
```

### 3. 参数定义

```javascript
params: [
  {
    name: "wifi_password",
    type: "string",
    required: true,
    description: "WiFi密码",
    pattern: /^[A-Za-z0-9!@#$%^&*]{8,}$/,
    errorMessage: "密码至少8位，包含字母、数字或特殊字符"
  }
]
```

### 4. 错误处理

```javascript
try {
  const result = await executeCommand(command, params);
  return result;
} catch (error) {
  // 用户友好的错误消息
  if (error.code === 'INVALID_PARAMS') {
    return {
      success: false,
      message: `参数错误：${error.message}。${error.suggestion}`
    };
  }
  
  // 记录错误但返回通用消息
  logger.error('Command execution failed', { error, command, params });
  return {
    success: false,
    message: '抱歉，执行失败了。请稍后重试。'
  };
}
```

## 应用场景

### 1. 智能客服
- 用户问题自动分类和路由
- 常见问题自动回答
- 人工客服辅助工具

### 2. IoT 设备控制
- "把客厅的灯打开" → 执行设备控制命令
- "空调温度调到26度" → 参数提取 + 执行

### 3. 企业内部工具
- "给我看上周的销售报表" → 查询数据库
- "发送周报给团队" → 触发自动化流程

### 4. 个人助理
- "提醒我明天下午3点开会" → 创建日历事件
- "查一下从北京到上海的高铁" → API调用

## 扩展性

### 插件系统

```javascript
class PluginManager {
  constructor() {
    this.plugins = new Map();
  }
  
  registerPlugin(name, plugin) {
    this.plugins.set(name, plugin);
  }
  
  async executeWithPlugins(command, params, context) {
    // Before hooks
    for (const plugin of this.plugins.values()) {
      if (plugin.beforeExecute) {
        await plugin.beforeExecute(command, params, context);
      }
    }
    
    // Execute
    const result = await command.handler(params, context);
    
    // After hooks
    for (const plugin of this.plugins.values()) {
      if (plugin.afterExecute) {
        await plugin.afterExecute(command, params, result, context);
      }
    }
    
    return result;
  }
}

// 使用示例
pluginManager.registerPlugin('logger', {
  beforeExecute: async (command, params) => {
    console.log(`Executing ${command.command}`, params);
  },
  afterExecute: async (command, params, result) => {
    console.log(`Executed ${command.command}`, result);
  }
});
```

### 多租户支持

```javascript
class MultiTenantNLEngine {
  constructor() {
    this.tenantEngines = new Map();
  }
  
  getEngine(tenantId) {
    if (!this.tenantEngines.has(tenantId)) {
      const tenantConfig = loadTenantConfig(tenantId);
      const engine = new NLCommandEngine(
        tenantConfig.commandRegistry,
        tenantConfig.aiClient
      );
      this.tenantEngines.set(tenantId, engine);
    }
    return this.tenantEngines.get(tenantId);
  }
  
  async processUserInput(tenantId, userId, userInput) {
    const engine = this.getEngine(tenantId);
    return await engine.processUserInput(userId, userInput);
  }
}
```

## 总结

这个框架的核心优势：

1. **通用性** - 适用于任何需要自然语言交互的场景
2. **可扩展** - 易于添加新命令和新功能
3. **智能化** - AI驱动的语义理解
4. **渐进式** - 从简单到复杂的降级策略
5. **用户友好** - 多轮对话支持，自然交互
6. **可维护** - 单一真相来源，命令集中管理
7. **可测试** - 清晰的接口和测试策略
8. **可观测** - 完整的日志和监控

无论是集成到现有系统，还是作为独立服务部署，这个框架都能提供一致的自然语言命令处理能力。
