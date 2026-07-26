import { render, screen, fireEvent, act } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { WizardProvider } from '../../../contexts/WizardContext';
import { ToastProvider } from '../../../components/Toast';
import ImportWizard from '../ImportWizard';
import {
  GET_PROJECT_EXCLUDED_ITEMS,
  GET_PROJECT_HARDWARE_SCHEDULE,
  RECONCILE_SCHEDULE,
} from '../../../graphql/import';
import {
  GET_OPENING_ITEMS,
  GET_PROJECT_INVENTORY_AVAILABILITY,
  GET_PULL_REQUESTS,
} from '../../../graphql/warehouse';
import { GET_SHIPPING_OUT_REQUESTS } from '../../../graphql/shipping';
import {
  useHardwareScheduleParser,
  type UseHardwareScheduleParserReturn,
} from '../../../hooks/useHardwareScheduleParser';
import type {
  ParseResult,
  ParsedHardwareItem,
  ParsedOpening,
} from '../../../types/hardwareSchedule';
import type { Project } from '../../../types/project';

// The real hook spawns a web worker, which jsdom lacks. Replace it with a
// controllable fake mirroring UseHardwareScheduleParserReturn.
vi.mock('../../../hooks/useHardwareScheduleParser', () => ({
  useHardwareScheduleParser: vi.fn(),
}));

const mockedUseParser = vi.mocked(useHardwareScheduleParser);

// Steps that mount MUI X DataGrid render slowly under jsdom; the default 5s
// per-test budget is not enough for the multi-step walks.
vi.setConfig({ testTimeout: 60_000 });

// MUI X DataGrid observes container size; jsdom has no ResizeObserver.
beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    // @ts-expect-error minimal stub for jsdom
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

// ---- Fixtures ----

function makeOpening(openingNumber: string): ParsedOpening {
  return {
    opening_number: openingNumber,
    building: null,
    floor: null,
    location: null,
    location_to: null,
    location_from: null,
    hand: null,
    width: null,
    length: null,
    door_thickness: null,
    jamb_thickness: null,
    door_type: null,
    frame_type: null,
    interior_exterior: null,
    keying: null,
    heading_no: null,
    single_pair: null,
    assignment_multiplier: null,
  };
}

function makeHardwareItem(overrides: Partial<ParsedHardwareItem>): ParsedHardwareItem {
  return {
    opening_number: 'O-1',
    product_code: 'HNG-100',
    material_id: 'M-1',
    hardware_category: 'Hinges',
    item_quantity: 3,
    unit_cost: 10,
    unit_price: null,
    list_price: null,
    vendor_discount: null,
    markup_pct: null,
    vendor_no: 'VEND-A',
    manufacturer: null,
    phase_code: null,
    item_category_code: null,
    product_group_code: null,
    submittal_id: null,
    ...overrides,
  };
}

const parseResult: ParseResult = {
  project: {
    project_id: 'P-100',
    description: 'Test Project',
    job_site_name: null,
    address: null,
    city: null,
    state: null,
    zip: null,
    contractor: null,
    project_manager: null,
    application: null,
    submittal_job_no: null,
    submittal_assignment_count: null,
    estimator_code: null,
    titan_user_id: null,
  },
  openings: [makeOpening('O-1'), makeOpening('O-2')],
  hardwareItems: [
    makeHardwareItem({}),
    makeHardwareItem({
      opening_number: 'O-2',
      product_code: 'LCK-200',
      material_id: 'M-2',
      hardware_category: 'Locks',
      item_quantity: 1,
      unit_cost: 25,
      vendor_no: 'VEND-B',
    }),
  ],
  validationSummary: {
    totalOpenings: 2,
    totalHardwareItems: 2,
    skippedRows: [],
    warnings: [],
  },
};

function makeParser(
  overrides: Partial<UseHardwareScheduleParserReturn> = {},
): UseHardwareScheduleParserReturn {
  return {
    state: 'done',
    progress: { percent: 100, phase: 'Complete' },
    parseResult,
    error: null,
    isLoading: false,
    parseFile: vi.fn(),
    hydrate: vi.fn(),
    setLoading: vi.fn(),
    setError: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  };
}

const firstImportProject: Project = {
  id: 'proj-1',
  projectId: 'P-100',
  description: 'Test Project',
  client: null,
  jobSiteName: null,
  openingCount: 0,
};

const reimportProject: Project = { ...firstImportProject, openingCount: 5 };

// A re-import project eagerly fetches the persisted schedule (null = nothing
// persisted, so the upload step stays a plain dropzone) and, once parsed items
// exist, the project's excluded-items list.
// Both request purposes read reservation-aware availability (#342) so the wizard can block an
// over-selection before submission. Generous by default: these tests are about step shape, and a
// shortfall would disable Next for a reason none of them is asserting.
const availabilityMock: MockedResponse = {
  request: {
    query: GET_PROJECT_INVENTORY_AVAILABILITY,
    variables: { projectId: 'proj-1' },
  },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      projectInventoryAvailability: [
        {
          hardwareCategory: 'Hinges',
          productCode: 'HNG-100',
          onHandQuantity: 99,
          deficientQuantity: 0,
          reservedQuantity: 0,
          availableQuantity: 99,
        },
        {
          hardwareCategory: 'Locks',
          productCode: 'LCK-200',
          onHandQuantity: 99,
          deficientQuantity: 0,
          reservedQuantity: 0,
          availableQuantity: 99,
        },
      ],
    },
  },
};

const reimportBaseMocks: MockedResponse[] = [
  availabilityMock,
  {
    request: {
      query: GET_PROJECT_HARDWARE_SCHEDULE,
      variables: { projectId: 'proj-1' },
    },
    result: { data: { projectHardwareSchedule: null } },
  },
  {
    request: {
      query: GET_PROJECT_EXCLUDED_ITEMS,
      variables: { projectId: 'proj-1' },
    },
    result: { data: { projectExcludedItems: [] } },
  },
];

// The shipping purpose reads the project's assembled units (#335). Empty by default so the
// step-shape tests don't need to care; the shipping walk below swaps in real ones. MockedProvider
// takes the first matching mock, so this must not be in the list when a populated one is wanted.
const emptyOpeningItemsMock: MockedResponse = {
  request: {
    query: GET_OPENING_ITEMS,
    variables: { projectId: 'proj-1' },
  },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { openingItems: [] } },
};

// The shipping purpose also asks which leaves are already claimed by an open pull or a pending
// request. Nothing claimed by default.
function claimMocks(
  pullRequests: object[] = [],
  shippingOutRequests: object[] = [],
): MockedResponse[] {
  return [
    {
      request: {
        query: GET_PULL_REQUESTS,
        variables: { projectId: 'proj-1', source: 'SHIPPING_OUT' },
      },
      maxUsageCount: Number.POSITIVE_INFINITY,
      result: { data: { pullRequests } },
    },
    {
      request: {
        query: GET_SHIPPING_OUT_REQUESTS,
        variables: { projectId: 'proj-1', status: 'PENDING', reopenableOnly: false },
      },
      maxUsageCount: Number.POSITIVE_INFINITY,
      result: { data: { shippingOutRequests } },
    },
  ];
}

const reimportMocks: MockedResponse[] = [...reimportBaseMocks, emptyOpeningItemsMock, ...claimMocks()];

// --- Shipping-path fixtures (#335) ---

// O-1's hinges were consumed into two assembled door leaves; O-2's lock is still loose stock.
const shippingReconcileMock: MockedResponse = {
  request: {
    query: RECONCILE_SCHEDULE,
    variables: {
      projectId: 'proj-1',
      items: [
        { openingNumber: 'O-1', hardwareCategory: 'Hinges', productCode: 'HNG-100', quantityNeeded: 3 },
        { openingNumber: 'O-2', hardwareCategory: 'Locks', productCode: 'LCK-200', quantityNeeded: 1 },
      ],
    },
  },
  result: {
    data: {
      reconcileSchedule: [
        {
          __typename: 'ReconciliationResult',
          openingNumber: 'O-1',
          hardwareCategory: 'Hinges',
          productCode: 'HNG-100',
          quantity: 3,
          status: 'ASSEMBLED',
        },
        {
          __typename: 'ReconciliationResult',
          openingNumber: 'O-2',
          hardwareCategory: 'Locks',
          productCode: 'LCK-200',
          quantity: 1,
          status: 'RECEIVED',
        },
      ],
    },
  },
};

function makeOpeningItem(id: string, leaf: number | null, state = 'IN_INVENTORY') {
  return {
    __typename: 'OpeningItem',
    id,
    projectId: 'proj-1',
    openingId: 'opening-1',
    openingNumber: 'O-1',
    building: null,
    floor: null,
    location: null,
    leaf,
    leafCount: 2,
    quantity: 1,
    assemblyCompletedAt: '2026-07-01T00:00:00',
    state,
    aisle: null,
    row: null,
    bay: null,
    createdAt: '2026-07-01T00:00:00',
    updatedAt: '2026-07-01T00:00:00',
    installedHardware: [
      {
        __typename: 'OpeningItemHardware',
        id: `${id}-hw`,
        openingItemId: id,
        productCode: 'HNG-100',
        hardwareCategory: 'Hinges',
        quantity: 3,
      },
    ],
  };
}

const shippingOpeningItemsMock: MockedResponse = {
  request: {
    query: GET_OPENING_ITEMS,
    variables: { projectId: 'proj-1' },
  },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      openingItems: [
        makeOpeningItem('oi-leaf-1', 1),
        makeOpeningItem('oi-leaf-2', 2),
        // Already pulled: it waits on the Ship tab, so the wizard must not offer it again.
        makeOpeningItem('oi-leaf-shipready', 1, 'SHIP_READY'),
      ],
    },
  },
};

// ---- Harness ----

function renderWizard(
  { project = firstImportProject, mocks = [] }: { project?: Project; mocks?: MockedResponse[] } = {},
) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter>
        <WizardProvider>
          <ToastProvider>
            <ImportWizard open project={project} onClose={onClose} />
          </ToastProvider>
        </WizardProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
  return { onClose };
}

function stepLabels(): Array<string | null> {
  return Array.from(document.querySelectorAll('.MuiStepLabel-label')).map((el) => el.textContent);
}

function nextButton() {
  return screen.getByRole('button', { name: 'Next' });
}

function clickNext() {
  fireEvent.click(nextButton());
}

function clickBack() {
  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
}

// Let MockedProvider deliver in-flight lazy-query results inside act().
async function flushApollo() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 60));
  });
}

const BASE_STEPS = ['Upload File', 'Purpose', 'Select Openings', 'Reconciliation'];

beforeEach(() => {
  mockedUseParser.mockReset();
  mockedUseParser.mockReturnValue(makeParser());
});

// ---- Tests ----

describe('ImportWizard step transitions', () => {
  it('starts on Upload File and blocks Next until a parse result exists', () => {
    mockedUseParser.mockReturnValue(
      makeParser({ state: 'idle', parseResult: null, progress: { percent: 0, phase: '' } }),
    );
    renderWizard();

    expect(screen.getByRole('heading', { name: 'Hardware Schedule' })).toBeInTheDocument();
    expect(screen.getByText('Drag and drop an XML file here')).toBeInTheDocument();
    expect(stepLabels()).toEqual([...BASE_STEPS, 'Finalize']);
    expect(nextButton()).toBeDisabled();
  });

  it('advances to Purpose once parsed and blocks Next until a purpose is chosen', () => {
    renderWizard();

    expect(screen.getByText('File parsed successfully!')).toBeInTheDocument();
    expect(nextButton()).toBeEnabled();
    clickNext();

    expect(screen.getByRole('heading', { name: 'Select Import Purpose' })).toBeInTheDocument();
    expect(nextButton()).toBeDisabled();

    // first import: pull-request purposes need existing received inventory
    expect(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i })).toBeDisabled();
    expect(screen.getByRole('radio', { name: /Pull Request for Shipping Out/i })).toBeDisabled();

    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    expect(nextButton()).toBeEnabled();
  });

  it('po purpose inserts Classification and Purchase Orders steps before Finalize', () => {
    renderWizard();
    clickNext();

    expect(stepLabels()).toEqual([...BASE_STEPS, 'Finalize']);
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));

    expect(stepLabels()).toEqual([...BASE_STEPS, 'Classification', 'Purchase Orders', 'Finalize']);
  });

  it('assembly purpose (re-import) inserts Classification and Shop Assembly steps', async () => {
    renderWizard({ project: reimportProject, mocks: reimportMocks });
    await flushApollo();
    clickNext();

    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i }));

    expect(stepLabels()).toEqual([...BASE_STEPS, 'Classification', 'Shop Assembly', 'Finalize']);
  });

  it('shipping purpose (re-import) inserts only the Shipping PRs step', async () => {
    renderWizard({ project: reimportProject, mocks: reimportMocks });
    await flushApollo();
    clickNext();

    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shipping Out/i }));

    expect(stepLabels()).toEqual([...BASE_STEPS, 'Shipping PRs', 'Finalize']);
  });

  it('blocks Next on Select Openings until at least one opening is selected', () => {
    renderWizard();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    clickNext();

    expect(screen.getByRole('heading', { name: 'Openings' })).toBeInTheDocument();
    expect(nextButton()).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();
    expect(nextButton()).toBeEnabled();
  });

  it('Back returns to the previous step and keeps the chosen purpose', () => {
    renderWizard();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    clickNext();
    expect(screen.getByRole('heading', { name: 'Openings' })).toBeInTheDocument();

    clickBack();
    expect(screen.getByRole('heading', { name: 'Select Import Purpose' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Create Purchase Orders/i })).toBeChecked();

    clickBack();
    expect(screen.getByRole('heading', { name: 'Hardware Schedule' })).toBeInTheDocument();
    expect(screen.getByText('File parsed successfully!')).toBeInTheDocument();
  });

  // #335: an assembled leaf ships as itself, not as a request for the loose hardware bolted onto it.
  it('offers assembled door leaves per leaf and drops their hardware from the loose list', async () => {
    renderWizard({
      project: reimportProject,
      mocks: [...reimportBaseMocks, shippingReconcileMock, shippingOpeningItemsMock, ...claimMocks()],
    });
    await flushApollo();
    clickNext();

    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shipping Out/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();
    await flushApollo();

    expect(screen.getByRole('heading', { name: 'Reconciliation' })).toBeInTheDocument();
    clickNext();

    expect(screen.getByRole('heading', { name: 'Shipping Pull Requests' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Add Shipping PR/i }));

    // One row per assembled leaf, and the SHIP_READY unit is not offered.
    expect(screen.getByText('Opening O-1 - Leaf 1')).toBeInTheDocument();
    expect(screen.getByText('Opening O-1 - Leaf 2')).toBeInTheDocument();
    expect(screen.getAllByText(/Opening O-1 - Leaf/)).toHaveLength(2);

    // The hinges live on those leaves now, so they are not offered as loose stock; the lock still is.
    expect(screen.queryByText(/Product: HNG-100/)).not.toBeInTheDocument();
    expect(screen.getByText(/Product: LCK-200/)).toBeInTheDocument();

    // Ticking a leaf records a selection on the draft.
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);
    expect(screen.getByText('Select items (1 selected):')).toBeInTheDocument();
    expect(nextButton()).toBeDisabled(); // still needs a PR number

    fireEvent.change(screen.getByRole('textbox', { name: /PR Number/i }), {
      target: { value: 'SHIP-0019' },
    });
    expect(nextButton()).toBeEnabled();
  });

  // A leaf stays IN_INVENTORY until its pull completes, so state alone would re-offer it and one
  // physical leaf would be pulled twice.
  it('hides an assembled leaf that is already on an open shipping pull', async () => {
    renderWizard({
      project: reimportProject,
      mocks: [
        ...reimportBaseMocks,
        shippingReconcileMock,
        shippingOpeningItemsMock,
        ...claimMocks([
          {
            __typename: 'PullRequest',
            id: 'pr-1',
            requestNumber: 'SHIP-EXISTING',
            projectId: 'proj-1',
            source: 'SHIPPING_OUT',
            status: 'IN_PROGRESS',
            requestedBy: 'someone',
            assignedTo: 'someone',
            createdAt: '2026-07-02T00:00:00',
            updatedAt: '2026-07-02T00:00:00',
            approvedAt: null,
            completedAt: null,
            cancelledAt: null,
            items: [
              {
                __typename: 'PullRequestItem',
                id: 'pri-1',
                pullRequestId: 'pr-1',
                itemType: 'OPENING_ITEM',
                openingNumber: 'O-1',
                openingItemId: 'oi-leaf-1',
                leaf: 1,
                hardwareCategory: null,
                productCode: null,
                requestedQuantity: 1,
              },
            ],
          },
        ]),
      ],
    });
    await flushApollo();
    clickNext();

    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shipping Out/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();
    await flushApollo();
    clickNext();

    fireEvent.click(screen.getByRole('button', { name: /Add Shipping PR/i }));

    expect(screen.queryByText('Opening O-1 - Leaf 1')).not.toBeInTheDocument();
    expect(screen.getByText('Opening O-1 - Leaf 2')).toBeInTheDocument();
  });

  it('walks the po path through Reconciliation to Classification and gates on unclassified items', () => {
    renderWizard();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();

    // first import: reconciliation is informational and never blocks
    expect(screen.getByRole('heading', { name: 'Reconciliation' })).toBeInTheDocument();
    expect(screen.getByText(/New project/)).toBeInTheDocument();
    expect(nextButton()).toBeEnabled();
    clickNext();

    expect(screen.getByRole('heading', { name: 'Classification' })).toBeInTheDocument();
    expect(screen.getByText('0 of 2 items classified')).toBeInTheDocument();
    expect(nextButton()).toBeDisabled();
  });
});
