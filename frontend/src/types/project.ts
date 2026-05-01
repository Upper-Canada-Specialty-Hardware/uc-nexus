export interface Project {
  id: string;
  projectId: string;
  description: string | null;
  client: string | null;
  jobSiteName: string | null;
  openings?: Array<{ id: string }>;
}
