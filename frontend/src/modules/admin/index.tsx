import { Navigate } from 'react-router-dom';

export default function AdminModule() {
  return <Navigate to="/app/warehouse/inventory" replace />;
}
