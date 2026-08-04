import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ApolloProvider } from '@apollo/client/react';
import { ClerkProvider } from '@clerk/clerk-react';
import { ThemeProvider, CssBaseline } from '@mui/material';
import theme from './theme';
import client from './apollo';
import { WizardProvider } from './contexts/WizardContext';
import { AuthRecoveryProvider } from './contexts/AuthRecoveryContext';
import { ToastProvider } from './components/Toast';
import { MotionProvider } from './motion';
import App from './App';
// @ts-expect-error fontsource CSS-only import has no type declarations
import '@fontsource-variable/source-sans-3';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/ibm-plex-mono/600.css';
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
          <MotionProvider>
            <BrowserRouter>
              <WizardProvider>
                <ToastProvider>
                  {/* Inside ClerkProvider (it reads useAuth) and the theme (it renders a dialog),
                      and above App so the re-auth prompt outlives whatever route blanked. */}
                  <AuthRecoveryProvider>
                    <App />
                  </AuthRecoveryProvider>
                </ToastProvider>
              </WizardProvider>
            </BrowserRouter>
          </MotionProvider>
        </ThemeProvider>
      </ApolloProvider>
    </ClerkProvider>
  </StrictMode>,
);
