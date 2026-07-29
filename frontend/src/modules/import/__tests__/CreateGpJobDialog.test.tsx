import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import CreateGpJobDialog from '../CreateGpJobDialog';
import {
  CREATE_GP_JOB,
  GET_GP_CUSTOMERS,
  GET_GP_CUSTOMER_ADDRESSES,
  GET_GP_DIVISIONS,
  GET_GP_EMPLOYEES,
  GET_GP_TAX_SCHEDULES,
} from '../../../graphql/import';
import { GET_PROJECTS, GET_RELAY_STATUS } from '../../../graphql/shared';

vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

const INFINITE = Number.POSITIVE_INFINITY;
const COMPANY = 'TUBC';

function relayStatusMock(connected: boolean): MockedResponse {
  return {
    request: { query: GET_RELAY_STATUS },
    maxUsageCount: INFINITE,
    result: {
      data: {
        relayStatus: {
          connected,
          company: connected ? COMPANY : null,
          build: connected ? 'relay-v0.1.0-build.40' : null,
          installId: connected ? 'install-1' : null,
          __typename: 'RelayStatus',
        },
      },
    },
  };
}

// Named so tests that need to replace or count it can swap it out of readMocks by identity.
const employeesReadMock: MockedResponse = {
  request: { query: GET_GP_EMPLOYEES, variables: { company: COMPANY } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      gpEmployees: [
        { employeeId: 'IANB', firstName: 'Ian', lastName: 'Brown', __typename: 'GpEmployee' },
        { employeeId: 'JONATHANR', firstName: 'Jonathan', lastName: 'Ruballos', __typename: 'GpEmployee' },
      ],
    },
  },
};

const readMocks: MockedResponse[] = [
  {
    request: { query: GET_GP_CUSTOMERS, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        gpCustomers: [
          { customerNumber: 'ELL100', customerName: 'Ellis Don', __typename: 'GpCustomer' },
          { customerNumber: 'SCO100', customerName: 'Scott Construction', __typename: 'GpCustomer' },
        ],
      },
    },
  },
  {
    request: { query: GET_GP_DIVISIONS, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: { data: { gpDivisions: ['VANCOUVER'] } },
  },
  employeesReadMock,
  {
    request: { query: GET_GP_TAX_SCHEDULES, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        gpTaxSchedules: [
          { taxScheduleId: 'GST 5%', description: 'Federal GST 5%', __typename: 'GpTaxSchedule' },
          { taxScheduleId: 'BC HST', description: 'BC HST 12%', __typename: 'GpTaxSchedule' },
        ],
      },
    },
  },
  {
    request: { query: GET_GP_CUSTOMER_ADDRESSES, variables: { company: COMPANY, customer: 'ELL100' } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        gpCustomerAddresses: [
          {
            addressCode: 'MAIN',
            address1: '1 Main St',
            city: 'Vancouver',
            state: 'BC',
            __typename: 'GpCustomerAddress',
          },
          {
            addressCode: 'SITE2',
            address1: '9 Site Rd',
            city: 'Burnaby',
            state: 'BC',
            __typename: 'GpCustomerAddress',
          },
        ],
      },
    },
  },
];

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: { data: { projects: [] } },
};

function renderDialog(mocks: MockedResponse[] = [], { connected = true } = {}) {
  return render(
    <MockedProvider mocks={[relayStatusMock(connected), ...readMocks, projectsMock, ...mocks]}>
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );
}

/**
 * MUI selects are comboboxes rendering their options into a portal listbox. Each one stays disabled
 * until the GP read behind it resolves - and those reads only fire after the relay status lands, so
 * every interaction here has to wait the field out rather than assume it is ready.
 */
async function pickFromSelect(name: RegExp, optionText: RegExp) {
  const trigger = await screen.findByRole('combobox', { name });
  await waitFor(() => expect(trigger).not.toHaveAttribute('aria-disabled', 'true'));
  fireEvent.mouseDown(trigger);
  const listbox = await screen.findByRole('listbox');
  fireEvent.click(await within(listbox).findByText(optionText));
}

async function pickEmployee(label: RegExp, option: RegExp) {
  const input = await screen.findByRole('combobox', { name: label });
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.mouseDown(input);
  fireEvent.change(input, { target: { value: 'IAN' } });
  fireEvent.click(await screen.findByText(option));
}

async function pickCustomer(name: RegExp) {
  const input = await screen.findByRole('combobox', { name: /^Customer/ });
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.mouseDown(input);
  fireEvent.change(input, { target: { value: 'E' } });
  fireEvent.click(await screen.findByText(name));
}

function typeInto(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** Everything the proc requires, in the order the form asks for it. */
async function fillRequired() {
  // Nothing is editable until the relay status resolves - the company it carries is what the GP
  // reads are keyed on.
  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());

  typeInto(/^Job number/, 'NEXUS-380-T1');
  typeInto(/^Job name/, 'Test job');
  await pickFromSelect(/^Division/, /VANCOUVER/);
  await pickCustomer(/Ellis Don/);
  await pickFromSelect(/^Job address/, /MAIN/);
  await pickFromSelect(/^Bill-to address/, /MAIN/);
  await pickFromSelect(/^Tax schedule/, /Federal GST 5%/);
  typeInto(/^Created date/, '2025-09-15');
}

function createButton() {
  return screen.getByRole('button', { name: /Create Job/i });
}

test('the create button stays disabled until every required field is filled', async () => {
  renderDialog();
  await screen.findByLabelText(/^Job number/);

  expect(createButton()).toBeDisabled();

  await fillRequired();

  await waitFor(() => expect(createButton()).toBeEnabled());
});

test('the address selects are disabled until a customer is picked', async () => {
  renderDialog();
  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());

  // An address code is only valid under its own customer, so there is nothing to offer yet.
  expect(screen.getByRole('combobox', { name: /^Job address/ })).toHaveAttribute('aria-disabled', 'true');
  expect(screen.getByRole('combobox', { name: /^Bill-to address/ })).toHaveAttribute('aria-disabled', 'true');

  await pickCustomer(/Ellis Don/);

  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: /^Job address/ })).not.toHaveAttribute('aria-disabled', 'true'),
  );
  expect(screen.getByRole('combobox', { name: /^Bill-to address/ })).not.toHaveAttribute('aria-disabled', 'true');
});

test('a relay too old for the new ops says so instead of showing empty dropdowns', async () => {
  // The deploy-before-relay-rebuild window: the required reads are not in the installed relay's
  // advertised op-set. Without this the dialog renders a green relay chip over empty required
  // dropdowns and a permanently disabled button, with nothing explaining why.
  const unsupported: MockedResponse[] = [GET_GP_CUSTOMERS, GET_GP_DIVISIONS, GET_GP_TAX_SCHEDULES, GET_GP_EMPLOYEES].map((query) => ({
    request: { query, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: {
      errors: [
        new GraphQLError('The connected relay does not support list_customers', {
          extensions: { code: 'RELAY_OP_UNSUPPORTED' },
        }),
      ],
    },
  }));

  render(
    <MockedProvider mocks={[relayStatusMock(true), ...unsupported, projectsMock]}>
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  expect(await screen.findByText(/relay is too old to create jobs/i)).toBeInTheDocument();
});

test('a failed GP read is reported rather than looking like an empty list', async () => {
  const failing: MockedResponse[] = [GET_GP_CUSTOMERS, GET_GP_DIVISIONS, GET_GP_TAX_SCHEDULES, GET_GP_EMPLOYEES].map((query) => ({
    request: { query, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: { errors: [new GraphQLError('relay timed out')] },
  }));

  render(
    <MockedProvider mocks={[relayStatusMock(true), ...failing, projectsMock]}>
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  expect(await screen.findByText(/Could not read the job setup data from GP/i)).toBeInTheDocument();
});

test('an adopted job does not claim it was created', async () => {
  // #392: GP already held the number, so createGpJob adopted rather than created. Saying "created"
  // there reports something that did not happen.
  const adopted: MockedResponse = {
    request: {
      query: CREATE_GP_JOB,
      variables: {
        input: {
          jobNumber: 'NEXUS-380-T1',
          jobName: 'Test job',
          division: 'VANCOUVER',
          customerNumber: 'ELL100',
          jobAddressCode: 'MAIN',
          billtoAddressCode: 'MAIN',
          taxScheduleId: 'GST 5%',
          createdDate: '2025-09-15',
          estimatorId: null,
          wsManagerId: null,
          wsProjectNumber: null,
          billCustomerNumber: null,
          useTaxSchedule: null,
          scheduleStartDate: null,
          scheduledCompletionDate: null,
          bidDueDate: null,
        },
      },
    },
    result: {
      data: {
        createGpJob: {
          created: false,
          project: { id: 'project-1', __typename: 'Project' },
          __typename: 'CreateGpJobResult',
        },
      },
    },
  };

  renderDialog([adopted]);
  await fillRequired();
  await waitFor(() => expect(createButton()).toBeEnabled());
  fireEvent.click(createButton());

  expect(await screen.findByText(/already existed in GP and is now a project/)).toBeInTheDocument();
});

test('a relay missing only the employees op does not claim jobs cannot be created', async () => {
  // #392 review: folding the OPTIONAL employees read into readsUnsupported made a relay that serves
  // create_job perfectly well announce "too old to create jobs" while the form stayed enabled and the
  // create went through. That is exactly the window between deploying this and updating the relay.
  const employeesUnsupported: MockedResponse = {
    request: { query: GET_GP_EMPLOYEES, variables: { company: COMPANY } },
    maxUsageCount: INFINITE,
    result: {
      errors: [
        new GraphQLError('The connected relay does not support list_employees', {
          extensions: { code: 'RELAY_OP_UNSUPPORTED' },
        }),
      ],
    },
  };

  render(
    <MockedProvider
      mocks={[relayStatusMock(true), ...readMocks.filter((m) => m !== employeesReadMock), employeesUnsupported, projectsMock]}
    >
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  await fillRequired();
  // the required reads all succeeded, so the create is genuinely available
  await waitFor(() => expect(createButton()).toBeEnabled());
  expect(screen.queryByText(/relay is too old to create jobs/i)).not.toBeInTheDocument();

  // and BOTH optional fields degrade to free text rather than becoming unsettable
  fireEvent.click(screen.getByRole('button', { name: /Show optional fields/i }));
  expect(await screen.findAllByText(/Employee list unavailable/i)).toHaveLength(2);
  expect(screen.getByLabelText(/^Estimator/)).toBeEnabled();
  expect(screen.getByLabelText(/^WS Manager/)).toBeEnabled();
});

test('the employees read is deferred until the optional section is opened', async () => {
  // Both consumers live behind the toggle, so every dialog open would otherwise cost a relay
  // round-trip and a payroll read that most creates never use.
  let employeeFetches = 0;
  const counted: MockedResponse = {
    ...employeesReadMock,
    result: () => {
      employeeFetches += 1;
      return { data: { gpEmployees: [] } };
    },
  } as MockedResponse;

  render(
    <MockedProvider mocks={[relayStatusMock(true), ...readMocks.filter((m) => m !== employeesReadMock), counted, projectsMock]}>
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());
  expect(employeeFetches).toBe(0);

  fireEvent.click(screen.getByRole('button', { name: /Show optional fields/i }));
  await waitFor(() => expect(employeeFetches).toBe(1));
});

test('the whole form is disabled while the relay is down', async () => {
  renderDialog([], { connected: false });

  expect(await screen.findByText(/GP relay is not connected/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/^Job number/)).toBeDisabled();
  expect(createButton()).toBeDisabled();
});

test("a GP rejection is shown in the proc's own words and the dialog stays open", async () => {
  const failure: MockedResponse = {
    request: {
      query: CREATE_GP_JOB,
      variables: {
        input: {
          jobNumber: 'NEXUS-380-T1',
          jobName: 'Test job',
          division: 'VANCOUVER',
          customerNumber: 'ELL100',
          jobAddressCode: 'MAIN',
          billtoAddressCode: 'MAIN',
          taxScheduleId: 'GST 5%',
          createdDate: '2025-09-15',
          estimatorId: null,
          wsManagerId: null,
          wsProjectNumber: null,
          billCustomerNumber: null,
          useTaxSchedule: null,
          scheduleStartDate: null,
          scheduledCompletionDate: null,
          bidDueDate: null,
        },
      },
    },
    result: {
      errors: [
        new GraphQLError('Job cannot be created within a closed period', {
          extensions: { code: 'VALIDATION_ERROR' },
        }),
      ],
    },
  };

  renderDialog([failure]);
  await screen.findByLabelText(/^Job number/);
  await fillRequired();
  await waitFor(() => expect(createButton()).toBeEnabled());

  fireEvent.click(createButton());

  expect(await screen.findByText(/Job cannot be created within a closed period/)).toBeInTheDocument();
  // still open, so the date can be corrected without re-entering the whole form
  expect(screen.getByLabelText(/^Job number/)).toBeInTheDocument();
});

test('a successful submit sends only the optional fields that were filled in', async () => {
  // The mock matches on exact variables, so this object IS the assertion on the payload: the two
  // optional fields that were filled carry values, and the six that were not travel as null rather
  // than as blank strings - GP keeps its own defaults for those. Any other shape fails to match and
  // the submit errors instead of succeeding.
  const success: MockedResponse = {
    request: {
      query: CREATE_GP_JOB,
      variables: {
        input: {
          jobNumber: 'NEXUS-380-T1',
          jobName: 'Test job',
          division: 'VANCOUVER',
          customerNumber: 'ELL100',
          jobAddressCode: 'MAIN',
          billtoAddressCode: 'MAIN',
          taxScheduleId: 'GST 5%',
          createdDate: '2025-09-15',
          estimatorId: 'IANB',
          scheduleStartDate: '2025-09-20',
          wsManagerId: null,
          wsProjectNumber: null,
          billCustomerNumber: null,
          useTaxSchedule: null,
          scheduledCompletionDate: null,
          bidDueDate: null,
        },
      },
    },
    result: {
      data: {
        createGpJob: {
          created: true,
          project: { id: 'project-1', __typename: 'Project' },
          __typename: 'CreateGpJobResult',
        },
      },
    },
  };

  renderDialog([success]);
  await fillRequired();

  fireEvent.click(screen.getByRole('button', { name: /Show optional fields/i }));
  await pickEmployee(/^Estimator/, /IANB/);
  typeInto(/^Scheduled start/, '2025-09-20');

  await waitFor(() => expect(createButton()).toBeEnabled());
  fireEvent.click(createButton());

  expect(await screen.findByText(/Job NEXUS-380-T1 created in GP/)).toBeInTheDocument();
});
