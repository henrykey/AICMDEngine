import { createContext, useContext, useState, type ReactNode } from 'react';

export interface ExecutionDetail {
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

interface ExecutionContextType {
  executionId: string | null;
  executionDetail: ExecutionDetail | null;
  rawResponse: string | null;
  setExecutionId: (id: string | null) => void;
  setExecutionDetail: (detail: ExecutionDetail | null) => void;
  setRawResponse: (response: string | null) => void;
}

const ExecutionContext = createContext<ExecutionContextType | undefined>(undefined);

export function ExecutionProvider({ children }: { children: ReactNode }) {
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [executionDetail, setExecutionDetail] = useState<ExecutionDetail | null>(null);
  const [rawResponse, setRawResponse] = useState<string | null>(null);

  return (
    <ExecutionContext.Provider value={{
      executionId,
      executionDetail,
      rawResponse,
      setExecutionId,
      setExecutionDetail,
      setRawResponse
    }}>
      {children}
    </ExecutionContext.Provider>
  );
}

export function useExecutionContext() {
  const context = useContext(ExecutionContext);
  if (!context) {
    throw new Error('useExecutionContext must be used within ExecutionProvider');
  }
  return context;
}
