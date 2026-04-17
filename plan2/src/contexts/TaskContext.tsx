import React, { createContext, useContext, useState, ReactNode } from 'react';

export interface PlanStep {
    step: number;
    description: string;
    command: string;
    params: Record<string, any>;
}

export interface PlanResponse {
    type: string;
    confidence: number;
    plan?: PlanStep[];
    question?: string;
    llmSummary?: string;
    llm_summary?: string;
    assistantMessage?: string;
    assistant_message?: string;
    userPlan?: {
        headline: string;
        summary: string;
        steps: string[];
        nextAction?: string;
        debugHint?: string;
    };
    user_plan?: {
        headline: string;
        summary: string;
        steps: string[];
        nextAction?: string;
        next_action?: string;
        debugHint?: string;
        debug_hint?: string;
    };
    debugAvailable?: boolean;
    debug_available?: boolean;
    resolvedMode?: string;
    retrievalDiagnostics?: {
        requested_retrieval_backend?: string;
        retrieval_backend?: string;
        remote_candidate_count?: number;
        remote_top_score?: number;
        remote_fallback_reason?: string;
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
    direct_result?: {
        serverName?: string;
        server_name?: string;
        toolName?: string;
        tool_name?: string;
        params: Record<string, any>;
        content: string;
        data: Record<string, any>;
    };
    risk_assessment?: {
        level: 'normal' | 'high' | 'critical';
        message: string;
    }
}

export interface ConversationMessage {
    role: 'user' | 'assistant';
    content: string;
}

export interface MCPToolInfo {
    name: string;
    description: string;
    input_schema: Record<string, any>;
}

export interface MCPServerInfo {
    name: string;
    version: string;
    description: string;
    status: 'running' | 'stopped' | 'error';
    tools: MCPToolInfo[];
}

export interface TaskContextType {
    // Chat state
    conversationHistory: ConversationMessage[];
    setConversationHistory: React.Dispatch<React.SetStateAction<ConversationMessage[]>>;
    lastQuestion: string | null;
    setLastQuestion: (question: string | null) => void;

    // Plan state
    currentPlan: PlanStep[] | null;
    setCurrentPlan: (plan: PlanStep[] | null) => void;
    currentPlanResponse: PlanResponse | null;
    setCurrentPlanResponse: (response: PlanResponse | null) => void;

    // Execution state
    executionId: string | null;
    setExecutionId: (id: string | null) => void;
    executionStatus: string | null;
    setExecutionStatus: (status: string | null) => void;

    // MCP selection state
    selectedMcp: string | null;
    setSelectedMcp: (mcp: string | null) => void;
    availableMcps: MCPServerInfo[];
    setAvailableMcps: (mcps: MCPServerInfo[]) => void;

    // Command Sets selection state
    selectedCommandSets: string[];
    setSelectedCommandSets: (sets: string[]) => void;

    // Planning mode
    planningMode: 'auto' | 'cmdengine' | 'mcp';
    setPlanningMode: (mode: 'auto' | 'cmdengine' | 'mcp') => void;
    retrievalBackend: 'auto' | 'docintel';
    setRetrievalBackend: (backend: 'auto' | 'docintel') => void;
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

export const TaskProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [conversationHistory, setConversationHistory] = useState<ConversationMessage[]>([]);
    const [lastQuestion, setLastQuestion] = useState<string | null>(null);
    const [currentPlan, setCurrentPlan] = useState<PlanStep[] | null>(null);
    const [currentPlanResponse, setCurrentPlanResponse] = useState<PlanResponse | null>(null);
    const [executionId, setExecutionId] = useState<string | null>(null);
    const [executionStatus, setExecutionStatus] = useState<string | null>(null);
    const [selectedMcp, setSelectedMcp] = useState<string | null>(null);
    const [availableMcps, setAvailableMcps] = useState<MCPServerInfo[]>([]);
    const [selectedCommandSets, setSelectedCommandSets] = useState<string[]>([]);
    const [planningMode, setPlanningMode] = useState<'auto' | 'cmdengine' | 'mcp'>('auto');
    const [retrievalBackend, setRetrievalBackend] = useState<'auto' | 'docintel'>('auto');

    const value: TaskContextType = {
        conversationHistory,
        setConversationHistory,
        lastQuestion,
        setLastQuestion,
        currentPlan,
        setCurrentPlan,
        currentPlanResponse,
        setCurrentPlanResponse,
        executionId,
        setExecutionId,
        executionStatus,
        setExecutionStatus,
        selectedMcp,
        setSelectedMcp,
        availableMcps,
        setAvailableMcps,
        selectedCommandSets,
        setSelectedCommandSets,
        planningMode,
        setPlanningMode,
        retrievalBackend,
        setRetrievalBackend,
    };

    return (
        <TaskContext.Provider value={value}>
            {children}
        </TaskContext.Provider>
    );
};

export const useTask = () => {
    const context = useContext(TaskContext);
    if (!context) {
        throw new Error('useTask must be used within TaskProvider');
    }
    return context;
};
