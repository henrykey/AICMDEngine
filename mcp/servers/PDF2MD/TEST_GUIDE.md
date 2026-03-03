# PDF2MD MCP服务测试指南

## 快速开始

### 1. 测试单页处理（通过MCP Router）

```bash
# 使用默认用户名密码 (admin/admin123)
python test_pdf2md_mcp.py --page 1

# 指定用户名密码
python test_pdf2md_mcp.py --username admin --password admin123 --page 1
```

### 2. 测试多页处理

```bash
# 测试第1,2,3页
python test_pdf2md_mcp.py --pages 1,2,3

# 测试第1-5页
python test_pdf2md_mcp.py --pages 1-5
```

### 3. 测试文档级处理

```bash
# 处理整个PDF文档
python test_pdf2md_mcp.py --document
```

### 4. 通过stdio直接连接（跳过Router）

```bash
# 直接启动PDF2MD MCP服务进行测试
python test_pdf2md_mcp.py --stdio-cmd "python -m PDF2MD" --page 1
```

## 测试工具说明

`test_pdf2md_mcp.py` 是一个完整的测试工具，支持：

### 功能特性

1. **Membership认证集成**
   - 自动登录获取JWT token
   - Token缓存（保存到`/tmp/pdf2md_token.txt`）
   - 自动验证token有效性
   - 支持强制重新登录（`--force-login`）

2. **两种连接模式**
   - **WebSocket模式**：通过MCP Router进行认证和路由
   - **stdio模式**：直接启动MCP进程，跳过Router

3. **测试功能**
   - `process_pdf_page` - 单页处理测试
   - `process_pdf_document` - 文档级处理测试
   - Render和RAG双模式数据展示

4. **详细输出**
   - 处理时间统计
   - 数据结构预览
   - 错误诊断信息

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--page N` | 测试指定页码 | - |
| `--pages X,Y,Z` | 测试多个页码（支持范围：1-5） | - |
| `--document` | 测试文档级处理 | - |
| `--username` | Membership用户名 | admin |
| `--password` | Membership密码 | admin123 |
| `--api-url` | MCP Router HTTP地址 | http://localhost:8000 |
| `--ws-url` | MCP Router WebSocket地址 | ws://localhost:8000/mcp/v1 |
| `--stdio-cmd` | stdio模式启动命令 | - |
| `--force-login` | 强制重新登录 | False |

## 返回数据结构

### process_pdf_page返回

```json
{
  "page_type": "normal",
  "page_num": 1,
  "render": {
    "markdown": "Markdown格式内容..."
  },
  "rag": {
    "content": "RAG检索用的纯文本描述..."
  },
  "elements": {
    "tables": [...],
    "figures": [...],
    "formulas": [...]
  },
  "chapters": [...]
}
```

### process_pdf_document返回

```json
{
  "success": true,
  "document": {
    "title": "文档标题",
    "toc": [...],
    "chapters": [...]
  },
  "elements": {
    "tables": [...],
    "figures": [...],
    "formulas": [...]
  },
  "metadata": {
    "total_pages": 100,
    "processed_pages": 100
  }
}
```

## 故障排查

### 问题1：登录失败

```bash
# 检查MCP Router是否运行
lsof -i :8000

# 检查token文件
cat /tmp/pdf2md_token.txt

# 强制重新登录
python test_pdf2md_mcp.py --force-login --page 1
```

### 问题2：MCP服务连接失败

```bash
# 检查PDF2MD MCP服务是否在Router中注册
curl http://localhost:8000/v1/servers

# 查看Router日志
docker logs mcp-router -f
```

### 问题3：PDF文件不存在

```bash
# 修改脚本中的PDF_PATH变量
# 或者创建软链接
ln -s /path/to/your.pdf ~/Documents/GBT16749-2018.pdf
```

## 完整测试流程示例

```bash
# 1. 启动MCP Router（如果未启动）
cd /Users/kehongwei/workspace/AICMDEngine/mcp/proxy
docker-compose up -d

# 2. 测试单页处理
python test_pdf2md_mcp.py --page 1

# 3. 测试多页处理
python test_pdf2md_mcp.py --pages 1,2,3

# 4. 测试文档级处理
python test_pdf2md_mcp.py --document

# 5. 通过stdio直接测试（绕过Router）
python test_pdf2md_mcp.py --stdio-cmd "python -m PDF2MD" --page 1
```

## 参考文档

- [MCP配置指南](/Users/kehongwei/workspace/AICMDEngine/docs/MCP_CONFIGURATION_GUIDE.md)
- [PaddleOCR MCP测试脚本](/Users/kehongwei/workspace/membership/tests/test_pdf_ocr_with_pages.py)
- [FastMCP文档](https://gofastmcp.com)
