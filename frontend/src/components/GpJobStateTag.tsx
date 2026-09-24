import { Alert, AlertTitle, Chip, Tooltip, Typography } from '@mui/material';
import { gpJobNotOpenReason, gpJobStateLabel, type GpJobStatus } from '../types/project';

/**
 * #730: the one surface for a GP job that is not open. GP owns the job, and GP refuses every NEXUS TO
 * GP WRITE against an inactive, closed or missing one - PO REGISTRATION, GP RECEIVE ENTRY and job
 * edits alike. The tag is what every list and picker shows; the banner is what a screen whose action
 * is refused shows in place of the action. Both render nothing for an open or never-mirrored job.
 */

const TAG_COLOR = {
  INACTIVE: 'warning',
  CLOSED: 'default',
  NOT_IN_GP: 'error',
} as const;

export function GpJobStateTag({ project }: { project: GpJobStatus | null | undefined }) {
  const label = gpJobStateLabel(project);
  if (!label) return null;
  const color = TAG_COLOR[project!.gpJobState as keyof typeof TAG_COLOR];
  return (
    <Tooltip title={gpJobNotOpenReason(project)} arrow>
      <Chip
        label={label}
        color={color}
        size="small"
        variant="outlined"
        data-testid="gp-job-state-tag"
        sx={{ height: 20, fontSize: '0.7rem', flexShrink: 0 }}
      />
    </Tooltip>
  );
}

interface GpJobNotOpenBannerProps {
  project: GpJobStatus | null | undefined;
  /** What is being refused, e.g. 'registering it in GP'. Completes "so ... is not possible". */
  action: string;
  /** Rendered inside a dialog that supplies its own spacing. */
  dense?: boolean;
}

export default function GpJobNotOpenBanner({ project, action, dense = false }: GpJobNotOpenBannerProps) {
  const label = gpJobStateLabel(project);
  if (!label) return null;
  const jobLabel = project?.projectId ? `GP job ${project.projectId}` : 'This project’s GP job';
  return (
    <Alert severity="error" sx={{ mb: dense ? 1.5 : 2.5 }} data-testid="gp-job-not-open-banner">
      <AlertTitle>{`${jobLabel}: ${label}`}</AlertTitle>
      <Typography variant="body2">{`${gpJobNotOpenReason(project)} So ${action} is not possible.`}</Typography>
    </Alert>
  );
}
