import { useState, useMemo } from 'react';
import {
  Alert,
  Box,
  Typography,
  ButtonBase,
  Chip,
  Button,
  Paper,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  TableSortLabel,
  IconButton,
  Collapse,
  CircularProgress,
  TextField,
  Select,
  MenuItem,
  Checkbox,
  ListItemText,
  Tooltip,
  Autocomplete,
  createFilterOptions,
} from '@mui/material';
import {
  Plus,
  ChevronRight,
  ChevronsUpDown,
  ChevronsDownUp,
  ClipboardPlus,
  Settings,
} from 'lucide-react';
import { motion } from 'motion/react';
import { useQuery } from '@apollo/client/react';
import { GET_PURCHASE_ORDERS, GET_PO_STATISTICS, GET_MY_RECEIVE_DECISIONS } from '../../graphql/po';
import { GET_GP_OUTBOX } from '../../graphql/shared';
import { GET_PROJECTS } from '../../graphql/shared';
import type { Project } from '../../types/project';
import PODetailModal from './PODetailModal';
import GpPurchaseOrderDialog from './GpPurchaseOrderDialog';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { useRelayStatus } from '../../relay/useRelayStatus';
import { poVendorName } from './poVendorName';
import { PO_STATUS_VALUES, formatPoStatus, poStatusChipColor } from './poStatus';
import { isStatusCardActive, toggleStatusCard } from './statusCardFilter';
import { Routes, Route, useNavigate } from 'react-router-dom';
import { useIdentity } from '../../hooks/useIdentity';
import PODocumentSettingsPage from './PODocumentSettingsPage';
import ReceiveDecisionsPage from './ReceiveDecisionsPage';
import { monoSx, tabularSx, microLabelSx } from '../../theme';
import { AnimatedNumber, FadeIn, StaggerItem, StaggerList, springs } from '../../motion';
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

export interface PurchaseOrder {
  id: string;
  poNumber: string | null;
  requestNumber: string;
  projectId: string | null;
  status: string;
  gpCompany: string | null;
  gpVendorId: string | null;
  vendorNameSnapshot: string | null;
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

// `status` is the po_status the segment filters the table down to when clicked (#316); null on Total,
// which clears the status filter instead. Clicking the already-active segment clears it too, so the
// strip doubles as the status filter and never traps you in a filtered view with no way back.
//
// Rendered as ONE compact strip rather than seven tiles: the counts are a readout, and a grid of tiles
// spent a third of the page saying "0" six times. Total leads; a zero count is dimmed so the eye lands
// on the statuses that actually have POs in them.
const STAT_CARDS: { label: string; key: keyof POStatistics; status: string | null }[] = [
  { label: 'Total', key: 'total', status: null },
  { label: 'Draft', key: 'draft', status: 'DRAFT' },
  { label: 'GP-Registered', key: 'gpRegistered', status: 'GP_REGISTERED' },
  { label: 'Vendor Confirmed', key: 'vendorConfirmed', status: 'VENDOR_CONFIRMED' },
  { label: 'Partially Received', key: 'partiallyReceived', status: 'PARTIALLY_RECEIVED' },
  { label: 'Closed', key: 'closed', status: 'CLOSED' },
  { label: 'Cancelled', key: 'cancelled', status: 'CANCELLED' },
];

// --- Sort + filter state ---

type SortField =
  | 'projectNumber'
  | 'projectName'
  | 'poNumber'
  | 'status'
  | 'vendor'
  | 'createdAt'
  | 'orderedAt'
  | 'itemsCount';

interface SortState {
  field: SortField | null;
  direction: 'asc' | 'desc';
}

interface FilterState {
  projectIds: Set<string>;
  poSearch: string;
  statuses: Set<string>;
  vendorSearch: string;
  createdFrom: string;
  createdTo: string;
  orderedFrom: string;
  orderedTo: string;
  itemsMin: string;
}

const EMPTY_FILTER_STATE: FilterState = {
  projectIds: new Set(),
  poSearch: '',
  statuses: new Set(),
  vendorSearch: '',
  createdFrom: '',
  createdTo: '',
  orderedFrom: '',
  orderedTo: '',
  itemsMin: '',
};

function poDisplayId(po: PurchaseOrder): string {
  return po.poNumber ?? po.requestNumber;
}

// Project columns (issue: PO list is now all-projects). POs carry only projectId (a UUID); the human
// project number + name come from the projects list, joined client-side via this map.
type ProjectsById = Map<string, Project>;

function poProjectNumber(po: PurchaseOrder, projectsById: ProjectsById): string {
  if (!po.projectId) return '';
  return projectsById.get(po.projectId)?.projectId ?? '';
}

function poProjectName(po: PurchaseOrder, projectsById: ProjectsById): string {
  if (!po.projectId) return '';
  const p = projectsById.get(po.projectId);
  return p?.description || p?.projectId || '';
}

function matchesFilter(po: PurchaseOrder, f: FilterState): boolean {
  if (f.projectIds.size > 0) {
    if (!po.projectId || !f.projectIds.has(po.projectId)) return false;
  }
  if (f.poSearch) {
    if (!poDisplayId(po).toLowerCase().includes(f.poSearch.toLowerCase())) return false;
  }
  if (f.statuses.size > 0 && !f.statuses.has(po.status)) return false;
  if (f.vendorSearch) {
    if (!poVendorName(po).toLowerCase().includes(f.vendorSearch.toLowerCase())) return false;
  }
  if (f.createdFrom || f.createdTo) {
    const d = po.createdAt.substring(0, 10);
    if (f.createdFrom && d < f.createdFrom) return false;
    if (f.createdTo && d > f.createdTo) return false;
  }
  if (f.orderedFrom || f.orderedTo) {
    if (!po.orderedAt) return false;
    const d = po.orderedAt.substring(0, 10);
    if (f.orderedFrom && d < f.orderedFrom) return false;
    if (f.orderedTo && d > f.orderedTo) return false;
  }
  if (f.itemsMin) {
    const min = parseInt(f.itemsMin, 10);
    if (Number.isFinite(min) && (po.lineItems?.length ?? 0) < min) return false;
  }
  return true;
}

function comparePOs(
  a: PurchaseOrder,
  b: PurchaseOrder,
  sort: SortState,
  projectsById: ProjectsById,
): number {
  if (!sort.field) return 0;
  const dir = sort.direction === 'asc' ? 1 : -1;
  let av: string | number = 0;
  let bv: string | number = 0;
  let aNull = false;
  let bNull = false;
  switch (sort.field) {
    case 'projectNumber':
      av = poProjectNumber(a, projectsById).toLowerCase();
      bv = poProjectNumber(b, projectsById).toLowerCase();
      aNull = !av;
      bNull = !bv;
      break;
    case 'projectName':
      av = poProjectName(a, projectsById).toLowerCase();
      bv = poProjectName(b, projectsById).toLowerCase();
      aNull = !av;
      bNull = !bv;
      break;
    case 'poNumber':
      av = poDisplayId(a).toLowerCase();
      bv = poDisplayId(b).toLowerCase();
      break;
    case 'status':
      av = a.status;
      bv = b.status;
      break;
    case 'vendor':
      av = poVendorName(a).toLowerCase();
      bv = poVendorName(b).toLowerCase();
      aNull = !av;
      bNull = !bv;
      break;
    case 'createdAt':
      av = a.createdAt;
      bv = b.createdAt;
      break;
    case 'orderedAt':
      av = a.orderedAt ?? '';
      bv = b.orderedAt ?? '';
      aNull = !a.orderedAt;
      bNull = !b.orderedAt;
      break;
    case 'itemsCount':
      av = a.lineItems?.length ?? 0;
      bv = b.lineItems?.length ?? 0;
      break;
  }
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;
  if (av < bv) return -1 * dir;
  if (av > bv) return 1 * dir;
  return 0;
}

// --- Line items mini-table (rendered inside an expanded row) ---

interface POLineItemsMiniTableProps {
  lineItems: POLineItem[];
  hasReceives: boolean;
}

function POLineItemsMiniTable({ lineItems, hasReceives }: POLineItemsMiniTableProps) {
  if (lineItems.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No line items.
      </Typography>
    );
  }
  return (
    <Table size="small" sx={{ bgcolor: 'background.paper' }}>
      <TableHead>
        <TableRow>
          <TableCell>Product Code</TableCell>
          <TableCell>Order As</TableCell>
          <TableCell>Hardware Category</TableCell>
          <TableCell align="right">Ordered Qty</TableCell>
          {hasReceives && <TableCell align="right">Received Qty</TableCell>}
          <TableCell align="right">Unit Cost</TableCell>
          <TableCell align="right">Line Total</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {lineItems.map((li) => (
          <TableRow key={li.id}>
            <TableCell sx={monoSx}>{li.productCode}</TableCell>
            <TableCell sx={li.orderAs ? monoSx : { color: 'text.disabled' }}>
              {li.orderAs || '—'}
            </TableCell>
            <TableCell>{li.hardwareCategory}</TableCell>
            <TableCell align="right" sx={tabularSx}>{li.orderedQuantity}</TableCell>
            {hasReceives && (
              <TableCell align="right" sx={tabularSx}>{li.receivedQuantity}</TableCell>
            )}
            <TableCell align="right" sx={tabularSx}>${(li.unitCost ?? 0).toFixed(2)}</TableCell>
            <TableCell align="right" sx={tabularSx}>
              ${((li.orderedQuantity ?? 0) * (li.unitCost ?? 0)).toFixed(2)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// --- Sortable column header ---

interface SortHeaderProps {
  field: SortField;
  label: string;
  align?: 'left' | 'right';
  // Hug the content instead of sharing the leftover width. Every column hugs except Vendor, which
  // takes the remainder - vendor names are the one value here long enough to want the room.
  hug?: boolean;
  sortState: SortState;
  onSort: (field: SortField) => void;
}

function SortHeader({ field, label, align = 'left', hug = true, sortState, onSort }: SortHeaderProps) {
  const active = sortState.field === field;
  return (
    <TableCell
      align={align}
      sortDirection={active ? sortState.direction : false}
      sx={hug ? { width: '1%', whiteSpace: 'nowrap' } : undefined}
    >
      <TableSortLabel
        active={active}
        direction={active ? sortState.direction : 'asc'}
        onClick={() => onSort(field)}
      >
        {label}
      </TableSortLabel>
    </TableCell>
  );
}

// --- Filter row ---

// Match projects by both number and name so typing either narrows the list.
const projectFilterOptions = createFilterOptions<Project>({
  stringify: (p) => `${p.projectId} ${p.description ?? ''}`,
});

interface FilterRowProps {
  filterState: FilterState;
  onChange: (updater: (prev: FilterState) => FilterState) => void;
  projects: Project[];
}

function FilterRow({ filterState, onChange, projects }: FilterRowProps) {
  return (
    <TableRow>
      <TableCell sx={{ width: 48 }} />
      {/* Spans both project columns (# and name) — one selector filters by project. */}
      <TableCell colSpan={2}>
        <Autocomplete
          multiple
          size="small"
          options={projects}
          value={projects.filter((p) => filterState.projectIds.has(p.id))}
          onChange={(_e, selected) =>
            onChange((s) => ({ ...s, projectIds: new Set(selected.map((p) => p.id)) }))
          }
          disableCloseOnSelect
          limitTags={2}
          filterOptions={projectFilterOptions}
          getOptionLabel={(p) => p.description || p.projectId}
          isOptionEqualToValue={(a, b) => a.id === b.id}
          renderOption={(props, option, { selected }) => {
            const { key, ...liProps } = props as typeof props & { key: string };
            return (
              <li key={key} {...liProps}>
                <Checkbox size="small" checked={selected} sx={{ mr: 1 }} />
                <ListItemText
                  primary={option.description || option.projectId}
                  secondary={option.description ? `#${option.projectId}` : undefined}
                />
              </li>
            );
          }}
          renderInput={(params) => (
            <TextField
              {...params}
              placeholder={filterState.projectIds.size === 0 ? 'All projects' : undefined}
              inputProps={{ ...params.inputProps, 'aria-label': 'Filter by project' }}
            />
          )}
          sx={{ minWidth: 200 }}
        />
      </TableCell>
      <TableCell>
        <TextField
          size="small"
          placeholder="Search…"
          value={filterState.poSearch}
          onChange={(e) => onChange((s) => ({ ...s, poSearch: e.target.value }))}
          fullWidth
        />
      </TableCell>
      <TableCell>
        <Select
          size="small"
          multiple
          displayEmpty
          value={Array.from(filterState.statuses)}
          onChange={(e) => {
            const v = e.target.value as string[];
            onChange((s) => ({ ...s, statuses: new Set(v) }));
          }}
          renderValue={(selected) => {
            if ((selected as string[]).length === 0) {
              return (
                <Typography variant="body2" color="text.secondary">
                  All
                </Typography>
              );
            }
            return (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.3 }}>
                {(selected as string[]).map((s) => (
                  <Chip
                    key={s}
                    label={formatPoStatus(s)}
                    color={poStatusChipColor(s)}
                    size="small"
                  />
                ))}
              </Box>
            );
          }}
          fullWidth
        >
          {PO_STATUS_VALUES.map((s) => (
            <MenuItem key={s} value={s}>
              <Checkbox checked={filterState.statuses.has(s)} size="small" />
              <ListItemText primary={formatPoStatus(s)} />
            </MenuItem>
          ))}
        </Select>
      </TableCell>
      <TableCell>
        <TextField
          size="small"
          placeholder="Search…"
          value={filterState.vendorSearch}
          onChange={(e) => onChange((s) => ({ ...s, vendorSearch: e.target.value }))}
          fullWidth
        />
      </TableCell>
      <TableCell>
        {/* A bare pair of date boxes gave no clue which end was which. The aria-labels stay for
            assistive tech; the From/To eyebrows say the same thing on screen. */}
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          <Typography component="span" sx={{ ...microLabelSx, flexShrink: 0 }}>
            From
          </Typography>
          <TextField
            size="small"
            type="date"
            value={filterState.createdFrom}
            onChange={(e) => onChange((s) => ({ ...s, createdFrom: e.target.value }))}
            inputProps={{ 'aria-label': 'Created from' }}
            sx={{ flex: 1 }}
          />
          <Typography component="span" sx={{ ...microLabelSx, flexShrink: 0 }}>
            To
          </Typography>
          <TextField
            size="small"
            type="date"
            value={filterState.createdTo}
            onChange={(e) => onChange((s) => ({ ...s, createdTo: e.target.value }))}
            inputProps={{ 'aria-label': 'Created to' }}
            sx={{ flex: 1 }}
          />
        </Box>
      </TableCell>
      <TableCell>
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          <Typography component="span" sx={{ ...microLabelSx, flexShrink: 0 }}>
            From
          </Typography>
          <TextField
            size="small"
            type="date"
            value={filterState.orderedFrom}
            onChange={(e) => onChange((s) => ({ ...s, orderedFrom: e.target.value }))}
            inputProps={{ 'aria-label': 'Ordered from' }}
            sx={{ flex: 1 }}
          />
          <Typography component="span" sx={{ ...microLabelSx, flexShrink: 0 }}>
            To
          </Typography>
          <TextField
            size="small"
            type="date"
            value={filterState.orderedTo}
            onChange={(e) => onChange((s) => ({ ...s, orderedTo: e.target.value }))}
            inputProps={{ 'aria-label': 'Ordered to' }}
            sx={{ flex: 1 }}
          />
        </Box>
      </TableCell>
      <TableCell align="right">
        <TextField
          size="small"
          type="number"
          placeholder="≥"
          value={filterState.itemsMin}
          onChange={(e) => onChange((s) => ({ ...s, itemsMin: e.target.value }))}
          inputProps={{ min: 0, 'aria-label': 'Minimum items' }}
          sx={{ width: 90 }}
        />
      </TableCell>
      <TableCell />
    </TableRow>
  );
}

// --- Single PO row + collapsible line-item panel ---

const PO_TABLE_COLUMN_COUNT = 10;

interface POTableRowProps {
  po: PurchaseOrder;
  projectNumber: string;
  projectName: string;
  expanded: boolean;
  onToggle: () => void;
  onOpen: () => void;
  // #353 PR E: this PO has a GP write sitting on the outbox. Passed down rather than resolved per
  // row: a field on PurchaseOrder would make the All-Projects list an N+1.
  gpWriteQueued: boolean;
}

function POTableRow({
  po,
  projectNumber,
  projectName,
  expanded,
  onToggle,
  onOpen,
  gpWriteQueued,
}: POTableRowProps) {
  const hugSx = { width: '1%', whiteSpace: 'nowrap' as const };
  return (
    <>
      {/* The whole data row opens the PO. The leading cell is the expander and nothing else, so a
          click meant for "show me the lines" never turns into a modal. */}
      <TableRow
        hover
        onClick={onOpen}
        sx={{
          cursor: 'pointer',
          '& > *': { borderBottom: 'unset' },
          '&:hover .po-row-chevron': { color: 'text.primary' },
        }}
      >
        <TableCell
          sx={{ width: 48 }}
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
        >
          <IconButton
            size="small"
            aria-label={expanded ? 'Collapse line items' : 'Expand line items'}
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
        <TableCell sx={{ ...hugSx, ...monoSx }}>{projectNumber || '-'}</TableCell>
        <TableCell sx={hugSx}>
          <Typography variant="body2" noWrap title={projectName || undefined} sx={{ maxWidth: 240 }}>
            {projectName || '-'}
          </Typography>
        </TableCell>
        <TableCell sx={hugSx}>
          {po.poNumber ? (
            <Box component="span" sx={monoSx}>
              {po.poNumber}
            </Box>
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <Box component="span" sx={{ ...monoSx, color: 'text.secondary' }}>
                {po.requestNumber}
              </Box>
              <Chip
                label="Draft"
                size="small"
                variant="outlined"
                sx={{ height: 20, fontSize: '0.7rem' }}
              />
            </Box>
          )}
        </TableCell>
        <TableCell sx={hugSx}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
            <Chip
              label={formatPoStatus(po.status)}
              color={poStatusChipColor(po.status)}
              size="small"
            />
            {/* #353 PR E: the registration was accepted but has not reached GP yet, so the PO is
                still DRAFT. Saying so stops it reading as "nobody has done this". */}
            {gpWriteQueued && (
              <Tooltip title="Waiting for the GP relay. This will post automatically when it reconnects." arrow>
                <Chip label="GP registration queued" color="warning" size="small" variant="outlined" />
              </Tooltip>
            )}
            {/* #316: no Register in GP action here. A button sitting beside the status chip read as a
                second status ("why do Draft POs also have a Register in GP status?"). Registering is a
                deliberate act with a whole dialog behind it, so it lives on the PO itself - open the PO
                and register from there. */}
          </Box>
        </TableCell>
        <TableCell>{poVendorName(po) || '-'}</TableCell>
        <TableCell sx={{ ...hugSx, ...tabularSx }}>
          {parseServerDate(po.createdAt).toLocaleDateString()}
        </TableCell>
        <TableCell sx={{ ...hugSx, ...tabularSx }}>
          {po.orderedAt ? parseServerDate(po.orderedAt).toLocaleDateString() : '-'}
        </TableCell>
        <TableCell sx={{ ...hugSx, ...tabularSx }} align="right">
          {po.lineItems?.length ?? 0}
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
      <TableRow>
        <TableCell
          sx={{ p: 0, borderBottom: expanded ? undefined : 'none' }}
          colSpan={PO_TABLE_COLUMN_COUNT}
        >
          <Collapse in={expanded} timeout={220} unmountOnExit>
            <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
              <Typography component="h3" sx={{ ...microLabelSx, mb: 1 }}>
                Line Items
              </Typography>
              <POLineItemsMiniTable
                lineItems={po.lineItems}
                hasReceives={po.receiveRecords.length > 0}
              />
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
}

// --- Component ---

function POListPage() {
  const navigate = useNavigate();
  const { isAdmin } = useIdentity();
  const [selectedPOId, setSelectedPOId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER_STATE);
  const [sortState, setSortState] = useState<SortState>({ field: null, direction: 'asc' });

  // Relay presence is polled as the page loads (not when a dialog opens), so the user knows up front
  // whether GP actions work. Create PO is a GP-first flow, so it can't run when the relay is down.
  // This is the main PO page, so it polls continuously (no skip) - it's the single relay poller the
  // detail/create/register dialogs read through their relayConnected prop.
  const { connected: relayConnected } = useRelayStatus();

  // #353 PR E: which POs have a GP write still on the outbox. Read as ONE list query and joined onto
  // rows client-side on `entityKey` (`po:<id>`), deliberately not as a field on PurchaseOrder - a
  // per-row resolver would be an N+1 on this all-projects list, and converters must not query.
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

  // Shipments this user has to say where to put. Scoped to the caller server-side, so the count is
  // either zero or theirs.
  const { data: decisionsData } = useQuery<{ myReceiveDecisions: { id: string }[] }>(
    GET_MY_RECEIVE_DECISIONS,
    { fetchPolicy: 'cache-and-network' },
  );
  const pendingDecisionCount = decisionsData?.myReceiveDecisions?.length ?? 0;

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // --- Queries (all-projects view; per-project scoping is done via the table's project filter) ---

  const {
    data: statsData,
    loading: statsLoading,
    refetch: refetchStats,
  } = useQuery<{ poStatistics: POStatistics }>(GET_PO_STATISTICS);

  const {
    data: posData,
    loading: posLoading,
    refetch: refetchPOs,
  } = useQuery<{ purchaseOrders: PurchaseOrder[] }>(GET_PURCHASE_ORDERS, {
    fetchPolicy: 'cache-and-network',
  });

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);

  const stats = statsData?.poStatistics;
  const purchaseOrders = useMemo(
    () => posData?.purchaseOrders ?? [],
    [posData?.purchaseOrders],
  );
  const projects = useMemo(() => projectsData?.projects ?? [], [projectsData?.projects]);
  const projectsById = useMemo<ProjectsById>(
    () => new Map(projects.map((p) => [p.id, p])),
    [projects],
  );
  const selectedPO = purchaseOrders.find((po) => po.id === selectedPOId) ?? null;

  // --- Filter + sort ---

  const filteredAndSortedPOs = useMemo(() => {
    const filtered = purchaseOrders.filter((po) => matchesFilter(po, filterState));
    if (!sortState.field) return filtered;
    return [...filtered].sort((a, b) => comparePOs(a, b, sortState, projectsById));
  }, [purchaseOrders, filterState, sortState, projectsById]);

  const handleSortClick = (field: SortField) => {
    setSortState((prev) => {
      if (prev.field === field) {
        return { field, direction: prev.direction === 'asc' ? 'desc' : 'asc' };
      }
      return { field, direction: 'asc' };
    });
  };

  // --- Handlers ---

  const handleOpenPO = (id: string) => {
    setSelectedPOId(id);
    setModalOpen(true);
  };

  const handleExpandAll = () => {
    setExpandedIds(new Set(filteredAndSortedPOs.map((po) => po.id)));
  };

  const handleCollapseAll = () => {
    setExpandedIds(new Set());
  };

  const visibleExpandedCount = useMemo(
    () => filteredAndSortedPOs.filter((po) => expandedIds.has(po.id)).length,
    [filteredAndSortedPOs, expandedIds],
  );
  const allVisibleExpanded =
    filteredAndSortedPOs.length > 0 && visibleExpandedCount === filteredAndSortedPOs.length;
  const noneVisibleExpanded = visibleExpandedCount === 0;

  const handleCloseModal = () => {
    setModalOpen(false);
    setSelectedPOId(null);
  };

  const handleRefetch = () => {
    refetchPOs();
    refetchStats();
  };

  // --- Render ---

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, mb: 2 }}>
        <Typography variant="h5" sx={{ flex: 1 }}>
          Purchase Orders
        </Typography>
        <RelayStatusChip connected={relayConnected} />
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
        {/* #471: raising a PO off the hardware schedule used to be its own sidebar destination. It
            is an action of this module, so it is a button here - no role gate, because whoever can
            work this screen can raise one, and the schedule is what knows what is still owed. */}
        <Button
          variant="outlined"
          size="small"
          startIcon={<ClipboardPlus {...ICON} />}
          onClick={() => navigate('/app/import?purpose=po')}
        >
          Start a Request
        </Button>
        {/* Issue #256: creating a PO lands as a DRAFT (no GP involved), so no relay gating here -
            the relay is only needed later, to register the draft into GP. This is the screen's one
            filled accent: the thing you came here to do. */}
        <Button
          variant="contained"
          size="small"
          startIcon={<Plus {...ICON} />}
          onClick={() => setCreateOpen(true)}
        >
          Create PO
        </Button>
      </Box>

      {/* Hardware this user ordered has landed and is waiting on them to say where it goes. It sits
          above the status strip because it is the one thing on this page somebody else is blocked
          on - the PO list itself keeps until they have answered. */}
      {pendingDecisionCount > 0 && (
        <Alert
          severity="warning"
          sx={{ mb: 2.5 }}
          action={
            <Button color="inherit" size="small" onClick={() => navigate('/app/po/decisions')}>
              Review
            </Button>
          }
        >
          {pendingDecisionCount === 1
            ? '1 shipment is waiting on your keep-or-ship decision.'
            : `${pendingDecisionCount} shipments are waiting on your keep-or-ship decision.`}
        </Alert>
      )}

      {/* Status strip. Clicking a segment filters the table to that status (#316) - the count and the
          list it describes are the same thing, so reading one and then hunting the filter row for the
          other was busywork. Display-only borders are deliberately absent: the only edge here marks
          the segment that IS filtering the table. */}
      <FadeIn>
        <Paper
          variant="outlined"
          sx={{ mb: 2.5, display: 'flex', flexWrap: 'wrap', alignItems: 'stretch', overflow: 'hidden' }}
        >
          <StaggerList count={STAT_CARDS.length}>
            {STAT_CARDS.map((card, i) => {
              const active = isStatusCardActive(filterState, card.status);
              const count = stats?.[card.key] ?? 0;
              const zero = !statsLoading && count === 0;
              return (
                <StaggerItem key={card.key} style={{ display: 'flex' }}>
                  <ButtonBase
                    onClick={() => setFilterState((f) => toggleStatusCard(f, card.status))}
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
                        fontSize: '1.125rem',
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

      {/* Expand / Collapse controls */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, mb: 1 }}>
        <Button
          size="small"
          startIcon={<ChevronsUpDown {...ICON} />}
          onClick={handleExpandAll}
          disabled={posLoading || allVisibleExpanded}
        >
          Expand all
        </Button>
        <Button
          size="small"
          startIcon={<ChevronsDownUp {...ICON} />}
          onClick={handleCollapseAll}
          disabled={posLoading || noneVisibleExpanded}
        >
          Collapse all
        </Button>
      </Box>

      {/* PO Table */}
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 48 }} />
              <SortHeader
                field="projectNumber"
                label="Project #"
                sortState={sortState}
                onSort={handleSortClick}
              />
              <SortHeader
                field="projectName"
                label="Project"
                sortState={sortState}
                onSort={handleSortClick}
              />
              <SortHeader
                field="poNumber"
                label="PO / Request #"
                sortState={sortState}
                onSort={handleSortClick}
              />
              <SortHeader
                field="status"
                label="Status"
                sortState={sortState}
                onSort={handleSortClick}
              />
              <SortHeader
                field="vendor"
                label="Vendor"
                hug={false}
                sortState={sortState}
                onSort={handleSortClick}
              />
              <SortHeader
                field="createdAt"
                label="Creation Date"
                sortState={sortState}
                onSort={handleSortClick}
              />
              <SortHeader
                field="orderedAt"
                label="Order Date"
                sortState={sortState}
                onSort={handleSortClick}
              />
              <SortHeader
                field="itemsCount"
                label="Items"
                align="right"
                sortState={sortState}
                onSort={handleSortClick}
              />
              <TableCell sx={{ width: 44 }} />
            </TableRow>
            <FilterRow
              filterState={filterState}
              onChange={setFilterState}
              projects={projects}
            />
          </TableHead>
          <TableBody>
            {posLoading && (
              <TableRow>
                <TableCell colSpan={PO_TABLE_COLUMN_COUNT} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={24} />
                </TableCell>
              </TableRow>
            )}
            {!posLoading && filteredAndSortedPOs.length === 0 && (
              <TableRow>
                <TableCell colSpan={PO_TABLE_COLUMN_COUNT} align="center" sx={{ py: 4 }}>
                  <Typography variant="body2" color="text.secondary">
                    {purchaseOrders.length === 0
                      ? 'No purchase orders found.'
                      : 'No purchase orders match the current filters.'}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {!posLoading &&
              filteredAndSortedPOs.map((po) => (
                <POTableRow
                  key={po.id}
                  po={po}
                  projectNumber={poProjectNumber(po, projectsById)}
                  projectName={poProjectName(po, projectsById)}
                  expanded={expandedIds.has(po.id)}
                  onToggle={() => toggleExpand(po.id)}
                  onOpen={() => handleOpenPO(po.id)}
                  gpWriteQueued={queuedPoIds.has(po.id)}
                />
              ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Detail Modal */}
      {selectedPO && (
        <PODetailModal
          open={modalOpen}
          po={selectedPO}
          onClose={handleCloseModal}
          onRefetch={handleRefetch}
          relayConnected={relayConnected}
        />
      )}

      {/* Create PO Dialog (creates a brand-new PO directly in GP) */}
      <GpPurchaseOrderDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmitted={() => {
          setCreateOpen(false);
          handleRefetch();
        }}
        relayConnected={relayConnected}
      />
      {/* The register-a-Draft dialog is not mounted here any more (#316). It lives on PODetailModal,
          which is now the only way to reach it. */}
    </Box>
  );
}

export default function POModule() {
  return (
    <Routes>
      <Route index element={<POListPage />} />
      <Route path="document-settings" element={<PODocumentSettingsPage />} />
      {/* Scoped to the caller server-side, so no role gate: whoever raised a PO owes the answer,
          and that person may hold only the import role. */}
      <Route path="decisions" element={<ReceiveDecisionsPage />} />
    </Routes>
  );
}
