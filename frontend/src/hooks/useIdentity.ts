import { useUser } from '@clerk/clerk-react';

interface PublicMetadata {
  roles?: string[];
  // Issue #216: the GP BUYERID this account acts as (set by an Admin in User Management).
  gpBuyerId?: string | null;
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
  const gpBuyerId = metadata.gpBuyerId || null;
  return { displayName, userId, roles, hasRole, isAdmin, gpBuyerId, user };
}
