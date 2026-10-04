import { render, renderHook, screen } from '@testing-library/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import RelayStatusChip from '../RelayStatusChip';
import { relayBlockedReason, relayServes, useRelayFor, useRelayStatus } from '../useRelayStatus';

// #1334 / #1336: what the relay status says when the poll itself fails, and whether a connected relay
// can actually do GP work for the company on screen.
const query = vi.hoisted(() => ({
  result: { data: undefined, previousData: undefined, error: undefined } as {
    data?: unknown;
    previousData?: unknown;
    error?: Error;
  },
}));

vi.mock('@apollo/client/react', () => ({
  useQuery: () => query.result,
}));

const identity = vi.hoisted(() => ({ company: 'TUBC' as string | null }));

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Jay Puzon',
    userId: 'user_1',
    roles: [],
    hasRole: () => false,
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.company,
    user: null,
  }),
}));

function status(connected: boolean, companies: string[]) {
  return {
    relayStatus: {
      connected,
      companies,
      gpCompanies: companies.map((id) => ({ id, name: id })),
      companiesError: null,
      build: null,
      installId: null,
      lastConnectedAt: null,
      lastDisconnectedAt: null,
      lastDisconnectReason: null,
    },
  };
}

beforeEach(() => {
  identity.company = 'TUBC';
  query.result = { data: undefined, previousData: undefined, error: undefined };
});

it('keeps the last good status across a failed poll instead of falling back to checking', () => {
  query.result = { data: undefined, previousData: status(true, ['TUBC']), error: new Error('Failed to fetch') };
  const { result } = renderHook(() => useRelayStatus());

  expect(result.current.connected).toBe(true);
  expect(result.current.companies).toEqual(['TUBC']);
  expect(result.current.error).toBe('Failed to fetch');
  expect(result.current.unreachable).toBe(false);
});

it('reports an unreachable Nexus, not a down relay, when no status has ever arrived', () => {
  query.result = { data: undefined, previousData: undefined, error: new Error('Failed to fetch') };
  const { result } = renderHook(() => useRelayFor());

  expect(result.current.connected).toBeNull();
  expect(result.current.unreachable).toBe(true);
  expect(result.current.servesCompany).toBe(false);
  expect(relayBlockedReason(result.current)).toMatch(/can't reach Nexus/i);
});

it('says nothing while the first check is still in flight', () => {
  const { result } = renderHook(() => useRelayFor());
  expect(result.current.unreachable).toBe(false);
  expect(relayBlockedReason(result.current)).toBeNull();
});

it('serves the acting company only when the connected relay lists it', () => {
  query.result = { data: status(true, ['UCSH']) };
  const { result } = renderHook(() => useRelayFor());

  expect(result.current.connected).toBe(true);
  expect(result.current.company).toBe('TUBC');
  expect(result.current.servesCompany).toBe(false);
  expect(relayBlockedReason(result.current)).toMatch(/not serving TUBC/);
});

it('takes an explicit company over the acting one', () => {
  query.result = { data: status(true, ['UCSH']) };
  const { result } = renderHook(() => useRelayFor('UCSH'));
  expect(result.current.servesCompany).toBe(true);
  expect(relayBlockedReason(result.current)).toBeNull();
});

it('points a down relay at the GP workstation, not this machine', () => {
  query.result = { data: status(false, []) };
  const { result } = renderHook(() => useRelayFor());
  expect(relayBlockedReason(result.current)).toMatch(/GP workstation/);
});

it('relayServes needs a connected relay that lists the company', () => {
  expect(relayServes({ connected: true, companies: ['TUBC'] }, 'TUBC')).toBe(true);
  expect(relayServes({ connected: true, companies: [] }, 'TUBC')).toBe(false);
  expect(relayServes({ connected: false, companies: ['TUBC'] }, 'TUBC')).toBe(false);
  expect(relayServes({ connected: null, companies: [] }, null)).toBe(false);
  expect(relayServes({ connected: true, companies: [] }, null)).toBe(true);
});

it('the chip shows an unreachable Nexus as its own state', () => {
  render(<RelayStatusChip connected={null} unreachable companies={[]} />);
  expect(screen.getByText("can't reach Nexus - retrying")).toBeInTheDocument();
  expect(screen.queryByText(/relay not connected/i)).toBeNull();
});

// #1403: a lapsed sign-in holds the poll back with AuthSuspendedError (or the backend answers
// UNAUTHENTICATED). That is neither Nexus down nor the relay down, so it reads as its own state.
function authSuspended() {
  const e = new Error('Your sign-in has lapsed. Sign in again to keep working.');
  e.name = 'AuthSuspendedError';
  return e;
}

it('reports a lapsed sign-in, not an unreachable Nexus, when the poll is held back for auth', () => {
  query.result = { data: undefined, previousData: undefined, error: authSuspended() };
  const { result } = renderHook(() => useRelayFor());

  expect(result.current.signInLapsed).toBe(true);
  expect(result.current.unreachable).toBe(false);
  expect(relayBlockedReason(result.current)).toMatch(/sign-in has lapsed/i);
});

it('reads an UNAUTHENTICATED answer as a lapsed sign-in', () => {
  const error = new CombinedGraphQLErrors({
    errors: [{ message: 'Not signed in', extensions: { code: 'UNAUTHENTICATED' } }],
  });
  query.result = { data: undefined, previousData: undefined, error };
  const { result } = renderHook(() => useRelayStatus());

  expect(result.current.signInLapsed).toBe(true);
  expect(result.current.unreachable).toBe(false);
});

it('still reports an unreachable Nexus for a network failure', () => {
  query.result = { data: undefined, previousData: undefined, error: new Error('Failed to fetch') };
  const { result } = renderHook(() => useRelayStatus());
  expect(result.current.signInLapsed).toBe(false);
  expect(result.current.unreachable).toBe(true);
});

it('the chip shows a lapsed sign-in as its own state', () => {
  render(<RelayStatusChip connected={null} signInLapsed companies={[]} />);
  expect(screen.getByText('sign-in lapsed')).toBeInTheDocument();
  expect(screen.queryByText(/can't reach Nexus/i)).toBeNull();
  expect(screen.queryByText(/relay not connected/i)).toBeNull();
});
