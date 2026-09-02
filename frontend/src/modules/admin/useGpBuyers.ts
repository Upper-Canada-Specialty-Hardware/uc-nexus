import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { GET_GP_BUYERS_DETAILED } from '../../graphql/admin';
import { isRelayOpUnsupported } from '../../graphql/gpError';
import { useRelayStatus, type GpCompany } from '../../relay/useRelayStatus';
import { useCompanyChoice } from '../../relay/useCompanyChoice';

export interface GpBuyerOption {
  buyerId: string;
  description: string | null;
}

export interface GpBuyersState {
  buyers: GpBuyerOption[];
  loading: boolean;
  /** The GP company the list was read for; '' while disconnected or when none applies. */
  company: string;
  /** #637: every company the live relay found in GP, for screens that assign one. Empty while down. */
  companies: string[];
  /** The same codes with GP's display names, so a picker can offer 'TUBC - Test UBC'. */
  gpCompanies: GpCompany[];
  /** Why a connected relay reported none; null when it reported some or nothing is connected. */
  companiesError: string | null;
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
export function useGpBuyers(options?: { skip?: boolean; company?: string | null }): GpBuyersState {
  const skip = options?.skip ?? false;
  const relay = useRelayStatus({ skip });
  const choice = useCompanyChoice(relay.companies);
  // #637: the buyer master is per company. A caller that knows which one it means - the company of
  // the user being edited - says so; otherwise the caller's own company is what the list is read for.
  const company = options?.company || choice.company;
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
    companies: relay.companies,
    gpCompanies: relay.gpCompanies,
    companiesError: relay.companiesError,
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
