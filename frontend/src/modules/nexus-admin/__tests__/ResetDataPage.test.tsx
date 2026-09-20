import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ResetDataPage from '../ResetDataPage';
import { ToastProvider } from '../../../components/Toast';
import { publishAuthBridge, resetAuthBridge } from '../../../authBridge';

/**
 * #745: the reset left the top app bar for a page of its own. What is pinned here is the deliberate
 * part - who may open it, and the two gates (the typed phrase, then the confirm) that stand between
 * opening it and a request that empties the database.
 */

const identity = vi.hoisted(() => ({ isNexusAdmin: true }));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_admin',
    roles: identity.isNexusAdmin ? ['UC Nexus Admin'] : ['Tenant Owner'],
    hasRole: (role: string) => identity.isNexusAdmin && role === 'UC Nexus Admin',
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: !identity.isNexusAdmin,
    ownsTenant: true,
    isDbAdmin: false,
    gpBuyerId: null,
    company: null,
    user: null,
  }),
}));

const PHRASE = 'reset all nexus data';

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  identity.isNexusAdmin = true;
  // The page attaches the Clerk token by hand, off the same bridge the Apollo auth link reads.
  publishAuthBridge({ isLoaded: true, isSignedIn: true, getToken: async () => 'session-token' });
  fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ status: 'ok', message: 'Schema dropped and rebuilt. Preserved 1 relay install' }),
  }));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetAuthBridge();
});

function renderPage() {
  render(
    <MemoryRouter>
      <ToastProvider>
        <ResetDataPage />
      </ToastProvider>
    </MemoryRouter>,
  );
}

function resetButton(): HTMLElement {
  // The page's own button, not the confirm dialog's - both carry the same label on purpose.
  const buttons = screen.getAllByRole('button', { name: 'Reset data' });
  return buttons[0];
}

test('a user without the UC Nexus Admin role is refused the page', () => {
  identity.isNexusAdmin = false;
  renderPage();

  expect(screen.getByText(/The UC Nexus Admin role is required\./)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Reset data' })).not.toBeInTheDocument();
});

test('the reset stays disabled until the phrase is typed exactly', () => {
  renderPage();

  expect(resetButton()).toBeDisabled();

  const field = screen.getByLabelText('Confirmation phrase');
  fireEvent.change(field, { target: { value: 'reset all nexus dat' } });
  expect(resetButton()).toBeDisabled();

  // Case matters: the phrase is shown on the page, so there is nothing to guess at.
  fireEvent.change(field, { target: { value: 'Reset All Nexus Data' } });
  expect(resetButton()).toBeDisabled();

  fireEvent.change(field, { target: { value: PHRASE } });
  expect(resetButton()).toBeEnabled();
});

test('the request fires only once the confirm is accepted', async () => {
  renderPage();

  fireEvent.change(screen.getByLabelText('Confirmation phrase'), { target: { value: PHRASE } });
  fireEvent.click(resetButton());

  // The typed phrase opens the confirm; it does not send anything on its own.
  const dialog = await screen.findByRole('dialog');
  expect(fetchMock).not.toHaveBeenCalled();

  fireEvent.click(within(dialog).getByRole('button', { name: 'Reset data' }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledWith('/admin/reset-data', {
    method: 'POST',
    headers: { Authorization: 'Bearer session-token' },
  });
  // The endpoint's own summary line is what the page reports back under the button. Scoped to that
  // panel because the toast carries the same sentence.
  const reported = (await screen.findByText('Reset finished')).closest('.MuiAlert-root');
  expect(reported).toHaveTextContent('Schema dropped and rebuilt. Preserved 1 relay install');
});

test('cancelling the confirm sends nothing', async () => {
  renderPage();

  fireEvent.change(screen.getByLabelText('Confirmation phrase'), { target: { value: PHRASE } });
  fireEvent.click(resetButton());

  const dialog = await screen.findByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(fetchMock).not.toHaveBeenCalled();
});
