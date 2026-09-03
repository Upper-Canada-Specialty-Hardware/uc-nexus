import { useState, useMemo, useEffect } from 'react';
import {
  Box,
  Typography,
  ButtonBase,
  Chip,
  Button,
  Alert,
  Paper,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  TableSortLabel,
  TablePagination,
  IconButton,
  CircularProgress,
  TextField,
  InputAdornment,
  Tooltip,
  Autocomplete,
  ToggleButton,
  ToggleButtonGroup,
  createFilterOptions,
} from '@mui/material';
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
import PODetailModal from './PODetailModal';
import GpPurchaseOrderDialog from './GpPurchaseOrderDialog';
import CreatePOChooser from './CreatePOChooser';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { useRelayStatus } from '../../relay/useRelayStatus';
import { formatPoStatus, poStatusChipColor } from './poStatus';
import { isStatusCardActive, toggleStatusCard } from './statusCardFilter';
import { Routes, Route, useNavigate } from 'react-router-dom';
import { useIdentity } from '../../hooks/useIdentity';
import PODocumentSettingsPage from './PODocumentSettingsPage';
import { useToast } from '../../components/Toast';
import { monoSx, tabularSx, microLabelSx } from '../../theme';
import { AnimatedNumber, FadeIn, StaggerItem, StaggerList } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';

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
  // GP POP10110.ORD this line maps to; present on registered/mirrored lines.
  gpLineOrd: number | null;
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
  projectId: string | null;
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
  status: string;
  origin: string;
  // #637: the tenant that owns the PO - the register's Company column. Present on a draft, which
  // gpCompany is not.
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
const STAT_CARDS: { label: string; key: keyof POStatistics; status: string | null }[] = [
  { label: 'Total', key: 'total', status: null },
  { label: 'Draft', key: 'draft', status: 'DRAFT' },
  { label: 'GP-Registered', key: 'gpRegistered', status: 'GP_REGISTERED' },
  { label: 'Vendor Confirmed', key: 'vendorConfirmed', status: 'VENDOR_CONFIRMED' },
  { label: 'Partially Received', key: 'partiallyReceived', status: 'PARTIALLY_RECEIVED' },
  { label: 'Closed', key: 'closed', status: 'CLOSED' },
  // Mirror-CANCELLED rows (deleted_at NULL) still count into Total, so without a segment for them the
  // strip would stop summing to Total and those rows would be unreachable by any status filter.
  { label: 'Cancelled', key: 'cancelled', status: 'CANCELLED' },
];

// The register defaults to the open work rather than the full company history the backfill loads:
// what is live and being acted on. Total (and the Cancelled/Closed segments) reach the rest.
const OPEN_STATUSES = ['GP_REGISTERED', 'VENDOR_CONFIRMED', 'PARTIALLY_RECEIVED'];

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

const projectFilterOptions = createFilterOptions<Project>({
  stringify: (p) => `${p.projectId} ${p.description ?? ''}`,
});

// --- Sortable column header ---

interface SortHeaderProps {
  field: SortField;
  label: string;
  align?: 'left' | 'right';
  hug?: boolean;
  sortState: SortState;
  onSort: (field: SortField) => void;
}

function SortHeader({ field, label, align = 'left', hug = true, sortState, onSort }: SortHeaderProps) {
  const active = sortState.field === field;
  return (
    <TableCell
      align={align}
      sortDirection={active ? sortState.dir : false}
      sx={hug ? { width: '1%', whiteSpace: 'nowrap' } : undefined}
    >
      <TableSortLabel
        active={active}
        direction={active ? sortState.dir : 'asc'}
        onClick={() => onSort(field)}
      >
        {label}
      </TableSortLabel>
    </TableCell>
  );
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
  // #637: only Admin/Manager sees more than one company's POs here, so only they get the column.
  showCompany: boolean;
}

function POTableRow({ po, projectNumber, projectName, onOpen, gpWriteQueued, showCompany }: POTableRowProps) {
  const hugSx = { width: '1%', whiteSpace: 'nowrap' as const };
  return (
    <TableRow
      hover
      onClick={onOpen}
      sx={{ cursor: 'pointer', '&:hover .po-row-chevron': { color: 'text.primary' } }}
    >
      {/* #632: one Project column - mono number over the truncated name - so the register fits
          1366px without the container growing an x-scroll. */}
      <TableCell sx={{ ...hugSx, maxWidth: 180 }}>
        <Box component="span" sx={{ ...monoSx, display: 'block' }}>
          {projectNumber || '-'}
        </Box>
        {projectName && (
          <Typography
            variant="caption"
            color="text.secondary"
            noWrap
            title={projectName}
            sx={{ display: 'block', minWidth: 0, maxWidth: 172 }}
          >
            {projectName}
          </Typography>
        )}
      </TableCell>
      {showCompany && (
        <TableCell sx={{ ...hugSx, ...monoSx, color: 'text.secondary' }}>{po.company}</TableCell>
      )}
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
            <Chip label="Draft" size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
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
      <TableCell sx={{ maxWidth: 0 }}>
        <Typography variant="body2" noWrap title={po.vendorNameSnapshot || undefined}>
          {po.vendorNameSnapshot || '-'}
        </Typography>
      </TableCell>
      <TableCell sx={{ ...hugSx, maxWidth: 150 }}>
        <Typography variant="body2" noWrap title={po.createdBy || undefined} sx={{ maxWidth: 142 }}>
          {po.createdBy || '-'}
        </Typography>
      </TableCell>
      <TableCell sx={{ ...hugSx, ...tabularSx }}>
        {parseServerDate(po.createdAt).toLocaleDateString()}
      </TableCell>
      <TableCell sx={{ ...hugSx, ...tabularSx }}>
        {po.orderedAt ? parseServerDate(po.orderedAt).toLocaleDateString() : '-'}
      </TableCell>
      <TableCell sx={{ ...hugSx, ...tabularSx }} align="right">
        {po.lineItemCount}
      </TableCell>
      {/* Says the row goes somewhere, and gives the keyboard the same door the mouse has. */}
      <TableCell sx={{ width: 44, py: 0 }} align="right">
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
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();
  const [selectedPOId, setSelectedPOId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [chooserOpen, setChooserOpen] = useState(false);

  // Server-driven filter / sort / page state.
  const [searchInput, setSearchInput] = useState('');
  const [committedSearch, setCommittedSearch] = useState('');
  const [statuses, setStatuses] = useState<Set<string>>(() => new Set(OPEN_STATUSES));
  const [origin, setOrigin] = useState<OriginFilter>('ALL');
  const [projectId, setProjectId] = useState<string | null>(null);
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

  const relay = useRelayStatus();
  const relayConnected = relay.connected;
  // #637: the register is the combined view for an admin - every company's POs at once - so the row
  // has to say which company's it is. A scoped caller only ever gets their own; no column needed.
  const columnCount = isAdmin ? PO_TABLE_COLUMN_COUNT + 1 : PO_TABLE_COLUMN_COUNT;

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

  const pageVariables = useMemo(
    () => ({
      search: committedSearch || null,
      statuses: statuses.size ? Array.from(statuses) : null,
      origin: origin === 'ALL' ? null : origin,
      projectId: projectId || null,
      sortField: sort.field,
      sortDir: sort.dir,
      limit: rowsPerPage,
      offset: page * rowsPerPage,
    }),
    [committedSearch, statuses, origin, projectId, sort, rowsPerPage, page],
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

  const projectNumberOf = (po: POListRow) => (po.projectId ? projectsById.get(po.projectId)?.projectId ?? '' : '');
  const projectNameOf = (po: POListRow) => {
    if (!po.projectId) return '';
    const p = projectsById.get(po.projectId);
    return p?.description || p?.projectId || '';
  };

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

  const handleOpenPO = (id: string) => {
    setSelectedPOId(id);
    setModalOpen(true);
  };

  const handleCloseModal = () => {
    setModalOpen(false);
    setSelectedPOId(null);
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
        <Typography variant="h5" sx={{ flex: 1 }}>
          Purchase Orders
        </Typography>
        <RelayStatusChip connected={relayConnected} companies={relay.companies} gpCompanies={relay.gpCompanies} />
        {isAdmin && (
          <Button
            variant="outlined"
            size="small"
            startIcon={<RefreshCw {...ICON} />}
            onClick={handleSyncGpPos}
            disabled={syncing || !relayConnected}
          >
            {syncing ? 'Syncing…' : 'Sync from GP'}
          </Button>
        )}
        {isAdmin && (
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

      {/* Status strip. Clicking a segment filters the table to that status (#316). */}
      <FadeIn>
        <Paper
          variant="outlined"
          sx={{ mb: 2.5, display: 'flex', flexWrap: 'wrap', alignItems: 'stretch', overflow: 'hidden' }}
        >
          <StaggerList count={STAT_CARDS.length}>
            {STAT_CARDS.map((card, i) => {
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
                      borderBottom: '2px solid',
                      borderBottomColor: active ? 'secondary.main' : 'transparent',
                      '&:hover': { backgroundColor: 'action.hover' },
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
                        opacity: zero ? 0.6 : 1,
                      }}
                    >
                      {card.label}
                    </Typography>
                  </ButtonBase>
                </StaggerItem>
              );
            })}
          </StaggerList>
        </Paper>
      </FadeIn>

      {/* Filter bar: search reaches full history; project + origin narrow it. Server-driven. */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, mb: 1.5, alignItems: 'center' }}>
        <TextField
          size="small"
          placeholder="Search PO #, request #, or vendor…"
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
        <Autocomplete
          size="small"
          options={projects}
          value={projects.find((p) => p.id === projectId) ?? null}
          onChange={(_e, selected) => {
            setProjectId(selected?.id ?? null);
            setPage(0);
          }}
          filterOptions={projectFilterOptions}
          getOptionLabel={(p) => p.description || p.projectId}
          isOptionEqualToValue={(a, b) => a.id === b.id}
          renderInput={(params) => (
            <TextField {...params} placeholder="All projects" inputProps={{ ...params.inputProps, 'aria-label': 'Filter by project' }} />
          )}
          sx={{ minWidth: 220 }}
        />
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
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: '1%', whiteSpace: 'nowrap' }}>Project</TableCell>
              {isAdmin && <TableCell sx={{ width: '1%', whiteSpace: 'nowrap' }}>Company</TableCell>}
              <SortHeader field="poNumber" label="PO / Request #" sortState={sort} onSort={handleSortClick} />
              <SortHeader field="status" label="Status" sortState={sort} onSort={handleSortClick} />
              <SortHeader field="vendor" label="Vendor" hug={false} sortState={sort} onSort={handleSortClick} />
              <TableCell sx={{ width: '1%', whiteSpace: 'nowrap' }}>Created By</TableCell>
              <SortHeader field="createdAt" label="Creation Date" sortState={sort} onSort={handleSortClick} />
              <SortHeader field="orderedAt" label="Order Date" sortState={sort} onSort={handleSortClick} />
              <TableCell align="right" sx={{ width: '1%', whiteSpace: 'nowrap' }}>
                Items
              </TableCell>
              <TableCell sx={{ width: 44 }} />
            </TableRow>
          </TableHead>
          <TableBody>
            {pageLoading && (
              <TableRow>
                <TableCell colSpan={columnCount} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={24} />
                </TableCell>
              </TableRow>
            )}
            {!pageLoading && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={columnCount} align="center" sx={{ py: 4 }}>
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
                  showCompany={isAdmin}
                />
              ))}
          </TableBody>
        </Table>
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
      </TableContainer>

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
