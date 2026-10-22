import { render, screen, fireEvent, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import AuditHistoryDrawer from '../AuditHistoryDrawer';
import { GET_AUDIT_LOG, GET_WAREHOUSES } from '../../../graphql/shared';

// The drawer renders a MUI Drawer with a full page of rows; give it room under the parallel suite.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

function makeEntries(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => {
    const n = start + i;
    return {
      id: String(n),
      projectId: null,
      entityType: 'INVENTORY_LOCATION',
      entityId: 'inv-1',
      action: 'NOTE',
      detail: null,
      performedBy: `counter-${n}`,
      createdAt: '2026-08-01T10:00:00',
      __typename: 'AuditLogEntry',
    };
  });
}

function baseVars(offset: number) {
  return { entityId: 'inv-1', entityType: 'INVENTORY_LOCATION', limit: 50, offset };
}

describe('AuditHistoryDrawer pagination', () => {
  it('loads the next page on demand and appends it, then hides Load more at the end', async () => {
    const mocks: MockedResponse[] = [
      { request: { query: GET_AUDIT_LOG, variables: baseVars(0) }, result: { data: { auditLog: makeEntries(1, 50) } } },
      // #1269: the next page is asked for by keyset - older than the last entry shown - not by offset.
      {
        request: { query: GET_AUDIT_LOG, variables: { ...baseVars(0), beforeId: '50' } },
        result: { data: { auditLog: makeEntries(51, 5) } },
      },
    ];

    render(
      <MockedProvider mocks={mocks}>
        <AuditHistoryDrawer open onClose={vi.fn()} entityId="inv-1" entityType="INVENTORY_LOCATION" />
      </MockedProvider>,
    );

    // First page present; a full page means Load more is offered and the second page is not yet here.
    expect(await screen.findByText('by counter-1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load more' })).toBeInTheDocument();
    expect(screen.queryByText('by counter-55')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

    // Second page appended, and a short page retires the Load more affordance.
    expect(await screen.findByText('by counter-55')).toBeInTheDocument();
    expect(screen.getByText('by counter-1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Load more/i })).not.toBeInTheDocument();
  });
});

describe('AuditHistoryDrawer event detail (#974)', () => {
  const entry = (id: string, action: string, detail: Record<string, unknown>) => ({
    id,
    projectId: null,
    entityType: 'INVENTORY_LOCATION',
    entityId: 'inv-1',
    action,
    detail,
    performedBy: 'tester',
    createdAt: '2026-10-01T10:00:00',
    __typename: 'AuditLogEntry',
  });
  const loc = (aisle: string, warehouseId: string) => ({ aisle, row: '1', bay: '2', warehouseId });

  it('shows the quantity and key detail of transfer, destock, deficiency and the rest', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_AUDIT_LOG, variables: baseVars(0) },
        result: {
          data: {
            auditLog: [
              entry('1', 'TRANSFER', {
                quantity: 4,
                fromWarehouseId: 'w1',
                fromLocation: loc('A', 'w1'),
                toWarehouseId: 'w2',
                toLocation: loc('B', 'w2'),
              }),
              entry('2', 'DESTOCK', { quantity: 2, destockCost: 'ZERO', targetLocation: loc('C', 'w1') }),
              entry('3', 'REPORT_DEFICIENT', { quantity: 1, reasonText: 'bent' }),
              entry('4', 'RESOLVE_DEFICIENT', { quantity: 1, resolution: 'RETURN_TO_VENDOR', rmaReference: 'RMA-9' }),
              entry('5', 'POOL_KIND_CHANGE', { quantity: 3, fromKind: 'STOCK', toKind: 'OVERHEAD' }),
            ],
          },
        },
      },
      {
        request: { query: GET_WAREHOUSES, variables: { includeInactive: true } },
        result: {
          data: {
            warehouses: [
              { id: 'w1', code: 'VAN', __typename: 'Warehouse' },
              { id: 'w2', code: 'KEL', __typename: 'Warehouse' },
            ],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks}>
        <AuditHistoryDrawer open onClose={vi.fn()} entityId="inv-1" entityType="INVENTORY_LOCATION" />
      </MockedProvider>,
    );

    expect(await screen.findByText('Transferred')).toBeInTheDocument();
    expect(await screen.findByText('VAN A-1-2 → KEL B-1-2')).toBeInTheDocument();
    expect(screen.getByText('Destocked')).toBeInTheDocument();
    expect(screen.getByText('Left behind - $0')).toBeInTheDocument();
    expect(screen.getByText('bent')).toBeInTheDocument();
    expect(screen.getByText('Returned to vendor')).toBeInTheDocument();
    expect(screen.getByText('RMA-9')).toBeInTheDocument();
    expect(screen.getByText('Stock → Overhead')).toBeInTheDocument();
    // Every one of them carries its quantity.
    expect(screen.getAllByText(/^[1-4]$/)).toHaveLength(5);
  });

  const renderEntries = (auditLog: unknown[]) =>
    render(
      <MockedProvider
        mocks={[
          { request: { query: GET_AUDIT_LOG, variables: baseVars(0) }, result: { data: { auditLog } } },
          {
            request: { query: GET_WAREHOUSES, variables: { includeInactive: true } },
            result: { data: { warehouses: [{ id: 'w1', code: 'VAN', __typename: 'Warehouse' }] } },
          },
        ]}
      >
        <AuditHistoryDrawer open onClose={vi.fn()} entityId="inv-1" entityType="INVENTORY_LOCATION" />
      </MockedProvider>,
    );

  it('shows what an override left on the row, where it placed the rest, and the rows it created (#1895)', async () => {
    renderEntries([
      entry('1', 'ADJUSTMENT', {
        oldQuantity: 5,
        newQuantity: 6,
        adjustment: 1,
        requestedQuantity: 9,
        reason: 'found extra',
        override: true,
        destinations: [
          { aisle: 'A', row: '1', bay: '1', quantity: 1 },
          { aisle: 'B', row: '2', bay: '2', quantity: 3 },
        ],
      }),
      entry('2', 'ADJUSTMENT', {
        createdByOverrideOf: 'inv-0',
        oldQuantity: 0,
        newQuantity: 3,
        adjustment: 3,
        quantity: 3,
        location: { aisle: 'B', row: '2', bay: '2', warehouseId: 'w1' },
        reason: 'found extra',
      }),
      // Written before #1895: `delta` where the drawer reads `adjustment`.
      entry('3', 'ADJUSTMENT', { oldQuantity: 2, newQuantity: 4, delta: 2, reason: 'old', override: true }),
    ]);

    expect(await screen.findByText('5 → 6 (+1)')).toBeInTheDocument();
    expect(screen.getByText('1 at A-1-1, 3 at B-2-2')).toBeInTheDocument();
    expect(screen.getByText('Created by Override')).toBeInTheDocument();
    expect(await screen.findByText('VAN B-2-2')).toBeInTheDocument();
    expect(screen.getByText('2 → 4 (+2)')).toBeInTheDocument();
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  });
});
