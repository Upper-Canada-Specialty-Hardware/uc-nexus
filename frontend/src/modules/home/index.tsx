import { Navigate } from 'react-router-dom';
import HomeDashboard from './HomeDashboard';
import { useIdentity } from '../../hooks/useIdentity';

export default function HomeModule() {
  const { roles } = useIdentity();
  // #1727: an account that only drives has one page to work from, so it lands there instead of on a
  // dashboard of modules it cannot open.
  if (roles.length === 1 && roles[0] === 'Driver') return <Navigate to="/app/deliveries" replace />;
  return <HomeDashboard />;
}
