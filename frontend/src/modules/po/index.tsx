import { useState, useMemo, useEffect, useRef } from 'react';
import {
  Box,
  Typography,
  ButtonBase,
  Chip,
  Button,
  Alert,
  Paper,
  TableRow,
  TableCell,
  TableSortLabel,
  TablePagination,
  IconButton,
  CircularProgress,
  TextField,
  InputAdornment,
  Tooltip,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import { alpha, keyframes, type Theme } from '@mui/material/styles';
import { Plus, ChevronRight, Settings, Search, RefreshCw } from 'lucide-react';
import { useQuery, useMutation } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import {
  PURCHASE_ORDERS_PAGE,
  GET_PO_STATISTICS,
  GET_PURCHASE_ORDER,
  SYNC_GP_POS,
} from '../../graphql/po';
import { GET_GP_OUTBOX, GET_PROJECTS } from '../../graphql/shared';
import type { Project } from '../../types/project';
import Modal from '../../components/Modal';
import FitTable, { type FitTableColumn } from '../../components/FitTable';
import GpWriteQueuePanel from '../../components/GpWriteQueuePanel';
import PODetailModal from './PODetailModal';
import GpPurchaseOrderDialog from './GpPurchaseOrderDialog';
import CreatePOChooser from './CreatePOChooser';
import RelayStatusChip from '../../relay/RelayStatusChip';
import GpCompanyLabel from '../../relay/GpCompanyLabel';
import { useActingCompany } from '../../company/ActingCompanyContext';
import { useRelayFor } from '../../relay/useRelayStatus';
import { formatPoStatus, poStatusChipColor } from './poStatus';
import { isAwaitingGpReadBack } from './poDocumentGate';
import { isStatusCardActive, toggleStatusCard } from './statusCardFilter';
import { HIGHLIGHT_PARAM, PROJECT_PARAM, parseHighlightParam } from './poTableLinks';
import { Routes, Route, useNavigate, useSearchParams } from 'react-router-dom';
import { useIdentity } from '../../hooks/useIdentity';
import PODocumentSettingsPage from './PODocumentSettingsPage';
import { useToast } from '../../components/Toast';
import { monoSx, tabularSx, microLabelSx } from '../../theme';
import { AnimatedNumber, FadeIn, StaggerItem, StaggerList } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';
import { formatPoOrderDate, isGpEmptyDate, NO_GP_DATE_HINT } from './poOrderDate';
import { poVendorLabel, NO_GP_VENDOR, NO_GP_VENDOR_HINT } from './poVendorName';
import type { PoolKind } from '../../types/poolKind';
import { PoolKindChip } from '../../components/PoolKind';

const ICON = { size: 18, strokeWidth: 1.75 } as const;

// --- Types ---

interface POLineItem {
  id: string;
  poId: string;
  hardwareCategory: string;
  productCode: string;
  classification: string | null;
  orderedQuantity: number;
  receivedQuantity: number;
  unitCost: number;
  orderAs: string | null;
  // GP's own three per-line fields: the cost code the line books to, its unit of measure, and
  // whether GP books it to the job at all. A line on a PO with no project is never job cost.
  costCode: string | null;
  uofm: string | null;
  jobCost: boolean;
  // GP POP10110.ORD this line maps to; present on registered/mirrored lines.
  gpLineOrd: number | null;
  // True when hardwareCategory and productCode above came off a hardware schedule, so the GP sync
  // leaves them alone; false while the line still carries GP's own item number and description.
  nexusRegistered: boolean;
  // Set when the line was added from the non-schedule item catalog (#454). Order As belongs to
  // hardware schedule items only, so a line with this shows none.
  customInventoryItemId: string | null;
  // Issue #232: derived from the line's linked HardwareItem(s); drives the PO dialog's vendor suggestion.
  manufacturer: string | null;
  createdAt: string;
  updatedAt: string;
}

interface ReceiveRecordLineItem {
  id: string;
  receiveRecordId: string;
  poLineItemId: string;
  hardwareCategory: string;
  productCode: string;
  quantityReceived: number;
  createdAt: string;
}

interface ReceiveRecord {
  id: string;
  poId: string;
  receivedAt: string;
  receivedBy: string;
  createdAt: string;
  lineItems: ReceiveRecordLineItem[];
}

export interface PODocumentInfo {
  id: string;
  poId: string;
  fileName: string;
  contentType: string;
  fileSize: number;
  documentType: string;
  uploadedAt: string;
  downloadUrl: string;
}

export interface PODocumentData {
  id: string;
  poId: string;
  vendorAddress: string | null;
  buyerName: string | null;
  currency: string;
  shipTo: string | null;
  shippingMethod: string | null;
  quotationNumber: string | null;
  freight: number;
  miscellaneous: number;
  taxAmount: number;
  taxLabel: string;
  tariffAmount: number;
  requiredByOverride: string | null;
  includeFsc: boolean;
  includeUsaTariff: boolean;
  includeCustoms: boolean;
}

// The full PO the detail modal renders. The register list itself is slim (POListRow); opening a row
// fetches this by id (gp-owned-po mirror). request_number is null on a mirrored PO.
export interface PurchaseOrder {
  id: string;
  poNumber: string | null;
  requestNumber: string | null;
  // NEXUS (drafted here) or GP (discovered by the mirror sync).
  origin: string;
  gpSyncedAt: string | null;
  // True when every one of this PO's lines is a NEXUS REGISTERED LINE.
  nexusRegistered: boolean;
  projectId: string | null;
  // #832: Stock or Overhead - which half of the pool a PO with no project receives into. Optional
  // because not every document that builds a PurchaseOrder selects it.
  poolKind?: PoolKind;
  status: string;
  // #637: the tenant that owns the PO. Stamped when the PO is raised, so a draft has it too,
  // unlike gpCompany, which arrives only at GP registration.
  company: string;
  gpCompany: string | null;
  gpVendorId: string | null;
  vendorNameSnapshot: string | null;
  // #490: the buyer's GP cost-code pick, optionally captured at request time and used as the
  // default when the draft is registered.
  costCode: string | null;
  buyerId: string | null;
  vendorQuoteNumber: string | null;
  shippingCost: number | null;
  tariffAmount: number | null;
  notes: string | null;
  preferredDeliveryDate: string | null;
  expectedDeliveryDate: string | null;
  orderedAt: string | null;
  createdAt: string;
  updatedAt: string;
  lineItems: POLineItem[];
  receiveRecords: ReceiveRecord[];
  documents: PODocumentInfo[];
  documentData: PODocumentData | null;
}

// One register row (gp-owned-po mirror). Slim on purpose - a lineItemCount scalar, not the lines.
interface POListRow {
  id: string;
  poNumber: string | null;
  requestNumber: string | null;
  projectId: string | null;
  // #958: Stock or Overhead, shown as a chip where a PO with no project has no job.
  poolKind: PoolKind;
  status: string;
  origin: string;
  // #637: the tenant that owns the PO. Present on a draft, which gpCompany is not.
  company: string;
  gpCompany: string | null;
  vendorNameSnapshot: string | null;
  // #632: who raised it - resolved server-side (Clerk display name for a Nexus request, the GP buyer
  // id for a mirrored row, null when neither is known).
  createdBy: string | null;
  orderedAt: string | null;
  expectedDeliveryDate: string | null;
  createdAt: string;
  gpSyncedAt: string | null;
  lineItemCount: number;
}

interface POStatistics {
  total: number;
  draft: number;
  gpRegistered: number;
  vendorConfirmed: number;
  partiallyReceived: number;
  closed: number;
  cancelled: number;
}

// --- Status strip config ---

// `status` is the po_status the segment filters the table to when clicked (#316); null on Total, which
// clears the status filter. Clicking the active segment clears it too, so the strip doubles as the
// status filter and never traps you in a filtered view.
//
// The segments sit in two captioned boxes (#682) because the reader cannot otherwise tell who decides
// a PO's status: a draft only ever exists in Nexus, while the five statuses in the second box are
// written from GP by the OPEN-POS SYNC.
interface StatCard {
  label: string;
  key: keyof POStatistics;
  status: string | null;
}

const STAT_CARD_GROUPS: { caption: string; cards: StatCard[] }[] = [
  {
    caption: 'NEXUS',
    cards: [
      { label: 'Total', key: 'total', status: null },
      { label: 'Nexus Draft', key: 'draft', status: 'DRAFT' },
    ],
  },
  {
    caption: 'GP STATUSES',
    cards: [
      { label: 'GP-Registered', key: 'gpRegistered', status: 'GP_REGISTERED' },
      { label: 'Vendor Confirmed', key: 'vendorConfirmed', status: 'VENDOR_CONFIRMED' },
      { label: 'Partially Received', key: 'partiallyReceived', status: 'PARTIALLY_RECEIVED' },
      { label: 'Closed', key: 'closed', status: 'CLOSED' },
      // Mirror-CANCELLED rows (deleted_at NULL) still count into Total, so without a segment for them
      // the strip would stop summing to Total and those rows would be unreachable by any status filter.
      { label: 'Cancelled', key: 'cancelled', status: 'CANCELLED' },
    ],
  },
];

// The active segment's fill: the secondary accent at a tint strong enough to spot across the room.
const activeSegmentTint = (t: Theme) =>
  t.vars ? `rgba(${t.vars.palette.secondary.mainChannel} / 0.16)` : alpha(t.palette.secondary.main, 0.16);

const STAT_CARD_COUNT = STAT_CARD_GROUPS.reduce((n, g) => n + g.cards.length, 0);

// #851: the table opens on everything, newest first (DEFAULT_SORT), drafts and GP-mirrored POs
// together. It used to open on the three open GP statuses, which hid a draft someone had just raised
// while no segment looked pressed to say so. The segments are now optional narrowing only.

// #851: rows the import wizard has just created are tinted amber for a moment when the table opens on
// them, the same fade as the spreadsheet paste tint in the register dialog (#833).
const highlightedRowFade = keyframes`
  from { background-color: var(--highlighted-row-tint); }
  to { background-color: transparent; }
`;
const HIGHLIGHT_MS = 4000;

// The one write this module is answerable for: a PO REGISTRATION that has not reached GP yet. A
// constant rather than an inline array so the panel's query keeps one identity across renders.
const HELD_PO_REGISTRATION_OPS = ['create_po'];
// #854: the panel lists only registrations that still need someone; finished ones drop off.
const HELD_PO_REGISTRATION_STATUSES = ['PENDING', 'IN_FLIGHT', 'FAILED'];

// --- Server-driven sort ---

// Only columns the server can order by (gp-owned-po mirror). Project columns join client-side and are
// not sortable server-side; the items column is a scalar count, also not a sort key.
type SortField = 'poNumber' | 'status' | 'vendor' | 'createdAt' | 'orderedAt';

interface SortState {
  field: SortField;
  dir: 'asc' | 'desc';
}

type OriginFilter = 'ALL' | 'NEXUS' | 'GP';

const DEFAULT_SORT: SortState = { field: 'createdAt', dir: 'desc' };
const ROWS_PER_PAGE_OPTIONS = [25, 50, 100];

function poDisplayId(po: POListRow): string {
  return po.poNumber ?? po.requestNumber ?? '';
}

// Project columns: POs carry only projectId (a UUID); the human number + name come from the projects
// list, joined client-side via this map.
type ProjectsById = Map<string, Project>;

// --- Columns ---

/**
 * #909: the PO table fits its width and never scrolls sideways; columns are resizable and remembered
 * per person. Minimums hold a project number, a PO number with its GP or Nexus Draft chip, a status
 * chip, a local date (or "No date in GP") and the item count whole; the vendor takes the slack, and
 * vendor, creator and project name ellipsize with the full value on hover. The chevron is fixed.
 */
function poTableColumns(sortState: SortState, onSort: (field: SortField) => void): FitTableColumn[] {
  const sortable = (field: SortField, label: string, min: number, weight: number): FitTableColumn => {
    const active = sortState.field === field;
    return {
      id: field,
      label,
      min,
      weight,
      sortDirection: active ? sortState.dir : false,
      header: (
        <TableSortLabel active={active} direction={active ? sortState.dir : 'asc'} onClick={() => onSort(field)}>
          {label}
        </TableSortLabel>
      ),
    };
  };
  return [
    { id: 'project', label: 'Project', min: 120, weight: 1.2 },
    sortable('poNumber', 'PO / Request #', 176, 1),
    sortable('status', 'Status', 136, 1),
    sortable('vendor', 'Vendor', 140, 3),
    { id: 'createdBy', label: 'Created By', min: 100, weight: 1 },
    sortable('createdAt', 'Creation Date', 112, 0.7),
    sortable('orderedAt', 'Order Date', 112, 0.7),
    { id: 'items', label: 'Items', min: 64, weight: 0.4, align: 'right' },
    { id: 'open', label: 'Open', min: 48, fixed: 48, header: null, flush: true },
  ];
}

const PO_TABLE_COLUMN_COUNT = 9;

// --- Single register row ---

interface POTableRowProps {
  po: POListRow;
  projectNumber: string;
  projectName: string;
  onOpen: () => void;
  // #353 PR E: this PO has a GP write on the outbox. Joined client-side, not a per-row resolver.
  gpWriteQueued: boolean;
  // #851: one of the POs the import wizard just created; tinted for a moment on arrival.
  highlighted?: boolean;
}

function POTableRow({ po, projectNumber, projectName, onOpen, gpWriteQueued, highlighted = false }: POTableRowProps) {
  const hugSx = { width: '1%', whiteSpace: 'nowrap' as const };
  // #701: where a PO raised in GP carries no vendor, or no document date, the cell says so in plain
  // words. A bare dash left the reader unable to tell an empty field in GP from Nexus failing to
  // read one.
  const vendorLabel = poVendorLabel(po);
  const noGpVendor = vendorLabel === NO_GP_VENDOR;
  const noGpDate = isGpEmptyDate(po.orderedAt);
  return (
    <TableRow
      hover
      onClick={onOpen}
      data-highlighted={highlighted || undefined}
      sx={(theme) => ({
        cursor: 'pointer',
        '&:hover .po-row-chevron': { color: 'text.primary' },
        ...(highlighted && {
          '--highlighted-row-tint': alpha(theme.palette.warning.main, 0.16),
          animation: `${highlightedRowFade} ${HIGHLIGHT_MS}ms ease-out forwards`,
        }),
      })}
    >
      {/* #632: one Project column - mono number over the truncated name - so the register fits
          1366px without the container growing an x-scroll. */}
      <TableCell sx={hugSx} title={projectNumber || undefined}>
        {po.projectId ? (
          <Box component="span" sx={{ ...monoSx, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {projectNumber || '-'}
          </Box>
        ) : (
          <PoolKindChip kind={po.poolKind ?? 'STOCK'} />
        )}
        {projectName && (
          <Typography
            variant="caption"
            color="text.secondary"
            noWrap
            title={projectName}
            sx={{ display: 'block', minWidth: 0 }}
          >
            {projectName}
          </Typography>
        )}
      </TableCell>
      <TableCell sx={hugSx}>
        {po.poNumber ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <Box component="span" sx={monoSx}>
              {po.poNumber}
            </Box>
            {po.origin === 'GP' && (
              <Tooltip title="Mirrored from GP - not raised through Nexus" arrow>
                <Chip label="GP" size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
              </Tooltip>
            )}
          </Box>
        ) : (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <Box component="span" sx={{ ...monoSx, color: 'text.secondary' }}>
              {po.requestNumber ?? '-'}
            </Box>
            <Chip label="Nexus Draft" size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
          </Box>
        )}
      </TableCell>
      <TableCell sx={hugSx}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
          <Chip label={formatPoStatus(po.status)} color={poStatusChipColor(po.status)} size="small" />
          {gpWriteQueued && (
            <Tooltip title="Waiting for the GP relay. This will post automatically when it reconnects." arrow>
              <Chip label="GP registration queued" color="warning" size="small" variant="outlined" />
            </Tooltip>
          )}
        </Box>
      </TableCell>
      {/* The one stretch column: absorbs the slack and truncates instead of widening the table. */}
      <TableCell>
        {noGpVendor ? (
          <Tooltip title={NO_GP_VENDOR_HINT} arrow>
            <Typography variant="body2" noWrap>
              {NO_GP_VENDOR}
            </Typography>
          </Tooltip>
        ) : (
          <Typography variant="body2" noWrap title={vendorLabel || undefined}>
            {vendorLabel || '-'}
          </Typography>
        )}
      </TableCell>
      <TableCell sx={hugSx}>
        <Typography variant="body2" noWrap title={po.createdBy || undefined}>
          {po.createdBy || '-'}
        </Typography>
      </TableCell>
      <TableCell sx={{ ...hugSx, ...tabularSx }}>
        {parseServerDate(po.createdAt).toLocaleDateString()}
      </TableCell>
      <TableCell sx={{ ...hugSx, ...tabularSx }}>
        {noGpDate ? (
          <Tooltip title={NO_GP_DATE_HINT} arrow>
            <Box component="span">{formatPoOrderDate(po.orderedAt)}</Box>
          </Tooltip>
        ) : (
          formatPoOrderDate(po.orderedAt)
        )}
      </TableCell>
      <TableCell sx={{ ...hugSx, ...tabularSx }} align="right">
        {po.lineItemCount}
      </TableCell>
      {/* Says the row goes somewhere, and gives the keyboard the same door the mouse has. */}
      <TableCell sx={{ px: 0.5, py: 0 }} align="center">
        <IconButton
          size="small"
          className="po-row-chevron"
          aria-label={`Open ${poDisplayId(po)} details`}
          onClick={(e) => {
            e.stopPropagation();
            onOpen();
          }}
          sx={{ color: 'text.disabled', transition: 'color 0.15s ease' }}
        >
          <ChevronRight {...ICON} />
        </IconButton>
      </TableCell>
    </TableRow>
  );
}

// --- Component ---

function POListPage() {
  const navigate = useNavigate();
  const { ownsTenant, hasRole } = useIdentity();
  const { company } = useActingCompany();
  const { showToast } = useToast();
  // #732: `?po=<id>` opens that PO's detail on arrival (the import wizard's view POs links land here in
  // a new tab). The detail loads by id, so it opens whatever the table's filters and page are.
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedPOId, setSelectedPOId] = useState<string | null>(() => searchParams.get('po'));
  const [modalOpen, setModalOpen] = useState(() => searchParams.has('po'));
  const [createOpen, setCreateOpen] = useState(false);
  const [chooserOpen, setChooserOpen] = useState(false);

  // Server-driven filter / sort / page state.
  const [searchInput, setSearchInput] = useState('');
  const [committedSearch, setCommittedSearch] = useState('');
  const [statuses, setStatuses] = useState<Set<string>>(() => new Set());
  const [origin, setOrigin] = useState<OriginFilter>('ALL');
  // #851: the project scope lives in the link (`?project=<id>`), not in a picker: the project detail
  // page opens the table on its own project, and the Sidebar's plain link lands unscoped even while
  // this page is already mounted, because the scope is read from the URL on every render.
  const projectId = searchParams.get(PROJECT_PARAM);
  // #851: the import wizard's new drafts, tinted and scrolled to when the table opens on them.
  const highlightParam = searchParams.get(HIGHLIGHT_PARAM);
  const highlightIds = useMemo(() => new Set(parseHighlightParam(highlightParam)), [highlightParam]);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);

  // Debounce the search box so a query does not fire on every keystroke; a new term returns to page 1.
  useEffect(() => {
    const t = setTimeout(() => {
      setCommittedSearch(searchInput.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  // #1336: the PO table works in the acting company, so GP actions need the relay to serve it - a relay
  // connected for another company reads as down for Sync, Register and the dialogs fed from here.
  const relay = useRelayFor();
  const relayConnected = relay.connected === true ? relay.servesCompany : relay.connected;

  // #353 PR E: which POs have a GP write still on the outbox, joined onto rows client-side on
  // entityKey (`po:<id>`) rather than as a per-row resolver (which would be an N+1).
  const { data: outboxData } = useQuery<{ gpOutbox: { id: string; entityKey: string; status: string }[] }>(
    GET_GP_OUTBOX,
    { variables: { limit: 200 }, fetchPolicy: 'cache-and-network', pollInterval: 15_000 },
  );
  const queuedPoIds = useMemo(() => {
    const ids = new Set<string>();
    for (const entry of outboxData?.gpOutbox ?? []) {
      if (entry.status !== 'PENDING' && entry.status !== 'IN_FLIGHT') continue;
      if (entry.entityKey?.startsWith('po:')) ids.add(entry.entityKey.slice(3));
    }
    return ids;
  }, [outboxData]);

  const { data: statsData, loading: statsLoading, refetch: refetchStats } = useQuery<{
    poStatistics: POStatistics;
  }>(GET_PO_STATISTICS);

  // #851: a search spans every status. Someone looking up a PO by number should find it whichever
  // segment happens to be pressed; clearing the search returns to that segment's narrowing.
  const searchingAllStatuses = committedSearch !== '';

  const pageVariables = useMemo(
    () => ({
      search: committedSearch || null,
      statuses: !searchingAllStatuses && statuses.size ? Array.from(statuses) : null,
      origin: origin === 'ALL' ? null : origin,
      projectId: projectId || null,
      sortField: sort.field,
      sortDir: sort.dir,
      limit: rowsPerPage,
      offset: page * rowsPerPage,
    }),
    [committedSearch, searchingAllStatuses, statuses, origin, projectId, sort, rowsPerPage, page],
  );

  const {
    data: pageData,
    loading: pageLoading,
    refetch: refetchPage,
  } = useQuery<{ purchaseOrdersPage: { rows: POListRow[]; totalCount: number } }>(PURCHASE_ORDERS_PAGE, {
    variables: pageVariables,
    fetchPolicy: 'cache-and-network',
  });

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);

  // The selected PO's full detail (lines/documents/receives) for the modal, fetched on open. The
  // modal opens immediately on a row click; loading/error drive its placeholder until this resolves.
  const {
    data: selectedData,
    loading: selectedLoading,
    error: selectedError,
    refetch: refetchSelected,
    startPolling: startPollingSelected,
    stopPolling: stopPollingSelected,
  } = useQuery<{ purchaseOrder: PurchaseOrder | null }>(GET_PURCHASE_ORDER, {
    variables: { id: selectedPOId },
    skip: !selectedPOId,
    fetchPolicy: 'cache-and-network',
  });

  const [syncGpPos, { loading: syncing }] = useMutation(SYNC_GP_POS);

  const stats = statsData?.poStatistics;
  const rows = useMemo(() => pageData?.purchaseOrdersPage.rows ?? [], [pageData]);
  const totalCount = pageData?.purchaseOrdersPage.totalCount ?? 0;
  const projects = useMemo(() => projectsData?.projects ?? [], [projectsData?.projects]);
  const projectsById = useMemo<ProjectsById>(() => new Map(projects.map((p) => [p.id, p])), [projects]);
  const selectedPO = selectedData?.purchaseOrder ?? null;

  // #858: while the open PO's registration is queued or GP's copy has not been read back yet, the
  // detail holds its Generate PO Document button. Re-read the PO until that settles, so the button
  // comes up on its own instead of waiting for the person to close and reopen the PO.
  const selectedAwaitingGp =
    !!selectedPO && (queuedPoIds.has(selectedPO.id) || isAwaitingGpReadBack(selectedPO));
  useEffect(() => {
    if (!selectedAwaitingGp) return;
    startPollingSelected(10_000);
    return () => stopPollingSelected();
  }, [selectedAwaitingGp, startPollingSelected, stopPollingSelected]);

  const projectNumberOf = (po: POListRow) => (po.projectId ? projectsById.get(po.projectId)?.projectId ?? '' : '');
  const projectNameOf = (po: POListRow) => {
    if (!po.projectId) return '';
    const p = projectsById.get(po.projectId);
    return p?.description || p?.projectId || '';
  };

  // #851: once the highlighted rows have rendered, bring the first into view, then drop the link's
  // highlight when the tint has faded so a reload or a later refetch does not tint them again.
  const tableRef = useRef<HTMLDivElement>(null);
  const highlightShown = highlightIds.size > 0 && !pageLoading && rows.some((r) => highlightIds.has(r.id));
  useEffect(() => {
    if (!highlightShown) return;
    // jsdom has no scrollIntoView, hence the optional call.
    tableRef.current?.querySelector('[data-highlighted]')?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
    const t = setTimeout(() => {
      setSearchParams(
        (prev) => {
          prev.delete(HIGHLIGHT_PARAM);
          return prev;
        },
        { replace: true },
      );
    }, HIGHLIGHT_MS);
    return () => clearTimeout(t);
  }, [highlightShown, setSearchParams]);

  // Clamp the page when the server's total shrinks under it without a filter change - cancel the last
  // PO on the last page and the query would otherwise sit past the end on the empty state until a
  // filter moved. Adjusted during render (React's prescribed alternative to a state-sync effect): the
  // out-of-range page never commits, and setting it re-runs the query at the corrected offset. Guarded
  // on a real server answer (pageData present) so it never fights the first load, and the strict
  // inequality makes it self-terminating.
  if (pageData) {
    const lastPage = Math.max(0, Math.ceil(totalCount / rowsPerPage) - 1);
    if (page > lastPage) setPage(lastPage);
  }

  // --- Handlers ---

  const handleSortClick = (field: SortField) => {
    setSort((prev) => (prev.field === field ? { field, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { field, dir: 'asc' }));
    setPage(0);
  };

  const handleCardClick = (status: string | null) => {
    setStatuses((prev) => toggleStatusCard({ statuses: prev }, status).statuses);
    setPage(0);
  };

  const clearProjectScope = () => {
    setSearchParams(
      (prev) => {
        prev.delete(PROJECT_PARAM);
        return prev;
      },
      { replace: true },
    );
    setPage(0);
  };

  const handleOpenPO = (id: string) => {
    setSelectedPOId(id);
    setModalOpen(true);
  };

  const handleCloseModal = () => {
    setModalOpen(false);
    setSelectedPOId(null);
    // Drop the deep link so a reload lands on the table, not back on the PO just closed.
    if (searchParams.has('po')) {
      setSearchParams(
        (prev) => {
          prev.delete('po');
          return prev;
        },
        { replace: true },
      );
    }
  };

  const handleRefetch = () => {
    refetchPage();
    refetchStats();
    if (selectedPOId) refetchSelected();
  };

  const handleSyncGpPos = async () => {
    try {
      const resp = await syncGpPos();
      const r = (resp.data as { syncGpPos?: { mode: string; created: number; updated: number; backfillDone: boolean } })?.syncGpPos;
      if (r) {
        const msg =
          r.mode === 'unsupported'
            ? 'The connected relay does not support PO mirroring yet - update the relay.'
            : r.mode === 'queued'
              ? 'GP sync queued - the open-PO refresh runs in the background at the paced rate; the register updates as pages land.'
              : `GP sync (${r.mode}): ${r.created} added, ${r.updated} updated${r.backfillDone ? '' : ' - backfill still running'}.`;
        showToast(msg, r.mode === 'unsupported' ? 'warning' : r.mode === 'queued' ? 'info' : 'success');
      }
      handleRefetch();
    } catch (e) {
      const message =
        e instanceof CombinedGraphQLErrors ? e.errors[0]?.message : e instanceof Error ? e.message : 'GP sync failed';
      showToast(message ?? 'GP sync failed', 'error');
    }
  };

  // --- Render ---

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, mb: 2 }}>
        {/* Whose purchase orders these are, beside the title rather than under it so the answer
            costs no vertical space: the one GP company every row belongs to. #845: a UC NEXUS ADMIN
            works in one company at a time too, so they are told theirs rather than "All companies",
            and the table's Company column, which only ever repeated it, is gone. */}
        <Box
          sx={{
            flex: 1,
            minWidth: 0,
            display: 'flex',
            alignItems: 'baseline',
            flexWrap: 'wrap',
            columnGap: 1.25,
          }}
        >
          <Typography variant="h5">Purchase Orders</Typography>
          <Typography component="div" variant="body2" color="text.secondary" sx={{ minWidth: 0 }}>
            {company && <GpCompanyLabel code={company} gpCompanies={relay.gpCompanies} />}
          </Typography>
        </Box>
        <RelayStatusChip
          connected={relay.connected}
          unreachable={relay.unreachable}
          companies={relay.companies}
          gpCompanies={relay.gpCompanies}
        />
        {/* #744: everyone who works the PO table may bring the mirror up to date. The server scopes
            the pass to the caller's own company, so this is never a cross-company action. */}
        <Button
          variant="outlined"
          size="small"
          startIcon={<RefreshCw {...ICON} />}
          onClick={handleSyncGpPos}
          disabled={syncing || !relayConnected}
        >
          {syncing ? 'Syncing…' : 'Sync from GP'}
        </Button>
        {/* #729: Document Settings is the PO MANAGER's, with the TENANT OWNER beside them - the
            same any-of the server enforces on updatePoDocumentSettings. */}
        {(ownsTenant || hasRole('PO Manager')) && (
          <Button
            variant="outlined"
            size="small"
            startIcon={<Settings {...ICON} />}
            onClick={() => navigate('/app/po/document-settings')}
          >
            Document Settings
          </Button>
        )}
        <Button
          variant="contained"
          size="small"
          startIcon={<Plus {...ICON} />}
          onClick={() => setChooserOpen(true)}
        >
          Create a PO
        </Button>
      </Box>

      {/* Status strip. Clicking a segment filters the table to that status (#316). Each box carries a
          caption naming who owns the statuses inside it (#682). */}
      <FadeIn>
        <StaggerList count={STAT_CARD_COUNT}>
          <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', alignItems: 'stretch', mb: 2.5 }}>
            {STAT_CARD_GROUPS.map((group) => (
              <Box
                key={group.caption}
                // #851: a search spans every status, so the strip steps back while one is typed - a
                // pressed segment is not narrowing the table in that moment. Still clickable: the
                // press applies again once the search is cleared.
                sx={{
                  minWidth: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  opacity: searchingAllStatuses ? 0.45 : 1,
                  transition: 'opacity 0.2s ease',
                }}
              >
                <Typography component="div" sx={{ ...microLabelSx, textAlign: 'center', mb: 0.5 }}>
                  {group.caption}
                </Typography>
                <Paper
                  variant="outlined"
                  sx={{
                    flex: 1,
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'stretch',
                    overflow: 'hidden',
                  }}
                >
                  {group.cards.map((card, i) => {
                    const active = isStatusCardActive({ statuses }, card.status);
                    const count = stats?.[card.key] ?? 0;
                    const zero = !statsLoading && count === 0;
                    return (
                      <StaggerItem key={card.key} style={{ display: 'flex' }}>
                        <ButtonBase
                          onClick={() => handleCardClick(card.status)}
                          aria-pressed={active}
                          aria-label={`Filter by ${card.label}`}
                          sx={{
                            display: 'flex',
                            alignItems: 'baseline',
                            gap: 0.75,
                            px: 2,
                            py: 1.25,
                            borderLeft: i === 0 ? 'none' : '1px solid',
                            borderLeftColor: 'divider',
                            // #739: the whole segment fills when it is the filter, not just a thin
                            // underline - a filtered table must read as filtered at a glance.
                            borderBottom: '3px solid',
                            borderBottomColor: active ? 'secondary.main' : 'transparent',
                            backgroundColor: active ? activeSegmentTint : 'transparent',
                            '&:hover': { backgroundColor: active ? activeSegmentTint : 'action.hover' },
                          }}
                        >
                          <Typography
                            component="span"
                            sx={{
                              ...tabularSx,
                              fontSize: '1.25rem',
                              fontWeight: 700,
                              lineHeight: 1,
                              color: zero ? 'text.secondary' : 'text.primary',
                              opacity: zero ? 0.6 : 1,
                            }}
                          >
                            {statsLoading ? '–' : <AnimatedNumber value={count} />}
                          </Typography>
                          <Typography
                            component="span"
                            sx={{
                              ...microLabelSx,
                              whiteSpace: 'nowrap',
                              color: active ? 'text.primary' : 'text.secondary',
                              fontWeight: active ? 800 : undefined,
                              opacity: zero ? 0.6 : 1,
                            }}
                          >
                            {card.label}
                          </Typography>
                        </ButtonBase>
                      </StaggerItem>
                    );
                  })}
                </Paper>
              </Box>
            ))}
            {/* Sits in the strip's own row, beside the boxes it explains, so it costs no height. */}
            {searchingAllStatuses && (
              <Typography
                variant="caption"
                color="text.secondary"
                role="status"
                sx={{ alignSelf: 'flex-end', pb: 1.5, minWidth: 0 }}
              >
                Searching all statuses
              </Typography>
            )}
          </Box>
        </StaggerList>
      </FadeIn>

      {/* #754: the PO registrations GP has not taken yet, on the table they belong to rather than
          only on the admin queue. It renders nothing while there are none. */}
      <GpWriteQueuePanel
        ops={HELD_PO_REGISTRATION_OPS}
        statuses={HELD_PO_REGISTRATION_STATUSES}
        compact
        heading="Held PO registrations"
      />

      {/* Filter bar: search reaches full history, projects included (#851); origin narrows it, and a
          link's project scope shows as a chip. Server-driven. */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, mb: 1.5, alignItems: 'center' }}>
        <TextField
          size="small"
          placeholder="Search PO #, request #, vendor, or project…"
          inputProps={{ 'aria-label': 'Search purchase orders' }}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search {...ICON} />
              </InputAdornment>
            ),
          }}
          sx={{ flex: 1, minWidth: 260 }}
        />
        {/* #851: the project picker is gone - the search box finds a project by number or name. A
            link that opens the table on one project (the project detail page) shows that scope here,
            and removing the chip lifts it. */}
        {projectId && (
          <Chip
            size="small"
            variant="outlined"
            label={
              <Box component="span" sx={{ display: 'flex', gap: 0.75, minWidth: 0 }}>
                <Box component="span" sx={monoSx}>
                  {projectsById.get(projectId)?.projectId ?? 'Project'}
                </Box>
                {projectsById.get(projectId)?.description && (
                  <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {projectsById.get(projectId)?.description}
                  </Box>
                )}
              </Box>
            }
            title={projectsById.get(projectId)?.description ?? undefined}
            onDelete={clearProjectScope}
            sx={{ maxWidth: 320, minWidth: 0 }}
          />
        )}
        <ToggleButtonGroup
          size="small"
          exclusive
          value={origin}
          onChange={(_e, v) => {
            if (v) {
              setOrigin(v as OriginFilter);
              setPage(0);
            }
          }}
          aria-label="Filter by origin"
        >
          <ToggleButton value="ALL">All</ToggleButton>
          <ToggleButton value="NEXUS">Nexus</ToggleButton>
          <ToggleButton value="GP">GP</ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {/* PO Table */}
      <Box ref={tableRef} sx={{ minWidth: 0 }}>
        <FitTable
          storageKey="po-table"
          columns={poTableColumns(sort, handleSortClick)}
          footer={
            <TablePagination
              component="div"
              count={totalCount}
              page={page}
              onPageChange={(_e, p) => setPage(p)}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={(e) => {
                setRowsPerPage(parseInt(e.target.value, 10));
                setPage(0);
              }}
              rowsPerPageOptions={ROWS_PER_PAGE_OPTIONS}
            />
          }
        >
          {pageLoading && (
            <TableRow>
              <TableCell colSpan={PO_TABLE_COLUMN_COUNT} align="center" sx={{ py: 4 }}>
                <CircularProgress size={24} />
              </TableCell>
            </TableRow>
          )}
          {!pageLoading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={PO_TABLE_COLUMN_COUNT} align="center" sx={{ py: 4 }}>
                <Typography variant="body2" color="text.secondary">
                  No purchase orders match the current filters.
                </Typography>
              </TableCell>
            </TableRow>
          )}
          {!pageLoading &&
            rows.map((po) => (
              <POTableRow
                key={po.id}
                po={po}
                projectNumber={projectNumberOf(po)}
                projectName={projectNameOf(po)}
                onOpen={() => handleOpenPO(po.id)}
                gpWriteQueued={queuedPoIds.has(po.id)}
                highlighted={highlightIds.has(po.id)}
              />
            ))}
        </FitTable>
      </Box>

      {/* Detail Modal - the selected PO's full detail, fetched by id. The modal opens the instant a
          row is clicked so the click never reads as dead: a spinner shows while the PO loads, then
          the full detail, and a failed or missing PO surfaces its own message instead of nothing. */}
      {modalOpen &&
        (selectedPO ? (
          <PODetailModal
            open={modalOpen}
            po={selectedPO}
            onClose={handleCloseModal}
            onRefetch={handleRefetch}
            relayConnected={relayConnected}
            registrationQueued={queuedPoIds.has(selectedPO.id)}
          />
        ) : (
          <Modal open title="Purchase Order" onClose={handleCloseModal} maxWidth="lg">
            {selectedLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
                <CircularProgress />
              </Box>
            ) : (
              <Alert severity={selectedError ? 'error' : 'info'} sx={{ my: 1 }}>
                {selectedError
                  ? `Could not load this purchase order: ${selectedError.message}`
                  : 'This purchase order could not be found. It may have been cancelled or removed.'}
              </Alert>
            )}
          </Modal>
        ))}

      <CreatePOChooser
        open={chooserOpen}
        onClose={() => setChooserOpen(false)}
        onFromSchedule={() => {
          setChooserOpen(false);
          navigate('/app/import?purpose=po');
        }}
        onFromHardware={() => {
          setChooserOpen(false);
          navigate('/app/import?purpose=po&mode=hardware');
        }}
        onManual={() => {
          setChooserOpen(false);
          setCreateOpen(true);
        }}
      />

      <GpPurchaseOrderDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmitted={() => {
          setCreateOpen(false);
          handleRefetch();
        }}
        // #702: a PO that reached GP and was read back opens on its own detail, rather than leaving
        // the person to find the row they just raised in the PO table.
        onRegistered={(id) => {
          setCreateOpen(false);
          handleRefetch();
          handleOpenPO(id);
        }}
        relayConnected={relayConnected}
      />
    </Box>
  );
}

export default function POModule() {
  return (
    <Routes>
      <Route index element={<POListPage />} />
      <Route path="document-settings" element={<PODocumentSettingsPage />} />
    </Routes>
  );
}
