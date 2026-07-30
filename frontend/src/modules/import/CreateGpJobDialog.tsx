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
  IconButton,
  Link,
  Typography,
} from '@mui/material';
import { RefreshCw } from 'lucide-react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  CREATE_GP_JOB,
  GET_GP_CUSTOMERS,
  GET_GP_CUSTOMER_ADDRESSES,
  GET_GP_DIVISIONS,
  GET_GP_EMPLOYEES,
  GET_GP_TAX_SCHEDULES,
} from '../../graphql/import';
import { GET_PROJECTS } from '../../graphql/shared';
import { useToast } from '../../components/Toast';
import GpErrorAlert from '../../components/GpErrorAlert';
import { extractGpError, isRelayOpUnsupported, type GpError } from '../../graphql/gpError';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { useRelayStatus } from '../../relay/useRelayStatus';
import type { Project } from '../../types/project';
import { monoSx, microLabelSx } from '../../theme';
import AddCustomerAddressDialog from './AddCustomerAddressDialog';

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

interface GpEmployeeOption {
  employeeId: string;
  firstName: string | null;
  lastName: string | null;
}

function employeeLabel(e: GpEmployeeOption): string {
  const name = [e.firstName, e.lastName].filter(Boolean).join(' ');
  return name ? `${e.employeeId} - ${name}` : e.employeeId;
}

interface EmployeeFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  employees: GpEmployeeOption[];
  loading: boolean;
  unavailable: boolean;
  disabled: boolean;
}

/**
 * Estimator / WS Manager. One component because the two fields are identical apart from their label
 * and binding, and a fix applied to a copy-pasted twin is a fix that silently misses one of them.
 *
 * An Autocomplete rather than a Select: this is an unbounded master (TUBC has two employees, a real
 * payroll has hundreds), so it needs to be searchable for the same reason the Customer picker is.
 *
 * `unavailable` falls back to free text. The read can fail on its own - an older relay has no
 * list_employees op - and GP still accepts a known EMPLOYID, so leaving the field unsettable would
 * take away something #380 allowed. That is the same banner-plus-fallback shape the register-PO
 * dialog uses for tax details rather than showing an empty dropdown.
 */
function EmployeeField({ label, value, onChange, employees, loading, unavailable, disabled }: EmployeeFieldProps) {
  if (unavailable) {
    return (
      <TextField
        label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        size="small"
        sx={{ flex: 1 }}
        slotProps={{ input: { sx: monoSx }, htmlInput: { maxLength: MAX.id } }}
        helperText="Employee list unavailable - type a GP payroll ID"
      />
    );
  }
  return (
    <Autocomplete
      options={employees}
      loading={loading}
      value={employees.find((e) => e.employeeId === value) ?? null}
      getOptionLabel={employeeLabel}
      isOptionEqualToValue={(o, v) => o.employeeId === v.employeeId}
      onChange={(_, selected) => onChange(selected?.employeeId ?? '')}
      disabled={disabled}
      sx={{ flex: 1 }}
      slotProps={{ listbox: { sx: monoSx } }}
      renderInput={(params) => <TextField {...params} label={label} size="small" />}
    />
  );
}

interface CreateGpJobDialogProps {
  open: boolean;
  onClose: () => void;
}

/** GP column widths, so an over-length value is caught in the field rather than by the proc. */
const MAX = { jobNumber: 17, jobName: 31, projectNumber: 17, id: 15 };

/**
 * Today in LOCAL time. Deliberately not toISOString().slice(0, 10), which is UTC: west of Greenwich
 * that reads as tomorrow from late afternoon onward. Created date is the field GP validates against
 * the open fiscal period, so an off-by-one here produces a closed-period rejection for a date the
 * form itself presented as today.
 */
function todayIso(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function addressLabel(a: GpCustomerAddressOption): string {
  // An address code on its own ('MAIN', 'PRIMARY', 'RIH') doesn't say which site it is.
  const where = [a.address1, a.city].filter(Boolean).join(', ');
  return where ? `${a.addressCode} - ${where}` : a.addressCode;
}

/**
 * #444: the value the "+ Add new address" row carries. A MUI select has no way to hold an action
 * alongside its options, so the choice arrives through onChange like any other - and this is the one
 * value that must never be stored, since it is not an address code GP would accept.
 */
const ADD_ADDRESS = '__add__';

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
  // #392: both hold a GP payroll EMPLOYID, picked via EmployeeField. wsProjectNumber stays free
  // text - nothing in GP validates it.
  const [estimatorId, setEstimatorId] = useState('');
  const [wsManagerId, setWsManagerId] = useState('');
  const [wsProjectNumber, setWsProjectNumber] = useState('');
  const [billCustomer, setBillCustomer] = useState<GpCustomerOption | null>(null);
  const [useTaxSchedule, setUseTaxSchedule] = useState('');
  const [scheduleStartDate, setScheduleStartDate] = useState('');
  const [scheduledCompletionDate, setScheduledCompletionDate] = useState('');
  const [bidDueDate, setBidDueDate] = useState('');

  // #444: which address picker asked for a new address, which is also what decides the customer it is
  // created under. Null keeps the nested dialog unmounted, so its fields start clean every time.
  const [addAddressFor, setAddAddressFor] = useState<'job' | 'bill' | null>(null);

  const [gpError, setGpError] = useState<GpError | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  // The connected relay is enrolled for exactly one company, so the company is the relay's, shown
  // read-only rather than picked. skip: !open so a hidden dialog doesn't poll.
  const relay = useRelayStatus({ skip: !open });
  const company = relay.company ?? '';
  const relayConnected = relay.connected === true;

  const readsSkipped = !open || !relayConnected || !company;

  const {
    data: customersData,
    loading: customersLoading,
    error: customersError,
    refetch: refetchCustomers,
  } = useQuery<{ gpCustomers: GpCustomerOption[] }>(GET_GP_CUSTOMERS, {
    variables: { company },
    skip: readsSkipped,
    fetchPolicy: 'cache-first',
  });
  const {
    data: divisionsData,
    loading: divisionsLoading,
    error: divisionsError,
    refetch: refetchDivisions,
  } = useQuery<{ gpDivisions: string[] }>(GET_GP_DIVISIONS, {
    variables: { company },
    skip: readsSkipped,
    fetchPolicy: 'cache-first',
  });
  const {
    data: taxSchedulesData,
    loading: taxSchedulesLoading,
    error: taxSchedulesError,
    refetch: refetchTaxSchedules,
  } = useQuery<{ gpTaxSchedules: GpTaxScheduleOption[] }>(GET_GP_TAX_SCHEDULES, {
    variables: { company },
    skip: readsSkipped,
    fetchPolicy: 'cache-first',
  });
  // Only the optional section consumes this, so it is not fetched until that section is opened -
  // most creates never need it, and every open would otherwise cost a relay round-trip and a
  // UPR00100 read for nothing.
  const {
    data: employeesData,
    loading: employeesLoading,
    error: employeesError,
    refetch: refetchEmployees,
  } = useQuery<{ gpEmployees: GpEmployeeOption[] }>(GET_GP_EMPLOYEES, {
    variables: { company },
    skip: readsSkipped || !optionalOpen,
    fetchPolicy: 'cache-first',
  });

  // Addresses are per-customer: the proc validates a code against THAT customer's addresses, so this
  // re-fetches on every customer change and the two address selects stay disabled until one is picked.
  const {
    data: addressesData,
    loading: addressesLoading,
    error: addressesError,
    refetch: refetchAddresses,
  } = useQuery<{ gpCustomerAddresses: GpCustomerAddressOption[] }>(GET_GP_CUSTOMER_ADDRESSES, {
    variables: { company, customer: customer?.customerNumber ?? '' },
    skip: readsSkipped || !customer,
    fetchPolicy: 'cache-first',
  });

  // The optional Bill-to customer has its own addresses. Without this the Bill-to address select
  // would keep offering the JOB customer's codes, which the proc validates against the bill-to
  // customer and rejects - the form could not express a valid pairing at all.
  const billCustomerNumber = billCustomer?.customerNumber ?? null;
  const billScopedToOwnCustomer = billCustomerNumber !== null && billCustomerNumber !== customer?.customerNumber;
  const {
    data: billAddressesData,
    loading: billAddressesLoading,
    refetch: refetchBillAddresses,
  } = useQuery<{
    gpCustomerAddresses: GpCustomerAddressOption[];
  }>(GET_GP_CUSTOMER_ADDRESSES, {
    variables: { company, customer: billCustomerNumber ?? '' },
    skip: readsSkipped || !billScopedToOwnCustomer,
    fetchPolicy: 'cache-first',
  });

  const employees = useMemo(() => employeesData?.gpEmployees ?? [], [employeesData]);
  const customers = useMemo(() => customersData?.gpCustomers ?? [], [customersData]);
  const divisions = useMemo(() => divisionsData?.gpDivisions ?? [], [divisionsData]);
  const taxSchedules = useMemo(() => taxSchedulesData?.gpTaxSchedules ?? [], [taxSchedulesData]);
  const addresses = useMemo(() => addressesData?.gpCustomerAddresses ?? [], [addressesData]);
  // Bill-to address options follow whichever customer will actually be billed.
  const billAddresses = useMemo(
    () => (billScopedToOwnCustomer ? (billAddressesData?.gpCustomerAddresses ?? []) : addresses),
    [billScopedToOwnCustomer, billAddressesData, addresses],
  );
  // #444: and so does an address created FROM that picker - same rule, same reason.
  const billPickerCustomer = billScopedToOwnCustomer ? billCustomer : customer;
  const addAddressCustomer = addAddressFor === 'bill' ? billPickerCustomer : addAddressFor === 'job' ? customer : null;

  // A failed read is NOT an empty list. Without this the deploy-before-relay-rebuild window (the ops
  // are not in an older relay's advertised op-set) renders a green relay chip over empty required
  // dropdowns and a button that can never enable, with nothing saying why.
  //
  // Only the REQUIRED reads count here. Folding the optional employees read in made a relay that
  // serves create_job perfectly well announce "too old to create jobs" while the form stayed enabled
  // and the create went through - the banner asserting the opposite of what the button did. That is
  // exactly the state between deploying this and updating the relay, so it has to stay out.
  const readError = customersError ?? divisionsError ?? taxSchedulesError ?? addressesError ?? null;
  const readsUnsupported = [customersError, divisionsError, taxSchedulesError, addressesError].some((e) =>
    isRelayOpUnsupported(e),
  );
  // The optional section degrades on its own instead: pickers become free-text entry.
  const employeesUnavailable = Boolean(employeesError);

  const refreshReads = useCallback(() => {
    void refetchCustomers();
    void refetchDivisions();
    void refetchTaxSchedules();
    void refetchEmployees();
    if (customer) void refetchAddresses();
  }, [refetchCustomers, refetchDivisions, refetchTaxSchedules, refetchEmployees, refetchAddresses, customer]);

  const [createGpJob, { loading }] = useMutation<{ createGpJob: { created: boolean; project: Pick<Project, 'id'> } }>(
    CREATE_GP_JOB,
    { refetchQueries: [{ query: GET_PROJECTS }] },
  );

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

  /**
   * #444: the code GP just stored becomes the picker's selection.
   *
   * The re-read comes first because each picker renders its options from its own query - selecting a
   * code that is not in that list yet leaves the field blank until the read lands. `catch` keeps a
   * failed re-read from stranding the selection: the address exists in GP either way.
   */
  const handleAddressCreated = useCallback(
    (addressCode: string) => {
      const forBill = addAddressFor === 'bill';
      const refetch = forBill && billScopedToOwnCustomer ? refetchBillAddresses : refetchAddresses;
      const select = forBill ? setBilltoAddressCode : setJobAddressCode;
      void refetch()
        .catch(() => undefined)
        .then(() => select(addressCode));
    },
    [addAddressFor, billScopedToOwnCustomer, refetchAddresses, refetchBillAddresses],
  );

  const handleBillCustomerChange = useCallback((value: GpCustomerOption | null) => {
    setBillCustomer(value);
    // The bill-to address select is about to be re-scoped to a different customer's codes, so the
    // currently selected one is no longer necessarily in the list.
    setBilltoAddressCode('');
  }, []);

  // Optional values survive collapsing the section (losing typed input to a stray click would be
  // worse), so the count is what keeps "hidden" from reading as "not in play" - they are still sent.
  const optionalSetCount = [
    estimatorId.trim(),
    wsManagerId.trim(),
    wsProjectNumber.trim(),
    billCustomer?.customerNumber ?? '',
    useTaxSchedule,
    scheduleStartDate,
    scheduledCompletionDate,
    bidDueDate,
  ].filter(Boolean).length;

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
      const response = await createGpJob({
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
      // #392: GP may not have created anything - when it already held the job number the mutation
      // adopts it instead, and saying "created" there would report something that did not happen.
      // `=== true`, not `!== false`: an absent or partial payload must not be read as a creation,
      // which is the very claim this branch exists to stop making.
      const created = response.data?.createGpJob?.created === true;
      showToast(
        created
          ? `Job ${jobNumber.trim()} created in GP.`
          : `Job ${jobNumber.trim()} already existed in GP and is now a project.`,
        'success',
      );
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
            <IconButton
              size="small"
              aria-label="Refresh GP data"
              onClick={refreshReads}
              disabled={!relayConnected || loading}
              title="Re-read customers, addresses, divisions, tax schedules and employees from GP"
            >
              <RefreshCw size={16} strokeWidth={1.75} />
            </IconButton>
          </Stack>

          {!relayConnected && (
            <Alert severity="warning">
              The GP relay is not connected. A job can only be created against live GP data, so this form stays
              disabled until the relay is running.
            </Alert>
          )}

          {relayConnected && readsUnsupported && (
            <Alert severity="warning">
              The connected relay is too old to create jobs. Update the relay on that workstation, then reopen this
              form.
            </Alert>
          )}

          {relayConnected && readError && !readsUnsupported && (
            <Alert severity="error">
              Could not read the job setup data from GP, so the fields below are incomplete. {readError.message}
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
              // #444: the add row arrives as a value like any option, so it is intercepted here and
              // never stored - it opens the nested dialog and leaves the current selection alone.
              onChange={(e) => {
                if (e.target.value === ADD_ADDRESS) setAddAddressFor('job');
                else setJobAddressCode(e.target.value);
              }}
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
              {customer && (
                <MenuItem value={ADD_ADDRESS} sx={{ fontStyle: 'italic' }}>
                  + Add new address
                </MenuItem>
              )}
            </TextField>
            <TextField
              select
              label="Bill-to address"
              value={billtoAddressCode}
              onChange={(e) => {
                if (e.target.value === ADD_ADDRESS) setAddAddressFor('bill');
                else setBilltoAddressCode(e.target.value);
              }}
              required
              disabled={disabled || !customer || addressesLoading || billAddressesLoading}
              size="small"
              sx={{ flex: 1 }}
              helperText={
                !customer
                  ? 'Pick a customer first'
                  : billScopedToOwnCustomer
                    ? `Addresses of ${billCustomerNumber} (the bill-to customer)`
                    : ' '
              }
            >
              {billAddresses.map((a) => (
                <MenuItem key={a.addressCode} value={a.addressCode}>
                  {addressLabel(a)}
                </MenuItem>
              ))}
              {billPickerCustomer && (
                <MenuItem value={ADD_ADDRESS} sx={{ fontStyle: 'italic' }}>
                  + Add new address
                </MenuItem>
              )}
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
            {!optionalOpen && optionalSetCount > 0 ? ` (${optionalSetCount} set)` : ''}
          </Link>

          <Collapse in={optionalOpen} unmountOnExit>
            <Stack spacing={2}>
              {/* #392: GP validates both against the payroll master, so typing a name only ever
                  earns "The estimator does not exist in the payroll master table". */}
              <Stack direction="row" spacing={2}>
                <EmployeeField
                  label="Estimator"
                  value={estimatorId}
                  onChange={setEstimatorId}
                  employees={employees}
                  loading={employeesLoading}
                  unavailable={employeesUnavailable}
                  disabled={disabled}
                />
                <EmployeeField
                  label="WS Manager"
                  value={wsManagerId}
                  onChange={setWsManagerId}
                  employees={employees}
                  loading={employeesLoading}
                  unavailable={employeesUnavailable}
                  disabled={disabled}
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
                onChange={(_, value) => handleBillCustomerChange(value)}
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

      {/* #444: mounted only while a picker is asking, so the half-filled job form stays behind it. */}
      {addAddressCustomer && (
        <AddCustomerAddressDialog
          open
          onClose={() => setAddAddressFor(null)}
          customer={addAddressCustomer}
          onCreated={handleAddressCreated}
        />
      )}
    </Dialog>
  );
}
