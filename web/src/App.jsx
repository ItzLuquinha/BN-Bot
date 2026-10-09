import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './AuthContext';
import HomePage from './pages/HomePage';
import ServerSelectPage from './pages/ServerSelectPage';
import GuildDashboard from './pages/dashboard/GuildDashboard';

function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen bg-bn-dark flex items-center justify-center text-bn-muted text-sm">
        Carregando sessão...
      </div>
    );
  }
  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Rota Pública: Home */}
        <Route path="/" element={<HomePage />} />

        {/* Rotas Protegidas (Exigem Login) */}
        <Route 
          path="/servers" 
          element={
            <ProtectedRoute>
              <ServerSelectPage />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/dashboard/:guildId" 
          element={
            <ProtectedRoute>
              <GuildDashboard />
            </ProtectedRoute>
          } 
        />

        {/* Fallback para qualquer rota inexistente */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}