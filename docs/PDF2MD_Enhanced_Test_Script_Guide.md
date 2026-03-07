# PDF2MD Enhanced Test Script 使用手册

脚本路径：
`tests/test_pdf2md_enhanced_mcp.py`

适用场景：
- 通过 MCP Router 远程调用 `pdf2md-enhanced` 服务
- 单页/多页回归测试
- 生成两类结果文件：`Markdown`（展示） + `JSON`（RAG）

## 1. 基本用法

单页：
```bash
python tests/test_pdf2md_enhanced_mcp.py --page 31 --full --out docs/test/GB151.31
```

多页范围：
```bash
python tests/test_pdf2md_enhanced_mcp.py --pages 49-119 --full --out docs/test/GB151.49-119
```

多页离散：
```bash
python tests/test_pdf2md_enhanced_mcp.py --pages 1,2,5,10 --full --out docs/test/sample
```

## 2. 输出文件说明

当传 `--out <prefix>` 时，脚本输出：
- `<prefix>.md`：按页增量写入的渲染 Markdown（多页含 `<!-- page:N -->` 分隔）
- `<prefix>.json`：规范化 RAG JSON（用于下游 LangChain/ES）
- `<prefix>.pages.json`：每页原始 MCP 返回（调试用）

示例：
- `docs/test/GB151.49-119.md`
- `docs/test/GB151.49-119.json`
- `docs/test/GB151.49-119.pages.json`

## 3. 核心参数

基础：
- `--page <n>`：测试单页
- `--pages <spec>`：测试多页，支持 `1-5`、`1,2,3`
- `--pdf-path <path>`：指定 PDF 路径
- `--out <prefix>`：输出文件前缀
- `--full`：完整模式（保留完整结果处理流程）

处理策略：
- `--policy auto|force_direct|force_vlm`（默认 `auto`）
- `--render-dpi <int>`（默认 `220`）
- `--render-rotate-deg <int>`（默认 `0`，可用 `-90/90/180/270`）

重试：
- `--page-retries <int>`：每页失败后重试次数（默认 `0`）
- `--retry-render-dpi <int>`：重试时使用的 DPI（默认 `0`=沿用 `--render-dpi`）

WebSocket：
- `--ws-max-mb <int>`：WS 单消息上限 MB（默认 `100`）

file_data 传输模式（当远程容器无法访问本地 `file_path` 时生效）：
- `--file-data-mode single|batch`
  - `single`（默认）：逐页单独传输（最稳）
  - `batch`：按批传输
- `--file-data-batch-size <int>`
  - `0`（默认）：自适应二分拆批（若 1009 超包，自动 1/2、1/2/2...）
  - `>0`：固定批大小

FULL_VLM 兜底：
- `--full-vlm-retry-markdown / --no-full-vlm-retry-markdown`
  - 默认开启（建议保持开启）
- `--full-vlm-split-extract`
  - 默认关闭，仅调试用

大表占位策略：
- `--large-table-placeholder / --no-large-table-placeholder`（默认开启）
- `--large-table-min-cols <int>`（默认 `12`）
- `--large-table-min-rows <int>`（默认 `16`）
- `--large-table-min-cells <int>`（默认 `180`）

## 4. 推荐命令

推荐（稳定优先，逐页传输）：
```bash
python tests/test_pdf2md_enhanced_mcp.py \
  --pages 49-119 \
  --full \
  --out docs/test/GB151.49-119 \
  --file-data-mode single \
  --page-retries 2 \
  --render-dpi 220 \
  --retry-render-dpi 300 \
  --full-vlm-retry-markdown \
  --large-table-placeholder
```

批量+自动拆分（速度优先，仍可避免超包）：
```bash
python tests/test_pdf2md_enhanced_mcp.py \
  --pages 49-119 \
  --full \
  --out docs/test/GB151.49-119 \
  --file-data-mode batch \
  --file-data-batch-size 0 \
  --ws-max-mb 100
```

## 5. 常见问题

### Q1: 报 `1009 message too big`
原因：`file_data` 单条消息过大。  
处理：
1. 优先使用 `--file-data-mode single`
2. 或 `--file-data-mode batch --file-data-batch-size 0`（自动二分）
3. 适当提高 `--ws-max-mb`

### Q2: 某页 `full_vlm_no_render_recovered`
原因：该页首轮 VLM 未恢复出可用 render。  
处理：
1. `--page-retries 2 --retry-render-dpi 300`
2. 必要时单页重跑定位（`--page N`）

### Q3: 输出 MD 看起来“没分页”
现在多页 `.md` 默认写入页标记：
`<!-- page:N -->`  
如果没有，确认使用了最新脚本版本并传入 `--out`。

### Q4: 输出里出现 `<!-- Table (x1, y1, x2, y2) -->`
这是表区域坐标注释（布局定位信息），不是正文错误。  
可保留用于后续区域级处理；若仅做阅读展示，也可在 client 侧清理。

## 6. 与 RAG 构建的关系

当前脚本输出的 `<prefix>.json` 已按“render 优先重构”策略规范化，适合直接进入：
- LangChain chunk
- 向量化（embedding）
- ES 全文+语义检索
- page-index / vectorless 检索流程

建议下游只把 `<prefix>.json` 作为主输入，`<prefix>.md` 用于展示与人工核对。
