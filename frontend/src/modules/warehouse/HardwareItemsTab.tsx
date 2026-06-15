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
  Chip,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useLazyQuery, useMutation } from '@apollo/client/react';
import { GET_INVENTORY_HIERARCHY, GET_INVENTORY_ITEMS, GET_INVENTORY_BY_VENDOR } from '../../graphql/queries';
import { REPORT_INVENTORY_DEFICIENCY } from '../../graphql/mutations';
import { WAREHOUSE_REFETCH_QUERIES } from '../../graphql/refetch';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import InventoryCorrectionModal from '../admin/InventoryCorrectionModal';
import AuditHistoryDrawer from './AuditHistoryDrawer';
import SpotCheckModal from './SpotCheckModal';
import DestockInventoryModal from './stock/DestockInventoryModal';

interface InventoryItem {
  id: string;
  projectId: string;
  poLineItemId: string | null;
  receiveLineItemId: string | null;
  stockItemId: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  deficientQuantity: number;
  available: number;
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

interface VendorGroup {
  vendorName: string;
  totalQuantity: number;
  totalValue: number;
  productCodes: ProductCodeGroup[];
}

type GroupBy = 'category' | 'vendor';

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
    field: 'deficient',
    headerName: 'Deficient',
    flex: 0.5,
    type: 'number',
    valueGetter: (_v: unknown, row: InventoryItemDetail) =>
      row.inventoryLocation.deficientQuantity ?? 0,
    renderCell: (params: { row: InventoryItemDetail }) => {
      const dq = params.row.inventoryLocation.deficientQuantity ?? 0;
      return dq > 0 ? <Chip label={dq} color="warning" size="small" /> : <span>0</span>;
    },
  },
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

  // Audit history drawer state
  const [auditItemId, setAuditItemId] = useState<string | null>(null);
  const [auditLabel, setAuditLabel] = useState<string>('');
  const [auditOpen, setAuditOpen] = useState(false);

  // Spot check modal state
  const [spotCheckItem, setSpotCheckItem] = useState<InventoryItem | null>(null);
  const [spotCheckOpen, setSpotCheckOpen] = useState(false);

  // Destock modal
  const [destockItem, setDestockItem] = useState<InventoryItem | null>(null);

  // Report deficient — uses prompt for the qty (lightweight; can be upgraded later)
  const { showToast } = useToast();
  const [reportDeficient] = useMutation(REPORT_INVENTORY_DEFICIENCY, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Deficient quantity flagged on row', 'success');
      fetchItems({ variables: { projectId, category, productCode } });
    },
    onError: (err) => showToast(err.message, 'error'),
  });

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
    const historyCol: GridColDef = {
      field: 'history',
      headerName: '',
      width: 80,
      sortable: false,
      filterable: false,
      renderCell: (params: { row: InventoryItemDetail }) => (
        <Button
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            setAuditItemId(params.row.inventoryLocation.id);
            setAuditLabel(`${params.row.inventoryLocation.productCode} — ${params.row.inventoryLocation.hardwareCategory}`);
            setAuditOpen(true);
          }}
        >
          History
        </Button>
      ),
    };
    const spotCheckCol: GridColDef = {
      field: 'spotCheck',
      headerName: '',
      width: 100,
      sortable: false,
      filterable: false,
      renderCell: (params: { row: InventoryItemDetail }) => (
        <Button
          size="small"
          color="warning"
          onClick={(e) => {
            e.stopPropagation();
            setSpotCheckItem(params.row.inventoryLocation);
            setSpotCheckOpen(true);
          }}
        >
          Spot Check
        </Button>
      ),
    };
    const destockCol: GridColDef = {
      field: 'destock',
      headerName: '',
      width: 100,
      sortable: false,
      filterable: false,
      renderCell: (params: { row: InventoryItemDetail }) => (
        <Button
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            setDestockItem(params.row.inventoryLocation);
          }}
          disabled={params.row.inventoryLocation.quantity <= 0}
        >
          Destock
        </Button>
      ),
    };
    const reportDefCol: GridColDef = {
      field: 'reportDeficient',
      headerName: '',
      width: 110,
      sortable: false,
      filterable: false,
      renderCell: (params: { row: InventoryItemDetail }) => (
        <Button
          size="small"
          color="warning"
          onClick={(e) => {
            e.stopPropagation();
            const il = params.row.inventoryLocation;
            const avail = il.available ?? il.quantity - (il.deficientQuantity ?? 0);
            if (avail <= 0) {
              showToast('Nothing left to flag — all units already deficient', 'info');
              return;
            }
            const input = window.prompt(`Flag how many of ${il.productCode} as deficient? (max ${avail})`, '1');
            if (!input) return;
            const q = Number(input);
            if (!Number.isInteger(q) || q < 1 || q > avail) {
              showToast('Invalid quantity', 'error');
              return;
            }
            const reason = window.prompt('Reason (optional)', '') || null;
            reportDeficient({
              variables: {
                input: {
                  inventoryLocationId: il.id,
                  quantity: q,
                  reasonText: reason,
                  performedBy: 'Warehouse',
                },
              },
            });
          }}
          disabled={
            (params.row.inventoryLocation.available ?? params.row.inventoryLocation.quantity) <= 0
          }
        >
          Flag Deficient
        </Button>
      ),
    };
    if (!isAdmin) return [...baseDetailColumns, destockCol, reportDefCol, spotCheckCol, historyCol];
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
      destockCol,
      reportDefCol,
      spotCheckCol,
      historyCol,
    ];
  }, [isAdmin, reportDeficient, showToast]);

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

      {auditItemId && (
        <AuditHistoryDrawer
          open={auditOpen}
          onClose={() => {
            setAuditOpen(false);
            setAuditItemId(null);
          }}
          entityId={auditItemId}
          entityType="INVENTORY_LOCATION"
          label={auditLabel}
        />
      )}

      {spotCheckItem && (
        <SpotCheckModal
          open={spotCheckOpen}
          onClose={() => {
            setSpotCheckOpen(false);
            setSpotCheckItem(null);
          }}
          item={spotCheckItem}
          onSuccess={handleCorrectionSuccess}
        />
      )}

      {destockItem && (
        <DestockInventoryModal
          inventoryLocation={destockItem}
          onClose={() => setDestockItem(null)}
          onSuccess={() => {
            setDestockItem(null);
            handleCorrectionSuccess();
          }}
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
  const [groupBy, setGroupBy] = useState<GroupBy>('category');

  const { data, loading, error } = useQuery<{
    inventoryHierarchy: CategoryGroup[];
  }>(GET_INVENTORY_HIERARCHY, {
    variables: { projectId },
    skip: groupBy !== 'category',
  });

  const { data: vendorData, loading: vendorLoading, error: vendorError } = useQuery<{
    inventoryByVendor: VendorGroup[];
  }>(GET_INVENTORY_BY_VENDOR, {
    variables: { projectId },
    skip: groupBy !== 'vendor',
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
  const vendorHierarchy = vendorData?.inventoryByVendor ?? [];

  // Use whichever data source is active
  const activeGroups: { label: string; totalQuantity: number; totalValue: number; productCodes: ProductCodeGroup[] }[] = useMemo(() => {
    if (groupBy === 'vendor') {
      return vendorHierarchy.map((v) => ({ label: v.vendorName, ...v }));
    }
    return hierarchy.map((c) => ({ label: c.hardwareCategory, ...c }));
  }, [groupBy, hierarchy, vendorHierarchy]);

  // Extract distinct categories (for category filter, only in category mode)
  const categories = useMemo(
    () => [...new Set(hierarchy.map((c) => c.hardwareCategory))].sort(),
    [hierarchy],
  );

  // Extract distinct aisle values from Level 3 items
  const aisles = useMemo(() => {
    const aisleSet = new Set<string>();
    const groups = groupBy === 'vendor' ? vendorHierarchy : hierarchy;
    groups.forEach((g) =>
      g.productCodes.forEach((pc) =>
        pc.items.forEach((item) => {
          if (item.aisle) aisleSet.add(item.aisle);
        }),
      ),
    );
    return [...aisleSet].sort();
  }, [groupBy, hierarchy, vendorHierarchy]);

  // Filter hierarchy
  const filteredGroups = useMemo(() => {
    const search = debouncedSearch.toLowerCase();
    return activeGroups
      .filter((group) => {
        if (groupBy === 'category' && categoryFilter && group.label !== categoryFilter) return false;
        if (search) {
          const labelMatch = group.label.toLowerCase().includes(search);
          const productMatch = group.productCodes.some((pc) =>
            pc.productCode.toLowerCase().includes(search),
          );
          if (!labelMatch && !productMatch) return false;
        }
        return true;
      })
      .map((group) => {
        if (search) {
          const labelMatch = group.label.toLowerCase().includes(search);
          if (labelMatch) return group;
          return {
            ...group,
            productCodes: group.productCodes.filter((pc) =>
              pc.productCode.toLowerCase().includes(search),
            ),
          };
        }
        if (aisleFilter) {
          return {
            ...group,
            productCodes: group.productCodes.filter((pc) =>
              pc.items.some((item) => item.aisle === aisleFilter),
            ),
          };
        }
        return group;
      })
      .filter((group) => group.productCodes.length > 0);
  }, [activeGroups, debouncedSearch, categoryFilter, aisleFilter, groupBy]);

  const grandTotals = useMemo(() => {
    const totalQty = filteredGroups.reduce((sum, g) => sum + g.totalQuantity, 0);
    const totalVal = filteredGroups.reduce((sum, g) => sum + g.totalValue, 0);
    return { totalQty, totalVal };
  }, [filteredGroups]);

  const isLoading = groupBy === 'category' ? loading && !data : vendorLoading && !vendorData;
  const activeError = groupBy === 'category' ? error : vendorError;

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (activeError) {
    return <Alert severity="error">Error loading inventory: {activeError.message}</Alert>;
  }

  if (activeGroups.length === 0) {
    return (
      <Alert severity="info">No inventory items for this project</Alert>
    );
  }

  return (
    <Box>
      {/* Search and filter controls */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <ToggleButtonGroup
          value={groupBy}
          exclusive
          onChange={(_, v) => { if (v) setGroupBy(v); }}
          size="small"
        >
          <ToggleButton value="category">By Category</ToggleButton>
          <ToggleButton value="vendor">By Vendor</ToggleButton>
        </ToggleButtonGroup>
        <TextField
          label="Search"
          placeholder="Search by product code or category..."
          size="small"
          value={searchTerm}
          onChange={handleSearchChange}
          sx={{ minWidth: 250 }}
        />
        {groupBy === 'category' && (
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
        )}
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
      {filteredGroups.length === 0 && (
        <Alert severity="info">No matching inventory items</Alert>
      )}

      {/* Accordion hierarchy */}
      {filteredGroups.map((group) => (
        <Accordion key={group.label}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography sx={{ fontWeight: 600 }}>
              {group.label}
            </Typography>
            <Typography sx={{ ml: 2, color: 'text.secondary' }}>
              — Total: {group.totalQuantity} | Value: {formatCurrency(group.totalValue)}
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            {group.productCodes.map((pc) => (
              <ProductCodeDetail
                key={pc.productCode}
                projectId={projectId}
                category={pc.items[0]?.hardwareCategory ?? ''}
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
