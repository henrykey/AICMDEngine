import { useState } from 'react';
import ChatPanel from '../components/ChatPanel';
import PlannerExecutorPanel from '../components/PlannerExecutorPanel';

interface CommandSet {
  id: string;
  name: string;
}

interface NavItem {
  id: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'planner', label: 'Task Playground', icon: '🚀' },
  { id: 'commands', label: 'Command Sets', icon: '📂' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
  { id: 'analytics', label: 'Analytics', icon: '📊' },
  { id: 'documentation', label: 'Documentation', icon: '📖' },
];

const Dashboard = () => {
  const [activeNav, setActiveNav] = useState<string>('planner');
  const [selectedCommandSetId, setSelectedCommandSetId] = useState<string>('1');

  const commandSets: CommandSet[] = [
    { id: '1', name: '数据处理集' },
    { id: '2', name: '模型训练集' },
    { id: '3', name: '部署脚本集' },
    { id: '4', name: '监控任务集' },
    { id: '5', name: '备份恢复集' },
    { id: '6', name: '自定义集合' },
  ];

  const handleLogout = () => {
    localStorage.clear();
    window.location.href = '/login';
  };

  const username = typeof window !== 'undefined' ? localStorage.getItem('username') || 'guest' : 'guest';

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      {/* 左侧菜单栏 */}
      <div className="w-60 bg-sidebar text-white flex flex-col shadow-md">
        <div className="p-6 border-b border-sidebarBorder">
          <div className="text-lg font-bold text-blue-400 flex items-center gap-2.5">
            <span>☰</span> MENU
          </div>
        </div>
        <div className="flex-1 p-0 pt-5 flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <div
              key={item.id}
              onClick={() => setActiveNav(item.id)}
              className={`px-5 py-3.5 cursor-pointer flex items-center gap-3 transition-colors rounded-e-lg ${
                activeNav === item.id
                  ? 'bg-blue-900/15 border-e-4 border-blue-500 text-white'
                  : 'text-slate-300 hover:text-white hover:bg-sidebar/20'
              }`}
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
        <div className="border-t border-sidebarBorder p-4 text-xs text-slate-300">
          <p className="text-sm text-white/80">User: {username}</p>
          <button
            type="button"
            onClick={handleLogout}
            className="mt-3 w-full rounded-lg border border-red-500 bg-red-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-red-500"
          >
            Logout
          </button>
        </div>
      </div>

      {/* 右侧工作区 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 顶部：命令集选择 */}
        <div className="bg-white p-4 border-b border-slate-200 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <span className="text-xl text-blue-500">⚙️</span>
              <div>
                <div className="text-base font-bold text-slate-800">CMDs Set</div>
                <div className="text-sm text-slate-600">选择要执行的命令集合</div>
              </div>
            </div>
            <div className="flex gap-2.5">
              <button className="px-4 py-2 border border-slate-200 rounded-md bg-white text-slate-700 text-sm flex items-center gap-1.5 hover:border-blue-500 hover:text-blue-500">
                <span>📥</span> 导入
              </button>
              <button className="px-4 py-2 bg-blue-500 text-white text-sm rounded-md flex items-center gap-1.5 hover:bg-blue-600">
                <span>🔄</span> 刷新
              </button>
            </div>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-0.5">
            {commandSets.map((commandSet) => (
              <div
                key={commandSet.id}
                onClick={() => setSelectedCommandSetId(commandSet.id)}
                className={`px-5 py-2 rounded-md text-sm font-semibold whitespace-nowrap cursor-pointer ${
                  selectedCommandSetId === commandSet.id
                    ? 'bg-blue-500 text-white shadow-[0_2px_4px_rgba(59,130,246,0.2)]'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                {commandSet.name}
              </div>
            ))}
          </div>
        </div>

        {/* 中部：左右布局 - 始终 flex-row */}
        {activeNav === 'planner' ? (
          <div className="flex-1 flex flex-row p-6 gap-6 overflow-hidden" style={{ display: 'flex', flexDirection: 'row' }}>
            {/* CHAT 面板 */}
            <div className="flex-1 bg-white rounded-xl shadow-md flex flex-col" style={{ flex: '1 1 0%' }}>
              <div className="p-5 border-b border-slate-200 flex items-center justify-between">
                <div className="text-base font-bold text-slate-800 flex items-center gap-2.5">
                  <span>💬</span> CHAT
                </div>
                <div className="text-xs px-3 py-1 bg-green-100 text-green-800 rounded-full font-semibold">AI在线</div>
              </div>
              <div className="flex-1 p-6 overflow-y-auto flex flex-col gap-5">
                <ChatPanel commandSetId={selectedCommandSetId} />
              </div>
              <div className="p-5 border-t border-slate-200 bg-slate-50">
                <div className="flex gap-3">
                  <textarea
                    placeholder="输入您的消息..."
                    className="flex-1 p-3.5 border border-slate-200 rounded-xl text-sm min-h-[60px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-500"
                  />
                  <button
                    type="button"
                    className="w-12 bg-blue-500 text-white rounded-xl flex items-center justify-center text-xl hover:bg-blue-600 transition-transform hover:-translate-y-0.5"
                  >
                    ↵
                  </button>
                </div>
              </div>
            </div>

            {/* Planner & Executor 面板 */}
            <div className="flex-1 bg-white rounded-xl shadow-md flex flex-col" style={{ flex: '1 1 0%' }}>
              <div className="p-5 border-b border-slate-200">
                <div className="text-base font-bold text-slate-800 flex items-center gap-2.5">
                  <span>🧠</span> Planner & Executor
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-6">
                <PlannerExecutorPanel commandSetId={selectedCommandSetId} />
              </div>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-lg font-semibold text-slate-600">
              {NAV_ITEMS.find((item) => item.id === activeNav)?.label} 即将上线...
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
