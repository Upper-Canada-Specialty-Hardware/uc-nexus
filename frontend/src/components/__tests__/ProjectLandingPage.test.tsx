import { fireEvent, render, screen } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import ProjectLandingPage from '../ProjectLandingPage';
import { GET_PROJECTS } from '../../graphql/shared';

// #852: a company can hold thousands of jobs, most of them inactive in GP, and a card for every one
// froze the tab. The grid shows the active jobs, the rest wait behind a toggle, and a search reaches
// every job but draws a bounded number of cards.

function project(n: number, gpJobState: string | null) {
  return {
    __typename: 'Project',
    id: `p${n}`,
    projectId: `J${String(n).padStart(4, '0')}`,
    description: `Job ${n}`,
    client: null,
    jobSiteName: null,
    scheduleFilename: null,
    company: 'UCSH',
    openingCount: 0,
    gpSetupOk: true,
    gpSetupCheckedAt: null,
    gpSetupIssues: [],
    gpJobState,
  };
}

function renderLanding(projects: ReturnType<typeof project>[]) {
  const mocks: MockedResponse[] = [
    {
      request: { query: GET_PROJECTS },
      result: { data: { projects } },
      maxUsageCount: Number.POSITIVE_INFINITY,
    },
  ];
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter>
        <ProjectLandingPage title="Start a Request" onSelect={vi.fn()} />
      </MemoryRouter>
    </MockedProvider>,
  );
}

const cards = () => screen.queryAllByText(/^Job \d+$/);
const search = () => screen.getByPlaceholderText('Search projects by name, number, client or job site');

it('shows the active jobs and keeps the inactive ones behind a toggle', async () => {
  renderLanding([
    ...[1, 2, 3, 4, 5, 6, 7].map((n) => project(n, 'ACTIVE')),
    ...[8, 9, 10].map((n) => project(n, 'INACTIVE')),
  ]);

  await screen.findByText('Job 1');
  expect(cards()).toHaveLength(7);
  expect(screen.queryByText('Job 8')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Show inactive jobs (3)' }));
  expect(cards()).toHaveLength(10);

  fireEvent.click(screen.getByRole('button', { name: 'Hide inactive jobs' }));
  expect(cards()).toHaveLength(7);
});

it('finds an inactive job by search without the toggle', async () => {
  renderLanding([
    ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => project(n, 'ACTIVE')),
    project(9, 'INACTIVE'),
  ]);

  await screen.findByText('Job 1');
  fireEvent.change(search(), { target: { value: 'J0009' } });

  expect(cards()).toHaveLength(1);
  expect(screen.getByText('Job 9')).toBeInTheDocument();
});

it('draws at most 100 cards for a search and says to keep typing', async () => {
  renderLanding(Array.from({ length: 150 }, (_, i) => project(i + 1, 'INACTIVE')));

  await screen.findByRole('button', { name: 'Show inactive jobs (150)' });
  fireEvent.change(search(), { target: { value: 'job' } });

  expect(cards()).toHaveLength(100);
  expect(screen.getByText('Showing 100 of 150 matches. Keep typing to narrow.')).toBeInTheDocument();
});

it('says so when no job is active, rather than showing an empty grid', async () => {
  renderLanding([project(1, 'INACTIVE'), project(2, 'CLOSED')]);

  expect(
    await screen.findByText('No job here is active in GP. Show inactive jobs to see the 2 that are not.'),
  ).toBeInTheDocument();
  expect(cards()).toHaveLength(0);
});
