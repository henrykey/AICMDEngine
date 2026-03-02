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
        self.provider = os.getenv("VLM_MODEL_PROVIDER", "qwen").strip().lower()
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

        self.api_key = self._get_api_key()
        self.base_url = self._get_base_url()
        self.model = self._get_model_name()

        self._enabled = bool(self.api_key and self.base_url and self.model)
        self._client = None
        if self._enabled:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except Exception:
                self._enabled = False
                self._client = None

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

        prompt = """请分析这个PDF页面图片的文档布局结构。

**任务：识别并标记以下区域**

1. **页眉** - 页面顶部重复出现的内容，例如：
   - 文档标题（如"压力容器波形膨胀节"）
   - 标准编号（如"GB/T 16749—2018"、"GB/ T 16749—2018"）
   - 英文标题

2. **页脚** - 页面底部重复出现的内容，例如：
   - 发布信息（如"2019-04-01 实施"、"2018-09-17 发布"）
   - 机构名称（如"国家市场监督管理总局"、"中国国家标准化管理委员会"）

3. **页码** - 页面编号，例如：
   - "第X页"格式（如"第1页"、"第5页"）
   - 纯数字（如"1"、"5"）

4. **正文** - 实际文档内容，需要保留

**输出要求：**
请以JSON格式输出：
```json
{
  "header": ["页眉1", "页眉2"],
  "footer": ["页脚1", "页脚2"],
  "page_number": "识别到的页码",
  "content_summary": "一句话描述正文主要内容",
  "confidence": "high|medium|low"
}
```

**注意：**
- 如果某个区域不存在，返回空数组 []
- 页码只返回数字或"第X页"文字，不包括"##"标记
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
                    max_tokens=1024,
                    timeout=self.timeout_sec,
                    temperature=0.1,
                )

                content = response.choices[0].message.content if response.choices else ""
                if not content:
                    return self._get_default_layout()

                # 尝试解析JSON
                parsed = self._extract_json_from_response(content)
                if parsed:
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

    def _get_default_layout(self) -> Dict:
        """返回默认的空布局结构。"""
        return {
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
            "general": """请识别图片中的所有文字内容。

**重要说明：**
这是PDF文档的一页，请按照以下规则识别：

1. **必须忽略的内容（不要输出）：**
   - 页眉：页面顶部重复出现的标题（如"GB/T 16749—2018"、"压力容器波形膨胀节"）
   - 页脚：页面底部重复出现的信息（如"2019-04-01 实施"、"国家市场监督管理总局"）
   - 页码："第X页"格式或纯数字页码

2. **必须保留的内容（正常输出）：**
   - 正文内容（章节标题、段落文字）
   - 列表项（如"a)"、"b)"、"1)"、"2)"等）
   - 表格内容
   - 公式说明

3. **输出格式要求：**
   - 保持原有的段落结构
   - 保持列表格式
   - 不要输出页眉、页脚、页码

**示例：**
如果页面顶部有"GB/T 16749—2018"，不要输出
如果页面底部有"第5页"，不要输出
只输出中间的正文内容""",
        }
        return prompts.get(task_type, prompts["general"])
