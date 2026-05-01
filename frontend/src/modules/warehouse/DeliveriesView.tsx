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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_EXPECTED_DELIVERIES, GET_BACK_ORDERED_ITEMS } from '../../graphql/queries';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import type { Project } from '../../types/project';

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

const lineItemColumns: GridColDef[] = [
  { field: 'productCode', headerName: 'Product Code', flex: 1 },
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
  { field: 'productCode', headerName: 'Product Code', flex: 1 },
  { field: 'hardwareCategory', headerName: 'Category', flex: 1 },
  { field: 'vendorName', headerName: 'Vendor', flex: 1, valueFormatter: (v: string | null) => v ?? '—' },
  { field: 'poNumber', headerName: 'PO #', flex: 0.7, valueFormatter: (v: string | null) => v ?? '—' },
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
      {deliveries.map((po) => {
        const urgency = getUrgencyColor(po.expectedDeliveryDate);
        const urgencyLabel = getUrgencyLabel(po.expectedDeliveryDate);
        const pendingItems = po.lineItems.filter((li) => li.orderedQuantity > li.receivedQuantity);
        return (
          <Accordion key={po.id}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1, mr: 2 }}>
                <Typography sx={{ fontWeight: 600 }}>{po.poNumber ?? po.requestNumber}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {po.vendor?.name ?? 'No vendor'}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ ml: 'auto' }}>
                  {formatDate(po.expectedDeliveryDate)}
                </Typography>
                {urgencyLabel && <Chip label={urgencyLabel} color={urgency} size="small" variant="outlined" />}
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
                <Typography color="text.secondary">All items received</Typography>
              )}
            </AccordionDetails>
          </Accordion>
        );
      })}
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
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <Button size="small" startIcon={<ArrowBackIcon />} onClick={() => setSelectedProject(null)}>
          Projects
        </Button>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{projectLabel}</Typography>
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

      {viewMode === 'upcoming' ? (
        <UpcomingView projectId={projectId} />
      ) : (
        <OutstandingView projectId={projectId} />
      )}
    </Box>
  );
}
