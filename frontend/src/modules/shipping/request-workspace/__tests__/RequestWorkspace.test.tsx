import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { beforeAll, beforeEach, describe, it, expect } from 'vitest';
import { ToastProvider } from '../../../../components/Toast';
import RequestWorkspace from '../RequestWorkspace';
import { GET_PROJECTS } from '../../../../graphql/shared';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../../../graphql/warehouse';
import {
  GET_PROJECT_OPENINGS,
  GET_REQUEST_COVERAGE,
  GET_SHIPPING_OUT_REQUEST,
} from '../../../../graphql/shipping';

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

function availabilityMock(): MockedResponse {
  return {
    request: { query: GET_PROJECT_INVENTORY_AVAILABILITY, variables: { projectId: 'proj-1' } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: {
      data: {
        projectInventoryAvailability: [
          {
            hardwareCategory: 'HINGE',
            productCode: 'HG-100',
            onHandQuantity: 10,
            deficientQuantity: 0,
            reservedQuantity: 0,
            availableQuantity: 10,
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

    fireEvent.click(await screen.findByRole('tab', { name: 'From inventory' }, SLOW));
    // The seeded quantity reaches the inventory row, which is only true if the draft was loaded.
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

    fireEvent.click(await screen.findByRole('tab', { name: 'From inventory' }, SLOW));
    const qty = await screen.findByRole('spinbutton', { name: /Quantity of HG-100 to send loose/i }, SLOW);
    expect(qty).toHaveValue(2);

    // Change the cart - an edit must still not persist, so a background list refetch cannot clobber it.
    fireEvent.change(qty, { target: { value: '3' } });
    await waitFor(() => expect(qty).toHaveValue(3));
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

// The from-schedule tab opens on a source gate mirroring the import wizard's upload step (#608): use
// the schedule on file, or hand off to the import wizard to replace it.

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

function coverageMock(): MockedResponse {
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
            owedQuantity: 4,
            sentQuantity: 0,
            claimedQuantity: 0,
            suggestedQuantity: 4,
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

  it('opening selection drives the coverage table', async () => {
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
    expect(await screen.findByText('HG-100', {}, SLOW)).toBeInTheDocument();
  });
});
