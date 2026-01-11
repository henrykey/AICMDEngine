import { useState, useEffect } from 'react';
import { getConfig } from '../../config';

interface MCPServer {
  _id?: string;
  name: string;
  type: 'builtin' | 'custom';
  endpoint: string;
  status: 'running' | 'stopped' | 'error';
  health_score?: number;
  last_heartbeat?: Date;
  tools_count?: number;
  commands_count?: number;
  metadata?: {
    description?: string;
    version?: string;
    author?: string;
    dependencies?: string[];
  };
}

const MCPManagement = () => {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);
  const [showDetails, setShowDetails] = useState(false);

  // 获取 MCP 服务器列表
  const fetchServers = async () => {
    try {
      setLoading(true);
      const config = getConfig();
      const apiUrl = `${config.nlTpsApiUrl}/mcp/servers`;
      const response = await fetch(apiUrl);
      if (!response.ok) {
        throw new Error(`Failed to fetch MCP servers: ${response.status} ${response.statusText}`);
      }
      const data = await response.json();
      setServers(data.servers || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchServers();
    // 设置定时刷新
    const interval = setInterval(fetchServers, 30000); // 每30秒刷新一次
    return () => clearInterval(interval);
  }, []);

  // 刷新服务器状态
  const refreshServerStatus = async (name: string) => {
    try {
      const config = getConfig();
      const apiUrl = `${config.nlTpsApiUrl}/mcp/servers/${name}/refresh`;
      const response = await fetch(apiUrl, { method: 'POST' });
      if (!response.ok) {
        throw new Error(`Failed to refresh server status: ${response.status} ${response.statusText}`);
      }
      await fetchServers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // 停止/启动服务器
  const toggleServer = async (name: string, action: 'start' | 'stop') => {
    try {
      const config = getConfig();
      const apiUrl = `${config.nlTpsApiUrl}/mcp/servers/${name}/${action}`;
      const response = await fetch(apiUrl, { method: 'POST' });
      if (!response.ok) {
        throw new Error(`Failed to ${action} server: ${response.status} ${response.statusText}`);
      }
      await fetchServers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // 删除服务器
  const deleteServer = async (name: string) => {
    if (!window.confirm(`Are you sure you want to delete ${name}?`)) return;

    try {
      const config = getConfig();
      const apiUrl = `${config.nlTpsApiUrl}/mcp/servers/${name}`;
      const response = await fetch(apiUrl, { method: 'DELETE' });
      if (!response.ok) {
        throw new Error(`Failed to delete server: ${response.status} ${response.statusText}`);
      }
      await fetchServers();
      setSelectedServer(null);
      setShowDetails(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // 获取状态颜色
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running':
        return 'bg-green-100 text-green-800';
      case 'stopped':
        return 'bg-gray-100 text-gray-800';
      case 'error':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  // 获取状态图标
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running':
        return '🟢';
      case 'stopped':
        return '⚫';
      case 'error':
        return '🔴';
      default:
        return '⚪';
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* 顶部 */}
      <div className="p-6 border-b border-slate-200">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
              <span>🔌</span> MCP Server Management
            </h2>
            <p className="text-sm text-slate-600 mt-1">
              Manage Model Context Protocol servers and monitor their health
            </p>
          </div>
          <button
            onClick={() => {
              // TODO: Implement add server functionality
              alert('Add server functionality to be implemented');
            }}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 transition"
          >
            + Add Server
          </button>
        </div>

        {error && (
          <div className="mt-4 p-3 bg-red-100 border border-red-300 text-red-700 rounded-lg text-sm">
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-2 font-bold text-red-700 hover:text-red-900"
            >
              ×
            </button>
          </div>
        )}
      </div>

      {/* 主内容区 */}
      <div className="flex-1 overflow-hidden flex">
        {/* 左侧：服务器列表 */}
        <div className="w-1/3 border-r border-slate-200 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <p className="text-slate-600">Loading MCP servers...</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-200">
              {servers.length === 0 ? (
                <div className="p-6 text-center text-slate-600">
                  <p>No MCP servers configured</p>
                  <p className="text-sm mt-2">Click "Add Server" to configure a new MCP server</p>
                </div>
              ) : (
                servers.map((server) => (
                  <div
                    key={server.name}
                    onClick={() => {
                      setSelectedServer(server);
                      setShowDetails(true);
                    }}
                    className="p-4 cursor-pointer transition-colors hover:bg-slate-50"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <h3 className="font-semibold text-slate-900">{server.name}</h3>
                        <p className="text-sm text-slate-600">
                          {server.type === 'builtin' ? 'Built-in' : 'Custom'} • {server.endpoint}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-1 text-xs rounded-full font-medium ${getStatusColor(server.status)}`}>
                          {getStatusIcon(server.status)} {server.status}
                        </span>
                      </div>
                    </div>

                    {server.health_score !== undefined && (
                      <div className="flex items-center gap-2 text-xs text-slate-600 mb-2">
                        <span>Health:</span>
                        <div className="flex items-center gap-1">
                          <div className="w-16 bg-gray-200 rounded-full h-2">
                            <div
                              className={`h-2 rounded-full ${
                                server.health_score >= 80 ? 'bg-green-500' :
                                server.health_score >= 50 ? 'bg-yellow-500' : 'bg-red-500'
                              }`}
                              style={{ width: `${server.health_score}%` }}
                            ></div>
                          </div>
                          <span>{server.health_score}%</span>
                        </div>
                      </div>
                    )}

                    {server.tools_count !== undefined && server.commands_count !== undefined && (
                      <div className="flex items-center gap-4 text-xs text-slate-600">
                        <span>🔧 {server.tools_count} tools</span>
                        <span>📋 {server.commands_count} commands</span>
                      </div>
                    )}

                    <div className="flex gap-2 pt-2 border-t border-slate-200">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          refreshServerStatus(server.name);
                        }}
                        className="flex-1 px-2 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 rounded transition"
                      >
                        Refresh
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleServer(server.name, server.status === 'running' ? 'stop' : 'start');
                        }}
                        className={`flex-1 px-2 py-1.5 text-xs font-medium rounded transition ${
                          server.status === 'running'
                            ? 'text-red-600 hover:bg-red-50'
                            : 'text-green-600 hover:bg-green-50'
                        }`}
                      >
                        {server.status === 'running' ? 'Stop' : 'Start'}
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* 右侧：详情面板 */}
        <div className="flex-1 overflow-y-auto p-6">
          {showDetails && selectedServer ? (
            <ServerDetails server={selectedServer} onDelete={deleteServer} onClose={() => setShowDetails(false)} getStatusColor={getStatusColor} getStatusIcon={getStatusIcon} refreshServerStatus={refreshServerStatus} toggleServer={toggleServer} />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-600">
              <div className="text-center">
                <span className="text-4xl mb-4 block">🔌</span>
                <p className="text-lg mb-2">MCP Server Management</p>
                <p className="text-sm">Select a server to view details and manage its configuration</p>
                <p className="text-sm mt-4">Servers will be automatically discovered and monitored</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// 服务器详情组件
interface ServerDetailsProps {
  server: MCPServer;
  onDelete: (name: string) => void;
  onClose: () => void;
  getStatusColor: (status: string) => string;
  getStatusIcon: (status: string) => string;
  refreshServerStatus: (name: string) => Promise<void>;
  toggleServer: (name: string, action: 'start' | 'stop') => Promise<void>;
}

const ServerDetails = ({ server, onDelete, onClose, getStatusColor, getStatusIcon, refreshServerStatus, toggleServer }: ServerDetailsProps) => (
  <div className="space-y-6">
    <div className="bg-slate-50 rounded-lg p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xl font-bold text-slate-900">{server.name}</h3>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(server.status)}`}>
            {getStatusIcon(server.status)} {server.status}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-semibold text-slate-700">Type</label>
          <p className="text-slate-900">{server.type === 'builtin' ? 'Built-in' : 'Custom'}</p>
        </div>
        <div>
          <label className="text-sm font-semibold text-slate-700">Endpoint</label>
          <p className="text-slate-900 font-mono text-sm break-all">{server.endpoint}</p>
        </div>
      </div>

      {server.metadata?.description && (
        <div>
          <label className="text-sm font-semibold text-slate-700">Description</label>
          <p className="text-slate-900">{server.metadata.description}</p>
        </div>
      )}

      {server.metadata?.version && (
        <div>
          <label className="text-sm font-semibold text-slate-700">Version</label>
          <p className="text-slate-900">{server.metadata.version}</p>
        </div>
      )}

      {server.tools_count !== undefined && (
        <div>
          <label className="text-sm font-semibold text-slate-700">Tools</label>
          <p className="text-slate-900">{server.tools_count} tools available</p>
        </div>
      )}

      {server.commands_count !== undefined && (
        <div>
          <label className="text-sm font-semibold text-slate-700">Commands</label>
          <p className="text-slate-900">{server.commands_count} commands registered</p>
        </div>
      )}

      {server.last_heartbeat && (
        <div>
          <label className="text-sm font-semibold text-slate-700">Last Heartbeat</label>
          <p className="text-slate-900">{new Date(server.last_heartbeat).toLocaleString()}</p>
        </div>
      )}

      {server.metadata?.dependencies && server.metadata.dependencies.length > 0 && (
        <div>
          <label className="text-sm font-semibold text-slate-700">Dependencies</label>
          <div className="flex flex-wrap gap-2 mt-2">
            {server.metadata.dependencies.map((dep, index) => (
              <span key={index} className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                {dep}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>

    <div className="flex gap-3">
      <button
        onClick={() => refreshServerStatus(server.name)}
        className="px-4 py-2 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 transition"
      >
        🔄 Refresh Status
      </button>
      <button
        onClick={() => toggleServer(server.name, server.status === 'running' ? 'stop' : 'start')}
        className={`px-4 py-2 rounded-lg font-medium transition ${
          server.status === 'running'
            ? 'bg-red-500 text-white hover:bg-red-600'
            : 'bg-green-500 text-white hover:bg-green-600'
        }`}
      >
        {server.status === 'running' ? '⏹️ Stop Server' : '▶️ Start Server'}
      </button>
      <button
        onClick={() => onDelete(server.name)}
        className="px-4 py-2 bg-red-500 text-white rounded-lg font-medium hover:bg-red-600 transition"
      >
        🗑️ Delete
      </button>
      <button
        onClick={onClose}
        className="px-4 py-2 bg-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-400 transition"
      >
        Close
      </button>
    </div>
  </div>
);

export default MCPManagement;