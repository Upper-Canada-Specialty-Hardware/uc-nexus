import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Chip,
  Button,
  CircularProgress,
  Alert,
  TableCell,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  TextField,
  InputAdornment,
} from '@mui/material';
import { Search } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import SelectionActionBar, { BarButton } from '../../components/SelectionActionBar';
import PageHeader from '../../components/PageHeader';
import FitTable, { type FitTableColumn } from '../../components/FitTable';
import GpWriteQueuePanel from '../../components/GpWriteQueuePanel';
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
import { poVendorLabel, NO_GP_VENDOR, NO_GP_VENDOR_HINT } from '../po/poVendorName';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { noProjectPoLabel, type PoolKind } from '../../types/poolKind';
import { backOrderColumns, formatExpectedDate as formatDate, renderUrgencyChip } from './backOrderColumns';
import { FadeIn } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';

// ---- Types ----

// Lean receiving-picker row (gp-owned-po mirror): the two pending scalars come from the server's
// grouped query, so no line collection is loaded for the list.
interface OpenPO {
  id: string;
  poNumber: string | null;
  projectId: string | null;
  projectNumber: string | null;
  projectDescription: string | null;
  poolKind: PoolKind;
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

// The one write this page is answerable for: a GP RECEIVE ENTRY that has not reached GP yet. A
// constant rather than an inline array so the panel's query keeps one identity across renders.
const HELD_GP_RECEIVE_ENTRY_OPS = ['create_receipt'];

// #909: Recent Activity fits its width and never scrolls sideways; columns are resizable and
// remembered per person. Minimums hold a local date and time, a PO number, a GP receipt number and
// the item count whole; the receiver's name takes the slack and ellipsizes with it on hover.
const RECENT_COLUMNS: FitTableColumn[] = [
  { id: 'date', label: 'Date', min: 164, weight: 1 },
  { id: 'receivedBy', label: 'Received By', min: 110, weight: 1.6 },
  { id: 'poNumber', label: 'PO Number', min: 100, weight: 0.8 },
  // #447: the GP receipt, beside the PO it was posted against. This row is the last thing a receiver
  // sees after booking one in, so it is where the number is most likely to be wanted.
  { id: 'receipt', label: 'GP Receipt', min: 110, weight: 0.8 },
  { id: 'items', label: 'Items Received', min: 116, weight: 0.5, align: 'right' },
];

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
  poolKind: PoolKind;
}

// ---- Helpers ----

function formatDateTime(dateStr: string): string {
  return parseServerDate(dateStr).toLocaleString();
}

// ---- Component ----

export default function ReceivingPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [modalPOIds, setModalPOIds] = useState<string[]>([]);
  const [selectedPOIds, setSelectedPOIds] = useState<string[]>([]);
  const [poSearch, setPoSearch] = useState('');
  const { hasRole, ownsTenant } = useIdentity();
  const canReview = ownsTenant || hasRole('Warehouse Manager');

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

  // The history tab's project filter. Rows name their project off the server (#1196, #1215), since
  // this list leaves archived projects out.
  const projects = useMemo(() => projectsData?.projects ?? [], [projectsData]);

  // PO rows
  const poColumns: GridColDef[] = useMemo(
    () => [
      {
        field: 'poNumber',
        headerName: 'PO Number',
        flex: 0.8,
        minWidth: 120,
        renderCell: (params) => (
          <Typography component="span" sx={{ ...monoSx, fontWeight: 600 }}>
            {params.value as string}
          </Typography>
        ),
      },
      {
        field: 'vendorName',
        headerName: 'Vendor',
        flex: 1,
        minWidth: 150,
        // #701: a PO raised in GP with no vendor on it yet says so in plain words, and the hover
        // says whose gap it is. Every other row prints the vendor name exactly as it did before.
        renderCell: (params) => {
          const label = params.value as string;
          return label === NO_GP_VENDOR ? (
            <Tooltip title={NO_GP_VENDOR_HINT} arrow>
              <Typography component="span" variant="body2" noWrap>
                {label}
              </Typography>
            </Tooltip>
          ) : (
            <Typography component="span" variant="body2" noWrap>
              {label}
            </Typography>
          );
        },
      },
      { field: 'projectName', headerName: 'Project', flex: 1, minWidth: 140 },
      {
        field: 'expectedDeliveryDate',
        headerName: 'Expected Delivery',
        flex: 1,
        // The date and its urgency chip side by side.
        minWidth: 190,
        renderCell: (params) => {
          const date = params.value as string | null;
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, height: '100%' }}>
              <Typography variant="body2" sx={tabularSx}>
                {formatDate(date)}
              </Typography>
              {/* The chip carries lateness on its own, so the date itself stays neutral rather
                  than saying it twice. */}
              {renderUrgencyChip(date)}
            </Box>
          );
        },
      },
      {
        field: 'pendingLines',
        headerName: 'Pending Lines',
        flex: 0.6,
        minWidth: 120,
        type: 'number',
      },
      {
        field: 'pendingQty',
        headerName: 'Back Order',
        flex: 0.6,
        minWidth: 110,
        type: 'number',
      },
      {
        field: 'status',
        headerName: 'Status',
        flex: 0.7,
        // Room for the status chip and, briefly, the draft-pending chip beside it.
        minWidth: 130,
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
        vendorName: poVendorLabel(po) || '\u2014',
        // Off the row itself (#1196): the projects list leaves archived projects out.
        projectName: po.projectId
          ? po.projectDescription || po.projectNumber || '\u2014'
          : noProjectPoLabel(po.poolKind),
        jobNumber: po.projectNumber ?? '',
        expectedDeliveryDate: po.expectedDeliveryDate,
        pendingLines: po.pendingLineCount,
        pendingQty: po.pendingQuantity,
        status: po.status,
        pendingDraftCount: pendingDraftsByPoId.get(po.id)?.length ?? 0,
      })),
    [openPOsData, pendingDraftsByPoId],
  );

  // #857: the list runs to hundreds of POs, so a receiver with a delivery in hand narrows it as they
  // type, the way the PO table's search reads: PO number, vendor, or the project's job number or
  // name. Client-side, because every open PO is already loaded on this page.
  const poSearchTerm = poSearch.trim().toLowerCase();
  const filteredPoRows = useMemo(
    () =>
      poSearchTerm
        ? poRows.filter((row) =>
            [row.poNumber, row.vendorName, row.projectName, row.jobNumber].some((field) =>
              field.toLowerCase().includes(poSearchTerm),
            ),
          )
        : poRows,
    [poRows, poSearchTerm],
  );

  const backOrderRows = useMemo(
    () =>
      (backOrderData?.backOrderedItems ?? []).map((item) => ({
        ...item,
        // The PO line, not the row's position. A back-ordered row is a PO line, and every refetch
        // this page now performs re-runs the query's ORDER BY - so an index key would hand the grid
        // a fresh id for every unchanged row and make it rebuild instead of diff.
        id: item.poLineItemId,
        projectName: item.projectName ?? noProjectPoLabel(item.poolKind),
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
      <PageHeader
        title="Receiving"
        parent={{ label: 'Warehouse', to: '/app/warehouse' }}
        description={
          <>
            {view === 'receive' &&
              'Count hardware off a purchase order and into a rack location, and see what is still owed. Receives are submitted as drafts and post to GP when a Warehouse Manager approves them; a PO leaves this list while its receive waits.'}
            {view === 'drafts' &&
              'Your counted receives, waiting on a Warehouse Manager. Nothing here has reached GP or inventory yet.'}
            {view === 'history' &&
              'Every purchase order that reached GP, and what has landed against it. Open a row for its receipts.'}
          </>
        }
        actions={
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
        }
        sx={{ mb: 2.5 }}
      />

      {/* #754: the receives GP has not taken yet, on the dock they were counted on rather than only
          on the admin queue. It renders nothing while there are none. */}
      <GpWriteQueuePanel ops={HELD_GP_RECEIVE_ENTRY_OPS} compact heading="Held GP receive entries" />

      {view === 'drafts' && <MyReceiveDraftsView />}
      {view === 'history' && <ReceivingHistory projects={projects} />}

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
        POs Awaiting Receipt
        {/* #857: while a search is typed the count says how much of the list it is showing. */}
        {poRows.length > 0
          ? poSearchTerm
            ? ` (${filteredPoRows.length} of ${poRows.length})`
            : ` (${poRows.length})`
          : ''}
      </Typography>

      {poRows.length > 0 && (
        <TextField
          size="small"
          placeholder="Search PO #, vendor, or project…"
          inputProps={{ 'aria-label': 'Search POs awaiting receipt' }}
          value={poSearch}
          onChange={(e) => setPoSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search size={18} strokeWidth={1.75} />
              </InputAdornment>
            ),
          }}
          sx={{ mb: 1.5, width: '100%', maxWidth: 480 }}
        />
      )}

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
      {!openPOsLoading && !openPOsError && poRows.length > 0 && filteredPoRows.length === 0 && (
        <Alert severity="info" sx={{ mb: 3 }}>
          No POs awaiting receipt match &ldquo;{poSearch.trim()}&rdquo;.
        </Alert>
      )}
      {!openPOsLoading && !openPOsError && filteredPoRows.length > 0 && (
        // position: relative anchors the floating selection bar (#617 pattern) over this grid alone.
        <Box sx={{ mb: 4, position: 'relative' }}>
          <DataTable
            columns={poColumns}
            storageKey="warehouse.receiving.pos"
            rows={filteredPoRows}
            // #857: 25 a page rather than the table default of 10 - the list is long and is scanned.
            initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
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
          <DataTable columns={backOrderColumns} storageKey="warehouse.receiving.back-orders" rows={backOrderRows} getRowId={(row) => row.id} />
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
          <FitTable storageKey="receiving-recent-activity" columns={RECENT_COLUMNS}>
            {recentRecords.map((record) => (
              <TableRow key={record.receiveRecord.id} hover>
                <TableCell sx={tabularSx}>
                  {formatDateTime(record.receiveRecord.receivedAt)}
                </TableCell>
                <TableCell title={record.receiveRecord.receivedBy}>{record.receiveRecord.receivedBy}</TableCell>
                <TableCell sx={monoSx}>{record.poNumber ?? '\u2014'}</TableCell>
                <TableCell sx={monoSx}>
                  {record.receiveRecord.receiptNumber ?? '\u2014'}
                </TableCell>
                <TableCell align="right">{record.totalItemsReceived}</TableCell>
              </TableRow>
            ))}
          </FitTable>
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
