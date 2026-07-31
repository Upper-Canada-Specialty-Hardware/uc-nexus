import { useEffect } from 'react';
import { render, screen } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import GpSetupQuarantineBanner, { GpSetupBadge } from '../GpSetupQuarantineBanner';
import { ToastProvider } from '../Toast';
import { isGpSetupBroken, type GpSetupStatus } from '../../types/project';
import ShippingCart from '../../modules/shipping/ShippingCart';
import { CartProvider, useCart } from '../../contexts/CartContext';

// ShippingCart mounts DeliveryRequestForm (closed), which reaches for Clerk and the PDF renderer.
// Neither runs under jsdom and neither is what is under test here - same two stubs
// DeliveryRequestForm's own suite installs.
vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Me',
    userId: 'me',
    roles: [],
    hasRole: () => false,
    isAdmin: false,
    gpBuyerId: null,
    user: null,
  }),
}));

vi.mock('@react-pdf/renderer', () => ({
  pdf: () => ({ toBlob: () => Promise.resolve(new Blob()) }),
  Document: () => null,
  Page: () => null,
  Text: () => null,
  View: () => null,
  StyleSheet: { create: (s: unknown) => s },
}));

/**
 * The GP setup quarantine surface (#425).
 *
 * The rule that has to hold in both directions:
 *   gpSetupOk === false  -> banner, badge, actions off
 *   true / null / absent -> nothing at all
 *
 * The null case is the one worth the test. The verdict only exists while a relay is connected, so if
 * "never checked" rendered as "broken", a relay restart would put a red stop banner on every project
 * in the application and disable actions that have nothing to do with GP.
 */

const BROKEN: GpSetupStatus = {
  projectId: '23093',
  gpSetupOk: false,
  gpSetupIssues: [
    { costCode: '210-200-2', accountIndex: 1617 },
    { costCode: '310-000-3', accountIndex: 1622 },
  ],
};

describe('isGpSetupBroken', () => {
  it('is true only for an explicit false verdict', () => {
    expect(isGpSetupBroken({ gpSetupOk: false })).toBe(true);
    expect(isGpSetupBroken({ gpSetupOk: true })).toBe(false);
    expect(isGpSetupBroken({ gpSetupOk: null })).toBe(false);
    expect(isGpSetupBroken({})).toBe(false);
    expect(isGpSetupBroken(null)).toBe(false);
    expect(isGpSetupBroken(undefined)).toBe(false);
  });
});

describe('GpSetupQuarantineBanner', () => {
  it('names the job, every broken cost code and the account index it points at', () => {
    render(<GpSetupQuarantineBanner project={BROKEN} action="registering it in GP" />);

    expect(screen.getByTestId('gp-setup-quarantine-banner')).toBeInTheDocument();
    expect(screen.getByText(/GP job 23093 is not set up correctly/)).toBeInTheDocument();
    expect(screen.getByText('210-200-2')).toBeInTheDocument();
    expect(screen.getByText(/GL account index 1617/)).toBeInTheDocument();
    expect(screen.getByText('310-000-3')).toBeInTheDocument();
    expect(screen.getByText(/GL account index 1622/)).toBeInTheDocument();
    // The action being blocked is named, so the banner reads as an explanation of the dead button.
    expect(screen.getByText(/registering it in GP is on hold/)).toBeInTheDocument();
  });

  it('caps a long list and says how many were hidden', () => {
    const many = Array.from({ length: 24 }, (_, i) => ({
      costCode: `3${String(i).padStart(2, '0')}-000-3`,
      accountIndex: 1600 + i,
    }));
    render(<GpSetupQuarantineBanner project={{ gpSetupOk: false, gpSetupIssues: many }} />);

    expect(screen.getByText('and 18 more')).toBeInTheDocument();
  });

  it('still renders when the backend recorded no detail', () => {
    render(<GpSetupQuarantineBanner project={{ projectId: '23093', gpSetupOk: false }} />);

    expect(screen.getByTestId('gp-setup-quarantine-banner')).toBeInTheDocument();
    expect(
      screen.getByText(/cost codes point at general ledger accounts that do not exist/),
    ).toBeInTheDocument();
  });

  it('renders nothing for a healthy project', () => {
    render(<GpSetupQuarantineBanner project={{ gpSetupOk: true }} />);
    expect(screen.queryByTestId('gp-setup-quarantine-banner')).not.toBeInTheDocument();
  });

  it('renders nothing for a project that has never been checked', () => {
    // A relay that has not answered yet must not look like a broken job.
    render(<GpSetupQuarantineBanner project={{ gpSetupOk: null }} />);
    expect(screen.queryByTestId('gp-setup-quarantine-banner')).not.toBeInTheDocument();
  });

  it('renders nothing when there is no project at all', () => {
    render(<GpSetupQuarantineBanner project={null} />);
    expect(screen.queryByTestId('gp-setup-quarantine-banner')).not.toBeInTheDocument();
  });
});

describe('GpSetupBadge', () => {
  it('marks a quarantined project in a list', () => {
    render(<GpSetupBadge project={BROKEN} />);
    expect(screen.getByTestId('gp-setup-badge')).toHaveTextContent('GP setup broken');
  });

  it('stays out of the way for healthy and unchecked projects', () => {
    const { rerender } = render(<GpSetupBadge project={{ gpSetupOk: true }} />);
    expect(screen.queryByTestId('gp-setup-badge')).not.toBeInTheDocument();

    rerender(<GpSetupBadge project={{ gpSetupOk: null }} />);
    expect(screen.queryByTestId('gp-setup-badge')).not.toBeInTheDocument();
  });
});

/**
 * One real screen, to prove the banner is wired to an action and not just rendered next to one.
 * Shipping out is the last stage of the pipeline and the point of no return - hardware leaves the
 * building against a job whose costs cannot be booked - so its primary action is the one to pin.
 */
describe('ShippingCart under quarantine', () => {
  /**
   * The cart is loaded first. An empty cart already disables Proceed to Ship, so asserting on an
   * empty one would pass whether the quarantine were wired up or not - the healthy control below is
   * what makes the blocked case mean anything.
   */
  function LoadedCart({ project }: { project: GpSetupStatus | null }) {
    const { addItem, itemCount } = useCart();
    useEffect(() => {
      if (itemCount === 0) {
        addItem({ id: 'c1', itemType: 'Loose', openingNumber: 'A01', productCode: 'HG-100', quantity: 1 });
      }
    }, [addItem, itemCount]);
    if (itemCount === 0) return null;
    return (
      <ShippingCart open onClose={() => {}} projectId="p1" projectName="Broken Job" project={project} />
    );
  }

  function renderCart(project: GpSetupStatus | null) {
    return render(
      <MockedProvider mocks={[]}>
        <MemoryRouter>
          <ToastProvider>
            <CartProvider>
              <LoadedCart project={project} />
            </CartProvider>
          </ToastProvider>
        </MemoryRouter>
      </MockedProvider>,
    );
  }

  it('disables Proceed to Ship on a quarantined project and explains why', () => {
    renderCart(BROKEN);

    expect(screen.getByTestId('gp-setup-quarantine-banner')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Proceed to Ship' })).toBeDisabled();
  });

  it('leaves a loaded cart shippable when the project has never been checked', () => {
    renderCart({ projectId: '23090', gpSetupOk: null });

    expect(screen.queryByTestId('gp-setup-quarantine-banner')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Proceed to Ship' })).toBeEnabled();
  });
});
