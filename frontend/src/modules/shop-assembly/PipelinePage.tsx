import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Chip,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { useQuery } from '@apollo/client/react';
import type { GridColDef } from '@mui/x-data-grid';
import { GET_ASSEMBLY_PIPELINE, GET_ASSEMBLY_PIPELINE_SUMMARIES } from '../../graphql/shop-assembly';
import DataTable from '../../components/DataTable';
import Modal from '../../components/Modal';
import { leafSuffix } from '../../utils/leaf';
import { pipelineFlags, stageColor, stageLabel, stageProgress, unitProgressLabel } from './pipelineStages';

export interface PipelineSummary {
  requestId: string;
  requestNumber: string;
  projectId: string;
  projectCode: string | null;
  projectName: string | null;
  requestStatus: string;
  createdBy: string;
  createdAt: string;
  acceptedBy: string | null;
  acceptedAt: string | null;
  rejectedBy: string | null;
  rejectedAt: string | null;
  integrityNote: string | null;
  pullRequestId: string | null;
  pullRequestStatus: string | null;
  pullApprovedAt: string | null;
  pullCompletedAt: string | null;
  stagingStatus: string | null;
  cancelledPullCount: number;
  lastCancelledAt: string | null;
  lastCancelledBy: string | null;
  lastCancellationReason: string | null;
  openingCount: number;
  stagedOpeningCount: number;
  assignedOpeningCount: number;
  inProgressOpeningCount: number;
  completedOpeningCount: number;
  shippedOpeningCount: number;
  plannedUnitCount: number;
  /** Claimed out of inventory; the progress counters partition this, not plannedUnitCount. */
  allocatedUnitCount: number;
  /** Owed but never pulled - the request was sent short. */
  shortUnitCount: number;
  installedUnitCount: number;
  deficientUnitCount: number;
  replacementPendingUnitCount: number;
  awaitingReplacementOpeningCount: number;
  replacementAfterShipOpeningCount: number;
  shortOpeningCount: number;
  stage: string;
}

export interface PipelineOpeningRow {
  shopAssemblyOpeningId: string;
  openingNumber: string;
  leaf: number | null;
  building: string | null;
  floor: string | null;
  location: string | null;
  stage: string;
  pullStatus: string;
  stagedAt: string | null;
  stagedBy: string | null;
  assignedToUserId: string | null;
  assignedTo: string | null;
  assemblyStatus: string;
  completedAt: string | null;
  plannedUnitCount: number;
  allocatedUnitCount: number;
  shortUnitCount: number;
  installedUnitCount: number;
  deficientUnitCount: number;
  replacementPendingUnitCount: number;
  awaitingReplacementUnitCount: number;
  replacementArrivedAfterShip: boolean;
  openingItemId: string | null;
  openingItemState: string | null;
  assembledLocation: string | null;
}

const VIEWS = [
  { value: '', label: 'All' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Rejected' },
];

function StageChip({ stage }: { stage: string }) {
  return <Chip size='small' variant='outlined' color={stageColor(stage)} label={stageLabel(stage)} />;
}

const columns: GridColDef[] = [
  { field: 'requestNumber', headerName: 'Request', flex: 1 },
  {
    field: 'project',
    headerName: 'Project',
    flex: 1.1,
    valueGetter: (_v: unknown, row: PipelineSummary) =>
      [row.projectCode, row.projectName].filter(Boolean).join(' - ') || '-',
  },
  {
    field: 'stage',
    headerName: 'Stage',
    flex: 0.9,
    // The stage of the least-advanced opening: what the request is waiting on, not its best news.
    renderCell: (params) => <StageChip stage={params.row.stage} />,
  },
  {
    field: 'staging',
    headerName: 'Staged',
    flex: 0.8,
    // Blank rather than "0 of 0" when the request has no openings - the same rule the pull queue's
    // staging column follows, so "nothing to say" never reads as "nothing done".
    valueGetter: (_v: unknown, row: PipelineSummary) =>
      row.openingCount > 0 ? `${row.stagedOpeningCount} of ${row.openingCount}` : '',
  },
  {
    field: 'progress',
    headerName: 'Progress',
    flex: 0.9,
    valueGetter: (_v: unknown, row: PipelineSummary) => unitProgressLabel(row),
  },
  {
    field: 'assembled',
    headerName: 'Assembled',
    flex: 0.8,
    valueGetter: (_v: unknown, row: PipelineSummary) =>
      row.openingCount > 0 ? `${row.completedOpeningCount} of ${row.openingCount}` : '',
  },
  {
    field: 'shipped',
    headerName: 'Shipped',
    flex: 0.7,
    valueGetter: (_v: unknown, row: PipelineSummary) =>
      row.openingCount > 0 ? `${row.shippedOpeningCount} of ${row.openingCount}` : '',
  },
  {
    field: 'flags',
    headerName: 'Flags',
    flex: 1.2,
    sortable: false,
    // Nothing at all when nothing is wrong. A row of reassuring chips would make the one row that
    // does need attention harder to find, which is the opposite of what this column is for.
    renderCell: (params) => (
      <Stack direction='row' spacing={0.5} sx={{ flexWrap: 'wrap', alignItems: 'center' }}>
        {pipelineFlags(params.row as PipelineSummary).map((flag) => (
          <Chip key={flag.label} size='small' variant='outlined' color={flag.severity} label={flag.label} />
        ))}
      </Stack>
    ),
  },
];

function formatWhen(value: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString();
}

/**
 * Where every shop-assembly request has got to, and where each of its door leaves is (#344).
 *
 * Slices 1-5 each added a state that was legible only from the screen that wrote it: a request holds
 * a reservation, its pull is part-staged, one leaf is half-built, another is finished but owed a
 * replacement. Answering "where is opening A01 leaf 2?" meant opening four views and joining them by
 * eye. This is that join, done once.
 *
 * Nothing here is editable. It is deliberately a reading, not a console: every one of these states
 * already has a screen that owns changing it, and a second place to act on them is a second place
 * for the rules to be enforced.
 */
export default function PipelinePage() {
  const [status, setStatus] = useState('');
  // Hold the id, not the row: the detail query is the authority on this request, and pinning the
  // modal to a list snapshot is the trap #340 fixed in the assembly views.
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);

  const { data, loading } = useQuery<{ assemblyPipelineSummaries: PipelineSummary[] }>(
    GET_ASSEMBLY_PIPELINE_SUMMARIES,
    { variables: { status: status || null }, fetchPolicy: 'cache-and-network' },
  );

  const rows = useMemo(() => data?.assemblyPipelineSummaries ?? [], [data]);
  const handleRowClick = useCallback((params: { row: PipelineSummary }) => {
    setSelectedRequestId(params.row.requestId);
  }, []);

  return (
    <Box>
      <Typography variant='h5' gutterBottom>
        Pipeline
      </Typography>
      <Typography variant='body2' color='text.secondary' sx={{ mb: 2 }}>
        Every shop-assembly request and how far it has got: requested, accepted, staged, assigned,
        built, shipped. A request reads by its least-advanced opening, so the stage shown is what it
        is waiting on. Open one to see each door leaf.
      </Typography>

      <ToggleButtonGroup
        size='small'
        exclusive
        value={status}
        onChange={(_e, next) => setStatus(next ?? '')}
        sx={{ mb: 2 }}
      >
        {VIEWS.map((view) => (
          <ToggleButton key={view.value || 'all'} value={view.value}>
            {view.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>

      <DataTable
        rows={rows}
        columns={columns}
        loading={loading}
        onRowClick={handleRowClick}
        getRowId={(row: PipelineSummary) => row.requestId}
        height={520}
      />

      {selectedRequestId && (
        <PipelineDetailModal requestId={selectedRequestId} onClose={() => setSelectedRequestId(null)} />
      )}
    </Box>
  );
}

function PipelineDetailModal({ requestId, onClose }: { requestId: string; onClose: () => void }) {
  const { data, loading, error } = useQuery<{
    assemblyPipeline: { summary: PipelineSummary; openings: PipelineOpeningRow[] };
  }>(GET_ASSEMBLY_PIPELINE, { variables: { requestId }, fetchPolicy: 'cache-and-network' });

  const summary = data?.assemblyPipeline?.summary;
  const openings = data?.assemblyPipeline?.openings ?? [];
  const progress = summary ? stageProgress(summary.stage) : null;

  return (
    <Modal open title={summary ? `Pipeline - ${summary.requestNumber}` : 'Pipeline'} onClose={onClose}>
      {loading && !summary && !error && <LinearProgress />}
      {/* Without this the resolver failing left an empty dialog: no spinner (loading is false), no
          body (summary is undefined), and nothing saying why. A request deleted under the list, or a
          pipeline query that timed out, both land here. */}
      {error && !summary && (
        <Alert severity='error'>
          Could not load this request's pipeline. {error.message}
        </Alert>
      )}
      {summary && (
        <Box>
          {/* The request-level doubt (#342) comes first, above everything it casts doubt on. */}
          {summary.integrityNote && (
            <Alert severity='warning' sx={{ mb: 2 }}>
              {summary.integrityNote}
            </Alert>
          )}
          {summary.cancelledPullCount > 0 && (
            <Alert severity='warning' sx={{ mb: 2 }}>
              {summary.cancelledPullCount === 1 ? 'A pull for this request was' : 'Pulls for this request were'}{' '}
              cancelled and the hardware returned to inventory
              {summary.lastCancelledBy ? ` by ${summary.lastCancelledBy}` : ''}
              {summary.lastCancellationReason ? `: ${summary.lastCancellationReason}` : '.'}
            </Alert>
          )}
          {summary.replacementAfterShipOpeningCount > 0 && (
            <Alert severity='error' sx={{ mb: 2 }}>
              Replacement hardware arrived for {summary.replacementAfterShipOpeningCount} leaf/leaves that
              had already shipped. It cannot be fitted here and needs a reallocation or a site shipment.
            </Alert>
          )}

          <Stack direction='row' spacing={1} sx={{ mb: 1, flexWrap: 'wrap', alignItems: 'center' }}>
            <StageChip stage={summary.stage} />
            <Chip
              size='small'
              variant='outlined'
              label={
                summary.openingCount > 0
                  ? `${summary.stagedOpeningCount} of ${summary.openingCount} staged`
                  : 'No openings'
              }
            />
            <Chip size='small' variant='outlined' label={unitProgressLabel(summary)} />
            {summary.awaitingReplacementOpeningCount > 0 && (
              <Chip
                size='small'
                variant='outlined'
                color='warning'
                label={`${summary.awaitingReplacementOpeningCount} awaiting replacement`}
              />
            )}
            {summary.shortUnitCount > 0 && (
              <Chip
                size='small'
                variant='outlined'
                color='warning'
                label={`${summary.shortUnitCount} unit(s) never pulled across ${summary.shortOpeningCount} leaf/leaves`}
              />
            )}
          </Stack>
          {progress !== null && (
            <LinearProgress variant='determinate' value={progress * 100} sx={{ mb: 2 }} />
          )}

          <Typography variant='body2' color='text.secondary' sx={{ mb: 2 }}>
            Requested by {summary.createdBy} on {formatWhen(summary.createdAt)}
            {summary.acceptedBy ? `, accepted by ${summary.acceptedBy} on ${formatWhen(summary.acceptedAt)}` : ''}
            {summary.rejectedBy ? `, rejected by ${summary.rejectedBy} on ${formatWhen(summary.rejectedAt)}` : ''}.
          </Typography>

          {openings.length === 0 ? (
            <Typography variant='body2' color='text.secondary'>
              This request has no openings on it.
            </Typography>
          ) : (
            <Box sx={{ overflowX: 'auto' }}>
              <Table size='small'>
                <TableHead>
                  <TableRow>
                    <TableCell>Opening</TableCell>
                    <TableCell>Stage</TableCell>
                    <TableCell>Staged</TableCell>
                    <TableCell>Assigned to</TableCell>
                    <TableCell>Units</TableCell>
                    <TableCell>Location</TableCell>
                    <TableCell>Owed</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {openings.map((row) => (
                    <TableRow key={row.shopAssemblyOpeningId}>
                      <TableCell>
                        {row.openingNumber}
                        {leafSuffix(row.leaf)}
                        {(row.building || row.floor) && (
                          <Typography variant='caption' color='text.secondary' display='block'>
                            {[row.building, row.floor].filter(Boolean).join(' / ')}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <StageChip stage={row.stage} />
                      </TableCell>
                      <TableCell>
                        {row.stagedAt ? (
                          <>
                            {formatWhen(row.stagedAt)}
                            {row.stagedBy && (
                              <Typography variant='caption' color='text.secondary' display='block'>
                                by {row.stagedBy}
                              </Typography>
                            )}
                          </>
                        ) : (
                          '-'
                        )}
                      </TableCell>
                      <TableCell>{row.assignedTo ?? '-'}</TableCell>
                      <TableCell>{unitProgressLabel(row)}</TableCell>
                      <TableCell>{row.assembledLocation ?? '-'}</TableCell>
                      <TableCell>
                        <Stack direction='row' spacing={0.5} sx={{ flexWrap: 'wrap' }}>
                          {row.awaitingReplacementUnitCount > 0 && (
                            <Chip
                              size='small'
                              variant='outlined'
                              color={row.replacementArrivedAfterShip ? 'error' : 'warning'}
                              label={
                                row.replacementArrivedAfterShip
                                  ? `${row.awaitingReplacementUnitCount} arrived after shipping`
                                  : `${row.awaitingReplacementUnitCount} awaiting replacement`
                              }
                            />
                          )}
                          {row.shortUnitCount > 0 && (
                            <Chip
                              size='small'
                              variant='outlined'
                              color='warning'
                              label={`${row.shortUnitCount} never pulled`}
                            />
                          )}
                          {row.awaitingReplacementUnitCount === 0 && row.shortUnitCount === 0 && '-'}
                        </Stack>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          )}
        </Box>
      )}
    </Modal>
  );
}
