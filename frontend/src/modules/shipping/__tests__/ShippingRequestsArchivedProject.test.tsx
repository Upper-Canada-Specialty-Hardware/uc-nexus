import { render, screen, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShippingRequestsPage from '../ShippingRequestsPage';
import { GET_SHIPPING_OUT_REQUESTS } from '../../../graphql/shipping';
import { GET_PROJECT, GET_PROJECTS } from '../../../graphql/shared';

/**
 * #1877: an archived project's tile links to its shipping requests with ?project=. The list scoped by
 * the id, but the picker looked the project up in `projects`, which leaves archived jobs out - so it
 * read blank over a filtered list. A project the list does not hold is read by its id instead.
 */

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    userId: 'user_1',
    roles: ['Shipping Manager'],
    hasRole: (role: string) => role === 'Shipping Manager',
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    isDbAdmin: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

const INFINITE = Number.POSITIVE_INFINITY;

const archivedProject = {
  __typename: 'Project',
  id: 'proj-old',
  projectId: '70002',
  description: 'Old Library',
  client: null,
  jobSiteName: null,
  scheduleFilename: null,
  company: 'TUBC',
  openingCount: 12,
  gpSetupOk: null,
  gpSetupCheckedAt: null,
  gpSetupIssues: [],
  gpJobState: 'CLOSED',
};

const mocks: MockedResponse[] = [
  // The picker list, without the archived project - exactly what the server answers.
  { request: { query: GET_PROJECTS }, maxUsageCount: INFINITE, result: { data: { projects: [] } } },
  {
    request: { query: GET_PROJECT, variables: { id: 'proj-old' } },
    maxUsageCount: INFINITE,
    result: { data: { project: archivedProject } },
  },
  {
    request: { query: GET_SHIPPING_OUT_REQUESTS, variables: () => true },
    maxUsageCount: INFINITE,
    result: { data: { shippingOutRequests: [] } },
  },
];

it("names an archived project in the picker when the page is scoped to it by the link", async () => {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/app/shipping/requests?project=proj-old']}>
          <ShippingRequestsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );

  expect(await screen.findByDisplayValue('Old Library')).toBeInTheDocument();
});
