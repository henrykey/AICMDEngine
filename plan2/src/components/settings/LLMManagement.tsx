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
