import { useState, useMemo, useCallback } from 'react';
import { Box, Tab, Tabs, Button, TextField, Chip, Alert } from '@mui/material';
import AddShoppingCartIcon from '@mui/icons-material/AddShoppingCart';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { useProject } from '../../contexts/ProjectContext';
import { useCart } from '../../contexts/CartContext';
import { useToast } from '../../components/Toast';
import { GET_SHIP_READY_ITEMS } from '../../graphql/queries';

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
  building: string;
  floor: string;
  location: string;
  quantity: number;
  assemblyCompletedAt: string | null;
  state: string;
  shelf: string | null;
  column: string | null;
  row: string | null;
  createdAt: string;
  updatedAt: string;
  installedHardware: InstalledHardware[];
}

interface LooseItem {
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  availableQuantity: number;
}

interface ShipReadyData {
  shipReadyItems: {
    openingItems: OpeningItem[];
    looseItems: LooseItem[];
  };
}

export default function ShipReadyBrowser() {
  const { project } = useProject();
  const { items, addItem } = useCart();
  const { showToast } = useToast();
  const [tabIndex, setTabIndex] = useState(0);
  const [looseQuantities, setLooseQuantities] = useState<Record<string, number>>({});

  const { data, loading } = useQuery<ShipReadyData>(GET_SHIP_READY_ITEMS, {
    variables: { projectId: project?.id ?? '' },
    skip: !project,
    pollInterval: 10000,
  });

  const openingItems = data?.shipReadyItems?.openingItems ?? [];
  const looseItems = data?.shipReadyItems?.looseItems ?? [];

  const isOpeningItemInCart = useCallback(
    (openingItemId: string) => items.some((i) => i.openingItemId === openingItemId),
    [items],
  );

  const handleAddOpeningItem = useCallback(
    (oi: OpeningItem) => {
      addItem({
        id: oi.id,
        itemType: 'Opening_Item',
        openingItemId: oi.id,
        openingNumber: oi.openingNumber,
        quantity: 1,
        building: oi.building,
        floor: oi.floor,
        location: oi.location,
      });
      showToast(`Opening ${oi.openingNumber} added to cart`, 'success');
    },
    [addItem, showToast],
  );

  const handleAddLooseItem = useCallback(
    (item: LooseItem) => {
      const key = `${item.openingNumber}-${item.productCode}`;
      const qty = looseQuantities[key] ?? 0;
      if (qty <= 0) {
        showToast('Quantity must be greater than 0', 'warning');
        return;
      }
      if (qty > item.availableQuantity) {
        showToast(`Quantity cannot exceed available (${item.availableQuantity})`, 'warning');
        return;
      }
      addItem({
        id: crypto.randomUUID(),
        itemType: 'Loose',
        openingNumber: item.openingNumber,
        hardwareCategory: item.hardwareCategory,
        productCode: item.productCode,
        quantity: qty,
      });
      setLooseQuantities((prev) => ({ ...prev, [key]: 0 }));
      showToast(`${item.productCode} x${qty} added to cart`, 'success');
    },
    [addItem, looseQuantities, showToast],
  );

  const openingColumns = useMemo<GridColDef[]>(
    () => [
      { field: 'openingNumber', headerName: 'Opening #', flex: 1 },
      { field: 'building', headerName: 'Building', flex: 1 },
      { field: 'floor', headerName: 'Floor', flex: 0.7 },
      { field: 'location', headerName: 'Location', flex: 1 },
      {
        field: 'state',
        headerName: 'State',
        flex: 0.8,
        renderCell: (params) => (
          <Chip label={params.value} size="small" color="primary" variant="outlined" />
        ),
      },
      {
        field: 'actions',
        headerName: '',
        flex: 0.8,
        sortable: false,
        filterable: false,
        renderCell: (params) => (
          <Button
            size="small"
            startIcon={<AddShoppingCartIcon />}
            onClick={() => handleAddOpeningItem(params.row as OpeningItem)}
            disabled={isOpeningItemInCart(params.row.id)}
          >
            {isOpeningItemInCart(params.row.id) ? 'In Cart' : 'Add'}
          </Button>
        ),
      },
    ],
    [handleAddOpeningItem, isOpeningItemInCart],
  );

  const looseRows = useMemo(
    () =>
      looseItems.map((item, index) => ({
        id: `${item.openingNumber}-${item.productCode}-${index}`,
        ...item,
      })),
    [looseItems],
  );

  const looseColumns = useMemo<GridColDef[]>(
    () => [
      { field: 'openingNumber', headerName: 'Opening #', flex: 1 },
      { field: 'productCode', headerName: 'Product Code', flex: 1 },
      { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
      { field: 'availableQuantity', headerName: 'Available Qty', flex: 0.7, type: 'number' },
      {
        field: 'quantity',
        headerName: 'Qty to Ship',
        flex: 0.8,
        sortable: false,
        filterable: false,
        renderCell: (params) => {
          const key = `${params.row.openingNumber}-${params.row.productCode}`;
          return (
            <TextField
              type="number"
              size="small"
              value={looseQuantities[key] ?? ''}
              onChange={(e) =>
                setLooseQuantities((prev) => ({
                  ...prev,
                  [key]: parseInt(e.target.value, 10) || 0,
                }))
              }
              inputProps={{ min: 0, max: params.row.availableQuantity }}
              sx={{ width: 80 }}
            />
          );
        },
      },
      {
        field: 'actions',
        headerName: '',
        flex: 0.8,
        sortable: false,
        filterable: false,
        renderCell: (params) => (
          <Button
            size="small"
            startIcon={<AddShoppingCartIcon />}
            onClick={() => handleAddLooseItem(params.row as LooseItem)}
          >
            Add
          </Button>
        ),
      },
    ],
    [handleAddLooseItem, looseQuantities],
  );

  if (!project) return <Alert severity="info">Please select a project</Alert>;

  return (
    <Box>
      <Tabs value={tabIndex} onChange={(_, v) => setTabIndex(v)} sx={{ mb: 2 }}>
        <Tab label="Opening Items" />
        <Tab label="Loose Hardware" />
      </Tabs>

      {tabIndex === 0 && (
        <DataGrid
          rows={openingItems}
          columns={openingColumns}
          loading={loading}
          autoHeight
          pageSizeOptions={[10, 25, 50]}
          initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
          disableRowSelectionOnClick
        />
      )}

      {tabIndex === 1 && (
        <DataGrid
          rows={looseRows}
          columns={looseColumns}
          loading={loading}
          autoHeight
          pageSizeOptions={[10, 25, 50]}
          initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
          disableRowSelectionOnClick
        />
      )}
    </Box>
  );
}
