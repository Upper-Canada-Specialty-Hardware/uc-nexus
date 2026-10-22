import { fireEvent, render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import DbAccessPage from '../DbAccessPage';
import { POSTGRES_ACCESS_AUDIT, POSTGRES_ADMINS } from '../../../graphql/admin';
import theme from '../../../theme';

const admins = vi.hoisted(() => ({ rows: [] as Record<string, unknown>[] }));

// #1503: the audit history's failed read used to read as "No activity yet." - a clean record, when
// nothing had been read at all.
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { skip?: boolean }) => {
    if (options?.skip) return { data: undefined, loading: false, error: undefined, refetch: vi.fn() };
    if (query === POSTGRES_ACCESS_AUDIT) {
      return { data: undefined, loading: false, error: new Error('Network down'), refetch: vi.fn() };
    }
    if (query === POSTGRES_ADMINS) {
      return { data: { postgresAdmins: admins.rows }, loading: false, error: undefined, refetch: vi.fn() };
    }
    return { data: undefined, loading: false, error: undefined, refetch: vi.fn() };
  },
  useMutation: () => [vi.fn(), { loading: false }],
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../../../hooks/useIdentity', () => ({ useIdentity: () => ({ isDbAdmin: true }) }));

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  admins.rows = [];
});

function renderPage() {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <DbAccessPage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

it('says the audit history failed to load rather than "no activity yet" (#1503)', () => {
  render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <DbAccessPage />
      </MemoryRouter>
    </ThemeProvider>,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Audit history' }));

  expect(screen.getByText(/couldn.t load the audit history/i)).toBeInTheDocument();
  expect(screen.queryByText('No activity yet.')).not.toBeInTheDocument();
});

it('flags a login whose holder lost UC Nexus Admin and will not rotate it (#1866)', () => {
  const login = {
    clerkUserId: 'user_x',
    displayName: 'Pat Lost',
    email: 'pat@example.com',
    clerkMissing: false,
    active: true,
    createdAt: '2026-01-01T00:00:00',
    lastRotatedAt: null,
  };
  admins.rows = [
    { ...login, dbRole: 'user_lost', lostAdminRole: true },
    { ...login, dbRole: 'user_still', clerkUserId: 'user_y', displayName: 'Sam Still', lostAdminRole: false },
  ];
  renderPage();

  expect(screen.getAllByText('no longer an admin')).toHaveLength(1);
  const [lost, still] = screen.getAllByRole('button', { name: 'Rotate' });
  expect(lost).toBeDisabled();
  expect(still).toBeEnabled();
});
