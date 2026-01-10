import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useTask, MCPServerInfo } from '../contexts/TaskContext';

const MCPSelector: React.FC = () => {
  const { selectedMcp, setSelectedMcp, availableMcps, setAvailableMcps } = useTask();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load available MCP servers on component mount
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

        setAvailableMcps(mcpServers);

        // Auto-select first running MCP
        const runningMcp = mcpServers.find(m => m.status === 'running');
        if (runningMcp && !selectedMcp) {
          setSelectedMcp(runningMcp.name);
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load MCP servers');
        console.error('Error loading MCP servers:', err);
      } finally {
        setLoading(false);
      }
    };

    loadMCPs();
  }, [setAvailableMcps, setSelectedMcp, selectedMcp]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running':
        return 'bg-green-100 text-green-800 border-green-300';
      case 'stopped':
        return 'bg-gray-100 text-gray-800 border-gray-300';
      case 'error':
        return 'bg-red-100 text-red-800 border-red-300';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-300';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running':
        return '🟢';
      case 'stopped':
        return '⚪';
      case 'error':
        return '🔴';
      default:
        return '⚪';
    }
  };

  return (
    <div className="bg-white p-4 border-b border-slate-200 rounded-lg">
      <div className="flex items-center gap-4">
        <label className="text-sm font-semibold text-slate-700 whitespace-nowrap">
          Select MCP:
        </label>

        {loading ? (
          <div className="text-sm text-slate-500">Loading MCPs...</div>
        ) : error ? (
          <div className="text-sm text-red-500">{error}</div>
        ) : availableMcps.length === 0 ? (
          <div className="text-sm text-slate-500">No MCPs available</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {availableMcps.map((mcp) => (
              <button
                key={mcp.name}
                onClick={() => setSelectedMcp(mcp.name)}
                disabled={mcp.status !== 'running'}
                className={`px-3 py-2 rounded-lg border-2 transition-all ${
                  selectedMcp === mcp.name
                    ? 'ring-2 ring-blue-500 border-blue-500'
                    : 'border-slate-200 hover:border-slate-300'
                } ${
                  mcp.status !== 'running'
                    ? 'opacity-50 cursor-not-allowed'
                    : 'cursor-pointer'
                } ${getStatusColor(mcp.status)}`}
                title={`${mcp.description} (${mcp.status})`}
              >
                <span className="mr-1">{getStatusIcon(mcp.status)}</span>
                {mcp.name} ({mcp.tools.length} tools)
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedMcp && availableMcps.length > 0 && (
        <div className="mt-3 text-xs text-slate-600">
          {availableMcps.find(m => m.name === selectedMcp)?.description}
        </div>
      )}
    </div>
  );
};

export default MCPSelector;
