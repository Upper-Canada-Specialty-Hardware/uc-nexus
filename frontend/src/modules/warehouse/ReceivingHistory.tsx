import { useState, useMemo, useCallback } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  CircularProgress,
  IconButton,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { ChevronRight } from 'lucide-react';
import { userMessage } from '../../graphql/userMessage';
import RefreshFailedNote from '../../components/RefreshFailedNote';
import { motion } from 'motion/react';
import { useQuery } from '@apollo/client/react';
import { formatPoStatus, poStatusChipColor } from '../po/poStatus';
import { GET_PO_RECEIVING_DETAILS, GET_RECEIVING_HISTORY_POS } from '../../graphql/warehouse';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { noProjectPoLabel, type PoolKind } from '../../types/poolKind';
import FitTable, { type FitTableColumn } from '../../components/FitTable';
import { FIT_CELL_WRAP_SX } from '../../components/fitColumns';
import { springs } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';
import { useOnCompanySwitch } from '../../hooks/useDropProjectOnCompanySwitch';

// UI law 1 (#1231): a short value hugs its column, and the one text column takes the slack. A long
// product code wraps inside its cell rather than pushing the table wider.
const HUG_SX = { width: '1%', whiteSpace: 'nowrap' as const };
const SLACK_SX = { overflowWrap: 'anywhere' as const };

const ICON = { size: 18, strokeWidth: 1.75 } as const;

// Expander + PO + vendor + project + status + received-of-ordered + receives + last received.
const HISTORY_COLUMN_COUNT = 8;

// #909: the history table fits its width and never scrolls sideways; columns are resizable and
// remembered per person. Minimums hold a PO number, the widest status chip, "received of ordered"
// and a local date and time whole; vendor and project take the slack and ellipsize with the full
// value on hover. The expander is fixed, and the expanded receives row spans the table.
const HISTORY_COLUMNS: FitTableColumn[] = [
  { id: 'expand', label: 'Expand', min: 48, fixed: 48, header: null, flush: true },
  { id: 'poNumber', label: 'PO Number', min: 104, weight: 0.8 },
  { id: 'vendor', label: 'Vendor', min: 120, weight: 2 },
  { id: 'project', label: 'Project', min: 120, weight: 1.6 },
  { id: 'status', label: 'Status', min: 120, weight: 0.8 },
  { id: 'received', label: 'Received', min: 100, weight: 0.6, align: 'right' },
  { id: 'receives', label: 'Receives', min: 84, weight: 0.4, align: 'right' },
  { id: 'lastReceived', label: 'Last Received', min: 164, weight: 0.9 },
];

// How many POs the table paints before the "show more" tail, the same page size ShipmentsList uses.
// This view is the one warehouse surface that keeps CLOSED POs, so it is also the one that grows
// without bound - a year of receiving is thousands of rows, and none of them past the first screen
// is what the user came for.
const PAGE = 25;

// The page's placeholder for "no value", the same escape ReceivingPage writes it as.
const DASH = '\u2014';

// ---- Types ----

export interface ReceivingHistoryPO {
  id: string;
  poNumber: string | null;
  // Nullable: a mirrored GP-owned PO was never raised through Nexus, so it has a poNumber but no
  // request number. The row falls back to poNumber for its label.
  requestNumber: string | null;
  status: string;
  vendorName: string | null;
  projectId: string | null;
  projectNumber: string | null;
  projectDescription: string | null;
  poolKind: PoolKind;
  orderedTotal: number;
  receivedTotal: number;
  receiveCount: number;
  lastReceivedAt: string | null;
}

interface ReceiveRecordLineItem {
  id: string;
  poLineItemId: string;
  hardwareCategory: string;
  productCode: string;
  quantityReceived: number;
}

interface ReceiveRecord {
  id: string;
  receivedAt: string;
  receivedBy: string;
  receiptNumber: string | null;
  batchNumber: string | null;
  // #632: the counter's remark, carried off the approved draft.
  notes: string | null;
  lineItems: ReceiveRecordLineItem[];
}

interface ProjectOption {
  id: string;
  projectId: string;
  description: string | null;
}

interface ReceivingHistoryProps {
  projects: ProjectOption[];
}

// ---- Helpers ----

function formatDateTime(value: string | null): string {
  if (!value) return DASH;
  const d = parseServerDate(value);
  return isNaN(d.getTime()) ? DASH : d.toLocaleString();
}

// ---- One PO's receives, fetched only once its row is open ----

/**
 * The expanded panel. Mounted by the row's `Collapse` with `unmountOnExit`, so the query does not
 * run until somebody actually opens the PO - the list itself is deliberately scalars-only, and
 * eagerly fetching every PO's receives would undo that. Apollo's cache answers a re-expand, so
 * opening the same row twice is one round trip.
 */
function ReceivesPanel({ poId }: { poId: string }) {
  const { data, loading, error } = useQuery<{
    poReceivingDetails: { id: string; receiveRecords: ReceiveRecord[] };
  }>(GET_PO_RECEIVING_DETAILS, { variables: { poId } });

  // Only while there is nothing to show, the same guard the list above uses. The app's default is
  // cache-and-network, so `loading` is true again on every re-expand while the cached receives are
  // already rendered - spinning over them would make re-opening a row flash.
  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
        <CircularProgress size={22} />
      </Box>
    );
  }
  // #1584: only when nothing loaded; a failed re-read keeps the receives on screen with a note.
  if (error && !data) {
    return <Alert severity="error">Error loading receives: {userMessage(error, { reading: true })}</Alert>;
  }

  const receives = data?.poReceivingDetails?.receiveRecords ?? [];
  if (receives.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        Nothing has been received against this PO yet.
      </Typography>
    );
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {error && <RefreshFailedNote what="the receives" error={error} sx={{ mb: 0 }} />}
      {receives.map((receive) => (
        <Box key={receive.id}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'baseline',
              flexWrap: 'wrap',
              gap: 1.5,
              mb: 0.75,
            }}
          >
            {/* The GP receipt number leads (#447): it is what the receive is called in GP, and the
                whole reason somebody opens this row. */}
            {receive.receiptNumber ? (
              <Typography component="span" sx={{ ...monoSx, fontWeight: 700 }}>
                {receive.receiptNumber}
              </Typography>
            ) : (
              <Typography component="span" variant="body2" color="text.secondary">
                No GP receipt number
              </Typography>
            )}
            {receive.batchNumber && (
              <Typography component="span" variant="body2" color="text.secondary" sx={monoSx}>
                {receive.batchNumber}
              </Typography>
            )}
            <Typography component="span" variant="body2" color="text.secondary" sx={tabularSx}>
              {formatDateTime(receive.receivedAt)}
            </Typography>
            <Typography component="span" variant="body2" color="text.secondary">
              by {receive.receivedBy}
            </Typography>
          </Box>
          {/* #632: what the counter wanted remembered about this delivery. */}
          {receive.notes && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75, whiteSpace: 'pre-wrap' }}>
              Notes: {receive.notes}
            </Typography>
          )}
          <Table size="small" sx={{ bgcolor: 'background.paper' }}>
            <TableHead>
              <TableRow>
                <TableCell sx={HUG_SX}>Item Number</TableCell>
                <TableCell>Description</TableCell>
                <TableCell align="right" sx={HUG_SX}>
                  Quantity Received
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {receive.lineItems.map((li) => (
                <TableRow key={li.id}>
                  <TableCell sx={HUG_SX}>{li.hardwareCategory}</TableCell>
                  <TableCell sx={{ ...monoSx, ...SLACK_SX }}>{li.productCode}</TableCell>
                  <TableCell align="right" sx={{ ...HUG_SX, ...tabularSx }}>
                    {li.quantityReceived}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      ))}
    </Box>
  );
}

// ---- One PO row ----

interface HistoryRowProps {
  po: ReceivingHistoryPO;
  projectName: string;
  expanded: boolean;
  onToggle: () => void;
}

function HistoryRow({ po, projectName, expanded, onToggle }: HistoryRowProps) {
  const hugSx = HUG_SX;
  // A mirrored PO has a poNumber and a null requestNumber; a Nexus draft has the reverse until it is
  // registered. Prefer the PO number, fall back to the request number, and dash when neither exists.
  const label = po.poNumber ?? po.requestNumber ?? DASH;
  return (
    <>
      <TableRow hover sx={{ cursor: 'pointer', '& > *': { borderBottom: 'unset' } }} onClick={onToggle}>
        <TableCell sx={{ px: 0.5 }}>
          <IconButton
            size="small"
            aria-label={expanded ? `Collapse receives for ${label}` : `Expand receives for ${label}`}
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
          >
            <motion.span
              animate={{ rotate: expanded ? 90 : 0 }}
              transition={springs.fast}
              style={{ display: 'inline-flex' }}
            >
              <ChevronRight {...ICON} />
            </motion.span>
          </IconButton>
        </TableCell>
        <TableCell sx={{ ...hugSx, ...monoSx, fontWeight: 600 }}>{label}</TableCell>
        <TableCell title={po.vendorName || undefined}>{po.vendorName || DASH}</TableCell>
        <TableCell title={projectName}>{projectName}</TableCell>
        <TableCell sx={hugSx}>
          <Chip label={formatPoStatus(po.status)} color={poStatusChipColor(po.status)} size="small" />
        </TableCell>
        {/* Received of ordered in one cell: the bare received figure does not say whether a PO is
            finished, and "6 of 10" and "6 of 6" are different answers to the same question. */}
        <TableCell align="right" sx={{ ...hugSx, ...tabularSx }}>
          {po.receivedTotal} of {po.orderedTotal}
        </TableCell>
        <TableCell align="right" sx={{ ...hugSx, ...tabularSx }}>
          {po.receiveCount}
        </TableCell>
        <TableCell sx={{ ...hugSx, ...tabularSx }}>{formatDateTime(po.lastReceivedAt)}</TableCell>
      </TableRow>
      <TableRow>
        <TableCell
          sx={{ ...FIT_CELL_WRAP_SX, p: 0, borderBottom: expanded ? undefined : 'none' }}
          colSpan={HISTORY_COLUMN_COUNT}
        >
          <Collapse in={expanded} unmountOnExit>
            <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
              <Typography component="h3" sx={{ ...microLabelSx, mb: 1 }}>
                Receives
              </Typography>
              <ReceivesPanel poId={po.id} />
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
}

// ---- Component ----

/**
 * The Receiving page's History view (#447): every PO that reached GP, with what has landed against
 * it, expandable to the individual receives and their GP receipt numbers.
 *
 * The counterpart to the Receive view, which only lists what is still owed and therefore drops a PO
 * the moment it is complete. Reconciling a delivery against GP - "which receipt was this, and who
 * booked it" - needs the finished ones, so this is the one surface where CLOSED POs are in scope.
 */
export default function ReceivingHistory({ projects }: ReceivingHistoryProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  // #1537: the picked project belongs to the company it was picked in; kept across a switch, the list read
  // under the new company comes back empty, as if it had none.
  useOnCompanySwitch(() => setProjectFilter(''));
  const [shown, setShown] = useState(PAGE);

  // cache-and-network, because this view is unmounted while the user is receiving. A receive that
  // just posted has to show up the moment they switch over here, and RECEIVE_REFETCH_QUERIES does
  // not name this query - it cannot usefully, since nothing is mounted to refetch. Revalidating on
  // mount answers it without leaving the list blank while it happens.
  const { data, loading, error } = useQuery<{ receivingHistoryPos: ReceivingHistoryPO[] }>(
    GET_RECEIVING_HISTORY_POS,
    { variables: { projectId: projectFilter || null }, fetchPolicy: 'cache-and-network' },
  );

  const rows = useMemo(() => {
    const all = data?.receivingHistoryPos ?? [];
    const needle = search.trim().toLowerCase();
    if (!needle) return all;
    // PO number and vendor, because those are the two things written on a packing slip. The request
    // number is searched too so a PO that never got a GP number is still findable by what the row
    // actually displays.
    return all.filter((po) =>
      [po.poNumber, po.requestNumber, po.vendorName].some((v) => v?.toLowerCase().includes(needle)),
    );
  }, [data, search]);

  // Paged after the filters, not before: a search that matches one PO on page nine has to bring it
  // onto the first page, which it only does if the slice is taken from what survived the filter.
  const visible = useMemo(() => rows.slice(0, shown), [rows, shown]);

  const toggle = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <Box>
      <Typography
        component="div"
        sx={{
          ...microLabelSx,
          pb: 0.75,
          mb: 1.5,
          borderBottom: '2px solid',
          borderColor: 'text.primary',
        }}
      >
        Receiving History{rows.length > 0 ? ` (${rows.length})` : ''}
      </Typography>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, mb: 2 }}>
        <TextField
          size="small"
          label="Search PO or vendor"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setShown(PAGE);
          }}
          sx={{ minWidth: 240 }}
        />
        <TextField
          select
          size="small"
          label="Project"
          value={projectFilter}
          onChange={(e) => {
            setProjectFilter(e.target.value);
            setShown(PAGE);
          }}
          sx={{ minWidth: 220 }}
        >
          <MenuItem value="">All projects</MenuItem>
          {projects.map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.description || p.projectId}
            </MenuItem>
          ))}
        </TextField>
      </Box>

      {/* Only while there is nothing to show. Under cache-and-network `loading` is also true during
          the background revalidation, and spinning over a list the user is already reading would
          make every visit to this view flash. */}
      {loading && !data && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading receiving history: {userMessage(error, { reading: true })}
        </Alert>
      )}
      {!loading && !error && rows.length === 0 && (
        <Alert severity="info">
          {search || projectFilter
            ? 'No purchase orders match this filter.'
            : 'No purchase orders have reached GP yet.'}
        </Alert>
      )}
      {rows.length > 0 && (
        <FitTable storageKey="receiving-history" columns={HISTORY_COLUMNS}>
          {visible.map((po) => (
            <HistoryRow
              key={po.id}
              po={po}
              // Off the row (#1215): the projects list leaves archived projects out.
              projectName={
                po.projectId ? po.projectDescription || po.projectNumber || DASH : noProjectPoLabel(po.poolKind)
              }
              expanded={expandedIds.has(po.id)}
              onToggle={() => toggle(po.id)}
            />
          ))}
        </FitTable>
      )}

      {rows.length > visible.length && (
        <Button size="small" variant="text" onClick={() => setShown((n) => n + PAGE)} sx={{ mt: 1 }}>
          Show {Math.min(PAGE, rows.length - visible.length)} more of {rows.length - visible.length}
        </Button>
      )}
    </Box>
  );
}
