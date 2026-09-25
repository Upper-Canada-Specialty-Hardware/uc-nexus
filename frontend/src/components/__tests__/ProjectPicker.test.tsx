import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import ProjectPicker from '../ProjectPicker';
import { GET_PROJECTS, GET_RELAY_STATUS } from '../../graphql/shared';
import type { Project } from '../../types/project';

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    roles: [],
    hasRole: () => false,
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

const INFINITE = Number.POSITIVE_INFINITY;

// Neither name carries its own number, so a search that hits one from the other can only have come
// from the number being searched too.
const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      projects: [
        {
          id: 'p1',
          projectId: 'JOB-100',
          description: 'Main St Job',
          client: 'ACME',
          jobSiteName: 'Main St',
          company: 'TUBC',
          openingCount: 3,
          __typename: 'Project',
        },
        {
          id: 'p2',
          projectId: 'JOB-200',
          description: 'Elm St Job',
          client: 'ACME',
          jobSiteName: 'Elm St',
          company: 'TUBC',
          openingCount: 2,
          __typename: 'Project',
        },
      ],
    },
  },
};

// The text has to be typed into a focused input: unfocused, MUI wipes it back to the selected option
// the next time anything re-renders.
function typeInto(input: HTMLElement, text: string) {
  input.focus();
  fireEvent.change(input, { target: { value: text } });
}

function renderPicker() {
  const onChange = vi.fn();
  render(
    <MockedProvider mocks={[projectsMock]}>
      <ProjectPicker value={null} onChange={onChange} placeholder="Type to search projects…" />
    </MockedProvider>,
  );
  return { onChange };
}

describe('ProjectPicker', () => {
  it('finds a project by its number', async () => {
    const { onChange } = renderPicker();

    typeInto(screen.getByLabelText('Project'), 'JOB-200');

    fireEvent.click(await screen.findByText('Elm St Job'));
    expect(screen.queryByText('Main St Job')).toBeNull();
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'p2' }));
  });

  it('finds a project by its name', async () => {
    const { onChange } = renderPicker();

    typeInto(screen.getByLabelText('Project'), 'Main St');

    fireEvent.click(await screen.findByText('Main St Job'));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'p1' }));
  });

  // #689: the label used to sit inside the empty field, printing on top of the placeholder. Held in
  // the outline notch it cannot, and the placeholder reads as the hint it is meant to be.
  it('keeps the label out of the placeholder while the field is empty and unfocused', () => {
    renderPicker();

    // The notched outline carries the same words in its legend, so the label itself is asked for.
    expect(screen.getByText('Project', { selector: 'label' })).toHaveAttribute('data-shrink', 'true');
    expect(screen.getByPlaceholderText('Type to search projects…')).toBeInTheDocument();
  });
});

// #730: one open, one closed, one inactive and one missing job, plus one never mirrored.
const jobStatesMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      projects: [
        ['p1', 'JOB-100', 'Open Job', 'ACTIVE'],
        ['p2', 'JOB-200', 'Closed Job', 'CLOSED'],
        ['p3', 'JOB-300', 'Inactive Job', 'INACTIVE'],
        ['p4', 'JOB-400', 'Missing Job', 'NOT_IN_GP'],
        ['p5', 'JOB-500', 'Unmirrored Job', null],
      ].map(([id, projectId, description, gpJobState]) => ({
        id,
        projectId,
        description,
        client: null,
        jobSiteName: null,
        company: 'TUBC',
        openingCount: 0,
        gpJobState,
        __typename: 'Project',
      })),
    },
  },
};

function openOptions(gpBound: boolean) {
  const onChange = vi.fn();
  render(
    <MockedProvider mocks={[jobStatesMock]}>
      <ProjectPicker value={null} onChange={onChange} gpBound={gpBound} />
    </MockedProvider>,
  );
  typeInto(screen.getByLabelText('Project'), 'Job');
  return { onChange };
}

const optionFor = async (name: string) => (await screen.findByText(name)).closest('li')!;

describe('ProjectPicker GP job state (#730)', () => {
  it('tags every job that is not open in GP, and nothing else', async () => {
    openOptions(false);

    expect(within(await optionFor('Closed Job')).getByText('Closed in GP')).toBeInTheDocument();
    expect(within(await optionFor('Inactive Job')).getByText('Inactive in GP')).toBeInTheDocument();
    expect(within(await optionFor('Missing Job')).getByText('Not in GP')).toBeInTheDocument();
    expect(within(await optionFor('Open Job')).queryByTestId('gp-job-state-tag')).toBeNull();
    expect(within(await optionFor('Unmirrored Job')).queryByTestId('gp-job-state-tag')).toBeNull();
  });

  it('keeps them pickable where the pick does not write to GP', async () => {
    const { onChange } = openOptions(false);

    const closed = await optionFor('Closed Job');
    expect(closed).not.toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(closed);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'p2' }));
  });

  it('greys them out in a GP-bound picker, leaving open and unmirrored jobs pickable', async () => {
    openOptions(true);

    for (const name of ['Closed Job', 'Inactive Job', 'Missing Job']) {
      expect(await optionFor(name)).toHaveAttribute('aria-disabled', 'true');
    }
    for (const name of ['Open Job', 'Unmirrored Job']) {
      expect(await optionFor(name)).not.toHaveAttribute('aria-disabled', 'true');
    }
  });
});

// #831: GP's name for the one company, as the relay reports it.
const relayMock: MockedResponse = {
  request: { query: GET_RELAY_STATUS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      relayStatus: {
        connected: true,
        companies: ['TUBC'],
        gpCompanies: [{ id: 'TUBC', name: 'Test UBC', __typename: 'GpCompany' }],
        companiesError: null,
        build: null,
        installId: null,
        lastConnectedAt: null,
        lastDisconnectedAt: null,
        lastDisconnectReason: null,
        previewChannels: [],
        __typename: 'RelayStatus',
      },
    },
  },
};

const picked = {
  id: 'p1',
  projectId: 'JOB-100',
  description: 'Main St Job',
  client: 'ACME',
  jobSiteName: 'Main St',
  company: 'TUBC',
  openingCount: 3,
} as unknown as Project;

describe('ProjectPicker GP company (#831)', () => {
  // #845: every project offered is in the one acting company the app bar names, so a tag per option
  // only repeated it.
  it('tags no option with a GP company', async () => {
    render(
      <MockedProvider mocks={[projectsMock, relayMock]}>
        <ProjectPicker value={null} onChange={vi.fn()} />
      </MockedProvider>,
    );
    typeInto(screen.getByLabelText('Project'), 'Job');

    for (const name of ['Main St Job', 'Elm St Job']) {
      const option = await optionFor(name);
      expect(within(option).queryByTestId('gp-company-tag')).toBeNull();
    }
  });

  it("names the chosen project's GP company under the field, above the caller's own line", async () => {
    render(
      <MockedProvider mocks={[projectsMock, relayMock]}>
        <ProjectPicker value={picked} onChange={vi.fn()} helperText="Something the caller says" />
      </MockedProvider>,
    );

    expect(screen.getByText('GP company')).toBeInTheDocument();
    expect(await screen.findByTitle('GP company: TUBC - Test UBC')).toBeInTheDocument();
    expect(screen.getByText('Something the caller says')).toBeInTheDocument();
  });

  it('leaves the chosen company out where the screen already names it', () => {
    render(
      <MockedProvider mocks={[projectsMock, relayMock]}>
        <ProjectPicker value={picked} onChange={vi.fn()} showSelectedCompany={false} />
      </MockedProvider>,
    );

    expect(screen.queryByText('GP company')).toBeNull();
  });
});
