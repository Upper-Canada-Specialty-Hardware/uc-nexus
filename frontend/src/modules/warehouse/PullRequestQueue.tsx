import { useState } from 'react';
import { Box, Typography, Chip } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_PULL_REQUESTS } from '../../graphql/queries';
import DataTable from '../../components/DataTable';
import Tabs from '../../components/Tabs';
import PullRequestDetailModal from './PullRequestDetailModal';

// --- Types ---

export interface PullRequestItem {
  id: string;
  pullRequestId: string;
  itemType: string;
  openingNumber: string;
  openingItemId: string | null;
  hardwareCategory: string | null;
  productCode: string | null;
  requestedQuantity: number;
}

export interface PullRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  source: string;
  status: string;
  requestedBy: string;
  assignedTo: string | null;
  createdAt: string;
  updatedAt: string;
  approvedAt: string | null;
  completedAt: string | null;
  cancelledAt: string | null;
  items: PullRequestItem[];
}

// --- Status config ---

const STATUS_CHIP_COLOR: Record<string, 'warning' | 'info' | 'success' | 'error' | 'default'> = {
  PENDING: 'warning',
  IN_PROGRESS: 'info',
  COMPLETED: 'success',
  CANCELLED: 'error',
};

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
    valueGetter: (_value: unknown, row: PullRequest) => formatDate(row.createdAt),
  },
  {
    field: 'requestedBy',
    headerName: 'Requested By',
    flex: 1,
    minWidth: 140,
  },
  {
    field: 'itemsCount',
    headerName: 'Items Count',
    flex: 0.8,
    minWidth: 120,
    type: 'number',
    valueGetter: (_value: unknown, row: PullRequest) => row.items?.length ?? 0,
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

// --- Tab content component ---

interface PullRequestTabProps {
  source: string;
  onRowClick: (pr: PullRequest) => void;
}

function PullRequestTab({ source, onRowClick }: PullRequestTabProps) {
  const { data, loading } = useQuery<{ pullRequests: PullRequest[] }>(GET_PULL_REQUESTS, {
    variables: { source },
  });

  const requests = data?.pullRequests ?? [];

  const handleRowClick = (params: GridRowParams<PullRequest>) => {
    onRowClick(params.row);
  };

  return (
    <DataTable
      columns={columns}
      rows={requests}
      loading={loading}
      onRowClick={handleRowClick}
      sx={{ cursor: 'pointer' }}
      getRowId={(row) => row.id}
    />
  );
}

// --- Main component ---

export default function PullRequestQueue() {
  const [selectedPR, setSelectedPR] = useState<PullRequest | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const handleRowClick = (pr: PullRequest) => {
    setSelectedPR(pr);
    setModalOpen(true);
  };

  const handleCloseModal = () => {
    setModalOpen(false);
    setSelectedPR(null);
  };

  const handleRefetch = () => {
    setModalOpen(false);
    setSelectedPR(null);
  };

  const tabs = [
    {
      label: 'Shop Assembly',
      content: (
        <PullRequestTab
          source="SHOP_ASSEMBLY"
          onRowClick={handleRowClick}
        />
      ),
    },
    {
      label: 'Shipping Out',
      content: (
        <PullRequestTab
          source="SHIPPING_OUT"
          onRowClick={handleRowClick}
        />
      ),
    },
  ];

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Pull Request Queue
      </Typography>

      <Tabs tabs={tabs} defaultTab={0} />

      {selectedPR && (
        <PullRequestDetailModal
          open={modalOpen}
          pr={selectedPR}
          onClose={handleCloseModal}
          onRefetch={handleRefetch}
        />
      )}
    </Box>
  );
}
