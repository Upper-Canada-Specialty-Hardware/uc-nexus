import { useState } from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import LoadPicker from '../LoadPicker';
import { fmtShipDate, NEW_LOAD } from '../loads';
import { GET_JOINABLE_LOADS } from '../../../graphql/shipping';

/**
 * Which truck a shipment rides (#1720, #1723). What is pinned is what the person at the dock reads to
 * pick the right truck - each load with the slips already on it - and that the slip being edited is
 * not listed as riding with itself.
 */

const loadsMock: MockedResponse = {
  request: { query: GET_JOINABLE_LOADS, variables: { projectId: 'proj-1' } },
  result: {
    data: {
      joinableLoads: [
        {
          __typename: 'ShipmentLoad',
          id: 'load-1',
          loadNumber: '22713-10152026',
          shipDate: '2026-10-15',
          leadProjectNumber: '22713',
          slips: [
            {
              __typename: 'ShipmentLoadSlip',
              id: 'ps-1',
              packingSlipNumber: 'PS-00412',
              projectNumber: '22713',
              projectDescription: 'Lead job',
              status: 'SCHEDULED',
            },
            {
              __typename: 'ShipmentLoadSlip',
              id: 'ps-2',
              packingSlipNumber: 'PS-00413',
              projectNumber: '23001',
              projectDescription: 'Second job',
              status: 'SCHEDULED',
            },
          ],
        },
      ],
    },
  },
};

function Harness({ slipId, onPick }: { slipId?: string; onPick?: (id: string) => void }) {
  const [value, setValue] = useState(NEW_LOAD);
  return (
    <LoadPicker
      projectId="proj-1"
      value={value}
      slipId={slipId}
      onChange={(id) => {
        setValue(id);
        onPick?.(id);
      }}
    />
  );
}

async function openMenu() {
  const select = await screen.findByRole('combobox', { name: 'Load' });
  // Disabled until the loads arrive, and a disabled select ignores the press.
  await waitFor(() => expect(select).not.toHaveAttribute('aria-disabled', 'true'));
  fireEvent.mouseDown(select);
  return screen.findByRole('listbox');
}

it('starts on a new load and lists each joinable load with the slips on it', async () => {
  const onPick = vi.fn();
  render(
    <MockedProvider mocks={[loadsMock]}>
      <Harness onPick={onPick} />
    </MockedProvider>,
  );
  expect(await screen.findByText('New load')).toBeInTheDocument();

  const menu = await openMenu();
  expect(within(menu).getByText(`22713-10152026 · ${fmtShipDate('2026-10-15')}`)).toBeInTheDocument();
  expect(within(menu).getByText('PS-00412 (22713), PS-00413 (23001)')).toBeInTheDocument();

  fireEvent.click(within(menu).getByText(`22713-10152026 · ${fmtShipDate('2026-10-15')}`));
  expect(onPick).toHaveBeenCalledWith('load-1');
});

it('leaves the slip being edited out of the slips its load already carries', async () => {
  render(
    <MockedProvider mocks={[loadsMock]}>
      <Harness slipId="ps-2" />
    </MockedProvider>,
  );
  const menu = await openMenu();
  expect(within(menu).getByText('PS-00412 (22713)')).toBeInTheDocument();
});

it('reads a ship date as the calendar day it names, whatever the timezone', () => {
  expect(fmtShipDate('2026-10-15')).toBe(
    new Date(2026, 9, 15).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
  );
});
