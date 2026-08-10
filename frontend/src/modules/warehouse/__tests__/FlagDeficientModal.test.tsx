import { render, screen, fireEvent, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import FlagDeficientModal, { type FlagDeficientItem } from '../FlagDeficientModal';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../../graphql/warehouse';

// The modal renders inside a MUI Dialog; under the full parallel suite jsdom rendering is slow, so
// lift the per-test budget and testing-library's async-util default (mirrors DestockInventoryModal).
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

const baseItem: FlagDeficientItem = {
  id: 'inv-1',
  hardwareCategory: 'Hinges',
  productCode: 'HG-100',
  quantity: 10,
  deficientQuantity: 2,
  available: 8,
};

function renderModal(item: Partial<FlagDeficientItem> = {}, mocks: MockedResponse[] = []) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <FlagDeficientModal item={{ ...baseItem, ...item }} onClose={vi.fn()} onSuccess={vi.fn()} />
      </ToastProvider>
    </MockedProvider>,
  );
}

function flagButton() {
  return screen.getByRole('button', { name: 'Flag deficient' });
}

function quantityInput() {
  return screen.getByLabelText(/Quantity to flag/) as HTMLInputElement;
}

describe('FlagDeficientModal', () => {
  it('caps the flagged quantity at the available count', () => {
    renderModal(); // available 8, no projectId -> reservation query is skipped
    expect(screen.getByLabelText(/Quantity to flag \(max 8\)/)).toBeInTheDocument();

    fireEvent.change(quantityInput(), { target: { value: '9' } });
    expect(flagButton()).toBeDisabled();

    fireEvent.change(quantityInput(), { target: { value: '8' } });
    expect(flagButton()).toBeEnabled();

    fireEvent.change(quantityInput(), { target: { value: '0' } });
    expect(flagButton()).toBeDisabled();
  });

  it('escalates the reservation notice to a warning once the flag would strand a claim', async () => {
    const mocks: MockedResponse[] = [
      {
        request: {
          query: GET_PROJECT_INVENTORY_AVAILABILITY,
          variables: { projectId: 'proj-1' },
        },
        result: {
          data: {
            projectInventoryAvailability: [
              {
                hardwareCategory: 'Hinges',
                productCode: 'HG-100',
                onHandQuantity: 8,
                deficientQuantity: 0,
                reservedQuantity: 6,
                availableQuantity: 2,
                __typename: 'InventoryAvailability',
              },
            ],
          },
        },
      },
    ];
    renderModal({ projectId: 'proj-1', quantity: 10, deficientQuantity: 0, available: 8 }, mocks);

    // soundOnHand 8; default q=1 leaves 7, still covering the 6 reserved -> caption, no warning.
    expect(await screen.findByText('6 unit(s) reserved by active requests.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();

    // Flag 3 -> resulting sound on-hand 5 < 6 reserved: the notice becomes a warning alert.
    fireEvent.change(quantityInput(), { target: { value: '3' } });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('below the 6 unit(s) reserved by active requests');
  });
});
