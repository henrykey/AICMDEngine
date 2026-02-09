# Planning 功能修复说明

## 问题1：回车键在中文输入时误触发

**原因**：直接监听 `Enter` 键事件，没有考虑输入法组合键状态

**修复方案**：
- 添加 `isComposing` 状态追踪输入法组合状态
- 使用 `onCompositionStart` 和 `onCompositionEnd` 事件更新状态
- 修改 `onKeyDown` 处理器：只在 `!isComposing` 且 `!mutation.isPending` 时触发
- 添加 `e.preventDefault()` 防止默认行为

```tsx
const [isComposing, setIsComposing] = useState(false);

<input
  onCompositionStart={() => setIsComposing(true)}
  onCompositionEnd={() => setIsComposing(false)}
  onKeyDown={(e) => {
    if (e.key === 'Enter' && !isComposing && !mutation.isPending) {
      e.preventDefault();
      handlePlanTask();
    }
  }}
/>
```

## 问题2：发送后要立即显示内容

**原因**：用户输入只有在收到 LLM 响应后才被添加到对话历史

**修复方案**：
- 在 `handlePlanTask` 中立即将用户输入添加到 `conversationHistory`
- 然后再发送 API 请求
- `onSuccess` 回调中只添加 AI 的回复，不再添加用户输入
- 发送后清空输入框

```tsx
const handlePlanTask = () => {
    if (!goal.trim()) return;
    
    // 立即显示用户输入到对话历史
    const newHistory: ConversationMessage[] = [
        ...conversationHistory,
        { role: 'user', content: goal }
    ];
    setConversationHistory(newHistory);
    
    // 发送请求
    mutation.mutate({
        goal,
        conversationHistory: conversationHistory.length > 0 ? conversationHistory : undefined
    });
};
```

## 修改文件

- `ui/src/pages/TaskPlayground.tsx`

## 测试方法

1. **测试回车键**：
   - 使用中文输入法输入内容
   - 按下回车键确定拉丁字母输入 → 应该不会触发
   - 使用英文状态按回车键 → 正常提交

2. **测试立即显示**：
   - 输入内容后按回车或点击按钮
   - 输入内容应该立即出现在"Conversation History"中
   - 不需要等待 LLM 返回结果
