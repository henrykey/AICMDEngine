# Docs Converter MCP Goals Loop Plan

日期：2026-07-23
状态：Proposed
范围：新增独立 `docs-converter` MCP，第一版仅支持 `.doc` 转 `.docx`

## 1. 最终目标

提供一个可独立部署、可被 MCP Router 调用的 `docs-converter` 服务，将旧版 Microsoft Word 二进制 `.doc` 文件安全转换为 `.docx`，供后续 `office-word` 或 MarkItDown 使用。

完成链路：

```text
.doc
  -> docs-converter.convert_doc_to_docx
  -> .docx
  -> office-word 或 MarkItDown
```

## 2. 首版边界

### 包含

1. 新增 `mcp/servers/docs-converter/`。
2. 使用 LibreOffice headless 执行 `.doc -> .docx`。
3. 暴露一个 MCP 工具：`convert_doc_to_docx`。
4. 提供独立 Docker 镜像。
5. 注册到现有 MCP 部署与 Router 发现链路。
6. 覆盖成功、非法输入、冲突、转换失败和超时测试。

### 不包含

1. 不支持 `.ppt`、`.xls`、`.rtf` 等其他格式。
2. 不负责读取、编辑或分析 `.docx`。
3. 不集成 MarkItDown。
4. 不修改 `office-word` 现有工具行为。
5. 不在 MCP Router 内实现转换逻辑。
6. 不自动编排转换后的下一步处理。
7. 不引入数据库、任务队列或长期任务状态。

## 3. 工具契约

```text
convert_doc_to_docx(
    source_path: str,
    output_path: str | None = null,
    overwrite: bool = false
)
```

建议成功响应：

```json
{
  "success": true,
  "source_path": "/documents/example.doc",
  "output_path": "/documents/example.docx",
  "converter": "libreoffice",
  "warnings": []
}
```

建议失败响应：

```json
{
  "success": false,
  "source_path": "/documents/example.doc",
  "output_path": null,
  "error_code": "SOURCE_NOT_FOUND",
  "message": "Source document does not exist"
}
```

首版错误码：

- `SOURCE_NOT_FOUND`
- `UNSUPPORTED_FORMAT`
- `INVALID_SOURCE`
- `OUTPUT_EXISTS`
- `OUTPUT_NOT_WRITABLE`
- `CONVERSION_TIMEOUT`
- `CONVERSION_FAILED`
- `OUTPUT_NOT_CREATED`

## 4. 固定约束

1. 保留源 `.doc`，转换过程不得修改或删除源文件。
2. 默认输出为源文件同目录、同名的 `.docx`。
3. 默认不覆盖已有输出；只有 `overwrite=true` 时允许替换。
4. 文件扩展名与文件内容都要检查，不能只信任扩展名。
5. 转换先写入隔离的临时目录，验证成功后再移动到目标位置。
6. 失败或超时必须清理本次产生的临时文件。
7. LibreOffice 必须以 headless 模式运行，并设置明确超时。
8. 不执行文档中的宏。
9. 日志不得输出文档正文。
10. 容器间通过明确挂载的共享文档目录传递文件路径。

## 5. Goals Loop

每个 Goal 都按以下循环执行：

```text
建立失败测试
  -> 实现最小改动
  -> 运行目标测试
  -> 检查真实产物
  -> 失败则记录证据并回到本 Goal
  -> Exit criteria 全部满足后进入下一 Goal
```

### Goal 1：建立转换行为基线

目标：用真实 `.doc` 样本确认 LibreOffice 转换命令、输出位置和失败行为。

行动：

1. 准备一个包含段落和表格的最小真实 `.doc` fixture。
2. 在目标 Linux 基础镜像中执行 LibreOffice headless 转换。
3. 用 `python-docx` 打开生成的 `.docx` 并验证关键文字和表格。
4. 记录 LibreOffice 版本及转换命令。

验证：

- 生成文件是有效的 OOXML `.docx`，不能只是扩展名变化。
- 关键段落和表格内容可读取。
- 源 `.doc` 的哈希在转换前后不变。

Exit criteria：

- 至少一个真实 `.doc` 可稳定转换并通过内容断言。
- 已明确转换命令、超时策略和输出文件定位方式。

失败反馈：

- 若基础镜像无法稳定安装或运行 LibreOffice，停止后续实现并重新评估镜像方案。

### Goal 2：实现纯转换核心

目标：在不依赖 MCP transport 的情况下完成可测试的 `.doc -> .docx` 转换函数。

行动：

1. 先增加核心函数测试。
2. 实现输入验证、输出冲突检查和临时目录转换。
3. 实现超时、进程退出码和输出文件存在性检查。
4. 成功后以原子方式把临时产物移动到目标路径。

验证：

- 正常 `.doc` 转换成功。
- 文件不存在、伪造 `.doc`、已有输出和只读目录返回稳定错误码。
- 超时和 LibreOffice 失败不会留下目标文件或临时垃圾。
- `overwrite=false` 不改变已有文件。

Exit criteria：

- 核心测试全部通过。
- 每个错误分支都有确定、可序列化的结果。
- 源文件在所有路径下都保持不变。

失败反馈：

- 若 LibreOffice 输出命名不可可靠预测，只允许在隔离临时目录内定位本次新增的单个 `.docx`；不得扫描共享目录猜测结果。

### Goal 3：暴露 MCP 工具

目标：将核心转换函数封装为独立 FastMCP 工具。

行动：

1. 创建最小 MCP server 入口。
2. 注册 `convert_doc_to_docx`。
3. 为工具参数和响应提供明确描述。
4. 保持 transport 配置方式与现有外部 MCP 一致。

验证：

- MCP 客户端可以列出工具。
- 工具 schema 包含三个约定参数及默认值。
- 通过 MCP 调用成功转换真实 fixture。
- MCP 返回值与核心函数结果一致。

Exit criteria：

- 工具发现、成功调用和失败调用测试全部通过。
- 服务中没有首版范围之外的工具。

失败反馈：

- transport 问题与转换问题分别记录；不得通过修改核心转换语义解决协议问题。

### Goal 4：构建独立运行镜像

目标：生成包含 LibreOffice 的 `docs-converter` 镜像，并能访问共享文档目录。

行动：

1. 创建独立 Dockerfile。
2. 安装运行时所需的最小 LibreOffice 组件和字体。
3. 使用非 root 运行用户。
4. 配置共享文档目录和临时目录。
5. 增加服务健康检查。

验证：

- 镜像内可查询 LibreOffice 版本。
- 容器内 MCP 服务正常启动。
- 挂载目录中的 `.doc` 可转换，宿主机能看到生成的 `.docx`。
- 容器无法写入未授权目录。

Exit criteria：

- 镜像可重复构建。
- 容器内端到端转换测试通过。
- 输出文件权限允许下游 `office-word` 和 MarkItDown 读取。

失败反馈：

- 若字体或 LibreOffice 包导致镜像不可接受地膨胀，先记录镜像大小与缺失功能，再决定是否更换基础镜像；不在首版引入远程转换服务。

### Goal 5：接入 MCP 基础设施

目标：让 MCP Router 能发现并调用 `docs-converter`，同时不影响现有 MCP。

行动：

1. 为服务分配不冲突的端口。
2. 更新本地代理或 Compose 服务配置。
3. 更新 Router 的外部 MCP 配置。
4. 将服务纳入现有部署脚本的独立 scope 和 `mcp` 聚合 scope。
5. 补充最小运行说明。

验证：

- Router 可发现 `docs-converter.convert_doc_to_docx`。
- 经 Router 调用能完成真实转换。
- `office-word`、PDF2MD Enhanced、PageIndex 等现有 MCP 仍可发现。
- 仅选择 `docs-converter` scope 时不会构建或部署无关服务。

Exit criteria：

- Router 端到端调用通过。
- 部署配置预检通过。
- 现有服务注册无回归。

失败反馈：

- 若服务间看见的文件路径不一致，优先修正共享卷和路径契约；不得复制文件到 Router 容器作为补丁。

### Goal 6：完成验收与交接

目标：证明首版能力可以安全交给上层编排使用。

验收用例：

1. 普通 `.doc` 成功生成可由 `python-docx` 打开的 `.docx`。
2. 带表格的 `.doc` 转换后保留关键文字和表格单元格。
3. 不存在的源文件返回 `SOURCE_NOT_FOUND`。
4. 扩展名为 `.doc` 的非 Word 文件返回 `INVALID_SOURCE`。
5. 已有输出且 `overwrite=false` 返回 `OUTPUT_EXISTS`。
6. `overwrite=true` 成功替换目标文件，但不改变源文件。
7. 模拟超时返回 `CONVERSION_TIMEOUT` 且无残留目标文件。
8. Router 调用与直接 MCP 调用结果一致。
9. 生成的 `.docx` 可被现有 `office-word.get_document_text` 读取。
10. 生成的 `.docx` 可被 MarkItDown 转为 Markdown；若 MarkItDown 尚未部署，只记录为集成验收项，不把它作为本服务单元测试依赖。

最终 Exit criteria：

- Goal 1 至 Goal 5 的 Exit criteria 全部满足。
- 自动化测试全部通过。
- 至少一个真实 `.doc` 完成 Router 到 `.docx` 的端到端验证。
- 没有修改 `office-word` 的现有工具契约。
- 文档明确说明共享目录、端口、调用示例、限制和回滚方式。

## 6. 建议目录

```text
mcp/servers/docs-converter/
  Dockerfile
  README.md
  pyproject.toml
  docs_converter/
    __init__.py
    main.py
    converter.py
    models.py
  tests/
    fixtures/
      sample.doc
    test_converter.py
    test_mcp_tools.py
```

具体文件数量以实现时的最小需求为准；如果 `models.py` 只包含一个单次使用的数据结构，应直接合并到相邻模块。

## 7. 回滚边界

`docs-converter` 是独立服务，回滚只需：

1. 从 Router 外部 MCP 配置移除该服务。
2. 停止 `docs-converter` 容器。
3. 保留原始 `.doc` 文件。

回滚不得影响 `office-word`、MarkItDown 或其他 MCP 的现有行为。
