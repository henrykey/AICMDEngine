# PaddleOCR MCP 快速安装指南

**手动安装步骤** - 如果自动安装脚本失败，请按照以下步骤手动安装。

## 前提条件

- Python 3.8+
- pip
- 网络连接（用于下载模型）

## 安装步骤

### 1. 克隆PaddleOCR仓库

```bash
cd /Users/kehongwei/workspace/AICMDEngine

# 创建external_mcp目录
mkdir -p external_mcp

# 克隆仓库（如果git clone失败，可以从GitHub下载zip包）
git clone https://github.com/PaddlePaddle/PaddleOCR.git external_mcp/PaddleOCR

# 或者使用镜像（如果GitHub访问慢）
git clone https://gitee.com/PaddlePaddle/PaddleOCR.git external_mcp/PaddleOCR
```

### 2. 安装依赖

```bash
cd external_mcp/PaddleOCR

# 安装PaddleOCR MCP Server
pip install -e mcp_server

# 安装PaddleOCR及文档解析依赖
pip install "paddleocr>=2.7" opencv-python-headless pillow

# 可选：安装文档解析增强功能
pip install pdf2docx PyMuPDF pdfplumber
```

### 3. 验证安装

```bash
# 测试PaddleOCR导入
python -c "from paddleocr import PaddleOCR; print('✓ PaddleOCR安装成功')"

# 测试MCP Server
python -m paddleocr_mcp --help
```

### 4. 配置AICMDEngine

编辑 `/Users/kehongwei/workspace/AICMDEngine/.env` 文件，在`EXTERNAL_MCPS`配置中添加：

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

**重要配置说明**：
- `command`: 修改为你的Python路径
- `args[0]`: `-m paddleocr_mcp` - 以模块方式运行MCP Server
- `args[1]`: `--pipeline OCR` - 使用标准OCR管道
- `args[2]`: `--ppocr_source local` - 使用本地模型
- `timeout`: **240秒** - 首次启动需要下载模型（~200MB），约2-3分钟
- `env.PYTHONPATH`: PaddleOCR安装路径
- `env.PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK`: "True" - 跳过模型源连接检查，加快启动

**⚠️ 首次启动注意事项**：
- **首次启动**需要下载OCR模型（约200MB），包括：
  - PP-OCRv5_server_det (84MB) - 文本检测模型
  - PP-OCRv5_server_rec (81MB) - 文本识别模型
  - 其他辅助模型 (~35MB)
- 下载时间：约2-3分钟（取决于网络速度）
- 模型缓存位置：`~/.paddlex/official_models/`
- **后续启动**：使用缓存模型，启动时间约3-5秒
- 如果首次启动超时，请增加timeout值到300秒或更多

### 5. 重启AICMDEngine

```bash
cd /Users/kehongwei/workspace/AICMDEngine

# 停止现有服务
pkill -f "uvicorn src.main:app"

# 启动服务
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. 验证MCP注册

```bash
# 检查健康状态
curl http://localhost:8000/api/mcp/health

# 预期输出（应包含paddleocr）:
{
  "status": "ok",
  "total_servers": 6,
  "servers": ["kb_mcp", "form_mcp", "bpmn_mcp", "membership_mcp", "word", "paddleocr"]
}

# 查看PaddleOCR工具列表
curl http://localhost:8000/api/mcp/servers/paddleocr/tools
```

## 常见问题

### Q1: git clone 失败

**解决方案**: 使用GitHub镜像或下载zip包

```bash
# 方法1: 使用Gitee镜像
git clone https://gitee.com/PaddlePaddle/PaddleOCR.git external_mcp/PaddleOCR

# 方法2: 下载zip包
wget https://github.com/PaddlePaddle/PaddleOCR/archive/refs/heads/develop.zip
unzip develop.zip -d external_mcp/
mv external_mcp/PaddleOCR-develop external_mcp/PaddleOCR
```

### Q2: pip install 速度慢

**解决方案**: 使用国内镜像源

```bash
pip install -e mcp_server -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install paddleocr -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q3: MCP注册失败

**检查清单**:
1. Python路径是否正确
2. PYTHONPATH是否设置正确
3. PaddleOCR是否安装成功
4. 手动测试MCP Server:
   ```bash
   python -m paddleocr_mcp --help
   ```

### Q4: 模型下载失败

**解决方案**: 手动下载模型文件

```bash
# 创建模型目录
mkdir -p ~/.paddleocr/whl/det/ch/
mkdir -p ~/.paddleocr/whl/rec/ch/
mkdir -p ~/.paddleocr/whl/cls/

# 从百度网盘下载模型（参考PaddleOCR文档）
# 或使用自动下载（首次运行时会自动下载）
python -c "from paddleocr import PaddleOCR; ocr = PaddleOCR(use_angle_cls=True, lang='ch')"
```

### Q5: 如何确认模型已下载？

**检查模型文件**：
```bash
# 查看PaddleX模型目录
ls -lh ~/.paddlex/official_models/

# 应该看到以下目录：
# - PP-OCRv5_server_det/  (~84MB)
# - PP-OCRv5_server_rec/  (~81MB)
# - PP-LCNet_x1_0_doc_ori/  (~6.6MB)
# - UVDoc/  (~31MB)

# 查看模型文件详情
ls -lh ~/.paddlex/official_models/PP-OCRv5_server_det/
# 应该包含：inference.pdmodel, inference.pdiparams 等
```

**预期启动日志**：
```
# 首次启动（下载模型）：
2026-02-21 XX:XX:XX - src.mcp.external_mcp - INFO - Starting external MCP 'paddleocr'
Downloading models from HuggingFace...
[模型下载日志，2-3分钟]
2026-02-21 XX:XX:XX - src.mcp.external_mcp - INFO - Connected to external MCP 'paddleocr'

# 后续启动（使用缓存）：
2026-02-21 XX:XX:XX - src.mcp.external_mcp - INFO - Starting external MCP 'paddleocr'
2026-02-21 XX:XX:XX - src.mcp.external_mcp - INFO - Connected to external MCP 'paddleocr'
# 启动时间：3-5秒
```

### Q6: WebSocket 连接失败 - "did not receive a valid HTTP response"

**症状**: 测试脚本报告 WebSocket 连接失败，但 HTTP 登录成功

**原因**: 系统代理设置干扰了 WebSocket 连接

**检查是否有代理**:
```bash
env | grep -i proxy
```

**解决方案 1 - 临时禁用代理**（推荐用于测试）:
```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
```

**解决方案 2 - 设置 NO_PROXY**:
```bash
export NO_PROXY=localhost,127.0.0.1
```

**解决方案 3 - 永久配置**:
在 `~/.zshrc` 或 `~/.bashrc` 中添加：
```bash
export NO_PROXY=localhost,127.0.0.1
```

## 下一步

安装完成后，请查看完整文档：
- `/Users/kehongwei/workspace/AICMDEngine/docs/PADDELEOCR_MCP_INTEGRATION.md`

包含：
- 详细的配置说明
- 测试验证步骤
- 水印处理方案
- 故障排除指南
