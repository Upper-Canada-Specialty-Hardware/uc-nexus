import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import ShipmentMethodsDialog from '../ShipmentMethodsDialog';
import { CREATE_SHIPMENT_METHOD, GET_SHIPMENT_METHODS } from '../../../graphql/shipping';

/**
 * The shipping department's list of how a load can travel (#451).
 *
 * What is pinned here is where a new method lands in the order and how many times Add can fire,
 * because both are silent when wrong: a reused sortOrder just makes the dropdown order arbitrary,
 * and a double submit surfaces as a name conflict the user did nothing to cause.
 */

const INFINITE = Number.POSITIVE_INFINITY;

function method(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShipmentMethod',
    id: 'sm-1',
    name: 'Our truck',
    isActive: true,
    sortOrder: 0,
    createdAt: '2026-08-01T00:00:00Z',
    updatedAt: '2026-08-01T00:00:00Z',
    ...overrides,
  };
}

function listMock(methods: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: GET_SHIPMENT_METHODS, variables: { activeOnly: false } },
    maxUsageCount: INFINITE,
    result: { data: { shipmentMethods: methods } },
  };
}

function createMock(name: string, sortOrder: number, onFire?: () => void): MockedResponse {
  return {
    request: { query: CREATE_SHIPMENT_METHOD, variables: { name, sortOrder } },
    // One only: a second matching call has no mock left and the test fails loudly rather than
    // quietly passing on a duplicate submit.
    result: () => {
      onFire?.();
      return { data: { createShipmentMethod: method({ id: 'sm-new', name, sortOrder }) } };
    },
  };
}

function renderDialog(mocks: MockedResponse[]) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <ShipmentMethodsDialog open onClose={vi.fn()} />
      </ToastProvider>
    </MockedProvider>,
  );
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

it('puts a new method past the highest position in use, not at the row count', async () => {
  // Two rows numbered 0 and 4 - what a list looks like after a delete. The count would mint this
  // one onto 2, which nothing holds today but which the next reactivated row could.
  const fired = vi.fn();
  renderDialog([
    listMock([method({ id: 'sm-1', sortOrder: 0 }), method({ id: 'sm-2', name: 'Flatbed', sortOrder: 4 })]),
    createMock('Courier', 5, fired),
  ]);
  await flush();

  fireEvent.change(await screen.findByRole('textbox', { name: /New method/i }), {
    target: { value: 'Courier' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Add/i }));

  await waitFor(() => expect(fired).toHaveBeenCalled());
});

it('counts a retired method when working out the next position', async () => {
  // It keeps its place for the day it is reactivated, so the next method has to go past it.
  const fired = vi.fn();
  renderDialog([
    listMock([method({ id: 'sm-1', sortOrder: 0 }), method({ id: 'sm-2', name: 'Rail', sortOrder: 1, isActive: false })]),
    createMock('Courier', 2, fired),
  ]);
  await flush();

  fireEvent.change(await screen.findByRole('textbox', { name: /New method/i }), {
    target: { value: 'Courier' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Add/i }));

  await waitFor(() => expect(fired).toHaveBeenCalled());
});

it('does not fire a second create while the first is still in flight', async () => {
  const fired = vi.fn();
  renderDialog([listMock([]), createMock('Courier', 0, fired)]);
  await flush();

  const box = await screen.findByRole('textbox', { name: /New method/i });
  fireEvent.change(box, { target: { value: 'Courier' } });
  fireEvent.keyDown(box, { key: 'Enter' });
  fireEvent.keyDown(box, { key: 'Enter' });

  await waitFor(() => expect(fired).toHaveBeenCalledTimes(1));
  // The second Enter would have had no mock to match, which surfaces as an error alert.
  expect(screen.queryByText(/No more mocked responses/i)).not.toBeInTheDocument();
});

it('ignores Enter on an empty box', async () => {
  renderDialog([listMock([])]);
  await flush();

  const box = await screen.findByRole('textbox', { name: /New method/i });
  fireEvent.keyDown(box, { key: 'Enter' });

  await flush();
  expect(screen.queryByText(/No more mocked responses/i)).not.toBeInTheDocument();
});
