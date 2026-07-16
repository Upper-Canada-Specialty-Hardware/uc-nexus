import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useMutation, useQuery } from '@apollo/client/react';
import { GET_BUYER_ASSIGNMENTS, GET_PROJECTS } from '../../graphql/queries';
import { DELETE_BUYER_ASSIGNMENT, SAVE_BUYER_ASSIGNMENT } from '../../graphql/mutations';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import type { Project } from '../../types/project';

interface AssignmentProject {
  id: string;
  projectId: string;
  description: string | null;
}

interface BuyerAssignmentRow {
  buyerId: string;
  costCodes: string[];
  projects: AssignmentProject[];
}

function projectLabel(p: { projectId: string; description: string | null }): string {
  return p.description ? `${p.projectId} · ${p.description}` : p.projectId;
}

export default function BuyersPage() {
  const { isAdmin } = useIdentity();
  const { showToast } = useToast();

  const { data, loading } = useQuery<{ buyerAssignments: BuyerAssignmentRow[] }>(GET_BUYER_ASSIGNMENTS, {
    skip: !isAdmin,
    fetchPolicy: 'cache-and-network',
  });
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS, { skip: !isAdmin });
  const projects = useMemo(() => projectsData?.projects ?? [], [projectsData]);
  const rows = useMemo(() => data?.buyerAssignments ?? [], [data]);

  // Edit dialog state. isNew drives whether the buyer id is editable (it's the row key).
  const [editOpen, setEditOpen] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [buyerId, setBuyerId] = useState('');
  const [selectedProjects, setSelectedProjects] = useState<Project[]>([]);
  const [costCodesText, setCostCodesText] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const [saveAssignment, { loading: saving }] = useMutation(SAVE_BUYER_ASSIGNMENT, {
    refetchQueries: [{ query: GET_BUYER_ASSIGNMENTS }],
    onCompleted: () => {
      showToast('Buyer assignment saved', 'success');
      setEditOpen(false);
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const [deleteAssignment] = useMutation(DELETE_BUYER_ASSIGNMENT, {
    refetchQueries: [{ query: GET_BUYER_ASSIGNMENTS }],
    onCompleted: () => {
      showToast('Buyer assignment deleted', 'success');
      setDeleteTarget(null);
    },
    onError: (err) => {
      showToast(err.message, 'error');
      setDeleteTarget(null);
    },
  });

  const openNew = useCallback(() => {
    setIsNew(true);
    setBuyerId('');
    setSelectedProjects([]);
    setCostCodesText('');
    setEditOpen(true);
  }, []);

  const openEdit = useCallback(
    (row: BuyerAssignmentRow) => {
      setIsNew(false);
      setBuyerId(row.buyerId);
      const assignedIds = new Set(row.projects.map((p) => p.id));
      setSelectedProjects(projects.filter((p) => assignedIds.has(p.id)));
      setCostCodesText(row.costCodes.join('\n'));
      setEditOpen(true);
    },
    [projects],
  );

  const handleSave = useCallback(() => {
    saveAssignment({
      variables: {
        buyerId: buyerId.trim(),
        projectIds: selectedProjects.map((p) => p.id),
        costCodes: costCodesText
          .split('\n')
          .map((c) => c.trim())
          .filter(Boolean),
      },
    });
  }, [saveAssignment, buyerId, selectedProjects, costCodesText]);

  const columns = useMemo<GridColDef[]>(
    () => [
      { field: 'buyerId', headerName: 'GP Buyer', width: 160 },
      {
        field: 'projects',
        headerName: 'Assigned Projects',
        flex: 2,
        sortable: false,
        renderCell: (params) => (
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', py: 0.5 }}>
            {(params.row.projects as AssignmentProject[]).length > 0
              ? (params.row.projects as AssignmentProject[]).map((p) => (
                  <Chip key={p.id} size="small" label={projectLabel(p)} />
                ))
              : '—'}
          </Box>
        ),
      },
      {
        field: 'costCodes',
        headerName: 'Designated Cost Codes',
        flex: 1,
        sortable: false,
        valueGetter: (_value: unknown, row: BuyerAssignmentRow) =>
          row.costCodes.length > 0 ? row.costCodes.join(', ') : '—',
      },
      {
        field: 'actions',
        headerName: '',
        width: 60,
        sortable: false,
        filterable: false,
        renderCell: (params) => (
          <IconButton
            size="small"
            color="error"
            aria-label={`Delete assignment for ${params.row.buyerId}`}
            onClick={(e) => {
              e.stopPropagation();
              setDeleteTarget(params.row.buyerId);
            }}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        ),
      },
    ],
    [],
  );

  if (!isAdmin) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        You do not have permission to manage buyers. The Admin/Manager role is required.
      </Alert>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h5">Buyers</Typography>
          <Typography variant="body2" color="text.secondary">
            Which projects each GP buyer may create POs for, and their designated cost codes. A buyer
            with no assignment cannot create project POs. Link accounts to buyers in User Management.
          </Typography>
        </Box>
        <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={openNew}>
          Add Buyer
        </Button>
      </Box>

      <DataGrid
        rows={rows}
        columns={columns}
        getRowId={(row) => row.buyerId}
        loading={loading}
        density="compact"
        getRowHeight={() => 'auto'}
        disableRowSelectionOnClick
        onRowClick={(params: GridRowParams<BuyerAssignmentRow>) => openEdit(params.row)}
        hideFooter={rows.length <= 25}
        autoHeight
      />

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{isNew ? 'Add Buyer Assignment' : `Edit Buyer: ${buyerId}`}</DialogTitle>
        <DialogContent>
          <TextField
            label="GP Buyer ID"
            value={buyerId}
            onChange={(e) => setBuyerId(e.target.value)}
            size="small"
            fullWidth
            disabled={!isNew}
            sx={{ mt: 1, mb: 2 }}
            helperText={isNew ? 'The GP BUYERID exactly as it appears in GP (POP00101)' : ''}
          />
          <Autocomplete
            multiple
            options={projects}
            value={selectedProjects}
            onChange={(_, next) => setSelectedProjects(next)}
            getOptionLabel={(p) => projectLabel(p)}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            renderInput={(params) => <TextField {...params} label="Assigned projects" size="small" />}
            sx={{ mb: 2 }}
          />
          <TextField
            label="Designated cost codes"
            value={costCodesText}
            onChange={(e) => setCostCodesText(e.target.value)}
            size="small"
            fullWidth
            multiline
            minRows={3}
            maxRows={8}
            placeholder={'310-000\n210-200'}
            helperText="One per line, as 'cc1-cc2' (the code without the element digit)"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSave} disabled={saving || !buyerId.trim()}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete buyer assignment?"
        message={`Buyer '${deleteTarget}' will no longer be able to create project POs.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={() => deleteAssignment({ variables: { buyerId: deleteTarget } })}
        onCancel={() => setDeleteTarget(null)}
      />
    </Box>
  );
}
