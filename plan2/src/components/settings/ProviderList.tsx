interface LLMProvider {
  _id?: string;
  name: string;
  model: string;
  enabled: boolean;
  priority: number;
  is_current?: boolean;
  is_initialized?: boolean;
  metadata?: {
    provider_name: string;
  };
  // Capability detection fields
  capabilities?: string[];
  capabilities_detection_status?: 'pending' | 'detecting' | 'completed' | 'failed';
  capabilities_detection_error?: string | null;
  capabilities_mode?: 'auto' | 'manual';
}

interface ProviderListProps {
  providers: LLMProvider[];
  selectedProvider: LLMProvider | null;
  onSelectProvider: (provider: LLMProvider) => void;
  onEdit: (provider: LLMProvider) => void;
  onDelete: (name: string) => void;
  onTest: (name: string) => void;
  onSelect: (name: string) => void;
  onRetryDetection?: (name: string) => void;
}

const ProviderList = ({
  providers,
  selectedProvider: _selectedProvider,
  onSelectProvider,
  onEdit,
  onDelete,
  onTest,
  onSelect,
  onRetryDetection,
}: ProviderListProps) => {

  // 获取检测模式对应的样式
  const getDetectionModeBadge = (provider: LLMProvider) => {
    const status = provider.capabilities_detection_status;

    // Manual mode: no detection status (old configurations)
    if (!status) {
      return (
        <span className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded-full font-medium">
          Manual
        </span>
      );
    }

    // Auto-detected mode: detection completed or failed
    if (status === 'completed') {
      return (
        <span className="px-2 py-1 bg-green-100 text-green-800 text-xs rounded-full font-medium">
          ✓ Detected
        </span>
      );
    }
    if (status === 'failed') {
      return (
        <span className="px-2 py-1 bg-red-100 text-red-800 text-xs rounded-full font-medium" title={provider.capabilities_detection_error || 'Detection failed'}>
          ⚠️ Failed
        </span>
      );
    }

    // Temporary states during detection
    if (status === 'detecting') {
      return (
        <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full font-medium animate-pulse">
          🔍 Detecting...
        </span>
      );
    }
    if (status === 'pending') {
      return (
        <span className="px-2 py-1 bg-amber-100 text-amber-800 text-xs rounded-full font-medium">
          ⏳ Pending
        </span>
      );
    }

    return null;
  };

  // 获取能力徽章
  const getCapabilityBadges = (provider: LLMProvider) => {
    if (!provider.capabilities || provider.capabilities.length === 0) {
      return null;
    }

    const capabilityColors: Record<string, string> = {
      'chat': 'bg-purple-100 text-purple-800',
      'vision': 'bg-indigo-100 text-indigo-800',
      'embedding': 'bg-cyan-100 text-cyan-800',
      'code': 'bg-orange-100 text-orange-800',
      'reasoning': 'bg-pink-100 text-pink-800',
      'ocr': 'bg-yellow-100 text-yellow-800',
    };

    return (
      <div className="flex flex-wrap gap-1 mt-2">
        {provider.capabilities.map((cap) => (
          <span
            key={cap}
            className={`px-2 py-0.5 text-xs rounded-full font-medium ${
              capabilityColors[cap] || 'bg-gray-100 text-gray-800'
            }`}
          >
            {cap}
          </span>
        ))}
      </div>
    );
  };

  return (
    <div className="divide-y divide-slate-200">
      {providers.length === 0 ? (
        <div className="p-6 text-center text-slate-600">
          <p>No providers configured yet</p>
        </div>
      ) : (
        providers.map((provider) => (
          <div
            key={provider.name}
            onClick={() => onSelectProvider(provider)}
            className={`p-4 cursor-pointer transition-colors border-l-4 ${
              provider.is_current
                ? 'bg-blue-50 border-l-blue-500'
                : 'bg-white border-l-transparent hover:bg-slate-50'
            }`}
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1">
                <h3 className="font-semibold text-slate-900">{provider.name}</h3>
                <p className="text-sm text-slate-600">{provider.metadata?.provider_name || provider.model}</p>
                {getCapabilityBadges(provider)}
              </div>
              <div className="flex flex-col gap-1 items-end">
                <div className="flex gap-1">
                  {provider.is_current && (
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full font-medium flex items-center gap-1">
                      <span>🎯</span>
                      Selected
                    </span>
                  )}
                  {provider.enabled && !provider.is_current && (
                    <span className="px-2 py-1 bg-green-100 text-green-800 text-xs rounded-full font-medium">
                      ✓ Active
                  </span>
                  )}
                  {!provider.is_initialized && provider.enabled && (
                    <span className="px-2 py-1 bg-amber-100 text-amber-800 text-xs rounded-full font-medium">
                      ⚠️ Initializing
                    </span>
                  )}
                  {getDetectionModeBadge(provider)}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1 mb-3 text-xs text-slate-600">
              <span>Priority: {provider.priority}</span>
              <span className="mx-1">•</span>
              <span>Model: {provider.model}</span>
            </div>

            <div className="flex gap-2 pt-2 border-t border-slate-200">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit(provider);
                }}
                className="flex-1 px-2 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 rounded transition"
              >
                Edit
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onTest(provider.name);
                }}
                className="flex-1 px-2 py-1.5 text-xs font-medium text-amber-600 hover:bg-amber-50 rounded transition"
              >
                Test
              </button>
              {onRetryDetection && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onRetryDetection(provider.name);
                  }}
                  disabled={provider.capabilities_detection_status === 'detecting'}
                  className={`flex-1 px-2 py-1.5 text-xs font-medium rounded transition ${
                    provider.capabilities_detection_status === 'detecting'
                      ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                      : 'text-purple-600 hover:bg-purple-50'
                  }`}
                  title={
                    provider.capabilities_detection_status === 'detecting'
                      ? 'Detection in progress...'
                      : provider.capabilities_detection_status === 'completed'
                        ? 'Re-detect capabilities'
                        : provider.capabilities_detection_status === 'failed'
                          ? (provider.capabilities_detection_error || 'Retry capability detection')
                          : 'Start capability detection'
                  }
                >
                  {provider.capabilities_detection_status === 'detecting'
                    ? 'Detecting...'
                    : provider.capabilities_detection_status === 'completed'
                      ? 'Re-detect'
                      : provider.capabilities_detection_status === 'failed'
                        ? 'Retry'
                        : 'Detect'}
                </button>
              )}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(provider.name);
                }}
                className="flex-1 px-2 py-1.5 text-xs font-medium text-green-600 hover:bg-green-50 rounded transition"
              >
                Select
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(provider.name);
                }}
                className="flex-1 px-2 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 rounded transition"
              >
                Delete
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  );
};

export default ProviderList;
