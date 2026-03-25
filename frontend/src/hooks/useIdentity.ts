import { useUser } from '@clerk/clerk-react';

interface PublicMetadata {
  roles?: string[];
}

export function useIdentity() {
  const { user } = useUser();
  const displayName = user?.fullName || user?.primaryEmailAddress?.emailAddress || 'Unknown';
  const metadata = (user?.publicMetadata ?? {}) as PublicMetadata;
  const roles = metadata.roles ?? [];
  const hasRole = (role: string) => roles.includes(role);
  const isAdmin = hasRole('Admin/Manager');
  return { displayName, roles, hasRole, isAdmin, user };
}
