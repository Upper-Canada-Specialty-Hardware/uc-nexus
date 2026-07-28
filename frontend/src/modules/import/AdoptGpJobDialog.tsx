import { useState, useCallback } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Autocomplete,
  Button,
  IconButton,
  Stack,
  Alert,
  Typography,
} from '@mui/material';
import { RefreshCw } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { ADOPT_GP_JOB, GET_GP_JOBS } from '../../graphql/import';
import { GET_PROJECTS } from '../../graphql/shared';
import { useToast } from '../../components/Toast';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { useRelayStatus } from '../../relay/useRelayStatus';
import type { Project } from '../../types/project';
import { monoSx, microLabelSx } from '../../theme';

interface GpJobOption {
  jobNumber: string;
  jobName: string | null;
}

interface AdoptGpJobDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function AdoptGpJobDialog({ open, onClose }: AdoptGpJobDialogProps) {
  const { showToast } = useToast();
  const [selectedJob, setSelectedJob] = useState<GpJobOption | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);

  // The connected relay is enrolled for exactly one company, so the company is the relay's, shown
  // read-only rather than picked. skip: !open so a hidden dialog doesn't poll.
  const relay = useRelayStatus({ skip: !open });
  const company = relay.company ?? '';
  const relayConnected = relay.connected === true;

  // The live GP job master (JC00102) for this company, via the connected relay - this IS the
  // project picker: adopting a project means picking one of these, not typing a free-form number.
  // cache-first so reopening reuses the loaded list; the refresh control forces a re-pull from GP.
  const {
    data: jobsData,
    loading: jobsLoading,
    error: jobsFetchError,
    refetch: refetchJobs,
  } = useQuery<{ gpJobs: GpJobOption[] }>(GET_GP_JOBS, {
    variables: { company },
    skip: !open || !relayConnected || !company,
    fetchPolicy: 'cache-first',
  });
  const jobs = jobsData?.gpJobs ?? [];

  const [adoptGpJob, { loading }] = useMutation<{ adoptGpJob: Project }>(ADOPT_GP_JOB, {
    refetchQueries: [{ query: GET_PROJECTS }],
  });

  const reset = useCallback(() => {
    setSelectedJob(null);
    setJobError(null);
    setGeneralError(null);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const handleSubmit = useCallback(async () => {
    setJobError(null);
    setGeneralError(null);

    if (!selectedJob) {
      setJobError('Select a GP job to adopt');
      return;
    }

    try {
      await adoptGpJob({
        variables: {
          input: {
            jobNumber: selectedJob.jobNumber,
            jobName: selectedJob.jobName,
          },
        },
      });
      showToast('Project adopted from GP.', 'success');
      handleClose();
    } catch (err) {
      if (CombinedGraphQLErrors.is(err)) {
        // Both land on the job field: already-adopted (CONFLICT) and, since #314, "GP has no such
        // job" - the backend now verifies the number against the live job master rather than
        // trusting what the client posted, so a stale picker or a direct call is rejected here.
        const onJobField = err.errors.find((e) => {
          const ext = e.extensions as { code?: string; field?: string } | undefined;
          return ext?.code === 'CONFLICT' || (ext?.code === 'VALIDATION_ERROR' && ext?.field === 'job_number');
        });
        if (onJobField) {
          setJobError(onJobField.message);
          return;
        }
      }
      const message = err instanceof Error ? err.message : 'Failed to adopt GP job.';
      setGeneralError(message);
    }
  }, [selectedJob, adoptGpJob, showToast, handleClose]);

  return (
    <Dialog open={open} onClose={loading ? undefined : handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Adopt a GP Job</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {generalError && <Alert severity="error">{generalError}</Alert>}
          <Stack direction="row" spacing={2} alignItems="center">
            {/* The connected relay is enrolled for exactly one company, so this is read-only, not a pick. */}
            <TextField
              label="GP company"
              value={company || '—'}
              size="small"
              disabled
              sx={{ minWidth: 140 }}
              slotProps={{ input: { sx: monoSx } }}
            />
            <RelayStatusChip connected={relayConnected} />
          </Stack>

          <Typography sx={microLabelSx}>Job master (live from GP)</Typography>
          <Stack direction="row" spacing={0.5} alignItems="flex-start">
            <Autocomplete
              options={jobs}
              loading={jobsLoading}
              value={selectedJob}
              getOptionLabel={(o) => (o.jobName ? `${o.jobNumber} - ${o.jobName}` : o.jobNumber)}
              isOptionEqualToValue={(o, v) => o.jobNumber === v.jobNumber}
              onChange={(_, value) => {
                setSelectedJob(value);
                if (jobError) setJobError(null);
              }}
              disabled={!relayConnected || loading}
              sx={{ flex: 1 }}
              slotProps={{ listbox: { sx: monoSx } }}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="GP job"
                  required
                  autoFocus
                  error={Boolean(jobError)}
                  helperText={
                    jobError ||
                    (!relayConnected
                      ? 'GP relay not detected on this machine - it must be running to list jobs'
                      : jobsFetchError
                        ? 'Failed to load jobs from GP'
                        : 'Pick the GP job this project belongs to.')
                  }
                />
              )}
            />
            <IconButton
              size="small"
              aria-label="Refresh GP jobs"
              onClick={() => refetchJobs()}
              disabled={!relayConnected || loading}
              sx={{ mt: 1 }}
            >
              <RefreshCw size={16} strokeWidth={1.75} />
            </IconButton>
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={loading || !relayConnected}>
          {loading ? 'Adopting…' : 'Adopt Job'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
