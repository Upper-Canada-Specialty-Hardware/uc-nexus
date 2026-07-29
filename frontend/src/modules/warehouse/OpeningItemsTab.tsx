import { useState, useEffect, useMemo, useCallback, type ReactNode } from 'react';
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
import { ChevronRight } from 'lucide-react';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useLazyQuery } from '@apollo/client/react';
import { GET_OPENING_ITEMS, GET_OPENING_ITEM_DETAILS } from '../../graphql/warehouse';
import Modal from '../../components/Modal';
import { useIdentity } from '../../hooks/useIdentity';
import InventoryCorrectionModal from '../admin/InventoryCorrectionModal';
import FindInStockButton from './stock/FindInStockButton';
import { leafLabel } from '../../utils/leaf';
import OpeningLeafStatusPanel from '../../components/OpeningLeafStatusPanel';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

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
  return parseServerDate(dateStr).toLocaleDateString();
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

function MonoCell({ value }: { value: string | null | undefined }) {
  return (
    <Typography component="span" sx={monoSx}>
      {value == null || value === '' ? '—' : value}
    </Typography>
  );
}

const columns: GridColDef[] = [
  {
    field: 'openingNumber',
    headerName: 'Opening Number',
    flex: 1,
    sortable: true,
    renderCell: (params) => <MonoCell value={params.value as string} />,
  },
  {
    field: 'leaf',
    headerName: 'Leaf',
    flex: 0.6,
    valueGetter: (_value: unknown, row: OpeningItem) => leafLabel(row.leaf) ?? '—',
  },
  { field: 'building', headerName: 'Building', flex: 0.8 },
  { field: 'floor', headerName: 'Floor', flex: 0.6 },
  { field: 'location', headerName: 'Location', flex: 1 },
  {
    field: 'aisle',
    headerName: 'Aisle',
    flex: 0.6,
    renderCell: (params) => <MonoCell value={params.value as string | null} />,
  },
  {
    field: 'row',
    headerName: 'Row',
    flex: 0.6,
    renderCell: (params) => <MonoCell value={params.value as string | null} />,
  },
  {
    field: 'bay',
    headerName: 'Bay',
    flex: 0.6,
    renderCell: (params) => <MonoCell value={params.value as string | null} />,
  },
  { field: 'quantity', headerName: 'Quantity', flex: 0.6, type: 'number' },
  {
    field: 'assemblyCompletedAt',
    headerName: 'Assembly Completion Date',
    flex: 1.2,
    valueFormatter: (value: string | null) => formatDate(value),
  },
  {
    // The whole row opens the detail; the chevron is what says so.
    field: 'open',
    headerName: '',
    width: 44,
    sortable: false,
    filterable: false,
    align: 'center',
    renderCell: () => (
      <Box sx={{ display: 'flex', color: 'text.secondary' }}>
        <ChevronRight size={18} strokeWidth={1.75} />
      </Box>
    ),
  },
];

function InfoField({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <Box>
      <Typography component="div" sx={microLabelSx}>
        {label}
      </Typography>
      <Typography component="div" variant="body2" sx={mono ? monoSx : undefined}>
        {value}
      </Typography>
    </Box>
  );
}

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
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(3, 1fr)' },
                gap: 1.5,
                pb: 2,
                mb: 2,
                borderBottom: '1px solid',
                borderColor: 'divider',
              }}
            >
              <InfoField label="Opening Number" value={openingItem.openingNumber} mono />
              <InfoField label="Leaf" value={leafLabel(openingItem.leaf) ?? '—'} />
              <InfoField
                label="State"
                value={
                  <Chip
                    label={getStateDisplay(openingItem.state).label}
                    color={getStateDisplay(openingItem.state).color}
                    size="small"
                  />
                }
              />
              <InfoField label="Building" value={openingItem.building ?? '—'} />
              <InfoField label="Floor" value={openingItem.floor ?? '—'} />
              <InfoField label="Location" value={openingItem.location ?? '—'} />
              <InfoField
                label="Assembly Completed"
                value={
                  <Box component="span" sx={tabularSx}>
                    {formatDate(openingItem.assemblyCompletedAt)}
                  </Box>
                }
              />
              <InfoField
                label="Warehouse Location"
                value={formatLocation(openingItem.aisle, openingItem.row, openingItem.bay)}
                mono
              />
              <InfoField
                label="Quantity"
                value={
                  <Box component="span" sx={tabularSx}>
                    {openingItem.quantity}
                  </Box>
                }
              />
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

            <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
              Installed Hardware ({hardware.length})
            </Typography>
            {hardware.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No installed hardware
              </Typography>
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
                      <TableRow key={hw.id} hover>
                        <TableCell sx={monoSx}>{hw.productCode}</TableCell>
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
      {/* #311/#313: single source of truth for the per-opening "N of M leaves shipped" rollup -
          the shared panel reads the backend openingLeafStatus (dedup per leaf), replacing the
          divergent client-side count that over-counted corrected/duplicated shipped rows. */}
      <OpeningLeafStatusPanel projectId={projectId} mode="shipping" />
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
