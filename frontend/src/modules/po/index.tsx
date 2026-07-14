import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Grid,
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
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import AddIcon from '@mui/icons-material/Add';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight';
import UnfoldMoreIcon from '@mui/icons-material/UnfoldMore';
import UnfoldLessIcon from '@mui/icons-material/UnfoldLess';
import { useQuery } from '@apollo/client/react';
import { GET_PURCHASE_ORDERS, GET_PO_STATISTICS } from '../../graphql/queries';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import type { Project } from '../../types/project';
import PODetailModal from './PODetailModal';
import GpPurchaseOrderDialog from './GpPurchaseOrderDialog';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { useRelayStatus } from '../../relay/useRelayStatus';
import { poVendorName } from './poVendorName';
import { PO_STATUS_VALUES, formatPoStatus, poStatusChipColor } from './poStatus';
import { Routes, Route, useNavigate } from 'react-router-dom';
import SettingsIcon from '@mui/icons-material/Settings';
import { useIdentity } from '../../hooks/useIdentity';
import PODocumentSettingsPage from './PODocumentSettingsPage';

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

export interface VendorRef {
  id: string;
  name: string;
  contactName: string | null;
  email: string | null;
  phone: string | null;
}

export interface PODocumentData {
  id: string;
  poId: string;
  vendorAddress: string | null;
  buyerName: string | null;
  currency: string;
  shipTo: string | null;
  shippingMethod: string | null;
  proposalNumber: string | null;
  freight: number;
  miscellaneous: number;
  taxAmount: number;
  taxLabel: string;
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
  vendor: VendorRef | null;
  vendorQuoteNumber: string | null;
  notes: string | null;
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


// --- Stat card config (display-only) ---

const STAT_CARDS: { label: string; key: keyof POStatistics }[] = [
  { label: 'Total', key: 'total' },
  { label: 'Draft', key: 'draft' },
  { label: 'GP-Registered', key: 'gpRegistered' },
  { label: 'Vendor Confirmed', key: 'vendorConfirmed' },
  { label: 'Partially Received', key: 'partiallyReceived' },
  { label: 'Closed', key: 'closed' },
  { label: 'Cancelled', key: 'cancelled' },
];

// --- Sort + filter state ---

type SortField = 'poNumber' | 'status' | 'vendor' | 'orderedAt' | 'itemsCount';

interface SortState {
  field: SortField | null;
  direction: 'asc' | 'desc';
}

interface FilterState {
  poSearch: string;
  statuses: Set<string>;
  vendorSearch: string;
  orderedFrom: string;
  orderedTo: string;
  itemsMin: string;
}

const EMPTY_FILTER_STATE: FilterState = {
  poSearch: '',
  statuses: new Set(),
  vendorSearch: '',
  orderedFrom: '',
  orderedTo: '',
  itemsMin: '',
};

function poDisplayId(po: PurchaseOrder): string {
  return po.poNumber ?? po.requestNumber;
}

function matchesFilter(po: PurchaseOrder, f: FilterState): boolean {
  if (f.poSearch) {
    if (!poDisplayId(po).toLowerCase().includes(f.poSearch.toLowerCase())) return false;
  }
  if (f.statuses.size > 0 && !f.statuses.has(po.status)) return false;
  if (f.vendorSearch) {
    if (!poVendorName(po).toLowerCase().includes(f.vendorSearch.toLowerCase())) return false;
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

function comparePOs(a: PurchaseOrder, b: PurchaseOrder, sort: SortState): number {
  if (!sort.field) return 0;
  const dir = sort.direction === 'asc' ? 1 : -1;
  let av: string | number = 0;
  let bv: string | number = 0;
  let aNull = false;
  let bNull = false;
  switch (sort.field) {
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
            <TableCell>{li.productCode}</TableCell>
            <TableCell>{li.orderAs || '—'}</TableCell>
            <TableCell>{li.hardwareCategory}</TableCell>
            <TableCell align="right">{li.orderedQuantity}</TableCell>
            {hasReceives && <TableCell align="right">{li.receivedQuantity}</TableCell>}
            <TableCell align="right">${(li.unitCost ?? 0).toFixed(2)}</TableCell>
            <TableCell align="right">
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
  sortState: SortState;
  onSort: (field: SortField) => void;
}

function SortHeader({ field, label, align = 'left', sortState, onSort }: SortHeaderProps) {
  const active = sortState.field === field;
  return (
    <TableCell
      align={align}
      sortDirection={active ? sortState.direction : false}
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

interface FilterRowProps {
  filterState: FilterState;
  onChange: (updater: (prev: FilterState) => FilterState) => void;
}

function FilterRow({ filterState, onChange }: FilterRowProps) {
  return (
    <TableRow>
      <TableCell sx={{ width: 48 }} />
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
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <TextField
            size="small"
            type="date"
            value={filterState.orderedFrom}
            onChange={(e) => onChange((s) => ({ ...s, orderedFrom: e.target.value }))}
            inputProps={{ 'aria-label': 'Ordered from' }}
            sx={{ flex: 1 }}
          />
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
    </TableRow>
  );
}

// --- Single PO row + collapsible line-item panel ---

const PO_TABLE_COLUMN_COUNT = 6;

interface POTableRowProps {
  po: PurchaseOrder;
  expanded: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onRegister: () => void;
  relayConnected: boolean;
}

function POTableRow({ po, expanded, onToggle, onOpen, onRegister, relayConnected }: POTableRowProps) {
  const dataCellSx = { cursor: 'pointer' };
  return (
    <>
      <TableRow hover sx={{ '& > *': { borderBottom: 'unset' } }}>
        <TableCell sx={{ width: 48 }}>
          <IconButton
            size="small"
            aria-label={expanded ? 'Collapse line items' : 'Expand line items'}
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
          >
            {expanded ? <KeyboardArrowDownIcon /> : <KeyboardArrowRightIcon />}
          </IconButton>
        </TableCell>
        <TableCell sx={dataCellSx} onClick={onOpen}>
          {po.poNumber ? (
            po.poNumber
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Typography variant="body2" color="text.secondary">
                {po.requestNumber}
              </Typography>
              <Chip
                label="Draft"
                size="small"
                variant="outlined"
                sx={{ height: 20, fontSize: '0.7rem' }}
              />
            </Box>
          )}
        </TableCell>
        <TableCell sx={dataCellSx} onClick={onOpen}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
            <Chip
              label={formatPoStatus(po.status)}
              color={poStatusChipColor(po.status)}
              size="small"
            />
            {po.status === 'DRAFT' && (
              <Tooltip
                title={relayConnected ? '' : 'GP relay not detected on this machine - it must be running to register a PO'}
                arrow
              >
                <span>
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={!relayConnected}
                    onClick={(e) => {
                      e.stopPropagation();
                      onRegister();
                    }}
                    sx={{ py: 0, minHeight: 24, fontSize: '0.7rem' }}
                  >
                    Register in GP
                  </Button>
                </span>
              </Tooltip>
            )}
          </Box>
        </TableCell>
        <TableCell sx={dataCellSx} onClick={onOpen}>
          {poVendorName(po) || '-'}
        </TableCell>
        <TableCell sx={dataCellSx} onClick={onOpen}>
          {po.orderedAt ? new Date(po.orderedAt).toLocaleDateString() : '-'}
        </TableCell>
        <TableCell sx={dataCellSx} align="right" onClick={onOpen}>
          {po.lineItems?.length ?? 0}
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell
          sx={{ p: 0, borderBottom: expanded ? undefined : 'none' }}
          colSpan={PO_TABLE_COLUMN_COUNT}
        >
          <Collapse in={expanded} timeout="auto" unmountOnExit>
            <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
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
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>(null);
  const [selectedPOId, setSelectedPOId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [registerPO, setRegisterPO] = useState<PurchaseOrder | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER_STATE);
  const [sortState, setSortState] = useState<SortState>({ field: null, direction: 'asc' });

  // Relay presence is polled as the page loads (not when a dialog opens), so the user knows up front
  // whether GP actions work. Create PO is a GP-first flow, so it can't run when the relay is down.
  // This is the main PO page, so it polls continuously (no skip) - it's the single relay poller the
  // detail/create/register dialogs read through their relayConnected prop.
  const { connected: relayConnected } = useRelayStatus();

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const projectId = selectedProject && selectedProject !== 'all' ? selectedProject.id : undefined;

  // --- Queries ---

  const {
    data: statsData,
    loading: statsLoading,
    refetch: refetchStats,
  } = useQuery<{ poStatistics: POStatistics }>(GET_PO_STATISTICS, {
    variables: { projectId },
    skip: selectedProject === null,
  });

  const {
    data: posData,
    loading: posLoading,
    refetch: refetchPOs,
  } = useQuery<{ purchaseOrders: PurchaseOrder[] }>(GET_PURCHASE_ORDERS, {
    variables: { projectId },
    skip: selectedProject === null,
    fetchPolicy: 'cache-and-network',
  });

  const stats = statsData?.poStatistics;
  const purchaseOrders = useMemo(
    () => posData?.purchaseOrders ?? [],
    [posData?.purchaseOrders],
  );
  const selectedPO = purchaseOrders.find((po) => po.id === selectedPOId) ?? null;

  // --- Filter + sort ---

  const filteredAndSortedPOs = useMemo(() => {
    const filtered = purchaseOrders.filter((po) => matchesFilter(po, filterState));
    if (!sortState.field) return filtered;
    return [...filtered].sort((a, b) => comparePOs(a, b, sortState));
  }, [purchaseOrders, filterState, sortState]);

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

  // --- Landing page ---

  if (selectedProject === null) {
    return (
      <ProjectLandingPage
        title="Purchase Orders"
        onSelect={(p) => setSelectedProject(p === null ? 'all' : p)}
      />
    );
  }

  // --- Render ---

  const projectLabel =
    selectedProject === 'all' ? 'All Projects' : (selectedProject.description || selectedProject.projectId);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <Button
          size="small"
          startIcon={<ArrowBackIcon />}
          onClick={() => setSelectedProject(null)}
        >
          Projects
        </Button>
        <Typography variant="h5" sx={{ flex: 1 }}>
          Purchase Orders — {projectLabel}
        </Typography>
        <RelayStatusChip connected={relayConnected} />
        {isAdmin && (
          <Button
            size="small"
            startIcon={<SettingsIcon />}
            onClick={() => navigate('/app/po/document-settings')}
          >
            Document Settings
          </Button>
        )}
        <Tooltip
          title={relayConnected ? '' : 'GP relay not detected on this machine - it must be running to create a PO'}
          arrow
        >
          <span>
            <Button
              variant="contained"
              size="small"
              startIcon={<AddIcon />}
              onClick={() => setCreateOpen(true)}
              disabled={!relayConnected}
            >
              Create PO
            </Button>
          </span>
        </Tooltip>
      </Box>

      {/* Statistics Cards (display-only) */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {STAT_CARDS.map((card) => (
          <Grid key={card.key} size={{ xs: 6, sm: 4, md: 2 }}>
            <Card>
              <CardContent sx={{ textAlign: 'center', py: 2 }}>
                <Typography variant="h4" color="primary">
                  {statsLoading ? '-' : (stats?.[card.key] ?? 0)}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {card.label}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Expand / Collapse controls */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, mb: 1 }}>
        <Button
          size="small"
          startIcon={<UnfoldMoreIcon />}
          onClick={handleExpandAll}
          disabled={posLoading || allVisibleExpanded}
        >
          Expand all
        </Button>
        <Button
          size="small"
          startIcon={<UnfoldLessIcon />}
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
            </TableRow>
            <FilterRow
              filterState={filterState}
              onChange={setFilterState}
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
                  expanded={expandedIds.has(po.id)}
                  onToggle={() => toggleExpand(po.id)}
                  onOpen={() => handleOpenPO(po.id)}
                  onRegister={() => setRegisterPO(po)}
                  relayConnected={relayConnected === true}
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
        defaultProjectId={projectId}
        relayConnected={relayConnected}
      />

      {/* Register PO Dialog (registers an imported Draft into GP) */}
      <GpPurchaseOrderDialog
        open={!!registerPO}
        registerPo={registerPO}
        onClose={() => setRegisterPO(null)}
        onSubmitted={() => {
          setRegisterPO(null);
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
