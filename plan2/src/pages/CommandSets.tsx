import { useState, useEffect } from 'react';
import { api } from '../lib/api';

interface CommandSet {
    _id?: string;
    name: string;
    description?: string;
    version?: string;
    storageStatus?: {
        docintel?: boolean;
        local?: boolean;
    };
}

interface Command {
    _id?: string;
    command: string;
    summary: string;
    description?: string;
    riskLevel?: string;
    response_schema?: any;
}

interface CommandIndexStatus {
    exists: boolean;
    index_name: string;
    command_docs: number;
    mcp_tool_docs: number;
    total_docs: number;
    index_version: string;
    enabled?: boolean;
    reason?: string;
    docintel_enabled?: boolean;
    docintel?: {
        enabled?: boolean;
        base_url?: string;
    };
    local_retrieval?: {
        enabled?: boolean;
        backend?: string;
        reason?: string;
        exists?: boolean;
        total_docs?: number;
        command_docs?: number;
        mcp_tool_docs?: number;
        vector_docs?: number;
        vector_enabled?: boolean;
        embedding_model?: string;
        embedding_base_url?: string;
        embedding_healthy?: boolean;
    };
}

const CommandSets = () => {
    const [commandSets, setCommandSets] = useState<CommandSet[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState('');
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
    const [isImportModalOpen, setIsImportModalOpen] = useState(false);
    const [isViewCommandsModalOpen, setIsViewCommandsModalOpen] = useState(false);
    const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
    const [selectedSetName, setSelectedSetName] = useState('');

    const [name, setName] = useState('');
    const [desc, setDesc] = useState('');
    const [docContent, setDocContent] = useState('');
    const [status, setStatus] = useState('');
    const [docFile, setDocFile] = useState<File | null>(null);

    const [commands, setCommands] = useState<Command[]>([]);
    const [isCommandsLoading, setIsCommandsLoading] = useState(false);
    const [indexStatus, setIndexStatus] = useState<CommandIndexStatus | null>(null);
    const [adminStatus, setAdminStatus] = useState('');

    useEffect(() => {
        loadCommandSets();
        loadIndexStatus();
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

    const loadIndexStatus = async () => {
        try {
            const res = await api.get<CommandIndexStatus>('/command-index/status');
            setIndexStatus(res.data);
        } catch (err) {
            setIndexStatus(null);
        }
    };

    const handleRebuildIndex = async () => {
        setAdminStatus('Rebuilding command index...');
        try {
            const res = await api.post('/command-index/rebuild');
            setAdminStatus(`✅ Rebuilt index. Deleted ${res.data.deleted_command_docs}, rebuilt ${res.data.rebuilt_command_docs}.`);
            await loadIndexStatus();
        } catch (err: any) {
            setAdminStatus(`❌ Rebuild failed: ${err.response?.data?.detail || err.message}`);
        }
    };

    const handleRefreshMcpIndex = async () => {
        setAdminStatus('Refreshing MCP index...');
        try {
            const res = await api.post('/command-index/refresh-mcp');
            setAdminStatus(`✅ Refreshed MCP index. Deleted ${res.data.deleted_mcp_docs}, indexed ${res.data.indexed_mcp_docs}.`);
            await loadIndexStatus();
        } catch (err: any) {
            setAdminStatus(`❌ Refresh failed: ${err.response?.data?.detail || err.message}`);
        }
    };

    const handleSyncMcpDocIntel = async () => {
        setAdminStatus('Syncing MCP tools to DocIntel...');
        try {
            const res = await api.post('/command-index/sync-mcp-docintel');
            setAdminStatus(`✅ Synced ${res.data.synced_mcp_docs} MCP tools to DocIntel.`);
            await loadIndexStatus();
        } catch (err: any) {
            setAdminStatus(`❌ DocIntel sync failed: ${err.response?.data?.detail || err.message}`);
        }
    };

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            setDocFile(file);
            try {
                const content = await file.text();
                setDocContent(content);
                setStatus('📄 File loaded successfully');
                setTimeout(() => setStatus(''), 2000);
            } catch (err) {
                setStatus('❌ Failed to read file');
            }
        }
    };

    const handleCreateSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setStatus('Creating...');

        try {
            const response = await api.post('/command-sets/', {
                name,
                description: desc,
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
                setDocFile(null);
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

    const handleViewCommands = async (setId: string, setName: string) => {
        setSelectedSetId(setId);
        setSelectedSetName(setName);
        setIsViewCommandsModalOpen(true);
        setIsCommandsLoading(true);

        try {
            const res = await api.get<Command[]>(`/command-sets/${setId}/commands`);
            setCommands(res.data);
        } catch (err: any) {
            setError(`Failed to load commands: ${err.message}`);
            setCommands([]);
        } finally {
            setIsCommandsLoading(false);
        }
    };

    return (
        <div className="max-w-6xl mx-auto p-6">
            <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold">Command Sets Configuration</h2>
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => loadIndexStatus()}
                        className="rounded bg-slate-200 px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-300"
                    >
                        Refresh Status
                    </button>
                    <button
                        onClick={handleRebuildIndex}
                        className="rounded bg-amber-500 px-4 py-2 text-sm text-white transition hover:bg-amber-600"
                    >
                        Rebuild Index
                    </button>
                    <button
                        onClick={handleRefreshMcpIndex}
                        className="rounded bg-purple-600 px-4 py-2 text-sm text-white transition hover:bg-purple-700"
                    >
                        Refresh MCP Index
                    </button>
                    <button
                        onClick={handleSyncMcpDocIntel}
                        className="rounded bg-emerald-600 px-4 py-2 text-sm text-white transition hover:bg-emerald-700"
                    >
                        Sync MCP To DocIntel
                    </button>
                    <button
                        onClick={() => setIsCreateModalOpen(true)}
                        className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded transition flex items-center gap-2 text-white"
                    >
                        <span>+</span> New Command Set
                    </button>
                </div>
            </div>

            <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-2 flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-800">Command Retrieval</div>
                    {indexStatus && (
                        <span className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-600">
                            {indexStatus.docintel?.enabled ? 'docintel' : 'unavailable'}
                        </span>
                    )}
                </div>
                {indexStatus ? (
                    <div className="space-y-4 text-sm text-slate-600">
                        <div className="rounded border border-slate-200 bg-slate-50 p-3">
                            <div className="mb-2 flex items-center justify-between">
                                <div className="font-semibold text-slate-800">DocIntel Command Retrieval</div>
                                <span className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-600">
                                    {indexStatus.docintel?.enabled ? 'docintel' : 'unavailable'}
                                </span>
                            </div>
                            <div className="grid gap-2 md:grid-cols-4">
                                <div>Enabled: {indexStatus.docintel?.enabled ? 'yes' : 'no'}</div>
                                <div>Connected by: command-set `D` badge</div>
                                <div>Base URL: {indexStatus.docintel?.base_url || '-'}</div>
                                <div>Primary backend: yes</div>
                            </div>
                        </div>

                        <div className="rounded border border-slate-200 bg-white p-3">
                            <div className="mb-2 flex items-center justify-between">
                                <div className="font-semibold text-slate-800">Full Inventory Fallback</div>
                                <span className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-600">
                                    mongo commands
                                </span>
                            </div>
                            <div className="grid gap-2 md:grid-cols-4">
                                <div>DocIntel enabled: {indexStatus.docintel_enabled ? 'yes' : 'no'}</div>
                                <div>Local retrieval: disabled for now</div>
                                <div>Local ES: {indexStatus.enabled === false ? 'disabled' : 'enabled'}</div>
                                <div>Inventory fallback: always available</div>
                            </div>
                            {indexStatus.reason && (
                                <div className="mt-2 text-amber-700">{indexStatus.reason}</div>
                            )}
                        </div>
                    </div>
                ) : (
                    <div className="text-sm text-slate-500">Index status unavailable.</div>
                )}
                {adminStatus && (
                    <div className="mt-3 text-sm text-slate-700">{adminStatus}</div>
                )}
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
                                    <div className="flex items-center gap-2">
                                        {set.storageStatus?.docintel && (
                                            <span
                                                className="bg-slate-100 text-xs px-2 py-1 rounded text-slate-700 font-mono"
                                                title="Available in DocIntel command corpus"
                                            >
                                                D
                                            </span>
                                        )}
                                        {set.version && (
                                            <span className="bg-slate-100 text-xs px-2 py-1 rounded text-slate-600 font-mono">
                                                v{set.version}
                                            </span>
                                        )}
                                    </div>
                                </div>
                                <p className="text-slate-600 text-sm mb-4 h-10 overflow-hidden text-ellipsis">
                                    {set.description || 'No description provided.'}
                                </p>
                            </div>

                            <div className="flex gap-2 mt-auto pt-4 border-t border-slate-200">
                                <button
                                    onClick={() => handleViewCommands(set._id || '', set.name)}
                                    className="text-sm bg-slate-100 hover:bg-slate-200 text-slate-700 px-3 py-2 rounded flex-1 transition">
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
                                <div className="bg-blue-50 text-blue-900 p-3 rounded text-xs mb-3 border border-blue-200">
                                    Upload a file or paste documentation. AI will automatically extract all commands/APIs.
                                </div>

                                {/* File Upload */}
                                <div className="mb-3">
                                    <label className="flex items-center justify-center w-full px-4 py-3 border-2 border-dashed border-slate-300 rounded-lg cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition">
                                        <div className="flex flex-col items-center justify-center">
                                            <span className="text-2xl mb-1">📤</span>
                                            <span className="text-sm text-slate-600">
                                                {docFile ? `📁 ${docFile.name}` : 'Click to upload or drag file'}
                                            </span>
                                        </div>
                                        <input
                                            type="file"
                                            accept=".yaml,.yml,.json,.md,.txt,.openapi"
                                            onChange={handleFileChange}
                                            className="hidden"
                                        />
                                    </label>
                                </div>

                                {/* Or Paste */}
                                <div className="text-sm text-slate-500 text-center mb-2">or paste content below:</div>
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
                            <p className="font-semibold mb-1">Upload or paste documentation, AI will intelligently extract commands!</p>
                            <p className="text-xs opacity-90">Supported formats: OpenAPI YAML, Markdown documents, Man Pages, plain text descriptions...</p>
                        </div>

                        <form onSubmit={handleImportSubmit} className="flex flex-col flex-1">
                            {/* File Upload in Import Modal */}
                            <div className="mb-3">
                                <label className="flex items-center justify-center w-full px-4 py-3 border-2 border-dashed border-slate-300 rounded-lg cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition">
                                    <div className="flex flex-col items-center justify-center">
                                        <span className="text-2xl mb-1">📤</span>
                                        <span className="text-sm text-slate-600">
                                            {docFile ? `📁 ${docFile.name}` : 'Click to upload file'}
                                        </span>
                                    </div>
                                    <input
                                        type="file"
                                        accept=".yaml,.yml,.json,.md,.txt,.openapi"
                                        onChange={handleFileChange}
                                        className="hidden"
                                    />
                                </label>
                            </div>

                            <div className="text-sm text-slate-500 text-center mb-2">or paste content below:</div>
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

            {/* View Commands Modal */}
            {isViewCommandsModalOpen && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-lg p-6 w-full max-w-4xl border border-slate-300 shadow-lg flex flex-col h-[80vh]">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-xl font-bold">
                                Commands in "{selectedSetName}"
                            </h3>
                            <button
                                onClick={() => setIsViewCommandsModalOpen(false)}
                                className="text-slate-400 hover:text-slate-600 text-2xl"
                            >
                                ✕
                            </button>
                        </div>

                        <div className="flex-1 overflow-y-auto">
                            {isCommandsLoading ? (
                                <div className="flex items-center justify-center h-full text-slate-500">
                                    <p>Loading commands...</p>
                                </div>
                            ) : commands.length === 0 ? (
                                <div className="flex items-center justify-center h-full text-slate-500">
                                    <p>No commands found in this command set.</p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {commands.map((cmd) => (
                                        <div
                                            key={cmd._id}
                                            className="border border-slate-200 rounded-lg p-4 hover:border-slate-300 transition"
                                        >
                                            <div className="flex justify-between items-start mb-2">
                                                <div className="flex-1">
                                                    <div className="font-mono font-semibold text-blue-700">
                                                        {cmd.command}
                                                    </div>
                                                    <div className="text-sm text-slate-700 mt-1">
                                                        {cmd.summary}
                                                    </div>
                                                </div>
                                                {cmd.riskLevel && (
                                                    <span
                                                        className={`text-xs px-2 py-1 rounded whitespace-nowrap ml-2 font-medium ${
                                                            cmd.riskLevel === 'high'
                                                                ? 'bg-red-100 text-red-700'
                                                                : cmd.riskLevel === 'critical'
                                                                  ? 'bg-red-200 text-red-800'
                                                                  : 'bg-green-100 text-green-700'
                                                        }`}
                                                    >
                                                        {cmd.riskLevel.toUpperCase()}
                                                    </span>
                                                )}
                                            </div>

                                            {cmd.description && (
                                                <p className="text-xs text-slate-600 mb-2">{cmd.description}</p>
                                            )}

                                            {cmd.response_schema && (
                                                <div className="text-xs bg-slate-50 p-2 rounded border border-slate-200 text-slate-600">
                                                    <span className="font-semibold">Response:</span>{' '}
                                                    <span className="font-mono">
                                                        {cmd.response_schema.type}
                                                        {cmd.response_schema.wrapper ? ` (${cmd.response_schema.wrapper})` : ''}
                                                    </span>
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div className="flex justify-end gap-2 mt-4 pt-4 border-t border-slate-200">
                            <button
                                onClick={() => setIsViewCommandsModalOpen(false)}
                                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded transition"
                            >
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default CommandSets;
