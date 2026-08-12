import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { beforeEach, describe, it, expect } from 'vitest';
import { ToastProvider } from '../../../../components/Toast';
import RequestWorkspace from '../RequestWorkspace';
import { GET_PROJECTS } from '../../../../graphql/shared';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../../../graphql/warehouse';
import { GET_PROJECT_OPENINGS, GET_SHIPPING_OUT_REQUEST } from '../../../../graphql/shipping';

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
    result: { data: { projectHardwareSchedule: { openings: [] } } },
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
