import { render, screen } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import LocationAuditStrip from '../LocationAuditStrip';
import { GET_LOCATION_AUDIT_HISTORY } from '../../../graphql/warehouse';

const shelf = (aisle: string) => ({ aisle, row: '1', bay: '2', warehouseId: 'w1' });

function entry(id: string, action: string, detail: Record<string, unknown>) {
  return {
    __typename: 'AuditLogEntry',
    id,
    entityType: 'INVENTORY_LOCATION',
    entityId: 'inv-1',
    action,
    detail,
    performedBy: 'tester',
    createdAt: '2026-10-01T10:00:00',
  };
}

function renderStrip(entries: unknown[]) {
  render(
    <MockedProvider
      mocks={[
        {
          request: {
            query: GET_LOCATION_AUDIT_HISTORY,
            variables: { aisle: 'A', row: '1', bay: '2', limit: 10, warehouseId: 'w1' },
          },
          result: { data: { locationAuditHistory: entries } },
        },
      ]}
    >
      <LocationAuditStrip aisle="A" row="1" bay="2" warehouseId="w1" />
    </MockedProvider>,
  );
}

describe('LocationAuditStrip (#1896)', () => {
  it('names the shelf a receive landed on, from where every receive writer stores it', async () => {
    renderStrip([
      entry('1', 'RECEIVE', { quantity: 4, location: shelf('A') }),
      // An older receive that spelled it targetLocation.
      entry('2', 'RECEIVE', { targetLocation: shelf('B') }),
    ]);

    expect(await screen.findByText('Received 4 at A-1-2')).toBeInTheDocument();
    expect(screen.getByText('Received at B-1-2')).toBeInTheDocument();
  });

  it('reads every other action as words, never as its code', async () => {
    renderStrip([
      entry('1', 'TRANSFER', { quantity: 2, fromLocation: shelf('A'), toLocation: shelf('C') }),
      entry('2', 'RETURN', { quantity: 1, toLocation: shelf('A') }),
      entry('3', 'PULL_RESTOCK', { restockedQuantity: 3 }),
      entry('4', 'POOL_KIND_CHANGE', { quantity: 5, location: shelf('A') }),
      entry('5', 'SOMETHING_NEW', {}),
    ]);

    expect(await screen.findByText('Transferred 2 from A-1-2 to C-1-2')).toBeInTheDocument();
    expect(screen.getByText('Returned at A-1-2')).toBeInTheDocument();
    expect(screen.getByText('Pull Restocked')).toBeInTheDocument();
    expect(screen.getByText('Kind Changed at A-1-2')).toBeInTheDocument();
    expect(screen.getByText('Something new')).toBeInTheDocument();
    expect(screen.queryByText(/[A-Z]+_[A-Z]+/)).not.toBeInTheDocument();
  });
});
