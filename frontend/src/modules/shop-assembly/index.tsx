import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Tabs, Tab, Typography } from '@mui/material';
import SARListPage from './SARListPage';
import AssembleListPage from './AssembleListPage';
import AssignmentBoard from './AssignmentBoard';
import MyWorkPage from './MyWorkPage';

const SUB_ROUTES = [
  { label: 'Requests', path: 'requests' },
  { label: 'Assemble List', path: 'assemble' },
  { label: 'Assignments', path: 'assign' },
  { label: 'My Work', path: 'my-work' },
];

export default function ShopAssemblyModule() {
  const navigate = useNavigate();
  const location = useLocation();

  const currentSub = location.pathname.split('/').pop();
  const tabIndex = Math.max(SUB_ROUTES.findIndex((r) => r.path === currentSub), 0);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Shop Assembly</Typography>
      <Tabs value={tabIndex} onChange={(_, v) => navigate(`/app/shop-assembly/${SUB_ROUTES[v].path}`)} sx={{ mb: 2 }}>
        {SUB_ROUTES.map((r) => <Tab key={r.path} label={r.label} />)}
      </Tabs>
      <Routes>
        <Route path='requests' element={<SARListPage />} />
        <Route path='assemble' element={<AssembleListPage />} />
        <Route path='assign' element={<AssignmentBoard />} />
        <Route path='my-work' element={<MyWorkPage />} />
        <Route index element={<Navigate to='requests' replace />} />
      </Routes>
    </Box>
  );
}
