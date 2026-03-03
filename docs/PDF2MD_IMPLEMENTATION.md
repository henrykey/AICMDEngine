# PDF2MD 实现方法与处理逻辑

## 📋 文档概述

本文档详细描述PDF2MD（PDF转Markdown）的完整实现方法和处理逻辑，专门针对国标规范类PDF文档（如GB/T 16749-2018）进行优化。

**核心定位**：
- **作为MCP服务**：通过Model Context Protocol提供服务
- **被membership调用**：集成到DocIntel文档处理流程中

**核心目标**：
- **RAG用途**：生成纯净的文本信息，适合检索和向量化
- **展示用途**：生成完整的Markdown文档，保留表格、公式、图像

**应用场景**：
- 国标规范文档（GB、ISO、ASTM等）
- 技术标准文档
- 学术论文
- 技术手册

---

## 🏗️ MCP服务架构

### 服务定位

PDF2MD作为MCP服务提供者，通过MCP Router向membership系统提供PDF处理能力：

```
┌───────────────────────────────────────────────────────────────┐
│                   Membership System                           │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         DocumentTextExtractor                         │   │
│  │   - 接收文件上传                                       │   │
│  │   - 检测文档类型                                       │   │
│  │   - 选择提取策略                                       │   │
│  └────────────────────┬──────────────────────────────────┘   │
│                       │                                       │
│                       ▼                                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            ExtractionOrchestrator                     │   │
│  │   - 判断是否需要调用MCP                               │   │
│  │   - 对于PDF → 调用PDF2MD服务                          │   │
│  └────────────────────┬──────────────────────────────────┘   │
│                       │                                       │
│                       ▼                                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                 McpClient                             │   │
│  │   - WebSocket连接到MCP Router                        │   │
│  │   - 调用MCP工具                                       │   │
│  └────────────────────┬──────────────────────────────────┘   │
└────────────────────────┼───────────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────────┐
│                      MCP Router                               │
│                   (路由转发)                                   │
└────────────────────────┬───────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  PDF2MD      │ │   OCR        │ │  Multimodal  │
│  MCP Server  │ │  MCP Server  │ │  MCP Server  │
│              │ │              │ │              │
│ process_pdf_ │ │ extract_text │ │ analyze_     │
│ page()       │ │ ()           │ │ image()      │
└──────────────┘ └──────────────┘ └──────────────┘
```

### MCP工具定义

```python
# PDF2MD MCP Server提供的工具

@mcp.tool()
def process_pdf_page(
    pdf_path: str,
    page_num: int
) -> dict:
    """
    处理PDF单页，返回结构化结果

    输入：
    - pdf_path: PDF文件路径
    - page_num: 页码（从1开始）

    输出：
    {
      "page_num": 18,
      "page_type": "normal",
      "chapters": [...],
      "rag": {...},
      "render": {...},
      "elements": {...}
    }

    使用场景：
    - 单页测试
    - 快速预览
    - 调试
    """
    pass

@mcp.tool()
def process_pdf_document(
    pdf_path: str,
    pages: Optional[List[int]] = None
) -> dict:
    """
    处理整个PDF文档，返回完整结构化结果

    输入：
    - pdf_path: PDF文件路径
    - pages: 可选，指定处理的页码列表（None=全部）

    输出：
    {
      "document": {
        "title": "...",
        "toc": [...],
        "chapters": [...]
      },
      "metadata": {...}
    }

    使用场景：
    - RAG建库（一次性获取完整数据）
    - 文档MD化（生成完整Markdown）
    - 批量处理

    实现方式：
    1. 内部循环调用process_pdf_page()
    2. 聚合所有页面结果
    3. 按章节号合并跨页内容
    4. 返回文档级输出
    """
    pass
```

### 调用流程

```java
// membership系统中的调用代码

@Autowired
private McpClient mcpClient;

// 上传PDF后，调用PDF2MD处理
public DocumentMetadata processPdfDocument(InputStream pdfStream, String fileName) {
    // 1. 保存PDF到临时文件
    Path tempFile = saveToTempFile(pdfStream, fileName);

    // 2. 调用PDF2MD工具
    Map<String, Object> args = new HashMap<>();
    args.put("pdf_path", tempFile.toString());
    // args.put("pages", Arrays.asList(1, 2, 3)); // 可选：只处理部分页

    MCPResponse response = mcpClient.callTool(
        "pdf2md.process_pdf_document",  // MCP工具名称
        args,
        jwtToken  // 用户认证token
    );

    // 3. 解析响应
    String resultJson = extractTextFromResponse(response);
    Pdf2mdResult result = objectMapper.readValue(resultJson, Pdf2mdResult.class);

    // 4. 存储到MongoDB和ES
    storeToDatabase(result);

    return result.getMetadata();
}
```

---

## 🎯 整体架构

### 输入输出

```python
# 输入
PDF文档（逐页处理）

# 输出
{
  "document": {
    "title": "GB/T 16749—2018 压力容器波形膨胀节",
    "toc": [...],           # 目录索引（无页码）
    "chapters": [           # 章节内容（自然连接）
      {
        "num": "6.5",
        "title": "装运杆、装运螺栓或螺母",
        "rag": "...",       # RAG用文本
        "render": "...",    # 展示用MD
        "elements": {...}   # 结构化元素
      }
    ]
  }
}
```

### 处理流程

```
┌─────────────────────────────────────────────────────────────┐
│  PDF文档输入                                                  │
└──────────────────┬──────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  逐页处理循环                                                 │
│  ├─ 渲染页面图像                                              │
│  ├─ VLM布局识别（页面类型、页眉页脚页码）                        │
│  ├─ 提取章节信息                                              │
│  ├─ 识别结构化元素（表/图/公式）                                │
│  └─ 生成RAG文本 + Render MD                                   │
└──────────────────┬──────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  章节聚合（跨页合并）                                           │
│  ├─ 按章节号分组                                              │
│  ├─ 合并同一章节的多页内容                                      │
│  └─ 建立章节顺序                                              │
└──────────────────┬──────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  生成最终输出                                                 │
│  ├─ 完整JSON（RAG + Render + Elements）                      │
│  └─ 完整MD文档（章节自然连接）                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 数据结构设计

### 1. 页面级别结构

```python
{
  "page_num": 18,
  "page_type": "normal",  # cover | toc | blank | normal

  # 布局识别结果
  "layout": {
    "header": ["GB/T 16749—2018"],
    "footer": [],
    "page_number": "14"
  },

  # 章节信息
  "chapters": [
    {
      "num": "6.5",
      "title": "装运杆、装运螺栓或螺母",
      "level": 2,  # 1=一级, 2=二级, 3=三级
      "line_start": 7
    },
    {
      "num": "6.5.1",
      "title": "自制的装运杆、装运螺栓或螺母",
      "level": 3,
      "line_start": 9
    }
  ],

  # RAG文本（纯文本，适合检索）
  "rag": {
    "summary": "该页规定了装运杆、装运螺栓、螺母的材料选用及制造技术要求",
    "content": "自制的装运杆、装运螺栓或螺母，其材料选用...",
    "elements": [
      "表1：波纹管直边与端管连接焊缝，包含5种焊接类型...",
      "公式(2)：A_c = nt[2πr_m + ...]，用于计算单个U型波纹的金属横截面积"
    ],
    "keywords": ["装运杆", "螺栓", "螺母", "力学性能等级"]
  },

  # Render MD（完整格式，适合展示）
  "render": {
    "markdown": "## 6.5 装运杆、装运螺栓或螺母\n\n..."
  },

  # 结构化元素
  "elements": {
    "tables": [
      {
        "id": "table_1",
        "name": "表1：波纹管直边与端管连接焊缝",
        "summary": "5种焊接类型及变化形式",
        "rag_text": "表1展示了波纹管直边与端管连接的5种焊接类型...",
        "markdown": "| 序号 | 焊接类型 | ...",
        "rows": 6,
        "cols": 6
      }
    ],
    "figures": [
      {
        "id": "figure_1",
        "name": "图1：Ω波形与结构",
        "summary": "Ω波形整体成形过程",
        "rag_text": "图1展示了Ω波形的整体成形过程，包含端管、波纹管、加强环等",
        "caption": "**图1：** 该图展示了Ω波形的整体成形过程..."
      }
    ],
    "formulas": [
      {
        "id": "formula_2",
        "name": "公式(2)",
        "summary": "单个U型波纹金属横截面积",
        "rag_text": "公式(2)：A_c = nt[2πr_m + 2√((q/2 - 2r_m)^2 + (h - 2r_m)^2)]",
        "latex": "$$A_{\\mathrm{c}} = n t_{\\mathrm{p}} [2\\pi r_{\\mathrm{m}} + 2 \\sqrt{...}]$$",
        "plain_text": "A_c = nt[2πr_m + 2√((q/2 - 2r_m)^2 + (h - 2r_m)^2)]",
        "variables": [
          {"symbol": "A_c", "meaning": "单个U型波纹金属横截面积", "unit": "mm²"},
          {"symbol": "n", "meaning": "波纹数"},
          {"symbol": "t_p", "meaning": "波纹管厚度"}
        ]
      }
    ]
  }
}
```

### 2. 文档级别结构

```python
{
  "document": {
    "title": "GB/T 16749—2018 压力容器波形膨胀节",
    "standard_code": "GB/T 16749—2018",
    "publish_date": "2018-09-01",

    # 目录索引（无页码）
    "toc": [
      {"chapter": "1", "title": "范围"},
      {"chapter": "2", "title": "规范性引用文件"},
      {"chapter": "6", "title": "加强件、装运杆和螺栓"},
      {"chapter": "6.5", "title": "装运杆、装运螺栓或螺母"},
      {"chapter": "附录A", "title": "资料性附录"}
    ],

    # 章节内容（按顺序自然连接）
    "chapters": [
      {
        "num": "1",
        "title": "范围",
        "level": 1,
        "rag": "本标准规定了压力容器波形膨胀节的术语和定义、分类...",
        "render": "## 1 范围\n\n本标准规定了...",
        "elements": {"tables": [], "figures": [], "formulas": []}
      },
      {
        "num": "6.5",
        "title": "装运杆、装运螺栓或螺母",
        "level": 2,
        "rag": "该页规定了装运杆、装运螺栓、螺母的材料选用...",
        "render": "## 6.5 装运杆、装运螺栓或螺母\n\n...",
        "elements": {
          "tables": ["表1：..."],
          "formulas": ["公式(2)：...", "公式(3)：..."]
        }
      }
    ]
  },

  # 元数据
  "metadata": {
    "source_file": "GBT16749-2018.pdf",
    "total_pages": 57,
    "processed_pages": 57,
    "blank_pages": [3, 15],  # 空白页页码
    "processing_time": "2025-03-03T10:30:00Z"
  }
}
```

---

## 🔍 页面类型识别

### 页面类型分类

```python
page_types = {
  "cover": {      # 封面页
    "features": ["标准号", "标准名称", "实施日期"],
    "action": "提取标题和基本信息"
  },
  "toc": {        # 目录页
    "features": ["目次", "目录", "章节列表"],
    "action": "提取章节索引（无页码）"
  },
  "blank": {      # 空白页
    "features": ["无文字", "无图像"],
    "action": "跳过"
  },
  "normal": {     # 普通内容页
    "features": ["章节标题", "正文内容"],
    "action": "提取章节和元素"
  }
}
```

### VLM布局识别提示词

```python
layout_prompt = """
请分析PDF页面并识别以下内容：

**页面类型**（从以下选择）：
- cover：封面页（包含标准号、标题、实施日期）
- toc：目录页（包含章节列表、"目次"或"目录"字样）
- blank：空白页（无内容）
- normal：普通内容页（章节、正文、图表）

**需要识别的内容**：
1. 页眉：页面顶部重复出现的文本（如标准号）
2. 页脚：页面底部重复出现的文本（如实施日期）
3. 页码：页码标识（如"第18页"、"18"）
4. 页面类型：cover/toc/blank/normal
5. 内容摘要：简要描述页面主要内容

返回JSON格式。
"""
```

---

## 📝 章节识别与聚合

### 章节号识别规则

```python
# 正则表达式模式
chapter_patterns = [
  r'^(\d+)\s+(.+)$',           # 1 范围
  r'^(\d+\.\d+)\s+(.+)$',      # 6.5 装运杆
  r'^(\d+\.\d+\.\d+)\s+(.+)$', # 6.5.1 自制的装运杆
  r'^(附录[A-Z])\s*(.+)$',     # 附录A
  r'^([A-Z][A-Z\d]+)\s+(.+)$'  # 参考文献
]

# OCR错误处理
ocr_corrections = {
  r'(\d+)\s*\.\s*(\d+)': r'\1.\2',      # 6 . 5 → 6.5
  r'(\d+)\.\s+$': r'\1.',                 # 6. → 6.
  r'(\d+)\s+(\.\s+)$': r'\1.',            # 去除尾随点号
}
```

### 跨页章节聚合逻辑

```python
def aggregate_chapters(pages: List[Page]) -> List[Chapter]:
    """
    将页面级别的章节信息聚合为文档级别的章节

    处理逻辑：
    1. 按章节号分组
    2. 合并同一章节的多页内容
    3. 保持父子章节关系
    4. 建立章节顺序
    """
    chapters_by_num = {}

    for page in pages:
        for page_chapter in page.chapters:
            num = page_chapter.num

            if num not in chapters_by_num:
                # 新章节
                chapters_by_num[num] = {
                    "num": num,
                    "title": page_chapter.title,
                    "level": page_chapter.level,
                    "pages": [page.page_num],
                    "content": [],
                    "elements": {"tables": [], "figures": [], "formulas": []}
                }
            else:
                # 已有章节，追加内容
                chapter = chapters_by_num[num]
                chapter["pages"].append(page.page_num)

            # 追加RAG文本和元素
            chapters_by_num[num]["content"].append(page.rag["content"])
            chapters_by_num[num]["elements"]["tables"].extend(
                [e["rag_text"] for e in page.elements["tables"]]
            )

    # 合并内容并排序
    sorted_chapters = sort_chapters(chapters_by_num.values())

    for chapter in sorted_chapters:
        chapter["rag"] = "\n\n".join(chapter["content"])
        chapter["render"] = generate_markdown(chapter)
        del chapter["content"]  # 删除中间状态

    return sorted_chapters

def sort_chapters(chapters: List[Dict]) -> List[Dict]:
    """
    章节排序逻辑

    优先级：
    1. 数字章节（1, 2, 6.5, 6.5.1）
    2. 附录（附录A, 附录B）
    3. 参考文献
    """
    def chapter_key(ch):
        num = ch["num"]

        # 数字章节
        if re.match(r'^\d+(\.\d+)*$', num):
            parts = num.split('.')
            return (0, [int(p) for p in parts])

        # 附录
        if num.startswith("附录"):
            letter = num.replace("附录", "")[0]
            return (1, ord(letter))

        # 参考文献
        if num == "参考文献":
            return (2, 0)

        # 其他
        return (3, num)

    return sorted(chapters, key=chapter_key)
```

---

## 🤖 VLM提示词设计

### RAG模式提示词

```python
rag_prompts = {
  "table": """
识别表格并生成简洁摘要，用于文本检索。

返回格式：
```
表X：表名
该表包含N行M列，主要内容是...
关键数据包括：...
```

要求：
- 纯文本描述，无Markdown格式
- 突出关键信息和数据
- 一句话概括表格用途
""",

  "figure": """
描述图像内容，用于文本检索。

返回格式：
```
图X：图名
该图展示了...，包含...
用于说明...
```

要求：
- 一句话概括
- 突出主要对象和关系
- 说明用途或意义
""",

  "formula": """
识别数学公式，用于文本检索。

返回格式：
```
公式(X)：公式名称
公式：纯文本公式（如 A_c = nt[2πr_m + ...]）
用途：说明公式用途
变量：符号=含义（单位）
```

要求：
- 纯文本公式，不用LaTeX
- 列出所有变量及其含义
- 说明公式用途
"""
}
```

### Render模式提示词

```python
render_prompts = {
  "table": """
识别表格并输出Markdown格式。

要求：
- 保持行列结构
- 保留表头
- 精确识别单元格内容
- 忽略水印
""",

  "figure": """
描述图像内容。

返回格式：
**图X：** 详细描述

要求：
- 详细描述图像内容
- 说明各个组成部分
- 保持专业性
""",

  "formula": """
识别数学公式并输出LaTeX格式。

要求：
- 标准LaTeX语法
- 使用$$...$$或\\[...\\]包裹
- 保留公式编号
- 精确识别所有符号
"""
}
```

---

## 🧹 内容清理

### 需要清理的内容

```python
# 1. 页眉页脚
headers_footers = [
  "GB/T 16749—2018",
  "压力容器波形膨胀节",
  "2019-04-01 实施",
  "国家市场监督管理总局"
]

# 2. 页码
page_numbers = [
  r"第\d+页",
  r"^\d+$",  # 单独数字
  r"-\s*\d+\s*-"  # -18-
]

# 3. OCR噪音
ocr_noise = [
  r"[^\w\u4e00-\u9fff\s\.,;:!?()（）\[\]{}+=\-*/]",  # 无意义符号
  r"\s{2,}",  # 多余空格
]

# 4. 重复内容
duplicates = [
  "连续相同的段落",
  "表/图的重复描述"
]
```

### 清理流程

```python
def clean_content(raw_markdown: str, layout_info: Dict) -> str:
    """
    内容清理流程

    1. 移除页眉页脚（基于VLM识别）
    2. 移除页码
    3. 合并断行
    4. 修复OCR错误
    5. 标准化空白符
    """
    lines = raw_markdown.split('\n')
    cleaned = []

    for line in lines:
        stripped = line.strip()

        # 跳过页眉
        if any(h in stripped for h in layout_info["header"]):
            continue

        # 跳过页脚
        if any(f in stripped for f in layout_info["footer"]):
            continue

        # 跳过页码
        if re.match(r'^第\d+页$', stripped):
            continue

        # 保留有效内容
        if stripped:
            cleaned.append(line)

    # 合并并清理
    result = '\n'.join(cleaned)
    result = re.sub(r'\n{3,}', '\n\n', result)  # 合并多余空行
    result = result.strip()

    return result
```

---

## 🎨 输出格式

### JSON输出

```json
{
  "document": {
    "title": "GB/T 16749—2018 压力容器波形膨胀节",
    "toc": [...],
    "chapters": [...]
  },
  "metadata": {...}
}
```

### Markdown输出

```markdown
# GB/T 16749—2018 压力容器波形膨胀节

## 目次

- 1 范围
- 2 规范性引用文件
- ...
- 附录A

## 前言

## 1 范围

本标准规定了...

## 6.5 装运杆、装运螺栓或螺母

### 6.5.1 自制的装运杆

自制的装运杆、装运螺栓或螺母...

**表1：** 波纹管直边与端管连接焊缝

| 序号 | 焊接类型 | 变化形式 |
|------|----------|----------|
| 1 | 外套/角焊缝 | — |

$$
A_{\mathrm{c}} = n t_{\mathrm{p}} [2\pi r_{\mathrm{m}} + ...]
$$

## 附录A（资料性附录）

...

## 参考文献
```

---

## ⚠️ 边界情况处理

### 1. 跨页表格

```python
# 检测表格被分页
if table_end == "..." and next_page_has_table:
    # 合并表格
    merged_table = merge_tables(table_current, table_next)
```

### 2. 章节号OCR错误

```python
# 6 . 5 → 6.5
# 6.5. → 6.5
normalized_chapter = normalize_ocr_errors(raw_chapter)
```

### 3. 子章节层级

```python
# 识别父子关系
if chapter_a.level < chapter_b.level:
    chapter_b.parent = chapter_a.num
```

### 4. 图表公式引用

```python
# "见表1" → 建立引用关系
# "如图1所示" → 建立引用关系
references = extract_references(content)
```

### 5. 附录识别

```python
# 附录A（资料性附录）
# 附录 B（规范性附录）
appendix_match = re.match(r'附录\s*([A-Z])\s*（(.*?)）', title)
```

---

## 🚀 实现步骤

### Phase 1: 单页处理

1. 渲染页面图像
2. VLM布局识别
3. 提取章节信息
4. 识别结构化元素
5. 生成RAG + Render

### Phase 2: 章节聚合

1. 按章节号分组
2. 合并跨页内容
3. 建立章节顺序
4. 生成文档级输出

### Phase 3: 后处理

1. 清理残留噪音
2. 修复格式错误
3. 验证完整性
4. 生成最终输出

---

## 📚 参考资料

- **MCP协议规范**：[MCP_CONFIGURATION_GUIDE.md](./MCP_CONFIGURATION_GUIDE.md)
- **VLM集成设计**：[MCP of PDF2MD v2.0.md](./MCP%20of%20PDF2MD%20v2.0.md)
- **测试文档**：GBT16749-2018.pdf

---

## 📝 变更日志

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2025-03-03 | 1.0 | 初始版本，定义完整实现逻辑 | Claude |
