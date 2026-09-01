import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import CreateGpJobDialog from '../CreateGpJobDialog';
import {
  CREATE_GP_CUSTOMER_ADDRESS,
  CREATE_GP_JOB,
  GET_GP_COST_CODE_MASTER,
  GET_GP_CUSTOMERS,
  GET_GP_CUSTOMER_ADDRESSES,
  GET_GP_DIVISIONS,
  GET_GP_EMPLOYEES,
  GET_GP_TAX_SCHEDULES,
} from '../../../graphql/import';
import { GET_PROJECTS, GET_RELAY_STATUS } from '../../../graphql/shared';

vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

// #637: the dialog resolves which GP company to create the job in from the caller's identity, so
// the hook is stubbed rather than reaching for a Clerk provider this file does not mount.
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_admin',
    roles: ['Admin/Manager'],
    hasRole: () => true,
    isAdmin: true,
    gpBuyerId: null,
    company: null,
    user: null,
  }),
}));

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
          companies: connected ? [COMPANY] : [],
          build: connected ? 'relay-v0.1.0-build.40' : null,
          installId: connected ? 'install-1' : null,
          lastConnectedAt: null,
          lastDisconnectedAt: null,
          lastDisconnectReason: null,
          configuredCompanies: null,
          previewChannels: [],
          __typename: 'RelayStatus',
        },
      },
    },
  };
}

function address(addressCode: string, address1: string, city: string) {
  return { addressCode, address1, city, state: 'BC', __typename: 'GpCustomerAddress' };
}

// The addresses ELL100 already has in GP. Named like employeesReadMock so a test that has to serve a
// growing list (#444: an address created mid-form) can swap it out of readMocks by identity.
const addressesReadMock: MockedResponse = {
  request: { query: GET_GP_CUSTOMER_ADDRESSES, variables: { company: COMPANY, customer: 'ELL100' } },
  maxUsageCount: INFINITE,
  result: {
    data: { gpCustomerAddresses: [address('MAIN', '1 Main St', 'Vancouver'), address('SITE2', '9 Site Rd', 'Burnaby')] },
  },
};

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

function costCodeEntry(costCode: string, description: string, costElement: number, mapped: boolean) {
  return { costCode, description, costElement, mapped, __typename: 'GpCostCodeMasterEntry' };
}

/**
 * #448: the cost-code master as it applies to VANCOUVER. 210-200 is unmapped - the division has no GL
 * account for that code's cost element - and provisioning it is exactly what the GP-setup check
 * quarantines a project for, so it is the row the picker has to refuse to send.
 *
 * Named like employeesReadMock so a test needing a different master can swap it out by identity.
 */
const costCodeMasterReadMock: MockedResponse = {
  request: { query: GET_GP_COST_CODE_MASTER, variables: { company: COMPANY, division: 'VANCOUVER' } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      gpCostCodeMaster: [
        costCodeEntry('310-000', 'Hardware', 3, true),
        costCodeEntry('520-000', 'Electrical', 2, true),
        costCodeEntry('210-200', 'Site labour', 2, false),
      ],
    },
  },
};

/** What the form defaults to sending: every mapped code in the master, in master order. */
const MAPPED_COST_CODES = [
  { costCode: '310-000', costElement: 3 },
  { costCode: '520-000', costElement: 2 },
];

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
  addressesReadMock,
  costCodeMasterReadMock,
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

async function pickBillCustomer(name: RegExp) {
  const input = await screen.findByRole('combobox', { name: /^Bill-to customer/ });
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.mouseDown(input);
  fireEvent.change(input, { target: { value: 'Scott' } });
  fireEvent.click(await screen.findByText(name));
}

function typeInto(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** Everything the proc requires, in the order the form asks for it. */
async function fillRequiredFields() {
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

/** The above, plus the cost-code master the create waits on. What most tests want. */
async function fillRequired() {
  await fillRequiredFields();
  // #448: the cost-code master is read off the division and its mapped codes default to checked, and
  // they ride along on the create - so a submit fired before that lands carries a different payload.
  // The counter is the master having landed, and the button stays disabled until it has.
  await screen.findByText('2 of 2 selected');
}

/** The row's own checkbox: its accessible name is the label, which leads with GP's own spelling. */
function costCodeBox(code: RegExp) {
  return screen.getByRole('checkbox', { name: code });
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
          company: COMPANY,
          jobNumber: 'NEXUS-380-T1',
          jobName: 'Test job',
          division: 'VANCOUVER',
          customerNumber: 'ELL100',
          jobAddressCode: 'MAIN',
          billtoAddressCode: 'MAIN',
          taxScheduleId: 'GST 5%',
          createdDate: '2025-09-15',
          costCodes: MAPPED_COST_CODES,
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
          // #448: an already-existing job is left as GP has it, so nothing was provisioned onto it.
          costCodesProvisioned: 0,
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
          company: COMPANY,
          jobNumber: 'NEXUS-380-T1',
          jobName: 'Test job',
          division: 'VANCOUVER',
          customerNumber: 'ELL100',
          jobAddressCode: 'MAIN',
          billtoAddressCode: 'MAIN',
          taxScheduleId: 'GST 5%',
          createdDate: '2025-09-15',
          costCodes: MAPPED_COST_CODES,
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
          company: COMPANY,
          jobNumber: 'NEXUS-380-T1',
          jobName: 'Test job',
          division: 'VANCOUVER',
          customerNumber: 'ELL100',
          jobAddressCode: 'MAIN',
          billtoAddressCode: 'MAIN',
          taxScheduleId: 'GST 5%',
          createdDate: '2025-09-15',
          costCodes: MAPPED_COST_CODES,
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
          costCodesProvisioned: MAPPED_COST_CODES.length,
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

// --- #444: creating a customer address from the pickers themselves -------------------------------

/**
 * A customer's addresses as GP reports them either side of a create - `extra` only shows up from the
 * second read on. A picker offers a code only once its own query has returned it, so the call count
 * is what proves the re-read happened rather than the code being pushed into the select blind.
 */
function growingAddressesMock(
  customer: string,
  base: ReturnType<typeof address>[],
  extra: ReturnType<typeof address>,
  counter: { calls: number },
): MockedResponse {
  return {
    request: { query: GET_GP_CUSTOMER_ADDRESSES, variables: { company: COMPANY, customer } },
    maxUsageCount: INFINITE,
    result: () => {
      counter.calls += 1;
      return { data: { gpCustomerAddresses: counter.calls > 1 ? [...base, extra] : base } };
    },
  } as MockedResponse;
}

/** A customer's addresses, counted, so a test can prove that picker's own query was re-read. */
function countedAddressesMock(
  customer: string,
  rows: ReturnType<typeof address>[],
  counter: { calls: number },
): MockedResponse {
  return {
    request: { query: GET_GP_CUSTOMER_ADDRESSES, variables: { company: COMPANY, customer } },
    maxUsageCount: INFINITE,
    result: () => {
      counter.calls += 1;
      return { data: { gpCustomerAddresses: rows } };
    },
  } as MockedResponse;
}

/** The nested dialog, so its Cancel is never confused with the job form's own. */
function addAddressDialog() {
  const dialog = screen.getByLabelText(/^Address code/).closest('[role="dialog"]');
  if (!(dialog instanceof HTMLElement)) throw new Error('the add-address dialog is not open');
  return dialog;
}

/** The three fields GP requires. The code goes in lower-case: the field is what upper-cases it. */
function fillNewAddress({ code, line1, city }: { code: string; line1: string; city: string }) {
  fireEvent.change(screen.getByLabelText(/^Address code/), { target: { value: code } });
  fireEvent.change(screen.getByLabelText(/^Address 1/), { target: { value: line1 } });
  fireEvent.change(screen.getByLabelText(/^City/), { target: { value: city } });
}

test('the add-address row opens the nested dialog without becoming the selected address', async () => {
  renderDialog();
  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());
  await pickCustomer(/Ellis Don/);
  await pickFromSelect(/^Job address/, /MAIN/);

  await pickFromSelect(/^Job address/, /Add new address/);
  expect(await screen.findByLabelText(/^Address code/)).toBeInTheDocument();

  // The row's value is a sentinel, not an address code. Storing it would hand GP a code no customer
  // has, and it would have wiped the selection the user had already made to get here.
  fireEvent.click(within(addAddressDialog()).getByRole('button', { name: /^Cancel$/i }));
  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: /^Job address/ })).toHaveTextContent('MAIN - 1 Main St, Vancouver'),
  );
});

test('the add-address row does not become the selected bill-to address either', async () => {
  // The bill-to picker carries its own copy of the sentinel row, so the job picker's test does not
  // cover it - and a sentinel stored here is a code the proc refuses, on the field the user is least
  // likely to look at again.
  renderDialog();
  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());
  await pickCustomer(/Ellis Don/);
  await pickFromSelect(/^Bill-to address/, /MAIN/);

  await pickFromSelect(/^Bill-to address/, /Add new address/);
  expect(await screen.findByLabelText(/^Address code/)).toBeInTheDocument();

  fireEvent.click(within(addAddressDialog()).getByRole('button', { name: /^Cancel$/i }));
  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: /^Bill-to address/ })).toHaveTextContent(
      'MAIN - 1 Main St, Vancouver',
    ),
  );
});

test('an address added from the job picker is created under the job customer and selected', async () => {
  const ell100 = { calls: 0 };
  // The mock matches on exact variables, so this object IS the assertion on the payload: the customer
  // is the one the picker is bound to, the code is upper-cased, and the four fields left blank travel
  // as null rather than as empty strings GP would store over its own defaults.
  const created: MockedResponse = {
    request: {
      query: CREATE_GP_CUSTOMER_ADDRESS,
      variables: {
        input: {
          customerNumber: 'ELL100',
          addressCode: 'SITE3',
          address1: '77 New Rd',
          address2: null,
          city: 'Surrey',
          state: null,
          zipCode: null,
          country: null,
        },
      },
    },
    result: {
      data: {
        createGpCustomerAddress: {
          addressCode: 'SITE3',
          address1: '77 New Rd',
          city: 'Surrey',
          state: 'BC',
          __typename: 'GpCustomerAddress',
        },
      },
    },
  };

  render(
    <MockedProvider
      mocks={[
        relayStatusMock(true),
        ...readMocks.filter((m) => m !== addressesReadMock),
        growingAddressesMock(
          'ELL100',
          [address('MAIN', '1 Main St', 'Vancouver'), address('SITE2', '9 Site Rd', 'Burnaby')],
          address('SITE3', '77 New Rd', 'Surrey'),
          ell100,
        ),
        projectsMock,
        created,
      ]}
    >
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());
  await pickCustomer(/Ellis Don/);
  await waitFor(() => expect(ell100.calls).toBe(1));

  await pickFromSelect(/^Job address/, /Add new address/);
  fillNewAddress({ code: 'site3', line1: '77 New Rd', city: 'Surrey' });
  fireEvent.click(within(addAddressDialog()).getByRole('button', { name: /^Add address$/i }));

  await waitFor(() => expect(ell100.calls).toBe(2));
  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: /^Job address/ })).toHaveTextContent('SITE3 - 77 New Rd, Surrey'),
  );
  // and the job form is back, with everything filled in so far still there
  expect(screen.queryByLabelText(/^Address code/)).not.toBeInTheDocument();
});

test('a created address is selectable even when the re-read of GP fails', async () => {
  // The cache write, not the re-read, is what puts the option in the picker. While the selection was
  // chained onto the refetch, a relay that dropped in the window right after taCreateCustomerAddress
  // committed left the user with an address GP holds and a required field that would not take it.
  let calls = 0;
  const flakyAddresses: MockedResponse = {
    request: { query: GET_GP_CUSTOMER_ADDRESSES, variables: { company: COMPANY, customer: 'ELL100' } },
    maxUsageCount: INFINITE,
    result: () => {
      calls += 1;
      return calls > 1
        ? { errors: [new GraphQLError('no relay is currently connected')] }
        : { data: { gpCustomerAddresses: [address('MAIN', '1 Main St', 'Vancouver')] } };
    },
  } as MockedResponse;

  const created: MockedResponse = {
    request: {
      query: CREATE_GP_CUSTOMER_ADDRESS,
      variables: {
        input: {
          customerNumber: 'ELL100',
          addressCode: 'SITE3',
          address1: '77 New Rd',
          address2: null,
          city: 'Surrey',
          state: null,
          zipCode: null,
          country: null,
        },
      },
    },
    result: {
      data: {
        createGpCustomerAddress: {
          addressCode: 'SITE3',
          address1: '77 New Rd',
          city: 'Surrey',
          state: 'BC',
          __typename: 'GpCustomerAddress',
        },
      },
    },
  };

  render(
    <MockedProvider
      mocks={[
        relayStatusMock(true),
        ...readMocks.filter((m) => m !== addressesReadMock),
        flakyAddresses,
        projectsMock,
        created,
      ]}
    >
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());
  await pickCustomer(/Ellis Don/);
  await waitFor(() => expect(calls).toBe(1));

  await pickFromSelect(/^Job address/, /Add new address/);
  fillNewAddress({ code: 'site3', line1: '77 New Rd', city: 'Surrey' });
  fireEvent.click(within(addAddressDialog()).getByRole('button', { name: /^Add address$/i }));

  await waitFor(() => expect(calls).toBe(2));
  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: /^Job address/ })).toHaveTextContent('SITE3 - 77 New Rd, Surrey'),
  );
});

test('an address added from the bill-to picker is created under the bill-to customer', async () => {
  // The whole point of the scoping: the bill-to picker is showing SCO100's addresses, so a code added
  // from it has to be filed against SCO100. Against ELL100 it would not even appear in the list it
  // was added from, and the job proc would refuse it.
  const sco100 = { calls: 0 };
  const created: MockedResponse = {
    request: {
      query: CREATE_GP_CUSTOMER_ADDRESS,
      variables: {
        input: {
          customerNumber: 'SCO100',
          addressCode: 'SITE9',
          address1: '3 Depot Ave',
          address2: null,
          city: 'Langley',
          state: null,
          zipCode: null,
          country: null,
        },
      },
    },
    result: {
      data: {
        createGpCustomerAddress: {
          addressCode: 'SITE9',
          address1: '3 Depot Ave',
          city: 'Langley',
          state: 'BC',
          __typename: 'GpCustomerAddress',
        },
      },
    },
  };

  renderDialog([
    growingAddressesMock('SCO100', [address('HQ', '5 Bay St', 'Toronto')], address('SITE9', '3 Depot Ave', 'Langley'), sco100),
    created,
  ]);

  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());
  await pickCustomer(/Ellis Don/);
  fireEvent.click(screen.getByRole('button', { name: /Show optional fields/i }));
  await pickBillCustomer(/Scott Construction/);
  await waitFor(() => expect(sco100.calls).toBe(1));

  await pickFromSelect(/^Bill-to address/, /Add new address/);
  fillNewAddress({ code: 'site9', line1: '3 Depot Ave', city: 'Langley' });
  fireEvent.click(within(addAddressDialog()).getByRole('button', { name: /^Add address$/i }));

  // the bill-to customer's own query is the one re-read, and the new code lands in that picker
  await waitFor(() => expect(sco100.calls).toBe(2));
  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: /^Bill-to address/ })).toHaveTextContent('SITE9 - 3 Depot Ave, Langley'),
  );
});

test('a duplicate address code shows the relay detail, stays open, and re-reads the picker', async () => {
  // The shape the backend actually emits: the relay refusal arrives as a RelayCallError, which
  // errors.py validation_error_from_relay turns into a ValidationError carrying `.detail`, so
  // extensions.code is VALIDATION_ERROR and the relay's own body rides along under
  // extensions.relayError. A recovery keyed on extensions.code === 'address_code_already_exists'
  // would match nothing in production, which is why the mock has to be this shape and not that one.
  const message = "customer 'ELL100' already has address code 'MAIN' in GP company TUBC (RM00102)";
  const ell100 = { calls: 0 };
  const duplicate: MockedResponse = {
    request: {
      query: CREATE_GP_CUSTOMER_ADDRESS,
      variables: {
        input: {
          customerNumber: 'ELL100',
          addressCode: 'MAIN',
          address1: '77 New Rd',
          address2: null,
          city: 'Surrey',
          state: null,
          zipCode: null,
          country: null,
        },
      },
    },
    result: {
      errors: [
        new GraphQLError(message, {
          extensions: {
            code: 'VALIDATION_ERROR',
            relayError: { error: 'address_code_already_exists', message, context: {} },
          },
        }),
      ],
    },
  };

  render(
    <MockedProvider
      mocks={[
        relayStatusMock(true),
        ...readMocks.filter((m) => m !== addressesReadMock),
        countedAddressesMock('ELL100', [address('MAIN', '1 Main St', 'Vancouver')], ell100),
        projectsMock,
        duplicate,
      ]}
    >
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());
  await pickCustomer(/Ellis Don/);
  await waitFor(() => expect(ell100.calls).toBe(1));

  await pickFromSelect(/^Job address/, /Add new address/);
  fillNewAddress({ code: 'main', line1: '77 New Rd', city: 'Surrey' });
  fireEvent.click(within(addAddressDialog()).getByRole('button', { name: /^Add address$/i }));

  expect(await screen.findByText(/already has address code/)).toBeInTheDocument();
  // the relay's own key, rendered off extensions.relayError - the detail table is what gets
  // screenshotted, so it is the thing worth asserting rather than the message text alone
  const dialog = within(addAddressDialog());
  expect(dialog.getByText('Relay')).toBeInTheDocument();
  expect(dialog.getByText('address_code_already_exists')).toBeInTheDocument();

  // 'Already exists' is the answer to a retry whose first attempt committed and lost its reply, so the
  // picker's own list is re-read - otherwise the user is shown an error for an address GP holds and
  // still cannot select it without reloading the page.
  await waitFor(() => expect(ell100.calls).toBe(2));

  // Closing here would throw away a whole address over one wrong code, so it stays open and typed in.
  expect(screen.getByLabelText(/^Address code/)).toHaveValue('MAIN');
  expect(screen.getByLabelText(/^Address 1/)).toHaveValue('77 New Rd');
});

// --- #448: provisioning the new job's cost codes -------------------------------------------------

/**
 * The create, with whatever cost codes the form settled on. Everything else is the fillRequired run.
 *
 * `costCodesProvisioned` defaults to agreeing with the request, which is the healthy relay. The whole
 * point of the field is that it need not: a relay older than #448 drops the codes and answers zero.
 */
function createJobMock(
  costCodes: { costCode: string; costElement: number }[],
  { created = true, costCodesProvisioned = costCodes.length } = {},
): MockedResponse {
  return {
    request: {
      query: CREATE_GP_JOB,
      variables: {
        input: {
          company: COMPANY,
          jobNumber: 'NEXUS-380-T1',
          jobName: 'Test job',
          division: 'VANCOUVER',
          customerNumber: 'ELL100',
          jobAddressCode: 'MAIN',
          billtoAddressCode: 'MAIN',
          taxScheduleId: 'GST 5%',
          createdDate: '2025-09-15',
          costCodes,
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
          created,
          costCodesProvisioned,
          project: { id: 'project-1', __typename: 'Project' },
          __typename: 'CreateGpJobResult',
        },
      },
    },
  };
}

test('the division cost-code master arrives with the mapped codes checked and the unmapped one unusable', async () => {
  // Accounting provisions a job wholesale, so select-all is the default. The unmapped code is the
  // exception, and not because it is unwanted: the division has no GL account for its cost element, so
  // putting it on the job is what the GP-setup check quarantines the project for.
  renderDialog();
  await waitFor(() => expect(screen.getByLabelText(/^Job number/)).toBeEnabled());

  // whether a code has an account is a fact about the division, so there is nothing to show yet
  expect(screen.getByText(/Pick a division first/)).toBeInTheDocument();

  await pickFromSelect(/^Division/, /VANCOUVER/);

  await waitFor(() => expect(costCodeBox(/310-000-3/)).toBeChecked());
  expect(costCodeBox(/520-000-2/)).toBeChecked();
  expect(costCodeBox(/210-200-2/)).toBeDisabled();
  expect(costCodeBox(/210-200-2/)).not.toBeChecked();
  expect(screen.getByText(/No GP account for cost element 2 in this division/)).toBeInTheDocument();
  // Mapped rows are the denominator: the unmapped one can never be ticked, so counting it would make
  // an untouched form - which has everything it is allowed to have - read as partly deselected.
  expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();
});

test('a cost code unchecked before the submit is left out of the create', async () => {
  // The mock matches on exact variables, so this IS the assertion on the payload: the code that was
  // unchecked is gone, and the one that stayed travels as GP's own pair rather than the display key.
  const success = createJobMock([{ costCode: '520-000', costElement: 2 }]);

  renderDialog([success]);
  await fillRequired();

  fireEvent.click(costCodeBox(/310-000-3/));
  await waitFor(() => expect(costCodeBox(/310-000-3/)).not.toBeChecked());
  expect(screen.getByText('1 of 2 selected')).toBeInTheDocument();

  await waitFor(() => expect(createButton()).toBeEnabled());
  fireEvent.click(createButton());

  expect(await screen.findByText(/Job NEXUS-380-T1 created in GP/)).toBeInTheDocument();
});

test('a job with no cost codes can still be created, with a warning that it cannot buy', async () => {
  // An unprovisioned job is a legal create - it is what GP does on its own - so the button stays
  // usable. What it must not be is silent: nothing else in Nexus explains an empty register-PO
  // cost-code dropdown until purchasing hits it.
  const success = createJobMock([]);

  renderDialog([success]);
  await fillRequired();

  fireEvent.click(costCodeBox(/310-000-3/));
  fireEvent.click(costCodeBox(/520-000-2/));
  await waitFor(() => expect(screen.getByText('0 of 2 selected')).toBeInTheDocument());

  expect(screen.getByText(/blocked from GP purchasing until they are added in GP/)).toBeInTheDocument();
  expect(createButton()).toBeEnabled();

  fireEvent.click(createButton());

  expect(await screen.findByText(/Job NEXUS-380-T1 created in GP/)).toBeInTheDocument();
});

test('the create is held while the cost-code master is still in flight, so an empty selection cannot be sent', async () => {
  // The selection is DERIVED from the master, so while that read is in flight there is nothing to
  // derive and the form would send costCodes: [] - creating exactly the bare, quarantined job this
  // feature exists to prevent, and reporting it as an ordinary success.
  //
  // The read is pinned open rather than merely slowed: a delay is a race against however long the
  // other reads take under a loaded test run, and this has to be the read that holds the button. The
  // other direction - it enables once the master lands - is what every fillRequired() test proves.
  const masterInFlight: MockedResponse = { ...costCodeMasterReadMock, delay: INFINITE };

  render(
    <MockedProvider
      mocks={[
        relayStatusMock(true),
        ...readMocks.filter((m) => m !== costCodeMasterReadMock),
        masterInFlight,
        projectsMock,
        // servable on purpose: a button that stopped holding would then reach a toast the assertion
        // below catches, rather than dying on an unmatched operation that looks the same as passing
        createJobMock(MAPPED_COST_CODES),
      ]}
    >
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  // every other required field is filled, so the disabled button is down to this read and nothing else
  await fillRequiredFields();

  expect(screen.getByText(/Reading the cost-code master from GP/)).toBeInTheDocument();
  expect(createButton()).toBeDisabled();
  // and a click in that window does nothing at all - no create, no toast
  fireEvent.click(createButton());
  await waitFor(() => expect(screen.queryByText(/created in GP/)).not.toBeInTheDocument());
});

test('a relay too old for the cost-code master says to update it rather than showing the raw op error', async () => {
  // Deliberately NOT the hard readsUnsupported gate: a relay without list_cost_code_master still
  // creates jobs, and an unprovisioned job is a legal create. Only the wording changes - "does not
  // support list_cost_code_master" tells the user nothing they can act on.
  const unsupportedMaster: MockedResponse = {
    request: { query: GET_GP_COST_CODE_MASTER, variables: { company: COMPANY, division: 'VANCOUVER' } },
    maxUsageCount: INFINITE,
    result: {
      errors: [
        new GraphQLError('The connected relay does not support list_cost_code_master', {
          extensions: { code: 'RELAY_OP_UNSUPPORTED' },
        }),
      ],
    },
  };

  render(
    <MockedProvider
      mocks={[
        relayStatusMock(true),
        ...readMocks.filter((m) => m !== costCodeMasterReadMock),
        unsupportedMaster,
        projectsMock,
      ]}
    >
      <ToastProvider>
        <CreateGpJobDialog open onClose={() => {}} />
      </ToastProvider>
    </MockedProvider>,
  );

  await fillRequiredFields();

  expect(await screen.findByText(/relay is too old to offer cost codes/i)).toBeInTheDocument();
  expect(screen.queryByText(/does not support list_cost_code_master/)).not.toBeInTheDocument();
  // the job itself is still creatable, so neither the hard banner nor a dead button appears
  expect(screen.queryByText(/relay is too old to create jobs/i)).not.toBeInTheDocument();
  await waitFor(() => expect(createButton()).toBeEnabled());
});

test('a create whose cost codes did not land warns instead of reporting a clean success', async () => {
  // A relay older than #448 ignores the unknown costCodes key without a word and answers a perfectly
  // ordinary success, having made the bare job the GP-setup check quarantines. GP's own read-back
  // count is the only evidence of it, so a zero against a non-empty selection has to be said out loud.
  const droppedByAnOldRelay = createJobMock(MAPPED_COST_CODES, { costCodesProvisioned: 0 });

  renderDialog([droppedByAnOldRelay]);
  await fillRequired();
  await waitFor(() => expect(createButton()).toBeEnabled());
  fireEvent.click(createButton());

  expect(await screen.findByText(/cost codes were not provisioned/i)).toBeInTheDocument();
  expect(screen.queryByText('Job NEXUS-380-T1 created in GP.')).not.toBeInTheDocument();
});

test('an adopted job says the cost codes picked here were not applied to it', async () => {
  // The adopt path leaves the job exactly as GP has it - the selection is not applied to somebody
  // else's setup. Saying only "already existed" would let the user believe their codes went on it.
  const adopted = createJobMock(MAPPED_COST_CODES, { created: false, costCodesProvisioned: 0 });

  renderDialog([adopted]);
  await fillRequired();
  await waitFor(() => expect(createButton()).toBeEnabled());
  fireEvent.click(createButton());

  expect(await screen.findByText(/were not applied to it/i)).toBeInTheDocument();
});
