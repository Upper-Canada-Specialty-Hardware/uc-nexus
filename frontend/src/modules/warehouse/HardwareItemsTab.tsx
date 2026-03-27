import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import {
  Box,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  CircularProgress,
  Alert,
  Button,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useLazyQuery } from '@apollo/client/react';
import { GET_INVENTORY_HIERARCHY, GET_INVENTORY_ITEMS } from '../../graphql/queries';
import { useIdentity } from '../../hooks/useIdentity';
import InventoryCorrectionModal from '../admin/InventoryCorrectionModal';

interface InventoryItem {
  id: string;
  projectId: string;
  poLineItemId: string;
  receiveLineItemId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  aisle: string | null;
  bay: string | null;
  bin: string | null;
  receivedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

interface ProductCodeGroup {
  productCode: string;
  totalQuantity: number;
  totalValue: number;
  items: InventoryItem[];
}

interface CategoryGroup {
  hardwareCategory: string;
  totalQuantity: number;
  totalValue: number;
  productCodes: ProductCodeGroup[];
}

interface InventoryItemDetail {
  inventoryLocation: InventoryItem;
  poNumber: string | null;
  classification: string;
  unitCost: number | null;
}

interface HardwareItemsTabProps {
  projectId?: string;
}

function formatLocation(aisle: string | null, bay: string | null, bin: string | null): string {
  if (aisle && bay && bin) {
    return `${aisle}-${bay}-${bin}`;
  }
  return 'Unlocated';
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString();
}

function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

const baseDetailColumns: GridColDef[] = [
  { field: 'productCode', headerName: 'Product Code', flex: 1 },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
  { field: 'quantity', headerName: 'Quantity', flex: 0.5, type: 'number' },
  {
    field: 'unitCost',
    headerName: 'Unit Cost',
    flex: 0.7,
    type: 'number',
    valueGetter: (_value: unknown, row: InventoryItemDetail) => row.unitCost,
    valueFormatter: (value: number | null) => formatCurrency(value),
  },
  {
    field: 'lineTotal',
    headerName: 'Line Total',
    flex: 0.7,
    type: 'number',
    valueGetter: (_value: unknown, row: InventoryItemDetail) =>
      row.unitCost != null ? row.unitCost * row.inventoryLocation.quantity : null,
    valueFormatter: (value: number | null) => formatCurrency(value),
  },
  {
    field: 'location',
    headerName: 'Location',
    flex: 1,
    valueGetter: (_value: unknown, row: InventoryItemDetail) =>
      formatLocation(
        row.inventoryLocation.aisle,
        row.inventoryLocation.bay,
        row.inventoryLocation.bin,
      ),
  },
  { field: 'poNumber', headerName: 'PO Number', flex: 1 },
  {
    field: 'receivedAt',
    headerName: 'Received Date',
    flex: 1,
    valueGetter: (_value: unknown, row: InventoryItemDetail) =>
      formatDate(row.inventoryLocation.receivedAt),
  },
];

function ProductCodeDetail({
  projectId,
  category,
  productCode,
  totalQuantity,
  totalValue,
}: {
  projectId: string | undefined;
  category: string;
  productCode: string;
  totalQuantity: number;
  totalValue: number;
}) {
  const { isAdmin } = useIdentity();

  const [expanded, setExpanded] = useState(false);
  const hasFetched = useRef(false);
  const [fetchItems, { data, loading, error }] = useLazyQuery<{
    inventoryItems: InventoryItemDetail[];
  }>(GET_INVENTORY_ITEMS);

  // Correction modal state
  const [correctionItem, setCorrectionItem] = useState<InventoryItem | null>(null);
  const [correctionOpen, setCorrectionOpen] = useState(false);

  const handleExpand = useCallback(
    (_event: React.SyntheticEvent, isExpanded: boolean) => {
      setExpanded(isExpanded);
      if (isExpanded && !hasFetched.current) {
        hasFetched.current = true;
        fetchItems({
          variables: { projectId, category, productCode },
        });
      }
    },
    [fetchItems, projectId, category, productCode],
  );

  const rows = useMemo(
    () =>
      (data?.inventoryItems ?? []).map((item) => ({
        ...item,
        id: item.inventoryLocation.id,
      })),
    [data],
  );

  const detailColumns = useMemo(() => {
    if (!isAdmin) return baseDetailColumns;
    return [
      ...baseDetailColumns,
      {
        field: 'actions',
        headerName: 'Actions',
        flex: 0.7,
        sortable: false,
        filterable: false,
        renderCell: (params: { row: InventoryItemDetail }) => (
          <Button
            size="small"
            variant="outlined"
            onClick={(e) => {
              e.stopPropagation();
              setCorrectionItem(params.row.inventoryLocation);
              setCorrectionOpen(true);
            }}
          >
            Correction
          </Button>
        ),
      } satisfies GridColDef,
    ];
  }, [isAdmin]);

  const handleCorrectionSuccess = useCallback(() => {
    fetchItems({
      variables: { projectId, category, productCode },
    });
  }, [fetchItems, projectId, category, productCode]);

  return (
    <>
      <Accordion expanded={expanded} onChange={handleExpand} sx={{ ml: 2 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography sx={{ fontWeight: 500 }}>
            {productCode}
          </Typography>
          <Typography sx={{ ml: 2, color: 'text.secondary' }}>
            — Qty: {totalQuantity} | Value: {formatCurrency(totalValue)}
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          {loading && !data && (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
              <CircularProgress size={24} />
            </Box>
          )}
          {error && <Alert severity="error">Error loading items: {error.message}</Alert>}
          {!(loading && !data) && !error && rows.length === 0 && (
            <Typography color="text.secondary">No items found</Typography>
          )}
          {!(loading && !data) && rows.length > 0 && (
            <Box sx={{ height: 300, width: '100%' }}>
              <DataGrid
                rows={rows}
                columns={detailColumns}
                pageSizeOptions={[5, 10, 25]}
                initialState={{
                  pagination: { paginationModel: { pageSize: 5 } },
                }}
                disableRowSelectionOnClick
                density="compact"
              />
            </Box>
          )}
        </AccordionDetails>
      </Accordion>

      {correctionItem && (
        <InventoryCorrectionModal
          open={correctionOpen}
          onClose={() => {
            setCorrectionOpen(false);
            setCorrectionItem(null);
          }}
          itemType="inventory"
          item={correctionItem}
          onSuccess={handleCorrectionSuccess}
        />
      )}
    </>
  );
}

export default function HardwareItemsTab({ projectId }: HardwareItemsTabProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [aisleFilter, setAisleFilter] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  const { data, loading, error } = useQuery<{
    inventoryHierarchy: CategoryGroup[];
  }>(GET_INVENTORY_HIERARCHY, {
    variables: { projectId },
  });

  // Debounce search input
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearchTerm(value);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setDebouncedSearch(value);
    }, 300);
  }, []);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, []);

  const hierarchy = data?.inventoryHierarchy ?? [];

  // Extract distinct categories
  const categories = useMemo(
    () => [...new Set(hierarchy.map((c) => c.hardwareCategory))].sort(),
    [hierarchy],
  );

  // Extract distinct aisle values from Level 3 items
  const aisles = useMemo(() => {
    const aisleSet = new Set<string>();
    hierarchy.forEach((cat) =>
      cat.productCodes.forEach((pc) =>
        pc.items.forEach((item) => {
          if (item.aisle) aisleSet.add(item.aisle);
        }),
      ),
    );
    return [...aisleSet].sort();
  }, [hierarchy]);

  // Filter hierarchy
  const filteredHierarchy = useMemo(() => {
    const search = debouncedSearch.toLowerCase();
    return hierarchy
      .filter((cat) => {
        if (categoryFilter && cat.hardwareCategory !== categoryFilter) return false;
        if (search) {
          const categoryMatch = cat.hardwareCategory.toLowerCase().includes(search);
          const productMatch = cat.productCodes.some((pc) =>
            pc.productCode.toLowerCase().includes(search),
          );
          if (!categoryMatch && !productMatch) return false;
        }
        return true;
      })
      .map((cat) => {
        // If searching, also filter product codes within the category
        if (search) {
          const categoryMatch = cat.hardwareCategory.toLowerCase().includes(search);
          if (categoryMatch) return cat; // show all product codes if category matched
          return {
            ...cat,
            productCodes: cat.productCodes.filter((pc) =>
              pc.productCode.toLowerCase().includes(search),
            ),
          };
        }
        // If aisle filter is active, filter product codes that have items with matching aisle
        if (aisleFilter) {
          return {
            ...cat,
            productCodes: cat.productCodes.filter((pc) =>
              pc.items.some((item) => item.aisle === aisleFilter),
            ),
          };
        }
        return cat;
      })
      .filter((cat) => cat.productCodes.length > 0);
  }, [hierarchy, debouncedSearch, categoryFilter, aisleFilter]);

  const grandTotals = useMemo(() => {
    const totalQty = filteredHierarchy.reduce((sum, cat) => sum + cat.totalQuantity, 0);
    const totalVal = filteredHierarchy.reduce((sum, cat) => sum + cat.totalValue, 0);
    return { totalQty, totalVal };
  }, [filteredHierarchy]);

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading inventory: {error.message}</Alert>;
  }

  if (hierarchy.length === 0) {
    return (
      <Alert severity="info">No inventory items for this project</Alert>
    );
  }

  return (
    <Box>
      {/* Search and filter controls */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        <TextField
          label="Search"
          placeholder="Search by product code or category..."
          size="small"
          value={searchTerm}
          onChange={handleSearchChange}
          sx={{ minWidth: 250 }}
        />
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel>Category</InputLabel>
          <Select
            value={categoryFilter}
            label="Category"
            onChange={(e) => setCategoryFilter(e.target.value)}
          >
            <MenuItem value="">All Categories</MenuItem>
            {categories.map((cat) => (
              <MenuItem key={cat} value={cat}>
                {cat}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Aisle</InputLabel>
          <Select
            value={aisleFilter}
            label="Aisle"
            onChange={(e) => setAisleFilter(e.target.value)}
          >
            <MenuItem value="">All Aisles</MenuItem>
            {aisles.map((aisle) => (
              <MenuItem key={aisle} value={aisle}>
                {aisle}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      {/* Grand total summary */}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          p: 2,
          mb: 2,
          bgcolor: 'primary.main',
          color: 'primary.contrastText',
          borderRadius: 1,
        }}
      >
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
          Inventory Summary
        </Typography>
        <Box sx={{ display: 'flex', gap: 4 }}>
          <Typography variant="subtitle1">
            Total Items: {grandTotals.totalQty.toLocaleString()}
          </Typography>
          <Typography variant="subtitle1">
            Total Value: {formatCurrency(grandTotals.totalVal)}
          </Typography>
        </Box>
      </Box>

      {/* Filtered empty state */}
      {filteredHierarchy.length === 0 && (
        <Alert severity="info">No matching inventory items</Alert>
      )}

      {/* Accordion hierarchy */}
      {filteredHierarchy.map((cat) => (
        <Accordion key={cat.hardwareCategory}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography sx={{ fontWeight: 600 }}>
              {cat.hardwareCategory}
            </Typography>
            <Typography sx={{ ml: 2, color: 'text.secondary' }}>
              — Total: {cat.totalQuantity} | Value: {formatCurrency(cat.totalValue)}
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            {cat.productCodes.map((pc) => (
              <ProductCodeDetail
                key={pc.productCode}
                projectId={projectId}
                category={cat.hardwareCategory}
                productCode={pc.productCode}
                totalQuantity={pc.totalQuantity}
                totalValue={pc.totalValue}
              />
            ))}
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  );
}
