import { useUser } from '@clerk/clerk-react';

interface PublicMetadata {
  roles?: string[];
  // Issue #216: the GP BUYERID this account acts as (set in User Management).
  gpBuyerId?: string | null;
  // #637: the GP company (TUBC, UCSH, …) this account is scoped to. A tenant IS a GP company, so
  // this decides which rows the server will return. UC NEXUS ADMIN is the only unscoped role and
  // may hold none.
  company?: string | null;
}

export function useIdentity() {
  const { user } = useUser();
  const displayName = user?.fullName || user?.primaryEmailAddress?.emailAddress || 'Unknown';
  // Stable Clerk user id (#324): the key shop-assembly assignment / My Work agree on, so a
  // display-name change never detaches in-flight work. Empty string until Clerk has loaded.
  const userId = user?.id ?? '';
  const metadata = (user?.publicMetadata ?? {}) as PublicMetadata;
  const roles = metadata.roles ?? [];
  const hasRole = (role: string) => roles.includes(role);
  // #729: the two halves the one retired all-access role used to bundle. UC NEXUS ADMIN is the only
  // role that crosses the GP COMPANY NEXUS TENANT line; TENANT OWNER holds everything inside one
  // company. Every gate in the app picks one of the three deliberately, because "unscoped" and
  // "owns this company" are different questions and the old single flag answered both at once.
  const isNexusAdmin = hasRole('UC Nexus Admin');
  const isTenantOwner = hasRole('Tenant Owner');
  const ownsTenant = isNexusAdmin || isTenantOwner;
  // The Database Access tier, deliberately checked explicitly rather than through the tenant-owner
  // shorthand. It stacks on UC NEXUS ADMIN, but db-access mints internet-reachable read-write
  // credentials, so only a real holder of "DB Admin" sees the page and its entry point.
  const isDbAdmin = hasRole('DB Admin');
  const gpBuyerId = metadata.gpBuyerId || null;
  // #637: null is a real state, not a default - a scoped user without one is shown the unassigned
  // notice rather than an empty app, because every scoped read would come back empty.
  const company = metadata.company || null;
  return {
    displayName,
    userId,
    roles,
    hasRole,
    isNexusAdmin,
    isTenantOwner,
    ownsTenant,
    isDbAdmin,
    gpBuyerId,
    company,
    user,
  };
}
