import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  Chip,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_SHOP_ASSEMBLY_REQUESTS } from '../../graphql/queries';
import DataTable from '../../components/DataTable';
import SARDetailModal from './SARDetailModal';

// --- Types ---

interface ShopAssemblyOpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
}

interface ShopAssemblyOpening {
  id: string;
  shopAssemblyRequestId: string;
  openingId: string;
  pullStatus: string;
  assignedTo: string | null;
  assemblyStatus: string;
  completedAt: string | null;
  items: ShopAssemblyOpeningItem[];
}

export interface ShopAssemblyRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  status: string;
  createdBy: string;
  approvedBy: string | null;
  rejectedBy: string | null;
  rejectionReason: string | null;
  createdAt: string;
  approvedAt: string | null;
  rejectedAt: string | null;
  openings: ShopAssemblyOpening[];
}

// --- Status config ---

type StatusFilter = '' | 'PENDING' | 'APPROVED' | 'REJECTED';

const STATUS_CHIP_COLOR: Record<string, 'default' | 'warning' | 'success' | 'error'> = {
  PENDING: 'warning',
  APPROVED: 'success',
  REJECTED: 'error',
};

const STATUS_FILTER_OPTIONS: { label: string; value: StatusFilter }[] = [
  { label: 'All', value: '' },
  { label: 'Pending', value: 'PENDING' },
  { label: 'Approved', value: 'APPROVED' },
  { label: 'Rejected', value: 'REJECTED' },
];

function formatStatus(status: string): string {
  return status
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleDateString();
}

// --- Columns ---

const columns: GridColDef[] = [
  {
    field: 'requestNumber',
    headerName: 'Request #',
    flex: 1,
    minWidth: 140,
  },
  {
    field: 'createdAt',
    headerName: 'Created Date',
    flex: 1,
    minWidth: 140,
    valueGetter: (_value: unknown, row: ShopAssemblyRequest) => formatDate(row.createdAt),
  },
  {
    field: 'createdBy',
    headerName: 'Created By',
    flex: 1,
    minWidth: 140,
  },
  {
    field: 'openingsCount',
    headerName: 'Openings Count',
    flex: 0.8,
    minWidth: 130,
    type: 'number',
    valueGetter: (_value: unknown, row: ShopAssemblyRequest) => row.openings?.length ?? 0,
  },
  {
    field: 'status',
    headerName: 'Status',
    flex: 1,
    minWidth: 130,
    renderCell: (params) => (
      <Chip
        label={formatStatus(params.value as string)}
        color={STATUS_CHIP_COLOR[params.value as string] ?? 'default'}
        size="small"
      />
    ),
  },
];

// --- Component ---

export default function SARListPage() {
  const [activeFilter, setActiveFilter] = useState<StatusFilter>('PENDING');
  const [selectedSAR, setSelectedSAR] = useState<ShopAssemblyRequest | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const queryVariables = useMemo(
    () => ({
      status: activeFilter || undefined,
    }),
    [activeFilter],
  );

  const {
    data,
    loading,
    refetch,
  } = useQuery<{ shopAssemblyRequests: ShopAssemblyRequest[] }>(GET_SHOP_ASSEMBLY_REQUESTS, {
    variables: queryVariables,
  });

  const requests = data?.shopAssemblyRequests ?? [];

  // --- Handlers ---

  const handleRowClick = (params: GridRowParams<ShopAssemblyRequest>) => {
    setSelectedSAR(params.row);
    setModalOpen(true);
  };

  const handleCloseModal = () => {
    setModalOpen(false);
    setSelectedSAR(null);
  };

  const handleRefetch = () => {
    refetch();
  };

  // --- Render ---

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Shop Assembly Requests
      </Typography>

      {/* Status Filter Dropdown */}
      <FormControl size="small" sx={{ mb: 2, minWidth: 200 }}>
        <InputLabel id="sar-status-filter-label">Status Filter</InputLabel>
        <Select
          labelId="sar-status-filter-label"
          value={activeFilter}
          label="Status Filter"
          onChange={(e) => setActiveFilter(e.target.value as StatusFilter)}
        >
          {STATUS_FILTER_OPTIONS.map((opt) => (
            <MenuItem key={opt.value} value={opt.value}>
              {opt.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* SAR Table */}
      <DataTable
        columns={columns}
        rows={requests}
        loading={loading}
        onRowClick={handleRowClick}
        sx={{ cursor: 'pointer' }}
        getRowId={(row) => row.id}
      />

      {/* Detail Modal */}
      {selectedSAR && (
        <SARDetailModal
          open={modalOpen}
          sar={selectedSAR}
          onClose={handleCloseModal}
          onRefetch={handleRefetch}
        />
      )}
    </Box>
  );
}
