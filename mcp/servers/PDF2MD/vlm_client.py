#!/usr/bin/env python3
import base64
import json
import os
import re
import time
from typing import Dict, Optional


class UnifiedVLMClient:
    """Unified OpenAI-compatible VLM client for qwen/gpt-4o/glm-4v."""

    def __init__(self, timeout_sec: int = 60, max_retries: int = 2) -> None:
        import sys
        debug_log = "/tmp/pdf2md_debug.log"
        def log(msg):
            with open(debug_log, "a") as f:
                f.write(f"{msg}\n")
            print(msg, file=sys.stderr, flush=True)

        self.provider = os.getenv("VLM_MODEL_PROVIDER", "qwen").strip().lower()
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

        log(f"[DEBUG VLM] provider: {self.provider}")
        self.api_key = self._get_api_key()
        self.base_url = self._get_base_url()
        self.model = self._get_model_name()

        log(f"[DEBUG VLM] api_key: {self.api_key[:20] if self.api_key else None}...")
        log(f"[DEBUG VLM] base_url: {self.base_url}")
        log(f"[DEBUG VLM] model: {self.model}")

        self._enabled = bool(self.api_key and self.base_url and self.model)
        log(f"[DEBUG VLM] _enabled (before OpenAI import): {self._enabled}")

        self._client = None
        if self._enabled:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
                log(f"[DEBUG VLM] OpenAI client created successfully")
            except Exception as e:
                self._enabled = False
                self._client = None
                log(f"[DEBUG VLM] OpenAI import/init failed: {e}")

        log(f"[DEBUG VLM] Final _enabled: {self._enabled}")

    def _get_api_key(self) -> Optional[str]:
        key_map = {
            "qwen": os.getenv("QWEN_API_KEY"),
            "gpt-4o": os.getenv("OPENAI_API_KEY"),
            "glm-4v": os.getenv("ZHIPU_API_KEY"),
        }
        return key_map.get(self.provider)

    def _get_base_url(self) -> Optional[str]:
        base_url_map = {
            "qwen": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "gpt-4o": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "glm-4v": os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        }
        return base_url_map.get(self.provider)

    def _get_model_name(self) -> Optional[str]:
        model_map = {
            "qwen": os.getenv("QWEN_MODEL_NAME", "qwen-vl-max-latest"),
            "gpt-4o": os.getenv("OPENAI_MODEL_NAME", "gpt-4o"),
            "glm-4v": os.getenv("ZHIPU_MODEL_NAME", "glm-4v"),
        }
        return model_map.get(self.provider)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get_effective_config(self) -> Dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model or "",
            "base_url": self.base_url or "",
            "enabled": str(self._enabled).lower(),
        }

    def recognize_complex_content(self, image_path: str, task_type: str = "general") -> str:
        if not self._enabled or not self._client:
            return ""

        prompt = self._get_prompt(task_type)
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=1024,
                    timeout=self.timeout_sec,
                    temperature=0.1,
                )
                content = response.choices[0].message.content if response.choices else ""
                if isinstance(content, list):
                    return "\n".join([item.get("text", "") for item in content if isinstance(item, dict)])
                return content or ""
            except Exception:
                if attempt >= self.max_retries:
                    return ""
                time.sleep(0.4 * (attempt + 1))

        return ""

    def recognize_layout(self, image_path: str) -> Dict:
        """识别页面布局，标记页眉、页脚、页码等区域（两阶段处理的阶段1）。

        返回格式:
        {
            "page_type": "normal|toc|cover",  # 页面类型：普通页/目录页/封面
            "header": ["页眉文本1", "页眉文本2"],
            "footer": ["页脚文本1", "页脚文本2"],
            "page_number": "页码文本",
            "content_summary": "对正文内容的简要描述",
            "confidence": "high|medium|low",
            "regions": [{"type": "header|footer|page_number", "text": "...", "keep": False}]
        }
        """
        if not self._enabled or not self._client:
            return self._get_default_layout()

        prompt = """请分析这个PDF页面图片的文档布局结构，识别页面类型和各个区域。

**任务：识别页面类型并标记区域**

**第一步：判断页面类型**

请根据以下特征判断页面属于哪种类型：

1. **封面页（cover）** - 具有以下多个特征：
   - 页面顶部有突出的标题（字体较大、居中显示）
   - 可能包含文档编号、版本号、发布日期等信息
   - 页面文字较少（通常不超过页面的1/3）
   - 内容通常集中在页面上半部分

2. **目录页（toc）** - 具有以下多个特征：
   - 有明确的标题，如"目录"、"目次"、"CONTENTS"、"Table of Contents"等
   - 包含章节或条目列表（每个条目通常有标题和对应的页码）
   - 页码通常以数字或"......X"的形式出现
   - 可能采用多栏排版

3. **空白页（blank）** - 具有以下特征：
   - 页面几乎空白（完全空白或只有极少量文字）

4. **普通内容页（normal）** - 具有以下特征：
   - 包含正文内容（段落、列表、表格、公式等）
   - 有章节标题（可能是"1."、"1.1"、数字编号等格式）
   - 内容通常占据页面的大部分区域

**第二步：标记页眉、页脚、页码**

在判断完页面类型后，请标记以下区域：

1. **页眉（header）** - 页面顶部重复出现的内容
   - 识别依据：在多页文档的每一页顶部都会重复出现
   - 可能是：文档标题、编号、公司名称等
   - 注意：如果是封面页，整个页面的标题不是页眉，是封面内容
   - 注意：如果是目录页，"目录"、"目次"等标题是页面内容，不是页眉

2. **页脚（footer）** - 页面底部重复出现的内容
   - 识别依据：在多页文档的每一页底部都会重复出现
   - 可能是：日期、公司名称、版权信息、网址等

3. **页码（page_number）** - 页面编号
   - 格式可能是："第X页"、纯数字"1"、罗马数字"I"等
   - 通常位于页面底部或顶部角落

**输出要求：**
请以JSON格式输出分析结果：
```json
{
  "page_type": "normal|toc|cover|blank",
  "header": ["页眉1", "页眉2"],
  "footer": ["页脚1", "页脚2"],
  "page_number": "识别到的页码",
  "content_summary": "简要描述页面的主要内容",
  "confidence": "high|medium|low"
}
```

**重要说明：**
- 如果某个区域不存在或无法确定，返回空数组 []
- 页码只返回数字或"第X页"文字，不包括"##"等markdown标记
- content_summary用一句话概括页面内容
- 只输出JSON，不要有其他文字说明
"""

        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=4096,  # 增加到4096，本地Qwen模型会在reasoning字段输出大量思考
                    timeout=self.timeout_sec,
                    temperature=0.1,
                )

                # 调试：打印response信息
                print(f"[DEBUG] VLM响应对象: choices={len(response.choices) if response.choices else 0}")

                content = response.choices[0].message.content if response.choices else ""
                if not content:
                    print(f"[DEBUG] VLM返回空响应")
                    print(f"[DEBUG] response对象: {response}")
                    return self._get_default_layout()

                print(f"[DEBUG] VLM原始响应:\n{content}\n")

                # 尝试解析JSON
                parsed = self._extract_json_from_response(content)
                if parsed:
                    print(f"[DEBUG] VLM解析成功: {parsed}")
                    # 添加regions列表便于后续处理
                    regions = []
                    for h in parsed.get("header", []):
                        regions.append({"type": "header", "text": h, "keep": False})
                    for f in parsed.get("footer", []):
                        regions.append({"type": "footer", "text": f, "keep": False})
                    if parsed.get("page_number"):
                        regions.append({
                            "type": "page_number",
                            "text": parsed["page_number"],
                            "keep": False
                        })
                    parsed["regions"] = regions
                    return parsed

                print(f"[DEBUG] VLM JSON解析失败，返回默认布局")
                print(f"[DEBUG] 失败的响应内容: {content[:500]}")  # 打印前500字符
                return self._get_default_layout()

            except Exception as e:
                if attempt >= self.max_retries:
                    return self._get_default_layout()
                time.sleep(0.4 * (attempt + 1))

        return self._get_default_layout()

    def _extract_json_from_response(self, response: str) -> Optional[Dict]:
        """从VLM响应中提取JSON内容。"""
        if not response:
            return None

        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 尝试提取markdown代码块中的JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取花括号之间的内容
        brace_match = re.search(r'\{.*\}', response, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _try_fix_truncated_json(self, response: str) -> Optional[Dict]:
        """尝试修复被截断的JSON。

        常见截断模式：
        1. JSON字符串中间被截断（例如render字段）
        2. JSON末尾缺少闭合的花括号
        """
        if not response:
            return None

        # 先提取markdown代码块中的内容
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试提取花括号之间的内容
            brace_match = re.search(r'\{(.*)', response, re.DOTALL)
            if brace_match:
                json_str = '{' + brace_match.group(1)
            else:
                return None

        # 尝试补全JSON
        # 检查是否缺少闭合的花括号
        open_braces = json_str.count('{')
        close_braces = json_str.count('}')

        if close_braces < open_braces:
            # 补全缺少的闭合花括号
            json_str += '\n' + '}' * (open_braces - close_braces)

        # 检查字符串是否被截断
        # 如果在字符串中间截断（例如 "render": "被截断的内容...）
        # 尝试找到最后一个完整的字符串值并补全
        lines = json_str.split('\n')

        # 从后往前找，确保JSON结构完整
        # 简单策略：如果render字段的值不完整，添加闭合的引号和花括号
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            # 如果最后几行看起来像被截断的内容
            if line and not line.endswith(('}', ']', '"', ',')):
                # 可能被截断了，尝试补全
                # 添加引号和闭合括号
                json_str = '\n'.join(lines[:i+1])
                # 确保字符串引号闭合
                if json_str.count('"') % 2 != 0:
                    json_str += '"'
                # 确保花括号闭合
                remaining_open = json_str.count('{') - json_str.count('}')
                if remaining_open > 0:
                    json_str += '\n' + '}' * remaining_open
                break

        # 尝试解析修复后的JSON
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None

    def extract_toc(self, image_path: str) -> Dict:
        """专门提取目录页的结构化目录信息。

        返回格式:
        {
            "title": "目 次",
            "entries": [
                {"level": 1, "title": "前言", "page": "1"},
                {"level": 1, "title": "范围", "page": "1"},
                {"level": 2, "title": "规范性引用文件", "page": "2"},
                ...
            ],
            "confidence": "high|medium|low"
        }
        """
        if not self._enabled or not self._client:
            return {"title": "", "entries": [], "confidence": "low"}

        prompt = """请提取这个目录页的结构化信息。

**任务：**
1. 识别目录标题（如"目 次"、"目录"、"CONTENTS"等）
2. 提取所有目录条目，包括：
   - 层级（level）：1级标题、2级标题、3级标题等
   - 标题（title）：章节名称
   - 页码（page）：该章节所在的页码

**输出要求：**
请以JSON格式输出：
```json
{
  "title": "目录标题",
  "entries": [
    {"level": 1, "title": "章节名称", "page": "页码"},
    {"level": 2, "title": "子章节名称", "page": "页码"}
  ],
  "confidence": "high|medium|low"
}
```

**注意：**
- 只输出JSON，不要有其他文字说明
- 如果页码是罗马数字（I, II, III），请保留原样
- 层级根据缩进或字体大小判断
- 只输出JSON，不要有其他文字说明
"""

        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=2048,
                    timeout=self.timeout_sec,
                    temperature=0.1,
                )

                content = response.choices[0].message.content if response.choices else ""
                if not content:
                    return {"title": "", "entries": [], "confidence": "low"}

                # 尝试解析JSON
                parsed = self._extract_json_from_response(content)
                if parsed:
                    return parsed

                return {"title": "", "entries": [], "confidence": "low"}

            except Exception as e:
                if attempt >= self.max_retries:
                    return {"title": "", "entries": [], "confidence": "low"}
                time.sleep(0.4 * (attempt + 1))

        return {"title": "", "entries": [], "confidence": "low"}

    def _get_default_layout(self) -> Dict:
        """返回默认的空布局结构。"""
        return {
            "page_type": "normal",  # 默认为普通页
            "header": [],
            "footer": [],
            "page_number": "",
            "content_summary": "",
            "confidence": "low",
            "regions": []
        }

    def should_filter_text(self, text: str, layout_info: Dict) -> bool:
        """判断文本是否应该被过滤（是页眉/页脚/页码）。

        Args:
            text: 要检查的文本（可能是OCR识别的文本）
            layout_info: recognize_layout返回的布局信息

        Returns:
            True表示应该过滤，False表示保留
        """
        text_stripped = text.strip()

        # 检查是否匹配页眉（部分匹配即可）
        for header in layout_info.get("header", []):
            if header.lower() in text_stripped.lower() or text_stripped.lower() in header.lower():
                return True

        # 检查是否匹配页脚（部分匹配即可）
        for footer in layout_info.get("footer", []):
            if footer.lower() in text_stripped.lower() or text_stripped.lower() in footer.lower():
                return True

        # 检查是否匹配页码
        page_num = layout_info.get("page_number", "")
        if page_num:
            # 如果页码是"第X页"格式
            if page_num in text_stripped:
                return True
            # 如果text是"## 第X页"格式，提取数字部分比较
            if re.match(r'^##\s*第\s*\d+\s*页\s*$', text_stripped):
                text_page_num = re.sub(r'^##\s*第\s*(\d+)\s*页\s*$', r'\1', text_stripped)
                if text_page_num in page_num or page_num in text_page_num:
                    return True

        # 正则匹配常见的页码格式（兜底规则）
        if re.match(r'^##\s*第\s*\d+\s*页\s*$', text_stripped):
            return True

        return False

    def recognize_content_with_layout_filter(self, image_path: str, layout_info: Dict) -> str:
        """识别内容并根据布局信息过滤噪音（两阶段处理的阶段2）。

        Args:
            image_path: 页面图片路径
            layout_info: recognize_layout返回的布局信息

        Returns:
            过滤后的干净文本内容
        """
        if not self._enabled or not self._client:
            return ""

        # 构建过滤上下文
        filter_context = self._build_filter_context(layout_info)

        prompt = f"""请识别图片中的所有文字内容。

{filter_context}

**输出要求：**
1. 识别并输出所有正文内容
2. 保持原有的段落结构和列表格式
3. 不要输出上面标记为"必须忽略"的内容

**输出格式：**
- 保持段落换行
- 保持列表格式（如"a)"、"b)"、"1)"、"2)"）
- 直接输出文字，不需要任何标记或说明
"""

        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=4096,  # 增加token限制以获取更多内容
                    timeout=self.timeout_sec,
                    temperature=0.1,
                )

                content = response.choices[0].message.content if response.choices else ""
                if isinstance(content, list):
                    return "\n".join([item.get("text", "") for item in content if isinstance(item, dict)])
                return content or ""

            except Exception:
                if attempt >= self.max_retries:
                    return ""
                time.sleep(0.4 * (attempt + 1))

        return ""

    def _build_filter_context(self, layout_info: Dict) -> str:
        """构建过滤上下文说明。"""
        context_parts = ["**必须忽略的内容：**"]

        headers = layout_info.get("header", [])
        if headers:
            context_parts.append("\n- 页眉（不要输出）：")
            for h in headers:
                context_parts.append(f"  * {h}")

        footers = layout_info.get("footer", [])
        if footers:
            context_parts.append("\n- 页脚（不要输出）：")
            for f in footers:
                context_parts.append(f"  * {f}")

        page_num = layout_info.get("page_number", "")
        if page_num:
            context_parts.append(f"\n- 页码（不要输出）：{page_num}")

        context_parts.append("\n**必须保留的内容：**")
        context_parts.append("- 正文内容（章节标题、段落、列表）")
        context_parts.append("- 表格内容")
        context_parts.append("- 公式说明")

        return "\n".join(context_parts)

    def _get_prompt(self, task_type: str) -> str:
        prompts = {
            "formula": "请识别图中的数学公式，输出标准LaTeX格式。忽略背景水印，只输出公式。",
            "table": "请识别图中的表格，输出Markdown格式并保持行列结构。忽略水印。",
            "figure_caption": "请用一句话描述图中主要对象和关系，输出简洁中文说明。",
            "general": """请识别图片中的所有文字内容，保持原文格式和结构。

**必须忽略的内容（不要输出）：**
- 页眉：页面顶部重复出现的标题、编号、名称等
- 页脚：页面底部重复出现的日期、公司名称、版权信息等
- 页码：页面编号（如"第X页"、纯数字、罗马数字等）

**必须保留的内容（正常输出）：**
- 章节标题：包括章节编号和完整标题（如"1. 概述"、"6.3.2 技术要求"）
- 正文段落：所有段落内容
- 列表内容：包括列表符号（a) b) c)、1) 2) 3)、——、• 等）
- 表格内容：保持表格的行列结构
- 公式和数学表达式：包括公式编号
- 图表标题和说明

**识别注意事项：**
1. 章节标题的特征：
   - 通常以数字编号开头（如"1."、"2.1"、"6.3.2"）
   - 或以特殊词开头（如"附录"、"Chapter"、"Section"）
   - 字体通常比正文粗或大
   - 不要把表格中的数字或公式中的变量误认为章节标题

2. 列表格式的特征：
   - 有明确的列表符号：a) b) c)、1) 2) 3)、——、•、- 等
   - 或有缩进结构
   - 保持原有的列表符号和层级

3. 表格的特征：
   - 有行列结构
   - 第一行通常是表头
   - 保持表格内容的完整性

**输出格式要求：**
1. 保持原有段落结构（用空行分隔段落）
2. 保持列表的缩进和符号
3. 保持表格的行列结构
4. 不要添加任何解释性文字，直接输出识别的内容
5. 如果某个区域的内容被标记为"必须忽略"，则不要输出该部分内容
""",
        }
        return prompts.get(task_type, prompts["general"])

    def generate_dual_mode_content(self, image_path: str) -> Dict:
        """生成双模式内容：Render（展示用）和RAG（检索用）。

        使用V2流程化提示词，生成两套数据：
        - Render: Markdown格式，包含表格、插图描述、LaTeX公式
        - RAG: 纯文本描述，用于语义检索

        返回格式:
        {
            "render": "Markdown字符串",
            "rag": "文字描述字符串",
            "success": True/False,
            "error": "错误信息（如果失败）"
        }
        """
        if not self._enabled or not self._client:
            return {"render": "", "rag": "", "success": False, "error": "VLM未启用"}

        # V2流程化提示词
        prompt = """分析这页PDF，生成Render和RAG两套数据。

【Render】- 用于展示（Markdown格式）：
- 识别页面类型（封面/目录/正文）
- 封面：保留标题、编号、日期
- 目录：保留章节名称和层次，去掉页码
- 正文：去掉页眉页脚页码
  * 表格转为Markdown表格（不要用base64图片）
  * 插图：用一句话详细描述占位（不要用base64图片）
  * 公式转LaTeX格式

【RAG】- 用于检索（纯文本）：
- 表格：简单描述内容
- 插图：详细描述
- 公式：简单描述含义

输出JSON格式：{"render": "Markdown内容", "rag": "文字描述"}
注意：不要输出base64图片，用文字描述代替。"""

        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=16384,  # 增加以支持更长的内容
                    timeout=120,
                    temperature=0.1,
                )

                content = response.choices[0].message.content if response.choices else ""
                if not content:
                    return {"render": "", "rag": "", "success": False, "error": "VLM返回空响应"}

                # 提取JSON
                parsed = self._extract_json_from_response(content)
                if parsed and "render" in parsed and "rag" in parsed:
                    return {
                        "render": parsed["render"],
                        "rag": parsed["rag"],
                        "success": True,
                        "error": None
                    }

                # JSON解析失败，可能是被截断，尝试修复
                parsed_fixed = self._try_fix_truncated_json(content)
                if parsed_fixed and "render" in parsed_fixed and "rag" in parsed_fixed:
                    return {
                        "render": parsed_fixed["render"],
                        "rag": parsed_fixed["rag"],
                        "success": True,
                        "error": None,
                        "warning": "JSON被截断但已修复"
                    }

                # 完全失败
                return {
                    "render": "",
                    "rag": "",
                    "success": False,
                    "error": f"JSON解析失败。原始响应: {content[:500]}"
                }

            except Exception as e:
                if attempt >= self.max_retries:
                    return {
                        "render": "",
                        "rag": "",
                        "success": False,
                        "error": f"调用失败: {str(e)}"
                    }
                time.sleep(0.4 * (attempt + 1))

        return {"render": "", "rag": "", "success": False, "error": "达到最大重试次数"}
