import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { beforeAll, beforeEach, describe, it, expect, vi } from 'vitest';
import { ToastProvider } from '../../../../components/Toast';
import RequestWorkspace from '../RequestWorkspace';
import { GET_PROJECTS } from '../../../../graphql/shared';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../../../graphql/warehouse';
import {
  GET_PROJECT_OPENINGS,
  GET_REQUEST_COVERAGE,
  GET_SHIPPING_OUT_REQUEST,
} from '../../../../graphql/shipping';

// Every test walks the source gate and mounts the DataGrid opening picker, which blows through
// vitest's default 5s per-test budget on the CI runner (fine locally).
vi.setConfig({ testTimeout: 30_000 });

// MUI X DataGrid (the opening picker, once past the source gate) observes container size; jsdom has
// no ResizeObserver.
beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    // @ts-expect-error minimal stub for jsdom
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

// #637: the project picker badges the company for an admin, so it reads identity. Stubbed rather
// than mounting a Clerk provider this file has no other use for.
vi.mock('../../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Me',
    userId: 'me',
    roles: [],
    hasRole: () => false,
    isAdmin: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

/** Renders the current URL so a test can assert where the "upload a newer schedule" hand-off went. */
function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

// The seed rules the design pins: a create-mode draft persists per project in sessionStorage and
// survives navigation, while an edit seeds from the server once and is NEVER persisted - which is
// what keeps a background refetch from clobbering a half-made edit.

const STORAGE_KEY = 'shipping-request-cart:proj-1';

function projectsMock(): MockedResponse {
  return {
    request: { query: GET_PROJECTS },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: {
      data: {
        projects: [
          {
            __typename: 'Project',
            id: 'proj-1',
            projectId: 'JOB-1',
            description: 'Riverside Tower',
            client: null,
            jobSiteName: null,
            scheduleFilename: null,
            company: 'TUBC',
            openingCount: 4,
            gpSetupOk: true,
            gpSetupCheckedAt: null,
            gpSetupIssues: null,
          },
        ],
      },
    },
  };
}

function availabilityMock(overrides?: Partial<{ available: number; onHand: number; classification: string | null }>): MockedResponse {
  const onHand = overrides?.onHand ?? overrides?.available ?? 10;
  const available = overrides?.available ?? 10;
  return {
    request: { query: GET_PROJECT_INVENTORY_AVAILABILITY, variables: { projectId: 'proj-1' } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: {
      data: {
        projectInventoryAvailability: [
          {
            hardwareCategory: 'HINGE',
            productCode: 'HG-100',
            onHandQuantity: onHand,
            deficientQuantity: 0,
            reservedQuantity: onHand - available,
            availableQuantity: available,
            classification: overrides?.classification ?? null,
          },
        ],
      },
    },
  };
}

function openingsMock(): MockedResponse {
  return {
    request: { query: GET_PROJECT_OPENINGS, variables: { projectId: 'proj-1' } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: { data: { projectOpenings: { openingCount: 0, hardwareItemCount: 0, openings: [] } } },
  };
}

function requestMock(): MockedResponse {
  return {
    request: { query: GET_SHIPPING_OUT_REQUEST, variables: { id: 'req-1' } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: {
      data: {
        shippingOutRequest: {
          __typename: 'ShippingOutRequest',
          id: 'req-1',
          requestNumber: 'JOB-1-003',
          projectId: 'proj-1',
          status: 'PENDING',
          createdBy: 'Shipper',
          createdAt: '2026-08-03T00:00:00',
          integrityNote: null,
          items: [
            {
              __typename: 'ShippingOutRequestItem',
              id: 'item-1',
              openingNumber: null,
              hardwareCategory: 'HINGE',
              productCode: 'HG-100',
              requestedQuantity: 2,
            },
          ],
        },
      },
    },
  };
}

function renderAt(entry: string, mocks: MockedResponse[]) {
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[entry]}>
        <ToastProvider>
          <Routes>
            <Route path="/app/shipping/requests/new" element={<RequestWorkspace mode="create" />} />
            <Route path="/app/shipping/requests/:id/edit" element={<RequestWorkspace mode="edit" />} />
            <Route path="/app/import" element={<LocationProbe />} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
}

const SLOW = { timeout: 5000 };

beforeEach(() => {
  sessionStorage.clear();
});

describe('RequestWorkspace draft persistence', () => {
  it('seeds a create-mode cart from the saved draft and persists changes back', async () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([{ openingNumber: null, hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 2 }]),
    );
    renderAt('/app/shipping/requests/new?projectId=proj-1', [
      projectsMock(),
      availabilityMock(),
      openingsMock(),
    ]);

    // The extras lane opens on its own because the draft already carries a loose line, so the seeded
    // quantity is reachable without a tab or a click - which is only true if the draft was loaded.
    const qty = await screen.findByRole('spinbutton', { name: /Quantity of HG-100 to send loose/i }, SLOW);
    expect(qty).toHaveValue(2);

    fireEvent.change(qty, { target: { value: '3' } });

    await waitFor(() => {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '[]');
      expect(saved).toEqual([
        { openingNumber: null, hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 3 },
      ]);
    });
  });

  it('seeds edit mode from the server and never writes the draft to sessionStorage', async () => {
    renderAt('/app/shipping/requests/req-1/edit', [
      projectsMock(),
      availabilityMock(),
      openingsMock(),
      requestMock(),
    ]);

    const qty = await screen.findByRole('spinbutton', { name: /Quantity of HG-100 to send loose/i }, SLOW);
    expect(qty).toHaveValue(2);

    // Change the cart - an edit must still not persist, so a background list refetch cannot clobber it.
    fireEvent.change(qty, { target: { value: '3' } });
    await waitFor(() => expect(qty).toHaveValue(3));
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

// The openings-first catalog opens on a source gate mirroring the import wizard's upload step (#608):
// use the schedule on file, or hand off to the import wizard to replace it.

function scheduleOpeningsMock(): MockedResponse {
  return {
    request: { query: GET_PROJECT_OPENINGS, variables: { projectId: 'proj-1' } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: {
      data: {
        projectOpenings: {
          openingCount: 2,
          hardwareItemCount: 7,
          openings: [
            { openingNumber: '101', building: 'A', floor: '1', location: 'Lobby', hand: 'LH', doorType: 'HM', frameType: 'HM', interiorExterior: 'Interior', keying: 'K1', leafCount: 1 },
            { openingNumber: '102', building: 'B', floor: '2', location: 'Stair', hand: 'RH', doorType: 'WD', frameType: 'HM', interiorExterior: 'Exterior', keying: 'K2', leafCount: 2 },
          ],
        },
      },
    },
  };
}

function coverageMock(suggested = 4, owed = 4): MockedResponse {
  return {
    request: { query: GET_REQUEST_COVERAGE, variables: { projectId: 'proj-1', openingNumbers: ['101'] } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: {
      data: {
        requestCoverage: [
          {
            openingNumber: '101',
            hardwareCategory: 'HINGE',
            productCode: 'HG-100',
            classification: null,
            owedQuantity: owed,
            sentQuantity: 0,
            assembledQuantity: 0,
            shippedQuantity: 0,
            claimedQuantity: 0,
            suggestedQuantity: suggested,
            onOrderQuantity: 0,
          },
        ],
      },
    },
  };
}

describe('from-schedule source gate', () => {
  it('opens on the two source cards, showing the persisted counts', async () => {
    renderAt('/app/shipping/requests/new?projectId=proj-1', [projectsMock(), availabilityMock(), scheduleOpeningsMock()]);
    expect(await screen.findByText(/2 openings.*7 hardware items/i, {}, SLOW)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /use current schedule/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload a newer schedule/i })).toBeInTheDocument();
  });

  it('"use current schedule" reaches the opening grid', async () => {
    renderAt('/app/shipping/requests/new?projectId=proj-1', [projectsMock(), availabilityMock(), scheduleOpeningsMock()]);
    // The card is disabled until the counts load, so wait for them before clicking.
    await screen.findByText(/2 openings/i, {}, SLOW);
    fireEvent.click(screen.getByRole('button', { name: /use current schedule/i }));
    expect(await screen.findByPlaceholderText('Paste opening numbers, one per line...', {}, SLOW)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Select All' })).toBeInTheDocument();
  });

  it('"upload a newer schedule" hands off to the import wizard, carrying purpose and returnTo', async () => {
    renderAt('/app/shipping/requests/new?projectId=proj-1', [projectsMock(), availabilityMock(), scheduleOpeningsMock()]);
    fireEvent.click(await screen.findByRole('button', { name: /upload a newer schedule/i }, SLOW));
    const loc = await screen.findByTestId('loc', {}, SLOW);
    expect(loc.textContent).toContain('/app/import');
    expect(loc.textContent).toContain('projectId=proj-1');
    expect(loc.textContent).toContain('purpose=schedule');
    expect(loc.textContent).toContain(`returnTo=${encodeURIComponent('/app/shipping/requests/new?projectId=proj-1')}`);
  });

  it('opening selection drives the coverage table, which carries a live Free column', async () => {
    renderAt('/app/shipping/requests/new?projectId=proj-1', [
      projectsMock(),
      availabilityMock(),
      scheduleOpeningsMock(),
      coverageMock(),
    ]);
    await screen.findByText(/2 openings/i, {}, SLOW);
    fireEvent.click(screen.getByRole('button', { name: /use current schedule/i }));
    const paste = await screen.findByPlaceholderText('Paste opening numbers, one per line...', {}, SLOW);
    // Selecting via the paste filter drives requestCoverage, whose product row then renders.
    fireEvent.change(paste, { target: { value: '101' } });
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    const productCell = await screen.findByText('HG-100', {}, SLOW);
    // Free is the openings-first addition (#610): the live pool remainder for the product.
    expect(screen.getByText('Free')).toBeInTheDocument();
    const cells = within(productCell.closest('tr') as HTMLElement).getAllByRole('cell');
    // #632: expander / Product / Category / chip / Required / Through shop / Shipped out / Claimed /
    // Free / Suggested / On order / Add - one row per PRODUCT, summed over the selected openings.
    expect(cells[8]).toHaveTextContent('10'); // Free = availability (10), nothing in the cart yet
    expect(cells[9]).toHaveTextContent('4'); // Suggested
  });

  it('flags a suggestion the free pool cannot cover, but still offers the add', async () => {
    renderAt('/app/shipping/requests/new?projectId=proj-1', [
      projectsMock(),
      availabilityMock({ available: 2 }),
      scheduleOpeningsMock(),
      coverageMock(4, 4),
    ]);
    await screen.findByText(/2 openings/i, {}, SLOW);
    fireEvent.click(screen.getByRole('button', { name: /use current schedule/i }));
    const paste = await screen.findByPlaceholderText('Paste opening numbers, one per line...', {}, SLOW);
    fireEvent.change(paste, { target: { value: '101' } });
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    const productCell = await screen.findByText('HG-100', {}, SLOW);
    const cells = within(productCell.closest('tr') as HTMLElement).getAllByRole('cell');
    expect(cells[8]).toHaveTextContent('2'); // Free clamped to what stock can cover
    expect(cells[9]).toHaveTextContent('4'); // Suggested still the full owed figure
    // A shortfall does not block the add - the line goes and claims what stock can cover.
    expect(within(cells[11]).getByRole('button', { name: 'Add' })).toBeEnabled();
  });
});

// The composer collapse: rows with nothing to add (no suggestion, or no stock behind the suggestion)
// fold behind a per-opening expander line; a row in the cart is always visible.

function coverageRow(over: Partial<Record<string, unknown>> = {}) {
  return {
    openingNumber: '101',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    classification: null,
    owedQuantity: 4,
    sentQuantity: 0,
    assembledQuantity: 0,
    shippedQuantity: 0,
    claimedQuantity: 0,
    suggestedQuantity: 4,
    onOrderQuantity: 0,
    ...over,
  };
}

function coverageMockRows(rows: Array<Record<string, unknown>>): MockedResponse {
  return {
    request: { query: GET_REQUEST_COVERAGE, variables: { projectId: 'proj-1', openingNumbers: ['101'] } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: { data: { requestCoverage: rows } },
  };
}

async function reachCoverage(extraMocks: MockedResponse[]) {
  renderAt('/app/shipping/requests/new?projectId=proj-1', [
    projectsMock(),
    availabilityMock(),
    scheduleOpeningsMock(),
    ...extraMocks,
  ]);
  await screen.findByText(/2 openings/i, {}, SLOW);
  fireEvent.click(screen.getByRole('button', { name: /use current schedule/i }));
  const paste = await screen.findByPlaceholderText('Paste opening numbers, one per line...', {}, SLOW);
  fireEvent.change(paste, { target: { value: '101' } });
  fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
}

describe('composer collapse', () => {
  it('hides rows with nothing to add and reveals them through the expander', async () => {
    await reachCoverage([
      coverageMockRows([
        coverageRow(),
        // Already covered: nothing left to suggest.
        coverageRow({ hardwareCategory: 'LOCK', productCode: 'LK-200', suggestedQuantity: 0, sentQuantity: 4 }),
        // Awaiting stock: suggested, but no availability behind it (only HINGE|HG-100 has a pool).
        coverageRow({ hardwareCategory: 'DOOR', productCode: 'DR-300', suggestedQuantity: 3, onOrderQuantity: 5 }),
      ]),
    ]);
    await screen.findByText('HG-100', {}, SLOW);

    expect(screen.queryByText('LK-200')).not.toBeInTheDocument();
    expect(screen.queryByText('DR-300')).not.toBeInTheDocument();
    const expander = screen.getByRole('button', {
      name: '2 lines with nothing to add · 1 awaiting stock (5 on order) · 1 already covered - show',
    });

    fireEvent.click(expander);
    expect(screen.getByText('LK-200')).toBeInTheDocument();
    expect(screen.getByText('DR-300')).toBeInTheDocument();
  });

  it('collapses an opening with nothing to add to its header and the expander line alone', async () => {
    await reachCoverage([
      coverageMockRows([coverageRow({ suggestedQuantity: 0, sentQuantity: 4 })]),
    ]);
    const expander = await screen.findByRole(
      'button',
      { name: '1 line with nothing to add · 1 already covered - show' },
      SLOW,
    );
    // No table at all until expanded - the opening is its header plus this one line.
    expect(screen.queryByText('Suggested')).not.toBeInTheDocument();

    fireEvent.click(expander);
    expect(await screen.findByText('HG-100', {}, SLOW)).toBeInTheDocument();
  });

  it('keeps a restored draft line visible even when its row has nothing left to suggest', async () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([{ openingNumber: '101', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 2 }]),
    );
    await reachCoverage([coverageMockRows([coverageRow({ suggestedQuantity: 0, sentQuantity: 4 })])]);

    // #632: the product row carries ONE quantity for the product across the selected openings.
    const qty = await screen.findByRole(
      'spinbutton',
      { name: 'Quantity of HG-100 across selected openings' },
      SLOW,
    );
    expect(qty).toHaveValue(2);
    // The only row is pinned visible by the cart, so there is nothing to collapse.
    expect(screen.queryByRole('button', { name: /with nothing to add/ })).not.toBeInTheDocument();

    // The per-opening breakdown behind the expander still names the door the units are owed to.
    fireEvent.click(screen.getByRole('button', { name: 'Show per-opening breakdown for HG-100' }));
    expect(await screen.findByRole('spinbutton', { name: 'Quantity of HG-100 for 101' }, SLOW)).toHaveValue(2);
  });
});

// The extras lane (#610): loose stock demoted to a bottom accordion, opening on its own only when
// the cart already carries loose lines.

describe('extras lane', () => {
  it('stays collapsed on a fresh request and opens on demand', async () => {
    renderAt('/app/shipping/requests/new?projectId=proj-1', [projectsMock(), availabilityMock(), scheduleOpeningsMock()]);
    const summary = await screen.findByText('Extras - not owed to any opening', {}, SLOW);
    // Collapsed: the loose list is unmounted until the lane is opened.
    expect(screen.queryByRole('button', { name: 'Take all free' })).not.toBeInTheDocument();
    fireEvent.click(summary);
    expect(await screen.findByRole('button', { name: 'Take all free' }, SLOW)).toBeInTheDocument();
  });

  it('nudges a loose row toward the opening its product is scheduled for', async () => {
    renderAt('/app/shipping/requests/new?projectId=proj-1', [
      projectsMock(),
      availabilityMock(),
      scheduleOpeningsMock(),
      coverageMock(),
    ]);
    await screen.findByText(/2 openings/i, {}, SLOW);
    fireEvent.click(screen.getByRole('button', { name: /use current schedule/i }));
    const paste = await screen.findByPlaceholderText('Paste opening numbers, one per line...', {}, SLOW);
    fireEvent.change(paste, { target: { value: '101' } });
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    await screen.findByText('HG-100', {}, SLOW);
    // Opening the extras lane, its HG-100 row shows the hint because 101 still owes that product.
    fireEvent.click(screen.getByText('Extras - not owed to any opening'));
    expect(await screen.findByText(/on schedule for 101/i, {}, SLOW)).toBeInTheDocument();
  });
});
