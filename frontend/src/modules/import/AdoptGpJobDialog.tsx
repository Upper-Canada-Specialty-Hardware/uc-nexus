import { useState, useCallback } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  Autocomplete,
  Button,
  Stack,
  Alert,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { ADOPT_GP_JOB } from '../../graphql/mutations';
import { GET_PROJECTS, GET_GP_JOBS, GET_RELAY_STATUS } from '../../graphql/queries';
import { useToast } from '../../components/Toast';
import RelayStatusChip from '../../relay/RelayStatusChip';
import type { Project } from '../../types/project';

interface GpJobOption {
  jobNumber: string;
  jobName: string | null;
}

// GP companies the relay is allowed to read from (sandboxes for the POC) - mirrors the list used
// by GpPurchaseOrderDialog / GpVendorSyncPage.
const COMPANIES = ['TUBC', 'TUCSH'];

interface AdoptGpJobDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function AdoptGpJobDialog({ open, onClose }: AdoptGpJobDialogProps) {
  const { showToast } = useToast();
  const [company, setCompany] = useState('TUBC');
  const [selectedJob, setSelectedJob] = useState<GpJobOption | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);

  const { data: relayStatusData } = useQuery<{ relayStatus: { connected: boolean } }>(GET_RELAY_STATUS, {
    skip: !open,
  });
  const relayConnected = relayStatusData?.relayStatus.connected === true;

  // The live GP job master (JC00102) for this company, via the connected relay - this IS the
  // project picker: adopting a project means picking one of these, not typing a free-form number.
  const {
    data: jobsData,
    loading: jobsLoading,
    error: jobsFetchError,
  } = useQuery<{ gpJobs: GpJobOption[] }>(GET_GP_JOBS, {
    variables: { company },
    skip: !open || !relayConnected,
    fetchPolicy: 'network-only',
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

  // A job picked under one company doesn't carry over to another.
  const handleCompanyChange = useCallback((newCompany: string) => {
    setCompany(newCompany);
    setSelectedJob(null);
  }, []);

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
        const conflict = err.errors.find(
          (e) => (e.extensions as { code?: string } | undefined)?.code === 'CONFLICT',
        );
        if (conflict) {
          setJobError(conflict.message);
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
            <TextField
              select
              label="GP company"
              value={company}
              onChange={(e) => handleCompanyChange(e.target.value)}
              size="small"
              disabled={loading}
              sx={{ minWidth: 140 }}
            >
              {COMPANIES.map((c) => (
                <MenuItem key={c} value={c}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
            <RelayStatusChip connected={relayConnected} />
          </Stack>
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
