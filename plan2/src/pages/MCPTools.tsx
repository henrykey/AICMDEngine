import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { MCPToolInfo, MCPServerInfo } from '../contexts/TaskContext';

const MCPTools = () => {
  const [mcps, setMcps] = useState<MCPServerInfo[]>([]);
  const [selectedMcp, setSelectedMcp] = useState<string | null>(null);
  const [selectedTool, setSelectedTool] = useState<MCPToolInfo | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load MCP list on component mount
  useEffect(() => {
    const loadMCPs = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.get<{ success?: boolean; servers?: any[] }>(
          '/v1/mcp/servers'
        );

        // Handle both response formats
        const servers = response.data.servers || response.data.data || [];

        // Transform the response to match MCPServerInfo interface
        const mcpServers: MCPServerInfo[] = servers.map((server: any) => ({
          name: server.name,
          version: server.metadata?.version || server.version || '1.0',
          description: server.metadata?.description || server.description || `${server.name} MCP Server`,
          status: (server.status || 'stopped') as 'running' | 'stopped' | 'error',
          tools: server.tools || []
        }));

        setMcps(mcpServers);
        if (mcpServers.length > 0) {
          setSelectedMcp(mcpServers[0].name);
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load MCP servers');
        console.error('Error loading MCP servers:', err);
      } finally {
        setLoading(false);
      }
    };

    loadMCPs();
  }, []);

  const currentMcp = mcps.find(m => m.name === selectedMcp);
  const tools = currentMcp?.tools || [];

  // Filter tools based on search query
  const filteredTools = tools.filter(tool =>
    tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    tool.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getStatusBadge = (status: string) => {
    const statusConfig: Record<string, { icon: string; color: string }> = {
      running: { icon: '🟢', color: 'bg-green-100 text-green-800' },
      stopped: { icon: '⚪', color: 'bg-gray-100 text-gray-800' },
      error: { icon: '🔴', color: 'bg-red-100 text-red-800' }
    };
    const config = statusConfig[status] || statusConfig.stopped;
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${config.color}`}>
        {config.icon} {status}
      </span>
    );
  };

  return (
    <div className="flex flex-col gap-6 h-full p-6 bg-slate-50">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-800">MCP Tools Browser</h1>
        <p className="text-sm text-slate-600 mt-1">
          Browse and explore MCP tools from available MCP servers
        </p>
      </div>

      {/* Main Content */}
      <div className="flex gap-6 flex-1 overflow-hidden">
        {/* Left Panel: MCP Servers List */}
        <div className="w-64 bg-white rounded-lg border border-slate-200 p-4 flex flex-col gap-4 overflow-hidden shadow-sm">
          <h2 className="font-semibold text-slate-800">MCP Servers</h2>

          {loading ? (
            <div className="text-sm text-slate-500">Loading...</div>
          ) : error ? (
            <div className="text-sm text-red-500">{error}</div>
          ) : mcps.length === 0 ? (
            <div className="text-sm text-slate-500">No MCP servers available</div>
          ) : (
            <div className="space-y-2 overflow-auto flex-1">
              {mcps.map((mcp) => (
                <button
                  key={mcp.name}
                  onClick={() => {
                    setSelectedMcp(mcp.name);
                    setSelectedTool(null);
                    setSearchQuery('');
                  }}
                  disabled={mcp.status !== 'running'}
                  className={`w-full text-left px-3 py-2 rounded-lg border-2 transition-all ${
                    selectedMcp === mcp.name
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-slate-200 hover:border-slate-300'
                  } ${
                    mcp.status !== 'running'
                      ? 'opacity-50 cursor-not-allowed'
                      : 'cursor-pointer'
                  }`}
                  title={mcp.description}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm text-slate-800 truncate">
                        {mcp.name}
                      </div>
                      <div className="text-xs text-slate-600 truncate">
                        v{mcp.version} • {mcp.tools.length} tools
                      </div>
                    </div>
                    <div className="text-xs flex-shrink-0">
                      {mcp.status === 'running' ? '🟢' : mcp.status === 'stopped' ? '⚪' : '🔴'}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Middle Panel: Tools List */}
        <div className="w-72 bg-white rounded-lg border border-slate-200 p-4 flex flex-col gap-4 overflow-hidden shadow-sm">
          <div>
            <h2 className="font-semibold text-slate-800 mb-3">Tools</h2>
            <input
              type="text"
              placeholder="Search tools..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {currentMcp ? (
            <div className="space-y-2 overflow-auto flex-1">
              {filteredTools.length === 0 ? (
                <div className="text-sm text-slate-500">
                  {searchQuery ? 'No tools match your search' : 'No tools available'}
                </div>
              ) : (
                filteredTools.map((tool) => (
                  <button
                    key={tool.name}
                    onClick={() => setSelectedTool(tool)}
                    className={`w-full text-left px-3 py-2 rounded-lg border-2 transition-all ${
                      selectedTool?.name === tool.name
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-slate-200 hover:border-slate-300'
                    } cursor-pointer`}
                  >
                    <div className="font-medium text-sm text-slate-800">
                      {tool.name}
                    </div>
                    <div className="text-xs text-slate-600 line-clamp-2">
                      {tool.description}
                    </div>
                  </button>
                ))
              )}
            </div>
          ) : (
            <div className="text-sm text-slate-500">Select an MCP server</div>
          )}
        </div>

        {/* Right Panel: Tool Details */}
        <div className="flex-1 bg-white rounded-lg border border-slate-200 p-4 flex flex-col gap-4 overflow-hidden shadow-sm">
          {selectedTool ? (
            <>
              {/* Tool Header */}
              <div className="border-b border-slate-200 pb-4">
                <h3 className="text-lg font-semibold text-slate-800">
                  {selectedTool.name}
                </h3>
                <p className="text-sm text-slate-600 mt-2">
                  {selectedTool.description}
                </p>
                {currentMcp && (
                  <div className="mt-2 text-xs text-slate-500">
                    From: <span className="font-medium">{currentMcp.name}</span>
                  </div>
                )}
              </div>

              {/* Input Schema */}
              <div className="flex-1 overflow-auto">
                <h4 className="font-medium text-slate-800 mb-3">Input Schema</h4>
                <pre className="bg-slate-100 p-4 rounded-lg text-xs overflow-auto border border-slate-300 font-mono">
                  {JSON.stringify(selectedTool.input_schema, null, 2)}
                </pre>
              </div>

              {/* Footer Actions */}
              <div className="border-t border-slate-200 pt-4 mt-auto">
                <p className="text-xs text-slate-500 mb-3">
                  Use this tool in the Task Playground by selecting the MCP server and describing your task.
                </p>
                <div className="flex gap-2">
                  <button
                    className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 transition-colors text-sm"
                    onClick={() => {
                      // Copy tool name to clipboard
                      navigator.clipboard.writeText(selectedTool.name);
                      alert('Tool name copied to clipboard!');
                    }}
                  >
                    Copy Name
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-slate-500 text-center">
              <div>
                <p className="text-sm">Select a tool to view details</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default MCPTools;
