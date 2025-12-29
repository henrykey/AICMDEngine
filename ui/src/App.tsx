import React from 'react';
import { BrowserRouter, Routes, Route, Link, useNavigate, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import CommandSets from './pages/CommandSets';
import TaskPlayground from './pages/TaskPlayground';
import Login from './pages/Login';

const queryClient = new QueryClient();

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const tenantId = localStorage.getItem('tenantId');
  const username = localStorage.getItem('username');

  const handleLogout = () => {
    localStorage.clear();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 flex">
      <aside className="w-64 bg-gray-800 border-r border-gray-700 p-4 flex flex-col">
        <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent mb-8">
          NL-TPS Admin
        </h1>
        <nav className="space-y-2 flex-1">
          <Link to="/" className="block px-4 py-2 rounded hover:bg-gray-700 transition">
            Task Playground
          </Link>
          <Link to="/command-sets" className="block px-4 py-2 rounded hover:bg-gray-700 transition">
            Command Sets
          </Link>
        </nav>

        <div className="pt-8 border-t border-gray-700">
          <div className="mb-4">
            <label className="text-xs text-gray-500 uppercase block">User</label>
            <span className="text-sm font-medium">{username || 'Unknown'}</span>
          </div>

          <div className="mb-4">
            <label className="text-xs text-gray-500 uppercase block">Tenant Context</label>
            <input
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm mt-1"
              defaultValue={tenantId || "tenant-dev-001"}
              onChange={(e) => localStorage.setItem('tenantId', e.target.value)}
              placeholder="Tenant ID"
            />
          </div>

          <button
            onClick={handleLogout}
            className="w-full text-sm text-red-400 hover:bg-red-900/20 py-2 rounded transition"
          >
            Sign Out
          </button>
        </div>
      </aside>
      <main className="flex-1 p-8 overflow-auto">
        {children}
      </main>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />

          <Route path="/" element={
            <ProtectedRoute>
              <Layout>
                <TaskPlayground />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/command-sets" element={
            <ProtectedRoute>
              <Layout>
                <CommandSets />
              </Layout>
            </ProtectedRoute>
          } />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
