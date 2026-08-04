import { render, screen, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import GpSetupQuarantineBanner, { GpSetupBadge } from '../GpSetupQuarantineBanner';
import { ToastProvider } from '../Toast';
import { isGpSetupBroken, type GpSetupStatus } from '../../types/project';
import StagingWorkspace from '../../modules/shipping/StagingWorkspace';
import { GET_STAGING_POOL } from '../../graphql/shipping';

// StagingWorkspace mounts the confirm form (closed), which reaches for Clerk and the PDF renderer.
// Neither runs under jsdom and neither is what is under test here.
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
 * That action is now "Ship n containers" on the staging workspace (#451), which replaced the cart.
 */
describe('Staging workspace under quarantine', () => {
  const PROJECT_ID = 'p1';

  // A loaded container, selected. An empty workspace already disables the ship button, so asserting
  // on an empty one would pass whether the quarantine were wired up or not - the healthy control
  // below is what makes the blocked case mean anything.
  function poolMock(): MockedResponse {
    return {
      request: { query: GET_STAGING_POOL, variables: { projectId: PROJECT_ID } },
      maxUsageCount: Number.POSITIVE_INFINITY,
      result: {
        data: {
          stagingPool: {
            __typename: 'StagingPool',
            leaves: [],
            looseItems: [],
            containers: [
              {
                __typename: 'ShipmentContainer',
                id: 'c-1',
                projectId: PROJECT_ID,
                containerType: 'BOX',
                name: 'Box 1',
                packingSlipId: null,
                createdBy: 'tester',
                items: [
                  {
                    __typename: 'ShipmentContainerItem',
                    id: 'ci-1',
                    itemType: 'LOOSE',
                    openingItemId: null,
                    openingNumber: 'A01',
                    leaf: null,
                    hardwareCategory: 'HINGE',
                    productCode: 'HG-100',
                    quantity: 1,
                    position: 0,
                  },
                ],
              },
            ],
          },
        },
      },
    };
  }

  async function renderWorkspace(project: GpSetupStatus | null) {
    render(
      <MockedProvider mocks={[poolMock()]}>
        <MemoryRouter>
          <ToastProvider>
            <StagingWorkspace projectId={PROJECT_ID} project={project} />
          </ToastProvider>
        </MemoryRouter>
      </MockedProvider>,
    );
    // Select the container, or the ship button is disabled for having nothing on the truck.
    const include = await screen.findByRole('checkbox', { name: /Include Box 1/i });
    include.click();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Ship 1 container/i })).toBeInTheDocument(),
    );
  }

  it('disables the shipment on a quarantined project and explains why', async () => {
    await renderWorkspace(BROKEN);

    expect(screen.getByTestId('gp-setup-quarantine-banner')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ship 1 container/i })).toBeDisabled();
  });

  it('leaves a loaded container shippable when the project has never been checked', async () => {
    await renderWorkspace({ projectId: '23090', gpSetupOk: null });

    expect(screen.queryByTestId('gp-setup-quarantine-banner')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ship 1 container/i })).toBeEnabled();
  });
});
