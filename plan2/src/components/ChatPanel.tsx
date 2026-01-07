import { useState, useRef, useEffect } from 'react';
import { api } from '../lib/api';
import { useTask, PlanResponse } from '../contexts/TaskContext';

interface CommandSet {
    _id?: string;
    name: string;
    description?: string;
}

const ChatPanel: React.FC = () => {
    const { conversationHistory, setConversationHistory, lastQuestion, setLastQuestion, setCurrentPlanResponse } = useTask();
    const [goal, setGoal] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');
    const [commandSets, setCommandSets] = useState<CommandSet[]>([]);
    const [selectedCommandSets, setSelectedCommandSets] = useState<string[]>([]);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Load command sets on mount
    useEffect(() => {
        loadCommandSets();
    }, []);

    // Auto-scroll to latest message
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [conversationHistory]);

    const loadCommandSets = async () => {
        try {
            const res = await api.get<CommandSet[]>('/command-sets/');
            setCommandSets(res.data);
        } catch (err) {
            console.error('Failed to load command sets:', err);
        }
    };

    const handlePlanTask = async () => {
        if (!goal.trim()) return;

        setIsLoading(true);
        setError('');

        try {
            const payload: any = {
                goal,
                conversationHistory: conversationHistory.length > 0 ? conversationHistory : undefined
            };

            if (selectedCommandSets.length > 0) {
                payload.context = { commandSetNames: selectedCommandSets };
            }

            const res = await api.post<PlanResponse>('/tasks/', payload);
            const data = res.data;

            if (data.question) {
                setLastQuestion(data.question);
                const newHistory = [
                    ...conversationHistory,
                    { role: 'user' as const, content: goal },
                    { role: 'assistant' as const, content: data.question }
                ];
                setConversationHistory(newHistory);
            } else {
                setLastQuestion(null);
                setCurrentPlanResponse(data);
            }

            setGoal('');
        } catch (err: any) {
            setError(err.response?.data?.error_message || err.message || 'Failed to plan task');
        } finally {
            setIsLoading(false);
        }
    };

    const handleClearConversation = () => {
        setConversationHistory([]);
        setLastQuestion(null);
        setGoal('');
        setError('');
    };

    const toggleCommandSet = (name: string) => {
        setSelectedCommandSets(prev =>
            prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]
        );
    };

    return (
        <div className="flex flex-1 flex-col overflow-hidden gap-4">
            {/* Command Sets Selection */}
            {commandSets.length > 0 && (
                <div className="p-3 bg-slate-100 rounded-lg border border-slate-200">
                    <label className="block text-xs font-medium text-slate-700 mb-2">
                        Command Sets (optional)
                    </label>
                    <div className="flex flex-wrap gap-2">
                        {commandSets.map((cs) => (
                            <button
                                key={cs._id}
                                onClick={() => toggleCommandSet(cs.name)}
                                className={`px-3 py-1 rounded text-xs transition ${selectedCommandSets.includes(cs.name)
                                    ? 'bg-blue-500 text-white'
                                    : 'bg-slate-200 text-slate-700 hover:bg-slate-300'
                                    }`}
                            >
                                {cs.name}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* Conversation History */}
            <div className="chat-messages flex flex-1 flex-col gap-4 overflow-y-auto pr-1">
                {conversationHistory.map((msg, idx) => (
                    <div
                        key={idx}
                        className={`max-w-[85%] p-3 rounded-lg text-sm leading-relaxed shadow-sm ${msg.role === 'user'
                            ? 'ml-auto rounded-br-none bg-blue-500 text-white'
                            : 'rounded-bl-none bg-slate-100 text-slate-800'
                            }`}
                    >
                        {msg.content}
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>

            {/* Error Message */}
            {error && (
                <div className="p-3 bg-red-100 border border-red-300 rounded-lg text-sm text-red-700">
                    {error}
                </div>
            )}

            {/* Input Area */}
            <div className="flex gap-2">
                <input
                    type="text"
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !isLoading && handlePlanTask()}
                    placeholder={lastQuestion ? "Answer the AI's question..." : "Describe your task..."}
                    className="flex-1 p-3 text-sm border border-slate-200 rounded-lg bg-white focus:bg-white focus:border-blue-500 focus:outline-none disabled:opacity-50"
                    disabled={isLoading}
                />
                <button
                    onClick={handlePlanTask}
                    disabled={isLoading || !goal.trim()}
                    className="px-4 py-3 bg-blue-500 hover:bg-blue-600 text-white text-sm rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition"
                >
                    {isLoading ? 'Planning...' : 'Plan'}
                </button>
                {conversationHistory.length > 0 && (
                    <button
                        onClick={handleClearConversation}
                        className="px-4 py-3 bg-slate-200 hover:bg-slate-300 text-slate-700 text-sm rounded-lg font-medium transition"
                    >
                        Clear
                    </button>
                )}
            </div>
        </div>
    );
};

export default ChatPanel;
