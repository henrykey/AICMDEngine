# PDF2MD

基于 MinerU (magic-pdf) 的扫描 PDF -> Markdown 与 RAG 预处理 MCP 服务。

## Tools

- `health_check`
- `parse_standard_pdf(file_path, options)`
- `prepare_rag_chunks(file_path, options)`

## 技术路线

- 主解析: MinerU (magic-pdf)
- 增强: Qwen-VL (OpenAI 兼容接口，可选)
- 输出: `document_markdown` + `layout_blocks` + `rag_chunks`

## Run (stdio)

```bash
PYTHONPATH=/absolute/path/to/AIPlanner/mcp/servers \
python -m PDF2MD.__main__
```

## Run (HTTP)

```bash
PYTHONPATH=/absolute/path/to/AIPlanner/mcp/servers \
python -m PDF2MD.__main__ --http --host 127.0.0.1 --port 8030
```

## Router EXTERNAL_MCPS 示例

```env
EXTERNAL_MCPS='{
  "PDF2MD": {
    "command": "python",
    "args": ["-m", "PDF2MD.__main__"],
    "transport": "stdio",
    "timeout": 300,
    "env": {
      "PYTHONPATH": "/absolute/path/to/AIPlanner/mcp/servers",
      "PDF2MD_OUTPUT_DIR": "/tmp/pdf2md_output",
      "PDF2MD_ALLOW_EXTERNAL_VLM": "true"
    }
  }
}'
```

## 关键配置

- `PDF2MD_OUTPUT_DIR`
- `PDF2MD_MAX_FILE_SIZE_MB`
- `PDF2MD_MAX_PAGES`
- `PDF2MD_MAX_QWEN_CALLS_PER_DOC`
- `PDF2MD_QWEN_TIMEOUT_SEC`
- `PDF2MD_QWEN_MAX_RETRIES`
- `PDF2MD_ALLOW_EXTERNAL_VLM`

Qwen 相关优先读取 `QWEN_*`，否则回退读取现有 `OPENAI_*`。

## 说明

- 默认优先 MinerU；失败时回退 `fitz` 文本抽取，保证有兜底输出。
- 非文本区域会生成描述文本，供 embedding/RAG 使用。
- 工具返回 JSON 字符串，兼容 MCP Router 透传。
