import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import ImportModule from '../index';
import { GET_PROJECTS } from '../../../graphql/shared';

// What the module screens' "Start a Request" buttons hand over (#471), and what the keep-or-ship
// decision has handed over since #447. Both arrive as URL params, so this is about the seam between
// the link and the wizard's props - the wizard's own handling of initialPurpose is pinned in
// ImportWizard.test.tsx and deliberately not re-tested here.

vi.mock('../../../hooks/useIdentity', () => ({
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

// The real wizard spawns a parser worker and fires half a dozen queries. Only the props it is handed
// matter here, so it is replaced by a probe that prints them.
vi.mock('../ImportWizard', () => ({
  default: ({
    open,
    project,
    initialPurpose,
    initialSelectionMode,
    autoStartFromLatest,
  }: {
    open: boolean;
    project: { id: string };
    initialPurpose?: string;
    initialSelectionMode?: string;
    autoStartFromLatest?: boolean;
  }) =>
    open ? (
      <div data-testid="wizard">
        {`project=${project.id} purpose=${initialPurpose ?? 'none'} latest=${String(!!autoStartFromLatest)} mode=${initialSelectionMode ?? 'openings'}`}
      </div>
    ) : null,
}));

function project(id: string, description: string) {
  return {
    __typename: 'Project',
    id,
    projectId: `JOB-${id}`,
    description,
    client: null,
    jobSiteName: null,
    openingCount: 4,
    gpSetupOk: true,
    gpSetupCheckedAt: null,
    gpSetupIssues: null,
  };
}

function projectsMock(): MockedResponse {
  return {
    request: { query: GET_PROJECTS },
    result: { data: { projects: [project('proj-1', 'Riverside Tower'), project('proj-2', 'Bay Mills')] } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

/** Prints wherever the router ended up, so "the param was consumed" is an assertion about the URL. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

/**
 * Clearing the params is a router navigation, which React Router lands in a later commit than the
 * state the same effect set - so waiting is the assertion, not a workaround for a flaky one.
 */
async function expectParamsCleared() {
  await vi.waitFor(
    () => expect(screen.getByTestId('location')).toHaveTextContent(/^\/app\/import$/),
    { timeout: 5000 },
  );
}

function renderModule(entry: string) {
  render(
    <MockedProvider mocks={[projectsMock()]}>
      <MemoryRouter initialEntries={[entry]}>
        <ImportModule />
        <LocationProbe />
      </MemoryRouter>
    </MockedProvider>,
  );
}

const SLOW = { timeout: 5000 };

vi.setConfig({ testTimeout: 30_000 });

describe('ImportModule deep links', () => {
  it('holds a purpose that arrived without a project until one is picked', async () => {
    renderModule('/app/import?purpose=po');

    // Nothing to open on yet: the module button knows what the user came to raise, not which job.
    await screen.findByText('Riverside Tower', undefined, SLOW);
    expect(screen.queryByTestId('wizard')).not.toBeInTheDocument();
    await expectParamsCleared();

    fireEvent.click(screen.getByRole('button', { name: /Riverside Tower/ }));

    expect(await screen.findByTestId('wizard', undefined, SLOW)).toHaveTextContent(
      'project=proj-1 purpose=po latest=false',
    );
  });

  it('opens straight onto the project when the link names one', async () => {
    renderModule('/app/import?projectId=proj-2&purpose=shipping&source=latest');

    expect(await screen.findByTestId('wizard', undefined, SLOW)).toHaveTextContent(
      'project=proj-2 purpose=shipping latest=true',
    );
    await expectParamsCleared();
  });

  // #565: the "by hardware" chooser card links `?purpose=po&mode=hardware` with no project. The mode
  // has to survive the pick-a-project fall-through so the wizard opens in the hardware pathway.
  it('carries the by-hardware selection mode through the project picker', async () => {
    renderModule('/app/import?purpose=po&mode=hardware');

    await screen.findByText('Riverside Tower', undefined, SLOW);
    expect(screen.queryByTestId('wizard')).not.toBeInTheDocument();
    await expectParamsCleared();

    fireEvent.click(screen.getByRole('button', { name: /Riverside Tower/ }));

    expect(await screen.findByTestId('wizard', undefined, SLOW)).toHaveTextContent(
      'project=proj-1 purpose=po latest=false mode=hardware',
    );
  });

  // A link with no mode is the by-opening pathway - the default the wizard has always run.
  it('defaults to the by-opening mode when the link names none', async () => {
    renderModule('/app/import?projectId=proj-2&purpose=po');

    expect(await screen.findByTestId('wizard', undefined, SLOW)).toHaveTextContent(
      'project=proj-2 purpose=po latest=false mode=openings',
    );
  });

  it('lands on the picker when the link names a project that no longer exists', async () => {
    // A stale link. Opening the wizard on the wrong job would be worse than asking again, and the
    // purpose it carried is still good, so it survives the fall-through.
    renderModule('/app/import?projectId=gone&purpose=assembly');

    await screen.findByText('Riverside Tower', undefined, SLOW);
    expect(screen.queryByTestId('wizard')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Bay Mills/ }));

    expect(await screen.findByTestId('wizard', undefined, SLOW)).toHaveTextContent(
      'project=proj-2 purpose=assembly latest=false',
    );
  });

  it('ignores a purpose it does not recognise', async () => {
    renderModule('/app/import?purpose=nonsense');

    await screen.findByText('Riverside Tower', undefined, SLOW);
    fireEvent.click(screen.getByRole('button', { name: /Riverside Tower/ }));

    expect(await screen.findByTestId('wizard', undefined, SLOW)).toHaveTextContent(
      'project=proj-1 purpose=none latest=false',
    );
  });
});
