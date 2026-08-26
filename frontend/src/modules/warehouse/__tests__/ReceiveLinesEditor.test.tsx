import { useState } from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import ReceiveLinesEditor from '../ReceiveLinesEditor';
import type { PODetailLineItem, PODetails } from '../receiveLines';

// The editor is pure presentation over the numbers - no Apollo, no router, no toasts. Everything
// that differs between the three screens using it (which mutation fires, what the buttons say)
// belongs to the parent, so this file only has to pin the data entry.

function line(over: Partial<PODetailLineItem> = {}): PODetailLineItem {
  return {
    id: 'li-1',
    poId: 'po-1',
    hardwareCategory: 'Hinges',
    productCode: 'HG-100',
    classification: null,
    orderedQuantity: 10,
    receivedQuantity: 7,
    unitCost: 2.5,
    orderAs: null,
    gpLineOrd: 1,
    ...over,
  };
}

function po(lineItems: PODetailLineItem[], over: Partial<PODetails> = {}): PODetails {
  return {
    id: 'po-1',
    poNumber: 'PO-123',
    projectId: 'proj-1',
    gpCompany: 'UCSH',
    vendorNameSnapshot: 'Acme Hardware',
    notes: null,
    status: 'ORDERED',
    lineItems,
    ...over,
  };
}

/** Controlled the way every real parent controls it, so a Fill click is observable on the field. */
function Harness({
  poDetailsList,
  initial = {},
  onChange,
  showPoHeaders = false,
}: {
  poDetailsList: PODetails[];
  initial?: Record<string, number>;
  onChange?: (lineId: string, value: number) => void;
  showPoHeaders?: boolean;
}) {
  const [quantities, setQuantities] = useState<Record<string, number>>(initial);
  return (
    <ReceiveLinesEditor
      poDetailsList={poDetailsList}
      receiveQuantities={quantities}
      onQuantityChange={(lineId, value) => {
        onChange?.(lineId, value);
        setQuantities((prev) => ({ ...prev, [lineId]: value }));
      }}
      showPoHeaders={showPoHeaders}
    />
  );
}

const fillButton = () => screen.getByRole('button', { name: 'Fill pending for HG-100 (3)' });
const qtyInput = () => screen.getByRole('spinbutton', { name: 'Receive now — HG-100 (max 3)' });

describe('ReceiveLinesEditor Fill shortcut (#632)', () => {
  it('fills the whole pending quantity in one click - the ordinary case is that it all arrived', () => {
    const onChange = vi.fn();
    render(<Harness poDetailsList={[po([line()])]} onChange={onChange} />);

    expect(qtyInput()).toHaveValue(0);
    fireEvent.click(fillButton());

    expect(onChange).toHaveBeenCalledWith('li-1', 3);
    expect(qtyInput()).toHaveValue(3);
  });

  it('goes disabled once the field already holds the pending quantity', () => {
    render(<Harness poDetailsList={[po([line()])]} />);

    expect(fillButton()).toBeEnabled();
    fireEvent.click(fillButton());
    expect(fillButton()).toBeDisabled();

    // Typing away from pending offers it again.
    fireEvent.change(qtyInput(), { target: { value: '1' } });
    expect(fillButton()).toBeEnabled();
  });

  it('names the pending count on its face and its label, per line', () => {
    render(
      <Harness
        poDetailsList={[
          po([line(), line({ id: 'li-3', productCode: 'CL-300', orderedQuantity: 4, receivedQuantity: 0 })]),
        ]}
      />,
    );
    expect(screen.getByRole('button', { name: 'Fill pending for HG-100 (3)' })).toHaveTextContent('Fill 3');
    expect(screen.getByRole('button', { name: 'Fill pending for CL-300 (4)' })).toHaveTextContent('Fill 4');
  });
});

describe('ReceiveLinesEditor row states', () => {
  it('a fully received line reads Fully Received, with nothing left to enter', () => {
    render(
      <Harness
        poDetailsList={[po([line(), line({ id: 'li-2', productCode: 'LK-200', orderedQuantity: 5, receivedQuantity: 5 })])]}
      />,
    );

    const fullRow = screen.getByText('LK-200').closest('tr') as HTMLElement;
    expect(within(fullRow).getByText('Fully Received')).toBeInTheDocument();
    expect(within(fullRow).queryByRole('spinbutton')).toBeNull();
    expect(within(fullRow).queryByRole('button')).toBeNull();

    // The line still owed keeps both controls.
    const pendingRow = screen.getByText('HG-100').closest('tr') as HTMLElement;
    expect(within(pendingRow).getByRole('spinbutton')).toBeInTheDocument();
    expect(within(pendingRow).getByRole('button')).toBeInTheDocument();
  });

  it('flags a count above what the line still owes, and clears once it is back in range', () => {
    render(<Harness poDetailsList={[po([line()])]} />);

    fireEvent.change(qtyInput(), { target: { value: '5' } });
    expect(screen.getByText('Max: 3')).toBeInTheDocument();

    fireEvent.change(qtyInput(), { target: { value: '3' } });
    expect(screen.queryByText('Max: 3')).toBeNull();
  });

  it('a cleared field reads as zero rather than NaN', () => {
    const onChange = vi.fn();
    render(<Harness poDetailsList={[po([line()])]} initial={{ 'li-1': 3 }} onChange={onChange} />);
    fireEvent.change(qtyInput(), { target: { value: '' } });
    expect(onChange).toHaveBeenCalledWith('li-1', 0);
  });
});

describe('ReceiveLinesEditor table shape (#632)', () => {
  it('renders every line at once - a delivery is counted top to bottom, not page by page', () => {
    // 30 lines is past any page size the old grid would have imposed; a page boundary mid-count
    // hides lines the counter still has to walk against the packing slip.
    const many = Array.from({ length: 30 }, (_, i) =>
      line({ id: `li-${i}`, productCode: `P-${i}`, orderedQuantity: 2, receivedQuantity: 0 }),
    );
    render(<Harness poDetailsList={[po(many)]} />);

    expect(screen.getAllByRole('spinbutton')).toHaveLength(30);
    expect(screen.getByText('P-29')).toBeInTheDocument();
    expect(screen.queryByText(/rows per page/i)).toBeNull();
  });

  it('names each PO above its own table only when a batch is being counted', () => {
    const two = [po([line()]), po([line({ id: 'li-3', poId: 'po-2', productCode: 'CL-300' })], { id: 'po-2', poNumber: 'PO-456' })];

    const { unmount } = render(<Harness poDetailsList={two} showPoHeaders />);
    expect(screen.getAllByRole('table')).toHaveLength(2);
    expect(screen.getByText(/PO-123/)).toBeInTheDocument();
    expect(screen.getByText(/PO-456/)).toBeInTheDocument();
    unmount();

    render(<Harness poDetailsList={[po([line()])]} />);
    expect(screen.queryByText(/PO-123/)).toBeNull();
  });

  it('carries the counter note down from the PO so the reviewer sees what was written', () => {
    render(<Harness poDetailsList={[po([line()], { notes: 'box crushed' })]} />);
    expect(screen.getByText(/Notes: box crushed/)).toBeInTheDocument();
  });
});
