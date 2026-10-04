import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECTS } from '../graphql/shared';
import type { Project } from '../types/project';

/**
 * A page's picked project, only while the acting company still offers it (#1467, as #1450 did for the
 * reports). A UC NEXUS ADMIN's company switch resets the store and reloads the company-scoped project
 * list; a pick from the previous company drops out instead of being queried under the new one, where
 * the server refuses it and the page would show that error beside a project the company doesn't have.
 */
export function useScopedProject<T extends { id: string }>(picked: T | null): T | null {
  const { data } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  return useMemo(
    () => (picked && data?.projects?.some((p) => p.id === picked.id) ? picked : null),
    [picked, data],
  );
}
