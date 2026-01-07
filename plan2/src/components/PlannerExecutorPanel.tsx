import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { useTask } from '../contexts/TaskContext';

interface ExecutionStep {
    step: number;
    command: string;
    description: string;
    params: Record<string, any>;
    status?: 'pending' | 'running' | 'completed' | 'failed';
    result?: any;
    error?: string;
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
    steps: ExecutionStep[];
}

const PlannerExecutorPanel: React.FC = () => {
    const { currentPlanResponse } = useTask();
    const [executionSteps, setExecutionSteps] = useState<ExecutionStep[]>([]);
    const [isExecuting, setIsExecuting] = useState(false);
    const [executionId, setExecutionId] = useState<string | null>(null);
    const [executionStatus, setExecutionStatus] = useState<string | null>(null);
    const [error, setError] = useState('');

    // Initialize steps from plan response
    useEffect(() => {
        if (currentPlanResponse?.plan) {
            const stepsWithStatus = currentPlanResponse.plan.map(step => ({
                ...step,
                status: 'pending' as const,
                result: undefined,
                error: undefined
            }));
            setExecutionSteps(stepsWithStatus);
            setExecutionId(null);
            setExecutionStatus(null);
        }
    }, [currentPlanResponse]);

    const handleExecuteAll = async () => {
        if (!currentPlanResponse?.plan || executionSteps.length === 0) return;

        setIsExecuting(true);
        setError('');

        try {
            const tenantId = localStorage.getItem('tenantId');
            const token = localStorage.getItem('token');

            const payload = {
                plan: currentPlanResponse.plan,
                global_timeout: 60,
                tenant_id: tenantId ? parseInt(tenantId) : undefined,
                auth_token: token || undefined
            };

            const res = await api.post<ExecutionResponse>('/executions/', payload);
            setExecutionId(res.data.execution_id);
            setExecutionStatus('started');

            // Start polling for execution details
            pollExecutionDetails(res.data.execution_id);
        } catch (err: any) {
            setError(err.response?.data?.error_message || err.message || 'Failed to execute tasks');
            setIsExecuting(false);
        }
    };

    const pollExecutionDetails = async (execId: string) => {
        const interval = setInterval(async () => {
            try {
                const res = await api.get<ExecutionDetail>(`/executions/${execId}`);
                const data = res.data;

                // Update steps with status and results
                const updatedSteps = executionSteps.map(step => {
                    const execStep = data.steps.find(s => s.step === step.step);
                    if (execStep) {
                        return {
                            ...step,
                            status: execStep.status || step.status,
                            result: execStep.result,
                            error: execStep.error
                        };
                    }
                    return step;
                });
                setExecutionSteps(updatedSteps);
                setExecutionStatus(data.status);

                // Stop polling if execution is complete
                if (['completed', 'failed', 'partial_failed', 'timeout', 'rollback'].includes(data.status)) {
                    clearInterval(interval);
                    setIsExecuting(false);
                }
            } catch (err) {
                console.error('Failed to fetch execution details:', err);
                clearInterval(interval);
                setIsExecuting(false);
            }
        }, 2000); // Poll every 2 seconds
    };

    const getStatusBgColor = (status?: string) => {
        switch (status) {
            case 'completed':
                return 'bg-green-50 border-l-4 border-green-500';
            case 'running':
                return 'bg-blue-50 border-l-4 border-blue-500';
            case 'failed':
                return 'bg-red-50 border-l-4 border-red-500';
            case 'pending':
            default:
                return 'bg-slate-50 border-l-4 border-slate-300';
        }
    };

    const getStatusBadge = (status?: string) => {
        switch (status) {
            case 'completed':
                return { bg: 'bg-green-100', text: 'text-green-800', label: 'Completed' };
            case 'running':
                return { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Running' };
            case 'failed':
                return { bg: 'bg-red-100', text: 'text-red-800', label: 'Failed' };
            case 'pending':
            default:
                return { bg: 'bg-slate-100', text: 'text-slate-800', label: 'Pending' };
        }
    };

    const getProgressWidth = (status?: string) => {
        switch (status) {
            case 'completed':
                return 'w-full bg-green-500';
            case 'running':
                return 'w-2/3 bg-blue-500';
            case 'failed':
                return 'w-1/2 bg-red-500';
            default:
                return 'w-0 bg-slate-300';
        }
    };

    if (!currentPlanResponse?.plan || executionSteps.length === 0) {
        return (
            <div className="flex flex-1 flex-col items-center justify-center text-center p-6 text-slate-600">
                <p className="text-sm">Plan a task in the Chat panel to see execution details here</p>
            </div>
        );
    }

    return (
        <div className="flex flex-1 flex-col gap-6 overflow-y-auto">
            {/* Execution Summary */}
            {executionId && (
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                    <div className="text-sm">
                        <span className="font-medium text-slate-700">Execution ID:</span>
                        <span className="text-blue-600 ml-2 font-mono">{executionId}</span>
                    </div>
                    <div className="text-sm mt-1">
                        <span className="font-medium text-slate-700">Status:</span>
                        <span className="text-slate-600 ml-2 capitalize">{executionStatus}</span>
                    </div>
                </div>
            )}

            {/* Error Message */}
            {error && (
                <div className="p-3 bg-red-100 border border-red-300 rounded-lg text-sm text-red-700">
                    {error}
                </div>
            )}

            {/* Task Plan Title */}
            <div>
                <div className="text-sm font-semibold text-slate-700 mb-3">Task Execution Plan</div>

                {/* Execution Steps */}
                <div className="space-y-3">
                    {executionSteps.map((step) => {
                        const badge = getStatusBadge(step.status);
                        return (
                            <div
                                key={step.step}
                                className={`p-4 rounded-lg border transition ${getStatusBgColor(step.status)}`}
                            >
                                <div className="flex justify-between items-start mb-2">
                                    <div className="flex-1">
                                        <div className="font-medium text-slate-800">
                                            Step {step.step}: {step.description}
                                        </div>
                                        <div className="text-xs text-slate-600 mt-1 font-mono bg-slate-100 p-2 rounded mt-2">
                                            {step.command}
                                        </div>
                                    </div>
                                    <span className={`text-xs px-2 py-1 rounded whitespace-nowrap ml-2 ${badge.bg} ${badge.text}`}>
                                        {badge.label}
                                    </span>
                                </div>

                                {/* Progress Bar */}
                                <div className="mt-2 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                                    <div className={`h-full rounded-full ${getProgressWidth(step.status)}`} />
                                </div>

                                {/* Step Result or Error */}
                                {step.result && (
                                    <div className="mt-2 text-xs text-green-700 bg-green-50 p-2 rounded font-mono">
                                        Result: {typeof step.result === 'string' ? step.result : JSON.stringify(step.result, null, 2)}
                                    </div>
                                )}

                                {step.error && (
                                    <div className="mt-2 text-xs text-red-700 bg-red-50 p-2 rounded font-mono">
                                        Error: {step.error}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Execute Button */}
            <div className="flex gap-2 mt-auto">
                <button
                    onClick={handleExecuteAll}
                    disabled={isExecuting || executionSteps.length === 0}
                    className="flex-1 py-3 bg-gradient-to-r from-green-500 to-emerald-400 hover:from-green-600 hover:to-emerald-500 text-white text-sm rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition"
                >
                    {isExecuting ? 'Executing...' : 'Execute All'}
                </button>
            </div>
        </div>
    );
};

export default PlannerExecutorPanel;
