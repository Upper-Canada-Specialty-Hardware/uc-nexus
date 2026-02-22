import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ApolloProvider } from '@apollo/client/react';
import { ThemeProvider, CssBaseline } from '@mui/material';
import theme from './theme';
import client from './apollo';
import { RoleProvider } from './contexts/RoleContext';
import { ProjectProvider } from './contexts/ProjectContext';
import { WizardProvider } from './contexts/WizardContext';
import { CartProvider } from './contexts/CartContext';
import { ToastProvider } from './components/Toast';
import App from './App';
// @ts-expect-error fontsource CSS-only import has no type declarations
import '@fontsource-variable/source-sans-3';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ApolloProvider client={client}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <BrowserRouter>
          <RoleProvider>
            <ProjectProvider>
              <WizardProvider>
                <CartProvider>
                  <ToastProvider>
                    <App />
                  </ToastProvider>
                </CartProvider>
              </WizardProvider>
            </ProjectProvider>
          </RoleProvider>
        </BrowserRouter>
      </ThemeProvider>
    </ApolloProvider>
  </StrictMode>,
);
