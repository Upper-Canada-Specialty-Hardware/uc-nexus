import { useQuery } from '@apollo/client/react';
import { GET_RELAY_STATUS } from '../graphql/shared';

export interface RelayStatusInfo {
  // null = the first relayStatus check is still in flight.
  connected: boolean | null;
  // The GP company the connected relay is enrolled for; null when disconnected.
  company: string | null;
  // The connected relay's build tag (issue #315), e.g. 'relay-v0.1.0-build.30'. null when disconnected
  // or when an older relay that predates the hello frame is connected.
  build: string | null;
  // Which relay install is holding the connection (#366); null when disconnected. Lets the Relay
  // Installs grid disable Remove on the live row instead of letting the backend reject it.
  installId: string | null;
}

// Single definition of the relay-status poll (backend relayStatus field, the relay-to-backend WS
// channel - not a browser probe). Consumers pass skip: !open on dialogs/modals so a hidden one
// doesn't poll, which keeps this to one live poller at a time.
export function useRelayStatus(options?: { skip?: boolean }): RelayStatusInfo {
  const { data } = useQuery<{
    relayStatus: { connected: boolean; company: string | null; build: string | null; installId: string | null };
  }>(GET_RELAY_STATUS, {
    pollInterval: 10_000,
    fetchPolicy: 'cache-and-network',
    skip: options?.skip,
  });
  return {
    connected: data ? data.relayStatus.connected : null,
    company: data?.relayStatus.company ?? null,
    build: data?.relayStatus.build ?? null,
    installId: data?.relayStatus.installId ?? null,
  };
}
