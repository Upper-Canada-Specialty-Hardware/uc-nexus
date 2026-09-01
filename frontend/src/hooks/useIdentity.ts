import { useUser } from '@clerk/clerk-react';

interface PublicMetadata {
  roles?: string[];
  // Issue #216: the GP BUYERID this account acts as (set by an Admin in User Management).
  gpBuyerId?: string | null;
  // #637: the GP company (TUBC, UCSH, …) this account is scoped to. A tenant IS a GP company, so
  // this decides which rows the server will return. Admin/Manager is unscoped and may hold none.
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
  const isAdmin = hasRole('Admin/Manager');
  // The Database Access tier, deliberately checked explicitly rather than through `isAdmin`. The app
  // treats Admin/Manager as all-access (`isAdmin || ...` in the nav and launcher), but db-access mints
  // internet-reachable read-write credentials, so it must NOT ride that short-circuit - only a real
  // holder of "DB Admin" sees the page and its entry point.
  const isDbAdmin = hasRole('DB Admin');
  const gpBuyerId = metadata.gpBuyerId || null;
  // #637: null is a real state, not a default - a non-admin without one is shown the unassigned
  // notice rather than an empty app, because every scoped read would come back empty.
  const company = metadata.company || null;
  return { displayName, userId, roles, hasRole, isAdmin, isDbAdmin, gpBuyerId, company, user };
}
