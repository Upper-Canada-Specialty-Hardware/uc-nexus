import { useQuery } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { GET_RELAY_STATUS } from '../graphql/shared';
import { useActingCompany } from '../company/ActingCompanyContext';

// One shared empty list so a disconnected relay keeps the same array identity across renders - a
// fresh [] each poll would invalidate every consumer's memo for nothing.
const NO_STRINGS: string[] = [];
const NO_COMPANIES: GpCompany[] = [];

/** One GP company the live relay serves, as GP names it. `name` falls back to the code. */
export interface GpCompany {
  id: string;
  name: string;
}

export interface RelayStatusInfo {
  // null = the first relayStatus check is still in flight.
  connected: boolean | null;
  // #637: the GP companies the connected relay discovered in GP's company master; empty when
  // disconnected or when discovery failed. A tenant IS a company.
  companies: string[];
  // The same codes with GP's display name attached, for anything that labels an option rather than
  // showing a bare code. Same order and membership as `companies`.
  gpCompanies: GpCompany[];
  // Why a CONNECTED relay reported no companies - GP unreachable, a relay too old to look. null when
  // it reported some, and when nothing is connected (that is its own explanation).
  companiesError: string | null;
  // The connected relay's build tag (issue #315), e.g. 'relay-v0.1.0-build.30'. null when disconnected
  // or when an older relay that predates the hello frame is connected.
  build: string | null;
  // Which relay install is holding the connection (#366); null when disconnected. Lets the Relay
  // Installs grid disable Remove on the live row instead of letting the backend reject it.
  installId: string | null;
  // When the link last came up / went down, and why it went down. Null until the backend has seen
  // one of those transitions since it started.
  lastConnectedAt: string | null;
  lastDisconnectedAt: string | null;
  lastDisconnectReason: string | null;
  // #1334: the status poll itself failed (backend redeploying, network blip). The fields above keep the
  // last status that DID arrive, so a failed poll never reads as the relay going down. null when the
  // last poll succeeded.
  error: string | null;
  // #1334: no status has ever arrived and the poll is failing - Nexus is unreachable, which says
  // nothing about the relay. Shown as its own state instead of "relay not connected".
  unreachable: boolean;
  // #1403: no status has arrived because the user's sign-in lapsed - the poll is held back (or refused)
  // until they sign in again. Nexus and the relay may both be fine, so this is neither of those states.
  signInLapsed: boolean;
}

// #1403: the poll failed because the session lapsed, not because Nexus is down. Matched by name so this
// hook does not pull in the Apollo client module: apollo.ts raises AuthSuspendedError while the session
// is lapsed and MissingAuthTokenError when no token could be minted; the backend answers UNAUTHENTICATED.
const AUTH_ERROR_NAMES = new Set(['AuthSuspendedError', 'MissingAuthTokenError']);

export function isSignInLapsedError(error: unknown): boolean {
  if (CombinedGraphQLErrors.is(error)) {
    return error.errors.some((e) => e.extensions?.code === 'UNAUTHENTICATED');
  }
  return error instanceof Error && AUTH_ERROR_NAMES.has(error.name);
}

// Single definition of the relay-status poll (backend relayStatus field, the relay-to-backend WS
// channel - not a browser probe). Consumers pass skip: !open on dialogs/modals so a hidden one
// doesn't poll, which keeps this to one live poller at a time.
export function useRelayStatus(options?: { skip?: boolean }): RelayStatusInfo {
  const { data: current, previousData, error } = useQuery<{
    relayStatus: {
      connected: boolean;
      companies: string[];
      gpCompanies: GpCompany[];
      companiesError: string | null;
      build: string | null;
      installId: string | null;
      lastConnectedAt: string | null;
      lastDisconnectedAt: string | null;
      lastDisconnectReason: string | null;
    };
  }>(GET_RELAY_STATUS, {
    pollInterval: 10_000,
    fetchPolicy: 'cache-and-network',
    skip: options?.skip,
  });
  // #1334: an errored poll comes back with no data. Keep the last good answer instead of falling back
  // to "checking" - a backend redeploy is minutes of failed polls while the relay is perfectly fine.
  const data = current ?? previousData;
  return {
    connected: data ? data.relayStatus.connected : null,
    companies: data?.relayStatus.companies ?? NO_STRINGS,
    gpCompanies: data?.relayStatus.gpCompanies ?? NO_COMPANIES,
    companiesError: data?.relayStatus.companiesError ?? null,
    build: data?.relayStatus.build ?? null,
    installId: data?.relayStatus.installId ?? null,
    lastConnectedAt: data?.relayStatus.lastConnectedAt ?? null,
    lastDisconnectedAt: data?.relayStatus.lastDisconnectedAt ?? null,
    lastDisconnectReason: data?.relayStatus.lastDisconnectReason ?? null,
    error: error ? error.message : null,
    unreachable: !data && Boolean(error) && !isSignInLapsedError(error),
    signInLapsed: !data && isSignInLapsedError(error),
  };
}

export interface RelayForCompany extends RelayStatusInfo {
  // The company GP work on screen is for: the one passed in, or the acting company.
  company: string | null;
  // #1336: the relay is connected AND serves that company. The backend refuses every GP read and write
  // for a company the relay does not serve, so this, not `connected`, is what GP actions gate on. With
  // no company known yet it is just `connected` (callers already hold their reads until a company is).
  servesCompany: boolean;
}

/** Whether `relay` can do GP work for `company` (#1336). */
export function relayServes(relay: Pick<RelayStatusInfo, 'connected' | 'companies'>, company: string | null): boolean {
  if (relay.connected !== true) return false;
  return company ? relay.companies.includes(company) : true;
}

/** #1336: `relay` read for `company` - for callers that already know their company. */
export function relayFor(relay: RelayStatusInfo, company: string | null): RelayForCompany {
  return { ...relay, company, servesCompany: relayServes(relay, company) };
}

// #1336: the relay status plus the one question GP actions ask of it - can it do GP work for the
// company on screen? Pass `company` where the work is for a specific one (a PO's own company); without
// it, the acting company from the app bar.
export function useRelayFor(company?: string | null, options?: { skip?: boolean }): RelayForCompany {
  const relay = useRelayStatus(options);
  const { company: acting } = useActingCompany();
  return relayFor(relay, company ?? acting ?? null);
}

/** #1334/#1336: the one sentence explaining why GP actions are off, or null when they are on. */
export function relayBlockedReason(relay: RelayForCompany): string | null {
  if (relay.signInLapsed) return 'Your sign-in has lapsed - sign in again to use GP.';
  if (relay.unreachable) return "Can't reach Nexus right now - retrying.";
  if (relay.connected === null) return null; // first check still in flight
  if (relay.connected === false) {
    return 'The GP relay (on the GP workstation) is not connected - ask an admin to check it.';
  }
  if (!relay.servesCompany && relay.company) {
    return `The GP relay is connected but is not serving ${relay.company} - ask an admin to check it.`;
  }
  return null;
}
