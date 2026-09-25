import { useQuery } from '@apollo/client/react';
import { GET_RELAY_STATUS } from '../graphql/shared';
import type { GpCompany } from './useRelayStatus';

const NO_COMPANIES: GpCompany[] = [];

/**
 * GP's display names for the company codes, WITHOUT a poller of its own (#831).
 *
 * Every project header, picker and GP-writing dialog now names its GP company, so this is mounted
 * almost everywhere. useRelayStatus polls every 10 seconds; a copy of that on every page would be a
 * poll per tab for a name that practically never changes (TopBarCompany avoids it for the same
 * reason). This reads the same relayStatus document cache-first: one fetch the first time a page
 * needs a name, and after that whatever the cache holds - which a live useRelayStatus poller, where
 * one is mounted, keeps fresh for free. The same document, not a slimmer one, so the two never fight
 * over the un-normalized root field in the cache.
 */
export function useGpCompanyNames(options?: { skip?: boolean }): GpCompany[] {
  const { data } = useQuery<{ relayStatus: { gpCompanies: GpCompany[] } }>(GET_RELAY_STATUS, {
    fetchPolicy: 'cache-first',
    skip: options?.skip,
  });
  return data?.relayStatus.gpCompanies ?? NO_COMPANIES;
}
