import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from '@mui/material';
import AppLayout from '../AppLayout';
import theme from '../../theme';

// #745: the reset was a button in this bar, on every screen, one click from a confirm that emptied
// the database. It is a page in the UC Nexus Admin module now, so the bar must offer nothing.

vi.mock('@clerk/clerk-react', () => ({ UserButton: () => null }));
vi.mock('../NotificationBell', () => ({ default: () => null }));
vi.mock('../TopBarCompany', () => ({ default: () => null }));
vi.mock('../CompanyGate', () => ({ default: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('../Sidebar', () => ({ default: () => null, NavRail: () => null }));
vi.mock('../../relay/GpQueueChip', () => ({ default: () => null }));
vi.mock('../../relay/GpOutboxWatcher', () => ({ default: () => null }));

// This runner exposes no web storage at all (see src/test/setup.ts), and the bar reads the nav
// rail's collapsed flag out of it on its first render.
const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderLayout() {
  render(
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={['/app']}>
        <Routes>
          <Route path="/app" element={<AppLayout />}>
            <Route index element={<div>Home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

test('the app bar offers no reset', () => {
  renderLayout();

  expect(screen.getByText('Home')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /reset data/i })).not.toBeInTheDocument();
  expect(screen.queryByText(/DevAction/i)).not.toBeInTheDocument();
});
