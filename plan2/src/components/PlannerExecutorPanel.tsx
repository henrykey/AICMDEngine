import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { useTask } from '../contexts/TaskContext';
import MCPSelector from './MCPSelector';
import ExecutionResultRenderer from './ExecutionResultRenderer';

interface ExecutionStep {
    step: number;
    command: string;
    description: string;
    params: Record<string, any>;
    status?: 'pending' | 'running' | 'completed' | 'failed' | 'success' | 'skipped';
    result?: any;
    result_content?: string;
    error?: string;
    error_message?: string;
    response_data?: any;
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
    steps: Array<{
        step_number?: number;
        step?: number;
        command: string;
        description: string;
        status: string;
        error_message?: string;
        error?: string;
        response_data?: any;
        result?: any;
        result_content?: string;
    }>;
}

const PlannerExecutorPanel: React.FC = () => {
    const { currentPlanResponse } = useTask();
    const [executionSteps, setExecutionSteps] = useState<ExecutionStep[]>([]);
    const [isExecuting, setIsExecuting] = useState(false);
    const [executionId, setExecutionId] = useState<string | null>(null);
    const [executionStatus, setExecutionStatus] = useState<string | null>(null);
    const [error, setError] = useState('');
    const [executionError, setExecutionError] = useState<string | null>(null);

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
        setExecutionError(null);

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
                    const execStep = data.steps.find(s => (s.step_number ?? s.step) === step.step);
                    if (execStep) {
                        return {
                            ...step,
                            status: (execStep.status as any) || step.status,
                            result: execStep.result || execStep.response_data,
                            result_content: execStep.result_content,
                            error: execStep.error_message || execStep.error,
                            error_message: execStep.error_message,
                            response_data: execStep.response_data
                        };
                    }
                    return step;
                });
                setExecutionSteps(updatedSteps);
                setExecutionStatus(data.status);
                if (data.error_message) {
                    setExecutionError(data.error_message);

                    // Check if error is due to token expiration
                    const errorMsg = data.error_message.toLowerCase();
                    if (errorMsg.includes('token') &&
                        (errorMsg.includes('expired') || errorMsg.includes('refresh') || errorMsg.includes('login'))) {
                        console.warn('Token expired detected, redirecting to login');
                        clearInterval(interval);
                        setIsExecuting(false);

                        // Clear stored credentials
                        localStorage.removeItem('token');
                        localStorage.removeItem('username');
                        localStorage.removeItem('tenantId');

                        // Redirect to login
                        window.location.href = '/login';
                        return;
                    }
                }

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
        if (currentPlanResponse?.directResult) {
            return (
                <div className="flex flex-1 flex-col gap-4 overflow-y-auto">
                    <MCPSelector />
                    <div className="rounded-lg border border-green-200 bg-green-50 p-4">
                        <div className="mb-2 text-sm font-semibold text-green-900">Direct MCP Result</div>
                        <div className="mb-3 text-xs text-slate-600">
                            Resolved mode: {currentPlanResponse.resolvedMode ?? 'mcp'}
                        </div>
                        <div className="mb-3 rounded bg-white px-3 py-2 font-mono text-sm text-green-700">
                            {currentPlanResponse.directResult.serverName}.{currentPlanResponse.directResult.toolName}
                        </div>
                        {Object.keys(currentPlanResponse.directResult.params ?? {}).length > 0 && (
                            <pre className="mb-3 overflow-auto rounded bg-white p-3 text-xs text-slate-600">
                                {JSON.stringify(currentPlanResponse.directResult.params, null, 2)}
                            </pre>
                        )}
                        <div className="rounded bg-white p-3 text-sm text-slate-800">
                            {currentPlanResponse.directResult.content}
                        </div>
                        {currentPlanResponse.directResult.data && Object.keys(currentPlanResponse.directResult.data).length > 0 && (
                            <pre className="mt-3 overflow-auto rounded bg-white p-3 text-xs text-slate-500">
                                {JSON.stringify(currentPlanResponse.directResult.data, null, 2)}
                            </pre>
                        )}
                    </div>

                    {currentPlanResponse.retrievalDiagnostics && (
                        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                            <div className="mb-2 text-sm font-semibold text-slate-700">Retrieval Diagnostics</div>
                            <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                                <div>Requested mode: {currentPlanResponse.retrievalDiagnostics.requested_mode ?? 'auto'}</div>
                                <div>Requested retrieval: {currentPlanResponse.retrievalDiagnostics.requested_retrieval_backend ?? 'auto'}</div>
                                <div>Resolved mode: {currentPlanResponse.retrievalDiagnostics.resolved_mode ?? currentPlanResponse.resolvedMode ?? 'mcp'}</div>
                                <div>Retrieval backend: {currentPlanResponse.retrievalDiagnostics.retrieval_backend ?? 'n/a'}</div>
                                <div>Remote candidates: {currentPlanResponse.retrievalDiagnostics.remote_candidate_count ?? 0}</div>
                                <div>Remote top score: {currentPlanResponse.retrievalDiagnostics.remote_top_score ?? 'n/a'}</div>
                                <div>Keyword hits: {currentPlanResponse.retrievalDiagnostics.keyword_hits ?? 0}</div>
                                <div>Vector hits: {currentPlanResponse.retrievalDiagnostics.vector_hits ?? 0}</div>
                                <div>Raw candidates: {currentPlanResponse.retrievalDiagnostics.raw_candidate_count ?? 0}</div>
                                <div>Prompt candidates: {currentPlanResponse.retrievalDiagnostics.prompt_candidate_count ?? 0}</div>
                                <div>Embedding provider: {currentPlanResponse.retrievalDiagnostics.embedding_provider ?? 'n/a'}</div>
                                <div>Embedding model: {currentPlanResponse.retrievalDiagnostics.embedding_model ?? 'n/a'}</div>
                                <div>Fallback reason: {currentPlanResponse.retrievalDiagnostics.remote_fallback_reason ?? 'none'}</div>
                            </div>
                        </div>
                    )}
                </div>
            );
        }

        return (
            <div className="flex flex-1 flex-col items-center justify-center text-center p-6 text-slate-600">
                <p className="text-sm">Plan a task in the Chat panel to see execution details here</p>
            </div>
        );
    }

    return (
        <div className="flex flex-1 flex-col gap-6 overflow-y-auto">
            {/* MCP Selector */}
            <MCPSelector />

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

            {/* Execution-level Error Message */}
            {executionError && (
                <div className="p-4 bg-red-50 border border-red-300 rounded-lg">
                    <div className="text-sm font-semibold text-red-800 mb-2">Execution Error:</div>
                    <div className="text-sm text-red-700 font-mono whitespace-pre-wrap overflow-auto max-h-32">
                        {executionError}
                    </div>
                </div>
            )}

            {/* Request-level Error Message */}
            {error && (
                <div className="p-3 bg-red-100 border border-red-300 rounded-lg text-sm text-red-700">
                    {error}
                </div>
            )}

            {/* Task Plan Title */}
            <div>
                <div className="text-sm font-semibold text-slate-700 mb-3">Task Execution Plan</div>
                <div className="mb-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                    <div>Resolved mode: {currentPlanResponse.resolvedMode ?? 'cmdengine'}</div>
                    <div>Confidence: {Math.round((currentPlanResponse.confidence ?? 0) * 100)}%</div>
                </div>

                {currentPlanResponse.retrievalDiagnostics && (
                    <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
                        <div className="mb-2 text-sm font-semibold text-slate-700">Retrieval Diagnostics</div>
                        <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                            <div>Requested mode: {currentPlanResponse.retrievalDiagnostics.requested_mode ?? 'auto'}</div>
                            <div>Requested retrieval: {currentPlanResponse.retrievalDiagnostics.requested_retrieval_backend ?? 'auto'}</div>
                            <div>Resolved mode: {currentPlanResponse.retrievalDiagnostics.resolved_mode ?? currentPlanResponse.resolvedMode ?? 'cmdengine'}</div>
                            <div>Retrieval backend: {currentPlanResponse.retrievalDiagnostics.retrieval_backend ?? 'n/a'}</div>
                            <div>Remote candidates: {currentPlanResponse.retrievalDiagnostics.remote_candidate_count ?? 0}</div>
                            <div>Remote top score: {currentPlanResponse.retrievalDiagnostics.remote_top_score ?? 'n/a'}</div>
                            <div>Keyword hits: {currentPlanResponse.retrievalDiagnostics.keyword_hits ?? 0}</div>
                            <div>Vector hits: {currentPlanResponse.retrievalDiagnostics.vector_hits ?? 0}</div>
                            <div>Raw candidates: {currentPlanResponse.retrievalDiagnostics.raw_candidate_count ?? 0}</div>
                            <div>Prompt candidates: {currentPlanResponse.retrievalDiagnostics.prompt_candidate_count ?? 0}</div>
                            <div>System state loaded: {currentPlanResponse.retrievalDiagnostics.system_state_loaded ? 'yes' : 'no'}</div>
                            <div>Embedding provider: {currentPlanResponse.retrievalDiagnostics.embedding_provider ?? 'n/a'}</div>
                            <div>Fallback reason: {currentPlanResponse.retrievalDiagnostics.remote_fallback_reason ?? 'none'}</div>
                        </div>
                        {currentPlanResponse.retrievalDiagnostics.top_commands && currentPlanResponse.retrievalDiagnostics.top_commands.length > 0 && (
                            <div className="mt-3">
                                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Top Commands</div>
                                <div className="space-y-1 font-mono text-xs text-slate-700">
                                    {currentPlanResponse.retrievalDiagnostics.top_commands.map((command) => (
                                        <div key={command}>{command}</div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}

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
                                {(step.result_content || step.result || step.response_data) && (
                                    <div className="mt-2 text-xs bg-green-50 p-3 rounded overflow-auto max-h-64">
                                        <ExecutionResultRenderer
                                            data={step.response_data || step.result}
                                            resultContent={step.result_content}
                                        />
                                    </div>
                                )}

                                {step.error_message && (
                                    <div className="mt-2 p-3 rounded bg-red-50 border border-red-200">
                                        <div className="text-xs font-semibold text-red-800 mb-1">Error Details:</div>
                                        <div className="text-xs text-red-700 font-mono whitespace-pre-wrap overflow-auto max-h-24">
                                            {step.error_message}
                                        </div>
                                    </div>
                                )}

                                {step.error && !step.error_message && (
                                    <div className="mt-2 text-xs text-red-700 bg-red-50 p-2 rounded font-mono">
                                        Error: {step.error}
                                    </div>
                                )}

                                {step.response_data && step.status === 'failed' && (
                                    <div className="mt-2 p-3 rounded bg-orange-50 border border-orange-200">
                                        <div className="text-xs font-semibold text-orange-800 mb-1">Response Data:</div>
                                        <div className="text-xs text-orange-700 font-mono overflow-auto max-h-32 whitespace-pre-wrap">
                                            {typeof step.response_data === 'string' ? step.response_data : JSON.stringify(step.response_data, null, 2)}
                                        </div>
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
