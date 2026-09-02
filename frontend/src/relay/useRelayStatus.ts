import { useQuery } from '@apollo/client/react';
import { GET_RELAY_STATUS } from '../graphql/shared';

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
  // Production only: the preview-environment sockets the relay is being told to dial as well.
  previewChannels: string[];
}

// Single definition of the relay-status poll (backend relayStatus field, the relay-to-backend WS
// channel - not a browser probe). Consumers pass skip: !open on dialogs/modals so a hidden one
// doesn't poll, which keeps this to one live poller at a time.
export function useRelayStatus(options?: { skip?: boolean }): RelayStatusInfo {
  const { data } = useQuery<{
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
      previewChannels: string[];
    };
  }>(GET_RELAY_STATUS, {
    pollInterval: 10_000,
    fetchPolicy: 'cache-and-network',
    skip: options?.skip,
  });
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
    previewChannels: data?.relayStatus.previewChannels ?? NO_STRINGS,
  };
}
