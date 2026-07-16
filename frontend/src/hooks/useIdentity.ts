import { useUser } from '@clerk/clerk-react';

interface PublicMetadata {
  roles?: string[];
  // Issue #216: the GP BUYERID this account acts as (set by an Admin in User Management).
  gpBuyerId?: string | null;
}

export function useIdentity() {
  const { user } = useUser();
  const displayName = user?.fullName || user?.primaryEmailAddress?.emailAddress || 'Unknown';
  const metadata = (user?.publicMetadata ?? {}) as PublicMetadata;
  const roles = metadata.roles ?? [];
  const hasRole = (role: string) => roles.includes(role);
  const isAdmin = hasRole('Admin/Manager');
  const gpBuyerId = metadata.gpBuyerId || null;
  return { displayName, roles, hasRole, isAdmin, gpBuyerId, user };
}
