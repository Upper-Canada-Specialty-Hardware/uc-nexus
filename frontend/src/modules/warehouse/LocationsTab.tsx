import { useState, useMemo, useCallback, useEffect } from 'react';
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  Drawer,
  IconButton,
  Divider,
  Chip,
  List,
  ListItemButton,
  ListItemText,
  TextField,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useQuery, useLazyQuery } from '@apollo/client/react';
import { GET_LOCATION_UTILIZATION, GET_LOCATION_CONTENTS } from '../../graphql/queries';

interface LocationEntry {
  aisle: string;
  bay: string | null;
  bin: string | null;
  itemCount: number;
  totalQuantity: number;
}

interface InventoryLocationItem {
  id: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
}

interface ContentsInventoryItem {
  inventoryLocation: InventoryLocationItem;
  poNumber: string | null;
  unitCost: number | null;
}

interface ContentsOpeningItem {
  id: string;
  openingNumber: string;
  building: string | null;
  floor: string | null;
  state: string;
  quantity: number;
}

interface LocationContentsData {
  locationContents: {
    inventoryItems: ContentsInventoryItem[];
    openingItems: ContentsOpeningItem[];
  };
}

function formatLocation(aisle: string, bay: string | null, bin: string | null): string {
  const parts = [aisle];
  if (bay) parts.push(bay);
  if (bin) parts.push(bin);
  return parts.join('-');
}

function formatCurrency(value: number | null): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

const columns: GridColDef[] = [
  {
    field: 'location',
    headerName: 'Location',
    flex: 1,
    valueGetter: (_v: unknown, row: LocationEntry) => formatLocation(row.aisle, row.bay, row.bin),
  },
  { field: 'aisle', headerName: 'Aisle', flex: 0.5 },
  { field: 'bay', headerName: 'Bay', flex: 0.5, valueFormatter: (v: string | null) => v ?? '—' },
  { field: 'bin', headerName: 'Bin', flex: 0.5, valueFormatter: (v: string | null) => v ?? '—' },
  { field: 'itemCount', headerName: 'Items', flex: 0.5, type: 'number' },
  { field: 'totalQuantity', headerName: 'Total Qty', flex: 0.5, type: 'number' },
];

function LocationContentsDrawer({
  open,
  onClose,
  aisle,
  bay,
  bin,
}: {
  open: boolean;
  onClose: () => void;
  aisle: string;
  bay: string | null;
  bin: string | null;
}) {
  const [fetchContents, { data, loading, error }] = useLazyQuery<LocationContentsData>(GET_LOCATION_CONTENTS);

  useEffect(() => {
    if (open) {
      fetchContents({ variables: { aisle, bay, bin } });
    }
  }, [open, aisle, bay, bin, fetchContents]);

  const invItems = data?.locationContents?.inventoryItems ?? [];
  const oiItems = data?.locationContents?.openingItems ?? [];

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: 420, maxWidth: '90vw' } }}>
      <Box sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">Location: {formatLocation(aisle, bay, bin)}</Typography>
          <IconButton onClick={onClose} size="small"><CloseIcon /></IconButton>
        </Box>

        {loading && <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>}
        {error && <Alert severity="error">Error: {error.message}</Alert>}

        {!loading && invItems.length === 0 && oiItems.length === 0 && (
          <Alert severity="info">No items at this location</Alert>
        )}

        {invItems.length > 0 && (
          <>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Hardware Items ({invItems.length})</Typography>
            <List dense disablePadding>
              {invItems.map((item) => (
                <ListItemButton key={item.inventoryLocation.id} sx={{ borderRadius: 1, mb: 0.5 }}>
                  <ListItemText
                    primary={`${item.inventoryLocation.productCode} — ${item.inventoryLocation.hardwareCategory}`}
                    secondary={`Qty: ${item.inventoryLocation.quantity} | PO: ${item.poNumber ?? '—'} | ${formatCurrency(item.unitCost)}/ea`}
                  />
                </ListItemButton>
              ))}
            </List>
            <Divider sx={{ my: 1.5 }} />
          </>
        )}

        {oiItems.length > 0 && (
          <>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Opening Items ({oiItems.length})</Typography>
            <List dense disablePadding>
              {oiItems.map((oi) => (
                <ListItemButton key={oi.id} sx={{ borderRadius: 1, mb: 0.5 }}>
                  <ListItemText
                    primary={oi.openingNumber}
                    secondary={`${oi.building ?? ''} ${oi.floor ?? ''} — ${oi.state}`}
                  />
                  <Chip label={oi.state.replace('_', ' ')} size="small" variant="outlined" />
                </ListItemButton>
              ))}
            </List>
          </>
        )}
      </Box>
    </Drawer>
  );
}

export default function LocationsTab() {
  const [search, setSearch] = useState('');
  const [selectedLocation, setSelectedLocation] = useState<LocationEntry | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const { data, loading, error } = useQuery<{ locationUtilization: LocationEntry[] }>(GET_LOCATION_UTILIZATION);

  const rows = useMemo(() => {
    const locations = data?.locationUtilization ?? [];
    return locations
      .filter((loc) => {
        if (!search) return true;
        const s = search.toLowerCase();
        return (
          loc.aisle.toLowerCase().includes(s) ||
          (loc.bay ?? '').toLowerCase().includes(s) ||
          (loc.bin ?? '').toLowerCase().includes(s)
        );
      })
      .map((loc, i) => ({ ...loc, id: `${loc.aisle}-${loc.bay}-${loc.bin}-${i}` }));
  }, [data, search]);

  const handleRowClick = useCallback((params: GridRowParams<LocationEntry & { id: string }>) => {
    setSelectedLocation(params.row);
    setDrawerOpen(true);
  }, []);

  if (loading && !data) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;
  }
  if (error) return <Alert severity="error">Error: {error.message}</Alert>;

  const totalLocations = rows.length;
  const totalQty = rows.reduce((sum, r) => sum + r.totalQuantity, 0);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <TextField
          label="Search locations"
          placeholder="Filter by aisle, bay, or bin..."
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: 250 }}
        />
        <Typography variant="body2" color="text.secondary">
          {totalLocations} locations — {totalQty.toLocaleString()} total items
        </Typography>
      </Box>

      {rows.length === 0 ? (
        <Alert severity="info">No inventory has been assigned to locations yet</Alert>
      ) : (
        <Box sx={{ height: 600, width: '100%' }}>
          <DataGrid
            rows={rows}
            columns={columns}
            pageSizeOptions={[10, 25, 50]}
            initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
            disableRowSelectionOnClick
            onRowClick={handleRowClick}
            density="compact"
            sx={{ '& .MuiDataGrid-row': { cursor: 'pointer' } }}
          />
        </Box>
      )}

      {selectedLocation && (
        <LocationContentsDrawer
          open={drawerOpen}
          onClose={() => { setDrawerOpen(false); setSelectedLocation(null); }}
          aisle={selectedLocation.aisle}
          bay={selectedLocation.bay}
          bin={selectedLocation.bin}
        />
      )}
    </Box>
  );
}
