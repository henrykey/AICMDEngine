import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import WorkflowDesigner from './pages/WorkflowDesigner';
import { TaskProvider } from './contexts/TaskContext';
import { hasUsableSession } from './lib/api';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!hasUsableSession()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route path="/" element={
          <ProtectedRoute>
            <TaskProvider>
              <Dashboard />
            </TaskProvider>
          </ProtectedRoute>
        } />

        <Route path="/designer" element={<WorkflowDesigner />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
