# PDF2MD 计算书解析首版执行报告

日期：2026-09-07。基线：main / fa19a54f8fbc2f9d73c5c8af836b61a4d71b837e，开始时工作区干净。
用户授权：同意计算书独立解析建议并要求实施。没有提交、推送、构建、重启或 Membership 修改授权。

## 实现与自审

1. 识别与分流：现有 VLM 返回 data_table / calculation_sheet / mixed / uncertain。
   计算书候选由独立 parse_calculation_sheet 处理，按分组、计算项和来源组织，不使用 pandas 网格。
2. 保留 OCR 原文；公式、条件、单位、校核及引用只能引用目标对象的确切文本。
   来源字符遗漏、错误引用、公式改写、括号不平衡、越界位置均显式阻断。
3. 派生两列表达单独放在 calculation_sheet.render_markdown。混合型与不确定类型只标记待审。
   计算书不得被普通 lookup_sections 查询使用；查询入口在模型和 pandas 前阻断。
4. 最终采用两阶段：复用上传/单页的既有语义调用做分类，计算书再调用专门的
   extract_calculation_sheet。vlm_config.table_analysis_max_model_calls 默认 2（分类 1 + 提取 1），
   同页全部表共用，范围 0..8；耗尽返回明确原因。0 不调用表格语义模型。该上限是逻辑调用数，
   不把现有 provider 传输重试/fallback 误称为物理请求预算。新增计算提取不做循环补全。
   输出上限为 min(provider max_tokens, 16384)，不自动执行公式。
5. 单页 GLM 在启用既有 VLM 描述调用时，先分类后网格化；正常数据表回到原有网格路径。
   双输出、区域、直接 VLM 表格响应的类型/计算项契约贯穿归一化。
6. 独立 table_content_quality 不把名字/描述齐全、HTML 闭合、EXTRACTED 或源一致性当成图像验收。
7. 两种 Dockerfile 已加入新模块 COPY；本轮不构建镜像。

兼容边界：纯 native、关闭语义的 GLM、仅对象 HTML 裁剪恢复不增加隐式模型调用。
旧模型响应未返回 table_kind 时继续旧契约，不宣称完成分类。Membership 须另行接入派生显示字段、
类型与质量门禁；本轮未改变业务持久化或索引。跨页依赖与混合分区不在首版范围。

## Goals Loop 证据

- 首次失败用例：新计算书测试因缺少解析模块而 collection error，日志 /tmp/pdf2md-calculation-red.txt。
- 已实现并验证：源一致性、公式/条件错配、遗漏、非数据类型、重复/外来身份、直接与上传入口、
  禁用模型、源位置边界、截断响应、真实调用暴露的缺少 items/错误依据、输出转义。
- CodeGraph status / query / context 已检查，sync 成功；没有全量重建。
- 私有图像、OCR 和模型原始响应只保存在现有数据目录及 /tmp，不加入提交。

## 真实模型验收

用户先同意真实验收；自动审批因未明确私有 p15 到外部 Qwen 的具体数据目的地授权而拒绝。
随后用户明确“同意”：允许 p15 图像及已有 OCR 发送 Qwen qwen3-vl-flash，1 次物理调用，
最多 16384 输出 token。脚本禁用 SDK 重试，并对物理 create 调用计数硬限制为 1。
只读读取现有 PDF2MD 绑定的模型配置，凭据不打印、不写报告。

第一轮：1 次物理/逻辑调用，9.28 秒，finish_reason=stop。
模型返回 calculation_sheet，但没返回 calculation_sheet.sections/items；部分分类依据来自旧语义说明。
校验降为 uncertain，未错误宣布完成。日志：/tmp/pdf2md-calculation-live-{raw,result,summary}.json。

据此修正：明确类型分流和计算项是语义元数据之外的必填输出，移除表格输入中的旧生成 context，
禁止把旧语义说明当成来源。新增对应离线回归，没有放松确切来源校验。
用户另行“确认”第二次同范围、同目的地、同一次调用上限复验。
第二轮：1 次物理/逻辑调用，6.81 秒，finish_reason=stop。
分类证据通过，接受 calculation_sheet；模型仍只返回元数据，没有 sections/items。
解析器返回 invalid_calculation_sheet / unresolved（0 个已接受计算项），不误报通过。
日志：/tmp/pdf2md-calculation-live2-{raw,result,summary}.json。

两次真实结果证明合并输出不可靠，因此最终撤回“同一语义响应兼顾全部提取”的优化，
实现独立 VLM 提取方法与明确共享调用预算。该最终两阶段协议已通过离线桩回归，
但两次授权的真实调用额度已全部使用，未擅自追加调用。最终路径真实复验未完成。
这两次结果不是最终协议的成功验收，也不是部署后端到端验收。

## 离线验证与交付状态

最终离线回归：529 passed，64 个已有警告，3.60 秒。新增计算书用例 45 项。
命令：`.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_calculation_sheet.py
 tests/test_pdf2md_quality_completion.py tests/test_pdf2md_content_quality.py
 tests/test_pdf2md_enhanced_table_query.py tests/test_pdf2md_object_semantics.py
 tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_object_recovery.py
 tests/test_pdf2md_enhanced_upload_semantics.py tests/test_pdf2md_enhanced_bad_text_policy.py`。
日志 /tmp/pdf2md-calculation-final-tests.txt。覆盖两个 Docker COPY 隔离导入测试，未实际构建。
一次中间回归有 3 个失败，原因是 mock wire 按旧提示词字符串路由；仅更新该定位条件后通过，
保留原有调用次数、图片尺寸和内容断言。不是关闭测试或放松生产校验。
最终 py_compile 与 git diff --check 通过；CodeGraph sync 成功。
源一致性不是原图识别准确性，首版保持 image_verified=false。
未构建/重启/部署，因此本地源码结果不代表当前服务已运行新解析器。
未执行 Membership 集成验收，未提交或推送。
