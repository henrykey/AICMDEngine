import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';

interface CommandSet {
    _id?: string;
    name: string;
    description?: string;
    version: string;
}

export default function CommandSets() {
    const queryClient = useQueryClient();
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
    const [isImportModalOpen, setIsImportModalOpen] = useState(false);
    const [selectedSetId, setSelectedSetId] = useState<string | null>(null);

    const [name, setName] = useState('');
    const [desc, setDesc] = useState('');
    const [createDocContent, setCreateDocContent] = useState('');
    const [docContent, setDocContent] = useState('');
    const [importStatus, setImportStatus] = useState('');
    const [createStatus, setCreateStatus] = useState('');

    const { data: commandSets, isLoading } = useQuery({
        queryKey: ['command-sets'],
        queryFn: async () => {
            const res = await api.get<CommandSet[]>('/command-sets/');
            return res.data;
        }
    });

    const importMutation = useMutation({
        mutationFn: async ({ setId, document }: { setId: string, document: string }) => {
            const response = await api.post(`/command-sets/${setId}/import/smart`, {
                document
            });
            return response.data;
        },
        onSuccess: (data: any) => {
            setImportStatus(`✅ Success! Extracted ${data.commands_extracted} commands.`);
            setTimeout(() => {
                setIsImportModalOpen(false);
                setImportStatus('');
                setDocContent('');
            }, 2000);
        },
        onError: (err: any) => {
            setImportStatus(`❌ Error: ${err.response?.data?.detail || err.message}`);
        }
    });

    const deleteMutation = useMutation({
        mutationFn: async (setId: string) => {
            return api.delete(`/command-sets/${setId}`);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['command-sets'] });
        }
    });

    const handleCreateSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setCreateStatus('Creating...');

        try {
            const response = await api.post('/command-sets/', {
                name,
                description: desc,
                tenant_id: "auto-filled",
                source_type: "manual"
            });

            const newSetId = response.data._id;

            if (createDocContent.trim()) {
                setCreateStatus('🧠 AI is analyzing documentation...');
                await api.post(`/command-sets/${newSetId}/import/smart`, {
                    document: createDocContent
                });
                setCreateStatus('✅ Created and imported successfully!');
            } else {
                setCreateStatus('✅ Command Set created!');
            }

            queryClient.invalidateQueries({ queryKey: ['command-sets'] });

            setTimeout(() => {
                setIsCreateModalOpen(false);
                setName('');
                setDesc('');
                setCreateDocContent('');
                setCreateStatus('');
            }, 1500);

        } catch (error: any) {
            setCreateStatus(`❌ Error: ${error.response?.data?.detail || error.message}`);
        }
    };

    const handleImportSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!docContent.trim()) {
            setImportStatus('❌ Please paste documentation content');
            return;
        }

        if (selectedSetId) {
            setImportStatus('🧠 AI is analyzing the documentation...');
            importMutation.mutate({ setId: selectedSetId, document: docContent });
        }
    };

    const openImport = (setId: string) => {
        setSelectedSetId(setId);
        setIsImportModalOpen(true);
        setImportStatus('');
    };

    const handleDelete = (setId: string, name: string) => {
        if (confirm(`确定要删除 "${name}" 吗？\n\n此操作会同时删除该命令集下的所有命令，且无法恢复。`)) {
            deleteMutation.mutate(setId);
        }
    };

    return (
        <div className="max-w-6xl mx-auto">
            <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
                    Command Sets Configuration
                </h2>
                <button
                    onClick={() => setIsCreateModalOpen(true)}
                    className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded transition flex items-center gap-2"
                >
                    <span>+</span> New Command Set
                </button>
            </div>

            {isLoading ? (
                <div className="text-gray-500 animate-pulse">Loading configurations...</div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {commandSets?.map((set) => (
                        <div key={set._id} className="bg-gray-800 p-6 rounded-lg border border-gray-700 hover:border-gray-500 transition shadow-lg flex flex-col justify-between relative group">
                            <button
                                onClick={() => set._id && handleDelete(set._id, set.name)}
                                className="absolute top-2 right-2 text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                                title="删除此命令集"
                            >
                                🗑️
                            </button>

                            <div>
                                <div className="flex justify-between items-start mb-3 pr-8">
                                    <h3 className="text-lg font-bold text-gray-100">{set.name}</h3>
                                    <span className="bg-gray-700 text-xs px-2 py-1 rounded text-blue-300 font-mono">
                                        v{set.version}
                                    </span>
                                </div>
                                <p className="text-gray-400 text-sm mb-6 h-10 overflow-hidden text-ellipsis">
                                    {set.description || "No description provided."}
                                </p>
                            </div>

                            <div className="flex gap-2 mt-auto pt-4 border-t border-gray-700/50">
                                <button
                                    className="text-sm bg-gray-700 hover:bg-gray-600 text-gray-200 px-3 py-2 rounded flex-1 transition"
                                    onClick={() => alert("View Commands - Coming Soon")}
                                >
                                    View Commands
                                </button>
                                <button
                                    className="text-sm bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 text-white px-3 py-2 rounded flex-1 transition"
                                    onClick={() => set._id && openImport(set._id)}
                                >
                                    🧠 Smart Import
                                </button>
                            </div>
                        </div>
                    ))}

                    {commandSets?.length === 0 && (
                        <div className="col-span-full text-center py-16 text-gray-500 bg-gray-800/30 rounded-xl border-2 border-dashed border-gray-700">
                            <p className="text-lg mb-2">No configuration sets found.</p>
                            <p className="text-sm">Create a new Command Set to start defining your system capabilities.</p>
                        </div>
                    )}
                </div>
            )}

            {isCreateModalOpen && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-gray-800 rounded-xl p-6 w-full max-w-3xl border border-gray-600 shadow-2xl max-h-[90vh] overflow-y-auto">
                        <h3 className="text-xl font-bold mb-4 text-white">New Command Set</h3>
                        <form onSubmit={handleCreateSubmit} className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium mb-1 text-gray-300">Name *</label>
                                <input
                                    className="w-full bg-gray-900 border border-gray-600 rounded p-2 focus:ring-2 focus:ring-blue-500 outline-none text-white"
                                    value={name}
                                    onChange={e => setName(e.target.value)}
                                    required
                                    placeholder="e.g., Membership Service, Linux Commands"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-1 text-gray-300">Description</label>
                                <textarea
                                    className="w-full bg-gray-900 border border-gray-600 rounded p-2 focus:ring-2 focus:ring-blue-500 outline-none text-white h-20"
                                    value={desc}
                                    onChange={e => setDesc(e.target.value)}
                                    placeholder="Brief description of this command set..."
                                />
                            </div>

                            <div className="border-t border-gray-700 pt-4">
                                <label className="block text-sm font-medium mb-2 text-gray-300 flex items-center gap-2">
                                    📄 Documentation (Optional)
                                    <span className="text-xs bg-purple-600 px-2 py-0.5 rounded">AI-Powered</span>
                                </label>
                                <div className="bg-blue-900/20 text-blue-200 p-3 rounded text-xs mb-2 border border-blue-700/50">
                                    粘贴任意格式的技术文档，AI 会自动提取所有命令/API。
                                    支持：OpenAPI YAML、Markdown、Man Pages、纯文本说明等。
                                </div>

                                <div className="flex gap-2 mb-2">
                                    <input
                                        type="file"
                                        id="doc-file-input"
                                        className="hidden"
                                        accept=".yaml,.yml,.md,.txt,.json"
                                        onChange={(e) => {
                                            const file = e.target.files?.[0];
                                            if (file) {
                                                const reader = new FileReader();
                                                reader.onload = (event) => {
                                                    setCreateDocContent(event.target?.result as string);
                                                };
                                                reader.readAsText(file);
                                            }
                                        }}
                                    />
                                    <button
                                        type="button"
                                        onClick={() => document.getElementById('doc-file-input')?.click()}
                                        className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded text-sm transition flex items-center gap-2"
                                    >
                                        📁 选择文件
                                    </button>
                                    <span className="text-xs text-gray-400 self-center">或直接粘贴到下方 ↓</span>
                                </div>

                                <textarea
                                    className="w-full bg-gray-950 border border-gray-600 rounded p-3 focus:ring-2 focus:ring-purple-500 outline-none text-green-400 font-mono text-sm h-48"
                                    value={createDocContent}
                                    onChange={e => setCreateDocContent(e.target.value)}
                                    placeholder={`粘贴文档到这里（可选）...

示例：
- OpenAPI/Swagger YAML 完整定义
- API 文档的 Markdown
- 命令的 --help 输出
- 或简单描述："我有三个命令：create_user, delete_user, list_users..."`}
                                />
                            </div>

                            {createStatus && (
                                <div className={`text-sm p-2 rounded ${createStatus.includes('❌') ? 'text-red-400 bg-red-900/20' : 'text-green-400 bg-green-900/20'}`}>
                                    {createStatus}
                                </div>
                            )}

                            <div className="flex justify-end gap-3 pt-4">
                                <button
                                    type="button"
                                    onClick={() => setIsCreateModalOpen(false)}
                                    className="px-4 py-2 hover:bg-gray-700 rounded text-gray-300 transition"
                                    disabled={createStatus.includes('Creating') || createStatus.includes('analyzing')}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={createStatus.includes('Creating') || createStatus.includes('analyzing')}
                                    className="px-6 py-2 bg-blue-600 hover:bg-blue-500 rounded text-white font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {createStatus.includes('Creating') || createStatus.includes('analyzing') ? createStatus : 'Create & Import'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {isImportModalOpen && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-gray-800 rounded-xl p-6 w-full max-w-2xl border border-gray-600 shadow-2xl flex flex-col h-[80vh]">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-xl font-bold text-white flex items-center gap-2">
                                🧠 Smart Import
                                <span className="text-xs bg-purple-600 px-2 py-1 rounded">AI-Powered</span>
                            </h3>
                            <button
                                onClick={() => setIsImportModalOpen(false)}
                                className="text-gray-400 hover:text-white text-2xl"
                            >
                                ✕
                            </button>
                        </div>

                        <div className="bg-gradient-to-r from-blue-900/30 to-purple-900/30 text-blue-100 p-4 rounded text-sm mb-4 border border-blue-700/50">
                            <p className="font-semibold mb-2">✨ 粘贴任意格式的文档，由 AI 智能提取命令！</p>
                            <p className="text-xs opacity-90">支持格式：OpenAPI YAML、Markdown 文档、Man Pages、纯文本说明...</p>
                            <p className="text-xs opacity-90 mt-1">AI 会自动理解文档内容并提取所有可用的命令/API/操作。</p>
                        </div>

                        <textarea
                            className="flex-1 w-full bg-gray-950 border border-gray-700 rounded p-4 font-mono text-sm text-green-400 focus:ring-2 focus:ring-purple-500 outline-none resize-none mb-4"
                            value={docContent}
                            onChange={e => setDocContent(e.target.value)}
                            placeholder={`粘贴任意格式的文档到这里...

例如：
- OpenAPI YAML 完整定义
- Bash 脚本的 --help 输出
- API 文档的 Markdown
- 或者直接描述："我有三个命令：add_user, delete_user, list_users..."`}
                        />

                        <div className="flex justify-between items-center">
                            <span className={`text-sm ${importStatus.includes('Error') || importStatus.includes('❌') ? 'text-red-400' : 'text-green-400'}`}>
                                {importStatus}
                            </span>
                            <div className="flex gap-3">
                                <button
                                    type="button"
                                    onClick={() => setIsImportModalOpen(false)}
                                    className="px-4 py-2 hover:bg-gray-700 rounded text-gray-300 transition"
                                >
                                    Close
                                </button>
                                <button
                                    onClick={handleImportSubmit}
                                    disabled={importMutation.isPending || !docContent}
                                    className="px-6 py-2 bg-green-600 hover:bg-green-500 rounded text-white font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {importMutation.isPending ? 'Analyzing...' : 'Smart Import'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
