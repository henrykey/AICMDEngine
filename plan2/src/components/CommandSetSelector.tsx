import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { useTask } from '../contexts/TaskContext';

interface CommandSet {
    _id?: string;
    name: string;
    description?: string;
}

const CommandSetSelector: React.FC = () => {
    const { selectedCommandSets, setSelectedCommandSets } = useTask();
    const [commandSets, setCommandSets] = useState<CommandSet[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    useEffect(() => {
        loadCommandSets();
    }, []);

    const loadCommandSets = async () => {
        setIsLoading(true);
        try {
            const res = await api.get<CommandSet[]>('/command-sets/');
            setCommandSets(res.data);
        } catch (err) {
            console.error('Failed to load command sets:', err);
        } finally {
            setIsLoading(false);
        }
    };

    const toggleCommandSet = (name: string) => {
        const updated = selectedCommandSets.includes(name)
            ? selectedCommandSets.filter(n => n !== name)
            : [...selectedCommandSets, name];
        setSelectedCommandSets(updated);
    };

    if (isLoading || commandSets.length === 0) {
        return null;
    }

    return (
        <div className="p-2 bg-slate-100 rounded-lg border border-slate-300">
            <label className="block text-xs font-medium text-slate-700 mb-1.5">
                Command Sets (optional)
            </label>
            <div className="flex flex-wrap gap-1.5">
                {commandSets.map((cs) => (
                    <button
                        key={cs._id}
                        onClick={() => toggleCommandSet(cs.name)}
                        className={`px-2 py-0.5 rounded text-xs font-medium transition ${
                            selectedCommandSets.includes(cs.name)
                                ? 'bg-blue-500 text-white'
                                : 'bg-white text-slate-700 border border-slate-300 hover:border-slate-400'
                        }`}
                    >
                        {cs.name}
                    </button>
                ))}
            </div>
        </div>
    );
};

export default CommandSetSelector;
