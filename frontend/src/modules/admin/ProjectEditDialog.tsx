import { useState, useCallback } from 'react';
import { Box, Button, Divider, FormControlLabel, Stack, Switch, TextField, Typography } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { UPDATE_PROJECT } from '../../graphql/mutations';
import { GET_ADMIN_PROJECTS } from '../../graphql/queries';

export interface ProjectFormValue {
  id: string;
  projectId: string;
  description: string | null;
  client: string | null;
  jobSiteName: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
  contractor: string | null;
  projectManager: string | null;
  application: string | null;
  gcContactName: string | null;
  gcPhone: string | null;
  gcEmail: string | null;
  offSiteStorageAgreement: boolean;
  // Read-only TITAN references
  submittalJobNo: string | null;
  submittalAssignmentCount: number | null;
  estimatorCode: string | null;
  titanUserId: string | null;
}

interface ProjectEditDialogProps {
  open: boolean;
  project: ProjectFormValue | null;
  onClose: () => void;
}

interface FormState {
  description: string;
  client: string;
  jobSiteName: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  contractor: string;
  projectManager: string;
  application: string;
  gcContactName: string;
  gcPhone: string;
  gcEmail: string;
  offSiteStorageAgreement: boolean;
}

function toForm(p: ProjectFormValue): FormState {
  return {
    description: p.description ?? '',
    client: p.client ?? '',
    jobSiteName: p.jobSiteName ?? '',
    address: p.address ?? '',
    city: p.city ?? '',
    state: p.state ?? '',
    zip: p.zip ?? '',
    contractor: p.contractor ?? '',
    projectManager: p.projectManager ?? '',
    application: p.application ?? '',
    gcContactName: p.gcContactName ?? '',
    gcPhone: p.gcPhone ?? '',
    gcEmail: p.gcEmail ?? '',
    offSiteStorageAgreement: p.offSiteStorageAgreement,
  };
}

function ProjectEditDialogContent({ project, onClose }: { project: ProjectFormValue; onClose: () => void }) {
  const { showToast } = useToast();
  const [form, setForm] = useState<FormState>(() => toForm(project));

  const [updateProject, { loading }] = useMutation(UPDATE_PROJECT, {
    refetchQueries: [{ query: GET_ADMIN_PROJECTS }],
    onCompleted: () => {
      showToast('Project updated', 'success');
      onClose();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const setText = useCallback(
    (key: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [key]: e.target.value })),
    [],
  );

  const handleSubmit = useCallback(() => {
    const input = {
      description: form.description.trim(),
      client: form.client.trim(),
      jobSiteName: form.jobSiteName.trim(),
      address: form.address.trim(),
      city: form.city.trim(),
      state: form.state.trim(),
      zip: form.zip.trim(),
      contractor: form.contractor.trim(),
      projectManager: form.projectManager.trim(),
      application: form.application.trim(),
      gcContactName: form.gcContactName.trim(),
      gcPhone: form.gcPhone.trim(),
      gcEmail: form.gcEmail.trim(),
      offSiteStorageAgreement: form.offSiteStorageAgreement,
    };
    updateProject({ variables: { id: project.id, input } });
  }, [form, project.id, updateProject]);

  const readOnly: Array<[string, string]> = [
    ['Project Number', project.projectId],
    ['Submittal Job No', project.submittalJobNo ?? '—'],
    ['Submittal Assignment Count', project.submittalAssignmentCount?.toString() ?? '—'],
    ['Estimator Code', project.estimatorCode ?? '—'],
    ['TITAN User ID', project.titanUserId ?? '—'],
  ];

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={onClose} disabled={loading}>
        Cancel
      </Button>
      <Button variant="contained" onClick={handleSubmit} disabled={loading}>
        {loading ? 'Saving...' : 'Save'}
      </Button>
    </Stack>
  );

  return (
    <Modal open title={`Edit ${project.projectId}`} onClose={onClose} actions={actions} maxWidth="md">
      <Stack spacing={2} sx={{ pt: 1 }}>
        <FormControlLabel
          control={
            <Switch
              checked={form.offSiteStorageAgreement}
              onChange={(e) => setForm((f) => ({ ...f, offSiteStorageAgreement: e.target.checked }))}
            />
          }
          label="Off-site storage agreement (OSSA)"
        />

        <TextField label="Description" value={form.description} onChange={setText('description')} fullWidth />
        <TextField label="Client" value={form.client} onChange={setText('client')} fullWidth />
        <TextField label="Job Site Name" value={form.jobSiteName} onChange={setText('jobSiteName')} fullWidth />

        <TextField label="Address" value={form.address} onChange={setText('address')} fullWidth />
        <Stack direction="row" spacing={2}>
          <TextField label="City" value={form.city} onChange={setText('city')} fullWidth />
          <TextField label="State" value={form.state} onChange={setText('state')} sx={{ width: 120 }} />
          <TextField label="Zip" value={form.zip} onChange={setText('zip')} sx={{ width: 140 }} />
        </Stack>

        <TextField label="General Contractor" value={form.contractor} onChange={setText('contractor')} fullWidth />
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField label="GC Contact Name" value={form.gcContactName} onChange={setText('gcContactName')} fullWidth />
          <TextField label="GC Phone" value={form.gcPhone} onChange={setText('gcPhone')} fullWidth />
          <TextField label="GC Email" value={form.gcEmail} onChange={setText('gcEmail')} fullWidth />
        </Stack>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField label="Project Manager" value={form.projectManager} onChange={setText('projectManager')} fullWidth />
          <TextField label="Application" value={form.application} onChange={setText('application')} fullWidth />
        </Stack>

        <Divider />
        <Typography variant="subtitle2" color="text.secondary">
          From TITAN (read-only)
        </Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1 }}>
          {readOnly.map(([label, value]) => (
            <Typography key={label} variant="body2">
              <strong>{label}:</strong> {value}
            </Typography>
          ))}
        </Box>
      </Stack>
    </Modal>
  );
}

export default function ProjectEditDialog({ open, project, onClose }: ProjectEditDialogProps) {
  if (!open || !project) return null;
  return <ProjectEditDialogContent project={project} onClose={onClose} />;
}
