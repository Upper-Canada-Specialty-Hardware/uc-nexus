import { render, screen, fireEvent, within } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import DeliveriesPage from '../DeliveriesPage';
import { GET_MY_DELIVERIES, MARK_SHIPMENT_PICKED_UP } from '../../../graphql/shipping';
import { DELIVERY_REQUEST_FIELDS } from '../../../types/deliveryRequestFields';

/**
 * A driver's own deliveries (#1727). Pinned: what the driver needs at the site is on the card, and the
 * one button is the next leg - picked up while scheduled, delivered once picked up.
 */

const blankHeader = Object.fromEntries(DELIVERY_REQUEST_FIELDS.map((f) => [f, null]));

function slip(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'PackingSlip',
    ...blankHeader,
    id: 'ps-1',
    packingSlipNumber: 'PS-00412',
    projectId: 'proj-1',
    projectNumber: '22713',
    projectDescription: 'Harbour tower',
    status: 'SCHEDULED',
    shippedBy: 'Shipping Desk',
    shippedAt: '2026-10-14T15:00:00Z',
    createdAt: '2026-10-14T15:00:00Z',
    pickupDate: '2026-10-15',
    deliveryDate: '2026-10-16',
    deliveryAddress: '88 Harbourview Rd',
    contractorContactName: 'R. Singh',
    contractorContactPhone: '604-555-0188',
    gateNumber: '4',
    pickedUpAt: null,
    pickedUpBy: null,
    deliveredAt: null,
    deliveredBy: null,
    driverUserId: 'u_dan',
    driverName: 'Dan Driver',
    photos: [],
    containers: [{ __typename: 'ShipmentContainer', id: 'c-1', containerType: 'SKID', name: 'Skid 1', items: [] }],
    load: {
      __typename: 'ShipmentLoadRef',
      id: 'load-1',
      loadNumber: '22713-10152026',
      shipDate: '2026-10-15',
      slips: [],
    },
    ...overrides,
  };
}

const listMock = (slips: Record<string, unknown>[]): MockedResponse => ({
  request: { query: GET_MY_DELIVERIES },
  result: { data: { myDeliveries: slips } },
});

function renderPage(mocks: MockedResponse[]) {
  render(
    <MemoryRouter>
      <MockedProvider mocks={mocks}>
        <ToastProvider>
          <DeliveriesPage />
        </ToastProvider>
      </MockedProvider>
    </MemoryRouter>,
  );
}

it('shows where, who to call and what is on the truck, with the next leg as its button', async () => {
  renderPage([listMock([slip()])]);
  expect(await screen.findByText('PS-00412')).toBeInTheDocument();
  expect(screen.getByText('Load 22713-10152026')).toBeInTheDocument();
  expect(screen.getByText('88 Harbourview Rd')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '604-555-0188' })).toHaveAttribute('href', 'tel:6045550188');
  expect(screen.getByText(/Gate: 4/)).toBeInTheDocument();
  expect(screen.getByText(/Skid 1/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Mark picked up' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Mark delivered' })).not.toBeInTheDocument();
});

it('marks a shipment picked up behind a confirmation and reads the list again', async () => {
  const pickedUp: MockedResponse = {
    request: { query: MARK_SHIPMENT_PICKED_UP, variables: { id: 'ps-1' } },
    result: { data: { markShipmentPickedUp: slip({ status: 'PICKED_UP', pickedUpAt: '2026-10-15T13:00:00Z', pickedUpBy: 'Dan Driver' }) } },
  };
  renderPage([listMock([slip()]), pickedUp, listMock([slip({ status: 'PICKED_UP' })])]);

  fireEvent.click(await screen.findByRole('button', { name: 'Mark picked up' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Mark picked up' }));

  expect(await screen.findByRole('button', { name: 'Mark delivered' })).toBeInTheDocument();
});

it('says so when nothing is assigned', async () => {
  renderPage([listMock([])]);
  expect(await screen.findByText(/Nothing assigned to you right now/)).toBeInTheDocument();
});
