import { useState } from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import DriverPicker from '../DriverPicker';
import { GET_SHIPMENT_DRIVERS } from '../../../graphql/shipping';

/**
 * Who drives a shipment (#1726). Pinned: "No driver" is where it starts (most shipments go by
 * courier), and a stored driver who has since lost the role is still shown rather than dropped.
 */

const driversMock: MockedResponse = {
  request: { query: GET_SHIPMENT_DRIVERS, variables: { projectId: 'proj-1' } },
  result: {
    data: {
      shipmentDrivers: [
        { __typename: 'ShipmentDriver', userId: 'u_dan', name: 'Dan Driver' },
        { __typename: 'ShipmentDriver', userId: 'u_ann', name: 'Ann Able' },
      ],
    },
  },
};

function Harness({ initial = '', storedName }: { initial?: string; storedName?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <DriverPicker projectId="proj-1" value={value} onChange={setValue} storedName={storedName} />
      <span data-testid="chosen">{value}</span>
    </>
  );
}

async function openMenu() {
  const select = await screen.findByRole('combobox', { name: 'Driver' });
  await waitFor(() => expect(select).not.toHaveAttribute('aria-disabled', 'true'));
  fireEvent.mouseDown(select);
  return screen.findByRole('listbox');
}

it('starts on no driver and picks one of the company drivers', async () => {
  render(
    <MockedProvider mocks={[driversMock]}>
      <Harness />
    </MockedProvider>,
  );
  expect(await screen.findByText('No driver')).toBeInTheDocument();
  const menu = await openMenu();
  fireEvent.click(within(menu).getByText('Dan Driver'));
  expect(screen.getByTestId('chosen')).toHaveTextContent('u_dan');
});

it('keeps showing a stored driver who is no longer listed', async () => {
  render(
    <MockedProvider mocks={[driversMock]}>
      <Harness initial="u_gone" storedName="Paul Former" />
    </MockedProvider>,
  );
  const menu = await openMenu();
  expect(within(menu).getByText('Paul Former')).toBeInTheDocument();
});
