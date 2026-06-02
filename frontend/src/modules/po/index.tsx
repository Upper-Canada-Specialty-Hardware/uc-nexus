import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  CardActionArea,
  Grid,
  Chip,
  Tabs,
  Tab,
  Button,
  Paper,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  IconButton,
  Collapse,
  CircularProgress,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import AddIcon from '@mui/icons-material/Add';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight';
import { useQuery } from '@apollo/client/react';
import { GET_PURCHASE_ORDERS, GET_PO_STATISTICS } from '../../graphql/queries';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import type { Project } from '../../types/project';
import PODetailModal from './PODetailModal';
import CreatePODialog from './CreatePODialog';

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

export interface PurchaseOrder {
  id: string;
  poNumber: string | null;
  requestNumber: string;
  projectId: string | null;
  status: string;
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
}

interface POStatistics {
  total: number;
  draft: number;
  ordered: number;
  vendorConfirmed: number;
  partiallyReceived: number;
  closed: number;
  cancelled: number;
}

// --- Status config ---

type StatusFilter = '' | 'DRAFT' | 'ORDERED' | 'VENDOR_CONFIRMED' | 'PARTIALLY_RECEIVED' | 'CLOSED' | 'CANCELLED';

const STATUS_CHIP_COLOR: Record<string, 'default' | 'primary' | 'info' | 'warning' | 'success' | 'error'> = {
  DRAFT: 'default',
  ORDERED: 'primary',
  VENDOR_CONFIRMED: 'info',
  PARTIALLY_RECEIVED: 'warning',
  CLOSED: 'success',
  CANCELLED: 'error',
};

const TAB_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: 'All', value: '' },
  { label: 'Draft', value: 'DRAFT' },
  { label: 'Ordered', value: 'ORDERED' },
  { label: 'Vendor Confirmed', value: 'VENDOR_CONFIRMED' },
  { label: 'Partially Received', value: 'PARTIALLY_RECEIVED' },
  { label: 'Closed', value: 'CLOSED' },
  { label: 'Cancelled', value: 'CANCELLED' },
];

// --- Stat card config ---

interface StatCard {
  label: string;
  filter: StatusFilter;
  key: keyof POStatistics;
}

const STAT_CARDS: StatCard[] = [
  { label: 'Total', filter: '', key: 'total' },
  { label: 'Draft', filter: 'DRAFT', key: 'draft' },
  { label: 'Ordered', filter: 'ORDERED', key: 'ordered' },
  { label: 'Vendor Confirmed', filter: 'VENDOR_CONFIRMED', key: 'vendorConfirmed' },
  { label: 'Partially Received', filter: 'PARTIALLY_RECEIVED', key: 'partiallyReceived' },
  { label: 'Closed', filter: 'CLOSED', key: 'closed' },
  { label: 'Cancelled', filter: 'CANCELLED', key: 'cancelled' },
];

// --- Helpers ---

function formatStatus(status: string): string {
  return status
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
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

// --- Single PO row + collapsible line-item panel ---

const PO_TABLE_COLUMN_COUNT = 6;

interface POTableRowProps {
  po: PurchaseOrder;
  expanded: boolean;
  onToggle: () => void;
  onOpen: () => void;
}

function POTableRow({ po, expanded, onToggle, onOpen }: POTableRowProps) {
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
          <Chip
            label={formatStatus(po.status)}
            color={STATUS_CHIP_COLOR[po.status] ?? 'default'}
            size="small"
          />
        </TableCell>
        <TableCell sx={dataCellSx} onClick={onOpen}>
          {po.vendor?.name || '-'}
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

export default function POModule() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>(null);
  const [activeFilter, setActiveFilter] = useState<StatusFilter>('');
  const [selectedPOId, setSelectedPOId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const projectId = selectedProject && selectedProject !== 'all' ? selectedProject.id : undefined;

  const tabIndex = useMemo(
    () => TAB_FILTERS.findIndex((t) => t.value === activeFilter),
    [activeFilter],
  );

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
    variables: {
      projectId,
      status: activeFilter || undefined,
    },
    skip: selectedProject === null,
    fetchPolicy: 'cache-and-network',
  });

  const stats = statsData?.poStatistics;
  const purchaseOrders = posData?.purchaseOrders ?? [];
  const selectedPO = purchaseOrders.find((po) => po.id === selectedPOId) ?? null;

  // --- Handlers ---

  const handleCardClick = (filter: StatusFilter) => {
    setActiveFilter(filter);
  };

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setActiveFilter(TAB_FILTERS[newValue].value);
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
        <Button
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          onClick={() => setCreateOpen(true)}
        >
          Create PO
        </Button>
      </Box>

      {/* Statistics Cards */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {STAT_CARDS.map((card) => (
          <Grid key={card.key} size={{ xs: 6, sm: 4, md: 2 }}>
            <Card
              sx={{
                transition: 'box-shadow 0.2s',
                outline: activeFilter === card.filter ? '2px solid' : 'none',
                outlineColor: 'primary.main',
                '&:hover': { boxShadow: 4 },
              }}
            >
              <CardActionArea onClick={() => handleCardClick(card.filter)}>
                <CardContent sx={{ textAlign: 'center', py: 2 }}>
                  <Typography variant="h4" color="primary">
                    {statsLoading ? '-' : (stats?.[card.key] ?? 0)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {card.label}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Filter Tabs */}
      <Tabs value={tabIndex} onChange={handleTabChange} sx={{ mb: 2 }}>
        {TAB_FILTERS.map((tab) => (
          <Tab key={tab.value} label={tab.label} />
        ))}
      </Tabs>

      {/* PO Table */}
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 48 }} />
              <TableCell>PO / Request #</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Vendor</TableCell>
              <TableCell>Order Date</TableCell>
              <TableCell align="right">Items</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {posLoading && (
              <TableRow>
                <TableCell colSpan={PO_TABLE_COLUMN_COUNT} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={24} />
                </TableCell>
              </TableRow>
            )}
            {!posLoading && purchaseOrders.length === 0 && (
              <TableRow>
                <TableCell colSpan={PO_TABLE_COLUMN_COUNT} align="center" sx={{ py: 4 }}>
                  <Typography variant="body2" color="text.secondary">
                    No purchase orders found.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {!posLoading &&
              purchaseOrders.map((po) => (
                <POTableRow
                  key={po.id}
                  po={po}
                  expanded={expandedIds.has(po.id)}
                  onToggle={() => toggleExpand(po.id)}
                  onOpen={() => handleOpenPO(po.id)}
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
        />
      )}

      {/* Create PO Dialog */}
      <CreatePODialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setCreateOpen(false);
          handleRefetch();
        }}
        defaultProjectId={projectId}
      />
    </Box>
  );
}
