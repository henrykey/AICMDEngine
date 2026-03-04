# AICMDEngine MCP 测试脚本指南

这个目录包含用于测试AICMDEngine MCP Router集成的Python测试脚本。

## 测试脚本说明

### JWT Token传递测试

#### `test_membership_audit.py`
**目的**: 验证MCP Router自动传递JWT token给工具

**测试内容**:
- JWT token从WebSocket连接自动传递到工具
- 不需要在arguments中手动传递auth_token
- tenant_id从JWT token的tenantId claim自动提取

**使用方法**:
```bash
python test_membership_audit.py
```

**预期结果**: ✓ 无401错误，audit event成功提交

---

#### `test_membership_audit_with_token.py` ⚠️
**目的**: 测试在arguments中显式传递auth_token的行为

**⚠️  警告**: 这可能导致"got multiple values for keyword argument"错误

**原因**: protocol_handler.py:296会自动从context传递auth_token，如果在arguments中也传递，会导致重复参数错误

**参考文档**:
- `/Users/kehongwei/workspace/AICMDEngine/docs/MCP_CONFIGURATION_GUIDE.md`
- `/Users/kehongwei/workspace/AICMDEngine/src/mcp/protocol_handler.py:269-298`

---

### OCR测试

#### `test_pdf_pages_ocr.py` ⭐ **推荐**
**目的**: 演示处理大型PDF文件的最佳实践

**策略**:
1. 使用pdf2image提取单页图像
2. 对每页单独进行OCR (避免超时)
3. 随机选择3-5页进行测试

**优点**:
- ✓ 避免处理整个大文件导致的超时
- ✓ 每页独立处理，失败不影响其他页
- ✓ 更快的反馈和进度显示

**使用方法**:
```bash
# 安装依赖
pip install pdf2image Pillow

# Mac: 需要先安装poppler
brew install poppler

# 运行测试
python test_pdf_pages_ocr.py
```

**参考文档**:
- `/Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_MCP_INTEGRATION.md`
- `/Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_QUICKSTART.md`

---

#### `test_pdf_ocr_random_pages.py`
**目的**: 对整个PDF进行OCR并随机展示部分页面内容

**适用场景**:
- 较小的PDF文件 (<50MB)
- 需要完整文本提取

**⚠️  注意**: 对于大文件(>50MB)，建议使用test_pdf_pages_ocr.py

**使用方法**:
```bash
python test_pdf_ocr_random_pages.py
```

---

#### `test_pdf_ocr_best_practices.py` ⭐ **最佳实践**
**目的**: 综合演示OCR最佳实践

**特性**:
- ✓ 使用正确的参数名 (input_data)
- ✓ 单页提取避免超时
- ✓ JWT token自动传递
- ✓ 实现重试机制
- ✓ 显示详细统计信息

**使用方法**:
```bash
python test_pdf_ocr_best_practices.py
```

**输出示例**:
```
================================================================================
测试总结
================================================================================
成功处理: 4/4 页
总字符数: 3245
总中文字符: 1891
平均每页字符: 811

✓ 最佳实践验证成功!
✓ 参数使用正确 (input_data)
✓ JWT token自动传递 (无需手动传递)
✓ 单页处理避免超时
✓ 重试机制正常工作
================================================================================
```

---

## 核心概念

### JWT Token传递机制

MCP Router自动传递JWT token给工具，无需手动传递:

```python
# ❌ 错误 - 可能导致重复参数错误
"arguments": {
    "auth_token": "...",
    "tenant_id": 1,
    ...
}

# ✅ 正确 - 让MCP Router自动传递
"arguments": {
    "category": "ACCESS",
    "action": "test",
    ...
}
```

**工作流程**:
1. 客户端连接: `ws://localhost:8000/mcp/v1?token=<JWT>`
2. MCP Router提取JWT并保存到context
3. protocol_handler自动传递auth_token给工具 (protocol_handler.py:296)
4. 工具接收有效的auth_token

**参考代码**: `/Users/kehongwei/workspace/AICMDEngine/src/mcp/protocol_handler.py:269-298`

---

### OCR工具参数

**正确参数名**:
- `input_data`: 文件路径、URL或Base64编码数据
- `output_mode`: "simple" 或 "detailed"

**错误参数名** (❌ 不要使用):
- `file_path`
- `image`
- `filename`

**示例**:
```python
{
    "name": "paddleocr.ocr",
    "arguments": {
        "input_data": "/path/to/file.pdf",  # 或 base64, 或 URL
        "output_mode": "simple"
    }
}
```

---

### 大文件处理策略

对于大型PDF文件 (>50MB):

**问题**: 直接处理整个文件会导致超时 (默认60秒)

**解决方案**:
1. 使用pdf2image提取单页图像
2. 每页单独发送到OCR服务
3. 每页图像大小: ~40KB - 2MB
4. 处理时间: 每页 <10秒

**代码示例**:
```python
from pdf2image import convert_from_path

# 提取前10页
images = convert_from_path(PDF_PATH, first_page=1, last_page=10)

# 处理每页
for image in images:
    img_base64 = base64.b64encode(image_bytes)
    result = await paddleocr.ocr(input_data=img_base64)
```

---

## 环境配置

### JWT Token准备

```bash
# 获取JWT token并保存到文件
curl -s -X POST "http://localhost:8080/v2/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | jq -r '.access_token' > /tmp/token.txt
```

### Python依赖

```bash
pip install websockets pdf2image Pillow
```

### Mac系统依赖

```bash
# pdf2image需要poppler
brew install poppler
```

---

## 参考文档

### MCP集成文档
- `/Users/kehongwei/workspace/AICMDEngine/docs/MCP_CONFIGURATION_GUIDE.md` - MCP配置和集成指南
- `/Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_MCP_INTEGRATION.md` - PaddleOCR MCP集成文档
- `/Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_QUICKSTART.md` - PaddleOCR快速开始

### 源码
- `/Users/kehongwei/workspace/AICMDEngine/src/mcp/protocol_handler.py:269-298` - JWT自动传递逻辑
- `/Users/kehongwei/workspace/AICMDEngine/src/mcp/mcp_ws.py:112` - JWT提取逻辑

### 官方文档
- `/Users/kehongwei/workspace/AICMDEngine/external_mcp/PaddleOCR/docs/version3.x/deployment/mcp_server.md` - PaddleOCR MCP官方文档

---

## 故障排查

### 问题: "got multiple values for keyword argument 'auth_token'"

**原因**: arguments中包含了auth_token，但protocol_handler已经自动传递

**解决**: 从arguments中删除auth_token和tenant_id参数

---

### 问题: "Tool 'ocr' execution timed out"

**原因**: 尝试处理整个大文件 (如72MB PDF)

**解决**:
1. 使用test_pdf_pages_ocr.py进行单页处理
2. 或增加MCP配置中的timeout值

---

### 问题: "Missing required argument: input_data"

**原因**: 使用了错误的参数名

**解决**: 确保使用`input_data`而不是`file_path`或`image`

---

### 问题: WebSocket HTTP 403

**原因**: JWT token过期

**解决**: 刷新JWT token
```bash
curl -s -X POST "http://localhost:8080/v2/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | jq -r '.access_token' > /tmp/token.txt
```

---

## 测试输出示例

### 成功的OCR测试

```
================================================================================
处理第 5 页 (2/4)
================================================================================
图像大小: 1920.45 KB

→ 调用paddleocr.ocr工具...
  参数: input_data=<base64> (1920.4 KB)
  参数: output_mode=simple
  注意: 不传递auth_token (MCP Router自动传递)

✓ OCR提取成功!
  处理时间: 6.23 秒

文本统计:
  总字符数: 907
  非空行数: 42
  中文字符数: 529

提取的文本预览:
--------------------------------------------------------------------------------
中华人民共和国国家标准
GB/T 150.1-2024
压力容器 第1部分:通用要求
Pressure vessels—Part 1: General requirements
...
--------------------------------------------------------------------------------
```

---

## 总结

| 测试脚本 | 用途 | 推荐度 |
|---------|------|--------|
| test_pdf_pages_ocr.py | 大文件单页处理 | ⭐⭐⭐⭐⭐ |
| test_pdf_ocr_best_practices.py | 综合最佳实践 | ⭐⭐⭐⭐⭐ |
| test_membership_audit.py | JWT自动传递验证 | ⭐⭐⭐⭐ |
| test_pdf_ocr_random_pages.py | 小文件完整处理 | ⭐⭐⭐ |
| test_membership_audit_with_token.py | 显式传递token (仅测试) | ⭐⭐ |

**核心要点**:
1. ✓ 使用`input_data`参数 (不是file_path)
2. ✓ 大文件使用单页处理
3. ✓ 不要手动传递auth_token/tenant_id
4. ✓ 查看官方文档了解最新配置
