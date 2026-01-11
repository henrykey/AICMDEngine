import { useState } from 'react';
import LLMManagement from '../components/settings/LLMManagement';
import MCPManagement from '../components/settings/MCPManagement';

interface SettingsTab {
  id: string;
  label: string;
  icon: string;
  component: React.ComponentType;
}

const SETTINGS_TABS: SettingsTab[] = [
  { id: 'llm', label: 'LLM Management', icon: '🤖', component: LLMManagement },
  { id: 'mcp', label: 'MCP Management', icon: '🔌', component: MCPManagement },
];

const Settings = () => {
  const [activeTab, setActiveTab] = useState<string>('llm');

  const activeTabConfig = SETTINGS_TABS.find((tab) => tab.id === activeTab);
  const Component = activeTabConfig?.component;

  return (
    <div className="flex h-full gap-6 p-6">
      {/* 左侧标签页导航 */}
      <div className="w-48 flex flex-col gap-2">
        <div className="text-lg font-bold text-slate-800 mb-4">Settings</div>
        {SETTINGS_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-3 rounded-lg flex items-center gap-2 font-medium transition-all text-left ${
              activeTab === tab.id
                ? 'bg-blue-100 text-blue-700 border-l-4 border-blue-500'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <span className="text-lg">{tab.icon}</span>
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* 右侧内容区 */}
      <div className="flex-1 bg-white rounded-xl shadow-md overflow-hidden flex flex-col">
        {Component && <Component />}
      </div>
    </div>
  );
};

export default Settings;
