import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Outlet, useLocation } from 'react-router-dom';
import App from '../App';

/**
 * #729: the Admin module became two, and the old paths must not become dead links.
 *
 * Every /app/admin URL anyone ever bookmarked, mailed or pasted into an issue lands on the Tenant
 * Owner landing, which holds the company-facing pages that made up most of the old module. Without
 * the catch-all the app's own "*" rule would silently send them to Home instead.
 */
vi.mock('@clerk/clerk-react', () => ({
  SignedIn: ({ children }: { children: ReactNode }) => <>{children}</>,
  SignedOut: () => null,
  RedirectToSignIn: () => null,
  SignIn: () => null,
}));

vi.mock('../components/AppLayout', () => ({
  default: function AppLayoutStub() {
    const location = useLocation();
    return (
      <>
        <div data-testid="path">{location.pathname}</div>
        <Outlet />
      </>
    );
  },
}));

vi.mock('../modules/tenant-owner', () => ({
  default: () => <div>tenant owner module</div>,
}));

vi.mock('../modules/nexus-admin', () => ({
  default: () => <div>uc nexus admin module</div>,
}));

async function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  // The modules are lazy, so the first frame is the skeleton fallback.
  return screen.findByTestId('path');
}

it('sends a bookmarked Admin page to the Tenant Owner landing', async () => {
  await renderAt('/app/admin/projects');

  expect(await screen.findByText('tenant owner module')).toBeInTheDocument();
  expect(screen.getByTestId('path')).toHaveTextContent('/app/tenant-owner');
});

it('sends the bare Admin path to the Tenant Owner landing too', async () => {
  await renderAt('/app/admin');

  expect(await screen.findByText('tenant owner module')).toBeInTheDocument();
  expect(screen.getByTestId('path')).toHaveTextContent('/app/tenant-owner');
});

it('mounts the UC Nexus Admin module on its own path', async () => {
  await renderAt('/app/nexus-admin/relay-installs');

  expect(await screen.findByText('uc nexus admin module')).toBeInTheDocument();
  expect(screen.getByTestId('path')).toHaveTextContent('/app/nexus-admin/relay-installs');
});
