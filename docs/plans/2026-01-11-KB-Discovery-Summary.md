# 知识库发现总结 (Knowledge Base Discovery Summary)

**日期**: 2026-01-11
**发现**: Membership v2.4已设计完整的文档引擎，为BPMN-MCP/FORM-MCP提供了坚实基础

---

## 关键发现 🎯

### 之前的假设
- ❌ 知识库API完全缺失，需要从零设计
- ❌ Milvus向量库闲置，没有开放
- ❌ Membership只有组织管理，没有KB能力

### 实际情况
- ✅ **Membership v2.4已设计enterprise_platform_expansion_plan**
- ✅ **membership-docs模块已设计完整的文档引擎**
- ✅ **数据模型、服务实现已完成**，仅缺REST API层

---

## Membership v2.4文档引擎架构

### 存储层 (MongoDB)
```
collections:
├── documents
│   ├── document_id: "DOC-2024-001"
│   ├── tenant_id: "tenant_123"
│   ├── title: "产品需求文档"
│   ├── content_extracted: "文本内容..." (via Apache Tika)
│   ├── storage_type: "minio" | "gridfs"
│   ├── s3_key: "tenant_123/2024/11/DOC-2024-001.docx"
│   ├── tags, category, metadata
│   └── es_indexed: true, vector_indexed: true
│
└── document_permissions
    ├── document_id
    ├── permission_type: "role|user|org_unit"
    ├── access_level: "read|read_write|admin"
    └── expires_at (optional)
```

### 索引层 (Elasticsearch)

**Index 1: documents_text (全文搜索)**
- Field: content (IK中文分词)
- Analyzer: ik_smart_analyzer
- 用途: 关键词搜索

**Index 2: doc_embeddings (语义搜索)**
- Field: embedding (dense_vector, 768维)
- Similarity: cosine
- Index type: HNSW (m=16, ef_construction=100)
- 用途: 向量相似度搜索

### 搜索层 (Hybrid Search)

**HybridSearchService**:
- 算法: RRF (Reciprocal Rank Fusion)
- 权重: keyword_weight = 0.3, semantic_weight = 0.7
- 结果: 融合关键词和语义搜索

### 权限层 (Multi-Tenant)
- 多租户隔离: tenant_id + Elasticsearch sharding
- 权限管理: role/user/org_unit级别的访问控制
- 审计跟踪: 所有操作记录到audit_outbox

---

## BPMN-MCP和FORM-MCP的需求

### Phase 2.1 需要 (最小MVP)
```
✅ 关键词搜索 (Keyword Search)
   从Elasticsearch documents_text查询策略文档
   示例: "approval policy > 50000"
   结果: ["Pharmaceutical approval requires CFO", ...]
```

### Phase 2.2 需要 (完整功能)
```
✅ 语义搜索 (Semantic Search)
   从Elasticsearch doc_embeddings查询相关文档
   示例: "approval routing for pharmaceutical items"
   结果: 相关度最高的文档 + 相似度分数

✅ 混合搜索 (Hybrid Search)
   结合关键词和语义 (RRF融合)

✅ RAG问答 (RAG Query)
   LLM基于检索结果生成答案
```

---

## 需要补充的REST API

基于Membership v2.4文档引擎，需要添加这些API endpoint：

### 1. 关键词搜索
```
GET /v2/knowledge-base/search
?tenant_id=string
&query=string
&category=policy|template|rule
&limit=20
&offset=0

Response: {
  "results": [
    {
      "document_id": "DOC-2024-001",
      "title": "Approval Policy v2.1",
      "snippet": "... 包含关键词的摘录 ...",
      "relevance_score": 0.95
    }
  ],
  "total": 42
}
```

### 2. 语义搜索
```
POST /v2/knowledge-base/semantic-search
{
  "tenant_id": "string",
  "query": "What's the approval policy for pharma > 50k?",
  "limit": 10,
  "threshold": 0.7
}

Response: {
  "results": [
    {
      "document_id": "DOC-2024-001",
      "title": "Pharmaceutical Approval Policy",
      "content": "完整文档内容",
      "similarity_score": 0.92
    }
  ]
}
```

### 3. 混合搜索
```
POST /v2/knowledge-base/hybrid-search
{
  "tenant_id": "string",
  "query": "approval pharmaceutical 50000",
  "keyword_weight": 0.3,
  "semantic_weight": 0.7
}

Response: {
  "results": [融合了关键词和语义的结果],
  "search_explanation": "使用RRF融合算法..."
}
```

### 4. RAG问答
```
POST /v2/knowledge-base/rag-query
{
  "tenant_id": "string",
  "question": "Can we approve $500k without CFO?"
}

Response: {
  "answer": "According to Policy v2.1 section 3.2, ...",
  "sources": [
    {
      "document_id": "DOC-2024-001",
      "title": "Pharmaceutical Approval Policy",
      "excerpt": "... 用于生成回答的摘录 ..."
    }
  ],
  "confidence": 0.88
}
```

---

## 实现时间表

### 立即可用 (Week 1)
- ✅ Membership REST API (Members/Roles/Orgs) - 已有
- ✅ BPMN-MCP with hardcoded policies - 可开始

### 1-2周内 (Phase 2.1末)
- ✅ KB Keyword Search API - Membership补充
- ✅ BPMN-MCP集成keyword search

### 2-3周内 (Phase 2.2初)
- ✅ KB Semantic Search API - Membership补充
- ✅ KB RAG Query API - Membership补充
- ✅ BPMN-MCP/FORM-MCP升级到完整KB功能

---

## 行动项

### 对于Membership团队
1. 确认membership-docs模块REST API实现计划
2. 补充这4个查询API endpoint:
   - GET /v2/knowledge-base/search
   - POST /v2/knowledge-base/semantic-search
   - POST /v2/knowledge-base/hybrid-search
   - POST /v2/knowledge-base/rag-query
3. 与AICMDEngine团队协调集成时间

### 对于AICMDEngine团队
1. **Phase 2.1 (Week 1-2)**:
   - 实现BPMN-MCP with hardcoded policies
   - 不依赖KB API
   - 完整的BPMN生成功能

2. **Phase 2.1末 (Week 3-4)**:
   - 集成keyword search API
   - 验证API正确性

3. **Phase 2.2 (Week 5-8)**:
   - 集成semantic search
   - 实现动态路由
   - RAG增强的LLM提示

---

## 总结

| 方面 | 之前假设 | 实际情况 | 影响 |
|------|---------|--------|------|
| **文档存储** | ❌ 缺失 | ✅ MongoDB已设计 | ✅ 无额外工作 |
| **全文索引** | ❓ 可能缺失 | ✅ ES已设计 | ✅ 1-2周API |
| **向量索引** | ❌ 闲置 | ✅ ES 768维dense_vector已设计 | ✅ 2-3周充分利用 |
| **权限管理** | ❓ 待定 | ✅ MongoDB权限表已设计 | ✅ 无额外工作 |
| **多租户** | ✓ 已有 | ✅ 文档引擎已支持 | ✅ 开箱即用 |
| **REST API** | ❌ 完全缺失 | 🔄 需补充 | 🔄 1-3周实现 |

**结论**: Membership v2.4文档引擎为BPMN-MCP/FORM-MCP提供了坚实基础。
**风险**: 仅为REST API层需要补充，不存在核心功能缺口。
**建议**: 立即开始BPMN-MCP开发，与Membership团队并行推进KB API补充。

---

**文档状态**: ✅ 发现已记录，计划已更新
**下一步**: 发送KB API需求给Membership团队，并行启动BPMN-MCP实现
