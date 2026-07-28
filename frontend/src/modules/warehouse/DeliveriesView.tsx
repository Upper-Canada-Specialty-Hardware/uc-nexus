import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  ToggleButton,
  ToggleButtonGroup,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Chip,
  CircularProgress,
  Alert,
  Button,
} from '@mui/material';
import { ChevronDown, LayoutGrid } from 'lucide-react';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_EXPECTED_DELIVERIES, GET_BACK_ORDERED_ITEMS } from '../../graphql/warehouse';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import { poVendorName } from '../po/poVendorName';
import type { Project } from '../../types/project';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn, StaggerItem, StaggerList } from '../../motion';

interface POLineItem {
  id: string;
  hardwareCategory: string;
  productCode: string;
  orderedQuantity: number;
  receivedQuantity: number;
  unitCost: number;
}

interface ExpectedDeliveryPO {
  id: string;
  poNumber: string | null;
  requestNumber: string;
  vendorNameSnapshot: string | null;
  vendor: { id: string; name: string } | null;
  expectedDeliveryDate: string | null;
  orderedAt: string | null;
  status: string;
  lineItems: POLineItem[];
}

interface BackOrderedItem {
  hardwareCategory: string;
  productCode: string;
  orderedQuantity: number;
  receivedQuantity: number;
  outstandingQuantity: number;
  unitCost: number;
  poNumber: string | null;
  vendorName: string | null;
  expectedDeliveryDate: string | null;
}

type ViewMode = 'upcoming' | 'outstanding';

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'No date set';
  return new Date(dateStr).toLocaleDateString();
}

function formatCurrency(value: number): string {
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

function getUrgencyColor(dateStr: string | null): 'error' | 'warning' | 'info' | 'default' {
  if (!dateStr) return 'default';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(dateStr);
  date.setHours(0, 0, 0, 0);
  const diffDays = Math.ceil((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return 'error';
  if (diffDays === 0) return 'warning';
  if (diffDays <= 7) return 'info';
  return 'default';
}

function getUrgencyLabel(dateStr: string | null): string {
  if (!dateStr) return '';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(dateStr);
  date.setHours(0, 0, 0, 0);
  const diffDays = Math.ceil((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return `${Math.abs(diffDays)}d overdue`;
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Tomorrow';
  if (diffDays <= 7) return `In ${diffDays}d`;
  return '';
}

// Flat, hairline-bordered group. minWidth:0 keeps a long PO/vendor line from clipping.
const ACCORDION_SX = {
  border: '1px solid',
  borderColor: 'divider',
  borderRadius: 1,
  mb: 1,
  '&:before': { display: 'none' },
  '& .MuiAccordionSummary-content': { minWidth: 0, alignItems: 'center' },
} as const;

function MonoCell({ value }: { value: string | null | undefined }) {
  return (
    <Typography component="span" sx={monoSx}>
      {value == null || value === '' ? '—' : value}
    </Typography>
  );
}

const lineItemColumns: GridColDef[] = [
  {
    field: 'productCode',
    headerName: 'Product Code',
    flex: 1,
    renderCell: (params) => <MonoCell value={params.value as string} />,
  },
  { field: 'hardwareCategory', headerName: 'Category', flex: 1 },
  { field: 'orderedQuantity', headerName: 'Ordered', flex: 0.5, type: 'number' },
  { field: 'receivedQuantity', headerName: 'Received', flex: 0.5, type: 'number' },
  {
    field: 'pending',
    headerName: 'Pending',
    flex: 0.5,
    type: 'number',
    valueGetter: (_v: unknown, row: POLineItem) => row.orderedQuantity - row.receivedQuantity,
  },
  {
    field: 'unitCost',
    headerName: 'Unit Cost',
    flex: 0.7,
    type: 'number',
    valueFormatter: (value: number) => formatCurrency(value),
  },
];

const backOrderColumns: GridColDef[] = [
  {
    field: 'productCode',
    headerName: 'Product Code',
    flex: 1,
    renderCell: (params) => <MonoCell value={params.value as string} />,
  },
  { field: 'hardwareCategory', headerName: 'Category', flex: 1 },
  { field: 'vendorName', headerName: 'Vendor', flex: 1, valueFormatter: (v: string | null) => v ?? '—' },
  {
    field: 'poNumber',
    headerName: 'PO #',
    flex: 0.7,
    valueFormatter: (v: string | null) => v ?? '—',
    renderCell: (params) => <MonoCell value={params.value as string | null} />,
  },
  { field: 'outstandingQuantity', headerName: 'Outstanding', flex: 0.6, type: 'number' },
  {
    field: 'expectedDeliveryDate',
    headerName: 'Expected',
    flex: 0.8,
    valueFormatter: (v: string | null) => formatDate(v),
  },
  {
    field: 'urgency',
    headerName: '',
    width: 100,
    sortable: false,
    renderCell: (params: { row: BackOrderedItem }) => {
      const label = getUrgencyLabel(params.row.expectedDeliveryDate);
      if (!label) return null;
      return <Chip label={label} color={getUrgencyColor(params.row.expectedDeliveryDate)} size="small" variant="outlined" />;
    },
  },
];

function UpcomingView({ projectId }: { projectId: string }) {
  const { data, loading, error } = useQuery<{ expectedDeliveries: ExpectedDeliveryPO[] }>(
    GET_EXPECTED_DELIVERIES,
    { variables: { projectId } },
  );

  const deliveries = data?.expectedDeliveries ?? [];

  if (loading && !data) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;
  }
  if (error) return <Alert severity="error">Error: {error.message}</Alert>;
  if (deliveries.length === 0) return <Alert severity="info">No active purchase orders with outstanding items</Alert>;

  return (
    <Box>
      <StaggerList count={deliveries.length}>
        {deliveries.map((po) => {
          const urgency = getUrgencyColor(po.expectedDeliveryDate);
          const urgencyLabel = getUrgencyLabel(po.expectedDeliveryDate);
          const pendingItems = po.lineItems.filter((li) => li.orderedQuantity > li.receivedQuantity);
          return (
            <StaggerItem key={po.id}>
              <Accordion disableGutters elevation={0} sx={ACCORDION_SX}>
                <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1.5,
                      flex: 1,
                      minWidth: 0,
                      mr: 2,
                      flexWrap: 'wrap',
                    }}
                  >
                    <Typography sx={{ ...monoSx, fontWeight: 700 }}>
                      {po.poNumber ?? po.requestNumber}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" noWrap sx={{ minWidth: 0 }}>
                      {poVendorName(po) || 'No vendor'}
                    </Typography>
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ ...tabularSx, ml: 'auto', flexShrink: 0 }}
                    >
                      {formatDate(po.expectedDeliveryDate)}
                    </Typography>
                    {urgencyLabel && (
                      <Chip label={urgencyLabel} color={urgency} size="small" variant="outlined" />
                    )}
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  {pendingItems.length > 0 ? (
                    <Box sx={{ height: 250, width: '100%' }}>
                      <DataGrid
                        rows={pendingItems}
                        columns={lineItemColumns}
                        pageSizeOptions={[5, 10]}
                        initialState={{ pagination: { paginationModel: { pageSize: 5 } } }}
                        disableRowSelectionOnClick
                        density="compact"
                      />
                    </Box>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      All items received
                    </Typography>
                  )}
                </AccordionDetails>
              </Accordion>
            </StaggerItem>
          );
        })}
      </StaggerList>
    </Box>
  );
}

function OutstandingView({ projectId }: { projectId: string }) {
  const { data, loading, error } = useQuery<{ backOrderedItems: BackOrderedItem[] }>(
    GET_BACK_ORDERED_ITEMS,
    { variables: { projectId } },
  );

  const items = useMemo(() => {
    return (data?.backOrderedItems ?? []).map((item, i) => ({ ...item, id: `${item.poNumber}-${item.productCode}-${i}` }));
  }, [data]);

  if (loading && !data) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;
  }
  if (error) return <Alert severity="error">Error: {error.message}</Alert>;
  if (items.length === 0) return <Alert severity="info">No outstanding back-ordered items</Alert>;

  return (
    <Box sx={{ height: 500, width: '100%' }}>
      <DataGrid
        rows={items}
        columns={backOrderColumns}
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        disableRowSelectionOnClick
        density="compact"
      />
    </Box>
  );
}

export default function DeliveriesView() {
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('upcoming');

  if (!selectedProject) {
    return <ProjectLandingPage title="Deliveries" onSelect={setSelectedProject} />;
  }

  const projectId = selectedProject.id;
  const projectLabel = selectedProject.description || selectedProject.projectId;

  return (
    <Box>
      {/* One affordance, not a stack of them: the shell's breadcrumbs cover the module, so the only
          navigation here is the project switch. */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 2,
          flexWrap: 'wrap',
          mb: 2,
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography component="div" sx={microLabelSx}>
            Deliveries
          </Typography>
          <Typography variant="h5" sx={{ lineHeight: 1.2 }}>
            {projectLabel}
          </Typography>
        </Box>
        <Button
          size="small"
          variant="outlined"
          startIcon={<LayoutGrid size={18} strokeWidth={1.75} />}
          onClick={() => setSelectedProject(null)}
        >
          Projects
        </Button>
      </Box>

      <ToggleButtonGroup
        value={viewMode}
        exclusive
        onChange={(_, v) => { if (v) setViewMode(v); }}
        size="small"
        sx={{ mb: 2 }}
      >
        <ToggleButton value="upcoming">Upcoming Deliveries</ToggleButton>
        <ToggleButton value="outstanding">Outstanding Items</ToggleButton>
      </ToggleButtonGroup>

      <FadeIn key={viewMode} y={8}>
        {viewMode === 'upcoming' ? (
          <UpcomingView projectId={projectId} />
        ) : (
          <OutstandingView projectId={projectId} />
        )}
      </FadeIn>
    </Box>
  );
}
