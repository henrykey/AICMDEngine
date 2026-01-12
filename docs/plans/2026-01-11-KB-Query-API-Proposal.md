# Knowledge Base Query API 设计建议

**版本**: 2.0 (基于Membership v2.4文档引擎)
**日期**: 2026-01-11
**目的**: 为BPMN-MCP和FORM-MCP提供KB查询API，基于Membership v2.4已设计的文档引擎
**目标受众**: Membership开发团队、AICMDEngine集成团队

---

## 概述

BPMN-MCP和FORM-MCP需要在**运行时**查询知识库来做出智能决策：
- 路由规则（哪个部门应该审批？）
- 策略约束（这个金额是否需要CFO审批？）
- 动态数据（符合这些条件的人员有哪些？）

**关键点**: Membership v2.4已设计文档引擎架构（MongoDB + Elasticsearch）。本文建议的是在其基础上增加**REST查询API**，让AICMDEngine可以调用KB进行智能决策。

---

## 现状分析

### Membership v2.4已有能力 ✅
✅ 文档存储 (MongoDB collections: documents, document_permissions)
✅ 文本提取 (Apache Tika - 支持docx, pdf, md, images等)
✅ 全文搜索索引 (Elasticsearch: documents_text)
✅ 语义向量索引 (Elasticsearch: doc_embeddings, 768维dense_vector)
✅ 混合搜索算法 (HybridSearchService with RRF融合)
✅ 权限管理 (document_permissions collection)
✅ 多租户隔离 (tenant_id + Elasticsearch sharding)
✅ 组织结构（部门、角色、成员）- 通过Members/Roles/Orgs API
✅ 审计跟踪 - Kafka + MongoDB

### AICMDEngine需要的能力 ❌ → ✅ (需添加REST API)
❌→✅ KB文档查询API (GET /v2/knowledge-base/search)
❌→✅ 语义相似性查询API (POST /v2/knowledge-base/semantic-search)
❌→✅ 路由规则提取API (POST /v2/knowledge-base/extract-routing-rule)
❌→✅ RAG问答API (POST /v2/knowledge-base/rag-query)

---

## API设计建议

**基础**: 所有API基于Membership v2.4文档引擎的MongoDB + Elasticsearch架构。
**现状**: membership-docs模块已设计数据模型和服务实现，此处建议的是REST API层。

### 1. KB文档管理API

#### 1.1 创建/更新KB文档 (可能已有，确认格式)

```
POST /v2/knowledge-base/documents
```

**请求**:
```json
{
  "tenant_id": "string",
  "title": "string",
  "category": "policy|template|rule|procedure|example",
  "content": "string - Markdown格式",
  "metadata": {
    "applies_to_orgs": ["array of org_ids"],
    "applies_to_roles": ["array of role_ids"],
    "effective_from": "ISO8601",
    "effective_until": "ISO8601 (optional)",
    "priority": "integer (0-100)",
    "tags": ["array of tags"]
  },
  "source": "string - 来源，如'policy_v1.2', 'customer_request_#123'"
}
```

**响应**:
```json
{
  "document_id": "string - UUID",
  "tenant_id": "string",
  "title": "string",
  "category": "policy",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "status": "active|draft|archived"
}
```

**说明**:
- 文档存储在MongoDB
- 自动生成向量embedding保存到Milvus
- 自动提取关键字到Elasticsearch
- 支持多租户隔离

#### 1.2 批量导入

```
POST /v2/knowledge-base/documents/import
```

**用途**: 初始化客户KB（如导入组织政策、流程模板等）

---

### 2. KB查询API (核心)

#### 2.1 精确查询 (Keyword Search)

```
GET /v2/knowledge-base/search
```

**查询参数**:
```
?tenant_id=string (required)
&query=string (required) - 搜索关键词
&category=policy|template|rule|procedure|example (optional)
&applies_to_org=integer (optional)
&applies_to_role=integer (optional)
&limit=20 (default)
&offset=0
```

**响应**:
```json
{
  "results": [
    {
      "document_id": "string",
      "title": "string",
      "category": "policy",
      "snippet": "string - 包含关键词的摘录",
      "relevance_score": 0.95,
      "metadata": {
        "applies_to": ["org_id_123", "role_id_456"],
        "effective_from": "ISO8601"
      }
    }
  ],
  "total": 42,
  "page": 1,
  "limit": 20
}
```

**实现**: Elasticsearch全文搜索

**使用场景**:
```
查询: "Amounts > 10000 approval"
结果: "Policy: Approval > $10,000 requires CFO signature"
```

---

#### 2.2 语义查询 (Semantic Search)

```
POST /v2/knowledge-base/semantic-search
```

**请求**:
```json
{
  "tenant_id": "string",
  "query": "string - 自然语言描述",
  "category": "policy|template|rule|procedure|example (optional)",
  "applies_to_context": {
    "org_id": "integer (optional)",
    "role_id": "integer (optional)",
    "amount": "number (optional)",
    "item_type": "string (optional)",
    "region": "string (optional)"
  },
  "limit": 10,
  "threshold": 0.7 (0.0-1.0, 相似度阈值)
}
```

**响应**:
```json
{
  "results": [
    {
      "document_id": "string",
      "title": "string",
      "category": "policy",
      "full_content": "string",
      "similarity_score": 0.92,
      "applies_to_context": {
        "org_ids": ["org_123"],
        "role_ids": ["role_456"],
        "effective_from": "2025-01-01"
      }
    }
  ],
  "total": 5
}
```

**实现**: Milvus向量搜索 (Claude/OpenAI embeddings)

**使用场景 (Runtime in BPMN)**:
```json
{
  "query": "What's the approval policy for pharmaceutical items > $50k in EMEA region?",
  "applies_to_context": {
    "item_type": "pharmaceutical",
    "amount": 50000,
    "region": "EMEA"
  }
}

结果:
"Policy: Pharmaceutical items > $50k require:
 1. Medical review from 2 experts
 2. CFO approval for budget code verification
 3. Legal review for regulatory compliance
 Route to: pharma_director + cfo_committee"
```

---

#### 2.3 结构化查询 (for Dynamic Routing)

```
POST /v2/knowledge-base/extract-routing-rule
```

**请求**:
```json
{
  "tenant_id": "string",
  "context": {
    "process_type": "approval|workflow|notification",
    "category": "pharmaceutical|device|financial",
    "amount": 50000,
    "org_id": 123,
    "region": "EMEA"
  }
}
```

**响应**:
```json
{
  "routing_rule": {
    "primary_approver": {
      "type": "role|org",
      "value": "role_id_123 | org_id_456",
      "name": "pharma_director"
    },
    "secondary_approvers": [
      {"type": "role", "value": "cfo", "name": "CFO Committee"}
    ],
    "requires_review": ["legal", "compliance"],
    "policy_references": ["policy_v2.1_pharma", "policy_v1.5_regional"],
    "confidence": 0.95,
    "rationale": "Based on amount > $50k threshold and pharmaceutical category"
  },
  "alternative_routes": [
    {
      "condition": "If medical review fails",
      "route_to": "process_improvement_team"
    }
  ]
}
```

**实现**:
1. 语义搜索找到相关政策
2. Claude LLM提取结构化路由规则
3. 验证提议的approver在Membership中存在

---

#### 2.4 RAG查询 (for LLM Context)

```
POST /v2/knowledge-base/rag-query
```

**请求**:
```json
{
  "tenant_id": "string",
  "query": "string - 自然语言问题",
  "context_limit": 5,
  "use_semantic_search": true
}
```

**响应**:
```json
{
  "answer": "string - LLM生成的回答",
  "sources": [
    {
      "document_id": "string",
      "title": "string",
      "excerpt": "string - 用于生成回答的摘录"
    }
  ],
  "confidence": 0.88
}
```

**实现**:
1. 语义搜索取top-5最相关文档
2. 将文档摘录作为context传给LLM
3. LLM基于context生成回答
4. 返回answer + sources

**使用场景**:
```json
查询: "Can we approve this drug application for $500k without CFO signature?"

回答: "No. According to Policy v2.1 section 3.2, pharmaceutical items
      exceeding $250k require explicit CFO approval and board review.
      此金额需要额外的合规审查。"

来源: ["pharmaceutical_approval_policy_v2.1", "policy_exceptions_register_2025"]
```

---

### 3. 健康检查和元数据API

#### 3.1 KB统计信息

```
GET /v2/knowledge-base/stats
```

**响应**:
```json
{
  "tenant_id": "string",
  "total_documents": 523,
  "by_category": {
    "policy": 200,
    "template": 150,
    "rule": 100,
    "procedure": 50,
    "example": 23
  },
  "by_status": {
    "active": 450,
    "draft": 50,
    "archived": 23
  },
  "last_updated": "ISO8601",
  "vector_index_health": {
    "total_embeddings": 523,
    "last_sync": "ISO8601"
  },
  "elasticsearch_health": {
    "index_count": 523,
    "last_sync": "ISO8601"
  }
}
```

---

### 4. 权限和多租户

**安全策略**:
```
- 所有API要求X-Tenant-ID header (从JWT token提取)
- 文档对租户隔离 (MongoDB RLS)
- Milvus/Elasticsearch向量和索引也按tenant_id分隔
- 审计: 所有KB查询记录到audit_outbox
```

**权限**:
```
- kb:read - 允许查询KB文档
- kb:write - 允许创建/更新KB文档
- kb:admin - 允许管理KB（删除、导入、备份）
```

---

## 实现路线图

### Phase 1: 基础 (Week 1-2)
- [ ] MongoDB KB文档schema设计
- [ ] API endpoints 1.1 (create/update document)
- [ ] API endpoints 2.1 (keyword search via Elasticsearch)
- [ ] 多租户隔离和权限检查

### Phase 2: 语义搜索 (Week 3-4)
- [ ] Milvus集成和向量生成
- [ ] API endpoints 2.2 (semantic search)
- [ ] 向量embedding pipeline (MongoDB → Milvus)

### Phase 3: 高级功能 (Week 5-6)
- [ ] API endpoints 2.3 (structured routing rule extraction)
- [ ] API endpoints 2.4 (RAG with LLM)
- [ ] 缓存层优化

### Phase 4: 测试和优化 (Week 7-8)
- [ ] 全面测试
- [ ] 性能优化
- [ ] 文档完善

---

## 对BPMN-MCP和FORM-MCP的影响

### BPMN-MCP使用KB API

**生成阶段** (design-time):
```
用户输入: "Route approval based on amount and category"
  ↓
LLM调用KB API 2.1 (keyword search):
  查询: "approval policy amount category"
  得到: Policy文档
  ↓
LLM基于Policy生成BPMN
  ↓
结果: BPMN包含多个routing branches
```

**执行阶段** (runtime in Membership):
```
流程执行中: amount=50000, category="pharmaceutical"
  ↓
Flowable service task调用KB API 2.3:
  查询: "approval routing for pharmaceutical > 50k"
  得到: route_to = [cfo_committee, pharma_director]
  ↓
动态创建task给这些approvers
```

**关键点**: 如果政策改变，只需更新KB，不需要修改BPMN或代码！

### FORM-MCP使用KB API

**字段权限生成**:
```
LLM调用KB API 2.2 (semantic search):
  查询: "Who should see budget_code field in pharma approval?"
  得到: "Only finance dept and budget_managers can view/edit"
  ↓
生成form definition:
{
  "budget_code": {
    "permissions": {
      "view": {"applies_to": ["dept:finance"]},
      "edit": {"applies_to": ["role:budget_manager"]}
    }
  }
}
```

---

## 成本和风险评估

### 成本估算
- **基础KB API** (search + CRUD): 5-10工作日
- **语义搜索** (Milvus集成): 5-7工作日
- **高级功能** (routing extraction): 5-10工作日
- **总计**: 15-27工作日 (3-5.5周)

### 风险
1. **向量embedding成本**: 523文档 × embedding cost
   - 建议: 使用开源模型或批量处理
2. **LLM成本** (RAG功能): 每次查询调用LLM
   - 建议: 实现caching和batch processing
3. **性能**: Milvus/Elasticsearch延迟
   - 建议: 添加缓存层，使用异步索引更新

---

## 与现有系统集成

### MongoDB
```
新collection: `knowledge_base_documents`
schema:
  _id: ObjectId
  tenant_id: string
  title: string
  category: string
  content: string
  metadata: object
  status: string
  created_at: timestamp
  updated_at: timestamp
  vector_id: string (reference to Milvus)
```

### Elasticsearch
```
新index: `knowledge_base_documents`
document structure:
  {
    "id": "string",
    "tenant_id": "string",
    "title": "string",
    "category": "string",
    "content": "string",
    "tags": ["array"],
    "created_at": "timestamp"
  }
```

### Milvus
```
新collection: `kb_documents_embeddings`
schema:
  document_id: string
  tenant_id: string
  embedding: array<float32>[1536]  // OpenAI/Claude embedding dimension
  metadata: object
```

### Kafka audit trail
```
所有KB查询记录到audit_outbox:
{
  "event_type": "kb_query",
  "actor_id": integer,
  "tenant_id": string,
  "query_type": "keyword|semantic|routing|rag",
  "query": string,
  "results_count": integer,
  "timestamp": ISO8601
}
```

---

## 参考和建议

### 开源参考
- [LangChain](https://github.com/langchain-ai/langchain) - RAG框架
- [LlamaIndex](https://github.com/run-llama/llama_index) - 文档索引
- [Milvus文档](https://milvus.io/docs) - 向量搜索
- [Elasticsearch文档](https://www.elastic.co/guide/en/elasticsearch/reference) - 全文搜索

### 建议优先级
1. **高优先** (Week 1-2): 2.1 keyword search + 1.1 document CRUD
2. **中优先** (Week 3-4): 2.2 semantic search
3. **低优先** (Week 5+): 2.3 routing extraction + 2.4 RAG (可延迟到Phase 2.2)

---

## 下一步

1. **Membership团队审阅** 此方案
2. **确认**:
   - MongoDB schema和索引策略
   - Milvus/Elasticsearch与Membership的集成方式
   - LLM服务的调用方式 (内部服务还是第三方API?)
   - 成本预算和timeline
3. **实现**: 按优先级开发API
4. **BPMN-MCP/FORM-MCP集成**: 等KB API ready后集成

---

**文档状态**: ✅ 提议完成，待Membership团队反馈
**预期反馈周期**: 3-5个工作日
