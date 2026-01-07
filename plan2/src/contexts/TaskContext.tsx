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
    risk_assessment?: {
        level: 'normal' | 'high' | 'critical';
        message: string;
    }
}

export interface ConversationMessage {
    role: 'user' | 'assistant';
    content: string;
}

export interface TaskContextType {
    // Chat state
    conversationHistory: ConversationMessage[];
    setConversationHistory: (messages: ConversationMessage[]) => void;
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
}

const TaskContext = createContext<TaskContextType | undefined>(undefined);

export const TaskProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [conversationHistory, setConversationHistory] = useState<ConversationMessage[]>([]);
    const [lastQuestion, setLastQuestion] = useState<string | null>(null);
    const [currentPlan, setCurrentPlan] = useState<PlanStep[] | null>(null);
    const [currentPlanResponse, setCurrentPlanResponse] = useState<PlanResponse | null>(null);
    const [executionId, setExecutionId] = useState<string | null>(null);
    const [executionStatus, setExecutionStatus] = useState<string | null>(null);

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
