import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ChatPanel from '../components/ChatPanel';
import PlannerExecutorPanel from '../components/PlannerExecutorPanel';
import CommandSets from './CommandSets';

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
  { id: 'documentation', label: 'Docs', icon: '📖' },
];

const Dashboard = () => {
  const navigate = useNavigate();
  const [activeNav, setActiveNav] = useState<string>('planner');

  const handleLogout = () => {
    localStorage.clear();
    navigate('/login', { replace: true });
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
        {/* 顶部：工作区标题 */}
        <div className="bg-white p-4 border-b border-slate-200 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="text-xl text-blue-500">🎯</span>
            <div>
              <div className="text-base font-bold text-slate-800">Task Playground</div>
              <div className="text-sm text-slate-600">Plan and execute tasks using AI-powered orchestration</div>
            </div>
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
                <div className="text-xs px-3 py-1 bg-green-100 text-green-800 rounded-full font-semibold">AI Online</div>
              </div>
              <div className="flex-1 p-6 overflow-hidden flex flex-col">
                <ChatPanel />
              </div>
            </div>

            {/* Planner & Executor 面板 */}
            <div className="flex-1 bg-white rounded-xl shadow-md flex flex-col" style={{ flex: '1 1 0%' }}>
              <div className="p-5 border-b border-slate-200">
                <div className="text-base font-bold text-slate-800 flex items-center gap-2.5">
                  <span>🧠</span> Planner & Executor
                </div>
              </div>
              <div className="flex-1 overflow-hidden p-5 flex flex-col">
                <PlannerExecutorPanel />
              </div>
            </div>
          </div>
        ) : activeNav === 'commands' ? (
          <div className="flex-1 overflow-y-auto">
            <CommandSets />
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-lg font-semibold text-slate-600">
              {NAV_ITEMS.find((item) => item.id === activeNav)?.label} Coming soon...
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
