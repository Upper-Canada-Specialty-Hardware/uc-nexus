import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ProjectLandingPage from '../ProjectLandingPage';

// #1584: Apollo keeps the last read beside a failed refresh and sets `loading` on a refetch. The landing page
// used to swap its cards for skeletons on every refetch and for a bare error when a refresh failed.

type QueryState = { data?: unknown; loading: boolean; error?: Error };
let state: QueryState;
const refetch = vi.fn(() => Promise.resolve());

vi.mock('@apollo/client/react', () => ({
  useQuery: () => ({ ...state, refetch }),
  useMutation: () => [vi.fn(), { loading: false }],
}));

const projects = {
  projects: [
    {
      __typename: 'Project',
      id: 'p1',
      projectId: 'J0001',
      description: 'Harbour Tower',
      client: null,
      jobSiteName: null,
      scheduleFilename: null,
      company: 'TUBC',
      openingCount: 0,
      gpSetupOk: true,
      gpSetupCheckedAt: null,
      gpSetupIssues: [],
      gpJobState: 'ACTIVE',
    },
  ],
};

const renderLanding = () =>
  render(
    <MemoryRouter>
      <ProjectLandingPage title="Start a Request" onSelect={vi.fn()} />
    </MemoryRouter>,
  );

it('keeps the project cards while a refetch runs', () => {
  state = { data: projects, loading: true };
  renderLanding();
  expect(screen.getByText('Harbour Tower')).toBeInTheDocument();
});

it('keeps the project cards when a refresh fails, with a note', () => {
  state = { data: projects, loading: false, error: new TypeError('Failed to fetch') };
  renderLanding();
  expect(screen.getByText('Harbour Tower')).toBeInTheDocument();
  expect(screen.getByText(/Couldn.t refresh the projects/)).toBeInTheDocument();
});

it('offers a retry when the projects never loaded', () => {
  state = { loading: false, error: new TypeError('Failed to fetch') };
  renderLanding();
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(refetch).toHaveBeenCalled();
});
