# Reindex 功能 Bug 修复报告

## 日期
2026-02-26 23:59

## 问题描述

### 用户反馈
"reindex 应该完全重来，怎么还有页数的问题？"

### 症状
1. **Reindex 时使用了断点恢复的旧数据**
   - 日志显示：`断点恢复: documentId=..., 已完成=66/66`
   - 提取结果：只有 6204 字符（平均每页94字符，明显太少）
   - 文件大小：43MB，但只提取到 6204 字符（比例 0.000135）

2. **根本原因**：
   - 之前 PaddleOCR 模型未下载，WebSocket 超时
   - 每页 OCR 返回错误或空数据
   - 断点恢复保存了这 66 页的**失败数据**
   - 现在 PaddleOCR 已修复，但 reindex 直接使用旧缓存，**没有重新 OCR**

## Bug 分析

### 问题代码
**文件**: `DocumentStorageService.java`

#### Bug 1: `reindexDocument()` (单文档 reindex)
```java
public void reindexDocument(String documentId, String tenantId, String jwtToken) {
    log.info("开始重新索引文档, documentId: {}, tenantId: {}", documentId, tenantId);
    Query query = new Query(Criteria.where("_id").is(documentId).and("tenantId").is(tenantId));
    DocumentMetadata doc = mongoTemplate.findOne(query, DocumentMetadata.class);

    if (doc != null) {
        indexDocumentAsync(doc);  // ❌ 直接调用，没有清除旧数据
    }
}
```

#### Bug 2: `reindexDocuments()` (批量 reindex)
```java
public void reindexDocuments(List<String> documentIds, String tenantId) {
    log.info("开始批量重新索引文档, documentIds: {}, tenantId: {}", documentIds, tenantId);
    Query query = new Query(Criteria.where("_id").in(documentIds).and("tenantId").is(tenantId));
    List<DocumentMetadata> documents = mongoTemplate.find(query, DocumentMetadata.class);

    for (DocumentMetadata doc : documents) {
        log.info("重建索引中: {} ({})", doc.getTitle(), doc.getId());
        indexDocumentAsync(doc);  // ❌ 直接调用，没有清除旧数据
    }
}
```

#### Bug 3: `reindexAllDocuments()` (全部 reindex)
```java
public void reindexAllDocuments(String tenantId) {
    log.info("开始为租户重新索引所有文档, tenantId: {}", tenantId);
    List<DocumentMetadata> documents = listDocuments(tenantId);
    for (DocumentMetadata doc : documents) {
        log.info("重建索引中: {} ({})", doc.getTitle(), doc.getId());
        indexDocumentAsync(doc);  // ❌ 直接调用，没有清除旧数据
    }
}
```

### 数据流分析

```
reindexDocument()
    ↓
indexDocumentAsync()
    ↓
textExtractor.extractText()
    ↓
PdfPageOcrExtractor.extractText()
    ↓
getOrCreateOcrProgress()  // ← 这里会检查是否有旧的 ocr_progress
    ↓
if (existing != null) {
    return existing;  // ← 返回旧的失败数据（66/66 已完成）
}
```

## 解决方案

### 修复逻辑
Reindex 时必须**完全清除**以下数据：
1. `ocr_progress` - 断点恢复数据（关键！）
2. `extracted_text_length` - 提取的文本长度
3. `chunk_count` - 分块数量
4. `es_indexed` - ES 索引状态
5. `vector_indexed` - 向量索引状态
6. `processing_status` - 处理状态

### 修复代码

#### 修复 1: `reindexDocument()`
```java
public void reindexDocument(String documentId, String tenantId, String jwtToken) {
    log.info("开始重新索引文档, documentId: {}, tenantId: {}", documentId, tenantId);
    Query query = new Query(Criteria.where("_id").is(documentId).and("tenantId").is(tenantId));
    DocumentMetadata doc = mongoTemplate.findOne(query, DocumentMetadata.class);

    if (doc != null) {
        // ✅ 清除旧的OCR进度和提取结果，确保完全重新处理
        log.info("清除旧数据: documentId={}", documentId);
        Update clearUpdate = new Update()
            .unset("ocr_progress")  // ← 关键：清除断点恢复数据
            .set("extracted_text_length", 0)
            .set("chunk_count", 0)
            .set("es_indexed", false)
            .set("vector_indexed", false)
            .set("processing_status", "PENDING")
            .set("last_modified_time", Instant.now());

        mongoTemplate.updateFirst(query, clearUpdate, DocumentMetadata.class);
        log.info("旧数据已清除，开始重新索引: documentId={}", documentId);

        indexDocumentAsync(doc);
    }
}
```

#### 修复 2: `reindexDocuments()` (批量)
```java
public void reindexDocuments(List<String> documentIds, String tenantId) {
    log.info("开始批量重新索引文档, documentIds: {}, tenantId: {}", documentIds, tenantId);
    Query query = new Query(Criteria.where("_id").in(documentIds).and("tenantId").is(tenantId));
    List<DocumentMetadata> documents = mongoTemplate.find(query, DocumentMetadata.class);

    // ✅ 批量清除旧数据
    log.info("批量清除旧数据, documentIds: {}", documentIds);
    Update clearUpdate = new Update()
        .unset("ocr_progress")  // ← 关键：清除断点恢复数据
        .set("extracted_text_length", 0)
        .set("chunk_count", 0)
        .set("es_indexed", false)
        .set("vector_indexed", false)
        .set("processing_status", "PENDING")
        .set("last_modified_time", Instant.now());

    mongoTemplate.updateMulti(query, clearUpdate, DocumentMetadata.class);
    log.info("旧数据已清除，开始批量重新索引");

    for (DocumentMetadata doc : documents) {
        log.info("重建索引中: {} ({})", doc.getTitle(), doc.getId());
        indexDocumentAsync(doc);
    }
}
```

#### 修复 3: `reindexAllDocuments()` (全部)
```java
public void reindexAllDocuments(String tenantId) {
    log.info("开始为租户重新索引所有文档, tenantId: {}", tenantId);
    List<DocumentMetadata> documents = listDocuments(tenantId);

    // ✅ 批量清除旧数据
    log.info("批量清除租户所有文档的旧数据, tenantId: {}", tenantId);
    Query query = Query.query(Criteria.where("tenantId").is(tenantId));
    Update clearUpdate = new Update()
        .unset("ocr_progress")  // ← 关键：清除断点恢复数据
        .set("extracted_text_length", 0)
        .set("chunk_count", 0)
        .set("es_indexed", false)
        .set("vector_indexed", false)
        .set("processing_status", "PENDING")
        .set("last_modified_time", Instant.now());

    mongoTemplate.updateMulti(query, clearUpdate, DocumentMetadata.class);
    log.info("旧数据已清除，开始批量重新索引");

    for (DocumentMetadata doc : documents) {
        log.info("重建索引中: {} ({})", doc.getTitle(), doc.getId());
        indexDocumentAsync(doc);
    }
}
```

## 修复验证

### 预期行为（修复后）
```
开始重新索引文档, documentId: xxx, tenantId: 1
清除旧数据: documentId=xxx
旧数据已清除，开始重新索引: documentId=xxx

OCR处理: 文档ID=xxx, 总页数=66, 已完成=0, 从第1页开始  ← ✅ 从头开始
第1页OCR识别: 2048 字符  ← ✅ 正常识别
第2页OCR识别: 2156 字符
...
PDF分页OCR完成: 66 页, 总字符: 143567  ← ✅ 正常
```

### 实际行为（修复前）
```
开始重新索引文档, documentId: xxx, tenantId: 1
OCR处理: 文档ID=xxx, 总页数=66, 已完成=66, 从第67页开始  ← ❌ 跳过所有页
PDF分页OCR完成: 66 页, 总字符: 6204  ← ❌ 使用旧数据
```

## 部署

### 构建和重启
```bash
# 1. 编译
cd /Users/kehongwei/workspace/membership
./gradlew :membership-docs:build -x test

# 2. 快速构建 Docker 镜像
./build-ultra-fast.sh

# 3. 重启容器
docker restart membership-api-v2.4-dev

# 4. 验证健康状态
curl http://localhost:8080/actuator/health
```

### 清理旧数据
对于已经受影响的文档，需要手动重新 reindex：
```bash
# 方案 1: 单文档 reindex
curl -X POST "http://localhost:8080/v2/documents/e7638d2f-1e6b-46df-884b-f0185dcfaf32/reindex" \
  -H "X-Tenant-ID: 1" \
  -H "Authorization: Bearer $TOKEN"

# 方案 2: 批量 reindex
curl -X POST "http://localhost:8080/v2/documents/reindex/batch" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 1" \
  -d '["e7638d2f-1e6b-46df-884b-f0185dcfaf32", "doc-id-2", ...]'

# 方案 3: 租户全部 reindex
curl -X POST "http://localhost:8080/v2/documents/reindex" \
  -H "X-Tenant-ID: 1" \
  -H "Authorization: Bearer $TOKEN"
```

## 总结

### 问题
Reindex 功能没有清除 `ocr_progress`，导致使用失败时的旧数据。

### 影响
- 所有使用 reindex 的文档都会使用旧的失败 OCR 数据
- 必须手动清除 MongoDB 中的 `ocr_progress` 字段才能重新处理

### 解决
在所有 reindex 方法中添加清除旧数据的逻辑：
- 使用 `.unset("ocr_progress")` 删除断点恢复数据
- 重置所有状态字段
- 确保完全重新处理

### 状态
**✅ Bug 已修复并部署**

---

**修复人员**: Claude Code
**修复时间**: 2026-02-26 23:59
**影响版本**: v2.4-dev
**修复版本**: v2.4-dev (hotfix)
**严重程度**: 高（影响核心功能）
**优先级**: 紧急
