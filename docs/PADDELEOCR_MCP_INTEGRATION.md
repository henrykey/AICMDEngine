# PaddleOCR MCP 集成方案

**版本**: v1.0
**创建日期**: 2026-02-20
**适用场景**: 中英文OCR识别，处理带水印的国家标准PDF文档

---

## 📋 目录

1. [方案概述](#方案概述)
2. [技术架构](#技术架构)
3. [PaddleOCR MCP Server](#paddleocr-mcp-server)
4. [水印处理方案](#水印处理方案)
5. [集成步骤](#集成步骤)
6. [配置说明](#配置说明)
7. [测试验证](#测试验证)
8. [故障排除](#故障排除)

---

## 方案概述

### 核心目标

1. **中英文OCR识别** - 优先支持中文和英文的文档文字识别
2. **水印处理** - 处理带水印的中国国家标准PDF（建筑标准等）
3. **标准化集成** - 通过标准MCP协议集成到AICMDEngine
4. **智能选择** - docintel根据文档类型自动选择合适的MCP服务

### 技术选型

| 组件 | 技术选择 | 理由 |
|------|---------|------|
| OCR引擎 | **PaddleOCR** | 中文优化最强，开源免费 |
| MCP协议 | **标准MCP (JSON-RPC 2.0)** | AICMDEngine已支持 |
| 传输方式 | **stdio** | 标准MCP传输方式 |
| 水印处理 | **OpenCV + PaddleOCR** | 参考[hsloner文章](https://m.blog.csdn.net/hsloner/article/details/146557503) |
| 文档解析 | **PP-StructureV3** | PaddleOCR官方文档解析 |

---

## 技术架构

### 整体架构图

```
docintel文档导入
    ↓ 根据content_type智能选择
MCP Router (AICMDEngine)
    ↓ stdio传输
PaddleOCR MCP Server (外部进程)
    ↓ 调用
┌─────────────────────────────────┐
│ PaddleOCR Pipeline              │
├─────────────────────────────────┤
│ 1. OpenCV预处理 (去水印)         │
│ 2. 文字检测 (DBNet)             │
│ 3. 文字识别 (CRNN)              │
│ 4. 方向分类 (AngleClassifier)    │
│ 5. 后处理 (排版恢复)            │
└─────────────────────────────────┘
    ↓ 返回识别文字
docintel存储到知识库
```

### 数据流

```
PDF/图片文件
    ↓
ExtractionOrchestrator (docintel)
    ↓ content_type: application/pdf, image/png
McpClient.findToolsForContentType()
    ↓
PaddleOCR MCP (从MCP Router发现)
    ↓
工具调用: tools/call
    ↓
PaddleOCR处理结果 (文字内容)
```

---

## PaddleOCR MCP Server

### 官方资源

- **GitHub仓库**: https://github.com/PaddlePaddle/PaddleOCR
- **官方文档**: https://github.com/PaddlePaddle/PaddleOCR/blob/develop/README.md
- **MCP Server文档**: https://github.com/PaddlePaddle/PaddleOCR/tree/develop/mcp_server
- **安装教程**: [CSDN - PaddleOCR MCP Server实战](https://baijiahao.baidu.com/s?id=1843052215897808080)

### 特性

✅ **中英文双语支持** - 80+种语言识别
✅ **轻量级模型** - CPU模式即可运行
✅ **GPU加速** - 支持CUDA/MKL加速
✅ **文档解析** - PP-StructureV3支持版面分析
✅ **倾斜矫正** - 自动文本方向检测
✅ **多格式支持** - PDF、图片、扫描件

### 安装方式

#### 方法1: 从源码安装 (推荐)

```bash
# 1. 克隆仓库
git clone https://github.com/PaddlePaddle/PaddleOCR.git
cd PaddleOCR

# 2. 安装MCP Server
pip install -e mcp_server

# 3. 安装依赖
pip install paddleocr[doc-parser]

# 4. 验证安装
paddleocr_mcp --help
```

#### 方法2: 直接安装 (稳定版)

```bash
# 安装PaddleOCR及MCP支持
pip install "paddleocr>=2.7"
pip install "paddleocr-mcp>=0.1.0"

# 验证
python -c "from paddleocr import PaddleOCR; print('PaddleOCR installed successfully')"
```

### 运行方式

#### stdio模式 (推荐用于AICMDEngine)

```bash
# 标准OCR管道
paddleocr_mcp --pipeline OCR --ppocr_source local

# 带文档解析
paddleocr_mcp --pipeline PP-StructureV3 --ppocr_source local

# 自定义端口和协议
paddleocr_mcp --pipeline OCR --ppocr_source local --port 8234 --http
```

#### 配置参数说明

| 参数 | 说明 | 默认值 | 推荐值 |
|------|------|--------|--------|
| `--pipeline` | 处理管道类型 | OCR | OCR / PP-StructureV3 |
| `--ppocr_source` | OCR模型来源 | local | local (本地) / cloud (云端) |
| `--port` | HTTP端口 | 8234 | 8234 |
| `--http` | 启用HTTP服务 | False | True (可选) |

---

## 水印处理方案

### 问题分析

中国国家标准PDF常见水印类型：
1. **文字水印** - "中国建筑标准研究院"、"仅供学习参考"等
2. **半透明水印** - 淡色文字/Logo水印
3. **背景图案** - 复杂的底纹/图案

### 解决方案

参考：[基于opencv+paddle识别扫描版PDF文件](https://m.blog.csdn.net/hsloner/article/details/146557503)

#### 方案1: OpenCV预处理 + PaddleOCR识别

**原理**：
- 使用OpenCV去除水印干扰
- 保留文字信息
- PaddleOCR识别去水印后的图像

**步骤**：
```python
import cv2
import numpy as np
from paddleocr import PaddleOCR

def remove_watermark(image_path):
    """去除图片水印"""
    img = cv2.imread(image_path)

    # 1. 灰度化
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. 高斯模糊 (抑制水印纹理)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # 3. 自适应阈值 (增强文字，抑制水印)
    binary = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11, 2
    )

    # 4. 形态学操作 (修复断裂文字)
    kernel = np.ones((2, 2), np.uint8)
    processed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    return processed

# 使用示例
processed_img = remove_watermark("watermarked_pdf_page.png")
ocr = PaddleOCR(use_angle_cls=True, lang='ch')
result = ocr.ocr(processed_img, cls=True)
```

#### 方案2: AI去水印 + OCR (复杂场景)

**工具**: [WatermarkRemover-AI](https://github.com/xxx/WatermarkRemover-AI)

**原理**：
- 使用Florence-2模型检测水印区域
- AI inpainting技术去除水印
- PaddleOCR识别处理后的图像

**适用场景**：
- 复杂图案水印
- 多层水印叠加
- 高质量要求场景

---

## 集成步骤

### Step 1: 安装PaddleOCR MCP Server

```bash
# 在AICMDEngine服务器上执行
cd /Users/kehongwei/workspace/AICMDEngine

# 克隆仓库
git clone https://github.com/PaddlePaddle/PaddleOCR.git external_mcp/PaddleOCR
cd external_mcp/PaddleOCR

# 安装MCP Server
pip install -e mcp_server

# 安装完整依赖
pip install paddleocr[doc-parser] opencv-python-headless
```

### Step 2: 配置到AICMDEngine

编辑 `.env` 文件，添加PaddleOCR MCP配置：

```env
EXTERNAL_MCPS='{
  "word": {
    "command": "/Users/kehongwei/.pyenv/versions/3.12.11/bin/python",
    "args": ["/Users/kehongwei/workspace/AICMDEngine/mcp/Office-Word-MCP-Server/word_mcp_server.py"],
    "transport": "stdio",
    "timeout": 60
  },
  "paddleocr": {
    "command": "/Users/kehongwei/.pyenv/versions/3.12.11/bin/python",
    "args": ["-m", "paddleocr_mcp", "--pipeline", "OCR", "--ppocr_source", "local"],
    "transport": "stdio",
    "timeout": 120,
    "env": {
      "PYTHONPATH": "/Users/kehongwei/workspace/AICMDEngine/external_mcp/PaddleOCR"
    }
  }
}'
```

**参数说明**:
- `command`: Python解释器路径
- `args`: MCP Server启动参数
  - `-m paddleocr_mcp`: 以模块方式运行
  - `--pipeline OCR`: 使用标准OCR管道
  - `--ppocr_source local`: 使用本地模型
- `transport`: 使用stdio传输 (标准MCP协议)
- `timeout`: 120秒 (OCR处理较慢，需要更长超时)
- `env.PYTHONPATH`: PaddleOCR模块路径

### Step 3: 重启AICMDEngine

```bash
cd /Users/kehongwei/workspace/AICMDEngine

# 停止现有服务
pkill -f "uvicorn src.main:app"

# 启动服务
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 4: 验证MCP注册

```bash
# 检查MCP健康状态
curl http://localhost:8000/api/mcp/health

# 预期输出:
{
  "status": "ok",
  "total_servers": 6,  # 应该包含paddleocr
  "servers": ["kb_mcp", "form_mcp", "bpmn_mcp", "membership_mcp", "word", "paddleocr"]
}

# 查看PaddleOCR工具列表
curl http://localhost:8000/api/mcp/servers/paddleocr/tools
```

---

## 配置说明

### PaddleOCR MCP 工具列表

注册后，PaddleOCR MCP会暴露以下工具：

| 工具名称 | 描述 | 输入参数 | 输出 |
|---------|------|----------|------|
| `ocr.ocr` | 标准OCR识别 | `filename`, `lang` | 识别文字+坐标 |
| `ocr.structure` | 文档结构分析 | `filename`, `layout` | 版面分析结果 |
| `ocr.table` | 表格识别 | `filename` | 表格数据 |

### 工具输入Schema

```json
{
  "name": "ocr.ocr",
  "description": "Extract text from image using PaddleOCR",
  "inputSchema": {
    "type": "object",
    "properties": {
      "filename": {
        "type": "string",
        "description": "Path to image file or PDF page"
      },
      "lang": {
        "type": "string",
        "description": "Language code (ch, en, ch_en)",
        "default": "ch_en"
      }
    },
    "required": ["filename"]
  }
}
```

### docintel选择策略

docintel的`ServiceSelectionStrategy`需要配置content_type映射：

```python
# ServiceSelectionStrategy.java

CONTENT_TYPE_TO_MCP = {
    "application/pdf": "paddleocr",      # PDF扫描文档
    "image/png": "paddleocr",            # PNG图片
    "image/jpeg": "paddleocr",           # JPEG图片
    "image/tiff": "paddleocr",           # TIFF扫描件
}
```

---

## 测试验证

### 测试1: 中文OCR识别

准备测试图片（包含中文）：

```bash
# 测试调用
curl -X POST "http://localhost:8000/api/mcp/servers/paddleocr/tools/ocr.ocr/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "/path/to/chinese_text.png",
    "lang": "ch"
  }'
```

**预期结果**:
```json
{
  "success": true,
  "data": {
    "text": "识别出的中文文字内容",
    "regions": [
      {"text": "第一行文字", "box": [x1, y1, x2, y2]},
      {"text": "第二行文字", "box": [x1, y1, x2, y2]}
    ]
  }
}
```

### 测试2: 带水印PDF识别

```bash
# 使用docintel API导入PDF
curl -X POST "http://localhost:8080/v2/documents/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/watermarked_gb_standard.pdf" \
  -F "use_mcp=true"
```

**验证点**:
- ✅ docintel自动选择paddleocr MCP
- ✅ PaddleOCR成功识别文字（水印已处理）
- ✅ 识别结果正确存储到知识库

### 测试3: 中英文混合文档

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/paddleocr/tools/ocr.ocr/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "/path/to/mixed_lang_doc.png",
    "lang": "ch_en"
  }'
```

---

## 故障排除

### 问题1: MCP注册失败

**症状**: 日志显示 `Failed to register external MCP 'paddleocr'`

**解决方案**:
```bash
# 1. 检查Python路径
which python
# 确保.env中的command路径正确

# 2. 手动测试PaddleOCR
python -m paddleocr_mcp --help

# 3. 检查PYTHONPATH
echo $PYTHONPATH
```

### 问题2: OCR识别超时

**症状**: `Tool execution timeout`

**解决方案**:
```env
# 增加超时时间
"timeout": 180  # 3分钟

# 或者使用更快的模型
"args": ["-m", "paddleocr_mcp", "--pipeline", "OCR", "--model", "mobile"]
```

### 问题3: 水印去除效果不好

**症状**: 识别结果包含水印文字

**解决方案**:

**方法1: 调整预处理参数**
```python
# 在PaddleOCR MCP Server中添加预处理
blur_kernel = (7, 7)  # 增大模糊核
block_size = 15       # 增大自适应阈值块大小
```

**方法2: 使用AI去水印**
```bash
# 安装WatermarkRemover-AI
pip install watermark-remover-ai

# 在OCR前预处理
python -m watermark_remover input.png output.png
```

### 问题4: 中文识别准确率低

**症状**: 中文识别结果不准确

**解决方案**:

```bash
# 1. 下载更准确的中文模型
cd /Users/kehongwei/.paddleocr/whl
wget https://paddleocr.bj.bcebos.com/PP-OCRv3/chinese/ch_PP-OCRv3_det_infer.tar

# 2. 启用方向分类
# 在args中添加: "--use_angle_cls", "true"

# 3. 使用更大模型
# 在args中添加: "--det_model_dir", "ch_PP-OCRv3_det_infer"
```

---

## 性能优化

### GPU加速 (如果有NVIDIA GPU)

```bash
# 1. 安装GPU版PaddlePaddle
pip install paddlepaddle-gpu

# 2. 配置MCP使用GPU
"env": {
  "CUDA_VISIBLE_DEVICES": "0",
  "USE_GPU": "true"
}
```

### 批量处理优化

对于多页PDF，使用批量处理：

```python
# 伪代码示例
def process_pdf_batch(pdf_path, batch_size=4):
    pages = convert_pdf_to_images(pdf_path)
    results = []

    for i in range(0, len(pages), batch_size):
        batch = pages[i:i+batch_size]
        batch_results = paddleocr.ocr(batch, batch=True)
        results.extend(batch_results)

    return results
```

---

## 扩展阅读

### 官方文档

- [PaddleOCR GitHub](https://github.com/PaddlePaddle/PaddleOCR)
- [PaddleOCR 官方文档](https://github.com/PaddlePaddle/PaddleOCR/blob/develop/README_ch.md)
- [MCP 协议规范](https://modelcontextprotocol.io/specification/2025-11-25/)

### 参考文章

- [基于opencv+paddle处理水印PDF](https://m.blog.csdn.net/hsloner/article/details/146557503) ⭐
- [PaddleOCR MCP Server实战](https://baijiahao.baidu.com/s?id=1843052215897808080)
- [PaddleOCR图像预处理](https://m.blog.csdn.net/gitblog_00299/article/details/151001972)
- [AI水印去除工具WatermarkRemover-AI](https://www.xugj520.cn/archives/ai-watermark-remover-tool.html)

### 相关工具

- [Microsoft MarkItDown](https://github.com/microsoft/markitdown) - 文档转Markdown
- [WatermarkRemover-AI](https://github.com/xxx/WatermarkRemover-AI) - AI去水印
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) - 开源OCR (英文强)

---

**文档维护**: AICMDEngine开发团队
**最后更新**: 2026-02-20
**下一步**: 配置测试并验证水印处理效果
