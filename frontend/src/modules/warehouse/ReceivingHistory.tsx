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
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { ChevronRight } from 'lucide-react';
import { motion } from 'motion/react';
import { useQuery } from '@apollo/client/react';
import { formatPoStatus, poStatusChipColor } from '../po/poStatus';
import { GET_PO_RECEIVING_DETAILS, GET_RECEIVING_HISTORY_POS } from '../../graphql/warehouse';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { springs } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';

const ICON = { size: 18, strokeWidth: 1.75 } as const;

// Expander + PO + vendor + project + status + received-of-ordered + receives + last received.
const HISTORY_COLUMN_COUNT = 8;

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
  requestNumber: string;
  status: string;
  vendorName: string | null;
  projectId: string | null;
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
  lineItems: ReceiveRecordLineItem[];
}

interface ProjectOption {
  id: string;
  projectId: string;
  description: string | null;
}

interface ReceivingHistoryProps {
  projects: ProjectOption[];
  projectMap: Map<string, string>;
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
  if (error) {
    return <Alert severity="error">Error loading receives: {error.message}</Alert>;
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
          <Table size="small" sx={{ bgcolor: 'background.paper' }}>
            <TableHead>
              <TableRow>
                <TableCell>Category</TableCell>
                <TableCell>Product Code</TableCell>
                <TableCell align="right">Quantity Received</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {receive.lineItems.map((li) => (
                <TableRow key={li.id}>
                  <TableCell>{li.hardwareCategory}</TableCell>
                  <TableCell sx={monoSx}>{li.productCode}</TableCell>
                  <TableCell align="right" sx={tabularSx}>
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
  const hugSx = { width: '1%', whiteSpace: 'nowrap' as const };
  const label = po.poNumber ?? po.requestNumber;
  return (
    <>
      <TableRow hover sx={{ cursor: 'pointer', '& > *': { borderBottom: 'unset' } }} onClick={onToggle}>
        <TableCell sx={{ width: 48 }}>
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
        <TableCell>{po.vendorName || DASH}</TableCell>
        <TableCell>{projectName}</TableCell>
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
        <TableCell sx={{ p: 0, borderBottom: expanded ? undefined : 'none' }} colSpan={HISTORY_COLUMN_COUNT}>
          <Collapse in={expanded} timeout={220} unmountOnExit>
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
export default function ReceivingHistory({ projects, projectMap }: ReceivingHistoryProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
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
          Error loading receiving history: {error.message}
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
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 48 }} />
                <TableCell>PO Number</TableCell>
                <TableCell>Vendor</TableCell>
                <TableCell>Project</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Received</TableCell>
                <TableCell align="right">Receives</TableCell>
                <TableCell>Last Received</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visible.map((po) => (
                <HistoryRow
                  key={po.id}
                  po={po}
                  projectName={po.projectId ? (projectMap.get(po.projectId) ?? DASH) : 'Stock PO'}
                  expanded={expandedIds.has(po.id)}
                  onToggle={() => toggle(po.id)}
                />
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {rows.length > visible.length && (
        <Button size="small" variant="text" onClick={() => setShown((n) => n + PAGE)} sx={{ mt: 1 }}>
          Show {Math.min(PAGE, rows.length - visible.length)} more of {rows.length - visible.length}
        </Button>
      )}
    </Box>
  );
}
