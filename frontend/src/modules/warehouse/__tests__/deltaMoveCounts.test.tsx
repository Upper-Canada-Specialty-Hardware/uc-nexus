import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import type { DocumentNode } from 'graphql';
import type { ReactElement } from 'react';
import { ToastProvider } from '../../../components/Toast';
import ReclassifyStockModal from '../stock/ReclassifyStockModal';
import ReportStockDeficiencyModal from '../stock/ReportStockDeficiencyModal';
import DestockInventoryModal from '../stock/DestockInventoryModal';
import FlagDeficientModal from '../FlagDeficientModal';
import {
  DESTOCK_INVENTORY,
  RECLASSIFY_STOCK_ITEM,
  REPORT_INVENTORY_DEFICIENCY,
  REPORT_STOCK_DEFICIENCY,
} from '../../../graphql/warehouse';
import type { StockItem } from '../StockPoolView';

// The modals render inside a MUI Dialog; under the full parallel suite jsdom rendering is slow.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

// #1552: warehouse wifi drops after the server commits but before the reply lands, and the user
// confirms again. Every delta move sends the count its dialog showed, so that resend is refused.

const poolRow: StockItem = {
  id: 'si-1',
  warehouseId: 'wh-1',
  hardwareCategory: 'HINGE',
  productCode: 'HG-100',
  quantity: 10,
  deficientQuantity: 2,
  available: 8,
  unitCost: null,
  kind: 'STOCK',
  aisle: 'A',
  row: '1',
  bay: '1',
  receivedAt: '2026-09-01T12:00:00',
  createdAt: '2026-09-01T12:00:00',
  updatedAt: '2026-09-01T12:00:00',
};

/** A mock that records the variables it was sent and answers with null data. */
function capture(query: DocumentNode, field: string) {
  const calls: { input: Record<string, unknown> }[] = [];
  const mock: MockedResponse = {
    request: { query, variables: () => true },
    result: (vars) => {
      calls.push(vars as { input: Record<string, unknown> });
      return { data: { [field]: null } };
    },
  };
  return { calls, mock };
}

function renderWith(mocks: MockedResponse[], ui: ReactElement) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>{ui}</ToastProvider>
    </MockedProvider>,
  );
}

describe('delta move dialogs send the count they showed (#1552)', () => {
  it('reclassify sends the row count', async () => {
    const { calls, mock } = capture(RECLASSIFY_STOCK_ITEM, 'reclassifyStockItem');
    renderWith([mock], <ReclassifyStockModal item={poolRow} onClose={vi.fn()} onSuccess={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/New product code/), { target: { value: 'HG-200' } });
    fireEvent.change(screen.getByLabelText(/Quantity to reclassify/), { target: { value: '4' } });
    fireEvent.submit(screen.getByLabelText(/Quantity to reclassify/).closest('form')!);

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].input).toMatchObject({ quantity: 4, expectedQuantity: 10 });
  });

  it('report deficient on a pool row sends the flagged count', async () => {
    const { calls, mock } = capture(REPORT_STOCK_DEFICIENCY, 'reportStockDeficiency');
    renderWith([mock], <ReportStockDeficiencyModal item={poolRow} onClose={vi.fn()} onSuccess={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/Quantity to flag/), { target: { value: '3' } });
    fireEvent.submit(screen.getByLabelText(/Quantity to flag/).closest('form')!);

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].input).toMatchObject({ quantity: 3, expectedDeficientQuantity: 2 });
  });

  it('flag deficient on a project row sends the flagged count', async () => {
    const { calls, mock } = capture(REPORT_INVENTORY_DEFICIENCY, 'reportInventoryDeficiency');
    const item = {
      id: 'inv-1',
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      quantity: 10,
      deficientQuantity: 2,
      available: 8,
    };
    renderWith([mock], <FlagDeficientModal item={item} onClose={vi.fn()} onSuccess={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/Quantity to flag/), { target: { value: '1' } });
    fireEvent.submit(screen.getByLabelText(/Quantity to flag/).closest('form')!);

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].input).toMatchObject({ quantity: 1, expectedDeficientQuantity: 2 });
  });

  it('a row-changed refusal closes the dialog, so the retry starts from the fresh count', async () => {
    const message = 'This row changed from 10 to 6 since you opened it. Reload and try again.';
    const onClose = vi.fn();
    const onSuccess = vi.fn();
    const source = {
      id: 'inv-1',
      warehouseId: 'w1',
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      quantity: 10,
      deficientQuantity: 0,
      aisle: 'A1',
      row: 'R1',
      bay: 'B1',
    };
    renderWith(
      [
        {
          request: { query: DESTOCK_INVENTORY, variables: () => true },
          result: { errors: [{ message, extensions: { code: 'CONFLICT', field: 'expected_quantity' } }] },
        },
      ],
      <DestockInventoryModal inventoryLocation={source} onClose={onClose} onSuccess={onSuccess} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Left behind/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Destock' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
