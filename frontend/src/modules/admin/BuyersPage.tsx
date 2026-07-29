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
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { AlertTriangle, Plus, Trash2 } from 'lucide-react';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { useMutation, useQuery } from '@apollo/client/react';
import { GET_BUYER_ASSIGNMENTS, GET_PROJECTS } from '../../graphql/shared';
import { DELETE_BUYER_ASSIGNMENT, SAVE_BUYER_ASSIGNMENT } from '../../graphql/admin';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { FONT_MONO, microLabelSx, monoSx } from '../../theme';
import { FadeIn } from '../../motion';
import GpBuyerSelect from './GpBuyerSelect';
import RegisterGpBuyerDialog from './RegisterGpBuyerDialog';
import { useGpBuyers } from './useGpBuyers';
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
  const [registerOpen, setRegisterOpen] = useState(false);

  // Issue #409: GP's live buyer master. Polled for the whole page, not just the dialog - the panel
  // below renders it, and the grid uses it to flag assignments for ids GP never registered.
  const gpBuyers = useGpBuyers({ skip: !isAdmin });
  const registeredIds = useMemo(() => new Set(gpBuyers.buyers.map((b) => b.buyerId)), [gpBuyers.buyers]);
  // Only meaningful once the list actually loaded: an unavailable read would otherwise flag every row.
  const canFlagUnregistered = !gpBuyers.unavailable && !gpBuyers.loading && gpBuyers.buyers.length > 0;

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
      {
        field: 'buyerId',
        headerName: 'GP Buyer',
        width: 190,
        renderCell: (params) => {
          // #409: an assignment for an id GP never registered can never produce a PO - taPoHdr rejects
          // the BUYERID (error 269). Free text made these easy to create and invisible afterwards.
          const unregistered = canFlagUnregistered && !registeredIds.has(params.row.buyerId);
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                {params.row.buyerId}
              </Box>
              {unregistered && (
                <Tooltip title="Not registered in GP (POP00101). POs for this buyer will be rejected.">
                  <Box component="span" sx={{ display: 'flex', color: 'warning.main' }}>
                    <AlertTriangle size={15} strokeWidth={2} aria-label="Not registered in GP" />
                  </Box>
                </Tooltip>
              )}
            </Box>
          );
        },
      },
      {
        field: 'projects',
        headerName: 'Assigned Projects',
        flex: 2,
        sortable: false,
        renderCell: (params) => (
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', py: 0.5 }}>
            {(params.row.projects as AssignmentProject[]).length > 0
              ? (params.row.projects as AssignmentProject[]).map((p) => (
                  <Chip key={p.id} size="small" variant="outlined" label={projectLabel(p)} />
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
        renderCell: (params) => {
          const codes = (params.row as BuyerAssignmentRow).costCodes;
          return (
            <Box component="span" sx={codes.length > 0 ? monoSx : undefined}>
              {codes.length > 0 ? codes.join(', ') : '—'}
            </Box>
          );
        },
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
            <Trash2 size={18} strokeWidth={1.75} />
          </IconButton>
        ),
      },
    ],
    [canFlagUnregistered, registeredIds],
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
      <FadeIn>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, mb: 2 }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="h5" sx={{ mb: 0.25 }}>
              Buyers
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Which projects each GP buyer may create POs for, and their designated cost codes. A buyer
              with no assignment cannot create project POs. Link accounts to buyers in User Management.
            </Typography>
          </Box>
          <Button
            variant="contained"
            size="small"
            startIcon={<Plus size={18} strokeWidth={1.75} />}
            onClick={openNew}
            sx={{ flexShrink: 0 }}
          >
            Add Buyer
          </Button>
        </Box>
      </FadeIn>

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
        sx={{ '& .MuiDataGrid-row': { cursor: 'pointer' } }}
      />

      {/* Issue #409: GP's own buyer master, so an admin can see what exists and add to it without
          opening GP. Separate from the grid above because the two are different things: this is who
          GP knows as a buyer, that is what each buyer is allowed to do here. */}
      <Paper variant="outlined" sx={{ mt: 3, p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, mb: 1.5 }}>
          <Box sx={{ flex: 1 }}>
            <Typography component="div" sx={microLabelSx}>
              Registered in GP
            </Typography>
            <Typography variant="body2" color="text.secondary">
              GP&apos;s buyer master (POP00101) for {gpBuyers.company || 'the connected company'}. A buyer must
              be registered here before an account can be linked to it. Removing one is still a GP task.
            </Typography>
          </Box>
          <Button
            variant="outlined"
            size="small"
            startIcon={<Plus size={18} strokeWidth={1.75} />}
            onClick={() => setRegisterOpen(true)}
            disabled={gpBuyers.unavailable}
            sx={{ flexShrink: 0 }}
          >
            Register GP Buyer
          </Button>
        </Box>

        {gpBuyers.unavailable ? (
          <Alert severity="warning" sx={{ mt: 1 }}>
            {gpBuyers.unsupported
              ? 'The connected relay is too old to list GP buyers. Update the relay on that workstation, then reload this page.'
              : gpBuyers.relayConnected
                ? `Could not read the buyer master from GP. ${gpBuyers.error?.message ?? ''}`
                : 'The GP relay is not connected, so the buyer master cannot be read or added to.'}
          </Alert>
        ) : gpBuyers.buyers.length === 0 && !gpBuyers.loading ? (
          <Typography variant="body2" color="text.secondary">
            No buyers are registered in this GP company yet.
          </Typography>
        ) : (
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
            {gpBuyers.buyers.map((b) => (
              <Chip
                key={b.buyerId}
                size="small"
                variant="outlined"
                label={b.description ? `${b.buyerId} · ${b.description}` : b.buyerId}
                sx={{ '& .MuiChip-label': { fontFamily: FONT_MONO } }}
              />
            ))}
          </Stack>
        )}
      </Paper>

      <RegisterGpBuyerDialog
        open={registerOpen}
        company={gpBuyers.company}
        onClose={() => setRegisterOpen(false)}
      />

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{isNew ? 'Add Buyer Assignment' : `Edit Buyer: ${buyerId}`}</DialogTitle>
        <DialogContent>
          {/* #409: picked from GP's buyer master rather than typed. Still locked on an existing
              assignment - the buyer id is the row key, so changing it would be a different row. */}
          <Box sx={{ mt: 1, mb: 2 }}>
            <GpBuyerSelect
              value={buyerId || null}
              onChange={(next) => setBuyerId(next ?? '')}
              state={gpBuyers}
              disabled={!isNew}
              fullWidth
              helperText={isNew ? 'Only buyers registered in GP (POP00101) can be assigned' : ''}
            />
          </Box>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Scope
          </Typography>
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
            sx={{ '& .MuiInputBase-input': { fontFamily: FONT_MONO } }}
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
        confirmColor="error"
        cancelLabel="Cancel"
        onConfirm={() => deleteAssignment({ variables: { buyerId: deleteTarget } })}
        onCancel={() => setDeleteTarget(null)}
      />
    </Box>
  );
}
