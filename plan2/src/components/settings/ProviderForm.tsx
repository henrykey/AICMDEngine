import { useState, useEffect } from 'react';

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
  // Capability fields
  capabilities?: string[];
  context_window?: number;
  supports_multimodal?: boolean;
  supported_formats?: string[];
  embedding_dimensions?: number | null;
  capabilities_mode?: 'auto' | 'manual';
}

interface ProviderFormProps {
  provider: LLMProvider | null;
  onSave: (provider: LLMProvider) => void;
  onCancel: () => void;
}

const DEFAULT_PROVIDER: LLMProvider = {
  name: '',
  type: 'openai_compatible',
  base_url: '',
  model: '',
  api_key_ref: '',
  timeout: 30,
  temperature: 0.7,
  max_tokens: 2048,
  top_p: 1.0,
  cost_per_1k_tokens: 0.001,
  priority: 1,
  enabled: true,
  // Capability defaults
  capabilities_mode: 'auto',
  capabilities: [],
  context_window: 4096,
  supports_multimodal: false,
  supported_formats: [],
  embedding_dimensions: null,
};

const ProviderForm = ({ provider, onSave, onCancel }: ProviderFormProps) => {
  const [formData, setFormData] = useState<LLMProvider>(provider || DEFAULT_PROVIDER);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setFormData(provider || DEFAULT_PROVIDER);
  }, [provider]);

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.name.trim()) newErrors.name = 'Name is required';
    if (!formData.base_url.trim()) newErrors.base_url = 'Base URL is required';
    if (!formData.model.trim()) newErrors.model = 'Model is required';
    if (!formData.api_key_ref.trim()) newErrors.api_key_ref = 'API key reference is required';
    if (formData.temperature < 0 || formData.temperature > 2)
      newErrors.temperature = 'Temperature must be between 0 and 2';
    if (formData.max_tokens < 1) newErrors.max_tokens = 'Max tokens must be at least 1';
    if (formData.cost_per_1k_tokens < 0)
      newErrors.cost_per_1k_tokens = 'Cost cannot be negative';
    if (formData.priority < 1) newErrors.priority = 'Priority must be at least 1';

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validateForm()) {
      // Prepare data for submission
      let submitData = { ...formData };

      // If auto-detect mode, exclude capabilities field to let backend detect automatically
      if (formData.capabilities_mode === 'auto') {
        const { capabilities, context_window, supports_multimodal, supported_formats, embedding_dimensions, ...dataWithoutCapabilities } = submitData;
        submitData = dataWithoutCapabilities;
      }

      onSave(submitData);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const finalValue = type === 'checkbox' ? (e.target as HTMLInputElement).checked : value;

    setFormData((prev) => ({
      ...prev,
      [name]:
        type === 'number' && name !== 'name' && name !== 'api_key_ref'
          ? parseFloat(value)
          : finalValue,
    }));

    // Clear error for this field when user starts typing
    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }));
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <h3 className="text-lg font-bold text-slate-800">
        {provider ? 'Edit Provider' : 'Create New Provider'}
      </h3>

      {/* Basic Info */}
      <div className="space-y-4">
        <h4 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">
          Basic Information
        </h4>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Provider Name *
          </label>
          <input
            type="text"
            name="name"
            value={formData.name}
            onChange={handleChange}
            disabled={!!provider}
            placeholder="e.g., openai, deepseek, qwen"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-100"
          />
          {errors.name && <p className="text-red-600 text-sm mt-1">{errors.name}</p>}
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Type</label>
          <select
            name="type"
            value={formData.type}
            onChange={handleChange}
            className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="openai_compatible">OpenAI Compatible</option>
            <option value="custom">Custom</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Base URL *
          </label>
          <input
            type="text"
            name="base_url"
            value={formData.base_url}
            onChange={handleChange}
            placeholder="https://api.example.com/v1"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
          />
          {errors.base_url && <p className="text-red-600 text-sm mt-1">{errors.base_url}</p>}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Model *
            </label>
            <input
              type="text"
              name="model"
              value={formData.model}
              onChange={handleChange}
              placeholder="e.g., gpt-5, deepseek-v3.2"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {errors.model && <p className="text-red-600 text-sm mt-1">{errors.model}</p>}
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              API Key Ref * <span className="text-xs text-slate-500">(Environment variable name)</span>
            </label>
            <input
              type="text"
              name="api_key_ref"
              value={formData.api_key_ref}
              onChange={handleChange}
              placeholder="e.g., OPENAI_API_KEY"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
            />
            <p className="text-xs text-slate-500 mt-1">
              Environment variable name from .env file (e.g., OPENAI_API_KEY, DEEPSEEK_API_KEY)
            </p>
            {errors.api_key_ref && (
              <p className="text-red-600 text-sm mt-1">{errors.api_key_ref}</p>
            )}
          </div>
        </div>
      </div>

      {/* Model Parameters */}
      <div className="space-y-4">
        <h4 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">
          Model Parameters
        </h4>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Temperature
            </label>
            <input
              type="number"
              name="temperature"
              value={formData.temperature}
              onChange={handleChange}
              step="0.1"
              min="0"
              max="2"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {errors.temperature && (
              <p className="text-red-600 text-sm mt-1">{errors.temperature}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Top P
            </label>
            <input
              type="number"
              name="top_p"
              value={formData.top_p}
              onChange={handleChange}
              step="0.1"
              min="0"
              max="1"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Max Tokens
            </label>
            <input
              type="number"
              name="max_tokens"
              value={formData.max_tokens}
              onChange={handleChange}
              min="1"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {errors.max_tokens && (
              <p className="text-red-600 text-sm mt-1">{errors.max_tokens}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Timeout (seconds)
            </label>
            <input
              type="number"
              name="timeout"
              value={formData.timeout}
              onChange={handleChange}
              min="1"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
      </div>

      {/* Capabilities Configuration */}
      <div className="space-y-4">
        <h4 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">
          Capabilities
        </h4>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Detection Mode
          </label>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="capabilities_mode"
                value="auto"
                checked={formData.capabilities_mode !== 'manual'}
                onChange={(e) => {
                  setFormData((prev) => ({
                    ...prev,
                    capabilities_mode: e.target.value as 'auto' | 'manual',
                  }));
                }}
                className="w-4 h-4 text-blue-600"
              />
              <div>
                <span className="text-sm font-medium text-slate-900">Auto-detect</span>
                <p className="text-xs text-slate-500">Automatically detect capabilities from LLM API</p>
              </div>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="capabilities_mode"
                value="manual"
                checked={formData.capabilities_mode === 'manual'}
                onChange={(e) => {
                  setFormData((prev) => ({
                    ...prev,
                    capabilities_mode: e.target.value as 'auto' | 'manual',
                  }));
                }}
                className="w-4 h-4 text-blue-600"
              />
              <div>
                <span className="text-sm font-medium text-slate-900">Manual</span>
                <p className="text-xs text-slate-500">Manually specify capabilities</p>
              </div>
            </label>
          </div>
        </div>

        {formData.capabilities_mode === 'manual' && (
          <div className="space-y-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
            <p className="text-sm text-blue-800 font-medium mb-3">
              Manually configure provider capabilities
            </p>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Capabilities
              </label>
              <div className="flex flex-wrap gap-2">
                {['chat', 'vision', 'embedding', 'code', 'reasoning', 'ocr'].map((cap) => (
                  <label key={cap} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.capabilities?.includes(cap) || false}
                      onChange={(e) => {
                        const capabilities = formData.capabilities || [];
                        if (e.target.checked) {
                          setFormData((prev) => ({
                            ...prev,
                            capabilities: [...capabilities, cap],
                          }));
                        } else {
                          setFormData((prev) => ({
                            ...prev,
                            capabilities: capabilities.filter((c) => c !== cap),
                          }));
                        }
                      }}
                      className="w-4 h-4 rounded border-slate-300 text-blue-600"
                    />
                    <span className="text-sm text-slate-700 capitalize">{cap}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Context Window
                </label>
                <input
                  type="number"
                  name="context_window"
                  value={formData.context_window || 4096}
                  onChange={handleChange}
                  min="1"
                  placeholder="e.g., 128000"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Embedding Dimensions
                </label>
                <input
                  type="number"
                  name="embedding_dimensions"
                  value={formData.embedding_dimensions || ''}
                  onChange={handleChange}
                  min="1"
                  placeholder="e.g., 1536"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div className="flex items-center gap-3 p-3 bg-white rounded-lg border border-slate-200">
              <input
                type="checkbox"
                name="supports_multimodal"
                checked={formData.supports_multimodal || false}
                onChange={(e) => {
                  setFormData((prev) => ({
                    ...prev,
                    supports_multimodal: e.target.checked,
                  }));
                }}
                id="supports_multimodal"
                className="w-4 h-4 rounded border-slate-300 text-blue-600"
              />
              <label htmlFor="supports_multimodal" className="text-sm font-medium text-slate-700">
                Supports Multimodal (Images, Audio, etc.)
              </label>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Supported Formats (comma-separated)
              </label>
              <input
                type="text"
                name="supported_formats"
                value={formData.supported_formats?.join(', ') || ''}
                onChange={(e) => {
                  const formats = e.target.value.split(',').map((s) => s.trim()).filter((s) => s);
                  setFormData((prev) => ({
                    ...prev,
                    supported_formats: formats,
                  }));
                }}
                placeholder="e.g., text, image, audio"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        )}
      </div>

      {/* Configuration */}
      <div className="space-y-4">
        <h4 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">
          Configuration
        </h4>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Priority
            </label>
            <input
              type="number"
              name="priority"
              value={formData.priority}
              onChange={handleChange}
              min="1"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {errors.priority && (
              <p className="text-red-600 text-sm mt-1">{errors.priority}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Cost per 1K Tokens
            </label>
            <input
              type="number"
              name="cost_per_1k_tokens"
              value={formData.cost_per_1k_tokens}
              onChange={handleChange}
              step="0.000001"
              min="0"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
            />
            {errors.cost_per_1k_tokens && (
              <p className="text-red-600 text-sm mt-1">{errors.cost_per_1k_tokens}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
          <input
            type="checkbox"
            name="enabled"
            checked={formData.enabled}
            onChange={handleChange}
            id="enabled"
            className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-2 focus:ring-blue-500"
          />
          <label htmlFor="enabled" className="text-sm font-medium text-slate-700">
            Enabled
          </label>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-4 border-t border-slate-200">
        <button
          type="submit"
          className="flex-1 px-4 py-2 bg-blue-500 text-white font-medium rounded-lg hover:bg-blue-600 transition"
        >
          {provider ? 'Update Provider' : 'Create Provider'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 px-4 py-2 bg-slate-200 text-slate-800 font-medium rounded-lg hover:bg-slate-300 transition"
        >
          Cancel
        </button>
      </div>
    </form>
  );
};

export default ProviderForm;
