import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Chip,
  CircularProgress,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Button,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useLazyQuery } from '@apollo/client/react';
import { GET_OPENING_ITEMS, GET_OPENING_ITEM_DETAILS } from '../../graphql/warehouse';
import Modal from '../../components/Modal';
import { useIdentity } from '../../hooks/useIdentity';
import InventoryCorrectionModal from '../admin/InventoryCorrectionModal';
import FindInStockButton from './stock/FindInStockButton';
import { leafLabel } from '../../utils/leaf';

interface InstalledHardware {
  id: string;
  openingItemId: string;
  productCode: string;
  hardwareCategory: string;
  quantity: number;
}

interface OpeningItem {
  id: string;
  projectId: string;
  openingId: string;
  openingNumber: string;
  building: string | null;
  floor: string | null;
  location: string | null;
  leaf: number | null;
  leafCount: number | null;
  quantity: number;
  assemblyCompletedAt: string | null;
  state: string;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  createdAt: string;
  updatedAt: string;
  installedHardware: InstalledHardware[];
}

interface OpeningItemDetails {
  openingItem: OpeningItem;
  installedHardware: InstalledHardware[];
}

interface OpeningItemsTabProps {
  projectId?: string;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString();
}

function formatLocation(aisle: string | null, row: string | null, bay: string | null): string {
  if (aisle && row && bay) {
    return `${aisle}-${row}-${bay}`;
  }
  return 'Unlocated';
}

type StateColor = 'info' | 'warning' | 'success' | 'default';

function getStateDisplay(state: string): { label: string; color: StateColor } {
  switch (state) {
    case 'IN_INVENTORY':
      return { label: 'In Inventory', color: 'info' };
    case 'SHIP_READY':
      return { label: 'Ship Ready', color: 'warning' };
    case 'SHIPPED_OUT':
      return { label: 'Shipped Out', color: 'success' };
    default:
      return { label: state, color: 'default' };
  }
}

const columns: GridColDef[] = [
  { field: 'openingNumber', headerName: 'Opening Number', flex: 1, sortable: true },
  {
    field: 'leaf',
    headerName: 'Leaf',
    flex: 0.6,
    valueGetter: (_value: unknown, row: OpeningItem) => leafLabel(row.leaf) ?? '—',
  },
  { field: 'building', headerName: 'Building', flex: 0.8 },
  { field: 'floor', headerName: 'Floor', flex: 0.6 },
  { field: 'location', headerName: 'Location', flex: 1 },
  { field: 'aisle', headerName: 'Aisle', flex: 0.6 },
  { field: 'row', headerName: 'Row', flex: 0.6 },
  { field: 'bay', headerName: 'Bay', flex: 0.6 },
  { field: 'quantity', headerName: 'Quantity', flex: 0.6, type: 'number' },
  {
    field: 'assemblyCompletedAt',
    headerName: 'Assembly Completion Date',
    flex: 1.2,
    valueFormatter: (value: string | null) => formatDate(value),
  },
];

function OpeningItemDetailModal({
  open,
  onClose,
  itemId,
}: {
  open: boolean;
  onClose: () => void;
  itemId: string | null;
}) {
  const { isAdmin } = useIdentity();

  const [fetchDetails, { data, loading, error }] = useLazyQuery<{
    openingItemDetails: OpeningItemDetails;
  }>(GET_OPENING_ITEM_DETAILS);

  // Correction modal state
  const [correctionOpen, setCorrectionOpen] = useState(false);

  // Fetch details when itemId changes and modal is open
  useEffect(() => {
    if (itemId && open) {
      fetchDetails({ variables: { id: itemId } });
    }
  }, [itemId, open, fetchDetails]);

  const details = data?.openingItemDetails;
  const openingItem = details?.openingItem;
  const hardware = details?.installedHardware ?? [];

  const handleCorrectionSuccess = useCallback(() => {
    if (itemId) {
      fetchDetails({ variables: { id: itemId } });
    }
  }, [fetchDetails, itemId]);

  return (
    <>
      <Modal title="Opening Item Details" open={open} onClose={onClose}>
        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        )}
        {error && <Alert severity="error">Error loading details: {error.message}</Alert>}
        {openingItem && !loading && (
          <Box>
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mb: 3 }}>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Opening Number
                </Typography>
                <Typography>{openingItem.openingNumber}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Leaf
                </Typography>
                <Typography>{leafLabel(openingItem.leaf) ?? '—'}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  State
                </Typography>
                <Chip
                  label={getStateDisplay(openingItem.state).label}
                  color={getStateDisplay(openingItem.state).color}
                  size="small"
                />
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Building
                </Typography>
                <Typography>{openingItem.building ?? '—'}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Floor
                </Typography>
                <Typography>{openingItem.floor ?? '—'}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Location
                </Typography>
                <Typography>{openingItem.location ?? '—'}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Assembly Completion Date
                </Typography>
                <Typography>{formatDate(openingItem.assemblyCompletedAt)}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Warehouse Location
                </Typography>
                <Typography>
                  {formatLocation(openingItem.aisle, openingItem.row, openingItem.bay)}
                </Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Quantity
                </Typography>
                <Typography>{openingItem.quantity}</Typography>
              </Box>
            </Box>

            <Box sx={{ mb: 3, display: 'flex', gap: 1 }}>
              {isAdmin && (
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => setCorrectionOpen(true)}
                >
                  Correction
                </Button>
              )}
              <FindInStockButton
                openingItemId={openingItem.id}
                projectId={openingItem.projectId}
                defaultCategory={hardware[0]?.hardwareCategory}
                defaultProductCode={hardware[0]?.productCode}
                onAllocated={handleCorrectionSuccess}
              />
            </Box>

            <Typography variant="h6" sx={{ mb: 1 }}>
              Installed Hardware
            </Typography>
            {hardware.length === 0 ? (
              <Typography color="text.secondary">No installed hardware</Typography>
            ) : (
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Product Code</TableCell>
                      <TableCell>Hardware Category</TableCell>
                      <TableCell align="right">Quantity</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {hardware.map((hw) => (
                      <TableRow key={hw.id}>
                        <TableCell>{hw.productCode}</TableCell>
                        <TableCell>{hw.hardwareCategory}</TableCell>
                        <TableCell align="right">{hw.quantity}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Box>
        )}
      </Modal>

      {openingItem && (
        <InventoryCorrectionModal
          open={correctionOpen}
          onClose={() => setCorrectionOpen(false)}
          itemType="opening"
          item={openingItem}
          onSuccess={handleCorrectionSuccess}
        />
      )}
    </>
  );
}

export default function OpeningItemsTab({ projectId }: OpeningItemsTabProps) {
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const { data, loading, error } = useQuery<{
    openingItems: OpeningItem[];
  }>(GET_OPENING_ITEMS, {
    variables: { projectId },
  });

  const rows = useMemo(() => data?.openingItems ?? [], [data]);

  // "N of M door leaves shipped" rollup (#311): group assembled units by opening; M is the
  // opening's leaf_count (schedule), N the count already SHIPPED_OUT. Only pairs (M >= 2) are
  // worth a rollup - a single leaf is just its own row.
  const leafSummaries = useMemo(() => {
    const byOpening = new Map<string, { leafCount: number | null; shipped: number }>();
    for (const oi of rows) {
      const g = byOpening.get(oi.openingNumber) ?? { leafCount: oi.leafCount, shipped: 0 };
      if (oi.state === 'SHIPPED_OUT') g.shipped += 1;
      if (oi.leafCount != null) g.leafCount = oi.leafCount;
      byOpening.set(oi.openingNumber, g);
    }
    return Array.from(byOpening.entries())
      .filter(([, g]) => (g.leafCount ?? 1) >= 2)
      .map(([openingNumber, g]) => ({ openingNumber, shipped: g.shipped, total: g.leafCount as number }))
      .sort((a, b) => a.openingNumber.localeCompare(b.openingNumber));
  }, [rows]);

  const handleRowClick = useCallback((params: { id: string | number }) => {
    setSelectedItemId(String(params.id));
    setModalOpen(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setModalOpen(false);
    setSelectedItemId(null);
  }, []);

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading opening items: {error.message}</Alert>;
  }

  if (rows.length === 0) {
    return <Alert severity="info">No completed assemblies for this project</Alert>;
  }

  return (
    <Box>
      {leafSummaries.length > 0 && (
        <Box sx={{ mb: 2, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
          <Typography variant="subtitle2" color="text.secondary">
            Door leaves shipped:
          </Typography>
          {leafSummaries.map((s) => (
            <Chip
              key={s.openingNumber}
              size="small"
              color={s.shipped >= s.total ? 'success' : s.shipped > 0 ? 'warning' : 'default'}
              label={`Opening ${s.openingNumber}: ${s.shipped} of ${s.total} leaves shipped`}
            />
          ))}
        </Box>
      )}
      <Box sx={{ height: 600, width: '100%' }}>
        <DataGrid
          rows={rows}
          columns={columns}
          pageSizeOptions={[10, 25, 50]}
          initialState={{
            pagination: { paginationModel: { pageSize: 10 } },
          }}
          disableRowSelectionOnClick
          onRowClick={handleRowClick}
          sx={{
            '& .MuiDataGrid-row': {
              cursor: 'pointer',
            },
          }}
        />
      </Box>

      <OpeningItemDetailModal
        open={modalOpen}
        onClose={handleCloseModal}
        itemId={selectedItemId}
      />
    </Box>
  );
}
