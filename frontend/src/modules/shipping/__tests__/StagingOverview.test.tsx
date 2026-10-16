import { render, screen, fireEvent, within } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import StagingOverview from '../StagingOverview';
import { GET_STAGING_OVERVIEW } from '../../../graphql/shipping';

/** The staging page before a project is picked (#1698): every project's staged floor, grouped. */

function line(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'StagedLooseItem',
    openingNumber: '101',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    stagedQuantity: 4,
    placedQuantity: 1,
    unplacedQuantity: 3,
    ...overrides,
  };
}

function summary(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'StagingProjectSummary',
    projectId: 'proj-1',
    projectNumber: '22966',
    projectDescription: 'Harbour Tower',
    openContainerCount: 1,
    looseItems: [line()],
    ...overrides,
  };
}

function mockOverview(rows: unknown[]): MockedResponse {
  return { request: { query: GET_STAGING_OVERVIEW }, result: { data: { stagingOverview: rows } } };
}

function renderOverview(mocks: MockedResponse[], onOpen = vi.fn()) {
  render(
    <MockedProvider mocks={mocks}>
      <StagingOverview onOpen={onOpen} />
    </MockedProvider>,
  );
  return onOpen;
}

it('shows every project with something staged, each with its own lines', async () => {
  renderOverview([
    mockOverview([
      summary(),
      summary({
        projectId: 'proj-2',
        projectNumber: '23001',
        projectDescription: 'School Annex',
        openContainerCount: 0,
        looseItems: [line({ openingNumber: '205', hardwareCategory: 'CLOSER', productCode: 'CL-200', stagedQuantity: 2, placedQuantity: 0, unplacedQuantity: 2 })],
      }),
    ]),
  ]);

  const first = await screen.findByTestId('staging-group-proj-1');
  expect(within(first).getByText('Harbour Tower')).toBeInTheDocument();
  expect(within(first).getByText('22966')).toBeInTheDocument();
  expect(within(first).getByText('HG-100')).toBeInTheDocument();
  expect(within(first).getByText(/4 units staged · 3 loose · 1 open container/)).toBeInTheDocument();

  const second = screen.getByTestId('staging-group-proj-2');
  expect(within(second).getByText('CL-200')).toBeInTheDocument();
  expect(within(second).queryByText('HG-100')).not.toBeInTheDocument();
  expect(screen.getByText(/Staged across 2 projects/)).toBeInTheDocument();
});

it('opens the project a group belongs to', async () => {
  const onOpen = renderOverview([mockOverview([summary()])]);

  const group = await screen.findByTestId('staging-group-proj-1');
  fireEvent.click(within(group).getByRole('button', { name: 'Open' }));

  expect(onOpen).toHaveBeenCalledWith('proj-1');
});

it('says nothing is staged rather than showing a blank page', async () => {
  renderOverview([mockOverview([])]);

  expect(await screen.findByText(/Nothing is staged/)).toBeInTheDocument();
});

it('names a project by its job number when it has no description', async () => {
  renderOverview([mockOverview([summary({ projectDescription: null })])]);

  const group = await screen.findByTestId('staging-group-proj-1');
  expect(within(group).getByText('22966')).toBeInTheDocument();
});
