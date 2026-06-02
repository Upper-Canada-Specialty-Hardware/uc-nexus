import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box, CircularProgress } from '@mui/material';
import { SignedIn, SignedOut, SignIn, RedirectToSignIn } from '@clerk/clerk-react';
import AppLayout from './components/AppLayout';
import { LazyRoute } from './components/LazyBoundary';

// Lazy-loaded module imports
const HomeModule = React.lazy(() => import('./modules/home'));
const ImportModule = React.lazy(() => import('./modules/import'));
const POModule = React.lazy(() => import('./modules/po'));
const WarehouseModule = React.lazy(() => import('./modules/warehouse'));
const ShopAssemblyModule = React.lazy(() => import('./modules/shop-assembly'));
const ShippingModule = React.lazy(() => import('./modules/shipping'));
const AdminModule = React.lazy(() => import('./modules/admin'));

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  return (
    <>
      <SignedIn>{children}</SignedIn>
      <SignedOut><RedirectToSignIn /></SignedOut>
    </>
  );
}

function SuspenseFallback() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
      <CircularProgress />
    </Box>
  );
}

function SignInPage() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
      <SignIn routing="hash" />
    </Box>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={
        <>
          <SignedIn><Navigate to="/app" replace /></SignedIn>
          <SignedOut><SignInPage /></SignedOut>
        </>
      } />
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<LazyRoute fallback={<SuspenseFallback />}><HomeModule /></LazyRoute>} />
        <Route path="import/*" element={<LazyRoute fallback={<SuspenseFallback />}><ImportModule /></LazyRoute>} />
        <Route path="po/*" element={<LazyRoute fallback={<SuspenseFallback />}><POModule /></LazyRoute>} />
        <Route path="warehouse/*" element={<LazyRoute fallback={<SuspenseFallback />}><WarehouseModule /></LazyRoute>} />
        <Route path="shop-assembly/*" element={<LazyRoute fallback={<SuspenseFallback />}><ShopAssemblyModule /></LazyRoute>} />
        <Route path="shipping/*" element={<LazyRoute fallback={<SuspenseFallback />}><ShippingModule /></LazyRoute>} />
        <Route path="admin/*" element={<LazyRoute fallback={<SuspenseFallback />}><AdminModule /></LazyRoute>} />
      </Route>
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}

export default App;
