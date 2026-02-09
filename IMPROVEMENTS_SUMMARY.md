# Task Analysis & Member Creation Improvements

## 改进清单

### 1. 任务分析Prompt强化（第135-195行）
**问题**: 任务分析可能没有正确识别成员创建任务
**改进**:
- 在Prompt最开始明确要求："特别关注人员任务 - 用户提到的任何人都必须有对应任务"
- 提供了详细的JSON示例，包含成员创建任务
- 关键规则部分明确说明"如果用户说部门经理是某某人，必须创建create_member任务"

### 2. 规划Prompt增强（第809-821行 - 新增CRITICAL部分）
**问题**: 规划LLM可能忽略了成员创建需求
**改进**:
- 在Prompt最顶部（system_prompt开头）添加"⚠️ CRITICAL: MEMBER CREATION RULE"
- 明确说明：
  - 检查人员是否存在
  - 如果不存在或邮箱有变更 → 生成POST /v2/members步骤
  - 成员创建步骤必须在角色分配之前
  - 必须包含: full_name, email, username

### 3. 任务上下文构建改进（第296-349行）
**问题**: 任务分析信息可能没有有效地传递到规划Prompt
**改进**:
- 明确分离成员创建任务与其他任务
- 用"🔴 CRITICAL TASK BREAKDOWN (MEMBERS FIRST!)"格式展示
- 成员任务单独列在"## Step 1: CREATE MEMBERS"部分
- 其他任务列在"## Step 2-N"部分
- 先决条件成员单独突出显示

### 4. 规划指令强化（第360行）
**改进**:
- 指令文本改为："🔴 CRITICAL: Generate execution steps with MEMBER CREATION FIRST"
- 明确提醒："CRITICAL TASK BREAKDOWN section above explicitly lists members"
- 要求："Include creation steps for all listed members BEFORE any role assignments"

### 5. 详细的调试日志（四个关键点）
**改进**:
- 任务分析开始/结束时的日志
- 成员任务与其他任务的分离日志
- 规划结果的成员步骤验证日志
- 确认消息生成时的成员计数日志

## 关键变更

| 组件 | 改动 | 目的 |
|-----|-----|------|
| `_analyze_tasks()` Prompt | 增强成员识别、添加详细示例 | 确保识别所有人员 |
| `_build_prompt()` 开头 | 新增CRITICAL MEMBER CREATION RULE | 在所有其他规则前强调成员 |
| 任务上下文构建 | 分离成员任务，用标志区分优先级 | 让LLM明确看到哪些是成员任务 |
| 规划指令 | 改为"🔴 CRITICAL"格式 | 强调重要性 |
| 日志 | 关键步骤添加debug/info日志 | 便于诊断问题 |

## 预期效果

当用户再次提交：
```
添加两个Joinkey Software公司的下属组织机构叫财务部和行政管理部,名字都用英文。
财务部添加三个岗位，部门经理，会计和出纳。部门经理Zhao Hongxia，邮件zhaohx@joinkey.com。
行政部增加一个部门经理岗位，3个员工岗位。部门经理Yu Huawei，邮件yuhw@joinkey.com。
开发部增加一个岗位叫测试，测试岗位人员设为Fang Haihua。
```

系统应该：
1. ✅ 任务分析识别3个成员创建任务（Zhao Hongxia, Yu Huawei, Fang Haihua）
2. ✅ 在"CRITICAL TASK BREAKDOWN"部分明确列出这3个成员
3. ✅ 规划Prompt收到这个信息，并在生成计划时包含成员创建步骤
4. ✅ 最终确认消息中"将创建的成员"部分显示这3个人

## 日志追踪

启用DEBUG日志后，应该看到类似的输出：

```
INFO: Task analysis: Starting LLM analysis...
INFO: Task analysis: Got LLM response, length=XXX
INFO: Task analysis: 9 total tasks, 3 member tasks
INFO: Task analysis: Member tasks identified: ['Zhao Hongxia', 'Yu Huawei', 'Fang Haihua']
INFO: Task analysis: Prerequisites: 3 members must create
INFO: Task analysis: Members to create: [('Zhao Hongxia', 'zhaohx@joinkey.com'), ...]

INFO: Building task context from analysis: tasks=9, has_prerequisites=True
INFO: Task separation: 3 member tasks, 6 other tasks
INFO: Added 3 member creation tasks to context
INFO: Added 3 prerequisite members to context: ['Zhao Hongxia', 'Yu Huawei', 'Fang Haihua']

INFO: Planning result: 10 total steps, 3 member creation steps
INFO: Member creation steps found: ['Create member: Zhao Hongxia', ...]

INFO: Confirmation message: 2 orgs, 5 roles, 3 members to create
```

## 测试建议

1. **直接使用API重新提交原始对话**，按以下顺序：
   - "添加两个Joinkey Software公司的下属组织机构..."
   - "1. 你自己翻译一个。2. development。"
   - "1. 对的，就是id为13的部门。2.是一个人，原有的email是错的..."

2. **检查日志输出**：
   - 查看是否有"3 member tasks"日志
   - 查看是否有"3 member creation steps found"日志

3. **检查确认消息**：
   - 应该显示"👤 **将创建的成员** (3 个):"
   - 列出Zhao Hongxia, Yu Huawei, Fang Haihua

## 代码状态

✅ 所有改动已完成
✅ 语法检查已通过
✅ 代码编译成功

准备好进行完整测试。
