import { useState, useEffect, useMemo, useRef } from 'react';
import { api } from '../lib/api';
import { useTask } from '../contexts/TaskContext';
import MCPSelector from './MCPSelector';
import ExecutionResultRenderer from './ExecutionResultRenderer';

function normalizeUserPlan(response: any) {
    const raw = response?.userPlan || response?.user_plan;
    if (!raw) return null;
    return {
        headline: raw.headline,
        summary: raw.summary,
        steps: raw.steps || [],
        nextAction: raw.nextAction || raw.next_action,
        debugHint: raw.debugHint || raw.debug_hint,
    };
}

function normalizeDirectResult(response: any) {
    const raw = response?.directResult || response?.direct_result;
    if (!raw) return null;
    return {
        serverName: raw.serverName || raw.server_name,
        toolName: raw.toolName || raw.tool_name,
        params: raw.params || {},
        content: raw.content,
        data: raw.data || {},
    };
}

function normalizeLlmSummary(response: any) {
    return response?.llmSummary || response?.llm_summary || null;
}

function normalizeExecutionSummary(summary: any) {
    if (!summary) return null;
    return {
        headline: summary.headline,
        summary: summary.summary,
        statusLabel: summary.statusLabel || summary.status_label,
        nextAction: summary.nextAction || summary.next_action,
        detailLines: summary.detailLines || summary.detail_lines || [],
        debugHint: summary.debugHint || summary.debug_hint,
    };
}

function extractResultPayload(data: any) {
    if (!data || typeof data !== 'object') return data;
    return data.data || data.member || data.organization || data.org || data.role || data.resource || data;
}

function getDisplayName(item: any) {
    const nestedRole = item?.role && typeof item.role === 'object' ? item.role : null;
    const nestedSubject = item?.member && typeof item.member === 'object' ? item.member : null;
    const nestedOrg = item?.org && typeof item.org === 'object' ? item.org : null;
    const nested = nestedRole || nestedSubject || nestedOrg;
    return item?.fullName || item?.full_name || item?.name || item?.username || item?.code || item?.title ||
        nested?.fullName || nested?.full_name || nested?.name || nested?.username || nested?.code || nested?.title ||
        item?.id || nested?.id || 'Unknown';
}

function formatFieldValue(value: any) {
    if (value === undefined || value === null || value === '') return 'N/A';
    if (typeof value === 'object') return `\`${JSON.stringify(value)}\``;
    return String(value);
}

function formatObjectDetails(payload: Record<string, any>, isChinese: boolean) {
    const labels: Record<string, string> = isChinese
        ? {
            id: 'ID',
            username: '用户名',
            fullName: '姓名',
            full_name: '姓名',
            name: '名称',
            email: '邮箱',
            status: '状态',
            phone: '电话',
            alias: '别名',
            code: '编码',
            type: '类型',
        }
        : {
            id: 'ID',
            username: 'Username',
            fullName: 'Full name',
            full_name: 'Full name',
            name: 'Name',
            email: 'Email',
            status: 'Status',
            phone: 'Phone',
            alias: 'Alias',
            code: 'Code',
            type: 'Type',
        };
    const preferredKeys = ['id', 'username', 'fullName', 'full_name', 'name', 'email', 'status', 'phone', 'alias', 'code', 'type'];
    const lines = preferredKeys
        .filter((key) => payload[key] !== undefined && payload[key] !== null)
        .map((key) => `- **${labels[key] || key}**: ${formatFieldValue(payload[key])}`);
    return lines.join('\n');
}

function formatListItem(item: any) {
    if (!item || typeof item !== 'object') return `- ${formatFieldValue(item)}`;
    const role = item.role && typeof item.role === 'object' ? item.role : null;
    const details = [
        role?.id !== undefined ? `role ID: ${role.id}` : null,
        role?.code ? `code: ${role.code}` : null,
        role?.description ? `description: ${role.description}` : null,
        item.id !== undefined ? `ID: ${item.id}` : null,
        item.username ? `username: ${item.username}` : null,
        item.email ? `email: ${item.email}` : null,
        item.status ? `status: ${item.status}` : null,
        item.org_id !== undefined ? `org ID: ${item.org_id}` : null,
    ].filter(Boolean);
    return details.length > 0
        ? `- **${getDisplayName(item)}** (${details.join(', ')})`
        : `- **${getDisplayName(item)}**`;
}

function formatGenericExecutionResult(step: ExecutionDetail['steps'][number], isChinese: boolean) {
    const data = step.response_data || step.result;
    if (!data) {
        return step.result_content?.trim() || '';
    }

    if (typeof data === 'object' && data !== null) {
        const markdown = (data as any).markdown;
        const mermaid = (data as any).mermaid;
        if (typeof markdown === 'string' && markdown.trim()) {
            return markdown.trim();
        }
        if (typeof mermaid === 'string' && mermaid.trim()) {
            return `\`\`\`mermaid\n${mermaid.trim()}\n\`\`\``;
        }
    }

    if (Array.isArray(data)) {
        const title = isChinese ? `**查询完成，共 ${data.length} 条结果：**` : `**Query completed with ${data.length} result(s):**`;
        return [title, '', ...data.map(formatListItem)].join('\n');
    }

    if (typeof data === 'object') {
        const payload = extractResultPayload(data);
        if (Array.isArray(payload)) {
            const title = isChinese ? `**查询完成，共 ${payload.length} 条结果：**` : `**Query completed with ${payload.length} result(s):**`;
            return [title, '', ...payload.map(formatListItem)].join('\n');
        }

        if (payload && typeof payload === 'object') {
            const lines = formatObjectDetails(payload, isChinese);
            if (lines) {
                const title = isChinese ? `**查询结果：**` : `**Result:**`;
                return `${title}\n\n${lines}`;
            }
        }

        return JSON.stringify(data, null, 2);
    }

    return String(data);
}

interface ExecutionStep {
    step: number;
    displayStep?: number;
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
    originalGoal?: string;
    original_goal?: string;
    repairHint?: {
        recoverable: boolean;
        category: string;
        summary: string;
        suggestedAction?: string;
        coachPrompt?: string;
    };
    repair_hint?: {
        recoverable: boolean;
        category: string;
        summary: string;
        suggested_action?: string;
        coach_prompt?: string;
    };
    userSummary?: {
        headline: string;
        summary: string;
        statusLabel: string;
        nextAction?: string;
        detailLines: string[];
        debugHint?: string;
    };
    user_summary?: {
        headline: string;
        summary: string;
        status_label?: string;
        next_action?: string;
        detail_lines?: string[];
        debug_hint?: string;
    };
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
    const { currentPlanResponse, setCurrentPlanResponse, conversationHistory, setConversationHistory } = useTask();
    const [executionSteps, setExecutionSteps] = useState<ExecutionStep[]>([]);
    const [isExecuting, setIsExecuting] = useState(false);
    const [executionId, setExecutionId] = useState<string | null>(null);
    const [executionStatus, setExecutionStatus] = useState<string | null>(null);
    const [error, setError] = useState('');
    const [executionError, setExecutionError] = useState<string | null>(null);
    const [executionSummary, setExecutionSummary] = useState<ExecutionDetail['userSummary'] | null>(null);
    const [showDebugDetails, setShowDebugDetails] = useState(false);
    const [repairHint, setRepairHint] = useState<ExecutionDetail['repairHint'] | null>(null);
    const [originalGoal, setOriginalGoal] = useState<string | null>(null);
    const [repairGuidance, setRepairGuidance] = useState('');
    const [isRepairing, setIsRepairing] = useState(false);
    const postedExecutionResultsRef = useRef<Set<string>>(new Set());

    // Helper to detect if current goal is Chinese
    // Check multiple sources: originalGoal, question, userPlan summary, or last user message in conversation
    const isChinese = useMemo(() => {
        const goalText =
            originalGoal ||
            currentPlanResponse?.question ||
            currentPlanResponse?.userPlan?.summary ||
            currentPlanResponse?.user_plan?.summary ||
            (conversationHistory.length > 0
                ? [...conversationHistory].reverse().find(msg => msg.role === 'user')?.content || ''
                : '');
        return /[\u4e00-\u9fff]/.test(goalText);
    }, [originalGoal, currentPlanResponse?.question, currentPlanResponse?.userPlan?.summary, currentPlanResponse?.user_plan?.summary, conversationHistory]);

    // Initialize steps from plan response
    useEffect(() => {
        if (currentPlanResponse?.plan) {
            const stepsWithStatus = currentPlanResponse.plan.map((step, index) => ({
                ...step,
                displayStep: index + 1,
                status: 'pending' as const,
                result: undefined,
                error: undefined
            }));
            setExecutionSteps(stepsWithStatus);
            setExecutionId(null);
            setExecutionStatus(null);
            setExecutionSummary(null);
            setRepairHint(null);
            setOriginalGoal(null);
            setRepairGuidance('');
            postedExecutionResultsRef.current.clear();
            setShowDebugDetails(false);
        }
    }, [currentPlanResponse]);

    const executePlan = async (plan: any[], goal?: string | null) => {
        const tenantId = localStorage.getItem('tenantId');
        const token = localStorage.getItem('token');
        const payload = {
            plan,
            global_timeout: 60,
            goal: goal || undefined,
            tenant_id: tenantId ? parseInt(tenantId) : undefined,
            auth_token: token || undefined
        };
        const res = await api.post<ExecutionResponse>('/executions/', payload);
        return res.data;
    };

    const handleExecuteAll = async () => {
        if (!currentPlanResponse?.plan || executionSteps.length === 0) return;

        setIsExecuting(true);
        setError('');
        setExecutionError(null);

        try {
            // Get goal from: 1) originalGoal state, 2) last user message in conversation history
            const goalForExecution =
                originalGoal ||
                [...conversationHistory].reverse().find((msg) => msg.role === 'user')?.content ||
                null;
            console.log('[Bilingual] Executing with goal:', goalForExecution?.substring(0, 100));
            const result = await executePlan(currentPlanResponse.plan, goalForExecution);
            setExecutionId(result.execution_id);
            setExecutionStatus('started');
            setRepairHint(null);

            // Start polling for execution details
            pollExecutionDetails(result.execution_id);
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

                // Debug: log execution details
                console.log('Execution poll result:', {
                    execution_id: data.execution_id,
                    status: data.status,
                    steps_count: data.steps?.length,
                    steps: data.steps?.map((s: any) => ({
                        step_number: s.step_number,
                        status: s.status,
                        has_result_content: !!s.result_content,
                        result_content: s.result_content?.substring(0, 100),
                        has_response_data: !!s.response_data,
                    }))
                });

                // Update steps with status and results
                const updatedSteps = executionSteps.map((step, index) => {
                    const execStep = data.steps.find(s => (s.step_number ?? s.step) === index + 1);
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
                const normalizedSummary = normalizeExecutionSummary(data.userSummary ?? data.user_summary);
                console.log('[Bilingual] Execution poll - userSummary from API:', data.userSummary ?? data.user_summary);
                console.log('[Bilingual] Normalized summary:', normalizedSummary);
                setExecutionSummary(normalizedSummary);
                setRepairHint((data.repairHint ?? data.repair_hint ?? null) as any);
                setOriginalGoal(data.originalGoal ?? data.original_goal ?? null);
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

                    // Add execution result to conversation history when completed
                    if (data.status === 'completed' || data.status === 'partial_failed') {
                        let resultContent = '';

                        // Build result from step results - focus on final outcome, not intermediate steps
                        const completedSteps = data.steps?.filter(s => s.status === 'completed' || s.status === 'success') || [];

                        // Debug: log completed steps
                        console.log('[Result] Completed steps:', completedSteps.length);
                        console.log('[Result] Steps data:', completedSteps.map(s => ({
                            step: s.step_number || s.step,
                            command: s.command,
                            has_response_data: !!s.response_data,
                            response_keys: s.response_data ? Object.keys(s.response_data) : [],
                            permissions: s.response_data?.permissions ? Array.isArray(s.response_data.permissions) : false,
                        })));

                        if (completedSteps.length > 0) {
                            const stepResults: string[] = [];
                            for (const step of completedSteps) {
                                if (step.response_data) {
                                    // Extract meaningful data from response_data
                                    const rd = step.response_data;
                                    console.log('[Result] Processing step:', step.command, 'response_data keys:', Object.keys(rd));

                                    // Check for permissions in response_data.data.permissions (MCP tool result structure)
                                    const permissions = rd?.data?.permissions || rd?.permissions;
                                    if (permissions && Array.isArray(permissions)) {
                                        // Detect language from original goal for bilingual output
                                        // Use data.originalGoal directly to avoid stale closure issues
                                        const goalText = (data.originalGoal ?? data.original_goal ?? originalGoal) || '';
                                        const hasChinese = /[\u4e00-\u9fff]/.test(goalText);
                                        const isChinese = hasChinese;
                                        console.log('[Result] Language detection:', { goalText: goalText.substring(0, 50), hasChinese, isChinese });

                                        // Format permissions as a readable list
                                        const permissionList = permissions.map((p: any) => {
                                            const parts = [];
                                            if (p.name) parts.push(p.name);
                                            if (p.code) parts.push(`[${p.code}]`);
                                            if (p.resource) parts.push(`on ${p.resource}`);
                                            if (p.action) parts.push(`(${p.action})`);
                                            return `- ${parts.join(' ')}`;
                                        }).join('\n');
                                        const resultText = isChinese
                                            ? `**找到 ${permissions.length} 个权限：**\n${permissionList}`
                                            : `**Found ${permissions.length} permission(s):**\n${permissionList}`;
                                        console.log('[Result] Added permission result:', resultText.substring(0, 100));
                                        stepResults.push(resultText);
                                    } else if (rd.matched_role || rd.matched_member) {
                                        // Skip intermediate resolution steps
                                        console.log('[Result] Skipping intermediate resolution step');
                                        continue;
                                    } else if (rd.data && Array.isArray(rd.data) && rd.data.length > 0 && !permissions) {
                                        // Skip generic list results (like list_roles, list_members) unless it's the final answer
                                        console.log('[Result] Skipping generic list result, data length:', rd.data.length);
                                        continue;
                                    } else {
                                        console.log('[Result] Step has response_data but no permissions:', {
                                            has_data_permissions: !!rd?.data?.permissions,
                                            has_direct_permissions: !!rd?.permissions,
                                            response_keys: Object.keys(rd)
                                        });
                                    }
                                }
                            }
                            if (stepResults.length > 0) {
                                resultContent = stepResults.join('\n\n');
                                console.log('[Result] Final resultContent:', resultContent.substring(0, 200));
                            } else {
                                console.log('[Result] No stepResults accumulated');
                                const finalStep = [...completedSteps]
                                    .reverse()
                                    .find((step) => step.result_content || step.response_data || step.result);
                                if (finalStep) {
                                    resultContent = formatGenericExecutionResult(finalStep, isChinese).trim();
                                    console.log('[Result] Generic resultContent:', resultContent.substring(0, 200));
                                }
                            }
                        }

                        if (resultContent.trim() && !postedExecutionResultsRef.current.has(data.execution_id)) {
                            postedExecutionResultsRef.current.add(data.execution_id);
                            setConversationHistory((previous) => [
                                ...previous,
                                { role: 'assistant', content: resultContent.trim() }
                            ]);
                        } else {
                            console.log('[Result] No resultContent to add');
                        }
                    }
                }
            } catch (err) {
                console.error('Failed to fetch execution details:', err);
                clearInterval(interval);
                setIsExecuting(false);
            }
        }, 2000); // Poll every 2 seconds
    };

    const handleRepair = async () => {
        if (!executionId || !repairHint?.recoverable) return;
        setIsRepairing(true);
        setError('');
        try {
            const goalFromContext =
                originalGoal ||
                [...conversationHistory].reverse().find((item) => item.role === 'user')?.content ||
                '';
            const repairPayload = {
                goal: goalFromContext,
                guidance: repairGuidance || undefined,
                conversationHistory: conversationHistory,
            };
            const res = await api.post<any>(`/executions/${executionId}/repair`, repairPayload);
            const repaired = res.data;
            const nextResponse = {
                type: repaired.type || 'repair_plan_ready',
                confidence: repaired.confidence ?? currentPlanResponse?.confidence ?? 0,
                plan: repaired.repairedPlan || repaired.repaired_plan || [],
                assistantMessage: repaired.repairPlanDescription || repaired.repair_plan_description || repaired.repairSummary,
                userPlan: {
                    headline: isChinese ? '我已根据你的提示修复方案' : 'I have repaired the plan based on your guidance',
                    summary: repaired.repairPlanDescription || repaired.repair_plan_description || (isChinese ? '我会按修复后的方案继续执行。' : 'I will continue executing with the repaired plan.'),
                    steps: [],
                    nextAction: isChinese ? '系统将继续按修复后的方案执行。' : 'The system will continue executing with the repaired plan.',
                    debugHint: isChinese ? '调试详情中会保留修复后的工具选择和步骤。' : 'Debug details retain the repaired tool selections and steps.',
                },
                retrievalDiagnostics: currentPlanResponse?.retrievalDiagnostics,
                resolvedMode: currentPlanResponse?.resolvedMode,
                llmSummary: currentPlanResponse?.llmSummary || currentPlanResponse?.llm_summary,
            };
            setCurrentPlanResponse(nextResponse as any);
            if (repairGuidance.trim()) {
                setConversationHistory([
                    ...conversationHistory,
                    { role: 'user', content: repairGuidance.trim() },
                    { role: 'assistant', content: repaired.repairSummary || '我已根据你的提示重建执行计划。' },
                ]);
            }
            setExecutionId(null);
            setExecutionStatus(null);
            setExecutionError(null);
            setRepairHint(null);
            setRepairGuidance('');
            const repairedPlan = repaired.repairedPlan || repaired.repaired_plan || [];
            if (Array.isArray(repairedPlan) && repairedPlan.length > 0) {
                setIsExecuting(true);
                const executeResult = await executePlan(repairedPlan, goalFromContext);
                setExecutionId(executeResult.execution_id);
                setExecutionStatus('started');
                pollExecutionDetails(executeResult.execution_id);
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || err.message || 'Failed to repair execution');
        } finally {
            setIsRepairing(false);
        }
    };

    const userPlan = normalizeUserPlan(currentPlanResponse);
    const directResult = normalizeDirectResult(currentPlanResponse);
    const llmSummary = normalizeLlmSummary(currentPlanResponse);
    const retrievalDiagnostics = currentPlanResponse?.retrievalDiagnostics;
    const resolvedMode = currentPlanResponse?.resolvedMode ?? 'cmdengine';
    const summaryCard = executionSummary ?? (userPlan ? {
        headline: userPlan.headline,
        summary: userPlan.summary,
        statusLabel: executionStatus ?? 'ready',
        nextAction: userPlan.nextAction,
        detailLines: userPlan.steps ?? [],
        debugHint: userPlan.debugHint,
    } : null);

    const getStatusBgColor = (status?: string) => {
        switch (status) {
            case 'success':
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
            case 'success':
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
            case 'success':
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
        if (directResult) {
            return (
                <div className="flex flex-1 flex-col gap-4 overflow-y-auto">
                    <MCPSelector />
                    {summaryCard && (
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
                            <div className="mb-2 text-sm font-semibold text-emerald-900">{summaryCard.headline}</div>
                            <div className="text-sm leading-6 text-slate-700">{summaryCard.summary}</div>
                            {summaryCard.nextAction && (
                                <div className="mt-3 text-xs text-slate-600">{summaryCard.nextAction}</div>
                            )}
                        </div>
                    )}
                    {/* Render direct result data with expandable lists */}
                    {directResult.data && Object.keys(directResult.data).length > 0 && (
                        <div className="rounded-lg border border-slate-200 bg-white p-4">
                            <div className="mb-2 text-sm font-semibold text-slate-700">执行结果</div>
                            <ExecutionResultRenderer
                                data={directResult.data}
                                resultContent={directResult.content}
                            />
                        </div>
                    )}
                    <div className="rounded-lg border border-slate-200 bg-white p-4">
                        <button
                            type="button"
                            onClick={() => setShowDebugDetails((value) => !value)}
                            className="flex w-full items-center justify-between text-left text-sm font-semibold text-slate-700"
                        >
                            <span>{isChinese ? '调试详情' : 'Debug Details'}</span>
                            <span className="text-xs text-slate-500">{showDebugDetails ? (isChinese ? '隐藏' : 'Hide') : (isChinese ? '展开' : 'Expand')}</span>
                        </button>
                        {showDebugDetails && (
                            <div className="mt-4 space-y-3">
                                <div className="text-xs text-slate-600">
                                    Resolved mode: {resolvedMode}
                                </div>
                                <div className="rounded bg-slate-50 px-3 py-2 font-mono text-sm text-slate-700">
                                    {directResult.serverName}.{directResult.toolName}
                                </div>
                                {Object.keys(directResult.params ?? {}).length > 0 && (
                                    <pre className="overflow-auto rounded bg-slate-50 p-3 text-xs text-slate-600">
                                        {JSON.stringify(directResult.params, null, 2)}
                                    </pre>
                                )}
                                {directResult.data && Object.keys(directResult.data).length > 0 && (
                                    <pre className="overflow-auto rounded bg-slate-50 p-3 text-xs text-slate-500">
                                        {JSON.stringify(directResult.data, null, 2)}
                                    </pre>
                                )}
                            </div>
                        )}
                    </div>

                    {showDebugDetails && retrievalDiagnostics && (
                        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                            <div className="mb-2 text-sm font-semibold text-slate-700">Retrieval Diagnostics</div>
                            <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                                <div>Requested mode: {retrievalDiagnostics.requested_mode ?? 'auto'}</div>
                                <div>Requested retrieval: {retrievalDiagnostics.requested_retrieval_backend ?? 'auto'}</div>
                                <div>Resolved mode: {retrievalDiagnostics.resolved_mode ?? resolvedMode}</div>
                                <div>Retrieval backend: {retrievalDiagnostics.retrieval_backend ?? 'n/a'}</div>
                                <div>Remote candidates: {retrievalDiagnostics.remote_candidate_count ?? 0}</div>
                                <div>Remote top score: {retrievalDiagnostics.remote_top_score ?? 'n/a'}</div>
                                <div>Keyword hits: {retrievalDiagnostics.keyword_hits ?? 0}</div>
                                <div>Vector hits: {retrievalDiagnostics.vector_hits ?? 0}</div>
                                <div>Raw candidates: {retrievalDiagnostics.raw_candidate_count ?? 0}</div>
                                <div>Prompt candidates: {retrievalDiagnostics.prompt_candidate_count ?? 0}</div>
                                <div>Embedding provider: {retrievalDiagnostics.embedding_provider ?? 'n/a'}</div>
                                <div>Embedding model: {retrievalDiagnostics.embedding_model ?? 'n/a'}</div>
                                <div>Fallback reason: {retrievalDiagnostics.remote_fallback_reason ?? 'none'}</div>
                            </div>
                        </div>
                    )}
                </div>
            );
        }

        return (
            <div className="flex flex-1 flex-col items-center justify-center text-center p-6 text-slate-600">
                <p className="text-sm">{isChinese ? '在左侧对话中发起任务，这里会显示任务摘要和可展开的调试详情。' : 'Start a task in the conversation on the left; task summaries and expandable debug details will appear here.'}</p>
            </div>
        );
    }

    return (
        <div className="flex flex-1 flex-col gap-6 overflow-y-auto">
            {/* MCP Selector */}
            <MCPSelector />

            {summaryCard && (
                <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                    <div className="mb-2 flex items-center justify-between gap-3">
                        <div className="text-sm font-semibold text-slate-800">{summaryCard.headline}</div>
                        <span className="rounded-full bg-white px-2 py-1 text-xs font-medium capitalize text-slate-600">
                            {summaryCard.statusLabel}
                        </span>
                    </div>
                    <div className="text-sm leading-6 text-slate-700">{summaryCard.summary}</div>
                    {summaryCard.detailLines && summaryCard.detailLines.length > 0 && (
                        <div className="mt-3 space-y-1 text-xs text-slate-600">
                            {summaryCard.detailLines.map((line: string) => (
                                <div key={line}>{line}</div>
                            ))}
                        </div>
                    )}
                    {summaryCard.nextAction && (
                        <div className="mt-3 text-xs text-slate-600">{summaryCard.nextAction}</div>
                    )}
                    {summaryCard.debugHint && (
                        <div className="mt-2 text-xs text-slate-500">{summaryCard.debugHint}</div>
                    )}
                </div>
            )}

            {/* Execution Summary */}
            {executionId && (
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                    <div className="text-sm">
                        <span className="font-medium text-slate-700">{isChinese ? '执行 ID:' : 'Execution ID:'}</span>
                        <span className="text-blue-600 ml-2 font-mono">{executionId}</span>
                    </div>
                    <div className="text-sm mt-1">
                        <span className="font-medium text-slate-700">{isChinese ? '状态:' : 'Status:'}</span>
                        <span className="text-slate-600 ml-2 capitalize">{executionStatus}</span>
                    </div>
                </div>
            )}

            {/* Execution-level Error Message */}
            {executionError && (
                <div className="p-4 bg-red-50 border border-red-300 rounded-lg">
                    <div className="text-sm font-semibold text-red-800 mb-2">执行出现异常</div>
                    <div className="text-sm text-red-700">
                        系统没有完整完成这次请求。你可以展开调试详情查看技术原因。
                    </div>
                </div>
            )}

            {repairHint?.recoverable && (
                <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
                    <div className="text-sm font-semibold text-amber-900">继续教系统修复这次任务</div>
                    <div className="mt-2 text-sm text-slate-700">{repairHint.summary}</div>
                    {repairHint.suggestedAction && (
                        <div className="mt-2 text-xs text-slate-600">
                            {repairHint.suggestedAction}
                        </div>
                    )}
                    {repairHint.coachPrompt && (
                        <div className="mt-3 text-xs font-medium text-slate-700">
                            {repairHint.coachPrompt}
                        </div>
                    )}
                    <textarea
                        value={repairGuidance}
                        onChange={(e) => setRepairGuidance(e.target.value)}
                        placeholder="例如：先从成员列表中按 username=admin 匹配，再取 member_id。"
                        className="mt-3 min-h-24 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-amber-400"
                        disabled={isRepairing}
                    />
                    <div className="mt-3 flex justify-end">
                        <button
                            type="button"
                            onClick={handleRepair}
                            disabled={isRepairing}
                            className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-600 disabled:opacity-50"
                        >
                            {isRepairing ? 'Repairing...' : '继续尝试'}
                        </button>
                    </div>
                </div>
            )}

            {/* Request-level Error Message */}
            {error && (
                <div className="p-3 bg-red-100 border border-red-300 rounded-lg text-sm text-red-700">
                    {error}
                </div>
            )}

            <div className="rounded-lg border border-slate-200 bg-white p-4">
                <button
                    type="button"
                    onClick={() => setShowDebugDetails((value) => !value)}
                    className="flex w-full items-center justify-between text-left"
                >
                    <div>
                        <div className="text-sm font-semibold text-slate-700">
                            {isChinese ? '调试详情' : 'Debug Details'}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                            {isChinese
                                ? '这里保留内部规划、检索诊断、步骤状态和技术错误，默认对正式用户隐藏。'
                                : 'Internal planning, retrieval diagnostics, step status, and technical errors are shown here, hidden from production users by default.'}
                        </div>
                    </div>
                    <span className="text-xs text-slate-500">{showDebugDetails ? (isChinese ? '隐藏' : 'Hide') : (isChinese ? '展开' : 'Expand')}</span>
                </button>

                {showDebugDetails && (
                    <div className="mt-4">
                        <div className="mb-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                            <div>Resolved mode: {resolvedMode}</div>
                            <div>Confidence: {Math.round((currentPlanResponse.confidence ?? 0) * 100)}%</div>
                        </div>

                {retrievalDiagnostics && (
                    <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
                        <div className="mb-2 text-sm font-semibold text-slate-700">Retrieval Diagnostics</div>
                        <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                            <div>Requested mode: {retrievalDiagnostics.requested_mode ?? 'auto'}</div>
                            <div>Requested retrieval: {retrievalDiagnostics.requested_retrieval_backend ?? 'auto'}</div>
                            <div>Resolved mode: {retrievalDiagnostics.resolved_mode ?? resolvedMode}</div>
                            <div>Retrieval backend: {retrievalDiagnostics.retrieval_backend ?? 'n/a'}</div>
                            <div>Remote candidates: {retrievalDiagnostics.remote_candidate_count ?? 0}</div>
                            <div>Remote top score: {retrievalDiagnostics.remote_top_score ?? 'n/a'}</div>
                            <div>Keyword hits: {retrievalDiagnostics.keyword_hits ?? 0}</div>
                            <div>Vector hits: {retrievalDiagnostics.vector_hits ?? 0}</div>
                            <div>Raw candidates: {retrievalDiagnostics.raw_candidate_count ?? 0}</div>
                            <div>Prompt candidates: {retrievalDiagnostics.prompt_candidate_count ?? 0}</div>
                            <div>System state loaded: {retrievalDiagnostics.system_state_loaded ? 'yes' : 'no'}</div>
                            <div>Embedding provider: {retrievalDiagnostics.embedding_provider ?? 'n/a'}</div>
                            <div>Fallback reason: {retrievalDiagnostics.remote_fallback_reason ?? 'none'}</div>
                        </div>
                        {retrievalDiagnostics.top_commands && retrievalDiagnostics.top_commands.length > 0 && (
                            <div className="mt-3">
                                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Top Commands</div>
                                <div className="space-y-1 font-mono text-xs text-slate-700">
                                    {retrievalDiagnostics.top_commands.map((command) => (
                                        <div key={command}>{command}</div>
                                    ))}
                                </div>
                            </div>
                        )}
                        {llmSummary && (
                            <div className="mt-3">
                                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">LLM Response</div>
                                <div className="whitespace-pre-wrap rounded bg-white px-3 py-2 text-xs leading-6 text-slate-700">
                                    {llmSummary}
                                </div>
                            </div>
                        )}
                    </div>
                )}

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
                                            Step {step.displayStep ?? step.step}: {step.description}
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
                )}
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
