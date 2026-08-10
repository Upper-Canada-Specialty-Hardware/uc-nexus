import { render, screen, fireEvent, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import AuditHistoryDrawer from '../AuditHistoryDrawer';
import { GET_AUDIT_LOG } from '../../../graphql/shared';

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
      { request: { query: GET_AUDIT_LOG, variables: baseVars(50) }, result: { data: { auditLog: makeEntries(51, 5) } } },
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
