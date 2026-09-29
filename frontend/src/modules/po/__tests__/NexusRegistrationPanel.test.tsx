import { render, screen, waitFor, configure, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import NexusRegistrationPanel from '../NexusRegistrationPanel';
import { GET_PROJECT_SCHEDULE_PRODUCTS } from '../../../graphql/admin';
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

function renderPanel(po: PurchaseOrder, mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
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

it('shows an already registered line read-only', async () => {
  const po = makePo({
    lineItems: [
      makeLineItem({
        id: 'li-1',
        hardwareCategory: 'Hinges',
        productCode: 'HG-100',
        nexusRegistered: true,
      }),
    ],
  });
  renderPanel(po, [scheduleMock([product()])]);

  expect(await screen.findByText('Registered')).toBeInTheDocument();
  expect(screen.queryByLabelText('Product')).not.toBeInTheDocument();
  // Nothing to send, so the save button has nothing to do.
  expect(screen.getByRole('button', { name: 'Register in Nexus' })).toBeDisabled();
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
