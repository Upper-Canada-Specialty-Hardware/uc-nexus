import { useState, useCallback, useMemo } from 'react';
import { Alert, Box, Button, Divider, FormControlLabel, Stack, Switch, TextField, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import GpErrorAlert from '../../components/GpErrorAlert';
import ProcessingStep from '../../components/ProcessingStep';
import { GpJobStateTag } from '../../components/GpJobStateTag';
import { UPDATE_PROJECT, GET_ADMIN_PROJECTS } from '../../graphql/admin';
import {
  GET_GP_CUSTOMERS,
  GET_GP_CUSTOMER_ADDRESSES,
  GET_GP_DIVISIONS,
  GET_GP_EMPLOYEES,
  GET_GP_TAX_SCHEDULES,
} from '../../graphql/import';
import { extractGpError, RELAY_OP_UNSUPPORTED, type GpError } from '../../graphql/gpError';
import { useRelayStatus } from '../../relay/useRelayStatus';
import { gpJobNotOpenReason, isGpJobNotOpen, type GpJobState, type GpSetupIssue } from '../../types/project';
import { microLabelSx, monoSx } from '../../theme';
import {
  EmployeeField,
  GpAddressField,
  GpCustomerField,
  GpDateField,
  GpDivisionField,
  GpTaxScheduleField,
} from './GpJobFields';
import {
  MAX,
  addressCodeOrBlank,
  withCurrent,
  type GpCustomerAddressOption,
  type GpCustomerOption,
  type GpEmployeeOption,
  type GpTaxScheduleOption,
} from './gpJobFieldOptions';
import { useAddCustomerAddress } from './useAddCustomerAddress';

export interface ProjectFormValue {
  id: string;
  projectId: string;
  description: string | null;
  client: string | null;
  jobSiteName: string | null;
  // #637: the GP company that owns the job, and whether it has been archived out of the pickers.
  // Both are read-only here - the company comes from GP, and archiving has its own action.
  company: string;
  archived: boolean;
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
  openingCount: number;
  // GP job setup verdict (#425), read-only and stamped by the sync. Present so the admin project grid
  // can badge a quarantined job; the edit form never writes it.
  gpSetupOk?: boolean | null;
  gpSetupCheckedAt?: string | null;
  gpSetupIssues?: GpSetupIssue[] | null;
  // #730: the GP job's state, on every read. The rest is the GP job as GP holds it, read only by the
  // detail page and the edit mutation - the grid does not ask for it, so all of it is optional here.
  gpJobState?: GpJobState | null;
  gpClosedDate?: string | null;
  customerNumber?: string | null;
  jobAddressCode?: string | null;
  billtoAddressCode?: string | null;
  address2?: string | null;
  country?: string | null;
  division?: string | null;
  taxScheduleId?: string | null;
  useTaxScheduleId?: string | null;
  estimatorId?: string | null;
  estimatorName?: string | null;
  wsManagerId?: string | null;
  wsManagerName?: string | null;
  gpCreatedDate?: string | null;
  scheduleStartDate?: string | null;
  scheduledCompletionDate?: string | null;
  bidDueDate?: string | null;
  origContractAmount?: number | null;
  contractToDate?: number | null;
  totalActualCost?: number | null;
  billedAmountTtd?: number | null;
  retentionAmountTtd?: number | null;
  netBilledTtd?: number | null;
}

interface ProjectEditDialogProps {
  open: boolean;
  project: ProjectFormValue | null;
  onClose: () => void;
}

/** Fields only Nexus holds. Saving these alone never reaches GP. */
interface NexusForm {
  jobSiteName: string;
  contractor: string;
  projectManager: string;
  application: string;
  gcContactName: string;
  gcPhone: string;
  gcEmail: string;
  offSiteStorageAgreement: boolean;
}

/**
 * #730: the GP-owned text fields, each keyed by its UpdateProjectInput name. The customer is held apart
 * as a picked option, since its name travels with its number.
 */
interface GpForm {
  description: string;
  jobAddressCode: string;
  billtoAddressCode: string;
  address: string;
  address2: string;
  city: string;
  state: string;
  zip: string;
  country: string;
  division: string;
  taxScheduleId: string;
  useTaxScheduleId: string;
  estimatorId: string;
  wsManagerId: string;
  scheduleStartDate: string;
  scheduledCompletionDate: string;
  bidDueDate: string;
}

type GpKey = keyof GpForm;

/**
 * The site address. GP takes it one of two ways, never both in one save: an existing customer address
 * code picked as the job address, or these fields typed out, which GP files as a new address.
 */
const SITE_ADDRESS_KEYS: GpKey[] = ['address', 'address2', 'city', 'state', 'zip', 'country'];

/** The two address codes. Emptied on a customer change for re-picking, so never "cleared" by a person. */
const ADDRESS_CODE_KEYS: GpKey[] = ['jobAddressCode', 'billtoAddressCode'];

/** A date as the date input holds it. The server's ISO date may carry a time part. */
function dayOf(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : '';
}

function toNexusForm(p: ProjectFormValue): NexusForm {
  return {
    jobSiteName: p.jobSiteName ?? '',
    contractor: p.contractor ?? '',
    projectManager: p.projectManager ?? '',
    application: p.application ?? '',
    gcContactName: p.gcContactName ?? '',
    gcPhone: p.gcPhone ?? '',
    gcEmail: p.gcEmail ?? '',
    offSiteStorageAgreement: p.offSiteStorageAgreement,
  };
}

function toGpForm(p: ProjectFormValue): GpForm {
  return {
    description: p.description ?? '',
    jobAddressCode: p.jobAddressCode ?? '',
    billtoAddressCode: p.billtoAddressCode ?? '',
    address: p.address ?? '',
    address2: p.address2 ?? '',
    city: p.city ?? '',
    state: p.state ?? '',
    zip: p.zip ?? '',
    country: p.country ?? '',
    division: p.division ?? '',
    taxScheduleId: p.taxScheduleId ?? '',
    useTaxScheduleId: p.useTaxScheduleId ?? '',
    estimatorId: p.estimatorId ?? '',
    wsManagerId: p.wsManagerId ?? '',
    scheduleStartDate: dayOf(p.scheduleStartDate),
    scheduledCompletionDate: dayOf(p.scheduledCompletionDate),
    bidDueDate: dayOf(p.bidDueDate),
  };
}

function currentCustomer(p: ProjectFormValue): GpCustomerOption | null {
  return p.customerNumber ? { customerNumber: p.customerNumber, customerName: p.client } : null;
}

const sameCustomer = (a: GpCustomerOption, b: GpCustomerOption) => a.customerNumber === b.customerNumber;
const sameAddress = (a: GpCustomerAddressOption, b: GpCustomerAddressOption) => a.addressCode === b.addressCode;
const sameTaxSchedule = (a: GpTaxScheduleOption, b: GpTaxScheduleOption) => a.taxScheduleId === b.taxScheduleId;
const sameEmployee = (a: GpEmployeeOption, b: GpEmployeeOption) => a.employeeId === b.employeeId;

/** The option a picker shows for a value the live read has not (yet) listed, or null for no value. */
function heldEmployee(id: string | null | undefined, name: string | null | undefined): GpEmployeeOption | null {
  return id ? { employeeId: id, firstName: name ?? null, lastName: null } : null;
}

const CITY_ROW: Array<[GpKey, string]> = [
  ['city', 'City'],
  ['state', 'State'],
  ['zip', 'Zip'],
  ['country', 'Country'],
];

const DATE_ROW: Array<[GpKey, string]> = [
  ['scheduleStartDate', 'Scheduled start'],
  ['scheduledCompletionDate', 'Scheduled completion'],
  ['bidDueDate', 'Bid due'],
];

/**
 * One Save for the whole project (#730). GP owns the job, so the GP-owned fields are edited with the
 * same live pickers the Create GP job dialog uses, and a save that changes any of them is a NEXUS TO GP
 * WRITE: the mutation writes to GP and reads the job back before it answers, and the dialog waits on it
 * in front of the person. A save that changes only Nexus fields never reaches GP.
 */
function ProjectEditDialogContent({ project, onClose }: { project: ProjectFormValue; onClose: () => void }) {
  const { showToast } = useToast();
  const [nexus, setNexus] = useState<NexusForm>(() => toNexusForm(project));
  const initialGp = useMemo(() => toGpForm(project), [project]);
  const [gp, setGp] = useState<GpForm>(initialGp);
  const initialCustomer = useMemo(() => currentCustomer(project), [project]);
  const [customer, setCustomer] = useState<GpCustomerOption | null>(initialCustomer);
  const [gpError, setGpError] = useState<GpError | null>(null);

  const company = project.company;
  // GP refuses every write to an inactive, closed or missing job, so its fields are shown and not
  // offered. Nexus-only fields stay editable either way.
  const jobNotOpen = isGpJobNotOpen(project);
  const relay = useRelayStatus({ skip: jobNotOpen });
  const relayConnected = relay.connected === true;
  // The GP pickers are live reads through the relay, and a GP write needs it too.
  const gpEditable = !jobNotOpen && relayConnected;
  const readsSkipped = !gpEditable;

  const customerNumber = customer?.customerNumber ?? '';
  const customerChanged = customerNumber !== (initialCustomer?.customerNumber ?? '');

  const { data: customersData, loading: customersLoading, error: customersError } = useQuery<{
    gpCustomers: GpCustomerOption[];
  }>(GET_GP_CUSTOMERS, { variables: { company }, skip: readsSkipped, fetchPolicy: 'cache-first' });
  const { data: divisionsData, loading: divisionsLoading, error: divisionsError } = useQuery<{
    gpDivisions: string[];
  }>(GET_GP_DIVISIONS, { variables: { company }, skip: readsSkipped, fetchPolicy: 'cache-first' });
  const { data: taxSchedulesData, loading: taxSchedulesLoading, error: taxSchedulesError } = useQuery<{
    gpTaxSchedules: GpTaxScheduleOption[];
  }>(GET_GP_TAX_SCHEDULES, { variables: { company }, skip: readsSkipped, fetchPolicy: 'cache-first' });
  const { data: employeesData, loading: employeesLoading, error: employeesError } = useQuery<{
    gpEmployees: GpEmployeeOption[];
  }>(GET_GP_EMPLOYEES, { variables: { company }, skip: readsSkipped, fetchPolicy: 'cache-first' });
  // GP validates both address codes against the job's customer, so both pickers read that customer's
  // addresses and re-read on a customer change.
  const { data: addressesData, loading: addressesLoading, error: addressesError } = useQuery<{
    gpCustomerAddresses: GpCustomerAddressOption[];
  }>(GET_GP_CUSTOMER_ADDRESSES, {
    variables: { company, customer: customerNumber },
    skip: readsSkipped || !customer,
    fetchPolicy: 'cache-first',
  });

  // Employees degrade on their own to free text, as in the Create GP job dialog.
  const readError = customersError ?? divisionsError ?? taxSchedulesError ?? addressesError ?? null;

  // Every list keeps the value the job already holds, so the form opens on it before (or without) the
  // live read answering.
  const customers = useMemo(
    () => withCurrent(customersData?.gpCustomers ?? [], initialCustomer, sameCustomer),
    [customersData, initialCustomer],
  );
  const divisions = useMemo(() => {
    const list = divisionsData?.gpDivisions ?? [];
    return initialGp.division && !list.includes(initialGp.division) ? [initialGp.division, ...list] : list;
  }, [divisionsData, initialGp.division]);
  const taxSchedules = useMemo(() => {
    let list = taxSchedulesData?.gpTaxSchedules ?? [];
    for (const id of [initialGp.taxScheduleId, initialGp.useTaxScheduleId]) {
      list = withCurrent(list, id ? { taxScheduleId: id, description: null } : null, sameTaxSchedule);
    }
    return list;
  }, [taxSchedulesData, initialGp.taxScheduleId, initialGp.useTaxScheduleId]);
  const employees = useMemo(() => {
    let list = employeesData?.gpEmployees ?? [];
    list = withCurrent(list, heldEmployee(project.estimatorId, project.estimatorName), sameEmployee);
    list = withCurrent(list, heldEmployee(project.wsManagerId, project.wsManagerName), sameEmployee);
    return list;
  }, [employeesData, project.estimatorId, project.estimatorName, project.wsManagerId, project.wsManagerName]);
  const addresses = useMemo(() => {
    let list = addressesData?.gpCustomerAddresses ?? [];
    // The held codes belong to the job's current customer only - a new customer offers its own.
    if (!customerChanged) {
      if (initialGp.jobAddressCode) {
        list = withCurrent(
          list,
          { addressCode: initialGp.jobAddressCode, address1: project.address, city: project.city, state: project.state },
          sameAddress,
        );
      }
      if (initialGp.billtoAddressCode) {
        list = withCurrent(
          list,
          { addressCode: initialGp.billtoAddressCode, address1: null, city: null, state: null },
          sameAddress,
        );
      }
    }
    return list;
  }, [
    addressesData,
    customerChanged,
    initialGp.jobAddressCode,
    initialGp.billtoAddressCode,
    project.address,
    project.city,
    project.state,
  ]);

  const addAddress = useAddCustomerAddress(company, relayConnected);
  const startAddAddress = addAddress.open;

  const setGpField = useCallback((key: GpKey, value: string) => setGp((f) => ({ ...f, [key]: value })), []);
  const setNexusText = useCallback(
    (key: keyof NexusForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setNexus((f) => ({ ...f, [key]: e.target.value })),
    [],
  );

  const handleCustomerChange = useCallback(
    (value: GpCustomerOption | null) => {
      // GP keeps its own value when it is sent a blank, so a customer can be changed but not removed.
      if (!value) return;
      setCustomer(value);
      const back = value.customerNumber === (initialCustomer?.customerNumber ?? '');
      // GP validates both codes against the customer, so a new customer's have to be picked afresh, and
      // going back to the job's own customer puts its own codes back. The typed site address is put
      // back too, so the new customer's site is given one way or the other from a clean start.
      setGp((f) => {
        const next: GpForm = {
          ...f,
          jobAddressCode: back ? initialGp.jobAddressCode : '',
          billtoAddressCode: back ? initialGp.billtoAddressCode : '',
        };
        for (const key of SITE_ADDRESS_KEYS) next[key] = initialGp[key];
        return next;
      });
    },
    [initialCustomer, initialGp],
  );

  const changedGpKeys = useMemo(
    () => (Object.keys(initialGp) as GpKey[]).filter((k) => gp[k].trim() !== initialGp[k].trim()),
    [gp, initialGp],
  );
  // The site address is given one of two ways per save, never both: a job address code picked from the
  // customer's addresses, or the street fields typed out, which GP files as a new address. Whichever
  // is touched first locks the other.
  const jobAddressPicked = changedGpKeys.includes('jobAddressCode') && addressCodeOrBlank(gp.jobAddressCode) !== '';
  const siteAddressChanged = SITE_ADDRESS_KEYS.some((k) => changedGpKeys.includes(k));
  const gpChanged = gpEditable && (customerChanged || changedGpKeys.length > 0);

  // GP keeps its own value when it is sent a blank, so a value it holds can be changed, not cleared.
  const isBlanked = (key: GpKey) =>
    !ADDRESS_CODE_KEYS.includes(key) && initialGp[key].trim() !== '' && gp[key].trim() === '';
  const anyBlanked = changedGpKeys.some(isBlanked);
  // A new customer needs its bill-to address, and a site: a picked job address or a typed one.
  const addressesMissing =
    customerChanged &&
    (addressCodeOrBlank(gp.billtoAddressCode) === '' ||
      (addressCodeOrBlank(gp.jobAddressCode) === '' && !siteAddressChanged));

  const saveBlockedReason = !gpEditable
    ? null
    : addressesMissing
      ? 'Pick the bill-to address, and a job address or a new site address, for the new customer'
      : anyBlanked
        ? 'A value GP holds cannot be cleared from Nexus'
        : null;

  const [updateProject, { loading }] = useMutation(UPDATE_PROJECT, {
    refetchQueries: [{ query: GET_ADMIN_PROJECTS }],
  });
  const writingToGp = loading && gpChanged;

  const handleSubmit = useCallback(async () => {
    setGpError(null);
    const input: Record<string, unknown> = {
      jobSiteName: nexus.jobSiteName.trim(),
      contractor: nexus.contractor.trim(),
      projectManager: nexus.projectManager.trim(),
      application: nexus.application.trim(),
      gcContactName: nexus.gcContactName.trim(),
      gcPhone: nexus.gcPhone.trim(),
      gcEmail: nexus.gcEmail.trim(),
      offSiteStorageAgreement: nexus.offSiteStorageAgreement,
    };
    // Only what changed goes to GP - a field left out is one GP is not asked to write. The customer
    // name (`client`) is never sent: it comes back from GP with the customer.
    if (gpChanged) {
      for (const key of changedGpKeys) {
        if (!ADDRESS_CODE_KEYS.includes(key)) input[key] = gp[key].trim();
      }
      if (customerChanged) {
        // GP checks the addresses against the customer, so the bill-to code travels with it even when
        // the new customer's code is spelled the same as the old one's.
        input.customerNumber = customerNumber;
        input.billtoAddressCode = addressCodeOrBlank(gp.billtoAddressCode);
      } else if (changedGpKeys.includes('billtoAddressCode')) {
        input.billtoAddressCode = addressCodeOrBlank(gp.billtoAddressCode);
      }
      // The site goes one way or the other, never both: the picked job address code (always sent on a
      // customer change, for the same reason as the bill-to), or the typed street fields.
      if (siteAddressChanged) {
        for (const key of SITE_ADDRESS_KEYS) input[key] = gp[key].trim();
      } else if (jobAddressPicked || (customerChanged && addressCodeOrBlank(gp.jobAddressCode) !== '')) {
        input.jobAddressCode = addressCodeOrBlank(gp.jobAddressCode);
        for (const key of SITE_ADDRESS_KEYS) delete input[key];
      }
    }
    try {
      await updateProject({ variables: { id: project.id, input } });
      showToast('Project updated', 'success');
      onClose();
    } catch (err) {
      // Stays open with every value as typed, so the fix is one edit away.
      setGpError(extractGpError(err));
    }
  }, [
    nexus,
    gpChanged,
    changedGpKeys,
    gp,
    customerChanged,
    customerNumber,
    jobAddressPicked,
    siteAddressChanged,
    updateProject,
    project.id,
    showToast,
    onClose,
  ]);

  if (writingToGp) {
    return (
      <Modal
        open
        title={`Edit ${project.projectId}`}
        // GP is mid-write: there is nothing to cancel, and closing would hide the answer.
        onClose={() => {}}
        disableEscapeKeyDown
        hideCloseButton
        maxWidth="sm"
      >
        <Box sx={{ py: 0.5 }}>
          <ProcessingStep
            state="running"
            label="Writing to GP"
            detail={`Saving the changes to GP job ${project.projectId}, then reading the job back from GP.`}
          />
        </Box>
      </Modal>
    );
  }

  const readOnly: Array<[string, string]> = [
    ['Project Number', project.projectId],
    ['Submittal Job No', project.submittalJobNo ?? '—'],
    ['Submittal Assignment Count', project.submittalAssignmentCount?.toString() ?? '—'],
    ['Estimator Code', project.estimatorCode ?? '—'],
    ['TITAN User ID', project.titanUserId ?? '—'],
  ];

  const gpDisabled = !gpEditable || loading;
  const blankHelp = (key: GpKey) => (isBlanked(key) ? 'GP holds a value here, so it cannot be left blank' : undefined);
  const siteLocked = jobAddressPicked;
  const jobAddressLocked = siteAddressChanged;

  const gpTextField = (key: GpKey, label: string, extra?: { maxLength?: number; locked?: boolean }) => (
    <TextField
      key={key}
      label={label}
      value={gp[key]}
      onChange={(e) => setGpField(key, e.target.value)}
      disabled={gpDisabled || extra?.locked === true}
      error={isBlanked(key)}
      helperText={blankHelp(key)}
      size="small"
      fullWidth
      sx={{ minWidth: 0 }}
      slotProps={extra?.maxLength ? { htmlInput: { maxLength: extra.maxLength } } : undefined}
    />
  );

  const actions = (
    <Stack direction="row" spacing={1} alignItems="center">
      {saveBlockedReason && (
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'right' }}>
          {saveBlockedReason}
        </Typography>
      )}
      <Button onClick={onClose} disabled={loading}>
        Cancel
      </Button>
      <Button variant="contained" onClick={handleSubmit} disabled={loading || saveBlockedReason !== null}>
        {loading ? 'Saving...' : 'Save'}
      </Button>
    </Stack>
  );

  return (
    <Modal open title={`Edit ${project.projectId}`} onClose={onClose} actions={actions} maxWidth="md">
      <Stack spacing={2} sx={{ pt: 1 }}>
        {gpError?.code === RELAY_OP_UNSUPPORTED ? (
          <Alert severity="warning" onClose={() => setGpError(null)}>
            The connected relay is too old to change GP jobs. Update the relay on that workstation, then save again.
            Nothing was saved.
          </Alert>
        ) : (
          gpError && (
            <GpErrorAlert
              error={gpError}
              title={
                gpError.code === 'RELAY_UNAVAILABLE' || gpError.code === 'RELAY_TIMEOUT'
                  ? 'GP could not be reached, so nothing was saved'
                  : undefined
              }
              onClose={() => setGpError(null)}
            />
          )
        )}

        <FormControlLabel
          control={
            <Switch
              checked={nexus.offSiteStorageAgreement}
              onChange={(e) => setNexus((f) => ({ ...f, offSiteStorageAgreement: e.target.checked }))}
            />
          }
          label="Off-site storage agreement (OSSA)"
        />

        <Stack direction="row" spacing={1} alignItems="center">
          <Typography component="div" sx={microLabelSx}>
            GP job
          </Typography>
          <GpJobStateTag project={project} />
        </Stack>
        {jobNotOpen && (
          <Alert severity="info">{`${gpJobNotOpenReason(project)} The GP fields are read-only.`}</Alert>
        )}
        {!jobNotOpen && relay.connected === false && (
          <Alert severity="warning">
            The GP relay is not connected. The GP fields can only be changed against live GP data, so they stay
            read-only until the relay is running.
          </Alert>
        )}
        {gpEditable && readError && (
          <Alert severity="error">
            Could not read the job setup data from GP, so the fields below are incomplete. {readError.message}
          </Alert>
        )}

        {gpTextField('description', 'Job name', { maxLength: MAX.jobName })}

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '2fr 1fr' }, gap: 2 }}>
          <Box sx={{ minWidth: 0 }}>
            <GpCustomerField
              label="Customer"
              value={customer}
              onChange={handleCustomerChange}
              customers={customers}
              loading={customersLoading}
              disabled={gpDisabled}
              disableClearable={customer !== null}
            />
          </Box>
          <GpDivisionField
            value={gp.division}
            onChange={(v) => setGpField('division', v)}
            divisions={divisions}
            disabled={gpDisabled || divisionsLoading}
          />
        </Box>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <GpAddressField
            label="Job address"
            value={gp.jobAddressCode}
            onChange={(v) => setGpField('jobAddressCode', v)}
            addresses={addresses}
            onAddNew={customer ? () => startAddAddress(customer, (v) => setGpField('jobAddressCode', v)) : undefined}
            required={customerChanged}
            disabled={gpDisabled || !customer || addressesLoading || jobAddressLocked}
            helperText={jobAddressLocked ? 'The site address below is being changed instead' : ' '}
          />
          <GpAddressField
            label="Bill-to address"
            value={gp.billtoAddressCode}
            onChange={(v) => setGpField('billtoAddressCode', v)}
            addresses={addresses}
            onAddNew={
              customer ? () => startAddAddress(customer, (v) => setGpField('billtoAddressCode', v)) : undefined
            }
            required={customerChanged}
            disabled={gpDisabled || !customer || addressesLoading}
            helperText=" "
          />
        </Stack>

        <Box>
          <Typography component="div" sx={microLabelSx}>
            Site address
          </Typography>
          {siteLocked && gpEditable && (
            <Typography variant="caption" color="text.secondary">
              The site address comes from the job address picked above.
            </Typography>
          )}
        </Box>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          {gpTextField('address', 'Address', { locked: siteLocked })}
          {gpTextField('address2', 'Address 2', { locked: siteLocked })}
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', sm: '2fr 1fr 1fr 1fr' }, gap: 2 }}>
          {CITY_ROW.map(([key, label]) => gpTextField(key, label, { locked: siteLocked }))}
        </Box>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <GpTaxScheduleField
            label="Tax schedule"
            value={gp.taxScheduleId}
            onChange={(v) => setGpField('taxScheduleId', v)}
            taxSchedules={taxSchedules}
            disabled={gpDisabled || taxSchedulesLoading}
            sx={{ flex: 1 }}
          />
          <GpTaxScheduleField
            label="Use tax schedule"
            value={gp.useTaxScheduleId}
            onChange={(v) => setGpField('useTaxScheduleId', v)}
            taxSchedules={taxSchedules}
            // A use-tax schedule GP already holds can be changed, not removed.
            allowNone={initialGp.useTaxScheduleId === ''}
            disabled={gpDisabled || taxSchedulesLoading}
            sx={{ flex: 1 }}
          />
        </Stack>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <EmployeeField
            label="Estimator"
            value={gp.estimatorId}
            onChange={(v) => setGpField('estimatorId', v)}
            employees={employees}
            loading={employeesLoading}
            unavailable={Boolean(employeesError)}
            disabled={gpDisabled}
            disableClearable={initialGp.estimatorId !== ''}
          />
          <EmployeeField
            label="WS Manager"
            value={gp.wsManagerId}
            onChange={(v) => setGpField('wsManagerId', v)}
            employees={employees}
            loading={employeesLoading}
            unavailable={Boolean(employeesError)}
            disabled={gpDisabled}
            disableClearable={initialGp.wsManagerId !== ''}
          />
        </Stack>

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1fr' }, gap: 2 }}>
          {DATE_ROW.map(([key, label]) => (
            <GpDateField
              key={key}
              label={label}
              value={gp[key]}
              onChange={(v) => setGpField(key, v)}
              disabled={gpDisabled}
              helperText={blankHelp(key)}
            />
          ))}
        </Box>

        <Divider />
        <Typography component="div" sx={microLabelSx}>
          Nexus
        </Typography>
        <TextField label="Job Site Name" value={nexus.jobSiteName} onChange={setNexusText('jobSiteName')} fullWidth />
        <TextField label="General Contractor" value={nexus.contractor} onChange={setNexusText('contractor')} fullWidth />
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField
            label="GC Contact Name"
            value={nexus.gcContactName}
            onChange={setNexusText('gcContactName')}
            fullWidth
          />
          <TextField label="GC Phone" value={nexus.gcPhone} onChange={setNexusText('gcPhone')} fullWidth />
          <TextField label="GC Email" value={nexus.gcEmail} onChange={setNexusText('gcEmail')} fullWidth />
        </Stack>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField
            label="Project Manager"
            value={nexus.projectManager}
            onChange={setNexusText('projectManager')}
            fullWidth
          />
          <TextField label="Application" value={nexus.application} onChange={setNexusText('application')} fullWidth />
        </Stack>

        <Divider />
        <Typography component="div" sx={microLabelSx}>
          From TITAN (read-only)
        </Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1.5 }}>
          {readOnly.map(([label, value]) => (
            <Box key={label}>
              <Typography variant="caption" color="text.secondary" component="div">
                {label}
              </Typography>
              <Typography component="div" sx={monoSx}>
                {value}
              </Typography>
            </Box>
          ))}
        </Box>
      </Stack>
      {addAddress.dialog}
    </Modal>
  );
}

export default function ProjectEditDialog({ open, project, onClose }: ProjectEditDialogProps) {
  if (!open || !project) return null;
  return <ProjectEditDialogContent project={project} onClose={onClose} />;
}
