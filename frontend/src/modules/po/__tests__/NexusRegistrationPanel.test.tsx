import { render, screen, waitFor, configure, fireEvent } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import NexusRegistrationPanel from '../NexusRegistrationPanel';
import { GET_PROJECT_SCHEDULE_PRODUCTS } from '../../../graphql/admin';
import { GET_PO_LINE_TIED_QUANTITIES, NEXUS_REGISTER_PO_LINES } from '../../../graphql/po';
import type { PurchaseOrder } from '../index';

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

type LineItem = PurchaseOrder['lineItems'][number];

function makeLineItem(overrides: Partial<LineItem> & { id: string }): LineItem {
  return {
    poId: 'po-1',
    // A mirrored line holds GP's own pair: the item number in hardwareCategory, the description
    // in productCode.
    hardwareCategory: 'HD 001',
    productCode: 'HD 001 HINGE 4.5 X 4.5 HG-100',
    classification: null,
    orderedQuantity: 5,
    receivedQuantity: 0,
    unitCost: 10,
    orderAs: null,
    costCode: null,
    uofm: 'Each',
    jobCost: true,
    gpLineOrd: 16384,
    nexusRegistered: false,
    customInventoryItemId: null,
    manufacturer: null,
    createdAt: '2026-07-01T12:00:00Z',
    updatedAt: '2026-07-01T12:00:00Z',
    ...overrides,
  };
}

function makePo(overrides: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: 'po-1',
    poNumber: 'PO094114',
    requestNumber: null,
    origin: 'GP',
    gpSyncedAt: '2026-09-01T12:00:00Z',
    nexusRegistered: false,
    projectId: 'p1',
    status: 'GP_REGISTERED',
    company: 'TUBC',
    gpCompany: 'TUBC',
    gpVendorId: 'V1',
    vendorNameSnapshot: 'Ace Hardware Co',
    costCode: null,
    buyerId: null,
    vendorQuoteNumber: null,
    shippingCost: null,
    tariffAmount: null,
    notes: null,
    preferredDeliveryDate: null,
    expectedDeliveryDate: null,
    orderedAt: '2026-08-01',
    createdAt: '2026-07-01T12:00:00Z',
    updatedAt: '2026-07-01T12:00:00Z',
    lineItems: [makeLineItem({ id: 'li-1' })],
    receiveRecords: [],
    documents: [],
    documentData: null,
    ...overrides,
  };
}

function scheduleMock(products: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: GET_PROJECT_SCHEDULE_PRODUCTS, variables: { projectIds: ['p1'] } },
    result: { data: { projectScheduleProducts: products } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function product(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ProjectScheduleProduct',
    projectId: 'p1',
    hardwareCategory: 'Hinges',
    productCode: 'HG-100',
    classification: null,
    requiredQuantity: 12,
    availableQuantity: 12,
    ...overrides,
  };
}

/** #1128: the units already tied to each line. Lines left out have nothing tied. */
function tiedMock(tied: Record<string, number> = {}): MockedResponse {
  return {
    request: { query: GET_PO_LINE_TIED_QUANTITIES, variables: { poId: 'po-1' } },
    result: {
      data: {
        poLineTiedQuantities: Object.entries(tied).map(([poLineItemId, tiedQuantity]) => ({
          __typename: 'PoLineTiedQuantity',
          poLineItemId,
          tiedQuantity,
        })),
      },
    },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function renderPanel(po: PurchaseOrder, mocks: MockedResponse[]) {
  // Every project PO asks what is already tied; a test that cares passes its own tiedMock first.
  const withTied = po.projectId ? [...mocks, tiedMock()] : mocks;
  return render(
    <MockedProvider mocks={withTied}>
      <ToastProvider>
        <NexusRegistrationPanel po={po} onRefetch={vi.fn()} />
      </ToastProvider>
    </MockedProvider>,
  );
}

it('preselects the schedule product whose code is in the GP description', async () => {
  renderPanel(makePo(), [scheduleMock([product(), product({ productCode: 'LK-200' })])]);

  const picker = await screen.findByLabelText('Product');
  await waitFor(() => expect((picker as HTMLSelectElement).value).toBe('Hinges :: HG-100'));
});

it('defaults the tie quantity to what is still outstanding', async () => {
  // 5 ordered, 2 already received: 3 outstanding, and the schedule has plenty left.
  const po = makePo({ lineItems: [makeLineItem({ id: 'li-1', receivedQuantity: 2 })] });
  renderPanel(po, [scheduleMock([product()])]);

  // Wait for the schedule products, without which no product is picked and no tie is possible.
  const picker = await screen.findByLabelText('Product');
  await waitFor(() => expect((picker as HTMLSelectElement).value).toBe('Hinges :: HG-100'));

  expect((screen.getByLabelText('Tie quantity') as HTMLInputElement).value).toBe('3');
  expect(screen.getByText('max 3')).toBeInTheDocument();
});

it('caps the tie quantity at what the schedule still has unpurchased', async () => {
  // 5 outstanding, but only 2 units of the product were never drafted onto a PO.
  renderPanel(makePo(), [scheduleMock([product({ availableQuantity: 2 })])]);

  const picker = await screen.findByLabelText('Product');
  await waitFor(() => expect((picker as HTMLSelectElement).value).toBe('Hinges :: HG-100'));

  expect((screen.getByLabelText('Tie quantity') as HTMLInputElement).value).toBe('2');
  expect(screen.getByText('max 2')).toBeInTheDocument();
});

it('asks for a typed identity and no tie at all on a PO with no project', async () => {
  renderPanel(makePo({ projectId: null }), []);

  expect(await screen.findByLabelText('Hardware Category')).toBeInTheDocument();
  expect(screen.getByLabelText('Product Code')).toBeInTheDocument();
  expect(screen.queryByLabelText('Product')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Tie quantity')).not.toBeInTheDocument();
  expect(screen.queryByText('Tie qty')).not.toBeInTheDocument();
});

const registeredLine = (overrides: Partial<LineItem> = {}) =>
  makeLineItem({ id: 'li-1', hardwareCategory: 'Hinges', productCode: 'HG-100', nexusRegistered: true, ...overrides });

it('shows a fully tied registered line read-only', async () => {
  const po = makePo({ lineItems: [registeredLine()] });
  // All 5 outstanding units are tied.
  renderPanel(po, [tiedMock({ 'li-1': 5 }), scheduleMock([product()])]);

  expect(await screen.findByText('Registered')).toBeInTheDocument();
  expect(screen.queryByLabelText('Product')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Tie quantity')).not.toBeInTheDocument();
  // Nothing to send, so the save button has nothing to do.
  expect(screen.getByRole('button', { name: 'Register in Nexus' })).toBeDisabled();
});

it('keeps a registered line open for the units it still has untied (#1128)', async () => {
  const po = makePo({ lineItems: [registeredLine({ orderedQuantity: 10 })] });
  // 10 outstanding, 9 tied: one unit is still untied.
  renderPanel(po, [tiedMock({ 'li-1': 9 }), scheduleMock([product()])]);

  const tie = await screen.findByLabelText('Tie quantity');
  await waitFor(() => expect((tie as HTMLInputElement).value).toBe('1'));
  expect(screen.getByText('max 1')).toBeInTheDocument();
  // The identity is fixed: no product picker on a registered line.
  expect(screen.queryByLabelText('Product')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Register in Nexus' })).toBeEnabled();
});

it('says so when fewer units were tied than asked (#1128)', async () => {
  const po = makePo();
  const register: MockedResponse = {
    request: {
      query: NEXUS_REGISTER_PO_LINES,
      variables: {
        input: {
          poId: 'po-1',
          lines: [{ poLineItemId: 'li-1', hardwareCategory: 'Hinges', productCode: 'HG-100', tieQuantity: 5 }],
        },
      },
    },
    result: {
      data: {
        nexusRegisterPoLines: {
          __typename: 'NexusRegisterPoLinesResult',
          tiedUnits: 3,
          purchaseOrder: {
            __typename: 'PurchaseOrder',
            id: 'po-1',
            nexusRegistered: true,
            lineItems: [],
          },
        },
      },
    },
  };
  renderPanel(po, [scheduleMock([product()]), register]);

  const picker = await screen.findByLabelText('Product');
  await waitFor(() => expect((picker as HTMLSelectElement).value).toBe('Hinges :: HG-100'));
  fireEvent.click(screen.getByRole('button', { name: 'Register in Nexus' }));

  expect(await screen.findByText(/3 units of 5 tied to the schedule/)).toBeInTheDocument();
  expect(screen.getByText(/2 units could not be tied/)).toBeInTheDocument();
});

// #909: the grid fits the panel with resizable columns instead of scrolling sideways.
describe('grid width (#909)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** Report every observed box as `width` px wide; jsdom lays nothing out. */
  function stubWidth(width: number) {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        private cb: ResizeObserverCallback;
        constructor(cb: ResizeObserverCallback) {
          this.cb = cb;
        }
        observe() {
          this.cb([{ contentRect: { width } } as ResizeObserverEntry], this as unknown as ResizeObserver);
        }
        unobserve() {}
        disconnect() {}
      },
    );
  }

  /** The header row's column widths, read off the rule its own class carries (jsdom computes no
   *  grid tracks). */
  function tracks(): number[] {
    const header = screen.getByTestId('nexus-registration-grid').firstElementChild as HTMLElement;
    const css = Array.from(document.querySelectorAll('style'))
      .map((s) => s.textContent ?? '')
      .join('\n');
    const gridClass = Array.from(header.classList).find((c) => c.startsWith('css-')) as string;
    const rule = css.slice(css.lastIndexOf(`.${gridClass}{`));
    const value = /grid-template-columns:([^;]+);/.exec(rule)?.[1] ?? '';
    return value.trim().split(/\s+/).map((t) => parseFloat(t));
  }

  it('fits the panel exactly, never scrolls sideways, and resizes from the keyboard', async () => {
    stubWidth(900);
    renderPanel(makePo(), [scheduleMock([product()])]);
    await screen.findByLabelText('Product');

    for (const name of ['Item Number', 'Description', 'Ord', 'Rec', 'Out', 'Product', 'Tie qty']) {
      expect(screen.getByRole('separator', { name: `Resize ${name} column` })).toBeInTheDocument();
    }
    const widths = tracks();
    expect(widths).toHaveLength(8);
    expect(widths.reduce((a, b) => a + b, 0)).toBeCloseTo(900, 0);
    const grid = screen.getByTestId('nexus-registration-grid');
    for (const el of [grid, grid.parentElement as HTMLElement, grid.firstElementChild as HTMLElement]) {
      expect(['auto', 'scroll']).not.toContain(getComputedStyle(el).overflowX);
    }

    const handle = screen.getByRole('separator', { name: 'Resize Product column' });
    const before = Number(handle.getAttribute('aria-valuenow'));
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(Number(handle.getAttribute('aria-valuenow'))).toBe(before + 16);
  });

  it('gives the typed identity columns their own handles on a PO with no project', async () => {
    stubWidth(760);
    renderPanel(makePo({ projectId: null }), []);
    await screen.findByLabelText('Hardware Category');

    expect(screen.getByRole('separator', { name: 'Resize Hardware Category column' })).toBeInTheDocument();
    expect(screen.getByRole('separator', { name: 'Resize Product Code column' })).toBeInTheDocument();
    expect(tracks().reduce((a, b) => a + b, 0)).toBeCloseTo(760, 0);
  });
});
