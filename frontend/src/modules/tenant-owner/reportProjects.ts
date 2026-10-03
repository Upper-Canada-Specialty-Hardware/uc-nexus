// The project list behind the tenant-owner report pickers (#1200): every project of the company,
// archived ones included, live jobs first and archived ones after them, tagged in the label.

export interface ReportProject {
  id: string;
  projectId: string;
  description: string | null;
  archived: boolean;
  openingCount: number;
}

export function reportProjectLabel(p: ReportProject): string {
  const name = p.description || p.projectId;
  return p.archived ? `${name} (archived)` : name;
}

export function liveFirst(projects: readonly ReportProject[]): ReportProject[] {
  return [...projects].sort((a, b) => Number(a.archived) - Number(b.archived));
}
