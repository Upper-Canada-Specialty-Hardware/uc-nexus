import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import ProjectEditDialog, { type ProjectFormValue } from '../ProjectEditDialog';
import { GET_ADMIN_PROJECTS, UPDATE_PROJECT } from '../../../graphql/admin';
import {
  GET_GP_CUSTOMERS,
  GET_GP_CUSTOMER_ADDRESSES,
  GET_GP_DIVISIONS,
  GET_GP_EMPLOYEES,
  GET_GP_TAX_SCHEDULES,
} from '../../../graphql/import';
import { GET_RELAY_STATUS } from '../../../graphql/shared';

vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

const INFINITE = Number.POSITIVE_INFINITY;
const COMPANY = 'TUBC';
const PROJECT_ID = '11111111-2222-3333-4444-555555555555';

function project(overrides: Partial<ProjectFormValue> = {}): ProjectFormValue {
  return {
    id: PROJECT_ID,
    projectId: 'JOB-100',
    description: 'Riverside Tower',
    client: 'Ellis Construction',
    jobSiteName: 'Riverside',
    company: COMPANY,
    archived: false,
    address: '1 Main St',
    city: 'Vancouver',
    state: 'BC',
    zip: 'V5K',
    contractor: 'Ledcor',
    projectManager: 'Dana',
    application: null,
    gcContactName: null,
    gcPhone: null,
    gcEmail: null,
    offSiteStorageAgreement: false,
    submittalJobNo: null,
    submittalAssignmentCount: null,
    estimatorCode: null,
    titanUserId: null,
    openingCount: 4,
    gpSetupOk: true,
    gpSetupCheckedAt: null,
    gpSetupIssues: null,
    gpJobState: 'ACTIVE',
    gpClosedDate: null,
    customerNumber: 'ELL100',
    jobAddressCode: 'MAIN',
    billtoAddressCode: 'BILL',
    address2: null,
    country: 'CA',
    division: 'DIV1',
    taxScheduleId: 'BC-GST',
    useTaxScheduleId: null,
    estimatorId: 'E1',
    estimatorName: 'Erin Estimator',
    wsManagerId: null,
    wsManagerName: null,
    gpCreatedDate: '2026-01-05',
    scheduleStartDate: '2026-02-01',
    scheduledCompletionDate: null,
    bidDueDate: null,
    origContractAmount: 1000,
    contractToDate: 1200,
    totalActualCost: 500,
    billedAmountTtd: 800,
    retentionAmountTtd: 80,
    netBilledTtd: 720,
    ...overrides,
  };
}

const relayMock: MockedResponse = {
  request: { query: GET_RELAY_STATUS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      relayStatus: {
        connected: true,
        companies: [COMPANY],
        gpCompanies: [{ id: COMPANY, name: 'Test UBC', __typename: 'GpCompany' }],
        companiesError: null,
        build: 'relay-v0.1.0-build.80',
        installId: 'install-1',
        lastConnectedAt: null,
        lastDisconnectedAt: null,
        lastDisconnectReason: null,
        previewChannels: [],
        __typename: 'RelayStatus',
      },
    },
  },
};

function address(addressCode: string, address1: string) {
  return { addressCode, address1, city: 'Vancouver', state: 'BC', __typename: 'GpCustomerAddress' };
}

const readMocks: MockedResponse[] = [
  relayMock,
  {
    request: { query: GET_GP_CUSTOMERS, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        gpCustomers: [
          { customerNumber: 'ELL100', customerName: 'Ellis Construction', __typename: 'GpCustomer' },
          { customerNumber: 'PCL200', customerName: 'PCL Builders', __typename: 'GpCustomer' },
        ],
      },
    },
  },
  {
    request: { query: GET_GP_DIVISIONS, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: { data: { gpDivisions: ['DIV1', 'DIV2'] } },
  },
  {
    request: { query: GET_GP_TAX_SCHEDULES, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        gpTaxSchedules: [
          { taxScheduleId: 'BC-GST', description: 'BC GST', __typename: 'GpTaxSchedule' },
          { taxScheduleId: 'BC-PST', description: 'BC PST', __typename: 'GpTaxSchedule' },
        ],
      },
    },
  },
  {
    request: { query: GET_GP_EMPLOYEES, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        gpEmployees: [
          { employeeId: 'E1', firstName: 'Erin', lastName: 'Estimator', __typename: 'GpEmployee' },
          { employeeId: 'E2', firstName: 'Wes', lastName: 'Manager', __typename: 'GpEmployee' },
        ],
      },
    },
  },
  {
    request: { query: GET_GP_CUSTOMER_ADDRESSES, variables: { company: COMPANY, customer: 'ELL100' } },
    maxUsageCount: INFINITE,
    result: { data: { gpCustomerAddresses: [address('MAIN', '1 Main St'), address('BILL', '2 Bill St')] } },
  },
  {
    request: { query: GET_GP_CUSTOMER_ADDRESSES, variables: { company: COMPANY, customer: 'PCL200' } },
    maxUsageCount: INFINITE,
    result: { data: { gpCustomerAddresses: [address('HQ', '5 Head Rd'), address('YARD', '6 Yard Ln')] } },
  },
  {
    request: { query: GET_ADMIN_PROJECTS },
    maxUsageCount: INFINITE,
    result: { data: { adminProjects: [] } },
  },
];

type UpdateVars = { id: string; input: Record<string, unknown> };

/** The mutation, answering with the project as GP read it back, and recording what was sent. */
function updateMock(sent: UpdateVars[], opts: { delay?: number; error?: GraphQLError } = {}): MockedResponse {
  return {
    request: { query: UPDATE_PROJECT, variables: () => true },
    maxUsageCount: INFINITE,
    delay: opts.delay,
    result: (vars: UpdateVars) => {
      sent.push(vars);
      if (opts.error) return { errors: [opts.error] };
      return { data: { updateProject: { __typename: 'Project', ...project(), createdAt: '', updatedAt: '' } } };
    },
  } as MockedResponse;
}

function renderDialog(p: ProjectFormValue, mocks: MockedResponse[]) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={[...readMocks, ...mocks]}>
      <ToastProvider>
        <ProjectEditDialog open project={p} onClose={onClose} />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onClose };
}

const saveButton = () => screen.getByRole('button', { name: 'Save' });

/** Wait for the live reads - the division list is the last picker to come up. */
async function waitForGpReads() {
  await waitFor(() => expect(screen.getByLabelText('Division')).not.toHaveAttribute('aria-disabled'));
  await waitFor(() => expect(screen.getByLabelText('Job name')).toBeEnabled());
}

async function pickSelect(label: string | RegExp, option: RegExp) {
  await waitFor(() => expect(screen.getByLabelText(label)).not.toHaveAttribute('aria-disabled'));
  fireEvent.mouseDown(screen.getByLabelText(label));
  const listbox = await screen.findByRole('listbox');
  fireEvent.click(within(listbox).getByText(option));
  await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
}

async function pickCustomer(name: RegExp) {
  const input = screen.getByLabelText('Customer');
  input.focus();
  fireEvent.change(input, { target: { value: 'PCL' } });
  fireEvent.click(await screen.findByText(name));
}

describe('ProjectEditDialog (#730)', () => {
  it('saves Nexus-only changes without touching GP or waiting on it', async () => {
    const sent: UpdateVars[] = [];
    const { onClose } = renderDialog(project(), [updateMock(sent)]);
    await waitForGpReads();

    fireEvent.change(screen.getByLabelText('Project Manager'), { target: { value: 'Pat' } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(screen.queryByText('Writing to GP')).toBeNull();
    const input = sent[0].input;
    expect(input.projectManager).toBe('Pat');
    for (const key of ['description', 'client', 'customerNumber', 'address', 'jobAddressCode', 'division']) {
      expect(input).not.toHaveProperty(key);
    }
  });

  it('waits on GP in front of the person while a GP field is written, then closes', async () => {
    const sent: UpdateVars[] = [];
    const { onClose } = renderDialog(project(), [updateMock(sent, { delay: 300 })]);
    await waitForGpReads();

    fireEvent.change(screen.getByLabelText('Job name'), { target: { value: 'Riverside Tower II' } });
    await pickSelect('Division', /^DIV2$/);
    fireEvent.click(saveButton());

    expect(await screen.findByText('Writing to GP')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    // Only the GP fields that changed go to GP.
    expect(sent[0].input).toMatchObject({ description: 'Riverside Tower II', division: 'DIV2' });
    expect(sent[0].input).not.toHaveProperty('taxScheduleId');
    expect(sent[0].input).not.toHaveProperty('client');
  });

  it('stays open with the error and every typed value when GP refuses the save', async () => {
    const sent: UpdateVars[] = [];
    const error = new GraphQLError('GP refused the job name.', {
      extensions: { code: 'VALIDATION_ERROR', field: 'description' },
    });
    const { onClose } = renderDialog(project(), [updateMock(sent, { error })]);
    await waitForGpReads();

    fireEvent.change(screen.getByLabelText('Job name'), { target: { value: 'Riverside Tower II' } });
    fireEvent.change(screen.getByLabelText('Project Manager'), { target: { value: 'Pat' } });
    fireEvent.click(saveButton());

    expect(await screen.findByText('GP refused the job name.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Job name')).toHaveValue('Riverside Tower II');
    expect(screen.getByLabelText('Project Manager')).toHaveValue('Pat');
    expect(saveButton()).toBeEnabled();
  });

  it('tells the person to update the relay when it is too old to change jobs', async () => {
    const sent: UpdateVars[] = [];
    const error = new GraphQLError('Relay does not support update_job.', {
      extensions: { code: 'RELAY_OP_UNSUPPORTED' },
    });
    renderDialog(project(), [updateMock(sent, { error })]);
    await waitForGpReads();

    fireEvent.change(screen.getByLabelText('Job name'), { target: { value: 'Riverside Tower II' } });
    fireEvent.click(saveButton());

    expect(await screen.findByText(/Update the relay on that workstation/)).toBeInTheDocument();
  });

  it.each([
    ['CLOSED', 'Closed in GP'],
    ['INACTIVE', 'Inactive in GP'],
    ['NOT_IN_GP', 'Not in GP'],
  ] as const)('shows the GP fields read-only with the tag on a %s job, Nexus fields editable', async (state, tag) => {
    const sent: UpdateVars[] = [];
    const { onClose } = renderDialog(project({ gpJobState: state }), [updateMock(sent)]);

    expect(await screen.findByText(tag)).toBeInTheDocument();
    expect(screen.getByText(/The GP fields are read-only\./)).toBeInTheDocument();
    expect(screen.getByLabelText('Job name')).toBeDisabled();
    expect(screen.getByLabelText('Job name')).toHaveValue('Riverside Tower');
    expect(screen.getByLabelText('Customer')).toBeDisabled();
    expect(screen.getByLabelText('Address')).toBeDisabled();
    expect(screen.getByLabelText('Scheduled start')).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Project Manager'), { target: { value: 'Pat' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(sent[0].input).not.toHaveProperty('description');
  });

  it('makes both addresses be picked again for a new customer, and sends them with it', async () => {
    const sent: UpdateVars[] = [];
    const { onClose } = renderDialog(project(), [updateMock(sent)]);
    await waitForGpReads();
    expect(screen.getByLabelText(/^Job address/)).toHaveTextContent('MAIN');

    await pickCustomer(/PCL Builders/);

    // The old codes belonged to the old customer.
    await waitFor(() => expect(screen.getByLabelText(/^Job address/)).not.toHaveTextContent('MAIN'));
    expect(screen.getByLabelText(/^Bill-to address/)).not.toHaveTextContent('BILL');
    expect(saveButton()).toBeDisabled();
    expect(screen.getByText(/Pick the bill-to address, and a job address or a new site address/)).toBeInTheDocument();

    await pickSelect(/^Job address/, /^HQ - /);
    expect(saveButton()).toBeDisabled();
    await pickSelect(/^Bill-to address/, /^YARD - /);
    expect(saveButton()).toBeEnabled();
    // A picked job address is where the site comes from, so the typed site is locked.
    expect(screen.getByLabelText('Address')).toBeDisabled();

    fireEvent.click(saveButton());
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const input = sent[0].input;
    expect(input).toMatchObject({ customerNumber: 'PCL200', jobAddressCode: 'HQ', billtoAddressCode: 'YARD' });
    expect(input).not.toHaveProperty('client');
    expect(input).not.toHaveProperty('address');
    expect(input).not.toHaveProperty('city');
  });

  it('sends a typed site address instead of a job address code, never both', async () => {
    const sent: UpdateVars[] = [];
    const { onClose } = renderDialog(project(), [updateMock(sent)]);
    await waitForGpReads();

    fireEvent.change(screen.getByLabelText('Address'), { target: { value: '9 New Rd' } });
    expect(screen.getByLabelText(/^Job address/)).toHaveAttribute('aria-disabled', 'true');

    fireEvent.click(saveButton());
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const input = sent[0].input;
    expect(input).toMatchObject({ address: '9 New Rd', city: 'Vancouver', state: 'BC', zip: 'V5K' });
    expect(input).not.toHaveProperty('jobAddressCode');
  });

  it('will not blank a value GP holds', async () => {
    renderDialog(project(), [updateMock([])]);
    await waitForGpReads();

    fireEvent.change(screen.getByLabelText('Job name'), { target: { value: '' } });

    expect(saveButton()).toBeDisabled();
    expect(screen.getByText('A value GP holds cannot be cleared from Nexus')).toBeInTheDocument();
    // The use-tax schedule is blank in GP, so it may stay blank; the estimator is held, so it offers
    // no way to clear it.
    expect(screen.getByLabelText('Estimator').closest('.MuiAutocomplete-root')).not.toHaveClass(
      'MuiAutocomplete-hasClearIcon',
    );
  });
});
