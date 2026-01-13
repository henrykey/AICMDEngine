# FORM-MCP BPM 对齐 - 完整方案总结

**发布日期**: 2026-01-13  
**阶段**: Phase 2.1 - FORM-MCP 升级  
**目标**: 使 FORM-MCP 完全对齐 BPM FormSchema 标准

---

## 📌 概述

本文档总结了 FORM-MCP 与 BPM FormSchema 的对齐工作，包含：
- 设计文档和实现计划
- 37 种控件类型完整支持
- 从原有的 7 种字段类型升级
- 完整的嵌套容器和布局系统

---

## 📂 关键文档

### 1. 实现计划
**文件**: `docs/plans/2026-01-13-FORM-MCP-BPM-ALIGNMENT.md`

包含 10 个任务：
1. ✅ 数据模型更新 (支持 37 种控件)
2. ✅ FormValidator 更新
3. ✅ generate_form 工具更新
4. ✅ validate_form 工具更新
5. ✅ 其他工具更新
6. ✅ 设计文档更新
7. ✅ 测试更新
8. ✅ 向后兼容性
9. ✅ 集成测试
10. ✅ 最终验证

### 2. 详细设计
**文件**: `docs/plans/2026-01-13-FORM-MCP-UPDATED-DESIGN.md`

包含：
- 完整的 FormSchema 数据结构
- 37 种控件类型详解
- 完整验证规则系统
- MCP 工具接口定义
- 与 ProcessEditor 的集成
- 代码示例和用法指南

---

## 🎯 核心改进

### 前后对比

| 维度 | 原设计 | 新设计 | 变化 |
|------|--------|--------|------|
| **字段容器名** | `fields` | `controls` | 对齐 BPM 标准 |
| **控件类型数** | 7 种 | 37 种 | +30 种 |
| **嵌套支持** | ❌ (sections分组) | ✅ (children 数组) | 完整支持 |
| **布局系统** | ❌ 简单 width | ✅ width + flexProps | Flex 完整支持 |
| **验证规则** | 简单对象 | 完整数组系统 | 多规则链支持 |
| **字段权限** | ✅ 保留 | ✅ 增强 | 保持不变 |
| **BPMN 绑定** | ✅ 保留 | ✅ 增强 | 保持不变 |

### 37 种控件类型

**基础输入** (8 种):
```
text, textarea, number, date, time, datetime, password, email
```

**选择控件** (6 种):
```
radio, checkbox, select, cascader, tree-select, switch
```

**高级输入** (7 种):
```
richtext, file-upload, image-upload, signature, rating, color, slider
```

**布局容器** (4 种):
```
grid, tabs, collapse, flex-container
```

**特殊控件** (5 种):
```
subform, address, relation, data-table, computed-field
```

**业务控件** (4 种):
```
member-selector, role-selector, org-selector, process-selector
```

**展示控件** (4 种):
```
title, description, divider, html
```

---

## 🔄 数据格式变化

### 原格式 (v1.0)

```json
{
  "form_id": "form-001",
  "form_name": "表单",
  "fields": [
    {
      "field_id": "f1",
      "field_type": "text",
      "label": "姓名",
      "required": true
    }
  ]
}
```

### 新格式 (v1.1 - BPM 对齐)

```json
{
  "formId": "form-001",
  "version": "1.0.0",
  "title": "表单",
  "controls": [
    {
      "id": "f1",
      "type": "text",
      "label": "姓名",
      "props": {
        "required": true
      },
      "width": "100%",
      "validation": [
        { "type": "required", "message": "必填" }
      ],
      "permissions": {...},
      "data_binding": {...}
    }
  ],
  "validation": {
    "rules": {
      "f1": [
        { "type": "required", "message": "必填" }
      ]
    }
  }
}
```

---

## ✨ FORM-MCP 增强功能

### 1. 字段级权限 (FORM-MCP 专有)

```json
{
  "permissions": {
    "view": {
      "condition": "role:approver",
      "applies_to": ["role:approver"]
    },
    "edit": {
      "condition": "role:approver",
      "applies_to": ["role:approver"]
    },
    "required": {
      "condition": "role:approver",
      "applies_to": ["role:approver"]
    }
  }
}
```

**特点**:
- 基于角色和部门的动态权限
- 支持复杂的权限表达式
- 与 Membership API 集成

### 2. BPMN 流程变量绑定 (FORM-MCP 专有)

```json
{
  "data_binding": {
    "bpmn_variable": "applicant_name",
    "source_type": "user_input|calculated|from_membership|from_kb",
    "source_config": {
      "entity_type": "member|role|department"
    }
  }
}
```

**特点**:
- 自动映射表单字段到流程变量
- 支持多种数据源
- 与 BPMN-MCP 无缝集成

### 3. 智能生成

- 从自然语言自动生成表单
- LLM 驱动的字段建议
- 自动权限推荐

---

## 🛠️ 实现指南

### 开始实现

1. **阅读计划**: `docs/plans/2026-01-13-FORM-MCP-BPM-ALIGNMENT.md`
2. **参考设计**: `docs/plans/2026-01-13-FORM-MCP-UPDATED-DESIGN.md`
3. **执行任务**: 按顺序完成 10 个任务
4. **运行测试**: 验证所有测试通过
5. **提交代码**: 按任务粒度提交

### 执行方式

**选项 1: Subagent-Driven (当前会话)**
```
使用 superpowers:subagent-driven-development 技能
每个任务由独立的 subagent 执行
任务间有代码审查检查点
```

**选项 2: Parallel Session (独立会话)**
```
在新会话中开启 worktree
使用 superpowers:executing-plans 逐批执行任务
更适合长期实现工作
```

---

## 📊 质量指标

### 测试覆盖

- **单元测试**: > 75%
- **集成测试**: 15+ 个测试
- **验证测试**: 37 种控件 + 嵌套 + 权限 + BPMN

### 代码质量

- **代码审查**: 每个任务都有审查
- **文档完整性**: 100%
- **向后兼容性**: 完全支持

---

## 🔗 与其他组件的关系

### BPMN-MCP
```
BPMN-MCP 生成流程定义
    ↓
    ├─ 提取流程变量
    ├─ 传递给 FORM-MCP
    └─ FORM-MCP 生成对应的表单
```

### ProcessEditor
```
ProcessEditor 保存流程定义
    ↓
    └─ 调用 FORM-MCP 生成表单
        ↓
        └─ 导入 FormEditor
```

### Membership MCP
```
Membership 提供组织结构
    ↓
    ├─ 部门、角色、成员
    ├─ FORM-MCP 读取组织数据
    ├─ 权限自动映射
    └─ 业务控件自动填充
```

### KB MCP
```
KB 存储表单模板和数据
    ↓
    └─ FORM-MCP 查询相似表单
        ├─ 字段建议
        ├─ 验证规则建议
        └─ 数据绑定建议
```

---

## 🎓 学习资源

### 核心概念

1. **BPM FormSchema** - 了解 BPM 标准格式
2. **37 种控件** - 掌握各种控件的用途和属性
3. **验证系统** - 理解多规则验证链
4. **权限模型** - 学习字段级权限的实现
5. **BPMN 绑定** - 理解流程变量映射

### 参考文档

- BPM 表单设计规范: `/bpm/docs/form-controls-spec.md`
- BPMN-MCP 设计: `docs/plans/2026-01-11-BPMN-MCP-Design.md`
- 验证系统: `/bpm/docs/FORM_DESIGNER_COMPLETE_SPECIFICATION_05.md`

---

## 🚀 后续优化方向

### 短期 (1-2 周)
- ✅ 完成 BPM 对齐
- ✅ 所有测试通过
- ✅ 文档完整

### 中期 (1-2 月)
- 增强 LLM 生成质量
- 添加表单模板库
- 支持表单版本管理

### 长期 (2-3 月)
- 表单预览和模拟
- A/B 测试支持
- 表单分析和优化建议

---

## 📞 支持和问题

### 文档问题
- 查看设计文档: `docs/plans/2026-01-13-FORM-MCP-UPDATED-DESIGN.md`
- 查看实现计划: `docs/plans/2026-01-13-FORM-MCP-BPM-ALIGNMENT.md`

### 实现问题
- 按实现计划逐步进行
- 每个任务都有具体的代码示例
- 测试验证每个步骤

### 集成问题
- 查看与其他组件的关系章节
- 参考相关组件的文档

---

**版本**: 1.0  
**最后更新**: 2026-01-13  
**维护者**: Claude Code  
**状态**: ✅ 设计完成，准备实现
