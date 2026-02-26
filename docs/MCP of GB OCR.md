# 自定义 MinerU MCP Server 实施方案 (基于 Qwen-VL)

## 1. 方案概述

本方案旨在构建一个轻量级、可定制的 **MCP Server**，核心利用 **MinerU (magic-pdf)** 进行文档版面分析与基础解析，并强制指定 **Qwen-VL (兼容 OpenAI 协议)** 作为 VLM 后端来处理 OCR、公式识别及表格还原。

**核心优势：**
*   **完全可控：** 使用自有的 Qwen-VL API Key，数据不经过第三方解析服务。
*   **针对性优化：** 可针对“国标”文档特点（水印、复杂公式）定制 Prompt 和预处理流程。
*   **无缝集成：** 通过标准 MCP 协议接入你现有的 MCP Router。

---

## 2. 系统架构

```mermaid
graph TD
    Client[MCP Client (Cursor/Claude)] -->|MCP Protocol | Router[你的 MCP Router]
    Router -->|HTTP/Stdio | CustomMCP[自定义 MinerU MCP Server]
    
    subgraph CustomMCP [自定义 MCP Server]
        Tool[parse_document Tool]
        PreProc[图像预处理 (去噪/增强)]
        MagicPDF[MinerU Engine]
        VLM[Qwen-VL Client]
    end
    
    CustomMCP -->|1. 版面分析 | MagicPDF
    CustomMCP -->|2. 复杂区域识别 | VLM
    MagicPDF -->|3. 结果聚合 | Tool
    Tool -->|Markdown/JSON | Router
```

---

## 3. 环境准备

### 3.1 硬件要求
*   **CPU:** 4 核以上 (解析主要消耗 CPU)
*   **内存:** 8GB 以上 (MinerU 加载模型需要)
*   **GPU:** 非必须 (若使用本地模型则需要，本方案使用 API 则不需要)

### 3.2 软件依赖
确保已安装 Python 3.10+。

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装核心依赖
# mineru[full] 包含 magic-pdf 及所有 OCR 依赖
pip install -U "mineru[full]" -i https://mirrors.aliyun.com/pypi/simple

# 安装 MCP  SDK
pip install mcp

# 安装 OpenAI 兼容客户端 (用于调用 Qwen)
pip install openai
```

---

## 4. 项目结构

建议创建以下目录结构：

```text
my-mineru-mcp/
├── .env                  # 环境变量 (API Key 等)
├── config.json           # Magic-PDF 模型配置 (指定 Qwen 接口)
├── server.py             # MCP Server 入口
├── parser.py             # 文档解析核心逻辑
├── vlm_client.py         # Qwen-VL 调用封装
├── requirements.txt      # 依赖列表
└── output/               # 临时输出目录
```

---

## 5. 核心代码实现

### 5.1 环境变量 (`.env`)

```ini
# Qwen-VL 配置 (DashScope 兼容 OpenAI 协议)
QWEN_API_KEY=sk-your-actual-api-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL_NAME=qwen-vl-max-latest

# MinerU 配置
MINERU_OUTPUT_DIR=./output
LOG_LEVEL=INFO
```

### 5.2 Qwen-VL 客户端封装 (`vlm_client.py`)

用于处理需要高精度识别的区域（如公式、复杂表格）。

```python
import os
from openai import OpenAI
from base64 import b64encode

class QwenVLClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("QWEN_API_KEY"),
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self.model = os.getenv("QWEN_MODEL_NAME", "qwen-vl-max-latest")

    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return b64encode(image_file.read()).decode('utf-8')

    def recognize_complex_content(self, image_path: str, task_type: str = "general") -> str:
        """
        调用 Qwen-VL 识别图片内容
        task_type: 'formula', 'table', 'general'
        """
        base64_image = self.encode_image(image_path)
        
        # 针对国标的 Prompt 优化
        prompts = {
            "formula": "请识别图中的数学公式，输出标准的 LaTeX 格式。忽略背景水印。",
            "table": "请识别图中的表格，输出 Markdown 格式。保持行列结构完整。忽略水印。",
            "general": "请识别图中的文字内容，保持原有段落结构。忽略页眉页脚和水印。"
        }
        
        prompt = prompts.get(task_type, prompts["general"])

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            max_tokens=1024
        )
        return response.choices[0].message.content
```

### 5.3 解析逻辑封装 (`parser.py`)

这里整合 MinerU 的版面分析能力和自定义的 Qwen-VL 识别能力。

```python
import os
import json
from magic_pdf.data.data_reader_writer import FileBasedDataWriter
from magic_pdf.data.read_api import read_local_pdf
from magic_pdf.pipe.OCRPipe import OCRPipe
from magic_pdf.config.enums import SupportedPdfParseMethod
from vlm_client import QwenVLClient

class StdDocumentParser:
    def __init__(self):
        self.output_dir = os.getenv("MINERU_OUTPUT_DIR", "./output")
        os.makedirs(self.output_dir, exist_ok=True)
        self.vlm = QwenVLClient()
        
        # 注意：实际生产中，可能需要修改 magic-pdf 内部配置以使用外部 VLM
        # 此处演示流程：先用 MinerU 做版面分析，提取关键区域图片，再用 Qwen 细化
        
    def parse(self, pdf_path: str) -> dict:
        """
        解析 PDF 返回结构化数据
        """
        try:
            # 1. 初始化 MinerU 管道
            image_writer = FileBasedDataWriter(self.output_dir)
            pdf_docs = read_local_pdf(pdf_path)
            
            # 2. 创建 OCR 管道 (针对图片型 PDF)
            # 强制使用 OCR 模式，确保触发图像识别流程
            pipe = OCRPipe(pdf_docs, image_writer, None)
            
            # 3. 执行基础解析
            pipe.pipe_classify()
            pipe.pipe_analyze()
            pipe.pipe_parse()
            
            # 4. 获取基础 Markdown
            md_content = pipe.get_markdown()
            
            # 5. (可选) 后处理优化
            # 如果 MinerU 默认 OCR 对公式识别不佳，可在此处提取公式图片坐标
            # 调用 self.vlm.recognize_complex_content(...) 进行替换
            # 此处为简化示例，直接返回 MinerU 结果
            
            return {
                "success": True,
                "markdown": md_content,
                "images_path": self.output_dir,
                "message": "解析成功"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "解析失败"
            }
```

### 5.4 MCP Server 入口 (`server.py`)

```python
import os
import asyncio
from mcp.server.fastmcp import FastMCP
from parser import StdDocumentParser

# 初始化 MCP Server
mcp = FastMCP("StdDocumentParser")

# 初始化解析器
parser = StdDocumentParser()

@mcp.tool()
async def parse_standard_pdf(file_path: str) -> str:
    """
    解析国家标准 PDF 文档 (支持图片型、含水印、公式)。
    返回 Markdown 格式内容，适合存入知识库。
    
    Args:
        file_path: PDF 文件的本地绝对路径
    """
    if not os.path.exists(file_path):
        return "Error: File not found."
    
    # 执行解析 (建议在线程池运行，避免阻塞 MCP 事件循环)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, parser.parse, file_path)
    
    if result["success"]:
        return result["markdown"]
    else:
        return f"Error: {result['error']}"

if __name__ == "__main__":
    # 启动 MCP Server
    mcp.run()
```

---

## 6. 配置 MinerU 使用 Qwen-VL (关键步骤)

MinerU 默认使用本地模型。要让它调用你的 Qwen-VL API，需要修改其模型配置文件。

1.  **找到配置文件：**
    通常在 `~/.magic-pdf/config.json` 或安装目录下的 `magic-pdf/config.json`。
2.  **修改 VLM 配置：**
    将 VLM 后端配置为 OpenAI 兼容模式。

```json
{
    "vip_model": false,
    "cpu_only": true,
    "models": {
        "vlm": {
            "type": "openai", 
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-your-actual-api-key",
            "model_name": "qwen-vl-max-latest"
        }
    }
}
```
*注意：如果 MinerU 版本尚未完全开放外部 VLM 配置，则需在 `parser.py` 中手动拦截 OCR 步骤，提取图片后调用 `vlm_client.py` (如上述代码所示)。*

---

## 7. 接入 MCP Router

在你的 MCP Router 配置文件中添加该 Server。

```json
{
  "mcpServers": {
    "std-parser": {
      "command": "python",
      "args": ["/absolute/path/to/my-mineru-mcp/server.py"],
      "cwd": "/absolute/path/to/my-mineru-mcp",
      "env": {
        "PATH": "/absolute/path/to/venv/bin:$PATH",
        "QWEN_API_KEY": "sk-...",
        "QWEN_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "QWEN_MODEL_NAME": "qwen-vl-max-latest"
      }
    }
  }
}
```

---

## 8. 针对国标文档的优化策略

### 8.1 水印处理
*   **策略：** 不在图像层强行去除（易损文字），而在 Prompt 层忽略。
*   **实施：** 在 `vlm_client.py` 的 Prompt 中明确加入 `Ignore any diagonal watermarks or header/footer text.`。
*   **进阶：** 若水印极深，可在 `parser.py` 中加入 OpenCV 预处理：
    ```python
    import cv2
    def preprocess_image(img_path):
        img = cv2.imread(img_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 自适应阈值二值化，弱化浅色水印
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        cv2.imwrite(img_path, binary)
    ```

### 8.2 公式乱码修复
*   **策略：** 强制 LaTeX 输出。
*   **实施：** 检测 MinerU 输出中的公式块，若置信度低，截取该区域图片发送给 Qwen-VL，Prompt 指定 `Output strictly in LaTeX format`。

### 8.3 表格结构保持
*   **策略：** Markdown 表格还原。
*   **实施：** 同样通过 Qwen-VL 识别表格区域，Prompt 指定 `Output in Markdown Table format`，避免按行读取导致列错位。

---

## 9. 部署与测试

### 9.1 启动测试
```bash
# 激活环境
source venv/bin/activate

# 启动 Server
python server.py
```

### 9.2 客户端验证
在支持 MCP 的客户端（如 Cursor）中输入：
> "请使用 std-parser 解析 /path/to/standard.pdf 并总结主要内容。"

### 9.3 性能调优
*   **并发限制：** 在 `server.py` 中增加信号量，避免同时调用过多 Qwen API 导致限流。
*   **缓存：** 对已解析的 PDF 文件哈希值进行缓存，避免重复解析。

---

## 10. 安全与合规提示

1.  **版权风险：** 国家标准（GB）通常受版权保护。请确保你的知识库平台仅在授权范围内使用（如内部学习、已购买授权）。
2.  **数据隐私：** 虽然使用了自有 API Key，但文档内容仍会传输至阿里云 DashScope。若文档涉密，需使用本地部署的 VLM 模型（如 Qwen-VL-Chat 本地版）。
3.  **API 成本：** 图片型 PDF 解析消耗 Token 较多，建议监控 DashScope 账单，设置用量预警。

---

## 11. 故障排查

| 问题 | 可能原因 | 解决方案 |
| :--- | :--- | :--- |
| **导入 PDF 报错** | 依赖缺失 | 确保安装 `mineru[full]` 且系统安装了 `poppler-utils` |
| **公式仍为乱码** | 未触发 VLM | 检查 `config.json` 中 VLM 配置是否生效，或手动调用 `vlm_client` |
| **MCP 连接失败** | 路径错误 | 检查 Router 配置中的 `cwd` 和 `command` 绝对路径 |
| **API 限流** | 并发过高 | 在代码中加入 `time.sleep` 或信号量控制 |

---

*最后更新：2024-05-23*
*适用版本：MinerU v1.0+, Python 3.10+*