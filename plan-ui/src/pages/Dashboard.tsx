import { MouseEvent, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../lib/api'
import ChatPanel from '../components/ChatPanel'
import PlannerExecutorPanel from '../components/PlannerExecutorPanel'

interface CommandSet {
  id: string
  name: string
  description: string
}

interface NavItem {
  id: string
  label: string
  icon: string
}

const NAV_ITEMS: NavItem[] = [
  { id: 'planner', label: 'Task Playground', icon: '🚀' },
  { id: 'commands', label: 'Command Sets', icon: '📂' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
  { id: 'analytics', label: 'Analytics', icon: '📊' },
  { id: 'documentation', label: 'Documentation', icon: '📖' },
]

export default function Dashboard() {
  const [selectedCommandSetId, setSelectedCommandSetId] = useState<string>('')
  const [activeNav, setActiveNav] = useState<string>('planner')
  const [leftWidth, setLeftWidth] = useState(52)
  const containerRef = useRef<HTMLDivElement>(null)
  const draggingRef = useRef(false)

  const { data: commandSets = [] } = useQuery<CommandSet[]>({
    queryKey: ['commandSets'],
    queryFn: async () => {
      const response = await api.get('/command-sets')
      return response.data
    },
  })

  useEffect(() => {
    if (!selectedCommandSetId && commandSets.length > 0) {
      setSelectedCommandSetId(commandSets[0].id)
    }
  }, [commandSets, selectedCommandSetId])

  const handleLogout = () => {
    localStorage.clear()
    window.location.href = '/login'
  }

  const handleMouseDown = () => {
    draggingRef.current = true
  }

  const handleMouseUp = () => {
    draggingRef.current = false
  }

  const handleMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    if (!draggingRef.current || !containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const newLeftWidth = ((e.clientX - rect.left) / rect.width) * 100
    if (newLeftWidth > 30 && newLeftWidth < 70) {
      setLeftWidth(newLeftWidth)
    }
  }

  const username =
    typeof window !== 'undefined' ? localStorage.getItem('username') || 'guest' : 'guest'

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 text-slate-900">
      <aside className="flex w-72 flex-col bg-sidebar text-white shadow-lg pl-6">
        <div className="px-6 py-6 border-b border-sidebarBorder">
          <div className="flex items-center gap-2 text-lg font-bold text-blue-400">
            <span>☰</span>
            <span>MENU</span>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-4 py-4">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setActiveNav(item.id)}
              className={`flex w-full items-center gap-3 rounded-r-2xl px-5 py-3.5 text-sm font-semibold transition-colors ${
                activeNav === item.id
                  ? 'bg-blue-900/60 text-white border-r-4 border-blue-500 '
                  : 'text-slate-300 hover:text-white hover:bg-sidebarHover'
              }`}
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="border-t border-sidebarBorder px-6 py-4 text-xs text-slate-300">
          <p className="text-sm text-white/80">User: {username}</p>
          <button
            type="button"
            onClick={handleLogout}
            className="mt-3 w-full rounded-lg border border-red-500 bg-red-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-red-500"
          >
            Logout
          </button>
        </div>
      </aside>

      <div className="flex flex-1 flex-col min-w-0">
        <main className="flex flex-1 flex-col overflow-hidden px-6 pb-6">
          <div className="flex-1 flex min-h-0 flex-col overflow-hidden rounded-[32px] border border-slate-200 bg-[#e5e7f0]/80 shadow-inner">
              <div className="flex h-full min-h-0 flex-1 flex-col gap-8 p-8" style={{ padding: '32px', border: '6px solid rgba(219,39,119,0.6)' }}>
              <header className="bg-white px-8 py-6 shadow-sm rounded-b-2xl rounded-t-none" style={{ padding: '32px 48px', border: '6px solid rgba(219,39,119,0.95)' }}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex gap-2.5">
                    <button className="flex items-center gap-1.5 rounded-md border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-blue-500 hover:text-blue-500">
                      <span>📥</span>
                      导入
                    </button>
                    <button className="flex items-center gap-1.5 rounded-md bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600">
                      <span>🔄</span>
                      刷新
                    </button>
                  </div>
                </div>
                <div className="mt-5 flex gap-2 overflow-x-auto pb-1">
                  {commandSets.length > 0 ? (
                    commandSets.map((commandSet) => (
                      <button
                        key={commandSet.id}
                        type="button"
                        onClick={() => setSelectedCommandSetId(commandSet.id)}
                        className={`whitespace-nowrap rounded-md px-5 py-2 text-sm font-semibold transition ${
                          selectedCommandSetId === commandSet.id
                            ? 'bg-blue-500 text-white shadow-[0_2px_4px_rgba(59,130,246,0.3)]'
                            : 'bg-slate-50 text-slate-700 hover:bg-slate-200'
                        }`}
                      >
                        {commandSet.name}
                      </button>
                    ))
                  ) : (
                    <div className="rounded-md bg-slate-50 px-5 py-2 text-sm text-slate-500">无可用命令集</div>
                  )}
                </div>
              </header>

              <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-[28px] bg-white p-6 shadow-[0_20px_45px_rgba(15,23,42,0.08)]">
                {activeNav === 'planner' ? (
                  <div
                    ref={containerRef}
                    onMouseMove={handleMouseMove}
                    onMouseUp={handleMouseUp}
                    onMouseLeave={handleMouseUp}
                    className="flex h-full w-full items-stretch gap-6 overflow-hidden rounded-[26px] bg-white p-6"
                    style={{ userSelect: draggingRef.current ? 'none' : 'auto' }}
                  >
                    <div
                      style={{
                        width: `${leftWidth}%`,
                        minWidth: '32%',
                        maxWidth: '68%',
                      }}
                      className="flex min-h-0 flex-col"
                    >
                      <div className="flex h-full min-h-0 flex-col rounded-3xl border border-slate-100 bg-white shadow-[0_20px_45px_rgba(15,23,42,0.12)] m-6">
                        <ChatPanel commandSetId={selectedCommandSetId} />
                      </div>
                    </div>

                    <div className="flex h-full items-center justify-center">
                      <div
                        onMouseDown={handleMouseDown}
                        onMouseUp={handleMouseUp}
                        className="flex h-full cursor-col-resize items-center"
                      >
                        <div
                          className="h-full w-[2px] rounded-full transition-colors"
                          style={{ backgroundColor: draggingRef.current ? '#3b82f6' : '#cbd5f5' }}
                        />
                      </div>
                    </div>

                    <div
                      style={{
                        width: `${100 - leftWidth}%`,
                        minWidth: '32%',
                        maxWidth: '68%',
                      }}
                      className="flex min-h-0 flex-col"
                    >
                      <div className="flex h-full min-h-0 flex-col rounded-3xl border border-slate-100 bg-white shadow-[0_20px_45px_rgba(15,23,42,0.12)] m-6">
                        <PlannerExecutorPanel commandSetId={selectedCommandSetId} />
                      </div>
                    </div>

                  </div>
                ) : (
                  <div className="flex h-full w-full items-center justify-center">
                    <p className="text-lg font-semibold text-slate-600">
                      {NAV_ITEMS.find((item) => item.id === activeNav)?.label} 即将上线...
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
