# Docs Converter MCP

独立的旧版文档格式转换 MCP。第一版只提供 `.doc -> .docx`，转换由
LibreOffice headless 完成。

## 工具

```text
convert_doc_to_docx(
    source_path: str | None = None,
    output_path: str | None = None,
    overwrite: bool = false,
    input_data: str | None = None,
    filename: str = "document.doc"
)
```

- `source_path` 必须是可读取的真实 OLE `.doc` 文件。
- 未指定 `output_path` 时，在源文件同目录生成同名 `.docx`。
- 默认不覆盖已有文件。
- 源文件始终保留。
- 跨容器调用可通过 `input_data` 传入 Base64 编码的 `.doc`，并通过
  `output_base64` 接收转换后的 DOCX。

## 本地运行

系统需要提供 `soffice` 或 `libreoffice`：

```bash
pip install -e .
docs-converter
```

默认使用 stdio transport。HTTP/SSE 模式：

```bash
MCP_TRANSPORT=sse MCP_PORT=9012 docs-converter
```

## Docker

容器使用 `/documents` 作为与下游服务共享的文档目录：

```bash
docker build -t aiplanner-docs-converter:latest .
docker run --rm -p 9012:9012 \
  -v /absolute/path/to/documents:/documents \
  aiplanner-docs-converter:latest
```

转换调用中的路径应使用容器路径，例如：

```json
{
  "source_path": "/documents/example.doc"
}
```

## 限制

- 不读取、编辑或分析转换后的文档。
- 不支持 `.ppt`、`.xls`、`.rtf` 等格式。
- 不自动调用 `office-word` 或 MarkItDown。
- 加密、损坏或并非 OLE Word 文档的输入可能无法转换。
