import { useState, useRef, useEffect } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
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

interface ExecutionRequest {
    plan: PlanStep[];
    global_timeout?: number;
    tenant_id?: number;
    auth_token?: string;
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
    const [goal, setGoal] = useState('');
    const [conversationHistory, setConversationHistory] = useState<ConversationMessage[]>([]);
    const [lastQuestion, setLastQuestion] = useState<string | null>(null);
    const [selectedCommandSets, setSelectedCommandSets] = useState<string[]>([]);
    const [currentPlan, setCurrentPlan] = useState<PlanStep[] | null>(null);
    const [executionId, setExecutionId] = useState<string | null>(null);
    const [executionDetail, setExecutionDetail] = useState<ExecutionDetail | null>(null);
    const [leftWidth, setLeftWidth] = useState(60); // Percentage width of left panel
    const containerRef = useRef<HTMLDivElement>(null);
    const isDraggingRef = useRef(false);

    const { data: commandSets } = useQuery({
        queryKey: ['command-sets'],
        queryFn: async () => {
            const res = await api.get<CommandSet[]>('/command-sets/');
            return res.data;
        }
    });

    const executeMutation = useMutation({
        mutationFn: async (request: ExecutionRequest) => {
            const tenantId = localStorage.getItem('tenantId');
            const token = localStorage.getItem('token');

            const payload: any = {
                plan: request.plan,
                global_timeout: request.global_timeout || 60,
                tenant_id: tenantId ? parseInt(tenantId) : undefined,
                auth_token: token || undefined
            };

            const res = await api.post<ExecutionResponse>('/executions/', payload);
            return res.data;
        },
        onSuccess: (data) => {
            setExecutionId(data.execution_id);
            // Start polling for execution details
            pollExecutionDetails(data.execution_id);
        }
    });

    const mutation = useMutation({
        mutationFn: async (payload: any) => {
            const res = await api.post<PlanResponse>('/tasks/', payload);
            return res.data;
        },
        onSuccess: (data) => {
            if (data.question) {
                setLastQuestion(data.question);
                const newHistory: ConversationMessage[] = [
                    ...conversationHistory,
                    { role: 'user', content: goal },
                    { role: 'assistant', content: data.question }
                ];
                setConversationHistory(newHistory);
            } else {
                setLastQuestion(null);
                setConversationHistory([]);
            }
        }
    });

    const handlePlanTask = () => {
        const payload: any = {
            goal,
            conversationHistory: conversationHistory.length > 0 ? conversationHistory : undefined
        };

        if (selectedCommandSets.length > 0) {
            payload.context = { commandSetNames: selectedCommandSets };
        }

        mutation.mutate(payload);
    };

    const handleExecutePlan = (plan: PlanStep[]) => {
        if (!plan || plan.length === 0) {
            alert("Cannot execute empty plan. Please generate a valid plan first.");
            return;
        }
        setCurrentPlan(plan);
        executeMutation.mutate({
            plan,
            global_timeout: 60
        });
    };

    const pollExecutionDetails = async (execId: string) => {
        const interval = setInterval(async () => {
            try {
                const res = await api.get<ExecutionDetail>(`/executions/${execId}`);
                setExecutionDetail(res.data);

                // Stop polling if execution is complete
                if (['completed', 'failed', 'partial_failed', 'timeout', 'rollback'].includes(res.data.status)) {
                    clearInterval(interval);
                }
            } catch (error) {
                console.error('Failed to fetch execution details:', error);
                clearInterval(interval);
            }
        }, 2000); // Poll every 2 seconds

        // Cleanup on unmount
        return () => clearInterval(interval);
    };

    const resetPlan = () => {
        setCurrentPlan(null);
        setExecutionId(null);
        setExecutionDetail(null);
    };

    const handleClearConversation = () => {
        setConversationHistory([]);
        setLastQuestion(null);
        setGoal('');
    };

    const toggleCommandSet = (name: string) => {
        setSelectedCommandSets(prev =>
            prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]
        );
    };

    const handleMouseDown = () => {
        isDraggingRef.current = true;
    };

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (!isDraggingRef.current || !containerRef.current) return;

            const container = containerRef.current;
            const containerRect = container.getBoundingClientRect();
            const newLeftWidth = ((e.clientX - containerRect.left) / containerRect.width) * 100;

            // Constrain between 30% and 70% to prevent either side getting too small
            if (newLeftWidth >= 30 && newLeftWidth <= 70) {
                setLeftWidth(newLeftWidth);
            }
        };

        const handleMouseUp = () => {
            isDraggingRef.current = false;
        };

        if (isDraggingRef.current) {
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
            return () => {
                document.removeEventListener('mousemove', handleMouseMove);
                document.removeEventListener('mouseup', handleMouseUp);
            };
        }
    }, []);

    return (
        <div className="h-screen flex flex-col bg-gray-900">
            {/* Header */}
            <div className="bg-gray-800 border-b border-gray-700 px-6 py-4">
                <h1 className="text-2xl font-bold">Task Planning Playground</h1>
                <p className="text-sm text-gray-400 mt-1">Chat with AI, generate and execute plans</p>
            </div>

            {/* Command Sets Toolbar */}
            <div className="bg-gray-900 border-b border-gray-700 px-6 py-3">
                <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold text-gray-400">📚 Command Sets:</span>
                    <div className="flex flex-wrap gap-2">
                        {commandSets?.map((cs) => (
                            <button
                                key={cs._id}
                                onClick={() => toggleCommandSet(cs.name)}
                                className={`px-3 py-1 rounded transition text-sm ${selectedCommandSets.includes(cs.name)
                                        ? 'bg-blue-600 text-white'
                                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                                    }`}
                            >
                                {cs.name}
                            </button>
                        ))}
                    </div>
                    {selectedCommandSets.length > 0 && (
                        <span className="text-xs text-blue-400 ml-auto">
                            Selected: {selectedCommandSets.length}
                        </span>
                    )}
                </div>
            </div>

            {/* Main Content - Two Column Layout with Draggable Divider */}
            <div className="flex-1 flex overflow-hidden gap-0 p-4 min-h-0" ref={containerRef}>

                {/* LEFT COLUMN - Chat Conversation */}
                <div
                    className="flex flex-col bg-gray-800 rounded-lg border border-gray-700 overflow-hidden min-h-0 min-w-0"
                    style={{ width: `${leftWidth}%` }}
                >
                    <div className="px-4 py-3 border-b border-gray-700 bg-gray-900">
                        <h2 className="text-sm font-semibold text-gray-300">💬 Conversation</h2>
                    </div>

                    {/* Conversation History */}
                    <div className="flex-1 overflow-y-auto p-4 space-y-3">
                        {conversationHistory.length === 0 ? (
                            <div className="text-gray-500 text-sm text-center py-8">
                                <p>Start a conversation...</p>
                                <p className="text-xs mt-2">Describe what you want to do</p>
                            </div>
                        ) : (
                            conversationHistory.map((msg, idx) => (
                                <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                    <div className={`max-w-xs px-3 py-2 rounded-lg text-sm ${msg.role === 'user'
                                            ? 'bg-blue-600 text-white rounded-br-none'
                                            : 'bg-gray-700 text-gray-100 rounded-bl-none'
                                        }`}>
                                        {msg.content}
                                    </div>
                                </div>
                            ))
                        )}

                        {/* AI Clarification Question */}
                        {lastQuestion && (
                            <div className="flex justify-start">
                                <div className="max-w-xs px-3 py-2 rounded-lg text-sm bg-yellow-900/30 text-yellow-200 border border-yellow-700 rounded-bl-none">
                                    <div className="font-semibold text-xs mb-1">❓ Question:</div>
                                    {lastQuestion}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Input Area */}
                    <div className="px-4 py-3 border-t border-gray-700 bg-gray-900 space-y-2">
                        <div className="flex gap-2">
                            <input
                                type="text"
                                className="flex-1 bg-gray-800 border border-gray-600 rounded p-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none text-gray-100"
                                placeholder={lastQuestion ? "Answer the question..." : "Type your goal here..."}
                                value={goal}
                                onChange={(e) => setGoal(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handlePlanTask()}
                            />
                            <button
                                onClick={handlePlanTask}
                                disabled={mutation.isPending || !goal.trim()}
                                className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 px-4 py-2 rounded font-medium transition text-sm"
                            >
                                {mutation.isPending ? '...' : '→'}
                            </button>
                        </div>
                        {conversationHistory.length > 0 && (
                            <button
                                onClick={handleClearConversation}
                                className="text-xs text-gray-400 hover:text-gray-300"
                            >
                                Clear conversation
                            </button>
                        )}
                    </div>
                </div>

                {/* DRAGGABLE DIVIDER */}
                <div
                    className="w-1 bg-gray-700 hover:bg-blue-500 cursor-col-resize transition-colors"
                    onMouseDown={handleMouseDown}
                    style={{ userSelect: 'none' }}
                />

                {/* RIGHT COLUMN - Plan & Results */}
                <div
                    className="flex flex-col bg-gray-800 rounded-lg border border-gray-700 overflow-hidden min-h-0 min-w-0"
                    style={{ width: `${100 - leftWidth}%` }}
                >
                    <div className="px-4 py-2 border-b border-gray-700 bg-gray-900 flex-shrink-0">
                        <h2 className="text-sm font-semibold text-gray-300">📋 Plan & Results</h2>
                    </div>

                    <div className="flex-1 overflow-hidden flex flex-col min-h-0">
                        <div className="flex-1 overflow-y-auto p-2 space-y-1">
                            {!mutation.data ? (
                                <div className="text-gray-500 text-xs text-center py-2">
                                    <p>No plan yet</p>
                                    <p className="text-xs mt-1">Plans will appear here</p>
                                </div>
                            ) : (
                                <>
                                {/* Status Badges */}
                                <div className="flex gap-2 flex-wrap">
                                    <div className={`px-2 py-1 rounded text-xs font-bold ${mutation.data.type === 'plan_ready' ? 'bg-green-900 text-green-200' : 'bg-yellow-900 text-yellow-200'}`}>
                                        {mutation.data.type === 'plan_ready' ? '✓ READY' : '? NEEDS INFO'}
                                    </div>
                                    <div className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300">
                                        {(mutation.data.confidence * 100).toFixed(0)}% confident
                                    </div>
                                </div>


                                {/* Plan Steps */}
                                {mutation.data.plan && mutation.data.type === 'plan_ready' && !currentPlan && (
                                    <div className="space-y-1">
                                        <button
                                            onClick={() => handleExecutePlan(mutation.data.plan!)}
                                            className="w-full bg-green-600 hover:bg-green-700 px-2 py-1 rounded font-medium transition text-xs"
                                        >
                                            ▶ Execute Plan
                                        </button>
                                        {mutation.data.plan.map((step) => (
                                            <div key={step.step} className="bg-gray-900 p-1 rounded border border-gray-700 text-xs space-y-0">
                                                <div className="flex gap-1">
                                                    <span className="bg-gray-700 w-4 h-4 rounded-full flex items-center justify-center font-bold text-xs flex-none">
                                                        {step.step}
                                                    </span>
                                                    <span className="text-gray-300 flex-1 text-xs">{step.description}</span>
                                                </div>
                                                <div className="font-mono text-green-400 ml-5 text-xs bg-black/30 p-0.5 rounded">
                                                    {step.command}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* Execution Status */}
                                {executionId && executionDetail && (
                                    <div className="space-y-1">
                                        <div className="flex justify-between items-center">
                                            <span className="text-xs font-semibold text-blue-400">Execution</span>
                                            <button
                                                onClick={resetPlan}
                                                className="text-xs text-gray-400 hover:text-gray-300"
                                            >
                                                New
                                            </button>
                                        </div>
                                        <div className="grid grid-cols-3 gap-1">
                                            <div className="bg-gray-900 p-1 rounded text-xs">
                                                <div className="text-gray-400 text-xs">ID</div>
                                                <div className="font-mono text-gray-300 text-xs">{executionId.substring(0, 6)}...</div>
                                            </div>
                                            <div className="bg-gray-900 p-1 rounded text-xs">
                                                <div className="text-gray-400 text-xs">Status</div>
                                                <div className={`font-bold text-xs ${
                                                    executionDetail.status === 'completed' ? 'text-green-400' :
                                                    executionDetail.status === 'failed' ? 'text-red-400' :
                                                    executionDetail.status === 'running' ? 'text-blue-400' :
                                                    'text-yellow-400'
                                                }`}>
                                                    {executionDetail.status}
                                                </div>
                                            </div>
                                            <div className="bg-gray-900 p-1 rounded text-xs">
                                                <div className="text-gray-400 text-xs">Progress</div>
                                                <div className="font-mono text-gray-300 text-xs">{executionDetail.completed_steps}/{executionDetail.total_steps}</div>
                                            </div>
                                        </div>

                                        {executionDetail.error_message && (
                                            <div className="bg-red-900/30 border border-red-700 p-1 rounded text-xs text-red-200">
                                                {executionDetail.error_message}
                                            </div>
                                        )}

                                        {executionDetail.steps && executionDetail.steps.length > 0 && (
                                            <div className="space-y-0">
                                                {executionDetail.steps.map((step, idx) => (
                                                    <div key={idx} className={`flex gap-1 items-center text-xs p-0.5 rounded ${
                                                        step.status === 'success' ? 'bg-green-900/30 text-green-300' :
                                                        step.status === 'failed' ? 'bg-red-900/30 text-red-300' :
                                                        'bg-gray-900 text-gray-300'
                                                    }`}>
                                                        <span className={`w-3 h-3 rounded-full flex items-center justify-center text-xs font-bold flex-none ${
                                                            step.status === 'success' ? 'bg-green-700' :
                                                            step.status === 'failed' ? 'bg-red-700' :
                                                            'bg-gray-600'
                                                        }`}>
                                                            {idx + 1}
                                                        </span>
                                                        <span className="flex-1 truncate text-xs">{step.description}</span>
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
                        {mutation.data && (
                            <div className="border-t border-gray-700 bg-gray-900 p-2 text-xs flex-1 overflow-hidden flex flex-col min-h-0">
                                <div className="text-gray-400 font-mono mb-1 text-xs flex-shrink-0">Response:</div>
                                <pre className="text-gray-500 whitespace-pre-wrap break-words text-xs flex-1 overflow-auto">
                                    {JSON.stringify(mutation.data, null, 2)}
                                </pre>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
