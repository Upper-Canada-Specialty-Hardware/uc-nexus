import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import PullStagingPanel from '../PullStagingPanel';
import { isStageable, stagingChipColor, stagingChipLabel, isCancellable } from '../pullStaging';
import { GET_PULL_REQUEST_OPENINGS, STAGE_PULL_OPENINGS } from '../../../graphql/warehouse';

/**
 * Per-leaf pull staging (#343, laid out as sections in #367). The warehouse picks a pull cart by
 * cart, so the checklist's unit of confirmation is one door leaf and its hardware lines. Confirming
 * is a two-step (tick, then Confirm) because staging is a claim that hardware is physically on a
 * cart.
 */

vi.setConfig({ testTimeout: 30_000 });

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Picker',
    userId: 'picker',
    roles: [],
    hasRole: () => false,
    isAdmin: false,
    gpBuyerId: null,
    user: null,
  }),
}));

function opening(overrides: Record<string, unknown> = {}) {
  return {
    id: 'sao-1',
    pullRequestId: 'pr-1',
    openingId: 'op-1',
    openingNumber: '0019-EX',
    leaf: 1,
    building: 'A',
    floor: '2',
    pullStatus: 'NOT_PULLED',
    assemblyStatus: 'PENDING',
    assignedToUserId: null,
    assignedTo: null,
    stagedAt: null,
    stagedBy: null,
    items: [
      {
        id: 'sai-1',
        shopAssemblyOpeningId: 'sao-1',
        hardwareCategory: 'HINGE',
        productCode: 'HG-100',
        quantity: 3,
        allocatedQuantity: 3,
      },
    ],
    ...overrides,
  };
}

function openingsMock(rows: unknown[]): MockedResponse {
  return {
    request: { query: GET_PULL_REQUEST_OPENINGS, variables: { pullRequestId: 'pr-1' } },
    result: { data: { pullRequestOpenings: rows } },
    maxUsageCount: 5,
  };
}

function stageMock(openingIds: string[], completed: boolean, resulting: unknown[]): MockedResponse {
  return {
    request: {
      query: STAGE_PULL_OPENINGS,
      variables: { input: { pullRequestId: 'pr-1', openingIds, stagedBy: 'Picker' } },
    },
    result: {
      data: {
        stagePullOpenings: {
          pullRequest: {
            id: 'pr-1',
            requestNumber: 'PR-SA-0001',
            projectId: 'p1',
            source: 'SHOP_ASSEMBLY',
            status: completed ? 'COMPLETED' : 'IN_PROGRESS',
            requestedBy: 'importer',
            assignedTo: 'Picker',
            createdAt: '2026-07-01T00:00:00Z',
            updatedAt: '2026-07-01T00:00:00Z',
            approvedAt: '2026-07-01T00:00:00Z',
            completedAt: completed ? '2026-07-02T00:00:00Z' : null,
            cancelledAt: null,
            cancelledBy: null,
            cancellationReason: null,
            stagingStatus: completed ? 'PULLED' : 'PARTIAL',
            stagedOpeningCount: completed ? 2 : 1,
            totalOpeningCount: 2,
            items: [],
          },
          openings: resulting,
          newlyStagedOpeningIds: openingIds,
          completed,
        },
      },
    },
  };
}

function renderPanel(mocks: MockedResponse[], editable = true) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <PullStagingPanel
          pullRequestId="pr-1"
          pullRequestNumber="PR-SA-0001"
          editable={editable}
        />
      </ToastProvider>
    </MockedProvider>,
  );
}

// --- the checklist -----------------------------------------------------------------------------

it('groups the pull by opening and lists that opening s hardware lines', async () => {
  renderPanel([openingsMock([opening(), opening({ id: 'sao-2', leaf: 2 })])]);

  expect(await screen.findByText(/Stage carts \(0 of 2 leaves\)/)).toBeInTheDocument();
  expect(screen.getAllByText(/0019-EX/)).toHaveLength(2);
  // #367: a section per leaf, hardware as ledger rows beneath it - not a bulleted list in a cell.
  expect(screen.getAllByText('HG-100')).toHaveLength(2);
  expect(screen.getAllByText('HINGE')).toHaveLength(2);
});

it('shows a staged opening as staged, with who staged it, and does not offer it again', async () => {
  renderPanel([
    openingsMock([
      opening({ pullStatus: 'PULLED', stagedBy: 'Ada', stagedAt: '2026-07-02T09:00:00Z' }),
      opening({ id: 'sao-2', leaf: 2 }),
    ]),
  ]);

  expect(await screen.findByText(/Stage carts \(1 of 2 leaves\)/)).toBeInTheDocument();
  expect(screen.getByText('Staged')).toBeInTheDocument();
  expect(screen.getByText(/Ada/)).toBeInTheDocument();
  // The already-staged row's checkbox is disabled; only the outstanding one can be ticked.
  const boxes = screen.getAllByRole('checkbox');
  expect(boxes[0]).toBeDisabled();
  expect(boxes[1]).toBeEnabled();
});

it('will not confirm anything until an opening is ticked', async () => {
  renderPanel([openingsMock([opening()])]);
  const confirm = await screen.findByRole('button', { name: /Confirm 0 staged/ });
  expect(confirm).toBeDisabled();
});

it('confirms behind a dialog rather than staging on the tick', async () => {
  renderPanel([openingsMock([opening(), opening({ id: 'sao-2', leaf: 2 })])]);
  fireEvent.click(await screen.findByRole('checkbox', { name: /Stage 0019-EX . L1/ }));

  fireEvent.click(screen.getByRole('button', { name: /Confirm 1 staged/ }));
  expect(await screen.findByText('Confirm staged openings')).toBeInTheDocument();
  expect(
    screen.getByText(/They become available for assembly immediately/),
  ).toBeInTheDocument();
});

it('stages the ticked opening and says the rest of the pull is still outstanding', async () => {
  renderPanel([
    openingsMock([opening(), opening({ id: 'sao-2', leaf: 2 })]),
    stageMock(['sao-1'], false, [
      opening({ pullStatus: 'PULLED', stagedBy: 'Picker', stagedAt: '2026-07-02T09:00:00Z' }),
      opening({ id: 'sao-2', leaf: 2 }),
    ]),
  ]);
  fireEvent.click(await screen.findByRole('checkbox', { name: /Stage 0019-EX . L1/ }));
  fireEvent.click(screen.getByRole('button', { name: /Confirm 1 staged/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm staged' }));

  expect(
    await screen.findByText(/Carts staged. Those leaves are now available for assembly./),
  ).toBeInTheDocument();
});

it('says the pull is complete when the last opening is staged', async () => {
  renderPanel([
    openingsMock([opening({ pullStatus: 'PULLED', stagedBy: 'Ada' }), opening({ id: 'sao-2', leaf: 2 })]),
    stageMock(['sao-2'], true, []),
  ]);
  fireEvent.click(await screen.findByRole('checkbox', { name: /Stage 0019-EX . L2/ }));
  fireEvent.click(screen.getByRole('button', { name: /Confirm 1 staged/ }));
  // The dialog says so before it happens, too.
  expect(await screen.findByText(/This completes the pull/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm staged' }));

  expect(
    await screen.findByText(/All carts staged - PR-SA-0001 is complete./),
  ).toBeInTheDocument();
});

it('is read-only once the pull is no longer in progress', async () => {
  renderPanel([openingsMock([opening({ pullStatus: 'PULLED', stagedBy: 'Ada' })])], false);
  expect(await screen.findByText(/Stage carts \(1 of 1 leaf\)/)).toBeInTheDocument();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument();
});

it('renders nothing for a pull with no openings', async () => {
  const { container } = renderPanel([openingsMock([])]);
  await waitFor(() => expect(screen.queryByText(/Loading openings/)).not.toBeInTheDocument());
  expect(container.querySelector('section')).toBeNull();
});

// --- derived readings --------------------------------------------------------------------------

it('derives the staging chip only when staging applies', () => {
  expect(stagingChipLabel({ stagingStatus: 'PARTIAL', stagedOpeningCount: 4, totalOpeningCount: 8 })).toBe(
    '4 of 8 staged',
  );
  // A shipping-out / PR-REPL / legacy pull has no openings: null, never "0 of 0 staged".
  expect(stagingChipLabel({ stagingStatus: null, stagedOpeningCount: null, totalOpeningCount: null })).toBeNull();
  expect(stagingChipLabel({ stagingStatus: 'NOT_PULLED', stagedOpeningCount: 0, totalOpeningCount: 0 })).toBeNull();
});

it('colours the staging chip by real state only', () => {
  expect(stagingChipColor({ stagingStatus: 'NOT_PULLED' })).toBe('default');
  expect(stagingChipColor({ stagingStatus: 'PARTIAL' })).toBe('warning');
  expect(stagingChipColor({ stagingStatus: 'PULLED' })).toBe('success');
});

it('treats only an un-staged opening as stageable', () => {
  expect(isStageable(opening() as never)).toBe(true);
  expect(isStageable(opening({ pullStatus: 'PULLED' }) as never)).toBe(false);
});

it('offers cancel on an approved pull, and on a fully staged shop-assembly one', () => {
  expect(isCancellable({ status: 'PENDING', source: 'SHOP_ASSEMBLY' })).toBe(false);
  expect(isCancellable({ status: 'IN_PROGRESS', source: 'SHOP_ASSEMBLY' })).toBe(true);
  expect(isCancellable({ status: 'IN_PROGRESS', source: 'SHIPPING_OUT' })).toBe(true);
  // "Completed" for a shop-assembly pull now means only "every cart is built".
  expect(isCancellable({ status: 'COMPLETED', source: 'SHOP_ASSEMBLY', totalOpeningCount: 2 })).toBe(
    true,
  );
  // ...but only if it has carts at all. A completed PR-REPL pull is a SHOP_ASSEMBLY pull with no
  // openings, and the server refuses it every time, so the button must not be offered.
  expect(isCancellable({ status: 'COMPLETED', source: 'SHOP_ASSEMBLY', totalOpeningCount: 0 })).toBe(
    false,
  );
  expect(isCancellable({ status: 'COMPLETED', source: 'SHOP_ASSEMBLY', totalOpeningCount: null })).toBe(
    false,
  );
  expect(isCancellable({ status: 'COMPLETED', source: 'SHOP_ASSEMBLY' })).toBe(false);
  // A completed shipping-out pull has already flipped its leaves to ship-ready.
  expect(isCancellable({ status: 'COMPLETED', source: 'SHIPPING_OUT' })).toBe(false);
  expect(isCancellable({ status: 'CANCELLED', source: 'SHOP_ASSEMBLY' })).toBe(false);
});
