import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ApolloProvider } from '@apollo/client/react';
import { ClerkProvider } from '@clerk/clerk-react';
import { ThemeProvider, CssBaseline } from '@mui/material';
import theme from './theme';
import client from './apollo';
import { WizardProvider } from './contexts/WizardContext';
import { CartProvider } from './contexts/CartContext';
import { ToastProvider } from './components/Toast';
import App from './App';
// @ts-expect-error fontsource CSS-only import has no type declarations
import '@fontsource-variable/source-sans-3';
import './index.css';

const CLERK_PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

if (!CLERK_PUBLISHABLE_KEY) {
  throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY environment variable');
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY}>
      <ApolloProvider client={client}>
        <ThemeProvider theme={theme} defaultMode="light" modeStorageKey="uc-nexus-mode">
          <CssBaseline />
          <BrowserRouter>
            <WizardProvider>
              <CartProvider>
                <ToastProvider>
                  <App />
                </ToastProvider>
              </CartProvider>
            </WizardProvider>
          </BrowserRouter>
        </ThemeProvider>
      </ApolloProvider>
    </ClerkProvider>
  </StrictMode>,
);
