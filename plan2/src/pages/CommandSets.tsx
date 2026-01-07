import { useState, useEffect } from 'react';
import { api } from '../lib/api';

interface CommandSet {
    _id?: string;
    name: string;
    description?: string;
    version?: string;
}

const CommandSets = () => {
    const [commandSets, setCommandSets] = useState<CommandSet[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState('');
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
    const [isImportModalOpen, setIsImportModalOpen] = useState(false);
    const [selectedSetId, setSelectedSetId] = useState<string | null>(null);

    const [name, setName] = useState('');
    const [desc, setDesc] = useState('');
    const [docContent, setDocContent] = useState('');
    const [status, setStatus] = useState('');

    useEffect(() => {
        loadCommandSets();
    }, []);

    const loadCommandSets = async () => {
        setIsLoading(true);
        try {
            const res = await api.get<CommandSet[]>('/command-sets/');
            setCommandSets(res.data);
            setError('');
        } catch (err: any) {
            setError('Failed to load command sets');
            console.error(err);
        } finally {
            setIsLoading(false);
        }
    };

    const handleCreateSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setStatus('Creating...');

        try {
            const response = await api.post('/command-sets/', {
                name,
                description: desc,
                tenant_id: 'auto-filled',
                source_type: 'manual'
            });

            const newSetId = response.data._id;

            if (docContent.trim()) {
                setStatus('Analyzing documentation...');
                await api.post(`/command-sets/${newSetId}/import/smart`, {
                    document: docContent
                });
                setStatus('✅ Created and imported successfully!');
            } else {
                setStatus('✅ Command Set created!');
            }

            await loadCommandSets();

            setTimeout(() => {
                setIsCreateModalOpen(false);
                setName('');
                setDesc('');
                setDocContent('');
                setStatus('');
            }, 1500);
        } catch (error: any) {
            setStatus(`❌ Error: ${error.response?.data?.detail || error.message}`);
        }
    };

    const handleImportSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!docContent.trim()) {
            setStatus('❌ Please paste documentation content');
            return;
        }

        if (!selectedSetId) return;

        setStatus('Analyzing documentation...');
        try {
            await api.post(`/command-sets/${selectedSetId}/import/smart`, {
                document: docContent
            });
            setStatus(`✅ Success! Import completed.`);
            await loadCommandSets();

            setTimeout(() => {
                setIsImportModalOpen(false);
                setStatus('');
                setDocContent('');
            }, 2000);
        } catch (err: any) {
            setStatus(`❌ Error: ${err.response?.data?.detail || err.message}`);
        }
    };

    const handleDelete = async (setId: string, name: string) => {
        if (confirm(`Delete "${name}"?\n\nThis will also delete all commands in this set and cannot be undone.`)) {
            try {
                await api.delete(`/command-sets/${setId}`);
                await loadCommandSets();
            } catch (err: any) {
                alert(`Failed to delete: ${err.message}`);
            }
        }
    };

    return (
        <div className="max-w-6xl mx-auto p-6">
            <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold">Command Sets Configuration</h2>
                <button
                    onClick={() => setIsCreateModalOpen(true)}
                    className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded transition flex items-center gap-2 text-white"
                >
                    <span>+</span> New Command Set
                </button>
            </div>

            {error && (
                <div className="p-4 bg-red-100 border border-red-300 rounded-lg mb-6 text-red-700">
                    {error}
                </div>
            )}

            {isLoading ? (
                <div className="text-slate-500 animate-pulse text-center py-12">Loading configurations...</div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {commandSets.map((set) => (
                        <div
                            key={set._id}
                            className="bg-white p-6 rounded-lg border border-slate-200 hover:border-slate-300 transition shadow-sm flex flex-col justify-between relative group"
                        >
                            <button
                                onClick={() => set._id && handleDelete(set._id, set.name)}
                                className="absolute top-3 right-3 text-slate-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                                title="Delete this command set"
                            >
                                🗑️
                            </button>

                            <div>
                                <div className="flex justify-between items-start mb-2 pr-6">
                                    <h3 className="text-lg font-bold text-slate-800">{set.name}</h3>
                                    {set.version && (
                                        <span className="bg-slate-100 text-xs px-2 py-1 rounded text-slate-600 font-mono">
                                            v{set.version}
                                        </span>
                                    )}
                                </div>
                                <p className="text-slate-600 text-sm mb-4 h-10 overflow-hidden text-ellipsis">
                                    {set.description || 'No description provided.'}
                                </p>
                            </div>

                            <div className="flex gap-2 mt-auto pt-4 border-t border-slate-200">
                                <button className="text-sm bg-slate-100 hover:bg-slate-200 text-slate-700 px-3 py-2 rounded flex-1 transition">
                                    View Commands
                                </button>
                                <button
                                    onClick={() => {
                                        setSelectedSetId(set._id || null);
                                        setIsImportModalOpen(true);
                                        setStatus('');
                                    }}
                                    className="text-sm bg-blue-100 hover:bg-blue-200 text-blue-700 px-3 py-2 rounded flex-1 transition"
                                >
                                    Smart Import
                                </button>
                            </div>
                        </div>
                    ))}

                    {commandSets.length === 0 && (
                        <div className="col-span-full text-center py-16 text-slate-500 bg-slate-50 rounded-lg border-2 border-dashed border-slate-300">
                            <p className="text-lg mb-2">No command sets found.</p>
                            <p className="text-sm">Create a new Command Set to start defining your system capabilities.</p>
                        </div>
                    )}
                </div>
            )}

            {/* Create Modal */}
            {isCreateModalOpen && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-lg p-6 w-full max-w-2xl border border-slate-300 shadow-lg max-h-[90vh] overflow-y-auto">
                        <h3 className="text-xl font-bold mb-4">New Command Set</h3>
                        <form onSubmit={handleCreateSubmit} className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium mb-1">Name *</label>
                                <input
                                    className="w-full bg-white border border-slate-300 rounded p-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    required
                                    placeholder="e.g., Membership Service, Linux Commands"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-1">Description</label>
                                <textarea
                                    className="w-full bg-white border border-slate-300 rounded p-2 focus:ring-2 focus:ring-blue-500 outline-none h-20"
                                    value={desc}
                                    onChange={(e) => setDesc(e.target.value)}
                                    placeholder="Brief description of this command set..."
                                />
                            </div>

                            <div className="border-t border-slate-200 pt-4">
                                <label className="block text-sm font-medium mb-2 flex items-center gap-2">
                                    📄 Documentation (Optional)
                                </label>
                                <div className="bg-blue-50 text-blue-900 p-3 rounded text-xs mb-2 border border-blue-200">
                                    Paste any format of technical documentation. AI will automatically extract all commands/APIs.
                                </div>

                                <textarea
                                    className="w-full bg-white border border-slate-300 rounded p-3 focus:ring-2 focus:ring-blue-500 outline-none text-slate-800 font-mono text-sm h-32"
                                    value={docContent}
                                    onChange={(e) => setDocContent(e.target.value)}
                                    placeholder="Paste documentation here (optional)...

Examples:
- OpenAPI/Swagger YAML
- API documentation in Markdown
- Command --help output
- Or simply describe: 'I have three commands: create_user, delete_user, list_users...'"
                                />
                            </div>

                            {status && (
                                <div className={`text-sm p-2 rounded ${status.includes('❌') ? 'text-red-700 bg-red-100' : 'text-green-700 bg-green-100'}`}>
                                    {status}
                                </div>
                            )}

                            <div className="flex justify-end gap-3 pt-4">
                                <button
                                    type="button"
                                    onClick={() => setIsCreateModalOpen(false)}
                                    className="px-4 py-2 hover:bg-slate-100 rounded"
                                    disabled={status.includes('Creating') || status.includes('Analyzing')}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={status.includes('Creating') || status.includes('Analyzing')}
                                    className="px-6 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {status.includes('Creating') || status.includes('Analyzing') ? status : 'Create & Import'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Import Modal */}
            {isImportModalOpen && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-lg p-6 w-full max-w-2xl border border-slate-300 shadow-lg flex flex-col h-[80vh]">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-xl font-bold flex items-center gap-2">
                                Smart Import
                            </h3>
                            <button
                                onClick={() => setIsImportModalOpen(false)}
                                className="text-slate-400 hover:text-slate-600 text-2xl"
                            >
                                ✕
                            </button>
                        </div>

                        <div className="bg-blue-50 text-blue-900 p-4 rounded text-sm mb-4 border border-blue-200">
                            <p className="font-semibold mb-1">Paste any format of documentation, AI will intelligently extract commands!</p>
                            <p className="text-xs opacity-90">Supported formats: OpenAPI YAML, Markdown documents, Man Pages, plain text descriptions...</p>
                        </div>

                        <form onSubmit={handleImportSubmit} className="flex flex-col flex-1">
                            <textarea
                                className="flex-1 w-full bg-white border border-slate-300 rounded p-4 font-mono text-sm text-slate-800 focus:ring-2 focus:ring-blue-500 outline-none resize-none mb-4"
                                value={docContent}
                                onChange={(e) => setDocContent(e.target.value)}
                                placeholder="Paste any format documentation here...

Example:
- OpenAPI YAML definition
- Bash script --help output
- API documentation in Markdown
- Or simply describe: 'I have three commands: add_user, delete_user, list_users...'"
                            />

                            <div className="flex justify-between items-center">
                                <span className={`text-sm ${status.includes('Error') || status.includes('❌') ? 'text-red-600' : 'text-green-600'}`}>
                                    {status}
                                </span>
                                <div className="flex gap-3">
                                    <button
                                        type="button"
                                        onClick={() => setIsImportModalOpen(false)}
                                        className="px-4 py-2 hover:bg-slate-100 rounded"
                                    >
                                        Close
                                    </button>
                                    <button
                                        type="submit"
                                        disabled={status.includes('Analyzing') || !docContent}
                                        className="px-6 py-2 bg-green-600 hover:bg-green-700 rounded text-white font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        {status.includes('Analyzing') ? 'Analyzing...' : 'Smart Import'}
                                    </button>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default CommandSets;
