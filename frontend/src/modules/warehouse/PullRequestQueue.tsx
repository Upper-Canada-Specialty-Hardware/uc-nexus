import { useMemo, useState } from 'react';
import { Box, Typography, Chip } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_PULL_REQUESTS } from '../../graphql/warehouse';
import DataTable from '../../components/DataTable';
import Tabs from '../../components/Tabs';
import PullRequestDetailModal from './PullRequestDetailModal';
import { stagingChipColor, stagingChipLabel } from './pullStaging';

// --- Types ---

export interface PullRequestItem {
  id: string;
  pullRequestId: string;
  itemType: string;
  openingNumber: string;
  openingItemId: string | null;
  /** Door leaf this pull line is for (#311): 1 or 2, or null for legacy / leaf-agnostic lines. */
  leaf: number | null;
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
  cancelledBy: string | null;
  cancellationReason: string | null;
  /** Derived per-opening staging rollup (#343): NOT_PULLED / PARTIAL / PULLED over this pull's
   *  shop-assembly openings. Null when the pull has none (shipping-out, PR-REPL, legacy). */
  stagingStatus: string | null;
  stagedOpeningCount: number | null;
  totalOpeningCount: number | null;
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
  {
    // #343: how far the warehouse has got picking this pull, opening by opening. Blank rather than
    // a zeroed chip on a pull with no openings - staging does not apply there.
    field: 'staging',
    headerName: 'Staging',
    flex: 1,
    minWidth: 140,
    sortable: false,
    valueGetter: (_value: unknown, row: PullRequest) => stagingChipLabel(row) ?? '',
    renderCell: (params) => {
      const label = stagingChipLabel(params.row as PullRequest);
      if (!label) return null;
      return <Chip label={label} color={stagingChipColor(params.row as PullRequest)} size="small" />;
    },
  },
];

// --- Tab content component ---

interface PullRequestTabProps {
  source: string;
}

function PullRequestTab({ source }: PullRequestTabProps) {
  // The id, not the row (#343). The modal stages openings and cancels the pull, both of which
  // refetch this list; holding the object would pin the modal's staging chip to the pre-staging
  // snapshot - the same trap #340 fixed in the assembly views.
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, loading } = useQuery<{ pullRequests: PullRequest[] }>(GET_PULL_REQUESTS, {
    variables: { source },
  });

  const requests = useMemo(() => data?.pullRequests ?? [], [data]);
  const selected = useMemo(() => requests.find((pr) => pr.id === selectedId) ?? null, [requests, selectedId]);

  const handleRowClick = (params: GridRowParams<PullRequest>) => {
    setSelectedId(params.row.id);
  };

  return (
    <>
      <DataTable
        columns={columns}
        rows={requests}
        loading={loading}
        onRowClick={handleRowClick}
        sx={{ cursor: 'pointer' }}
        getRowId={(row) => row.id}
      />
      {selected && (
        <PullRequestDetailModal
          open
          pr={selected}
          onClose={() => setSelectedId(null)}
          onRefetch={() => setSelectedId(null)}
        />
      )}
    </>
  );
}

// --- Main component ---

export default function PullRequestQueue() {
  const tabs = [
    { label: 'Shop Assembly', content: <PullRequestTab source="SHOP_ASSEMBLY" /> },
    { label: 'Shipping Out', content: <PullRequestTab source="SHIPPING_OUT" /> },
  ];

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Pull Request Queue
      </Typography>

      <Tabs tabs={tabs} defaultTab={0} />
    </Box>
  );
}
