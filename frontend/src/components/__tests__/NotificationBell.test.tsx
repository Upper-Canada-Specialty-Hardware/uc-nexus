import { render, screen, fireEvent } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import NotificationBell from '../NotificationBell';
import {
  GET_NOTIFICATIONS,
  GET_NOTIFICATION_UNREAD_COUNT,
  MARK_ALL_NOTIFICATIONS_AS_READ,
  MARK_NOTIFICATION_AS_READ,
} from '../../graphql/shared';

// An audience-wide notification is read by several people from several places, so only the
// person-targeted types name one place to go. Navigating on the rest would be a guess, and this file
// is the regression guard on that split.

function notification(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'Notification',
    id: 'n-1',
    projectId: 'proj-1',
    recipientRole: null,
    type: 'RECEIVE_DRAFT_REJECTED',
    message: 'For Wendy Warehouse: Manny sent back your receive against PO-123 - recount.',
    isRead: false,
    createdAt: '2026-08-02T11:00:00Z',
    ...overrides,
  };
}

function notificationsMocks(items: Record<string, unknown>[], unreadCount?: number): MockedResponse[] {
  return [
    {
      request: { query: GET_NOTIFICATIONS, variables: { limit: 5 } },
      result: { data: { notifications: items } },
      maxUsageCount: Number.POSITIVE_INFINITY,
    },
    {
      request: { query: GET_NOTIFICATION_UNREAD_COUNT },
      result: {
        data: { notificationUnreadCount: unreadCount ?? items.filter((n) => !n.isRead).length },
      },
      maxUsageCount: Number.POSITIVE_INFINITY,
    },
  ];
}

function markAllMock(calls: { count: number }): MockedResponse {
  return {
    request: { query: MARK_ALL_NOTIFICATIONS_AS_READ },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: () => {
      calls.count += 1;
      return { data: { markAllNotificationsAsRead: 3 } };
    },
  };
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

function renderBell(
  items: Record<string, unknown>[],
  seen: string[] = [],
  { unreadCount, markAll = { count: 0 } }: { unreadCount?: number; markAll?: { count: number } } = {},
) {
  render(
    <MockedProvider mocks={[...notificationsMocks(items, unreadCount), markReadMock(seen), markAllMock(markAll)]}>
      <MemoryRouter initialEntries={['/app']}>
        <Routes>
          <Route path="/app" element={<NotificationBell />} />
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

  it('still opens the notification when marking it read fails', async () => {
    const items = [notification({ id: 'n-3' })];
    render(
      <MockedProvider
        mocks={[
          ...notificationsMocks(items),
          {
            request: { query: MARK_NOTIFICATION_AS_READ, variables: () => true },
            error: new Error('Notification not found'),
          },
        ]}
      >
        <MemoryRouter initialEntries={['/app']}>
          <Routes>
            <Route path="/app" element={<NotificationBell />} />
            <Route path="/app/warehouse/receiving" element={<div>Receiving</div>} />
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </MockedProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: /Notifications/ }));
    fireEvent.click(await screen.findByText(/sent back your receive/, undefined, SLOW));

    await screen.findByText('Receiving', undefined, SLOW);
    expect(screen.getByTestId('location')).toHaveTextContent('/app/warehouse/receiving?view=drafts');
  });

  it('marks every unread notification read with one request', async () => {
    // The popover only lists the latest few, and the badge counts every unread, so one action has to
    // reach the whole backlog. #1112: one bulk mutation, not one request per notification.
    const seen: string[] = [];
    const markAll = { count: 0 };
    renderBell(
      [
        notification({ id: 'n-a', type: 'PULL_REQUEST_COMPLETED', message: 'Pull A fulfilled.' }),
        notification({ id: 'n-b', type: 'PULL_REQUEST_COMPLETED', message: 'Pull B fulfilled.' }),
        notification({ id: 'n-c', type: 'PULL_REQUEST_COMPLETED', message: 'Pull C fulfilled.' }),
      ],
      seen,
      { markAll },
    );

    fireEvent.click(screen.getByRole('button', { name: /Notifications/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Mark all read/ }, SLOW));

    await vi.waitFor(() => expect(markAll.count).toBe(1), SLOW);
    expect(seen).toEqual([]);
  });

  it('shows 99+ when more than 99 are unread', async () => {
    // #1112: the count used to be the length of a 99-row fetch, so the badge could never pass 99.
    // #1224: the server now stops at 100, so 100 is what "a lot" looks like; it must read as 99+
    // on the badge, the label and the chip, never as an exact 100.
    renderBell([notification({ id: 'n-x', type: 'PULL_REQUEST_COMPLETED', message: 'X' })], [], {
      unreadCount: 100,
    });

    const bell = await screen.findByRole('button', { name: 'Notifications, 99+ unread' }, SLOW);
    expect(screen.getByText('99+')).toBeInTheDocument();
    fireEvent.click(bell);
    expect(await screen.findByText('99+ new', undefined, SLOW)).toBeInTheDocument();
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

  it('says the notifications failed to load rather than "nothing to review" (#1503)', async () => {
    render(
      <MockedProvider
        mocks={[
          {
            request: { query: GET_NOTIFICATIONS, variables: { limit: 5 } },
            error: new Error('Network down'),
            maxUsageCount: Number.POSITIVE_INFINITY,
          },
          notificationsMocks([])[1],
        ]}
      >
        <MemoryRouter>
          <NotificationBell />
        </MemoryRouter>
      </MockedProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: /Notifications/ }));
    expect(await screen.findByText(/couldn.t load your notifications/i, undefined, SLOW)).toBeInTheDocument();
    expect(screen.queryByText('Nothing to review right now')).not.toBeInTheDocument();
  });
});
