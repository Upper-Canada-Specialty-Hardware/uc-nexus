import { fireEvent, render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import DbAccessPage from '../DbAccessPage';
import { POSTGRES_ACCESS_AUDIT, POSTGRES_ADMINS } from '../../../graphql/admin';
import theme from '../../../theme';

// #1503: the audit history's failed read used to read as "No activity yet." - a clean record, when
// nothing had been read at all.
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { skip?: boolean }) => {
    if (options?.skip) return { data: undefined, loading: false, error: undefined, refetch: vi.fn() };
    if (query === POSTGRES_ACCESS_AUDIT) {
      return { data: undefined, loading: false, error: new Error('Network down'), refetch: vi.fn() };
    }
    if (query === POSTGRES_ADMINS) {
      return { data: { postgresAdmins: [] }, loading: false, error: undefined, refetch: vi.fn() };
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

afterEach(() => vi.unstubAllGlobals());

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
