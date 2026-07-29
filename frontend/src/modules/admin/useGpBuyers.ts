import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { GET_GP_BUYERS_DETAILED } from '../../graphql/admin';
import { isRelayOpUnsupported } from '../../graphql/gpError';
import { useRelayStatus } from '../../relay/useRelayStatus';

export interface GpBuyerOption {
  buyerId: string;
  description: string | null;
}

export interface GpBuyersState {
  buyers: GpBuyerOption[];
  loading: boolean;
  /** The connected relay is enrolled for exactly one GP company; '' while disconnected. */
  company: string;
  relayConnected: boolean;
  /** null while the first relay-status check is in flight, so "not yet known" isn't shown as "down". */
  relayStatus: boolean | null;
  /** The installed relay predates list_buyers_detailed (#315 gating). */
  unsupported: boolean;
  /** Any reason the live list can't be trusted: relay down, op unsupported, or the read failed. */
  unavailable: boolean;
  error: Error | null;
  refetch: () => void;
}

/**
 * GP's buyer master (POP00101) read live through the relay, for the admin screens that assign or
 * register a buyer identity (#409).
 *
 * Shared rather than queried per page because both consumers need the same three-way state - list,
 * relay down, relay too old - and a page that got any of them wrong would put an id into Clerk that
 * GP never registered, which surfaces much later as a rejected PO (taPoHdr error 269).
 *
 * `unavailable` deliberately folds a failed read in with a missing one: an empty list from a query
 * that errored must not read as "this company has no buyers", which is the state that would let a
 * blank dropdown look like an answer.
 */
export function useGpBuyers(options?: { skip?: boolean }): GpBuyersState {
  const skip = options?.skip ?? false;
  const relay = useRelayStatus({ skip });
  const company = relay.company ?? '';
  const relayConnected = relay.connected === true;

  const { data, loading, error, refetch } = useQuery<{ gpBuyersDetailed: GpBuyerOption[] }>(
    GET_GP_BUYERS_DETAILED,
    {
      variables: { company },
      skip: skip || !relayConnected || !company,
      fetchPolicy: 'cache-and-network',
    },
  );

  const buyers = useMemo(() => data?.gpBuyersDetailed ?? [], [data]);
  const unsupported = isRelayOpUnsupported(error);

  return {
    buyers,
    loading,
    company,
    relayConnected,
    relayStatus: relay.connected,
    unsupported,
    unavailable: !relayConnected || Boolean(error),
    error: error ?? null,
    refetch: () => {
      void refetch();
    },
  };
}
