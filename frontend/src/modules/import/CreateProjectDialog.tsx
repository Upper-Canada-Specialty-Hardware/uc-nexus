import { useState, useCallback } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Button,
  Stack,
  Alert,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { CREATE_PROJECT } from '../../graphql/mutations';
import { GET_PROJECTS } from '../../graphql/queries';
import { useToast } from '../../components/Toast';
import type { Project } from '../../types/project';

interface CreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function CreateProjectDialog({ open, onClose }: CreateProjectDialogProps) {
  const { showToast } = useToast();
  const [projectId, setProjectId] = useState('');
  const [description, setDescription] = useState('');
  const [client, setClient] = useState('');
  const [numberError, setNumberError] = useState<string | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);

  const [createProject, { loading }] = useMutation<{ createProject: Project }>(CREATE_PROJECT, {
    refetchQueries: [{ query: GET_PROJECTS }],
  });

  const reset = useCallback(() => {
    setProjectId('');
    setDescription('');
    setClient('');
    setNumberError(null);
    setGeneralError(null);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const handleSubmit = useCallback(async () => {
    setNumberError(null);
    setGeneralError(null);

    const trimmedNumber = projectId.trim();
    const trimmedName = description.trim();
    const trimmedClient = client.trim();
    if (!trimmedNumber || !trimmedName || !trimmedClient) {
      setGeneralError('All fields are required.');
      return;
    }

    try {
      await createProject({
        variables: {
          input: {
            projectId: trimmedNumber,
            description: trimmedName,
            client: trimmedClient,
          },
        },
      });
      showToast('Project created.', 'success');
      handleClose();
    } catch (err) {
      if (CombinedGraphQLErrors.is(err)) {
        const conflict = err.errors.find(
          (e) => (e.extensions as { code?: string } | undefined)?.code === 'CONFLICT',
        );
        if (conflict) {
          setNumberError(conflict.message);
          return;
        }
      }
      const message = err instanceof Error ? err.message : 'Failed to create project.';
      setGeneralError(message);
    }
  }, [projectId, description, client, createProject, showToast, handleClose]);

  return (
    <Dialog open={open} onClose={loading ? undefined : handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create New Project</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Project Name"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            fullWidth
            required
            autoFocus
            disabled={loading}
          />
          <TextField
            label="Project Number"
            value={projectId}
            onChange={(e) => {
              setProjectId(e.target.value);
              if (numberError) setNumberError(null);
            }}
            fullWidth
            required
            disabled={loading}
            error={Boolean(numberError)}
            helperText={numberError ?? 'Must be unique across all projects.'}
          />
          <TextField
            label="Client"
            value={client}
            onChange={(e) => setClient(e.target.value)}
            fullWidth
            required
            disabled={loading}
          />
          {generalError && <Alert severity="error">{generalError}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={loading}>
          {loading ? 'Creating…' : 'Create Project'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
