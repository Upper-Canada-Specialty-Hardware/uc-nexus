import { render, screen, fireEvent } from '@testing-library/react';
import ImportSuccessDialog, { type ImportSuccessResult } from '../ImportSuccessDialog';

/** #859: the success screen leads with the next step for what the run created. */

const PROJECT = { projectId: '23094', description: 'Cowichan District Hospital' };

function result(overrides: Partial<ImportSuccessResult> = {}): ImportSuccessResult {
  return { project: PROJECT, purchaseOrders: [], shippingOutRequests: [], shopAssemblyRequest: null, ...overrides };
}

function buttonNames() {
  return screen.getAllByRole('button').map((b) => b.textContent);
}

describe('ImportSuccessDialog', () => {
  it('sends a shop assembly request to the shop assembly requests page', () => {
    const onAction = vi.fn();
    render(
      <ImportSuccessDialog
        open
        result={result({ shopAssemblyRequest: { id: 'sar-1', requestNumber: 'SAR-0007' } })}
        onAction={onAction}
      />,
    );

    expect(buttonNames()).toEqual(['View shop assembly requests', 'Return to Home']);
    fireEvent.click(screen.getByRole('button', { name: 'View shop assembly requests' }));
    expect(onAction).toHaveBeenCalledWith('shop-assembly');
  });

  it('sends purchase orders to the PO table, with no warehouse detour', () => {
    const onAction = vi.fn();
    render(<ImportSuccessDialog open result={result({ purchaseOrders: [{ id: 'po-1' }] })} onAction={onAction} />);

    expect(buttonNames()).toEqual(['View purchase orders', 'Return to Home']);
    expect(screen.queryByRole('button', { name: /warehouse/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'View purchase orders' }));
    expect(onAction).toHaveBeenCalledWith('po');
  });

  it('offers one next step per kind created', () => {
    render(
      <ImportSuccessDialog
        open
        result={result({
          purchaseOrders: [{ id: 'po-1' }],
          shippingOutRequests: [{ id: 'sor-1', requestNumber: 'SOR-0003' }],
          shopAssemblyRequest: { id: 'sar-1', requestNumber: 'SAR-0007' },
        })}
        onAction={vi.fn()}
      />,
    );

    expect(buttonNames()).toEqual([
      'View shop assembly requests',
      'View shipping requests',
      'View purchase orders',
      'Return to Home',
    ]);
  });

  it('leaves only the way home when the run created none of them', () => {
    const onAction = vi.fn();
    render(<ImportSuccessDialog open result={result()} onAction={onAction} />);

    expect(buttonNames()).toEqual(['Return to Home']);
    fireEvent.click(screen.getByRole('button', { name: 'Return to Home' }));
    expect(onAction).toHaveBeenCalledWith('home');
  });
});
