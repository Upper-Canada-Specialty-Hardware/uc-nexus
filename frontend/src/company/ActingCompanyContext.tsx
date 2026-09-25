import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useApolloClient, useQuery } from '@apollo/client/react';
import { GET_NEXUS_COMPANIES } from '../graphql/shared';
import { useIdentity } from '../hooks/useIdentity';
import type { GpCompany } from '../relay/useRelayStatus';
import {
  publishActingCompanyHeader,
  readLastPick,
  readTabPick,
  rememberPick,
  resolveActingCompany,
} from './actingCompany';

export interface ActingCompanyState {
  /**
   * The GP company everything on screen belongs to. A scoped user's own assignment, or the company a
   * UC NEXUS ADMIN has switched to. Null for an unassigned user, and for an admin until it is known.
   */
  company: string | null;
  /** What an admin can switch between, with GP's names. Empty for everyone else. */
  companies: GpCompany[];
  /** Only a UC NEXUS ADMIN switches; everyone else is always in their own company. */
  canSwitch: boolean;
  setCompany: (company: string) => void;
  /**
   * An admin whose company is not known yet: no pick anywhere and the list still loading. Pages hold
   * off rather than show every company mixed together for a moment.
   */
  resolving: boolean;
}

const NO_COMPANIES: GpCompany[] = [];
const noop = () => {};

const ActingCompanyContext = createContext<ActingCompanyState | null>(null);

/**
 * Holds which GP company a UC NEXUS ADMIN is working in (#845), and tells the Apollo client so every
 * request carries it.
 *
 * Mounted once at the root, inside ApolloProvider (it reads the company list and resets the cache on
 * a switch) and ClerkProvider (it reads the identity).
 */
export function ActingCompanyProvider({ children }: { children: ReactNode }) {
  const { isNexusAdmin, company: own } = useIdentity();
  const client = useApolloClient();
  const [tabPick, setTabPick] = useState<string | null>(readTabPick);
  // Read once: a pick another tab makes later must not move this one.
  const [lastPick] = useState<string | null>(readLastPick);

  const { data, loading } = useQuery<{ nexusCompanies: GpCompany[] }>(GET_NEXUS_COMPANIES, {
    skip: !isNexusAdmin,
    fetchPolicy: 'cache-first',
  });
  const companies = isNexusAdmin ? (data?.nexusCompanies ?? NO_COMPANIES) : NO_COMPANIES;
  // A failed read (a backend that predates the list) leaves this null, and the stored pick or the own
  // assignment is taken on trust - the same as before the list arrives.
  const available = useMemo(() => (data ? data.nexusCompanies.map((c) => c.id) : null), [data]);

  const company = isNexusAdmin ? resolveActingCompany({ tabPick, own, lastPick, available }) : own;

  // Published during render, not in an effect: child effects run before this component's, and a page
  // whose query subscribes first would otherwise go out without the header - unscoped, every company
  // mixed together. The assignment is idempotent, so a re-render repeating it is harmless.
  publishActingCompanyHeader(isNexusAdmin ? company : null);

  // A switch (or the list correcting a stored pick it no longer holds) empties the cache and refetches
  // what is on screen, so no row from the previous company lingers beside the new one. The first
  // company an admin lands in is not a switch: nothing was cached for another one yet.
  const previous = useRef<string | null>(null);
  useEffect(() => {
    const before = previous.current;
    previous.current = company;
    if (!isNexusAdmin || before === null || before === company) return;
    void client.resetStore().catch(() => {
      // An in-flight query cancelled by the reset rejects here; the refetch that follows is what counts.
    });
  }, [client, company, isNexusAdmin]);

  const setCompany = useCallback(
    (next: string) => {
      if (!isNexusAdmin) return;
      rememberPick(next);
      setTabPick(next);
    },
    [isNexusAdmin],
  );

  const value = useMemo<ActingCompanyState>(
    () => ({
      company,
      companies,
      canSwitch: isNexusAdmin,
      setCompany,
      resolving: isNexusAdmin && company === null && loading,
    }),
    [company, companies, isNexusAdmin, setCompany, loading],
  );

  return <ActingCompanyContext.Provider value={value}>{children}</ActingCompanyContext.Provider>;
}

/**
 * The GP company the caller is working in (#845). Outside the provider - a test rendering one screen
 * alone - it is the user's own assignment and cannot be switched, which is exactly a scoped user.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useActingCompany(): ActingCompanyState {
  const context = useContext(ActingCompanyContext);
  const { company } = useIdentity();
  const fallback = useMemo<ActingCompanyState>(
    () => ({ company, companies: NO_COMPANIES, canSwitch: false, setCompany: noop, resolving: false }),
    [company],
  );
  return context ?? fallback;
}
