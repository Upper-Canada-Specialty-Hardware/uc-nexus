import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import PipelinePage from '../PipelinePage';
import { GET_ASSEMBLY_PIPELINE, GET_ASSEMBLY_PIPELINE_SUMMARIES } from '../../../graphql/shop-assembly';
import { pipelineFlags, stageColor, stageLabel, stageProgress, unitProgressLabel } from '../pipelineStages';

vi.setConfig({ testTimeout: 30_000 });

// The pipeline is a reading, not a console: it draws the ladder slices 1-5 built and surfaces the
// flags they introduced, and it changes nothing. These tests pin the readings and the two things a
// reader would be misled by if they broke - the stage shown for a request, and the flags.

function summary(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'AssemblyPipelineSummary',
    requestId: 'r1',
    requestNumber: 'SA-0001',
    projectId: 'p1',
    projectCode: 'JOB-1',
    projectName: 'Riverside',
    requestStatus: 'APPROVED',
    createdBy: 'Hardware Schedule Import',
    createdAt: '2026-07-01T09:00:00',
    acceptedBy: 'Ana',
    acceptedAt: '2026-07-02T09:00:00',
    rejectedBy: null,
    rejectedAt: null,
    integrityNote: null,
    pullRequestId: 'pr1',
    pullRequestStatus: 'IN_PROGRESS',
    pullApprovedAt: '2026-07-02T10:00:00',
    pullCompletedAt: null,
    stagingStatus: 'PARTIAL',
    cancelledPullCount: 0,
    lastCancelledAt: null,
    lastCancelledBy: null,
    lastCancellationReason: null,
    openingCount: 4,
    stagedOpeningCount: 2,
    assignedOpeningCount: 1,
    inProgressOpeningCount: 1,
    completedOpeningCount: 0,
    shippedOpeningCount: 0,
    plannedUnitCount: 16,
    installedUnitCount: 5,
    deficientUnitCount: 1,
    replacementPendingUnitCount: 0,
    awaitingReplacementOpeningCount: 1,
    replacementAfterShipOpeningCount: 0,
    stage: 'PULLING',
    ...overrides,
  };
}

function openingRow(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'PipelineOpening',
    shopAssemblyOpeningId: 'o1',
    openingNumber: 'A01',
    leaf: 2,
    building: 'A',
    floor: '2',
    location: null,
    stage: 'IN_PROGRESS',
    pullStatus: 'PULLED',
    stagedAt: '2026-07-02T11:00:00',
    stagedBy: 'Picker',
    assignedToUserId: 'user_1',
    assignedTo: 'Bo',
    assemblyStatus: 'IN_PROGRESS',
    completedAt: null,
    plannedUnitCount: 4,
    installedUnitCount: 2,
    deficientUnitCount: 1,
    replacementPendingUnitCount: 0,
    awaitingReplacementUnitCount: 1,
    replacementArrivedAfterShip: false,
    openingItemId: null,
    openingItemState: null,
    assembledLocation: null,
    ...overrides,
  };
}

function listMock(rows: ReturnType<typeof summary>[]): MockedResponse {
  return {
    request: { query: GET_ASSEMBLY_PIPELINE_SUMMARIES, variables: { status: null } },
    result: { data: { assemblyPipelineSummaries: rows } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function detailMock(
  s: ReturnType<typeof summary>,
  openings: ReturnType<typeof openingRow>[],
): MockedResponse {
  return {
    request: { query: GET_ASSEMBLY_PIPELINE, variables: { requestId: s.requestId } },
    result: {
      data: { assemblyPipeline: { __typename: 'AssemblyPipeline', summary: s, openings } },
    },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <PipelinePage />
    </MockedProvider>,
  );
}

describe('pipelineStages readings', () => {
  it('labels every rung of the ladder and both ways off it', () => {
    expect(stageLabel('PULLING')).toBe('Awaiting pull');
    expect(stageLabel('IN_PROGRESS')).toBe('In progress');
    expect(stageLabel('COMPLETED')).toBe('Assembled');
    expect(stageLabel('CANCELLED')).toBe('Pull cancelled');
  });

  it('keeps status colour for real system state only', () => {
    // DESIGN.md: colour is reserved. Most of the ladder is just "where the work is", so it stays
    // neutral; only the readings somebody acts on differently earn a colour.
    expect(stageColor('STAGED')).toBe('default');
    expect(stageColor('ASSIGNED')).toBe('default');
    expect(stageColor('IN_PROGRESS')).toBe('info');
    expect(stageColor('SHIPPED')).toBe('success');
    expect(stageColor('REJECTED')).toBe('error');
    expect(stageColor('CANCELLED')).toBe('warning');
  });

  it('gives no rail position to a stage that is off the ladder', () => {
    // Rendering REJECTED at 0 would say a request that got half way through never started.
    expect(stageProgress('REQUESTED')).toBe(0);
    expect(stageProgress('SHIPPED')).toBe(1);
    expect(stageProgress('REJECTED')).toBeNull();
    expect(stageProgress('CANCELLED')).toBeNull();
  });

  it('counts dispositioned units, not installed ones', () => {
    // Completion is gated on installed + deficient + pending === planned (#340/#341), so that is the
    // number the progress reading has to show or it disagrees with the gate.
    expect(
      unitProgressLabel({
        plannedUnitCount: 8,
        installedUnitCount: 5,
        deficientUnitCount: 2,
        replacementPendingUnitCount: 1,
      }),
    ).toBe('8/8 units');
  });

  it('returns no flags when nothing is wrong', () => {
    expect(pipelineFlags({ integrityNote: null, awaitingReplacementOpeningCount: 0 })).toEqual([]);
  });

  it('orders the flags doubt-first and escalates the after-shipping one', () => {
    const flags = pipelineFlags({
      integrityNote: 'a re-upload landed',
      awaitingReplacementOpeningCount: 2,
      replacementAfterShipOpeningCount: 1,
    });
    expect(flags.map((f) => f.label)).toEqual([
      'Needs review',
      '2 awaiting replacement',
      '1 arrived after shipping',
    ]);
    expect(flags[2].severity).toBe('error');
  });
});

describe('PipelinePage', () => {
  it('lists a request with its stage, staging and unit progress', async () => {
    renderPage([listMock([summary()])]);

    expect(await screen.findByText('SA-0001')).toBeInTheDocument();
    expect(screen.getByText('JOB-1 - Riverside')).toBeInTheDocument();
    // The stage of the least-advanced opening: what the request is waiting on.
    expect(screen.getByText('Awaiting pull')).toBeInTheDocument();
    expect(screen.getByText('2 of 4')).toBeInTheDocument();
    expect(screen.getByText('6/16 units')).toBeInTheDocument();
    expect(screen.getByText('1 awaiting replacement')).toBeInTheDocument();
  });

  it('renders nothing in the staging column for a request with no openings', async () => {
    // A zeroed "0 of 0" would read as "nothing done" rather than "not applicable" - the same rule the
    // pull queue's staging chip follows.
    renderPage([listMock([summary({ openingCount: 0, stagedOpeningCount: 0 })])]);

    expect(await screen.findByText('SA-0001')).toBeInTheDocument();
    expect(screen.queryByText('0 of 0')).not.toBeInTheDocument();
  });

  it('opens a request and shows where each door leaf is', async () => {
    const s = summary();
    renderPage([
      listMock([s]),
      detailMock(s, [
        // Two leaves of one opening at different rungs - the case the whole view exists for.
        openingRow(),
        openingRow({
          shopAssemblyOpeningId: 'o2',
          leaf: 1,
          stage: 'STAGED',
          assemblyStatus: 'PENDING',
          assignedToUserId: null,
          assignedTo: null,
          installedUnitCount: 0,
          deficientUnitCount: 0,
          awaitingReplacementUnitCount: 0,
        }),
      ]),
    ]);

    fireEvent.click(await screen.findByText('SA-0001'));

    // Scoped to the dialog: the list underneath has columns with the same headings, and this test is
    // about the per-leaf rows.
    expect(await screen.findByText(/A01 - Leaf 2/)).toBeInTheDocument();
    const detail = within(screen.getByRole('dialog'));
    // The question the view exists to answer, one row per leaf, at different rungs.
    expect(detail.getByText(/A01 - Leaf 1/)).toBeInTheDocument();
    expect(detail.getByText('Bo')).toBeInTheDocument();
    expect(detail.getByText('In progress')).toBeInTheDocument();
    // Leaf 2 has three of four units dispositioned; leaf 1 has not been started.
    expect(detail.getByText('3/4 units')).toBeInTheDocument();
    expect(detail.getByText('0/4 units')).toBeInTheDocument();
    expect(detail.getAllByText('by Picker')).toHaveLength(2);
    // The header chip and the leaf-2 row both say a unit is owed.
    expect(detail.getAllByText('1 awaiting replacement')).toHaveLength(2);
  });

  it('shows the assembled leaf location once there is one', async () => {
    const s = summary({ stage: 'COMPLETED', completedOpeningCount: 1, openingCount: 1, stagedOpeningCount: 1 });
    renderPage([
      listMock([s]),
      detailMock(s, [
        openingRow({
          stage: 'COMPLETED',
          assemblyStatus: 'COMPLETED',
          assembledLocation: 'B-2-3',
          openingItemId: 'oi1',
          openingItemState: 'IN_INVENTORY',
          installedUnitCount: 4,
          deficientUnitCount: 0,
          awaitingReplacementUnitCount: 0,
        }),
      ]),
    ]);

    fireEvent.click(await screen.findByText('SA-0001'));
    expect(await screen.findByText('B-2-3')).toBeInTheDocument();
  });

  it('surfaces the integrity note as an alert above the detail', async () => {
    const s = summary({ integrityNote: 'A schedule re-upload landed under this request.' });
    renderPage([listMock([s]), detailMock(s, [openingRow()])]);

    fireEvent.click(await screen.findByText('SA-0001'));
    expect(
      await screen.findByText('A schedule re-upload landed under this request.'),
    ).toBeInTheDocument();
  });

  it('explains a cancelled pull rather than leaving the request looking untouched', async () => {
    // A cancellation returns the request to PENDING and detaches its openings, so without this the
    // request would read as though it had never been accepted.
    const s = summary({
      requestStatus: 'PENDING',
      stage: 'CANCELLED',
      pullRequestId: null,
      pullRequestStatus: null,
      cancelledPullCount: 1,
      lastCancelledBy: 'Sam',
      lastCancellationReason: 'raised on the wrong project',
    });
    renderPage([listMock([s]), detailMock(s, [openingRow({ stage: 'CANCELLED' })])]);

    fireEvent.click(await screen.findByText('SA-0001'));
    await waitFor(() =>
      expect(
        screen.getByText(/cancelled and the hardware returned to inventory by Sam/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/raised on the wrong project/)).toBeInTheDocument();
  });

  it('escalates a replacement that arrived after its leaf shipped', async () => {
    const s = summary({ replacementAfterShipOpeningCount: 1, replacementPendingUnitCount: 1 });
    renderPage([
      listMock([s]),
      detailMock(s, [
        openingRow({
          stage: 'SHIPPED',
          openingItemState: 'SHIPPED_OUT',
          replacementPendingUnitCount: 1,
          awaitingReplacementUnitCount: 1,
          replacementArrivedAfterShip: true,
        }),
      ]),
    ]);

    fireEvent.click(await screen.findByText('SA-0001'));
    expect(await screen.findByText(/needs a reallocation or a site shipment/)).toBeInTheDocument();
    expect(screen.getAllByText('1 arrived after shipping').length).toBeGreaterThan(0);
  });
});
