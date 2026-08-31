import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Paper,
  Chip,
  Button,
  CircularProgress,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import SelectionActionBar, { BarButton } from '../../components/SelectionActionBar';
import ReceiveModal from './ReceiveModal';
import ReceivingHistory from './ReceivingHistory';
import MyReceiveDraftsView from './MyReceiveDraftsView';
import { useIdentity } from '../../hooks/useIdentity';
import { formatPoStatus, poStatusChipColor } from '../po/poStatus';
import { GET_PROJECTS } from '../../graphql/shared';
import {
  GET_BACK_ORDERED_ITEMS,
  GET_OPEN_POS_SUMMARY,
  GET_RECENT_RECEIVE_RECORDS,
  GET_PENDING_DRAFT_SUMMARIES,
} from '../../graphql/warehouse';
import { poVendorName } from '../po/poVendorName';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import { parseServerDate, parseServerDay } from '../../utils/serverDate';

// ---- Types ----

// Lean receiving-picker row (gp-owned-po mirror): the two pending scalars come from the server's
// grouped query, so no line collection is loaded for the list.
interface OpenPO {
  id: string;
  poNumber: string | null;
  projectId: string | null;
  status: string;
  origin: string;
  vendorNameSnapshot: string | null;
  orderedAt: string | null;
  expectedDeliveryDate: string | null;
  pendingLineCount: number;
  pendingQuantity: number;
}

interface Project {
  id: string;
  projectId: string;
  description: string | null;
}

interface RecentReceiveRecord {
  receiveRecord: {
    id: string;
    poId: string;
    receivedAt: string;
    receivedBy: string;
    // #447: GP's number for the receipt this receive posted. Null on rows recorded before the
    // column existed, and on the rare receive whose relay response carried no number.
    receiptNumber: string | null;
  };
  poNumber: string | null;
  totalItemsReceived: number;
}

/** Which part of the dock is showing. Receive is what is owed and how to count it in; My Drafts is
 *  what the user has counted and is waiting on a manager to post; History is what already landed,
 *  which needs the completed POs the Receive view deliberately drops (#447). */
type ReceivingView = 'receive' | 'drafts' | 'history';

const RECEIVING_VIEWS: ReceivingView[] = ['receive', 'drafts', 'history'];

interface BackOrderedItem {
  poLineItemId: string;
  hardwareCategory: string;
  productCode: string;
  orderedQuantity: number;
  receivedQuantity: number;
  outstandingQuantity: number;
  poNumber: string | null;
  vendorName: string | null;
  expectedDeliveryDate: string | null;
  projectName: string | null;
}

// ---- Helpers ----

/** An expected-delivery date is a calendar date, so it goes through `parseServerDay` (#238). This
 *  page used the instant parse until #416 and printed every expected delivery a day early for any
 *  viewer behind UTC - invisible on its own, glaring once the urgency chip started counting days off
 *  the same value and calling a PO due today "1d overdue". */
function formatDate(dateStr: string | null): string {
  if (!dateStr) return '\u2014';
  const d = parseServerDay(dateStr);
  // Same unparseable-input guard the two PO screens put around their copies of this parse, so all
  // three read the same way if one of them is ever pointed at a looser field than a Date scalar.
  return isNaN(d.getTime()) ? '\u2014' : d.toLocaleDateString();
}

function formatDateTime(dateStr: string): string {
  return parseServerDate(dateStr).toLocaleString();
}

/** How late or how soon, as a chip, or null when the date is far enough out to say nothing about.
 *  Reads the date through the same `parseServerDay` the printed date uses, so the chip and the date
 *  it sits beside can never disagree about which day they mean. */
function urgencyOf(
  dateStr: string | null,
): { label: string; color: 'error' | 'warning' | 'info' } | null {
  if (!dateStr) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = parseServerDay(dateStr);
  date.setHours(0, 0, 0, 0);
  // Round, not ceil or floor. Both operands are local midnight, so a DST boundary between them makes
  // the span 23 or 25 hours rather than 24, and only rounding maps that back to the whole day it is.
  // Ceil got all three of the interesting cases wrong: tomorrow across a fall-back read "In 2d",
  // seven days out across one lost its chip entirely, and yesterday across a spring-forward came out
  // as -0, which is not < 0, so a PO that was already late chipped "Today".
  const days = Math.round((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (days < 0) return { label: `${Math.abs(days)}d overdue`, color: 'error' };
  if (days === 0) return { label: 'Today', color: 'warning' };
  if (days === 1) return { label: 'Tomorrow', color: 'info' };
  if (days <= 7) return { label: `In ${days}d`, color: 'info' };
  return null;
}

function UrgencyChip({ dateStr }: { dateStr: string | null }) {
  const urgency = urgencyOf(dateStr);
  if (!urgency) return null;
  return <Chip label={urgency.label} color={urgency.color} size="small" variant="outlined" />;
}

function MonoCell({ value }: { value: string | null }) {
  return (
    <Typography component="span" sx={monoSx}>
      {value == null || value === '' ? '\u2014' : value}
    </Typography>
  );
}

// The back-order grid is line-level and always cross-project, so unlike the PO table above it has to
// name the project on every row. A PO with no project is a stock PO - the same label that table uses.
const backOrderColumns: GridColDef[] = [
  {
    field: 'productCode',
    headerName: 'Product Code',
    flex: 1,
    renderCell: (params) => <MonoCell value={params.value as string | null} />,
  },
  { field: 'hardwareCategory', headerName: 'Category', flex: 1 },
  { field: 'projectName', headerName: 'Project', flex: 1 },
  { field: 'vendorName', headerName: 'Vendor', flex: 1 },
  {
    field: 'poNumber',
    headerName: 'PO #',
    flex: 0.7,
    renderCell: (params) => <MonoCell value={params.value as string | null} />,
  },
  // Ordered and Received beside Outstanding because the bare outstanding number does not say whether
  // a line is untouched or nearly complete, and "2 of 10" and "2 of 3" are very different problems.
  // The deleted Deliveries accordion was the only place this breakdown showed.
  { field: 'orderedQuantity', headerName: 'Ordered', flex: 0.5, type: 'number' },
  { field: 'receivedQuantity', headerName: 'Received', flex: 0.5, type: 'number' },
  { field: 'outstandingQuantity', headerName: 'Outstanding', flex: 0.6, type: 'number' },
  {
    field: 'expectedDeliveryDate',
    headerName: 'Expected',
    flex: 1,
    renderCell: (params) => {
      const date = params.value as string | null;
      return (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, height: '100%' }}>
          <Typography variant="body2" sx={tabularSx}>
            {formatDate(date)}
          </Typography>
          <UrgencyChip dateStr={date} />
        </Box>
      );
    },
  },
];

// ---- Component ----

export default function ReceivingPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [modalPOIds, setModalPOIds] = useState<string[]>([]);
  const [selectedPOIds, setSelectedPOIds] = useState<string[]>([]);
  const { hasRole, isAdmin } = useIdentity();
  const canReview = isAdmin || hasRole('Warehouse Manager');

  // The view lives in the URL so it can be linked to: the receive modal's success action sends the
  // user to their drafts, and the bell's rejection notification lands on the same view.
  const [searchParams, setSearchParams] = useSearchParams();
  const paramView = searchParams.get('view');
  const view: ReceivingView = RECEIVING_VIEWS.includes(paramView as ReceivingView)
    ? (paramView as ReceivingView)
    : 'receive';
  const setView = useCallback(
    (next: ReceivingView) => {
      // replace, not push: flipping a tab is not a navigation step somebody wants to walk back
      // through one at a time.
      setSearchParams(next === 'receive' ? {} : { view: next }, { replace: true });
    },
    [setSearchParams],
  );

  // Queries. The three receiving lists are skipped unless the Receive view is showing: they are a
  // different question, and paying for all three on a page that is not displaying them is the whole
  // cost of putting several views behind one route.
  const showReceive = view === 'receive';
  const {
    data: openPOsData,
    loading: openPOsLoading,
    error: openPOsError,
  } = useQuery<{ openPosSummary: OpenPO[] }>(GET_OPEN_POS_SUMMARY, { skip: !showReceive });

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);

  const {
    data: recentData,
    loading: recentLoading,
    error: recentError,
  } = useQuery<{ recentReceiveRecords: RecentReceiveRecord[] }>(GET_RECENT_RECEIVE_RECORDS, {
    variables: { limit: 10 },
    skip: !showReceive,
  });

  // Cross-project on purpose, hence the explicit null: what is still owed is the same question
  // whoever is standing at the dock, and the rest of this page is not project-scoped either.
  const {
    data: backOrderData,
    loading: backOrderLoading,
    error: backOrderError,
  } = useQuery<{ backOrderedItems: BackOrderedItem[] }>(GET_BACK_ORDERED_ITEMS, {
    variables: { projectId: null },
    skip: !showReceive,
  });

  // Everybody's pending drafts, for the "already counted" chip on the PO rows. Scoped to PENDING
  // rather than mine, because the point of the chip is to stop a SECOND person re-counting a
  // delivery that is already in the queue. Scalars only - this needs a count per PO, not every
  // line and rack row of every draft in the system.
  const { data: pendingDraftsData } = useQuery<{
    receiveDrafts: { id: string; poId: string; totalQuantity: number }[];
  }>(GET_PENDING_DRAFT_SUMMARIES, {
    skip: !showReceive,
    fetchPolicy: 'cache-and-network',
  });
  const pendingDraftsByPoId = useMemo(() => {
    const map = new Map<string, { id: string; totalQuantity: number }[]>();
    for (const d of pendingDraftsData?.receiveDrafts ?? []) {
      const list = map.get(d.poId) ?? [];
      list.push({ id: d.id, totalQuantity: d.totalQuantity });
      map.set(d.poId, list);
    }
    return map;
  }, [pendingDraftsData]);
  const pendingDraftCount = pendingDraftsData?.receiveDrafts?.length ?? 0;

  // Project lookup
  const projects = useMemo(() => projectsData?.projects ?? [], [projectsData]);
  const projectMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of projects) {
      map.set(p.id, p.description || p.projectId);
    }
    return map;
  }, [projects]);

  // PO rows
  const poColumns: GridColDef[] = useMemo(
    () => [
      {
        field: 'poNumber',
        headerName: 'PO Number',
        flex: 0.8,
        renderCell: (params) => (
          <Typography component="span" sx={{ ...monoSx, fontWeight: 600 }}>
            {params.value as string}
          </Typography>
        ),
      },
      { field: 'vendorName', headerName: 'Vendor', flex: 1 },
      { field: 'projectName', headerName: 'Project', flex: 1 },
      {
        field: 'expectedDeliveryDate',
        headerName: 'Expected Delivery',
        flex: 1,
        renderCell: (params) => {
          const date = params.value as string | null;
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, height: '100%' }}>
              <Typography variant="body2" sx={tabularSx}>
                {formatDate(date)}
              </Typography>
              {/* The chip carries lateness on its own, so the date itself stays neutral rather
                  than saying it twice. */}
              <UrgencyChip dateStr={date} />
            </Box>
          );
        },
      },
      {
        field: 'pendingLines',
        headerName: 'Pending Lines',
        flex: 0.6,
        type: 'number',
      },
      {
        field: 'pendingQty',
        headerName: 'Back Order',
        flex: 0.6,
        type: 'number',
      },
      {
        field: 'status',
        headerName: 'Status',
        flex: 0.7,
        renderCell: (params) => {
          const status = params.value as string;
          // Short labels for the two common receiving states; the shared formatter handles the rest so a
          // status that isn't one of these (e.g. CLOSED) isn't silently mislabeled as "GP-Registered".
          const label =
            status === 'PARTIALLY_RECEIVED'
              ? 'Partial'
              : status === 'VENDOR_CONFIRMED'
                ? 'Confirmed'
                : formatPoStatus(status);
          const pendingDrafts = params.row.pendingDraftCount as number;
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, height: '100%' }}>
              <Chip label={label} color={poStatusChipColor(status)} size="small" />
              {/* #641: a PO with a pending draft is dropped from openPosSummary server-side, so this
                  chip only shows in the window where the two queries disagree - the drafts query is
                  cache-and-network and can land first. It is the row's warning that the PO is about
                  to leave the list, not a state the user is meant to act on. */}
              {pendingDrafts > 0 && (
                <Chip
                  label={pendingDrafts === 1 ? 'Draft pending' : `${pendingDrafts} drafts pending`}
                  color="warning"
                  size="small"
                  variant="outlined"
                />
              )}
            </Box>
          );
        },
      },
    ],
    [],
  );

  const poRows = useMemo(
    () =>
      (openPOsData?.openPosSummary ?? []).map((po) => ({
        id: po.id,
        poNumber: po.poNumber ?? '\u2014',
        vendorName: poVendorName(po) || '\u2014',
        projectName: po.projectId ? (projectMap.get(po.projectId) ?? '\u2014') : 'Stock PO',
        expectedDeliveryDate: po.expectedDeliveryDate,
        pendingLines: po.pendingLineCount,
        pendingQty: po.pendingQuantity,
        status: po.status,
        pendingDraftCount: pendingDraftsByPoId.get(po.id)?.length ?? 0,
      })),
    [openPOsData, projectMap, pendingDraftsByPoId],
  );

  const backOrderRows = useMemo(
    () =>
      (backOrderData?.backOrderedItems ?? []).map((item) => ({
        ...item,
        // The PO line, not the row's position. A back-ordered row is a PO line, and every refetch
        // this page now performs re-runs the query's ORDER BY - so an index key would hand the grid
        // a fresh id for every unchanged row and make it rebuild instead of diff.
        id: item.poLineItemId,
        projectName: item.projectName ?? 'Stock PO',
        vendorName: item.vendorName ?? '\u2014',
      })),
    [backOrderData],
  );

  // Units, not lines. The landing card's back-ordered figure is a SUM of outstanding quantities, so
  // a header counting rows would disagree with the number that linked the user here.
  const backOrderUnits = useMemo(
    () => backOrderRows.reduce((sum, r) => sum + r.outstandingQuantity, 0),
    [backOrderRows],
  );

  const recentRecords = recentData?.recentReceiveRecords ?? [];

  // Handlers
  const handlePORowClick = useCallback((params: GridRowParams) => {
    setModalPOIds([params.row.id as string]);
    setModalOpen(true);
  }, []);

  const handleReceiveSelected = useCallback(() => {
    setModalPOIds([...selectedPOIds]);
    setModalOpen(true);
  }, [selectedPOIds]);

  const handleCloseModal = useCallback(() => {
    setModalOpen(false);
    setModalPOIds([]);
    setSelectedPOIds([]);
  }, []);

  return (
    <Box sx={{ position: 'relative', minHeight: '60vh' }}>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 2,
          flexWrap: 'wrap',
          mb: 2.5,
        }}
      >
        <Box>
          <Typography variant="h5" sx={{ mb: 0.5 }}>
            Receiving
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {view === 'receive' &&
              'Count hardware off a purchase order and into a rack location, and see what is still owed. Receives are submitted as drafts and post to GP when a Warehouse Manager approves them; a PO leaves this list while its receive waits.'}
            {view === 'drafts' &&
              'Your counted receives, waiting on a Warehouse Manager. Nothing here has reached GP or inventory yet.'}
            {view === 'history' &&
              'Every purchase order that reached GP, and what has landed against it. Open a row for its receipts.'}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          {/* The manager's queue is a different screen, not a fourth tab: it works everybody's
              drafts, while these three views are all about this user's dock. */}
          {canReview && (
            <Button size="small" variant="outlined" component={RouterLink} to="/app/warehouse/receive-approvals">
              Approvals
              {pendingDraftsByPoId.size > 0 && ` (${pendingDraftCount})`}
            </Button>
          )}
          {/* Three views of the same dock, not three pages: what is owed, what you have counted, and
              what already arrived. The History side keeps the completed POs the Receive side drops
              (#447). */}
          <ToggleButtonGroup
            size="small"
            exclusive
            value={view}
            onChange={(_e, next: ReceivingView | null) => {
              if (next) setView(next);
            }}
            aria-label="Receiving view"
          >
            <ToggleButton value="receive">Receive</ToggleButton>
            <ToggleButton value="drafts">My Drafts</ToggleButton>
            <ToggleButton value="history">History</ToggleButton>
          </ToggleButtonGroup>
        </Box>
      </Box>

      {view === 'drafts' && <MyReceiveDraftsView />}
      {view === 'history' && <ReceivingHistory projects={projects} projectMap={projectMap} />}

      {showReceive && (
        <>
      {/* Pending POs Section. Multi-select receive moved off this band and into the floating
          selection bar over the grid, so the band is just the label like the sections below. */}
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
        POs Awaiting Receipt{poRows.length > 0 ? ` (${poRows.length})` : ''}
      </Typography>

      {openPOsLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {openPOsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading purchase orders: {openPOsError.message}
        </Alert>
      )}
      {!openPOsLoading && !openPOsError && poRows.length === 0 && (
        <Alert severity="info" sx={{ mb: 3 }}>
          No purchase orders awaiting receipt.
          {/* #641: an empty list with drafts in the queue is not the same as nothing to do, and the
              difference is exactly what a receiver whose PO just vanished needs told. */}
          {pendingDraftCount > 0 &&
            ` ${pendingDraftCount} ${pendingDraftCount === 1 ? 'receive is' : 'receives are'} waiting on a Warehouse Manager.`}
        </Alert>
      )}
      {!openPOsLoading && !openPOsError && poRows.length > 0 && (
        // position: relative anchors the floating selection bar (#617 pattern) over this grid alone.
        <Box sx={{ mb: 4, position: 'relative' }}>
          <DataTable
            columns={poColumns}
            rows={poRows}
            checkboxSelection
            rowSelectionModel={{ type: 'include' as const, ids: new Set(selectedPOIds) }}
            onRowSelectionModelChange={(newModel) =>
              setSelectedPOIds(Array.from(newModel.ids) as string[])
            }
            onRowClick={handlePORowClick}
            sx={{ cursor: 'pointer' }}
            getRowId={(row) => row.id}
          />
          {/* Row click stays the single-PO path; ticking checkboxes is the multi path, and the bar
              is its visible grammar from the first tick. */}
          <SelectionActionBar count={selectedPOIds.length} onClear={() => setSelectedPOIds([])}>
            <BarButton label="Receive" onClick={handleReceiveSelected} />
          </SelectionActionBar>
        </Box>
      )}

      {/* Back-Ordered Items Section */}
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
        Back-Ordered Items
        {backOrderRows.length > 0
          ? ` (${backOrderRows.length} ${backOrderRows.length === 1 ? 'line' : 'lines'}, ${backOrderUnits} ${backOrderUnits === 1 ? 'unit' : 'units'})`
          : ''}
      </Typography>

      {backOrderLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {backOrderError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading back-ordered items: {backOrderError.message}
        </Alert>
      )}
      {!backOrderLoading && !backOrderError && backOrderRows.length === 0 && (
        <Alert severity="info" sx={{ mb: 3 }}>
          Nothing is back-ordered.
        </Alert>
      )}
      {!backOrderLoading && !backOrderError && backOrderRows.length > 0 && (
        <Box sx={{ mb: 4 }}>
          <DataTable columns={backOrderColumns} rows={backOrderRows} getRowId={(row) => row.id} />
        </Box>
      )}

      {/* Recent Activity Section */}
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
        Recent Activity
      </Typography>

      {recentLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {recentError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading recent activity: {recentError.message}
        </Alert>
      )}
      {!recentLoading && !recentError && recentRecords.length === 0 && (
        <Typography color="text.secondary">No recent receiving activity.</Typography>
      )}
      {!recentLoading && !recentError && recentRecords.length > 0 && (
        <FadeIn y={8}>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Date</TableCell>
                  <TableCell>Received By</TableCell>
                  <TableCell>PO Number</TableCell>
                  {/* #447: the GP receipt, beside the PO it was posted against. This row is the
                      last thing a receiver sees after booking one in, so it is where the number is
                      most likely to be wanted. */}
                  <TableCell>GP Receipt</TableCell>
                  <TableCell align="right">Items Received</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {recentRecords.map((record) => (
                  <TableRow key={record.receiveRecord.id} hover>
                    <TableCell sx={tabularSx}>
                      {formatDateTime(record.receiveRecord.receivedAt)}
                    </TableCell>
                    <TableCell>{record.receiveRecord.receivedBy}</TableCell>
                    <TableCell sx={monoSx}>{record.poNumber ?? '\u2014'}</TableCell>
                    <TableCell sx={monoSx}>
                      {record.receiveRecord.receiptNumber ?? '\u2014'}
                    </TableCell>
                    <TableCell align="right">{record.totalItemsReceived}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </FadeIn>
      )}
        </>
      )}

      <ReceiveModal
        open={modalOpen}
        onClose={handleCloseModal}
        poIds={modalPOIds}
        pendingDraftsByPoId={pendingDraftsByPoId}
      />
    </Box>
  );
}
