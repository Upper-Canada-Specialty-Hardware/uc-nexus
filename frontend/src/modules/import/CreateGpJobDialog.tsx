import { useState, useCallback, useMemo } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Autocomplete,
  Button,
  Stack,
  Alert,
  MenuItem,
  Collapse,
  Link,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  CREATE_GP_JOB,
  GET_GP_CUSTOMERS,
  GET_GP_CUSTOMER_ADDRESSES,
  GET_GP_DIVISIONS,
  GET_GP_TAX_SCHEDULES,
} from '../../graphql/import';
import { GET_PROJECTS } from '../../graphql/shared';
import { useToast } from '../../components/Toast';
import GpErrorAlert from '../../components/GpErrorAlert';
import { extractGpError, type GpError } from '../../graphql/gpError';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { useRelayStatus } from '../../relay/useRelayStatus';
import type { Project } from '../../types/project';
import { monoSx, microLabelSx } from '../../theme';

interface GpCustomerOption {
  customerNumber: string;
  customerName: string | null;
}

interface GpCustomerAddressOption {
  addressCode: string;
  address1: string | null;
  city: string | null;
  state: string | null;
}

interface GpTaxScheduleOption {
  taxScheduleId: string;
  description: string | null;
}

interface CreateGpJobDialogProps {
  open: boolean;
  onClose: () => void;
}

/** GP column widths, so an over-length value is caught in the field rather than by the proc. */
const MAX = { jobNumber: 17, jobName: 31, projectNumber: 17, id: 15 };

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function addressLabel(a: GpCustomerAddressOption): string {
  // An address code on its own ('MAIN', 'PRIMARY', 'RIH') doesn't say which site it is.
  const where = [a.address1, a.city].filter(Boolean).join(', ');
  return where ? `${a.addressCode} - ${where}` : a.addressCode;
}

/**
 * Originate a job in GP (issue #380), which then becomes a Nexus project.
 *
 * Nexus holds only the job number and description; customer, address codes, tax schedule and division
 * all live in GP, so every picker here is a live read through the relay and the form is unusable while
 * the relay is down. That is the same gating the register-PO dialog applies, and the reason this
 * submits straight through to GP rather than queueing on the outbox.
 *
 * Replaces AdoptGpJobDialog: adoption is now automatic (gp_job_sync creates a project for every job GP
 * reports), so picking an existing job by hand no longer does anything.
 */
export default function CreateGpJobDialog({ open, onClose }: CreateGpJobDialogProps) {
  const { showToast } = useToast();

  const [jobNumber, setJobNumber] = useState('');
  const [jobName, setJobName] = useState('');
  const [division, setDivision] = useState('');
  const [customer, setCustomer] = useState<GpCustomerOption | null>(null);
  const [jobAddressCode, setJobAddressCode] = useState('');
  const [billtoAddressCode, setBilltoAddressCode] = useState('');
  const [taxScheduleId, setTaxScheduleId] = useState('');
  const [createdDate, setCreatedDate] = useState(todayIso);

  const [optionalOpen, setOptionalOpen] = useState(false);
  const [estimatorId, setEstimatorId] = useState('');
  const [wsManagerId, setWsManagerId] = useState('');
  const [wsProjectNumber, setWsProjectNumber] = useState('');
  const [billCustomer, setBillCustomer] = useState<GpCustomerOption | null>(null);
  const [useTaxSchedule, setUseTaxSchedule] = useState('');
  const [scheduleStartDate, setScheduleStartDate] = useState('');
  const [scheduledCompletionDate, setScheduledCompletionDate] = useState('');
  const [bidDueDate, setBidDueDate] = useState('');

  const [gpError, setGpError] = useState<GpError | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  // The connected relay is enrolled for exactly one company, so the company is the relay's, shown
  // read-only rather than picked. skip: !open so a hidden dialog doesn't poll.
  const relay = useRelayStatus({ skip: !open });
  const company = relay.company ?? '';
  const relayConnected = relay.connected === true;

  const readsSkipped = !open || !relayConnected || !company;

  const { data: customersData, loading: customersLoading } = useQuery<{ gpCustomers: GpCustomerOption[] }>(
    GET_GP_CUSTOMERS,
    { variables: { company }, skip: readsSkipped, fetchPolicy: 'cache-first' },
  );
  const { data: divisionsData, loading: divisionsLoading } = useQuery<{ gpDivisions: string[] }>(GET_GP_DIVISIONS, {
    variables: { company },
    skip: readsSkipped,
    fetchPolicy: 'cache-first',
  });
  const { data: taxSchedulesData, loading: taxSchedulesLoading } = useQuery<{
    gpTaxSchedules: GpTaxScheduleOption[];
  }>(GET_GP_TAX_SCHEDULES, { variables: { company }, skip: readsSkipped, fetchPolicy: 'cache-first' });

  // Addresses are per-customer: the proc validates a code against THAT customer's addresses, so this
  // re-fetches on every customer change and the two address selects stay disabled until one is picked.
  const { data: addressesData, loading: addressesLoading } = useQuery<{
    gpCustomerAddresses: GpCustomerAddressOption[];
  }>(GET_GP_CUSTOMER_ADDRESSES, {
    variables: { company, customer: customer?.customerNumber ?? '' },
    skip: readsSkipped || !customer,
    fetchPolicy: 'cache-first',
  });

  const customers = useMemo(() => customersData?.gpCustomers ?? [], [customersData]);
  const divisions = useMemo(() => divisionsData?.gpDivisions ?? [], [divisionsData]);
  const taxSchedules = useMemo(() => taxSchedulesData?.gpTaxSchedules ?? [], [taxSchedulesData]);
  const addresses = useMemo(() => addressesData?.gpCustomerAddresses ?? [], [addressesData]);

  const [createGpJob, { loading }] = useMutation<{ createGpJob: Project }>(CREATE_GP_JOB, {
    refetchQueries: [{ query: GET_PROJECTS }],
  });

  const requiredComplete =
    jobNumber.trim() !== '' &&
    jobName.trim() !== '' &&
    division !== '' &&
    customer !== null &&
    jobAddressCode !== '' &&
    billtoAddressCode !== '' &&
    taxScheduleId !== '' &&
    createdDate !== '';

  const reset = useCallback(() => {
    setJobNumber('');
    setJobName('');
    setDivision('');
    setCustomer(null);
    setJobAddressCode('');
    setBilltoAddressCode('');
    setTaxScheduleId('');
    setCreatedDate(todayIso());
    setOptionalOpen(false);
    setEstimatorId('');
    setWsManagerId('');
    setWsProjectNumber('');
    setBillCustomer(null);
    setUseTaxSchedule('');
    setScheduleStartDate('');
    setScheduledCompletionDate('');
    setBidDueDate('');
    setGpError(null);
    setFieldError(null);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const handleCustomerChange = useCallback((value: GpCustomerOption | null) => {
    setCustomer(value);
    // The old codes belong to the old customer and would be rejected by the proc.
    setJobAddressCode('');
    setBilltoAddressCode('');
  }, []);

  const handleSubmit = useCallback(async () => {
    setGpError(null);
    setFieldError(null);

    if (!requiredComplete || !customer) {
      setFieldError('Fill in every required field before creating the job.');
      return;
    }

    // Blank optional fields go as null, not '' - the relay drops a null rather than telling GP to
    // overwrite its own default with an empty string.
    const blankToNull = (v: string) => (v.trim() === '' ? null : v.trim());

    try {
      await createGpJob({
        variables: {
          input: {
            jobNumber: jobNumber.trim(),
            jobName: jobName.trim(),
            division,
            customerNumber: customer.customerNumber,
            jobAddressCode,
            billtoAddressCode,
            taxScheduleId,
            createdDate,
            estimatorId: blankToNull(estimatorId),
            wsManagerId: blankToNull(wsManagerId),
            wsProjectNumber: blankToNull(wsProjectNumber),
            billCustomerNumber: billCustomer?.customerNumber ?? null,
            useTaxSchedule: blankToNull(useTaxSchedule),
            scheduleStartDate: blankToNull(scheduleStartDate),
            scheduledCompletionDate: blankToNull(scheduledCompletionDate),
            bidDueDate: blankToNull(bidDueDate),
          },
        },
      });
      showToast(`Job ${jobNumber.trim()} created in GP.`, 'success');
      handleClose();
    } catch (err) {
      // GP's own words - a closed fiscal period, an address code not on the customer, a division with
      // no accounts. The dialog stays open so the fix is one edit away.
      setGpError(extractGpError(err));
    }
  }, [
    requiredComplete,
    customer,
    createGpJob,
    jobNumber,
    jobName,
    division,
    jobAddressCode,
    billtoAddressCode,
    taxScheduleId,
    createdDate,
    estimatorId,
    wsManagerId,
    wsProjectNumber,
    billCustomer,
    useTaxSchedule,
    scheduleStartDate,
    scheduledCompletionDate,
    bidDueDate,
    showToast,
    handleClose,
  ]);

  const disabled = !relayConnected || loading;

  return (
    <Dialog open={open} onClose={loading ? undefined : handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create a GP Job</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {gpError && <GpErrorAlert error={gpError} onClose={() => setGpError(null)} />}
          {fieldError && <Alert severity="warning">{fieldError}</Alert>}

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

          {!relayConnected && (
            <Alert severity="warning">
              The GP relay is not connected. A job can only be created against live GP data, so this form stays
              disabled until the relay is running.
            </Alert>
          )}

          <Typography sx={microLabelSx}>Required</Typography>

          <Stack direction="row" spacing={2}>
            <TextField
              label="Job number"
              value={jobNumber}
              onChange={(e) => setJobNumber(e.target.value)}
              required
              autoFocus
              disabled={disabled}
              size="small"
              sx={{ flex: 1 }}
              slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.jobNumber } }}
            />
            <TextField
              label="Job name"
              value={jobName}
              onChange={(e) => setJobName(e.target.value)}
              required
              disabled={disabled}
              size="small"
              sx={{ flex: 1.4 }}
              slotProps={{ htmlInput: { maxLength: MAX.jobName } }}
            />
          </Stack>

          <TextField
            select
            label="Division"
            value={division}
            onChange={(e) => setDivision(e.target.value)}
            required
            disabled={disabled || divisionsLoading}
            size="small"
            helperText="Only divisions with division accounts set up in GP can take a job."
          >
            {divisions.map((d) => (
              <MenuItem key={d} value={d} sx={monoSx}>
                {d}
              </MenuItem>
            ))}
          </TextField>

          <Autocomplete
            options={customers}
            loading={customersLoading}
            value={customer}
            getOptionLabel={(o) => (o.customerName ? `${o.customerNumber} - ${o.customerName}` : o.customerNumber)}
            isOptionEqualToValue={(o, v) => o.customerNumber === v.customerNumber}
            onChange={(_, value) => handleCustomerChange(value)}
            disabled={disabled}
            slotProps={{ listbox: { sx: monoSx } }}
            renderInput={(params) => <TextField {...params} label="Customer" required size="small" />}
          />

          <Stack direction="row" spacing={2}>
            <TextField
              select
              label="Job address"
              value={jobAddressCode}
              onChange={(e) => setJobAddressCode(e.target.value)}
              required
              disabled={disabled || !customer || addressesLoading}
              size="small"
              sx={{ flex: 1 }}
              helperText={!customer ? 'Pick a customer first' : ' '}
            >
              {addresses.map((a) => (
                <MenuItem key={a.addressCode} value={a.addressCode}>
                  {addressLabel(a)}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Bill-to address"
              value={billtoAddressCode}
              onChange={(e) => setBilltoAddressCode(e.target.value)}
              required
              disabled={disabled || !customer || addressesLoading}
              size="small"
              sx={{ flex: 1 }}
              helperText={!customer ? 'Pick a customer first' : ' '}
            >
              {addresses.map((a) => (
                <MenuItem key={a.addressCode} value={a.addressCode}>
                  {addressLabel(a)}
                </MenuItem>
              ))}
            </TextField>
          </Stack>

          <Stack direction="row" spacing={2}>
            <TextField
              select
              label="Tax schedule"
              value={taxScheduleId}
              onChange={(e) => setTaxScheduleId(e.target.value)}
              required
              disabled={disabled || taxSchedulesLoading}
              size="small"
              sx={{ flex: 1 }}
            >
              {taxSchedules.map((t) => (
                <MenuItem key={t.taxScheduleId} value={t.taxScheduleId}>
                  {t.description ? `${t.taxScheduleId} - ${t.description}` : t.taxScheduleId}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Created date"
              type="date"
              value={createdDate}
              onChange={(e) => setCreatedDate(e.target.value)}
              required
              disabled={disabled}
              size="small"
              sx={{ flex: 1 }}
              slotProps={{ inputLabel: { shrink: true } }}
              helperText="Must fall inside an open GP fiscal period."
            />
          </Stack>

          <Link
            component="button"
            type="button"
            underline="hover"
            onClick={() => setOptionalOpen((v) => !v)}
            sx={{ alignSelf: 'flex-start' }}
          >
            {optionalOpen ? 'Hide optional fields' : 'Show optional fields'}
          </Link>

          <Collapse in={optionalOpen} unmountOnExit>
            <Stack spacing={2}>
              <Stack direction="row" spacing={2}>
                <TextField
                  label="Estimator ID"
                  value={estimatorId}
                  onChange={(e) => setEstimatorId(e.target.value)}
                  disabled={disabled}
                  size="small"
                  sx={{ flex: 1 }}
                  slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.id } }}
                />
                <TextField
                  label="WS Manager ID"
                  value={wsManagerId}
                  onChange={(e) => setWsManagerId(e.target.value)}
                  disabled={disabled}
                  size="small"
                  sx={{ flex: 1 }}
                  slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.id } }}
                />
              </Stack>

              <TextField
                label="WS Project number"
                value={wsProjectNumber}
                onChange={(e) => setWsProjectNumber(e.target.value)}
                disabled={disabled}
                size="small"
                slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.projectNumber } }}
              />

              <Autocomplete
                options={customers}
                loading={customersLoading}
                value={billCustomer}
                getOptionLabel={(o) => (o.customerName ? `${o.customerNumber} - ${o.customerName}` : o.customerNumber)}
                isOptionEqualToValue={(o, v) => o.customerNumber === v.customerNumber}
                onChange={(_, value) => setBillCustomer(value)}
                disabled={disabled}
                slotProps={{ listbox: { sx: monoSx } }}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="Bill-to customer"
                    size="small"
                    helperText="Leave empty to bill the job's own customer."
                  />
                )}
              />

              <TextField
                select
                label="Use tax schedule"
                value={useTaxSchedule}
                onChange={(e) => setUseTaxSchedule(e.target.value)}
                disabled={disabled || taxSchedulesLoading}
                size="small"
              >
                <MenuItem value="">
                  <em>None</em>
                </MenuItem>
                {taxSchedules.map((t) => (
                  <MenuItem key={t.taxScheduleId} value={t.taxScheduleId}>
                    {t.description ? `${t.taxScheduleId} - ${t.description}` : t.taxScheduleId}
                  </MenuItem>
                ))}
              </TextField>

              <Stack direction="row" spacing={2}>
                <TextField
                  label="Scheduled start"
                  type="date"
                  value={scheduleStartDate}
                  onChange={(e) => setScheduleStartDate(e.target.value)}
                  disabled={disabled}
                  size="small"
                  sx={{ flex: 1 }}
                  slotProps={{ inputLabel: { shrink: true } }}
                />
                <TextField
                  label="Scheduled completion"
                  type="date"
                  value={scheduledCompletionDate}
                  onChange={(e) => setScheduledCompletionDate(e.target.value)}
                  disabled={disabled}
                  size="small"
                  sx={{ flex: 1 }}
                  slotProps={{ inputLabel: { shrink: true } }}
                />
              </Stack>

              <TextField
                label="Bid due"
                type="date"
                value={bidDueDate}
                onChange={(e) => setBidDueDate(e.target.value)}
                disabled={disabled}
                size="small"
                slotProps={{ inputLabel: { shrink: true } }}
              />
            </Stack>
          </Collapse>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={disabled || !requiredComplete}>
          {loading ? 'Creating…' : 'Create Job'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
