import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ChatPanel from '../components/ChatPanel';
import PlannerExecutorPanel from '../components/PlannerExecutorPanel';
import CommandSetSelector from '../components/CommandSetSelector';
import CommandSets from './CommandSets';
import Settings from './Settings';
import MCPTools from './MCPTools';
import WorkflowDesigner from './WorkflowDesigner';
import { useTask } from '../contexts/TaskContext';

interface NavItem {
  id: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'planner', label: 'Task Playground', icon: '🚀' },
  { id: 'designer', label: 'Designer', icon: '🎨' },
  { id: 'mcp-tools', label: 'MCP Tools', icon: '🔧' },
  { id: 'commands', label: 'Command Sets', icon: '📂' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
  { id: 'analytics', label: 'Analytics', icon: '📊' },
  { id: 'documentation', label: 'Docs', icon: '📖' },
];

const Dashboard = () => {
  const navigate = useNavigate();
  const { planningMode, setPlanningMode } = useTask();
  const [activeNav, setActiveNav] = useState<string>('planner');
  const [chatPanelWidth, setChatPanelWidth] = useState(50); // percent
  const [isDraggingDivider, setIsDraggingDivider] = useState(false);

  const handleDividerMouseDown = useCallback(() => {
    setIsDraggingDivider(true);
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingDivider) return;

      const viewportWidth = window.innerWidth;
      const sidebarWidth = 240; // w-60
      const contentLeft = sidebarWidth;
      const contentWidth = viewportWidth - contentLeft;
      const relativeX = e.clientX - contentLeft;
      const nextPercent = (relativeX / contentWidth) * 100;

      if (nextPercent >= 25 && nextPercent <= 75) {
        setChatPanelWidth(nextPercent);
      }
    };

    const handleMouseUp = () => {
      setIsDraggingDivider(false);
    };

    if (isDraggingDivider) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isDraggingDivider]);

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
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3 flex-1">
              <span className="text-xl text-blue-500 mt-0.5">
                {activeNav === 'planner' && '🎯'}
                {activeNav === 'designer' && '🎨'}
                {activeNav === 'mcp-tools' && '🔧'}
                {activeNav === 'commands' && '📂'}
                {activeNav === 'settings' && '⚙️'}
                {activeNav === 'analytics' && '📊'}
                {activeNav === 'documentation' && '📖'}
              </span>
              <div className="flex-1">
                <div className="text-base font-bold text-slate-800">
                  {NAV_ITEMS.find((item) => item.id === activeNav)?.label}
                </div>
                <div className="text-sm text-slate-600">
                  {activeNav === 'planner' && 'Plan and execute tasks using AI-powered orchestration'}
                  {activeNav === 'designer' && 'Design BPMN processes and forms with AI assistance'}
                  {activeNav === 'mcp-tools' && 'Browse and explore MCP tools from available servers'}
                  {activeNav === 'commands' && 'Manage and view command sets'}
                  {activeNav === 'settings' && 'Configure system settings and preferences'}
                  {activeNav === 'analytics' && 'View analytics and metrics'}
                  {activeNav === 'documentation' && 'Read documentation and guides'}
                </div>
              </div>
            </div>
            {activeNav === 'planner' && (
              <div className="flex flex-shrink-0 items-start gap-3">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 shadow-sm">
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Planning Mode
                  </label>
                  <select
                    value={planningMode}
                    onChange={(e) => setPlanningMode(e.target.value as 'auto' | 'cmdengine' | 'mcp')}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-500"
                  >
                    <option value="auto">Auto</option>
                    <option value="cmdengine">CmdEngine</option>
                    <option value="mcp">MCP Direct</option>
                  </select>
                </div>
                <CommandSetSelector />
              </div>
            )}
          </div>
        </div>

        {/* 中部：左右布局 - 始终 flex-row */}
        {activeNav === 'planner' ? (
          <div className="flex-1 flex flex-row p-6 overflow-hidden" style={{ display: 'flex', flexDirection: 'row' }}>
            {/* CHAT 面板 */}
            <div
              className="bg-white rounded-xl shadow-md flex flex-col min-w-0"
              style={{ width: `calc(${chatPanelWidth}% - 6px)` }}
            >
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

            <div
              className={`mx-3 w-1 rounded-full bg-slate-200 hover:bg-blue-500 cursor-col-resize transition-colors ${
                isDraggingDivider ? 'bg-blue-500' : ''
              }`}
              onMouseDown={handleDividerMouseDown}
              title="Drag to resize panels"
            />

            {/* Planner & Executor 面板 */}
            <div
              className="bg-white rounded-xl shadow-md flex flex-col min-w-0"
              style={{ width: `calc(${100 - chatPanelWidth}% - 6px)` }}
            >
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
        ) : activeNav === 'mcp-tools' ? (
          <div className="flex-1 overflow-hidden">
            <MCPTools />
          </div>
        ) : activeNav === 'commands' ? (
          <div className="flex-1 overflow-y-auto">
            <CommandSets />
          </div>
        ) : activeNav === 'settings' ? (
          <div className="flex-1 overflow-hidden">
            <Settings />
          </div>
        ) : activeNav === 'designer' ? (
          <div className="flex-1 overflow-hidden">
            <WorkflowDesigner />
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
