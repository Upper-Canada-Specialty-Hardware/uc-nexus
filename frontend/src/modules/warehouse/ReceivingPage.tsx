import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  Fab,
  Paper,
  Chip,
  CircularProgress,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import ReceiveWizard from './ReceiveWizard';
import {
  GET_OPEN_POS,
  GET_PROJECTS,
  GET_RECENT_RECEIVE_RECORDS,
} from '../../graphql/queries';

// ---- Types ----

interface OpenPOLineItem {
  id: string;
  orderedQuantity: number;
  receivedQuantity: number;
}

interface OpenPO {
  id: string;
  poNumber: string | null;
  projectId: string;
  status: string;
  vendorName: string | null;
  orderedAt: string | null;
  expectedDeliveryDate: string | null;
  lineItems: OpenPOLineItem[];
}

interface Project {
  id: string;
  projectId: string;
  description: string | null;
}

interface RecentReceiveRecord {
  receiveRecord: {
    id: string;
    poId: string;
    receivedAt: string;
    receivedBy: string;
  };
  poNumber: string | null;
  totalItemsReceived: number;
}

// ---- Helpers ----

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '\u2014';
  return new Date(dateStr).toLocaleDateString();
}

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString();
}

function isOverdue(expectedDeliveryDate: string | null): boolean {
  if (!expectedDeliveryDate) return false;
  return new Date(expectedDeliveryDate) < new Date(new Date().toDateString());
}

// ---- Component ----

export default function ReceivingPage() {
  const [wizardOpen, setWizardOpen] = useState(false);
  const [preSelectedPOId, setPreSelectedPOId] = useState<string | undefined>();

  // Queries
  const {
    data: openPOsData,
    loading: openPOsLoading,
    error: openPOsError,
  } = useQuery<{ openPOs: OpenPO[] }>(GET_OPEN_POS);

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);

  const {
    data: recentData,
    loading: recentLoading,
    error: recentError,
  } = useQuery<{ recentReceiveRecords: RecentReceiveRecord[] }>(GET_RECENT_RECEIVE_RECORDS, {
    variables: { limit: 10 },
  });

  // Project lookup
  const projectMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of projectsData?.projects ?? []) {
      map.set(p.id, p.description || p.projectId);
    }
    return map;
  }, [projectsData]);

  // PO rows
  const poColumns: GridColDef[] = useMemo(
    () => [
      { field: 'poNumber', headerName: 'PO Number', flex: 0.8 },
      { field: 'vendorName', headerName: 'Vendor', flex: 1 },
      { field: 'projectName', headerName: 'Project', flex: 1 },
      {
        field: 'expectedDeliveryDate',
        headerName: 'Expected Delivery',
        flex: 0.8,
        renderCell: (params) => {
          const date = params.value as string | null;
          const overdue = isOverdue(date);
          return (
            <Typography
              variant="body2"
              color={overdue ? 'error.main' : 'text.primary'}
              sx={{ fontWeight: overdue ? 600 : 400 }}
            >
              {formatDate(date)}
              {overdue && ' (overdue)'}
            </Typography>
          );
        },
      },
      {
        field: 'pendingLines',
        headerName: 'Pending Lines',
        flex: 0.6,
        type: 'number',
      },
      {
        field: 'pendingQty',
        headerName: 'Pending Qty',
        flex: 0.6,
        type: 'number',
      },
      {
        field: 'status',
        headerName: 'Status',
        flex: 0.7,
        renderCell: (params) => {
          const status = params.value as string;
          const color =
            status === 'PARTIALLY_RECEIVED' ? 'warning' : 'info';
          const label = status === 'PARTIALLY_RECEIVED' ? 'Partial' : status === 'VENDOR_CONFIRMED' ? 'Confirmed' : 'Ordered';
          return <Chip label={label} color={color} size="small" />;
        },
      },
    ],
    [],
  );

  const poRows = useMemo(
    () =>
      (openPOsData?.openPOs ?? []).map((po) => {
        const pendingLines = po.lineItems.filter(
          (li) => li.orderedQuantity - li.receivedQuantity > 0,
        ).length;
        const pendingQty = po.lineItems.reduce(
          (sum, li) => sum + Math.max(0, li.orderedQuantity - li.receivedQuantity),
          0,
        );
        return {
          id: po.id,
          poNumber: po.poNumber ?? '\u2014',
          vendorName: po.vendorName ?? '\u2014',
          projectName: projectMap.get(po.projectId) ?? '\u2014',
          expectedDeliveryDate: po.expectedDeliveryDate,
          pendingLines,
          pendingQty,
          status: po.status,
        };
      }),
    [openPOsData, projectMap],
  );

  const recentRecords = recentData?.recentReceiveRecords ?? [];

  // Handlers
  const handlePORowClick = useCallback((params: GridRowParams) => {
    setPreSelectedPOId(params.row.id as string);
    setWizardOpen(true);
  }, []);

  const handleOpenWizard = useCallback(() => {
    setPreSelectedPOId(undefined);
    setWizardOpen(true);
  }, []);

  const handleCloseWizard = useCallback(() => {
    setWizardOpen(false);
    setPreSelectedPOId(undefined);
  }, []);

  return (
    <Box sx={{ position: 'relative', minHeight: '60vh' }}>
      {/* Pending POs Section */}
      <Typography variant="h6" sx={{ mb: 2 }}>
        POs Awaiting Receipt
      </Typography>

      {openPOsLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {openPOsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading purchase orders: {openPOsError.message}
        </Alert>
      )}
      {!openPOsLoading && !openPOsError && poRows.length === 0 && (
        <Alert severity="info" sx={{ mb: 3 }}>
          No purchase orders awaiting receipt.
        </Alert>
      )}
      {!openPOsLoading && !openPOsError && poRows.length > 0 && (
        <Box sx={{ mb: 4 }}>
          <DataTable
            columns={poColumns}
            rows={poRows}
            onRowClick={handlePORowClick}
            sx={{ cursor: 'pointer' }}
            getRowId={(row) => row.id}
          />
        </Box>
      )}

      {/* Recent Activity Section */}
      <Typography variant="h6" sx={{ mb: 2 }}>
        Recent Activity
      </Typography>

      {recentLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {recentError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading recent activity: {recentError.message}
        </Alert>
      )}
      {!recentLoading && !recentError && recentRecords.length === 0 && (
        <Typography color="text.secondary">No recent receiving activity.</Typography>
      )}
      {!recentLoading && !recentError && recentRecords.length > 0 && (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Date</TableCell>
                <TableCell>Received By</TableCell>
                <TableCell>PO Number</TableCell>
                <TableCell align="right">Items Received</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {recentRecords.map((record) => (
                <TableRow key={record.receiveRecord.id}>
                  <TableCell>{formatDateTime(record.receiveRecord.receivedAt)}</TableCell>
                  <TableCell>{record.receiveRecord.receivedBy}</TableCell>
                  <TableCell>{record.poNumber ?? '\u2014'}</TableCell>
                  <TableCell align="right">{record.totalItemsReceived}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* FAB */}
      <Fab
        color="primary"
        aria-label="Receive Items"
        sx={{ position: 'fixed', bottom: 32, right: 32 }}
        onClick={handleOpenWizard}
      >
        <AddIcon />
      </Fab>

      <ReceiveWizard
        open={wizardOpen}
        onClose={handleCloseWizard}
        preSelectedPOId={preSelectedPOId}
      />
    </Box>
  );
}
