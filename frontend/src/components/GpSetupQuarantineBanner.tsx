import { Alert, AlertTitle, Box, Chip, Tooltip, Typography } from '@mui/material';
import { TriangleAlert } from 'lucide-react';
import { isGpSetupBroken, type GpSetupStatus } from '../types/project';
import { monoSx } from '../theme';

/**
 * The project quarantine surface for broken GP job setup (#425).
 *
 * The job's JC00701 cost codes point at general ledger accounts that do not exist in the GP company -
 * residue of the pre-2023 UCSH -> UBC job copy, 1504 rows across 62 production jobs. Nothing looks
 * wrong until a receipt is attempted, at which point eConnect rejects it with "Invalid Account Index"
 * and there is no way forward: the account was stamped onto the PO line at registration, so the PO is
 * permanently unreceivable and the hardware is already in the building.
 *
 * So the banner is not a warning, it is a stop. It names the cost codes because "GP setup is broken"
 * sends the user to ask somebody, and "cost code 210-200-2 points at account index 1617" is something
 * accounting can look up. It never offers a retry or a dismiss - nothing the user does in Nexus can
 * clear it.
 *
 * The server enforces the same rule (project_repository.require_gp_setup_ok), so this is the
 * explanation, not the enforcement.
 */

const MAX_LISTED_ISSUES = 6;

interface GpSetupQuarantineBannerProps {
  project: GpSetupStatus | null | undefined;
  /** What is being blocked, e.g. 'register this purchase order'. Completes "so you cannot ...". */
  action?: string;
  /** Rendered inside a dialog/drawer that supplies its own spacing. */
  dense?: boolean;
}

export default function GpSetupQuarantineBanner({
  project,
  action,
  dense = false,
}: GpSetupQuarantineBannerProps) {
  // Renders nothing for a healthy project AND for one that has never been checked. See
  // isGpSetupBroken: a relay that has not answered yet must not look like a broken job.
  if (!isGpSetupBroken(project)) return null;

  const issues = project?.gpSetupIssues ?? [];
  const shown = issues.slice(0, MAX_LISTED_ISSUES);
  const hidden = issues.length - shown.length;
  const jobLabel = project?.projectId ? `GP job ${project.projectId}` : 'This project’s GP job';

  return (
    <Alert
      severity="error"
      icon={<TriangleAlert size={20} strokeWidth={1.75} />}
      sx={{ mb: dense ? 1.5 : 2.5 }}
      data-testid="gp-setup-quarantine-banner"
    >
      <AlertTitle>{jobLabel} is not set up correctly in GP</AlertTitle>
      <Typography variant="body2">
        {issues.length > 0
          ? 'These cost codes point at general ledger accounts that do not exist in this company:'
          : 'Its cost codes point at general ledger accounts that do not exist in this company.'}
      </Typography>
      {shown.length > 0 && (
        <Box component="ul" sx={{ pl: 2.5, my: 0.75 }}>
          {shown.map((issue) => (
            <Box component="li" key={`${issue.costCode}-${issue.accountIndex}`}>
              <Typography variant="body2" component="span" sx={monoSx}>
                {issue.costCode}
              </Typography>
              <Typography variant="body2" component="span">
                {` → GL account index ${issue.accountIndex}`}
              </Typography>
            </Box>
          ))}
          {hidden > 0 && (
            <Box component="li">
              <Typography variant="body2">{`and ${hidden} more`}</Typography>
            </Box>
          )}
        </Box>
      )}
      <Typography variant="body2">
        {`A purchase order on this job would register in GP but could never be received, so ${
          action ?? 'work on this project'
        } is on hold. Accounting has to correct the job’s cost-code accounts in GP first.`}
      </Typography>
    </Alert>
  );
}

/**
 * The list/picker form of the same fact (#425): small enough to sit on a project card or a table row,
 * loud enough that nobody picks a quarantined project and only finds out at the finalize button.
 * Renders nothing unless the verdict is explicitly false, same rule as the banner.
 */
export function GpSetupBadge({ project }: { project: GpSetupStatus | null | undefined }) {
  if (!isGpSetupBroken(project)) return null;
  const issues = project?.gpSetupIssues ?? [];
  const title =
    issues.length > 0
      ? `Cost codes point at accounts this GP company does not have: ${issues
          .slice(0, 3)
          .map((i) => `${i.costCode} → ${i.accountIndex}`)
          .join(', ')}${issues.length > 3 ? `, and ${issues.length - 3} more` : ''}`
      : 'This project’s GP job setup is broken; work on it is on hold.';
  return (
    <Tooltip title={title} arrow>
      <Chip
        label="GP setup broken"
        color="error"
        size="small"
        variant="outlined"
        data-testid="gp-setup-badge"
        sx={{ height: 20, fontSize: '0.7rem' }}
      />
    </Tooltip>
  );
}
