import { useState, useEffect } from 'react';
import { getConfig } from '../../config';
import ProviderList from './ProviderList';
import ProviderForm from './ProviderForm';
import TestProvider from './TestProvider';

interface LLMProvider {
  _id?: string;
  name: string;
  type: string;
  base_url: string;
  model: string;
  api_key_ref: string;
  timeout: number;
  temperature: number;
  max_tokens: number;
  top_p: number;
  cost_per_1k_tokens: number;
  priority: number;
  enabled: boolean;
  metadata?: {
    provider_name: string;
    region: string;
    max_qps: number;
  };
  // Capability detection fields
  capabilities?: string[];
  context_window?: number;
  supports_multimodal?: boolean;
  supported_formats?: string[];
  embedding_dimensions?: number | null;
  capabilities_detection_status?: 'pending' | 'detecting' | 'completed' | 'failed';
  capabilities_last_updated?: string;
  capabilities_detection_error?: string | null;
  is_current?: boolean;
  is_initialized?: boolean;
  capabilities_mode?: 'auto' | 'manual';
}

const LLMManagement = () => {
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<LLMProvider | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showTestPanel, setShowTestPanel] = useState(false);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);

  // 获取提供商列表
  const fetchProviders = async () => {
    try {
      setLoading(true);
      const config = getConfig();
      const apiUrl = `${config.nlTpsApiUrl.replace('/v1', '')}/api/llm/providers`;
      const response = await fetch(apiUrl);
      if (!response.ok) {
        throw new Error(`Failed to fetch providers: ${response.status} ${response.statusText}`);
      }
      const data = await response.json();
      setProviders(data.providers || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  // 获取选中的提供商
  const fetchSelectedProvider = async () => {
    try {
      const config = getConfig();
      const apiUrl = `${config.nlTpsApiUrl.replace('/v1', '')}/api/llm/current`;
      const response = await fetch(apiUrl);
      if (response.ok) {
        const data = await response.json();
        const selected = providers.find(p => p.name === data.name);
        setSelectedProvider(selected || null);
      }
    } catch (err) {
      console.error('Failed to fetch selected provider:', err);
    }
  };

  useEffect(() => {
    fetchProviders();
  }, []);

  useEffect(() => {
    if (providers.length > 0) {
      fetchSelectedProvider();
    }
  }, [providers]);

  // WebSocket连接以接收实时能力检测更新
  useEffect(() => {
    const config = getConfig();
    const wsUrl = `${config.nlTpsApiUrl.replace('/v1', '').replace('http', 'ws')}/api/llm/ws/notifications`;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected for capability detection updates');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // 处理能力检测状态更新
        if (data.type === 'capability_detection_status' || data.type === 'capability_update') {
          console.log('Capability detection update:', data);
          // 刷新提供商列表以显示最新状态
          fetchProviders();
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
    };

    // 发送ping保持连接
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);

    return () => {
      clearInterval(pingInterval);
      ws.close();
    };
  }, []);

  // 处理创建/更新提供商
  const handleSaveProvider = async (provider: LLMProvider) => {
    try {
      const config = getConfig();
      const baseUrl = config.nlTpsApiUrl.replace('/v1', '');
      const endpoint = provider._id ? `${provider.name}` : '';
      const url = `${baseUrl}/api/llm/providers${endpoint ? '/' + endpoint : ''}`;
      const method = provider._id ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(provider),
      });

      if (!response.ok) {
        throw new Error(`Failed to save provider: ${response.status} ${response.statusText}`);
      }

      await fetchProviders();
      setShowForm(false);
      setSelectedProvider(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // 处理删除提供商
  const handleDeleteProvider = async (name: string) => {
    if (!window.confirm(`Are you sure you want to delete ${name}?`)) return;

    try {
      const config = getConfig();
      const baseUrl = config.nlTpsApiUrl.replace('/v1', '');
      const url = `${baseUrl}/api/llm/providers/${name}`;
      const response = await fetch(url, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error(`Failed to delete provider: ${response.status} ${response.statusText}`);
      }

      await fetchProviders();
      setSelectedProvider(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // 处理选择/取消选择提供商
  const handleSelectProvider = async (name: string) => {
    try {
      const config = getConfig();
      const baseUrl = config.nlTpsApiUrl.replace('/v1', '');
      const url = `${baseUrl}/api/llm/providers/${name}/select`;
      const response = await fetch(url, {
        method: 'GET',
      });

      if (!response.ok) {
        throw new Error(`Failed to select provider: ${response.status} ${response.statusText}`);
      }

      await fetchProviders();
      // 重新获取选中的提供商
      await fetchSelectedProvider();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // 处理测试提供商
  const handleTestProvider = (name: string) => {
    setTestingProvider(name);
    setShowTestPanel(true);
  };

  // 处理重试能力检测
  const handleRetryDetection = async (name: string) => {
    try {
      const config = getConfig();
      const baseUrl = config.nlTpsApiUrl.replace('/v1', '');
      const url = `${baseUrl}/api/llm/providers/${name}/retry-detection`;
      const response = await fetch(url, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error(`Failed to retry detection: ${response.status} ${response.statusText}`);
      }

      const result = await response.json();
      console.log('Detection restarted:', result.task_id);

      // Refresh providers to show updated status
      await fetchProviders();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* 顶部 */}
      <div className="p-6 border-b border-slate-200">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
              <span>🤖</span> LLM Provider Management
            </h2>
            <p className="text-sm text-slate-600 mt-1">
              Manage and configure different LLM providers with OpenAI-compatible interface
            </p>
          </div>
          <button
            onClick={() => {
              setShowForm(true);
              setSelectedProvider(null);
            }}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 transition"
          >
            + Add Provider
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
        {/* 左侧：提供商列表 */}
        <div className="w-1/3 border-r border-slate-200 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <p className="text-slate-600">Loading providers...</p>
            </div>
          ) : (
            <ProviderList
              providers={providers}
              selectedProvider={selectedProvider}
              onSelectProvider={(provider: any) => setSelectedProvider(provider as LLMProvider)}
              onEdit={(provider: any) => {
                setSelectedProvider(provider as LLMProvider);
                setShowForm(true);
              }}
              onDelete={handleDeleteProvider}
              onTest={handleTestProvider}
              onSelect={handleSelectProvider}
              onRetryDetection={handleRetryDetection}
            />
          )}
        </div>

        {/* 右侧：表单或详情 */}
        <div className="flex-1 overflow-y-auto p-6">
          {showForm ? (
            <ProviderForm
              provider={selectedProvider}
              onSave={handleSaveProvider}
              onCancel={() => {
                setShowForm(false);
                setSelectedProvider(null);
              }}
            />
          ) : showTestPanel && testingProvider ? (
            <TestProvider
              providerName={testingProvider}
              onClose={() => {
                setShowTestPanel(false);
                setTestingProvider(null);
              }}
            />
          ) : selectedProvider ? (
            <ProviderDetails provider={selectedProvider} />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-600">
              <p>Select a provider to view details or click "Add Provider" to create a new one</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// 提供商详情组件
interface ProviderDetailsProps {
  provider: LLMProvider;
}

const ProviderDetails = ({ provider }: ProviderDetailsProps) => (
  <div className="space-y-6">
    <div className="bg-slate-50 rounded-lg p-6 space-y-4">
      <div>
        <label className="text-sm font-semibold text-slate-700">Name</label>
        <p className="text-lg text-slate-900">{provider.name}</p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-semibold text-slate-700">Type</label>
          <p className="text-slate-900">{provider.type}</p>
        </div>
        <div>
          <label className="text-sm font-semibold text-slate-700">Model</label>
          <p className="text-slate-900">{provider.model}</p>
        </div>
      </div>
      <div>
        <label className="text-sm font-semibold text-slate-700">Base URL</label>
        <p className="text-slate-900 font-mono text-sm break-all">{provider.base_url}</p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-semibold text-slate-700">Temperature</label>
          <p className="text-slate-900">{provider.temperature}</p>
        </div>
        <div>
          <label className="text-sm font-semibold text-slate-700">Max Tokens</label>
          <p className="text-slate-900">{provider.max_tokens}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-semibold text-slate-700">Priority</label>
          <p className="text-slate-900">{provider.priority}</p>
        </div>
        <div>
          <label className="text-sm font-semibold text-slate-700">Cost per 1K tokens</label>
          <p className="text-slate-900">${provider.cost_per_1k_tokens.toFixed(6)}</p>
        </div>
      </div>

      {/* Capabilities Section */}
      {(provider.capabilities || provider.context_window || provider.supports_multimodal) && (
        <div className="border-t border-slate-200 pt-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">Capabilities</h3>

          {provider.capabilities && provider.capabilities.length > 0 && (
            <div>
              <label className="text-xs text-slate-600">Supported Capabilities</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {provider.capabilities.map((cap) => (
                  <span key={cap} className="px-3 py-1 bg-purple-100 text-purple-800 text-sm rounded-full font-medium">
                    {cap}
                  </span>
                ))}
              </div>
            </div>
          )}

          {provider.context_window && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-600">Context Window</label>
                <p className="text-slate-900">{provider.context_window.toLocaleString()} tokens</p>
              </div>
              {provider.supports_multimodal !== undefined && (
                <div>
                  <label className="text-xs text-slate-600">Multimodal Support</label>
                  <p className="text-slate-900">{provider.supports_multimodal ? 'Yes' : 'No'}</p>
                </div>
              )}
            </div>
          )}

          {provider.supported_formats && provider.supported_formats.length > 0 && (
            <div>
              <label className="text-xs text-slate-600">Supported Formats</label>
              <div className="flex flex-wrap gap-1 mt-1">
                {provider.supported_formats.map((fmt) => (
                  <span key={fmt} className="px-2 py-0.5 bg-slate-200 text-slate-700 text-xs rounded">
                    {fmt}
                  </span>
                ))}
              </div>
            </div>
          )}

          {provider.embedding_dimensions && (
            <div>
              <label className="text-xs text-slate-600">Embedding Dimensions</label>
              <p className="text-slate-900">{provider.embedding_dimensions}</p>
            </div>
          )}
        </div>
      )}

      {/* Detection Status Section */}
      {provider.capabilities_detection_status && (
        <div className="border-t border-slate-200 pt-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-700">Capability Detection</h3>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-slate-600">Status</label>
              <p className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${
                provider.capabilities_detection_status === 'completed' ? 'bg-green-100 text-green-800' :
                provider.capabilities_detection_status === 'detecting' ? 'bg-blue-100 text-blue-800' :
                provider.capabilities_detection_status === 'failed' ? 'bg-red-100 text-red-800' :
                'bg-gray-100 text-gray-800'
              }`}>
                {provider.capabilities_detection_status === 'completed' ? '✓ Completed' :
                 provider.capabilities_detection_status === 'detecting' ? '🔍 Detecting...' :
                 provider.capabilities_detection_status === 'failed' ? '⚠️ Failed' :
                 '⏳ Pending'}
              </p>
            </div>

            {provider.capabilities_mode && (
              <div>
                <label className="text-xs text-slate-600">Mode</label>
                <p className="text-slate-900">
                  {provider.capabilities_mode === 'auto' ? 'Auto-detected' : 'Manual'}
                </p>
              </div>
            )}
          </div>

          {provider.capabilities_last_updated && (
            <div>
              <label className="text-xs text-slate-600">Last Updated</label>
              <p className="text-slate-900 text-sm">
                {new Date(provider.capabilities_last_updated).toLocaleString()}
              </p>
            </div>
          )}

          {provider.capabilities_detection_error && (
            <div>
              <label className="text-xs text-slate-600">Error</label>
              <p className="text-red-700 text-sm bg-red-50 p-2 rounded">
                {provider.capabilities_detection_error}
              </p>
            </div>
          )}
        </div>
      )}

      <div>
        <label className="text-sm font-semibold text-slate-700">Status</label>
        <p className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${
          provider.enabled
            ? 'bg-green-100 text-green-800'
            : 'bg-gray-100 text-gray-800'
        }`}>
          {provider.enabled ? 'Enabled' : 'Disabled'}
        </p>
      </div>
    </div>
  </div>
);

export default LLMManagement;
