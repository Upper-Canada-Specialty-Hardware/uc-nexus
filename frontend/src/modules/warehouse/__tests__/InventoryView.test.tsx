import { render, screen, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import InventoryView from '../InventoryView';
import { GET_PROJECTS } from '../../../graphql/shared';

vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

// The tab is the inventory read itself; this test is about which project the page hands it.
vi.mock('../HardwareItemsTab', () => ({
  default: ({ projectId }: { projectId?: string }) => <div data-testid="tab">{projectId ?? 'all'}</div>,
}));

// #1469: the acting company, switchable from a test the way the app bar switches it.
let actingCompany: string | null = 'TUBC';
vi.mock('../../../company/ActingCompanyContext', () => ({
  useActingCompany: () => ({ company: actingCompany }),
}));

beforeEach(() => {
  actingCompany = 'TUBC';
});

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      projects: [
        {
          __typename: 'Project',
          id: 'proj-1',
          projectId: 'J-23094',
          description: 'Harbour Tower',
          client: null,
          jobSiteName: null,
          scheduleFilename: null,
          company: 'TUBC',
          openingCount: 0,
          gpSetupOk: null,
          gpSetupCheckedAt: null,
          gpSetupIssues: [],
          gpJobState: null,
        },
      ],
    },
  },
};

function renderAt(url: string) {
  render(
    <MockedProvider mocks={[projectsMock]}>
      <MemoryRouter initialEntries={[url]}>
        <InventoryView />
      </MemoryRouter>
    </MockedProvider>,
  );
}

it('scopes to the project the url names (#1359)', async () => {
  renderAt('/app/warehouse/inventory?project=proj-1');

  expect(screen.getByTestId('tab')).toHaveTextContent('proj-1');
  expect(await screen.findByText('Harbour Tower')).toBeInTheDocument();
});

it('shows every project with no project in the url', () => {
  renderAt('/app/warehouse/inventory');

  expect(screen.getByTestId('tab')).toHaveTextContent('all');
  expect(screen.getByText('All Projects')).toBeInTheDocument();
});

function Search() {
  return <div data-testid="search">{useLocation().search}</div>;
}

// A fresh element each time: the same one again would let React skip the re-render.
const scopedPage = () => (
  <MockedProvider mocks={[projectsMock]}>
    <MemoryRouter initialEntries={['/app/warehouse/inventory?project=proj-1']}>
      <InventoryView />
      <Search />
    </MemoryRouter>
  </MockedProvider>
);

it("clears the previous company's project from the url on a company switch (#1469)", () => {
  const { rerender } = render(scopedPage());
  expect(screen.getByTestId('tab')).toHaveTextContent('proj-1');

  actingCompany = 'OTHER';
  rerender(scopedPage());

  expect(screen.getByTestId('tab')).toHaveTextContent('all');
  expect(screen.getByTestId('search')).not.toHaveTextContent('project=');
});

it('keeps the project while the company stays the same', () => {
  const { rerender } = render(scopedPage());
  rerender(scopedPage());

  expect(screen.getByTestId('tab')).toHaveTextContent('proj-1');
});
