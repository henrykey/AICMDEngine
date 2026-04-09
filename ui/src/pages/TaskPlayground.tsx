import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../lib/api';

interface PlanStep {
    step: number;
    description: string;
    command: string;
    params: Record<string, any>;
}

interface PlanResponse {
    type: string;
    confidence: number;
    plan?: PlanStep[];
    question?: string;
    resolvedMode?: string;
    retrievalDiagnostics?: {
        keyword_hits: number;
        vector_hits: number;
        raw_candidate_count: number;
        prompt_candidate_count: number;
        embedding_provider?: string;
        embedding_model?: string;
        requested_mode?: string;
        resolved_mode?: string;
        system_state_loaded?: boolean;
        top_commands?: string[];
    };
    directResult?: {
        serverName: string;
        toolName: string;
        params: Record<string, any>;
        content: string;
        data: Record<string, any>;
    };
    risk_assessment?: {
        level: 'normal' | 'high' | 'critical';
        message: string;
    }
}

interface ConversationMessage {
    role: 'user' | 'assistant';
    content: string;
}

type PlanningMode = 'auto' | 'cmdengine' | 'mcp';

export default function TaskPlayground() {
    const [goal, setGoal] = useState('');
    const [conversationHistory, setConversationHistory] = useState<ConversationMessage[]>([]);
    const [lastQuestion, setLastQuestion] = useState<string | null>(null);
    const [isComposing, setIsComposing] = useState(false);
    const [planningMode, setPlanningMode] = useState<PlanningMode>('auto');

    const mutation = useMutation({
        mutationFn: async (payload: { goal: string; conversationHistory?: ConversationMessage[]; context?: { planningMode: PlanningMode } }) => {
            const res = await api.post<PlanResponse>('/tasks/', payload);
            return res.data;
        },
        onSuccess: (data) => {
            if (data.question) {
                // AI asked a question, save it
                setLastQuestion(data.question);
                const newHistory: ConversationMessage[] = [
                    ...conversationHistory,
                    { role: 'assistant', content: data.question }
                ];
                setConversationHistory(newHistory);
            } else {
                // Plan is ready, clear conversation
                setLastQuestion(null);
                setConversationHistory([]);
            }
            setGoal('');
        }
    });

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
            conversationHistory: conversationHistory.length > 0 ? conversationHistory : undefined,
            context: {
                planningMode
            }
        });
    };

    const handleClearConversation = () => {
        setConversationHistory([]);
        setLastQuestion(null);
        setGoal('');
    };

    return (
        <div className="max-w-4xl mx-auto space-y-6">
            <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
                <h2 className="text-lg font-semibold mb-4">Task Planning Playground</h2>
                <div className="mb-4 flex items-center gap-3">
                    <label className="text-sm text-gray-400">Mode</label>
                    <select
                        className="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm"
                        value={planningMode}
                        onChange={(e) => setPlanningMode(e.target.value as PlanningMode)}
                    >
                        <option value="auto">Auto</option>
                        <option value="cmdengine">CmdEngine</option>
                        <option value="mcp">MCP Direct</option>
                    </select>
                </div>

                {/* Show conversation history if exists */}
                {conversationHistory.length > 0 && (
                    <div className="mb-4 p-4 bg-gray-900 rounded border border-gray-700 space-y-2">
                        <div className="flex justify-between items-center mb-2">
                            <span className="text-xs text-gray-400">Conversation History:</span>
                            <button
                                onClick={handleClearConversation}
                                className="text-xs text-red-400 hover:text-red-300"
                            >
                                Clear
                            </button>
                        </div>
                        {conversationHistory.map((msg, idx) => (
                            <div key={idx} className={`text-sm ${msg.role === 'user' ? 'text-blue-300' : 'text-yellow-300'}`}>
                                <strong>{msg.role === 'user' ? 'You' : 'AI'}:</strong> {msg.content}
                            </div>
                        ))}
                    </div>
                )}

                <div className="flex gap-4">
                    <input
                        type="text"
                        className="flex-1 bg-gray-900 border border-gray-700 rounded p-3 focus:ring-2 focus:ring-blue-500 outline-none"
                        placeholder={lastQuestion ? "Answer the AI's question..." : "e.g., Create a user named Alice in R&D"}
                        value={goal}
                        onChange={(e) => setGoal(e.target.value)}
                        onCompositionStart={() => setIsComposing(true)}
                        onCompositionEnd={() => setIsComposing(false)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !isComposing && !mutation.isPending) {
                                e.preventDefault();
                                handlePlanTask();
                            }
                        }}
                    />
                    <button
                        onClick={handlePlanTask}
                        disabled={mutation.isPending}
                        className="bg-blue-600 hover:bg-blue-700 px-6 py-2 rounded font-medium disabled:opacity-50 transition"
                    >
                        {mutation.isPending ? 'Planning...' : lastQuestion ? 'Answer' : 'Plan Task'}
                    </button>
                </div>
            </div>

            {mutation.error && (
                <div className="bg-red-900/50 border border-red-700 text-red-200 p-4 rounded">
                    Error: {mutation.error.message}
                </div>
            )}

            {mutation.data && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4">
                    {/* Status Header */}
                    <div className="flex items-center gap-4">
                        <div className={`px-3 py-1 rounded-full text-sm font-bold ${mutation.data.type === 'plan_ready' ? 'bg-green-900 text-green-200' : 'bg-yellow-900 text-yellow-200'
                            }`}>
                            {mutation.data.type === 'plan_ready'
                                ? 'PLAN READY'
                                : mutation.data.type === 'direct_result'
                                    ? 'DIRECT MCP RESULT'
                                    : 'CLARIFICATION NEEDED'}
                        </div>
                        <div className="text-gray-400 text-sm">
                            Confidence: {(mutation.data.confidence * 100).toFixed(0)}%
                        </div>
                        <div className="text-gray-500 text-sm">
                            Resolved mode: {mutation.data.resolvedMode ?? planningMode}
                        </div>
                        {mutation.data.risk_assessment && (
                            <div className={`px-3 py-1 rounded-full text-sm font-bold border ${mutation.data.risk_assessment.level === 'critical' ? 'bg-red-900 text-red-100 border-red-500' :
                                mutation.data.risk_assessment.level === 'high' ? 'bg-orange-900 text-orange-100 border-orange-500' :
                                    'bg-blue-900 text-blue-100 border-blue-500'
                                }`}>
                                risk: {mutation.data.risk_assessment.level}
                            </div>
                        )}
                    </div>

                    {mutation.data.risk_assessment?.message && (
                        <div className="bg-orange-900/30 border-l-4 border-orange-500 p-4 text-orange-200">
                            ⚠️ {mutation.data.risk_assessment.message}
                        </div>
                    )}

                    {/* Question / Plan */}
                    {mutation.data.question && (
                        <div className="bg-gray-800 p-6 rounded-lg border border-yellow-700">
                            <h3 className="text-yellow-500 font-medium mb-2">AI Question:</h3>
                            <p className="text-xl mb-4">{mutation.data.question}</p>
                            <p className="text-sm text-gray-400">💡 Type your answer above and click "Answer"</p>
                        </div>
                    )}

                    {mutation.data.plan && (
                        <div className="space-y-4">
                            {mutation.data.plan.map((step) => (
                                <div key={step.step} className="bg-gray-800 p-4 rounded-lg border border-gray-700 flex gap-4">
                                    <div className="flex-none bg-gray-700 w-8 h-8 rounded-full flex items-center justify-center font-bold text-gray-300">
                                        {step.step}
                                    </div>
                                    <div className="flex-1 space-y-2">
                                        <p className="font-medium text-lg">{step.description}</p>
                                        <div className="bg-black/50 p-3 rounded font-mono text-sm text-green-400 overflow-x-auto">
                                            POST {step.command}
                                        </div>
                                        {Object.keys(step.params).length > 0 && (
                                            <pre className="text-xs text-gray-500 overflow-x-auto">
                                                {JSON.stringify(step.params, null, 2)}
                                            </pre>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {mutation.data.directResult && (
                        <div className="bg-gray-800 p-6 rounded-lg border border-green-700 space-y-4">
                            <div className="flex flex-wrap items-center gap-3">
                                <div className="rounded bg-green-900 px-3 py-1 text-sm font-semibold text-green-200">
                                    {mutation.data.directResult.serverName}.{mutation.data.directResult.toolName}
                                </div>
                                <div className="text-sm text-gray-400">
                                    Executed directly without plan generation
                                </div>
                            </div>
                            {Object.keys(mutation.data.directResult.params ?? {}).length > 0 && (
                                <pre className="overflow-x-auto rounded bg-black/50 p-3 text-xs text-gray-300">
                                    {JSON.stringify(mutation.data.directResult.params, null, 2)}
                                </pre>
                            )}
                            <div className="rounded bg-black/50 p-4 text-sm text-green-300">
                                {mutation.data.directResult.content}
                            </div>
                            {mutation.data.directResult.data && Object.keys(mutation.data.directResult.data).length > 0 && (
                                <pre className="overflow-x-auto rounded bg-black/50 p-3 text-xs text-gray-500">
                                    {JSON.stringify(mutation.data.directResult.data, null, 2)}
                                </pre>
                            )}
                        </div>
                    )}

                    {mutation.data.retrievalDiagnostics && (
                        <div className="bg-gray-800 p-4 rounded-lg border border-gray-700 space-y-3">
                            <h3 className="text-sm font-semibold text-gray-200">Retrieval Diagnostics</h3>
                            <div className="grid gap-2 text-sm text-gray-300 md:grid-cols-2">
                                <div>Requested mode: {mutation.data.retrievalDiagnostics.requested_mode ?? planningMode}</div>
                                <div>Resolved mode: {mutation.data.retrievalDiagnostics.resolved_mode ?? mutation.data.resolvedMode ?? planningMode}</div>
                                <div>Keyword hits: {mutation.data.retrievalDiagnostics.keyword_hits ?? 0}</div>
                                <div>Vector hits: {mutation.data.retrievalDiagnostics.vector_hits ?? 0}</div>
                                <div>Raw candidates: {mutation.data.retrievalDiagnostics.raw_candidate_count ?? 0}</div>
                                <div>Prompt candidates: {mutation.data.retrievalDiagnostics.prompt_candidate_count ?? 0}</div>
                                <div>Embedding provider: {mutation.data.retrievalDiagnostics.embedding_provider ?? 'n/a'}</div>
                                <div>Embedding model: {mutation.data.retrievalDiagnostics.embedding_model ?? 'n/a'}</div>
                                <div>System state loaded: {mutation.data.retrievalDiagnostics.system_state_loaded ? 'yes' : 'no'}</div>
                            </div>
                            {mutation.data.retrievalDiagnostics.top_commands && mutation.data.retrievalDiagnostics.top_commands.length > 0 && (
                                <div>
                                    <div className="mb-2 text-xs uppercase tracking-wide text-gray-500">Top Commands</div>
                                    <div className="space-y-1 font-mono text-xs text-green-300">
                                        {mutation.data.retrievalDiagnostics.top_commands.map((command) => (
                                            <div key={command}>{command}</div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    <div className="bg-gray-900 p-4 rounded text-xs text-gray-600 font-mono overflow-auto max-h-40">
                        Raw Response: {JSON.stringify(mutation.data, null, 2)}
                    </div>
                </div>
            )}
        </div>
    );
}
