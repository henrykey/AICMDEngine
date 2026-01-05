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
        <div className="flex h-screen w-full bg-slate-100">
            {/* SIDEBAR - Navigation */}
            <aside className="w-64 bg-slate-900 flex-shrink-0 flex flex-col p-4 text-white">
                <div className="text-xl font-bold mb-10">NL-TPS Admin</div>
                <nav className="flex-1 space-y-2">
                    <div className="bg-blue-600 p-2 rounded">Task Playground</div>
                    <div className="p-2 hover:bg-slate-800 rounded cursor-pointer">Command Sets</div>
                </nav>
                <div className="border-t border-slate-700 pt-4">
                    <div className="text-xs text-slate-400 uppercase mb-2">User</div>
                    <div className="text-sm text-white">admin</div>
                    <div className="text-xs text-slate-400 uppercase mt-4 mb-2">Tenant</div>
                    <div className="text-sm text-white">1</div>
                </div>
            </aside>

            {/* MAIN CONTENT */}
            <main className="flex-1 flex overflow-hidden">
                {/* LEFT COLUMN - Conversation */}
                <section className="flex-1 bg-white border-r border-slate-200 flex flex-col min-w-[400px]">
                    {/* Command Sets Bar */}
                    <div className="px-4 py-3 border-b border-slate-200 bg-white">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs font-semibold text-slate-600">Command Sets:</span>
                            {commandSets?.map((cs) => (
                                <button
                                    key={cs._id}
                                    onClick={() => toggleCommandSet(cs.name)}
                                    className={`px-2 py-1 rounded text-xs font-medium transition ${
                                        selectedCommandSets.includes(cs.name)
                                            ? 'bg-blue-500 text-white'
                                            : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                                    }`}
                                >
                                    {cs.name}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Conversation Header */}
                    <header className="px-4 py-3 border-b border-slate-200 font-semibold text-slate-800">
                        Conversation
                    </header>

                    {/* Messages Area */}
                    <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
                        {conversationHistory.length === 0 && !lastQuestion ? (
                            <div className="text-center text-slate-400 py-8">
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
                                                : 'bg-slate-100 text-slate-900 rounded-bl-none'
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
                    <div className="px-4 py-3 border-t border-slate-200 bg-white space-y-2">
                        <div className="flex gap-2">
                            <input
                                type="text"
                                className="flex-1 px-4 py-2 bg-slate-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 text-slate-900"
                                placeholder={lastQuestion ? "Answer the question..." : "Ask AI to plan..."}
                                value={goal}
                                onChange={(e) => setGoal(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handlePlanTask()}
                            />
                            <button
                                onClick={handlePlanTask}
                                disabled={planMutation.isPending || !goal.trim()}
                                className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white px-4 py-2 rounded-lg font-medium transition text-sm"
                            >
                                {planMutation.isPending ? '...' : 'Send'}
                            </button>
                        </div>
                        {conversationHistory.length > 0 && (
                            <button
                                onClick={handleClearConversation}
                                className="text-xs text-slate-500 hover:text-slate-700"
                            >
                                Clear conversation
                            </button>
                        )}
                    </div>
                </section>

                {/* RIGHT COLUMN - Plan & Results */}
                <section className="flex-[1.5] bg-slate-50 flex flex-col">
                    {/* Header */}
                    <header className="px-4 py-3 border-b border-slate-200 flex justify-between items-center bg-white">
                        <span className="font-semibold text-slate-800">Plan & Results</span>
                        {executionId && (
                            <button
                                onClick={handleResetPlan}
                                className="text-xs text-slate-600 hover:text-slate-900"
                            >
                                New Plan
                            </button>
                        )}
                    </header>

                    {/* Content */}
                    <div className="flex-1 overflow-y-auto px-8 py-6 space-y-4">
                        {!planMutation.data ? (
                            <div className="text-center text-slate-400 py-12">
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
                                    <div className="px-2 py-1 rounded text-xs bg-slate-200 text-slate-700">
                                        {(planMutation.data.confidence * 100).toFixed(0)}% confident
                                    </div>
                                </div>

                                {/* Plan Steps */}
                                {planMutation.data.plan && planMutation.data.type === 'plan_ready' && !currentPlan && (
                                    <div className="space-y-3">
                                        <button
                                            onClick={() => handleExecutePlan(planMutation.data.plan!)}
                                            className="w-full bg-green-600 hover:bg-green-700 text-white px-3 py-2 rounded-lg font-medium transition text-sm"
                                        >
                                            ▶ Execute Plan
                                        </button>
                                        {planMutation.data.plan.map((step) => (
                                            <div key={step.step} className="bg-white p-4 rounded-lg border border-slate-200 space-y-2">
                                                <div className="flex gap-3">
                                                    <span className="bg-blue-600 text-white w-6 h-6 rounded-full flex items-center justify-center font-bold text-xs flex-none">
                                                        {step.step}
                                                    </span>
                                                    <span className="text-slate-900 flex-1 text-sm">{step.description}</span>
                                                </div>
                                                <div className="font-mono text-green-700 ml-9 text-xs bg-green-50 p-2 rounded border border-green-200">
                                                    {step.command}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* Execution Status */}
                                {executionId && executionDetail && (
                                    <div className="space-y-3">
                                        <div className="bg-white p-4 rounded-lg border border-slate-200">
                                            <div className="text-sm font-semibold text-blue-600 mb-3">Execution In Progress</div>

                                            <div className="grid grid-cols-3 gap-3 mb-4">
                                                <div className="bg-slate-50 p-3 rounded border border-slate-200">
                                                    <div className="text-slate-600 text-xs mb-1">ID</div>
                                                    <div className="font-mono text-slate-900 text-xs">{executionId.substring(0, 8)}...</div>
                                                </div>
                                                <div className="bg-slate-50 p-3 rounded border border-slate-200">
                                                    <div className="text-slate-600 text-xs mb-1">Status</div>
                                                    <div className={`font-bold text-xs ${
                                                        executionDetail.status === 'completed' ? 'text-green-600' :
                                                        executionDetail.status === 'failed' ? 'text-red-600' :
                                                        executionDetail.status === 'running' ? 'text-blue-600' :
                                                        'text-yellow-600'
                                                    }`}>
                                                        {executionDetail.status}
                                                    </div>
                                                </div>
                                                <div className="bg-slate-50 p-3 rounded border border-slate-200">
                                                    <div className="text-slate-600 text-xs mb-1">Progress</div>
                                                    <div className="font-mono text-slate-900 text-xs">{executionDetail.completed_steps}/{executionDetail.total_steps}</div>
                                                </div>
                                            </div>

                                            {executionDetail.error_message && (
                                                <div className="bg-red-50 border border-red-200 p-3 rounded text-xs text-red-700 mb-4">
                                                    {executionDetail.error_message}
                                                </div>
                                            )}

                                            {executionDetail.steps && executionDetail.steps.length > 0 && (
                                                <div className="space-y-2">
                                                    {executionDetail.steps.map((step, idx) => (
                                                        <div key={idx} className={`flex gap-2 items-center text-xs p-2 rounded ${
                                                            step.status === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
                                                            step.status === 'failed' ? 'bg-red-50 text-red-700 border border-red-200' :
                                                            'bg-slate-100 text-slate-700 border border-slate-200'
                                                        }`}>
                                                            <span className={`w-4 h-4 rounded-full flex items-center justify-center text-xs font-bold flex-none ${
                                                                step.status === 'success' ? 'bg-green-600 text-white' :
                                                                step.status === 'failed' ? 'bg-red-600 text-white' :
                                                                'bg-slate-400 text-white'
                                                            }`}>
                                                                {idx + 1}
                                                            </span>
                                                            <span className="flex-1 truncate">{step.description}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    {/* Raw Response Preview */}
                    {planMutation.data && (
                        <div className="border-t border-slate-200 bg-white px-8 py-4 text-xs max-h-32 overflow-y-auto">
                            <div className="text-slate-600 font-mono mb-2 text-xs">Response:</div>
                            <pre className="text-slate-700 whitespace-pre-wrap break-words text-xs">
                                {JSON.stringify(planMutation.data, null, 2)}
                            </pre>
                        </div>
                    )}
                </section>
            </main>
        </div>
    );
}
