import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import NotificationBell from '../NotificationBell';
import { GET_NOTIFICATIONS, MARK_NOTIFICATION_AS_READ } from '../../graphql/shared';

// The bell shows every notification to everybody (recipient_role is an audience tag, not access
// control), so only the person-targeted types name one place to go. Navigating on the rest would be
// a guess, and this file is the regression guard on that split.

function notification(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'Notification',
    id: 'n-1',
    projectId: 'proj-1',
    recipientRole: 'u_creator',
    type: 'RECEIVE_DECISION_REQUIRED',
    message: '3 units received against PO-123.',
    isRead: false,
    createdAt: '2026-08-02T11:00:00Z',
    ...overrides,
  };
}

function notificationsMocks(items: Record<string, unknown>[]): MockedResponse[] {
  return [
    {
      request: { query: GET_NOTIFICATIONS, variables: { limit: 5 } },
      result: { data: { notifications: items } },
      maxUsageCount: Number.POSITIVE_INFINITY,
    },
    {
      request: { query: GET_NOTIFICATIONS, variables: { unreadOnly: true, limit: 99 } },
      result: { data: { notifications: items.filter((n) => !n.isRead) } },
      maxUsageCount: Number.POSITIVE_INFINITY,
    },
  ];
}

function markReadMock(seen: string[]): MockedResponse<Record<string, unknown>, { id: string }> {
  return {
    request: { query: MARK_NOTIFICATION_AS_READ, variables: () => true },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: (vars) => {
      seen.push(vars.id);
      return {
        data: {
          markNotificationAsRead: { __typename: 'Notification', id: vars.id, isRead: true },
        },
      };
    },
  };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function renderBell(items: Record<string, unknown>[], seen: string[] = []) {
  render(
    <MockedProvider mocks={[...notificationsMocks(items), markReadMock(seen)]}>
      <MemoryRouter initialEntries={['/app']}>
        <Routes>
          <Route path="/app" element={<NotificationBell />} />
          <Route path="/app/po/decisions" element={<div>Shipment Decisions</div>} />
          <Route path="/app/warehouse/receiving" element={<div>Receiving</div>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </MockedProvider>,
  );
}

const SLOW = { timeout: 5000 };

vi.setConfig({ testTimeout: 30_000 });

describe('NotificationBell', () => {
  it('takes the PO creator to the decision they owe an answer to', async () => {
    renderBell([notification()]);

    fireEvent.click(screen.getByRole('button', { name: /Notifications/ }));
    fireEvent.click(await screen.findByText('3 units received against PO-123.', undefined, SLOW));

    await screen.findByText('Shipment Decisions', undefined, SLOW);
    expect(screen.getByTestId('location')).toHaveTextContent('/app/po/decisions');
  });

  it('takes a warehouse user to their drafts when one is sent back', async () => {
    renderBell([
      notification({
        id: 'n-2',
        type: 'RECEIVE_DRAFT_REJECTED',
        message: 'For Wendy Warehouse: Manny sent back your receive against PO-123 - recount.',
      }),
    ]);

    fireEvent.click(screen.getByRole('button', { name: /Notifications/ }));
    fireEvent.click(await screen.findByText(/sent back your receive/, undefined, SLOW));

    await screen.findByText('Receiving', undefined, SLOW);
    expect(screen.getByTestId('location')).toHaveTextContent('/app/warehouse/receiving?view=drafts');
  });

  it('still only marks an audience-wide notification read, without navigating', async () => {
    // The pre-existing types are read by several people from several places, so there is no one
    // screen a click should take them to.
    const seen: string[] = [];
    renderBell(
      [notification({ id: 'n-3', type: 'PULL_REQUEST_COMPLETED', message: 'Pull Request PR-9 has been fulfilled.' })],
      seen,
    );

    fireEvent.click(screen.getByRole('button', { name: /Notifications/ }));
    fireEvent.click(await screen.findByText('Pull Request PR-9 has been fulfilled.', undefined, SLOW));

    await vi.waitFor(() => expect(seen).toEqual(['n-3']), SLOW);
    expect(screen.getByTestId('location')).toHaveTextContent('/app');
  });
});
