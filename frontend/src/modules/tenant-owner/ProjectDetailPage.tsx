import { useCallback, useMemo, useState, type ReactNode } from 'react';
import {
  Alert,
  Box,
  Button,
  ButtonBase,
  Chip,
  Divider,
  Link,
  Paper,
  Skeleton,
  Stack,
  Typography,
} from '@mui/material';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { Archive, ArchiveRestore, Boxes, DoorOpen, FileText, Pencil, Tags, Truck } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import { GET_ADMIN_PROJECT_DETAIL, GET_ADMIN_PROJECTS, SET_PROJECT_ARCHIVED } from '../../graphql/admin';
import { StatCard, StatCardSkeleton } from '../../components/StatCard';
import ConfirmDialog from '../../components/ConfirmDialog';
import PageHeader from '../../components/PageHeader';
import { GpSetupBadge } from '../../components/GpSetupQuarantineBanner';
import { GpJobStateTag } from '../../components/GpJobStateTag';
import { isGpSetupBroken } from '../../types/project';
import { isGpEmptyDate } from '../po/poOrderDate';
import { parseServerDay } from '../../utils/serverDate';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import { formatPoStatus, poStatusChipColor, PO_STATUS_VALUES } from '../po/poStatus';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import ProjectEditDialog, { type ProjectFormValue } from './ProjectEditDialog';

const ICON = { size: 18, strokeWidth: 1.75 } as const;

interface PoStatusCount {
  status: string;
  count: number;
}

interface AdminProjectDetail {
  project: ProjectFormValue;
  poCountsByStatus: PoStatusCount[];
  inventoryOnHand: number;
  openShippingRequestCount: number;
}

const ARCHIVE_WARNING =
  'An archived project disappears from every project picker in the app - imports, POs, receiving and ' +
  'shipping. Nothing it already holds is deleted, and archiving can be undone from this page.';

const UNARCHIVE_WARNING = 'This puts the project back in every project picker in the app.';

const ABSENT = '—';

const CURRENCY = new Intl.NumberFormat('en-CA', {
  style: 'currency',
  currency: 'CAD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatMoney(value: number | null | undefined): string {
  return value == null ? ABSENT : CURRENCY.format(value);
}

/**
 * #730: a GP job date. A dash when there is none - null, or GP's own 1900-01-01 stand-in for a date
 * nobody filled in, which on a job's optional dates is the ordinary case rather than a gap worth words.
 */
function formatGpDay(value: string | null | undefined): string {
  if (!value || isGpEmptyDate(value)) return ABSENT;
  return parseServerDay(value.slice(0, 10)).toLocaleDateString();
}

function employeeText(id: string | null | undefined, name: string | null | undefined): string | null {
  if (!id) return null;
  return name ? `${id} - ${name}` : id;
}

/** Label-left, value-right rows: the one shape every panel on this page uses. */
function InfoRows({ rows, tabular = false }: { rows: Array<[string, string | null]>; tabular?: boolean }) {
  return (
    <Stack spacing={1}>
      {rows.map(([label, value]) => (
        <Box key={label} sx={{ display: 'flex', gap: 1, justifyContent: 'space-between', minWidth: 0 }}>
          <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0 }}>
            {label}
          </Typography>
          <Typography
            variant="body2"
            noWrap
            title={value || undefined}
            sx={{ minWidth: 0, textAlign: 'right', ...(tabular ? tabularSx : {}) }}
          >
            {value || ABSENT}
          </Typography>
        </Box>
      ))}
    </Stack>
  );
}

/** One stat tile, optionally a link into the module the number is about. */
function StatTile({
  to,
  ariaLabel,
  children,
}: {
  to?: string;
  ariaLabel?: string;
  children: ReactNode;
}) {
  if (!to) return <Box sx={{ flex: '1 1 0', minWidth: 150, display: 'flex' }}>{children}</Box>;
  return (
    <ButtonBase
      component={RouterLink}
      to={to}
      aria-label={ariaLabel}
      sx={{
        flex: '1 1 0',
        minWidth: 150,
        display: 'flex',
        alignItems: 'stretch',
        borderRadius: 1,
        textAlign: 'left',
        // ButtonBase zeroes the outline, so the ring the rest of the app gets is restated here.
        '&.Mui-focusVisible': {
          outline: '2px solid',
          outlineColor: 'secondary.main',
          outlineOffset: 2,
        },
        '& > *': { width: '100%' },
      }}
    >
      {children}
    </ButtonBase>
  );
}

export default function ProjectDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const { ownsTenant } = useIdentity();
  const { showToast } = useToast();
  const [editOpen, setEditOpen] = useState(false);
  const [archiveConfirmOpen, setArchiveConfirmOpen] = useState(false);

  const { data, loading, error } = useQuery<{ adminProjectDetail: AdminProjectDetail | null }>(
    GET_ADMIN_PROJECT_DETAIL,
    { variables: { id }, skip: !ownsTenant || !id, fetchPolicy: 'cache-and-network' },
  );

  const detail = data?.adminProjectDetail ?? null;
  const project = detail?.project ?? null;

  const [setArchived, { loading: archiving }] = useMutation<{ setProjectArchived: { archived: boolean } }>(SET_PROJECT_ARCHIVED, {
    // The grid reads its own list, and archiving changes which rows it shows.
    refetchQueries: [{ query: GET_ADMIN_PROJECTS }],
    onCompleted: (result) => {
      setArchiveConfirmOpen(false);
      // Read the outcome off the reply, not off `project`: the normalized cache has already applied
      // the mutation by the time this runs, so `project.archived` is the NEW state and would name
      // the opposite action.
      showToast(result.setProjectArchived.archived ? 'Project archived' : 'Project restored', 'success');
    },
    onError: (err) => {
      setArchiveConfirmOpen(false);
      showToast(err.message, 'error');
    },
  });

  const handleToggleArchive = useCallback(() => {
    if (!project) return;
    setArchived({ variables: { id: project.id, archived: !project.archived } });
  }, [project, setArchived]);

  // Every status the PO lifecycle has, in lifecycle order, with the ones this project has no POs in
  // shown as zero rather than dropped - the absence of a Draft is itself worth seeing.
  const poCounts = useMemo(() => {
    const byStatus = new Map((detail?.poCountsByStatus ?? []).map((c) => [c.status, c.count]));
    return PO_STATUS_VALUES.map((status) => ({ status, count: byStatus.get(status) ?? 0 }));
  }, [detail?.poCountsByStatus]);
  const poTotal = poCounts.reduce((sum, c) => sum + c.count, 0);
  const inventoryOnHand = detail?.inventoryOnHand ?? 0;
  const openRequests = detail?.openShippingRequestCount ?? 0;

  if (!ownsTenant) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        You do not have permission to manage projects. The Tenant Owner role is required.
      </Alert>
    );
  }

  if (loading && !detail) {
    return (
      <Box>
        <Skeleton variant="text" width={280} height={40} sx={{ mb: 2 }} />
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <Box key={i} sx={{ flex: '1 1 0', minWidth: 150, display: 'flex' }}>
              <StatCardSkeleton />
            </Box>
          ))}
        </Box>
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Could not load this project: {error.message}</Alert>;
  }

  if (!project) {
    return (
      <Alert
        severity="info"
        action={
          <Button component={RouterLink} to="/app/tenant-owner/projects" size="small" color="inherit">
            All projects
          </Button>
        }
      >
        This project could not be found. It may have been removed.
      </Alert>
    );
  }

  return (
    <Box>
      <FadeIn>
        <PageHeader
          parent={{ label: 'Projects', to: '/app/tenant-owner/projects' }}
          title={
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography variant="h5" sx={{ ...monoSx, fontWeight: 700 }}>
                {project.projectId}
              </Typography>
              <Chip label={project.company} size="small" variant="outlined" sx={monoSx} />
              {project.offSiteStorageAgreement && <Chip label="OSSA" size="small" variant="outlined" />}
              {project.archived && <Chip label="Archived" size="small" color="warning" />}
              {isGpSetupBroken(project) && <GpSetupBadge project={project} />}
              <GpJobStateTag project={project} />
            </Stack>
          }
          description={
            <>
              {project.description || 'No description'}
              {project.client ? ` · ${project.client}` : ''}
            </>
          }
          actions={
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              {/* #735: correct a product's Shop / Site / By Others after import. */}
              <Button
                component={RouterLink}
                to={`/app/tenant-owner/projects/${project.id}/classifications`}
                variant="outlined"
                size="small"
                startIcon={<Tags {...ICON} />}
              >
                Hardware classifications
              </Button>
              <Button
                variant="outlined"
                size="small"
                startIcon={<Pencil {...ICON} />}
                onClick={() => setEditOpen(true)}
              >
                Edit details
              </Button>
              <Button
                variant="outlined"
                size="small"
                color={project.archived ? 'primary' : 'warning'}
                startIcon={project.archived ? <ArchiveRestore {...ICON} /> : <Archive {...ICON} />}
                onClick={() => setArchiveConfirmOpen(true)}
                disabled={archiving}
              >
                {project.archived ? 'Restore' : 'Archive'}
              </Button>
            </Stack>
          }
        />
      </FadeIn>

      {/* What the project currently holds. Each tile that has a module behind it is a door into it.
          A zero reads dimmed - it is the absence of work, not an achievement. */}
      <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 2 }}>
        <StatTile>
          <StatCard
            icon={<DoorOpen size={20} strokeWidth={1.75} />}
            label="Openings"
            value={project.openingCount}
            color={project.openingCount === 0 ? 'text.secondary' : undefined}
          />
        </StatTile>
        <StatTile to="/app/po" ariaLabel="Open Purchase Orders">
          <StatCard
            icon={<FileText size={20} strokeWidth={1.75} />}
            label="Purchase orders"
            value={poTotal}
            color={poTotal === 0 ? 'text.secondary' : undefined}
          />
        </StatTile>
        <StatTile to="/app/warehouse" ariaLabel="Open the Warehouse module">
          <StatCard
            icon={<Boxes size={20} strokeWidth={1.75} />}
            label="Inventory on hand"
            value={inventoryOnHand}
            color={inventoryOnHand === 0 ? 'text.secondary' : undefined}
          />
        </StatTile>
        <StatTile to="/app/shipping" ariaLabel="Open Shipping">
          <StatCard
            icon={<Truck size={20} strokeWidth={1.75} />}
            label="Open requests"
            value={openRequests}
            // An open request is someone waiting on this project, so a non-zero is real state.
            color={openRequests > 0 ? 'warning.main' : 'text.secondary'}
          />
        </StatTile>
      </Box>

      <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', alignItems: 'stretch' }}>
        {/* The PO breakdown gets the wide half - it is the one region with real content. */}
        <Paper variant="outlined" sx={{ flex: '2 1 340px', minWidth: 0, p: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="baseline" sx={{ mb: 1.5 }}>
            <Typography component="h2" sx={microLabelSx}>
              Purchase orders by status
            </Typography>
            <Link component={RouterLink} to="/app/po" variant="body2" underline="hover">
              Open register
            </Link>
          </Stack>
          {poTotal === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No purchase orders have been raised for this project.
            </Typography>
          ) : (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {poCounts.map(({ status, count }) => (
                <Stack
                  key={status}
                  direction="row"
                  spacing={0.75}
                  alignItems="center"
                  sx={{ opacity: count === 0 ? 0.45 : 1 }}
                >
                  <Chip label={formatPoStatus(status)} size="small" color={poStatusChipColor(status)} />
                  <Typography component="span" sx={{ ...tabularSx, fontWeight: 700 }}>
                    {count}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          )}
        </Paper>

        <Paper variant="outlined" sx={{ flex: '1 1 260px', minWidth: 0, p: 2 }}>
          <Typography component="h2" sx={{ ...microLabelSx, mb: 1.5 }}>
            Job
          </Typography>
          <InfoRows
            rows={[
              ['Job site', project.jobSiteName],
              ['General contractor', project.contractor],
              ['Project manager', project.projectManager],
              ['Site', [project.city, project.state].filter(Boolean).join(', ')],
            ]}
          />
          <Divider sx={{ my: 1.5 }} />
          <Typography variant="caption" color="text.secondary">
            {project.archived
              ? 'Archived - off every project picker until it is restored.'
              : 'Archive this project once the job is finished to take it off every project picker.'}
          </Typography>
        </Paper>
      </Box>

      {/* #730: the GP job as GP holds it. Three columns side by side on a wide screen - setup, dates,
          dollars - so the whole job reads in one band rather than a long list. */}
      <Paper variant="outlined" sx={{ p: 2, mt: 1.5 }} data-testid="gp-job-panel">
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
          <Typography component="h2" sx={microLabelSx}>
            GP job
          </Typography>
          <GpJobStateTag project={project} />
        </Stack>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'repeat(3, minmax(0, 1fr))' },
            columnGap: 3,
            rowGap: 2,
          }}
        >
          <InfoRows
            rows={[
              [
                'Customer',
                project.customerNumber
                  ? project.client
                    ? `${project.customerNumber} - ${project.client}`
                    : project.customerNumber
                  : project.client,
              ],
              [
                'Site address',
                [project.address, project.address2, project.city, project.state, project.zip, project.country]
                  .filter(Boolean)
                  .join(', '),
              ],
              ['Estimator', employeeText(project.estimatorId, project.estimatorName)],
              ['WS Manager', employeeText(project.wsManagerId, project.wsManagerName)],
              ['Division', project.division ?? null],
              ['Tax schedule', project.taxScheduleId ?? null],
              ['Use tax schedule', project.useTaxScheduleId ?? null],
            ]}
          />
          <InfoRows
            tabular
            rows={[
              ['Created', formatGpDay(project.gpCreatedDate)],
              ['Scheduled start', formatGpDay(project.scheduleStartDate)],
              ['Scheduled completion', formatGpDay(project.scheduledCompletionDate)],
              ['Bid due', formatGpDay(project.bidDueDate)],
              ...(project.gpJobState === 'CLOSED' || project.gpClosedDate
                ? ([['Closed', formatGpDay(project.gpClosedDate)]] as Array<[string, string]>)
                : []),
            ]}
          />
          <InfoRows
            tabular
            rows={[
              ['Original contract', formatMoney(project.origContractAmount)],
              ['Contract to date', formatMoney(project.contractToDate)],
              ['Total actual cost', formatMoney(project.totalActualCost)],
              ['Billed gross', formatMoney(project.billedAmountTtd)],
              ['Retention held', formatMoney(project.retentionAmountTtd)],
              ['Net billed', formatMoney(project.netBilledTtd)],
            ]}
          />
        </Box>
      </Paper>

      <ProjectEditDialog open={editOpen} project={project} onClose={() => setEditOpen(false)} />

      <ConfirmDialog
        open={archiveConfirmOpen}
        title={project.archived ? `Restore ${project.projectId}?` : `Archive ${project.projectId}?`}
        message={project.archived ? UNARCHIVE_WARNING : ARCHIVE_WARNING}
        confirmLabel={archiving ? 'Saving…' : project.archived ? 'Restore project' : 'Archive project'}
        confirmColor={project.archived ? 'primary' : 'warning'}
        onConfirm={handleToggleArchive}
        onCancel={() => setArchiveConfirmOpen(false)}
      />
    </Box>
  );
}
