# PDF OCR 测试使用指南

## 概述

本测试脚本用于验证 PaddleOCR MCP 服务通过 MCP Router 调用的功能。

## 前置条件

### 1. 服务依赖

必须启动以下服务：

- **MCP Router** (端口 8000)
  ```bash
  cd /Users/kehongwei/workspace/AICMDEngine
  python -m src.main
  ```

- **Membership Service** (端口 8080) - 用于认证

- **PaddleOCR MCP Server** - 由 MCP Router 自动管理

### 2. Python 环境

```bash
# 安装依赖
pip install websockets aiohttp pdf2image Pillow

# Mac 系统需要额外安装 poppler
brew install poppler
```

### 3. 网络配置

**重要：如果设置了代理，需要排除本地地址**

```bash
# 临时禁用代理（测试时）
unset http_proxy https_proxy

# 或者设置 NO_PROXY
export NO_PROXY=localhost,127.0.0.1
```

## 测试脚本位置

```bash
/Users/kehongwei/workspace/membership/AIPlanner/tests/test_pdf_ocr_with_pages.py
```

## 使用方法

### 基本用法

```bash
# 进入 membership 目录
cd /Users/kehongwei/workspace/membership

# 测试单页（第25页）
python AIPlanner/tests/test_pdf_ocr_with_pages.py --pages 25

# 测试多页
python AIPlanner/tests/test_pdf_ocr_with_pages.py --pages 1,5,10

# 测试页面范围
python AIPlanner/tests/test_pdf_ocr_with_pages.py --pages 1-10

# 测试随机N页
python AIPlanner/tests/test_pdf_ocr_with_pages.py --random 3

# 测试前N页
python AIPlanner/tests/test_pdf_ocr_with_pages.py --first 5
```

### 高级选项

```bash
# 指定用户名密码
python AIPlanner/tests/test_pdf_ocr_with_pages.py --username admin --password admin123 --pages 1

# 强制重新登录（忽略已保存的 token）
python AIPlanner/tests/test_pdf_ocr_with_pages.py --force-login --pages 1
```

## 测试输出说明

### 成功输出

```
✓ WebSocket连接成功 (JWT认证通过)
✓ 初始化完成
✓ 成功提取 1 页图像
✓ OCR提取成功!
  处理时间: 22.90 秒

文本统计:
  总字符数: 1078
  非空行数: 66
  中文字符数: 798
```

### 失败诊断

如果测试失败，按以下步骤排查：

#### 1. 检查服务状态

```bash
# 检查 MCP Router
lsof -i :8000

# 检查 Membership Service
lsof -i :8080
```

#### 2. 检查网络连接

```bash
# 测试 HTTP 登录
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 检查代理设置
env | grep -i proxy
```

#### 3. 运行诊断脚本

```bash
python AIPlanner/tests/diagnose_env.py
```

#### 4. 查看详细错误

```bash
# 运行测试并查看完整错误信息
python AIPlanner/tests/test_pdf_ocr_with_pages.py --pages 1 2>&1
```

## 常见问题

### Q1: "did not receive a valid HTTP response"

**原因**: 代理设置干扰了 WebSocket 连接

**解决**:
```bash
unset http_proxy https_proxy
```

### Q2: "Cannot connect to host localhost:8000"

**原因**: MCP Router 未启动

**解决**: 启动 MCP Router 服务

### Q3: "ModuleNotFoundError: No module named 'xxx'"

**原因**: 缺少 Python 依赖

**解决**:
```bash
pip install websockets aiohttp pdf2image Pillow
```

### Q4: "PDF文件不存在"

**原因**: 默认测试 PDF 路径不正确

**解决**: 检查脚本中的 `PDF_PATH` 变量，或修改为实际路径

## 测试结果验证

成功测试应包含以下要素：

1. ✓ Token 验证通过
2. ✓ WebSocket 连接成功
3. ✓ Initialize 握手完成
4. ✓ OCR 工具调用成功
5. ✓ 提取到文本内容
6. ✓ 中文字符统计正确

## 相关文档

- [PaddleOCR MCP 集成文档](/Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_MCP_INTEGRATION.md)
- [MCP 配置指南](/Users/kehongwei/workspace/AICMDEngine/docs/MCP_CONFIGURATION_GUIDE.md)
- [Membership API 文档](http://localhost:8080/swagger-ui.html)
