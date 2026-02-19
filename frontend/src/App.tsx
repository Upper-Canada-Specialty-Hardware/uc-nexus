import { Routes, Route, Navigate } from 'react-router-dom';
import { useRole } from './contexts/RoleContext';
import RoleSelectionPage from './pages/RoleSelectionPage';
import AppLayout from './components/AppLayout';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { role } = useRole();
  if (!role) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<RoleSelectionPage />} />
      <Route
        path="/app/*"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
