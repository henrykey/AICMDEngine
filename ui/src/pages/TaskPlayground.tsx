import { useState } from 'react';
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

    const { data: commandSets } = useQuery({
        queryKey: ['command-sets'],
        queryFn: async () => {
            const res = await api.get<CommandSet[]>('/command-sets/');
            return res.data;
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

    return (
        <div className="max-w-4xl mx-auto space-y-6">
            <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
                <h2 className="text-lg font-semibold mb-4">Task Planning Playground</h2>

                {/* Command Set Selection */}
                <div className="mb-4 p-4 bg-gray-900 rounded border border-gray-700">
                    <label className="block text-sm font-medium mb-2 text-gray-300">
                        📚 Command Sets (optional - leave empty to use all)
                    </label>
                    <div className="flex flex-wrap gap-2">
                        {commandSets?.map((cs) => (
                            <button
                                key={cs._id}
                                onClick={() => toggleCommandSet(cs.name)}
                                className={`px-3 py-1 rounded text-sm transition ${selectedCommandSets.includes(cs.name)
                                        ? 'bg-blue-600 text-white'
                                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                                    }`}
                            >
                                {cs.name}
                            </button>
                        ))}
                        {commandSets?.length === 0 && (
                            <span className="text-gray-500 text-sm">No command sets available</span>
                        )}
                    </div>
                    {selectedCommandSets.length > 0 && (
                        <div className="mt-2 text-xs text-blue-400">
                            Using: {selectedCommandSets.join(', ')}
                        </div>
                    )}
                    {selectedCommandSets.length === 0 && commandSets && commandSets.length > 0 && (
                        <div className="mt-2 text-xs text-gray-500">
                            Using all available command sets
                        </div>
                    )}
                </div>

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
                        onKeyDown={(e) => e.key === 'Enter' && handlePlanTask()}
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
                    Error: {String(mutation.error)}
                </div>
            )}

            {mutation.data && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4">
                    <div className="flex items-center gap-4">
                        <div className={`px-3 py-1 rounded-full text-sm font-bold ${mutation.data.type === 'plan_ready' ? 'bg-green-900 text-green-200' : 'bg-yellow-900 text-yellow-200'}`}>
                            {mutation.data.type === 'plan_ready' ? 'PLAN READY' : 'CLARIFICATION NEEDED'}
                        </div>
                        <div className="text-gray-400 text-sm">
                            Confidence: {(mutation.data.confidence * 100).toFixed(0)}%
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

                    <div className="bg-gray-900 p-4 rounded text-xs text-gray-600 font-mono overflow-auto max-h-40">
                        Raw Response: {JSON.stringify(mutation.data, null, 2)}
                    </div>
                </div>
            )}
        </div>
    );
}
