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
}

interface ProviderListProps {
  providers: LLMProvider[];
  selectedProvider: LLMProvider | null;
  onSelectProvider: (provider: LLMProvider) => void;
  onEdit: (provider: LLMProvider) => void;
  onDelete: (name: string) => void;
  onTest: (name: string) => void;
  onSelect: (name: string) => void;
}

const ProviderList = ({
  providers,
  selectedProvider: _selectedProvider,
  onSelectProvider,
  onEdit,
  onDelete,
  onTest,
  onSelect,
}: ProviderListProps) => {
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
              <div>
                <h3 className="font-semibold text-slate-900">{provider.name}</h3>
                <p className="text-sm text-slate-600">{provider.metadata?.provider_name || provider.model}</p>
              </div>
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
