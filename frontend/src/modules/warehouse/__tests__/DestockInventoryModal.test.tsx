import { render, screen, fireEvent, within, configure } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import DestockInventoryModal, { type DestockSource } from '../stock/DestockInventoryModal';

// The modal renders inside a MUI Dialog; under the full parallel suite jsdom rendering is slow, so
// lift the per-test budget and testing-library's async-util default (mirrors LocationActionDialog).
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

const baseSource: DestockSource = {
  id: 'inv-1',
  hardwareCategory: 'Hinges',
  productCode: 'HG-100',
  quantity: 10,
  deficientQuantity: 2,
  aisle: 'A1',
  row: 'R1',
  bay: 'B1',
};

function renderModal(source: Partial<DestockSource> = {}) {
  render(
    <MockedProvider mocks={[]}>
      <ToastProvider>
        <DestockInventoryModal
          inventoryLocation={{ ...baseSource, ...source }}
          onClose={vi.fn()}
          onSuccess={vi.fn()}
        />
      </ToastProvider>
    </MockedProvider>,
  );
}

function destockButton() {
  return screen.getByRole('button', { name: 'Destock' });
}

function quantityInput() {
  return screen.getByLabelText(/Quantity/) as HTMLInputElement;
}

async function openSourceSelect() {
  // The modal's only combobox is the Source select.
  fireEvent.mouseDown(screen.getByRole('combobox'));
  return screen.findByRole('listbox');
}

describe('DestockInventoryModal', () => {
  it('caps a non-deficient-swap at quantity minus deficient units', () => {
    renderModal(); // qty 10, deficient 2 -> max 8, source defaults to OVERAGE
    expect(screen.getByLabelText(/Quantity \(max 8\)/)).toBeInTheDocument();

    fireEvent.change(quantityInput(), { target: { value: '9' } });
    expect(destockButton()).toBeDisabled();

    fireEvent.change(quantityInput(), { target: { value: '8' } });
    expect(destockButton()).toBeEnabled();
  });

  it('caps a deficient swap at the deficient count', async () => {
    renderModal(); // qty 10, deficient 2
    const listbox = await openSourceSelect();
    fireEvent.click(within(listbox).getByText('Deficient swap'));

    expect(screen.getByLabelText(/Quantity \(max 2\)/)).toBeInTheDocument();

    fireEvent.change(quantityInput(), { target: { value: '3' } });
    expect(destockButton()).toBeDisabled();

    fireEvent.change(quantityInput(), { target: { value: '2' } });
    expect(destockButton()).toBeEnabled();
  });

  it('requires all three of aisle/row/bay once the target override is on', () => {
    renderModal();
    expect(destockButton()).toBeEnabled(); // qty 1 within cap, no override

    fireEvent.click(screen.getByRole('button', { name: 'Override target location' }));
    expect(destockButton()).toBeDisabled(); // override on, fields blank

    fireEvent.change(screen.getByLabelText(/Aisle/), { target: { value: 'C3' } });
    expect(destockButton()).toBeDisabled(); // partial override still blocked

    fireEvent.change(screen.getByLabelText(/Row/), { target: { value: '4' } });
    expect(destockButton()).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Bay/), { target: { value: '2' } });
    expect(destockButton()).toBeEnabled(); // all three present
  });
});
