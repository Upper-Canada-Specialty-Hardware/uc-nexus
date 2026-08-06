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
import { GET_SHIPPING_COVERAGE, GET_SHIPPING_OUT_REQUESTS } from '../../../graphql/shipping';
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

function coverageLine(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShippingCoverageLine',
    hardwareCategory: 'Hinges',
    productCode: 'HNG-100',
    classification: 'SHOP_HARDWARE',
    owedQuantity: 3,
    installedQuantity: 3,
    spokenForQuantity: 0,
    suggestedQuantity: 0,
    onOrderQuantity: 0,
    ...overrides,
  };
}

// What the two selected openings still owe (#451), matching the fixtures above: O-1's hinges went
// onto its two leaves and are owed nothing further, O-2's lock is site hardware still to send.
const shippingCoverageMock: MockedResponse = {
  request: {
    query: GET_SHIPPING_COVERAGE,
    variables: { projectId: 'proj-1', openingNumbers: ['O-1', 'O-2'] },
  },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      shippingCoverage: [
        {
          __typename: 'ShippingCoverageLeaf',
          openingNumber: 'O-1',
          leaf: 1,
          status: 'IN_INVENTORY',
          openingItemId: 'oi-leaf-1',
          claimedByRequestNumber: null,
          lines: [coverageLine()],
        },
        {
          __typename: 'ShippingCoverageLeaf',
          openingNumber: 'O-1',
          leaf: 2,
          status: 'IN_INVENTORY',
          openingItemId: 'oi-leaf-2',
          claimedByRequestNumber: null,
          lines: [coverageLine()],
        },
        {
          __typename: 'ShippingCoverageLeaf',
          openingNumber: 'O-2',
          leaf: null,
          status: 'NOT_ASSEMBLED',
          openingItemId: null,
          claimedByRequestNumber: null,
          lines: [
            coverageLine({
              hardwareCategory: 'Locks',
              productCode: 'LCK-200',
              classification: 'SITE_HARDWARE',
              owedQuantity: 1,
              installedQuantity: 0,
              suggestedQuantity: 1,
            }),
          ],
        },
      ],
    },
  },
};

// ---- Harness ----

function renderWizard(
  {
    project = firstImportProject,
    mocks = [],
    initialPurpose,
    autoStartFromLatest,
  }: {
    project?: Project;
    mocks?: MockedResponse[];
    initialPurpose?: 'po' | 'assembly' | 'shipping';
    autoStartFromLatest?: boolean;
  } = {},
) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter>
        <WizardProvider>
          <ToastProvider>
            <ImportWizard
              open
              project={project}
              onClose={onClose}
              initialPurpose={initialPurpose}
              autoStartFromLatest={autoStartFromLatest}
            />
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

  // #492: the assembly flow used to carry a Classification step. It asked the user to re-answer a
  // question the persisted schedule already holds, and a different answer than the original import
  // is the drift. Only the PO purpose classifies now.
  it('assembly purpose (re-import) inserts only the Shop Assembly step', async () => {
    renderWizard({ project: reimportProject, mocks: reimportMocks });
    await flushApollo();
    clickNext();

    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i }));

    expect(stepLabels()).toEqual([...BASE_STEPS, 'Shop Assembly', 'Finalize']);
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
      mocks: [
        ...reimportBaseMocks,
        shippingReconcileMock,
        shippingOpeningItemsMock,
        shippingCoverageMock,
        ...claimMocks(),
      ],
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
    await flushApollo();

    expect(screen.getByRole('heading', { name: 'Shipping Pull Requests' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Add Shipping PR/i }));
    await flushApollo();

    // One row per assembled leaf, and the SHIP_READY unit is not offered.
    expect(screen.getByText('Opening O-1 - Leaf 1')).toBeInTheDocument();
    expect(screen.getByText('Opening O-1 - Leaf 2')).toBeInTheDocument();
    expect(screen.getAllByText(/Opening O-1 - Leaf/)).toHaveLength(2);

    // The hinges live on those leaves now, so the coverage owes nothing loose for them; the lock is
    // site hardware that never went near the bench, so it is still owed and still offered.
    expect(screen.getByText('O-2 | LCK-200 | Locks')).toBeInTheDocument();
    expect(screen.queryByText(/^O-1 \| HNG-100/)).not.toBeInTheDocument();

    // Ticking a leaf records a selection on the draft.
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);
    expect(screen.getByText('1 door leaf/leaves')).toBeInTheDocument();
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

// A reconcile that fails takes the PO purpose's Next button with it: the button is gated on the
// auto-selected gap rows, and there are none when the query returned nothing. Before this the error
// was console-only and the step rendered its ordinary "nothing found" notice, so the wizard looked
// like it had simply decided there was nothing to do.
describe('ImportWizard reconciliation failure', () => {
  const RECONCILE_VARIABLES = {
    projectId: 'proj-1',
    items: [
      { openingNumber: 'O-1', hardwareCategory: 'Hinges', productCode: 'HNG-100', quantityNeeded: 3 },
      { openingNumber: 'O-2', hardwareCategory: 'Locks', productCode: 'LCK-200', quantityNeeded: 1 },
    ],
  };

  const failingReconcileMock: MockedResponse = {
    request: { query: RECONCILE_SCHEDULE, variables: RECONCILE_VARIABLES },
    error: new Error('stack depth limit exceeded'),
  };

  // O-1's hinges come back split across two buckets, which is what the server does when part of a
  // combo is already on order. Both rows carry the same (opening, product, category) key, so this
  // also pins that the aggregation still counts that key once.
  const succeedingReconcileMock: MockedResponse = {
    request: { query: RECONCILE_SCHEDULE, variables: RECONCILE_VARIABLES },
    result: {
      data: {
        reconcileSchedule: [
          {
            __typename: 'ReconciliationResult',
            openingNumber: 'O-1',
            hardwareCategory: 'Hinges',
            productCode: 'HNG-100',
            quantity: 2,
            status: 'NOT_COVERED',
          },
          {
            __typename: 'ReconciliationResult',
            openingNumber: 'O-1',
            hardwareCategory: 'Hinges',
            productCode: 'HNG-100',
            quantity: 1,
            status: 'ORDERED',
          },
          {
            __typename: 'ReconciliationResult',
            openingNumber: 'O-2',
            hardwareCategory: 'Locks',
            productCode: 'LCK-200',
            quantity: 1,
            status: 'NOT_COVERED',
          },
        ],
      },
    },
  };

  async function walkToReconciliation(mocks: MockedResponse[]) {
    renderWizard({ project: reimportProject, mocks: [...reimportBaseMocks, ...mocks] });
    await flushApollo();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();
    await flushApollo();
  }

  it('says the reconcile failed instead of reporting nothing found', async () => {
    await walkToReconciliation([failingReconcileMock]);

    expect(screen.getByRole('heading', { name: 'Reconciliation' })).toBeInTheDocument();
    expect(screen.getByText(/stack depth limit exceeded/)).toBeInTheDocument();
    expect(screen.queryByText('No existing records found for selected items.')).not.toBeInTheDocument();
    expect(nextButton()).toBeDisabled();
  });

  it('recovers in place when the retry succeeds', async () => {
    await walkToReconciliation([failingReconcileMock, succeedingReconcileMock]);

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await flushApollo();

    expect(screen.queryByText(/stack depth limit exceeded/)).not.toBeInTheDocument();
    // Two products, each seen once despite O-1's two status rows, and both pre-selected off their
    // remaining gap.
    expect(screen.getByText('2 of 2 product(s) selected')).toBeInTheDocument();
    expect(nextButton()).toBeEnabled();

    clickNext();
    expect(screen.getByRole('heading', { name: 'Classification' })).toBeInTheDocument();
  });
});

// The keep-or-ship decision's "Ship out now" lands here: the project is chosen, the purpose is
// shipping, and the schedule the hardware was bought against is already imported - so the two steps
// in front of the openings are answers the user has already given somewhere else.
describe('ImportWizard deep link', () => {
  // Enough of a persisted schedule for the hydrate to be legal: hardwareItems non-empty is what
  // makes `canStartFromLatest` true, and the project block is what the mapper reads first.
  const scheduleWithItems: MockedResponse = {
    request: { query: GET_PROJECT_HARDWARE_SCHEDULE, variables: { projectId: 'proj-1' } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: {
      data: {
        projectHardwareSchedule: {
          project: {
            projectId: 'P-100',
            description: 'Test Project',
            jobSiteName: null,
            address: null,
            city: null,
            state: null,
            zip: null,
            contractor: null,
            projectManager: null,
            application: null,
            submittalJobNo: null,
            submittalAssignmentCount: null,
            estimatorCode: null,
            titanUserId: null,
          },
          openings: [],
          hardwareItems: [
            {
              openingNumber: 'O-1',
              productCode: 'HNG-100',
              materialId: 'M-1',
              leaf: null,
              hardwareCategory: 'Hinges',
              itemQuantity: 3,
              unitCost: 10,
              unitPrice: null,
              listPrice: null,
              vendorDiscount: null,
              markupPct: null,
              vendorNo: 'VEND-A',
              manufacturer: null,
              phaseCode: null,
              itemCategoryCode: null,
              productGroupCode: null,
              submittalId: null,
              state: 'AVAILABLE',
            },
          ],
        },
      },
    },
  };

  it('preselects the shipping purpose on a re-import project', async () => {
    renderWizard({
      project: reimportProject,
      mocks: [...reimportMocks],
      initialPurpose: 'shipping',
    });
    await flushApollo();
    clickNext();

    expect(screen.getByRole('radio', { name: /Pull Request for Shipping Out/i })).toBeChecked();
  });

  it('leaves the purpose unset on a project with no schedule, rather than checking a disabled option', async () => {
    // Shipping needs an existing schedule. Silently checking it on a first import would land the
    // user on a radio they cannot use with nothing saying why.
    renderWizard({ project: firstImportProject, initialPurpose: 'shipping' });
    clickNext();

    expect(screen.getByRole('radio', { name: /Pull Request for Shipping Out/i })).not.toBeChecked();
    expect(nextButton()).toBeDisabled();
  });

  it('starts from the persisted schedule instead of asking for a file', async () => {
    const hydrate = vi.fn();
    mockedUseParser.mockReturnValue(
      makeParser({ state: 'idle', parseResult: null, hydrate, progress: { percent: 0, phase: '' } }),
    );
    renderWizard({
      project: reimportProject,
      mocks: [availabilityMock, scheduleWithItems],
      initialPurpose: 'shipping',
      autoStartFromLatest: true,
    });
    await flushApollo();

    expect(hydrate).toHaveBeenCalledTimes(1);
  });

  it('falls back to the upload step when the project has no persisted schedule', async () => {
    const hydrate = vi.fn();
    mockedUseParser.mockReturnValue(
      makeParser({ state: 'idle', parseResult: null, hydrate, progress: { percent: 0, phase: '' } }),
    );
    renderWizard({
      project: reimportProject,
      mocks: reimportMocks, // projectHardwareSchedule: null
      initialPurpose: 'shipping',
      autoStartFromLatest: true,
    });
    await flushApollo();

    expect(hydrate).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'Hardware Schedule' })).toBeInTheDocument();
  });
});
