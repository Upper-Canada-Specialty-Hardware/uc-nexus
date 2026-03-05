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
import { GET_OPENING_ITEMS, GET_OPENING_ITEM_DETAILS } from '../../graphql/queries';
import Modal from '../../components/Modal';
import { useRole } from '../../contexts/RoleContext';
import InventoryCorrectionModal from '../admin/InventoryCorrectionModal';

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
  quantity: number;
  assemblyCompletedAt: string | null;
  state: string;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
  createdAt: string;
  updatedAt: string;
  installedHardware: InstalledHardware[];
}

interface OpeningItemDetails {
  openingItem: OpeningItem;
  installedHardware: InstalledHardware[];
}

interface OpeningItemsTabProps {
  projectId: string;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString();
}

function formatLocation(aisle: string | null, bay: string | null, bin: string | null): string {
  if (aisle && bay && bin) {
    return `${aisle}-${bay}-${bin}`;
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
  { field: 'building', headerName: 'Building', flex: 0.8 },
  { field: 'floor', headerName: 'Floor', flex: 0.6 },
  { field: 'location', headerName: 'Location', flex: 1 },
  { field: 'aisle', headerName: 'Aisle', flex: 0.6 },
  { field: 'bay', headerName: 'Bay', flex: 0.6 },
  { field: 'bin', headerName: 'Bin', flex: 0.6 },
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
  const { role } = useRole();
  const isAdmin = role === 'Admin/Manager';

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
                  {formatLocation(openingItem.aisle, openingItem.bay, openingItem.bin)}
                </Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2" color="text.secondary">
                  Quantity
                </Typography>
                <Typography>{openingItem.quantity}</Typography>
              </Box>
            </Box>

            {isAdmin && (
              <Box sx={{ mb: 3 }}>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => setCorrectionOpen(true)}
                >
                  Correction
                </Button>
              </Box>
            )}

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
