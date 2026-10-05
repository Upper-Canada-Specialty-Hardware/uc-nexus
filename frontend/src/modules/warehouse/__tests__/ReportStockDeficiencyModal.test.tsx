import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import { REPORT_STOCK_DEFICIENCY } from '../../../graphql/warehouse';
import ReportStockDeficiencyModal from '../stock/ReportStockDeficiencyModal';
import type { StockItem } from '../StockPoolView';

// Renders inside a MUI Dialog; lift the budgets like the other modal tests do.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

const item: StockItem = {
  id: 's1',
  warehouseId: 'w1',
  hardwareCategory: 'HINGE',
  productCode: 'HG-100',
  quantity: 5,
  deficientQuantity: 0,
  available: 5,
  unitCost: null,
  kind: 'STOCK',
  aisle: null,
  row: null,
  bay: null,
  receivedAt: '2026-10-01T00:00:00Z',
  createdAt: '2026-10-01T00:00:00Z',
  updatedAt: '2026-10-01T00:00:00Z',
};

// #1548: Flag deficient on a pool row took no Enter, left the quantity unfocused, and went dead on 6 of
// 5 with nothing saying why.
it('focuses the quantity, says why Flag deficient is off, and sends once on Enter', async () => {
  const result = vi.fn(() => ({ data: { reportStockDeficiency: null } }));
  render(
    <MockedProvider mocks={[{ request: { query: REPORT_STOCK_DEFICIENCY, variables: () => true }, result }]}>
      <ToastProvider>
        <ReportStockDeficiencyModal item={item} onClose={vi.fn()} onSuccess={vi.fn()} />
      </ToastProvider>
    </MockedProvider>,
  );
  const qty = screen.getByLabelText(/Quantity to flag \(max 5\)/);
  await waitFor(() => expect(qty).toHaveFocus());

  fireEvent.change(qty, { target: { value: '6' } });
  expect(screen.getByText('Enter a whole number from 1 to 5')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Flag deficient' })).toBeDisabled();
  fireEvent.submit(qty.closest('form')!);

  fireEvent.change(qty, { target: { value: '2' } });
  fireEvent.submit(qty.closest('form')!);
  fireEvent.submit(qty.closest('form')!);

  await waitFor(() => expect(result).toHaveBeenCalledTimes(1));
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(result).toHaveBeenCalledTimes(1);
});
