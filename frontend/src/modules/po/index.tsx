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
  Alert,
} from '@mui/material';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_PURCHASE_ORDERS, GET_PO_STATISTICS } from '../../graphql/queries';
import { useProject } from '../../contexts/ProjectContext';
import DataTable from '../../components/DataTable';
import PODetailModal from './PODetailModal';

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
  vendorAlias: string | null;
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

export interface PurchaseOrder {
  id: string;
  poNumber: string;
  projectId: string;
  status: string;
  vendorName: string | null;
  vendorContact: string | null;
  expectedDeliveryDate: string | null;
  orderedAt: string | null;
  createdAt: string;
  updatedAt: string;
  lineItems: POLineItem[];
  receiveRecords: ReceiveRecord[];
}

interface POStatistics {
  total: number;
  draft: number;
  ordered: number;
  partiallyReceived: number;
  closed: number;
  cancelled: number;
}

// --- Status config ---

type StatusFilter = '' | 'DRAFT' | 'ORDERED' | 'PARTIALLY_RECEIVED' | 'CLOSED' | 'CANCELLED';

const STATUS_CHIP_COLOR: Record<string, 'default' | 'primary' | 'warning' | 'success' | 'error'> = {
  DRAFT: 'default',
  ORDERED: 'primary',
  PARTIALLY_RECEIVED: 'warning',
  CLOSED: 'success',
  CANCELLED: 'error',
};

const TAB_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: 'All', value: '' },
  { label: 'Draft', value: 'DRAFT' },
  { label: 'Ordered', value: 'ORDERED' },
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
  { label: 'Partially Received', filter: 'PARTIALLY_RECEIVED', key: 'partiallyReceived' },
  { label: 'Closed', filter: 'CLOSED', key: 'closed' },
  { label: 'Cancelled', filter: 'CANCELLED', key: 'cancelled' },
];

// --- Columns ---

const columns: GridColDef[] = [
  {
    field: 'poNumber',
    headerName: 'PO Number',
    flex: 1,
    minWidth: 140,
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
    field: 'vendorName',
    headerName: 'Vendor',
    flex: 1,
    minWidth: 160,
    valueGetter: (_value: unknown, row: PurchaseOrder) => row.vendorName || '-',
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
  const { project } = useProject();
  const [activeFilter, setActiveFilter] = useState<StatusFilter>('');
  const [selectedPOId, setSelectedPOId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

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
    variables: { projectId: project?.id },
    skip: !project?.id,
  });

  const {
    data: posData,
    loading: posLoading,
    refetch: refetchPOs,
  } = useQuery<{ purchaseOrders: PurchaseOrder[] }>(GET_PURCHASE_ORDERS, {
    variables: {
      projectId: project?.id,
      status: activeFilter || undefined,
    },
    skip: !project?.id,
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

  // --- No project selected ---

  if (!project) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity="info">
          Please select a project from the navigation bar to view purchase orders.
        </Alert>
      </Box>
    );
  }

  // --- Render ---

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Purchase Orders
      </Typography>

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
    </Box>
  );
}
