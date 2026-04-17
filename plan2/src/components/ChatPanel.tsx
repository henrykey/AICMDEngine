import { useState, useRef, useEffect } from 'react';
import { api } from '../lib/api';
import { useTask, PlanResponse } from '../contexts/TaskContext';
import ReactMarkdown from 'react-markdown';
import MermaidBlock from './MermaidBlock';

type PlanningMode = 'auto' | 'cmdengine' | 'mcp';
type RetrievalBackend = 'auto' | 'docintel';

function getAssistantContent(data: PlanResponse): string | undefined {
    const directContent = data.directResult?.content || data.direct_result?.content;
    return directContent || data.assistantMessage || data.assistant_message || data.question || data.userPlan?.summary || data.user_plan?.summary;
}

function normalizeToolTextAsMarkdown(content: string): string {
    return content
        .replace(/^(Found .+)$/gm, '**$1**')
        .replace(/^(Members|Organizations):$/gm, '**$1:**')
        .replace(/^Member:\s*(.+)$/gm, '**Member: $1**')
        .replace(/^\s*•\s+/gm, '- ')
        .replace(/^\s*\.\.\. and/gm, '- ... and')
        .replace(/^(ID|Email|Status):\s*(.+)$/gm, '- **$1**: $2');
}

const ChatPanel: React.FC = () => {
    const {
        conversationHistory,
        setConversationHistory,
        lastQuestion,
        setLastQuestion,
        currentPlanResponse,
        setCurrentPlanResponse,
        selectedCommandSets,
        planningMode,
        setPlanningMode,
        retrievalBackend,
        setRetrievalBackend
    } = useTask();
    const [goal, setGoal] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');
    const [isComposing, setIsComposing] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Auto-scroll to latest message
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [conversationHistory]);

    const handlePlanTask = async () => {
        if (!goal.trim()) return;

        setIsLoading(true);
        setError('');

        try {
            // 立即显示用户输入到对话历史
            const newHistory = [
                ...conversationHistory,
                { role: 'user' as const, content: goal }
            ];
            setConversationHistory(newHistory);
            
            // 立即清除输入框
            setGoal('');

            const contextualHistory = [...newHistory];

            if (currentPlanResponse?.plan?.length) {
                const activeTaskSummary =
                    currentPlanResponse.assistantMessage ||
                    currentPlanResponse.assistant_message ||
                    currentPlanResponse.userPlan?.summary ||
                    currentPlanResponse.user_plan?.summary ||
                    'An active task has already been planned.';

                contextualHistory.push({
                    role: 'assistant' as const,
                    content:
                        `[Task Context] There is an active planned task that has not necessarily been executed yet. ` +
                        `Previous plan summary: ${activeTaskSummary}`
                });
            }

            const payload: any = {
                goal,
                conversationHistory: contextualHistory.length > 0 ? contextualHistory : undefined
            };

            payload.context = {
                ...(selectedCommandSets.length > 0 ? { commandSetNames: selectedCommandSets } : {}),
                planningMode,
                retrievalBackend,
            };

            // 在对话中添加加载状态的占位符
            const historyWithLoading = [
                ...newHistory,
                { role: 'assistant' as const, content: '__LOADING__' }
            ];
            setConversationHistory(historyWithLoading);

            const res = await api.post<PlanResponse>('/tasks/', payload);
            const data = res.data;

            // 移除加载占位符，添加实际响应
            const finalHistory = [
                ...newHistory
            ];

            const assistantContent = getAssistantContent(data);

            if (data.question) {
                setLastQuestion(data.question);
            } else {
                setLastQuestion(null);
            }

            if (assistantContent) {
                finalHistory.push({ role: 'assistant' as const, content: assistantContent });
            }

            setConversationHistory(finalHistory);
            setCurrentPlanResponse(data);
        } catch (err: any) {
            // 移除加载占位符，保留用户消息
            setConversationHistory(
                conversationHistory.filter((msg) => msg.content !== '__LOADING__')
            );
            setError(err.response?.data?.error_message || err.message || 'Failed to plan task');
        } finally {
            setIsLoading(false);
        }
    };

    const handleClearConversation = () => {
        setConversationHistory([]);
        setLastQuestion(null);
        setGoal('');
        setError('');
    };

    // Loading animation component
    const LoadingDots = () => (
        <div className="flex items-center gap-1">
            <span className="w-2 h-2 bg-slate-600 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 bg-slate-600 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 bg-slate-600 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
    );

    return (
        <div className="flex flex-1 flex-col overflow-hidden gap-4">
            {/* Conversation History */}
            <div className="chat-messages flex flex-1 flex-col gap-4 overflow-y-auto pr-1">
                {conversationHistory.map((msg, idx) => (
                    <div
                        key={idx}
                        className={`max-w-[85%] p-3 rounded-lg text-sm leading-relaxed shadow-sm overflow-auto ${msg.role === 'user'
                            ? 'ml-auto rounded-br-none bg-blue-500 text-white'
                            : 'rounded-bl-none bg-slate-100 text-slate-800'
                            }`}
                    >
                        {msg.content === '__LOADING__' ? (
                            <LoadingDots />
                        ) : (
                            <div className="markdown-content">
                                <ReactMarkdown
                                    components={{
                                        code({ inline, className, children, ...props }: any) {
                                            const match = /language-(\w+)/.exec(className || '');
                                            const code = String(children || '').replace(/\n$/, '');
                                            if (!inline && match?.[1] === 'mermaid') {
                                                return <MermaidBlock chart={code} />;
                                            }
                                            return (
                                                <code className={className} {...props}>
                                                    {children}
                                                </code>
                                            );
                                        }
                                    }}
                                >
                                    {msg.role === 'assistant' ? normalizeToolTextAsMarkdown(msg.content) : msg.content}
                                </ReactMarkdown>
                            </div>
                        )}
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>

            {/* Error Message */}
            {error && (
                <div className="p-3 bg-red-100 border border-red-300 rounded-lg text-sm text-red-700">
                    {error}
                </div>
            )}

            {/* Input Area */}
            <div className="flex items-center gap-3 flex-wrap">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mode</label>
                <select
                    value={planningMode}
                    onChange={(e) => setPlanningMode(e.target.value as PlanningMode)}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-500"
                    disabled={isLoading}
                >
                    <option value="auto">Auto</option>
                    <option value="cmdengine">CmdEngine</option>
                    <option value="mcp">MCP Direct</option>
                </select>
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Retrieval</label>
                <select
                    value={retrievalBackend}
                    onChange={(e) => setRetrievalBackend(e.target.value as RetrievalBackend)}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-500"
                    disabled={isLoading}
                >
                    <option value="auto">Auto</option>
                    <option value="docintel">DocIntel</option>
                </select>
            </div>

            <div className="flex gap-2">
                <input
                    type="text"
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                    onCompositionStart={() => setIsComposing(true)}
                    onCompositionEnd={() => setIsComposing(false)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !isComposing && !isLoading) {
                            e.preventDefault();
                            handlePlanTask();
                        }
                    }}
                    placeholder={lastQuestion ? "Answer the AI's question..." : "Describe your task..."}
                    className="flex-1 p-3 text-sm border border-slate-200 rounded-lg bg-white focus:bg-white focus:border-blue-500 focus:outline-none disabled:opacity-50"
                    disabled={isLoading}
                />
                <button
                    onClick={handlePlanTask}
                    disabled={isLoading || !goal.trim()}
                    className="px-4 py-3 bg-blue-500 hover:bg-blue-600 text-white text-sm rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition"
                >
                    {isLoading ? 'Planning...' : 'Plan'}
                </button>
                {conversationHistory.length > 0 && (
                    <button
                        onClick={handleClearConversation}
                        className="px-4 py-3 bg-slate-200 hover:bg-slate-300 text-slate-700 text-sm rounded-lg font-medium transition"
                    >
                        Clear
                    </button>
                )}
            </div>
        </div>
    );
};

export default ChatPanel;
