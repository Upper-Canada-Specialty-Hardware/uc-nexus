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
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import AddIcon from '@mui/icons-material/Add';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_PURCHASE_ORDERS, GET_PO_STATISTICS } from '../../graphql/queries';
import DataTable from '../../components/DataTable';
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

// --- Columns ---

const columns: GridColDef[] = [
  {
    field: 'poNumber',
    headerName: 'PO / Request #',
    flex: 1,
    minWidth: 180,
    renderCell: (params) => {
      const row = params.row as PurchaseOrder;
      if (row.poNumber) return row.poNumber;
      return (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Typography variant="body2" color="text.secondary">{row.requestNumber}</Typography>
          <Chip label="Draft" size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
        </Box>
      );
    },
  },
  {
    field: 'status',
    headerName: 'Status',
    flex: 1,
    minWidth: 160,
    renderCell: (params) => (
      <Chip
        label={formatStatus(params.value as string)}
        color={STATUS_CHIP_COLOR[params.value as string] ?? 'default'}
        size="small"
      />
    ),
  },
  {
    field: 'vendor',
    headerName: 'Vendor',
    flex: 1,
    minWidth: 160,
    valueGetter: (_value: unknown, row: PurchaseOrder) => row.vendor?.name || '-',
  },
  {
    field: 'orderedAt',
    headerName: 'Order Date',
    flex: 1,
    minWidth: 140,
    valueGetter: (_value: unknown, row: PurchaseOrder) =>
      row.orderedAt ? new Date(row.orderedAt).toLocaleDateString() : '-',
  },
  {
    field: 'itemsCount',
    headerName: 'Items Count',
    flex: 0.7,
    minWidth: 110,
    valueGetter: (_value: unknown, row: PurchaseOrder) => row.lineItems?.length ?? 0,
  },
];

function formatStatus(status: string): string {
  return status
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
}

// --- Component ---

export default function POModule() {
  const [selectedProject, setSelectedProject] = useState<Project | 'all' | null>(null);
  const [activeFilter, setActiveFilter] = useState<StatusFilter>('');
  const [selectedPOId, setSelectedPOId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

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

  const handleRowClick = (params: GridRowParams<PurchaseOrder>) => {
    setSelectedPOId(params.row.id);
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
      <DataTable
        columns={columns}
        rows={purchaseOrders}
        loading={posLoading}
        onRowClick={handleRowClick}
        sx={{ cursor: 'pointer' }}
        getRowId={(row) => row.id}
      />

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
