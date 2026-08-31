import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
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
  GET_PROJECT_INVENTORY_AVAILABILITY,
} from '../../../graphql/warehouse';
import { GET_REQUEST_COVERAGE } from '../../../graphql/shipping';
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
  company: 'TUBC',
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

const reimportMocks: MockedResponse[] = [...reimportBaseMocks];

// --- Compose-step fixtures ---

// O-1's hinges were consumed into two assembled door leaves; O-2's lock is still loose stock.
const reconcileMock: MockedResponse = {
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

/** One row of the composer's answer. */
function coverageLine(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'RequestCoverageLine',
    openingNumber: 'O-1',
    hardwareCategory: 'Hinges',
    productCode: 'HNG-100',
    classification: 'SHOP_HARDWARE',
    owedQuantity: 6,
    sentQuantity: 0,
    assembledQuantity: 0,
    shippedQuantity: 0,
    claimedQuantity: 0,
    suggestedQuantity: 6,
    onOrderQuantity: 0,
    ...overrides,
  };
}

// What the two selected openings still have coming, as the Shop Assembly composer sees it: O-1's
// hinges are shop hardware still owed to the bench, O-2's lock is site hardware the bench never
// touches - so only the hinge is offered here (the compose step filters to SHOP).
const requestCoverageMock: MockedResponse = {
  request: {
    query: GET_REQUEST_COVERAGE,
    variables: { projectId: 'proj-1', openingNumbers: ['O-1', 'O-2'] },
  },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      requestCoverage: [
        coverageLine({ openingNumber: 'O-1', suggestedQuantity: 6 }),
        coverageLine({
          openingNumber: 'O-2',
          hardwareCategory: 'Locks',
          productCode: 'LCK-200',
          classification: 'SITE_HARDWARE',
          owedQuantity: 1,
          suggestedQuantity: 1,
        }),
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
    initialSelectionMode,
    autoStartFromLatest,
  }: {
    project?: Project;
    mocks?: MockedResponse[];
    initialPurpose?: 'po' | 'assembly';
    initialSelectionMode?: 'openings' | 'hardware';
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
              initialSelectionMode={initialSelectionMode}
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

// Reconciliation only exists when there is something to reconcile against - a project with persisted
// openings. On a first import it has nothing to compare and is left out of the stepper entirely.
const FIRST_IMPORT_STEPS = ['Upload File', 'Purpose', 'Select Openings'];
const REIMPORT_STEPS = [...FIRST_IMPORT_STEPS, 'Reconciliation'];

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
    expect(stepLabels()).toEqual([...FIRST_IMPORT_STEPS, 'Finalize']);
    expect(nextButton()).toBeDisabled();
  });

  it('advances to Purpose once parsed and blocks Next until a purpose is chosen', () => {
    renderWizard();

    expect(screen.getByText('File parsed successfully!')).toBeInTheDocument();
    expect(nextButton()).toBeEnabled();
    clickNext();

    expect(screen.getByRole('heading', { name: 'Select Import Purpose' })).toBeInTheDocument();
    expect(nextButton()).toBeDisabled();

    // first import: the pull-request purpose needs existing received inventory
    expect(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i })).toBeDisabled();

    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    expect(nextButton()).toBeEnabled();
  });

  it('po purpose inserts Classification and Organize PO Drafts steps before Finalize', () => {
    renderWizard();
    clickNext();

    expect(stepLabels()).toEqual([...FIRST_IMPORT_STEPS, 'Finalize']);
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));

    expect(stepLabels()).toEqual([...FIRST_IMPORT_STEPS, 'Classification', 'Organize PO Drafts', 'Finalize']);
  });

  // #492: the assembly flow used to carry a Classification step. It asked the user to re-answer a
  // question the persisted schedule already holds, and a different answer than the original import
  // is the drift. Only the PO purpose classifies now.
  it('assembly purpose (re-import) inserts only the Shop Assembly step', async () => {
    renderWizard({ project: reimportProject, mocks: reimportMocks });
    await flushApollo();
    clickNext();

    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i }));

    expect(stepLabels()).toEqual([...REIMPORT_STEPS, 'Shop Assembly', 'Finalize']);
  });

  // The composer is the whole of the shop-assembly step now, so what is worth walking is that the
  // offer reaches the screen and that its SHOP filter holds: the shop hardware is offered, the site
  // lock the bench never touches is not.
  it('offers only the shop hardware the selected openings still have coming', async () => {
    renderWizard({
      project: reimportProject,
      mocks: [...reimportBaseMocks, reconcileMock, requestCoverageMock],
    });
    await flushApollo();
    clickNext();

    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();
    await flushApollo();
    clickNext();
    await flushApollo();

    expect(screen.getByRole('heading', { name: 'Shop Assembly' })).toBeInTheDocument();
    // O-1's hinge is shop hardware still owed to the bench; O-2's lock is site hardware, which the
    // shop-assembly composer never offers. Twice: once in the reserve summary, once on the line.
    expect(screen.getAllByText('HNG-100')).toHaveLength(2);
    expect(screen.queryByText('LCK-200')).not.toBeInTheDocument();
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
  it('skips Reconciliation on a first import and lands on Classification', () => {
    renderWizard();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();

    expect(screen.queryByRole('heading', { name: 'Reconciliation' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Classification' })).toBeInTheDocument();
    // Nothing classified yet, so the step opens on the guided walk-through and Next stays gated.
    expect(screen.getByRole('button', { name: 'Start classifying' })).toBeInTheDocument();
    expect(nextButton()).toBeDisabled();
  });

  it('walks the po path through Reconciliation to Classification on a re-import', async () => {
    renderWizard({ project: reimportProject, mocks: reimportMocks });
    await flushApollo();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();
    await flushApollo();

    expect(screen.getByRole('heading', { name: 'Reconciliation' })).toBeInTheDocument();
  });
});

// #565: the hardware pathway is the PO purpose reached by product rather than by door. The Purpose
// step is gone (purpose is locked to po) and Select Openings is replaced by Select Hardware; every
// downstream step is the same as the by-opening PO flow.
describe('ImportWizard hardware mode', () => {
  const HARDWARE_FIRST_IMPORT_STEPS = [
    'Upload File',
    'Select Hardware',
    'Classification',
    'Organize PO Drafts',
    'Finalize',
  ];

  it('hides the Purpose step and swaps Select Openings for Select Hardware', () => {
    renderWizard({ initialSelectionMode: 'hardware' });

    // No Purpose step, no Select Openings; the product picker takes their place. Classification and
    // Classification and Organize PO Drafts still follow because the purpose is po.
    expect(stepLabels()).toEqual(HARDWARE_FIRST_IMPORT_STEPS);
    expect(screen.queryByText('Select Openings')).not.toBeInTheDocument();
  });

  it('keeps Reconciliation on a re-import, still with no Purpose step', async () => {
    renderWizard({
      project: reimportProject,
      mocks: reimportMocks,
      initialSelectionMode: 'hardware',
    });
    await flushApollo();

    expect(stepLabels()).toEqual([
      'Upload File',
      'Select Hardware',
      'Reconciliation',
      'Classification',
      'Organize PO Drafts',
      'Finalize',
    ]);
  });

  it('blocks Next on Select Hardware until at least one product is picked', () => {
    renderWizard({ initialSelectionMode: 'hardware' });

    // Parsed on the upload step, so Next is live; stepping forward lands on the product picker.
    clickNext();

    expect(screen.getByRole('heading', { name: 'Hardware' })).toBeInTheDocument();
    // Two products in the fixture (HNG-100 hinges, LCK-200 locks), one row each.
    expect(screen.getByText('0 of 2 selected')).toBeInTheDocument();
    expect(nextButton()).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();
    expect(nextButton()).toBeEnabled();
  });

  it('carries the product selection through to Classification', () => {
    renderWizard({ initialSelectionMode: 'hardware' });
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();

    // No Reconciliation on a first import, so the product pick lands straight on Classification, and
    // both selected products carry through - the guided walk-through counts two to classify.
    expect(screen.getByRole('heading', { name: 'Classification' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start classifying' }));
    expect(screen.getByText('0 of 2 fully classified')).toBeInTheDocument();
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

    // #567: HNG-100 would over-order (needs 3, 1 already ORDERED, selecting carries the opening's
    // full demand of 3). That no longer blocks - Next stays live and the step warns inline; the
    // per-product detail moves to the confirm modal shown at Next.
    expect(nextButton()).toBeEnabled();
    expect(screen.getByText(/would exceed the project need/i)).toBeInTheDocument();
  });
});

// #567: over-ordering past the project's hardware-schedule need is a warning now, not a hard block.
// Leaving reconciliation with a selection that over-orders opens a confirm modal - Go back stays on
// the step, Proceed anyway advances. Finalize itself does not enforce the limit.
describe('ImportWizard over-order warning', () => {
  const RECONCILE_VARIABLES = {
    projectId: 'proj-1',
    items: [
      { openingNumber: 'O-1', hardwareCategory: 'Hinges', productCode: 'HNG-100', quantityNeeded: 3 },
      { openingNumber: 'O-2', hardwareCategory: 'Locks', productCode: 'LCK-200', quantityNeeded: 1 },
    ],
  };

  // HNG-100 needs 3 across the project and 1 is already ORDERED. Selecting it carries the opening's
  // full demand of 3, which would put the project at 4 against a need of 3 - an over-order. LCK-200
  // has nothing committed and is fine.
  const overOrderReconcileMock: MockedResponse = {
    request: { query: RECONCILE_SCHEDULE, variables: RECONCILE_VARIABLES },
    result: {
      data: {
        reconcileSchedule: [
          { __typename: 'ReconciliationResult', openingNumber: 'O-1', hardwareCategory: 'Hinges', productCode: 'HNG-100', quantity: 2, status: 'NOT_COVERED' },
          { __typename: 'ReconciliationResult', openingNumber: 'O-1', hardwareCategory: 'Hinges', productCode: 'HNG-100', quantity: 1, status: 'ORDERED' },
          { __typename: 'ReconciliationResult', openingNumber: 'O-2', hardwareCategory: 'Locks', productCode: 'LCK-200', quantity: 1, status: 'NOT_COVERED' },
        ],
      },
    },
  };

  async function walkToReconciliation() {
    renderWizard({ project: reimportProject, mocks: [...reimportBaseMocks, overOrderReconcileMock] });
    await flushApollo();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Create Purchase Orders/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();
    await flushApollo();
  }

  it('warns inline rather than blocking Next, and opens the confirm modal on Next', async () => {
    await walkToReconciliation();

    expect(screen.getByRole('heading', { name: 'Reconciliation' })).toBeInTheDocument();
    // Over-ordering no longer disables Next; the step warns inline.
    expect(nextButton()).toBeEnabled();
    expect(screen.getByText(/would exceed the project need/i)).toBeInTheDocument();

    // Next opens the modal instead of advancing. The modal aria-hides the step behind it, so we
    // assert we did NOT reach Classification rather than re-querying the (now hidden) recon heading.
    clickNext();
    expect(screen.getByRole('button', { name: /Proceed anyway/i })).toBeInTheDocument();
    expect(screen.getByText(/needs 3, this would make it 4 \(\+1 over\)/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Classification' })).not.toBeInTheDocument();
  });

  it('Go back keeps the user on reconciliation', async () => {
    await walkToReconciliation();
    clickNext();

    fireEvent.click(screen.getByRole('button', { name: /Go back/i }));

    // The dialog closes with an exit transition, so poll until it is gone before reading the step
    // (which the open dialog had aria-hidden).
    // 5s timeout: the exit transition loses to CPU contention when suites run in parallel.
    await waitFor(
      () => expect(screen.queryByRole('button', { name: /Proceed anyway/i })).not.toBeInTheDocument(),
      { timeout: 5000 },
    );
    expect(screen.getByRole('heading', { name: 'Reconciliation' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Classification' })).not.toBeInTheDocument();
  });

  it('Proceed anyway advances to Classification', async () => {
    await walkToReconciliation();
    clickNext();

    fireEvent.click(screen.getByRole('button', { name: /Proceed anyway/i }));

    expect(await screen.findByRole('heading', { name: 'Classification' })).toBeInTheDocument();
  });
});

// #566: forward/back and the step position live in one fixed spot in the AppBar now, not in a
// bottom row that moved with content height. The gate for each step is computed in the wizard, so
// these walk the same buttons the earlier tests do - they just now sit in the toolbar.
describe('ImportWizard AppBar nav', () => {
  it('shows the step position and disables Back on the first step', () => {
    renderWizard();

    // First import with no purpose chosen: upload / purpose / openings / finalize.
    expect(screen.getByText('Step 1 of 4')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();
    expect(nextButton()).toBeEnabled();
  });

  it('advances the step counter and enables Back once past the first step', () => {
    renderWizard();
    expect(screen.getByText('Step 1 of 4')).toBeInTheDocument();

    clickNext();

    expect(screen.getByRole('heading', { name: 'Select Import Purpose' })).toBeInTheDocument();
    expect(screen.getByText('Step 2 of 4')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back' })).toBeEnabled();
  });

  it('reflects the disabled-Next reason under the AppBar on a compose step with no offer', async () => {
    // An empty coverage answer: nothing is owed, so Next stays disabled and the AppBar says why
    // instead of the reason sitting beside a bottom button that no longer exists.
    const emptyCoverage: MockedResponse = {
      request: {
        query: GET_REQUEST_COVERAGE,
        variables: { projectId: 'proj-1', openingNumbers: ['O-1', 'O-2'] },
      },
      maxUsageCount: Number.POSITIVE_INFINITY,
      result: { data: { requestCoverage: [] } },
    };
    renderWizard({
      project: reimportProject,
      mocks: [...reimportBaseMocks, reconcileMock, emptyCoverage],
    });
    await flushApollo();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();
    await flushApollo();
    clickNext();
    await flushApollo();

    expect(screen.getByRole('heading', { name: 'Shop Assembly' })).toBeInTheDocument();
    expect(nextButton()).toBeDisabled();
    expect(screen.getByText('There is nothing to request for these openings.')).toBeInTheDocument();
  });

  it('drops Next and keeps only Back on the finalize step, alongside the in-content CTA', async () => {
    renderWizard({
      project: reimportProject,
      mocks: [...reimportBaseMocks, reconcileMock, requestCoverageMock],
    });
    await flushApollo();
    clickNext();
    fireEvent.click(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i }));
    clickNext();
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    clickNext();
    await flushApollo();
    clickNext();
    await flushApollo();

    // The compose step auto-assigns the one owed line, so Next is live and carries us to finalize.
    expect(screen.getByRole('heading', { name: 'Shop Assembly' })).toBeInTheDocument();
    expect(nextButton()).toBeEnabled();
    clickNext();
    await flushApollo();

    expect(screen.getByRole('heading', { name: 'Review & Finalize' })).toBeInTheDocument();
    // upload / purpose / openings / reconciliation / shop-assembly / finalize
    expect(screen.getByText('Step 6 of 6')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Finish Import Session/i })).toBeInTheDocument();
  });
});

// A module's "Start a Request" link into shop assembly lands here: the project is chosen and its
// purpose is preselected, so the wizard opens with the purpose already answered. (Shipping-out
// composition has left the wizard entirely - it lives on the request workspace now.)
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

  it('preselects the assembly purpose on a re-import project', async () => {
    renderWizard({
      project: reimportProject,
      mocks: [...reimportMocks],
      initialPurpose: 'assembly',
    });
    await flushApollo();
    clickNext();

    expect(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i })).toBeChecked();
  });

  it('leaves the purpose unset on a project with no schedule, rather than checking a disabled option', async () => {
    // Shop assembly needs an existing schedule. Silently checking it on a first import would land the
    // user on a radio they cannot use with nothing saying why.
    renderWizard({ project: firstImportProject, initialPurpose: 'assembly' });
    clickNext();

    expect(screen.getByRole('radio', { name: /Pull Request for Shop Assembly/i })).not.toBeChecked();
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
      initialPurpose: 'assembly',
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
      initialPurpose: 'assembly',
      autoStartFromLatest: true,
    });
    await flushApollo();

    expect(hydrate).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'Hardware Schedule' })).toBeInTheDocument();
  });
});
