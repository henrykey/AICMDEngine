import { useState, useEffect } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
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
    risk_assessment?: {
        level: 'normal' | 'high' | 'critical';
        message: string;
    }
}

interface ExecutionResponse {
    execution_id: string;
    status: string;
    total_steps: number;
    started_at: string;
}

interface ExecutionDetail {
    execution_id: string;
    status: string;
    total_steps: number;
    completed_steps: number;
    failed_steps: number;
    started_at: string;
    completed_at?: string;
    error_message?: string;
    steps: any[];
}

interface ConversationMessage {
    role: 'user' | 'assistant';
    content: string;
}

interface CommandSet {
    _id?: string;
    name: string;
    description?: string;
}

export default function TaskPlayground() {
    const navigate = useNavigate();
    const [goal, setGoal] = useState('');
    const [conversationHistory, setConversationHistory] = useState<ConversationMessage[]>([]);
    const [lastQuestion, setLastQuestion] = useState<string | null>(null);
    const [selectedCommandSets, setSelectedCommandSets] = useState<string[]>([]);
    const [currentPlan, setCurrentPlan] = useState<PlanStep[] | null>(null);
    const [executionId, setExecutionId] = useState<string | null>(null);
    const [executionDetail, setExecutionDetail] = useState<ExecutionDetail | null>(null);

    // Check if user is logged in
    useEffect(() => {
        const token = localStorage.getItem('token');
        if (!token) {
            navigate('/login');
        }
    }, [navigate]);

    // Query command sets
    const { data: commandSets } = useQuery({
        queryKey: ['command-sets'],
        queryFn: async () => {
            const res = await api.get<CommandSet[]>('/command-sets/');
            return res.data;
        }
    });

    // Mutation for planning tasks
    const planMutation = useMutation({
        mutationFn: async (payload: any) => {
            const res = await api.post<PlanResponse>('/tasks/', payload);
            return res.data;
        },
        onSuccess: (data) => {
            if (data.question) {
                setLastQuestion(data.question);
                setConversationHistory(prev => [
                    ...prev,
                    { role: 'user' as const, content: goal },
                    { role: 'assistant' as const, content: data.question || '' }
                ]);
            } else {
                setLastQuestion(null);
                setCurrentPlan(data.plan || null);
                setConversationHistory(prev => [
                    ...prev,
                    { role: 'user' as const, content: goal }
                ]);
            }
        }
    });

    // Mutation for executing plans
    const executeMutation = useMutation({
        mutationFn: async (request: any) => {
            const tenantId = localStorage.getItem('tenantId');
            const token = localStorage.getItem('token');

            const res = await api.post<ExecutionResponse>('/executions/', {
                plan: request.plan,
                global_timeout: request.global_timeout || 60,
                tenant_id: tenantId ? parseInt(tenantId) : undefined,
                auth_token: token || undefined
            });
            return res.data;
        },
        onSuccess: (data) => {
            setExecutionId(data.execution_id);
            pollExecutionDetails(data.execution_id);
        }
    });

    // Poll execution details
    const pollExecutionDetails = async (execId: string) => {
        const interval = setInterval(async () => {
            try {
                const res = await api.get<ExecutionDetail>(`/executions/${execId}`);
                setExecutionDetail(res.data);

                if (['completed', 'failed', 'partial_failed', 'timeout', 'rollback'].includes(res.data.status)) {
                    clearInterval(interval);
                }
            } catch (error) {
                console.error('Failed to fetch execution details:', error);
                clearInterval(interval);
            }
        }, 2000);

        return () => clearInterval(interval);
    };

    // Handlers
    const handlePlanTask = () => {
        if (!goal.trim()) return;

        const payload: any = {
            goal,
            conversationHistory: conversationHistory.length > 0 ? conversationHistory : undefined
        };

        if (selectedCommandSets.length > 0) {
            payload.context = { commandSetNames: selectedCommandSets };
        }

        planMutation.mutate(payload);
    };

    const handleExecutePlan = (plan: PlanStep[]) => {
        if (!plan || plan.length === 0) {
            alert("Cannot execute empty plan. Please generate a valid plan first.");
            return;
        }
        setCurrentPlan(plan);
        executeMutation.mutate({ plan, global_timeout: 60 });
    };

    const handleResetPlan = () => {
        setCurrentPlan(null);
        setExecutionId(null);
        setExecutionDetail(null);
    };

    const handleClearConversation = () => {
        setConversationHistory([]);
        setLastQuestion(null);
        setGoal('');
        setCurrentPlan(null);
        setExecutionId(null);
        setExecutionDetail(null);
    };

    const toggleCommandSet = (name: string) => {
        setSelectedCommandSets(prev =>
            prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]
        );
    };

    return (
        <div className="flex flex-col h-screen bg-gray-50">
            {/* HEADER */}
            <div className="bg-white border-b border-gray-200 px-6 py-4">
                <h1 className="text-2xl font-bold text-gray-900">Task Planning Playground</h1>
                <p className="text-sm text-gray-600 mt-1">Chat with AI, generate and execute plans</p>
            </div>

            {/* TOOLBAR - Command Sets */}
            <div className="bg-white border-b border-gray-200 px-6 py-3">
                <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold text-gray-700">Command Sets:</span>
                    <div className="flex flex-wrap gap-2">
                        {commandSets?.map((cs) => (
                            <button
                                key={cs._id}
                                onClick={() => toggleCommandSet(cs.name)}
                                className={`px-3 py-1 rounded text-sm font-medium transition ${
                                    selectedCommandSets.includes(cs.name)
                                        ? 'bg-blue-500 text-white'
                                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                                }`}
                            >
                                {cs.name}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {/* MAIN CONTENT - Two Column Layout */}
            <div className="flex-1 flex gap-4 overflow-hidden p-4">
                {/* LEFT COLUMN - Chat Conversation */}
                <div className="flex-1 flex flex-col bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
                    <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                        <h2 className="text-sm font-semibold text-gray-900">Conversation</h2>
                    </div>

                    {/* Conversation Messages */}
                    <div className="flex-1 overflow-y-auto p-4 space-y-3">
                        {conversationHistory.length === 0 && !lastQuestion ? (
                            <div className="text-center text-gray-500 py-8">
                                <p className="text-sm">Start a conversation...</p>
                                <p className="text-xs mt-2">Describe what you want to do</p>
                            </div>
                        ) : (
                            <>
                                {conversationHistory.map((msg, idx) => (
                                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                        <div className={`max-w-xs px-3 py-2 rounded-lg text-sm ${
                                            msg.role === 'user'
                                                ? 'bg-blue-500 text-white rounded-br-none'
                                                : 'bg-gray-100 text-gray-900 rounded-bl-none'
                                        }`}>
                                            {msg.content}
                                        </div>
                                    </div>
                                ))}

                                {lastQuestion && (
                                    <div className="flex justify-start">
                                        <div className="max-w-xs px-3 py-2 rounded-lg text-sm bg-yellow-50 text-yellow-900 border border-yellow-200 rounded-bl-none">
                                            <div className="font-semibold text-xs mb-1">Question:</div>
                                            {lastQuestion}
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    {/* Input Area */}
                    <div className="px-4 py-3 border-t border-gray-200 bg-gray-50 space-y-2">
                        <div className="flex gap-2">
                            <input
                                type="text"
                                className="flex-1 bg-white border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none text-gray-900"
                                placeholder={lastQuestion ? "Answer the question..." : "Type your goal here..."}
                                value={goal}
                                onChange={(e) => setGoal(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handlePlanTask()}
                            />
                            <button
                                onClick={handlePlanTask}
                                disabled={planMutation.isPending || !goal.trim()}
                                className="bg-blue-500 hover:bg-blue-600 disabled:bg-gray-300 text-white px-4 py-2 rounded font-medium transition text-sm"
                            >
                                {planMutation.isPending ? 'Planning...' : 'Send'}
                            </button>
                        </div>
                        {conversationHistory.length > 0 && (
                            <button
                                onClick={handleClearConversation}
                                className="text-xs text-gray-500 hover:text-gray-700"
                            >
                                Clear conversation
                            </button>
                        )}
                    </div>
                </div>

                {/* RIGHT COLUMN - Plan & Results */}
                <div className="flex-1 flex flex-col bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
                    <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                        <h2 className="text-sm font-semibold text-gray-900">Plan & Results</h2>
                    </div>

                    <div className="flex-1 overflow-y-auto p-4 space-y-4">
                        {!planMutation.data ? (
                            <div className="text-center text-gray-500 py-8">
                                <p className="text-sm">No plan yet</p>
                                <p className="text-xs mt-2">Plans will appear here</p>
                            </div>
                        ) : (
                            <>
                                {/* Status Badges */}
                                <div className="flex gap-2 flex-wrap">
                                    <div className={`px-2 py-1 rounded text-xs font-bold ${
                                        planMutation.data.type === 'plan_ready'
                                            ? 'bg-green-100 text-green-800'
                                            : 'bg-yellow-100 text-yellow-800'
                                    }`}>
                                        {planMutation.data.type === 'plan_ready' ? '✓ READY' : '? NEEDS INFO'}
                                    </div>
                                    <div className="px-2 py-1 rounded text-xs bg-gray-100 text-gray-700">
                                        {(planMutation.data.confidence * 100).toFixed(0)}% confident
                                    </div>
                                </div>

                                {/* Plan Steps */}
                                {planMutation.data.plan && planMutation.data.type === 'plan_ready' && !currentPlan && (
                                    <div className="space-y-2">
                                        <button
                                            onClick={() => handleExecutePlan(planMutation.data.plan!)}
                                            className="w-full bg-green-500 hover:bg-green-600 text-white px-3 py-2 rounded font-medium transition text-sm"
                                        >
                                            ▶ Execute Plan
                                        </button>
                                        {planMutation.data.plan.map((step) => (
                                            <div key={step.step} className="bg-gray-50 p-3 rounded border border-gray-200 space-y-1">
                                                <div className="flex gap-2">
                                                    <span className="bg-blue-500 text-white w-6 h-6 rounded-full flex items-center justify-center font-bold text-xs flex-none">
                                                        {step.step}
                                                    </span>
                                                    <span className="text-gray-900 flex-1 text-sm">{step.description}</span>
                                                </div>
                                                <div className="font-mono text-green-700 ml-8 text-xs bg-green-50 p-2 rounded border border-green-200">
                                                    {step.command}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* Execution Status */}
                                {executionId && executionDetail && (
                                    <div className="space-y-2">
                                        <div className="flex justify-between items-center">
                                            <span className="text-sm font-semibold text-blue-600">Execution In Progress</span>
                                            <button
                                                onClick={handleResetPlan}
                                                className="text-xs text-gray-500 hover:text-gray-700"
                                            >
                                                New Plan
                                            </button>
                                        </div>

                                        <div className="grid grid-cols-3 gap-2">
                                            <div className="bg-gray-50 p-2 rounded border border-gray-200">
                                                <div className="text-gray-600 text-xs">ID</div>
                                                <div className="font-mono text-gray-900 text-xs">{executionId.substring(0, 8)}...</div>
                                            </div>
                                            <div className="bg-gray-50 p-2 rounded border border-gray-200">
                                                <div className="text-gray-600 text-xs">Status</div>
                                                <div className={`font-bold text-xs ${
                                                    executionDetail.status === 'completed' ? 'text-green-600' :
                                                    executionDetail.status === 'failed' ? 'text-red-600' :
                                                    executionDetail.status === 'running' ? 'text-blue-600' :
                                                    'text-yellow-600'
                                                }`}>
                                                    {executionDetail.status}
                                                </div>
                                            </div>
                                            <div className="bg-gray-50 p-2 rounded border border-gray-200">
                                                <div className="text-gray-600 text-xs">Progress</div>
                                                <div className="font-mono text-gray-900 text-xs">{executionDetail.completed_steps}/{executionDetail.total_steps}</div>
                                            </div>
                                        </div>

                                        {executionDetail.error_message && (
                                            <div className="bg-red-50 border border-red-200 p-2 rounded text-xs text-red-700">
                                                {executionDetail.error_message}
                                            </div>
                                        )}

                                        {executionDetail.steps && executionDetail.steps.length > 0 && (
                                            <div className="space-y-1">
                                                {executionDetail.steps.map((step, idx) => (
                                                    <div key={idx} className={`flex gap-2 items-center text-xs p-2 rounded ${
                                                        step.status === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
                                                        step.status === 'failed' ? 'bg-red-50 text-red-700 border border-red-200' :
                                                        'bg-gray-50 text-gray-700 border border-gray-200'
                                                    }`}>
                                                        <span className={`w-4 h-4 rounded-full flex items-center justify-center text-xs font-bold flex-none ${
                                                            step.status === 'success' ? 'bg-green-600 text-white' :
                                                            step.status === 'failed' ? 'bg-red-600 text-white' :
                                                            'bg-gray-400 text-white'
                                                        }`}>
                                                            {idx + 1}
                                                        </span>
                                                        <span className="flex-1 truncate">{step.description}</span>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    {/* Raw Response Preview */}
                    {planMutation.data && (
                        <div className="border-t border-gray-200 bg-gray-50 p-3 text-xs max-h-32 overflow-y-auto">
                            <div className="text-gray-600 font-mono mb-1">Response:</div>
                            <pre className="text-gray-700 whitespace-pre-wrap break-words text-xs">
                                {JSON.stringify(planMutation.data, null, 2)}
                            </pre>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
