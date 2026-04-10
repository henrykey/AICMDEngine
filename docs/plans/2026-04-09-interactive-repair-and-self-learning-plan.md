# 交互式修复与自学习任务系统方案

日期：2026-04-09

## 背景

当前 Task Planner 的标准链路为：

1. 用户输入自然语言任务
2. 系统检索相关命令子集
3. LLM 生成结构化执行计划
4. 系统执行计划
5. 若失败，则任务结束

这条链路的问题在于：第一次计划或执行失败后，系统通常只能停在技术错误，或者错误地给出业务结论。它不能继续探索，也不能把这次失败转化为后续成功的经验。

## 目标

建立一套“失败不中断”的交互式任务系统：

1. 失败后不直接结束。
2. 系统能分析失败类型，判断是否可修复。
3. 若可修复，系统继续与用户交互，请求新的思路或提示。
4. 系统根据失败原因和用户提示重新规划，再执行。
5. 成功后沉淀为新的可复用知识样本，用于后续任务的检索和规划增强。

## 核心原则

### 1. 自然语言理解依赖 LLM

LLM 负责：

- 理解用户意图
- 生成计划
- 在修复模式下根据失败上下文重新规划
- 生成用户可读的规划描述

### 2. 执行正确性不能完全依赖 LLM

代码负责：

- 执行计划
- 校验依赖是否满足
- 分析失败原因
- 判断当前失败是否可恢复

### 3. 失败不是终点，而是训练入口

失败后系统进入“交互式修复模式”，继续探索正确解法，而不是立刻把失败暴露给用户或给出错误业务结论。

### 4. 自学习的对象是“问题 + 意图 + 成功求解路径”

系统要沉淀的不是某个一次性答案，而是：

- 原始问题
- 识别到的意图
- 初始失败方案
- 用户给出的修正思路
- 最终成功 plan
- 最终答案
- 可复用 pattern

## 目标流程

### 正常流程

1. 用户输入问题
2. 系统检索命令子集
3. LLM 生成：
   - `plan_description`
   - `plan`
4. 系统执行 `plan`
5. 成功则返回结果

### 修复流程

1. 计划执行失败
2. 系统分析失败原因
3. 如果失败可恢复，则给出：
   - `repair_hint.summary`
   - `repair_hint.coach_prompt`
4. 用户提供新的方法或提示
5. 系统将：
   - 原始问题
   - 失败 plan
   - 失败原因
   - 用户提示
   一并交给 LLM
6. LLM 返回修复后的 `repaired_plan`
7. 系统执行修复后的计划
8. 成功后沉淀知识

## 状态机

定义如下状态：

- `planning`
- `executing`
- `repairable_failed`
- `coaching`
- `replanned`
- `resolved`
- `abandoned`

其中：

- `repairable_failed` 表示系统认为失败可以通过继续探索来修复
- `coaching` 表示系统正在等待用户作为测试员/训练教练提供提示

## 数据结构

### 执行详情增加 repair hint

`ExecutionDetailResponse` 增加：

- `repairHint.recoverable`
- `repairHint.category`
- `repairHint.summary`
- `repairHint.suggestedAction`
- `repairHint.coachPrompt`

用于告诉前端或调用方：

- 这次失败是否值得继续修复
- 当前应该向用户请求什么类型的提示

### 修复请求

新增 `RepairExecutionRequest`：

- `goal`
- `guidance`
- `conversationHistory`
- `authToken`

### 修复响应

新增 `RepairExecutionResponse`：

- `repairSummary`
- `repairPlanDescription`
- `repairedPlan`
- `sourceExecutionId`

## 后端改造

### 1. Execution 记录保留原始 goal 和 plan

执行记录中新增：

- `original_goal`
- `original_plan`

这样在 repair 阶段不必完全依赖前端重传上下文。

### 2. Execution Engine 增加失败分析

对以下失败进行分类：

- 缺少中间依赖步骤
- 参数解析失败
- JSONPath/结果提取失败
- 已确认的业务结论
- 其它未知失败

### 3. Planning Engine 增加 repair_plan

新增修复模式 prompt，输入包括：

- 原始问题
- 失败 plan
- 失败原因
- 用户教练提示
- 当前可用命令集

输出包括：

- `repair_summary`
- `plan_description`
- `plan`

## API 方案

新增接口：

`POST /executions/{execution_id}/repair`

用途：

- 基于失败的执行记录和用户提示生成修复后的 plan

输入：

- 原始问题
- 用户提示
- 可选对话历史

输出：

- 修复摘要
- 面向用户的修复说明
- 修复后的可执行计划

## 前端交互建议

前端遇到 `repairHint.recoverable = true` 时，不直接显示“任务失败”，而应显示：

- 当前方案失败原因
- 系统建议的继续探索方向
- 一个输入框，请用户继续指导系统

例如：

“当前方案失败在没有正确提取成员 ID。你建议我下一步如何从成员列表中定位目标成员？”

## 自学习沉淀

每次修复成功后，记录如下学习样本：

- 原始问题
- 归一化意图
- 初始失败 plan
- 失败原因
- 教练提示
- 最终成功 plan
- 最终答案
- 可复用 pattern

建议把学习样本分三类回写：

1. `qa_example`
2. `plan_example`
3. `execution_pattern`

## 分阶段实施

### 第一期：失败不中断

- 增加失败分析
- 增加 repair hint
- 增加 repair API
- 支持基于用户提示重规划

### 第二期：交互闭环

- 前端支持修复对话
- 用户可直接在失败后提供新方法
- 系统支持多轮修复

### 第三期：自学习沉淀

- 成功修复样本自动写回知识库
- 下次相似问题优先召回修复后的 pattern

## 当前实现范围

本次代码实现覆盖第一期的后端基础：

- 执行记录保留原始问题与计划
- 执行失败生成 `repairHint`
- 新增修复请求/响应模型
- 新增 `POST /executions/{execution_id}/repair`
- 新增基于失败上下文和用户提示的 `repair_plan`

前端教练式修复交互和知识回写属于后续阶段。
