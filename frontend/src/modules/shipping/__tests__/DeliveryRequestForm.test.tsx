import { useEffect, useRef } from 'react';
import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { InMemoryCache } from '@apollo/client/cache';
import { useQuery } from '@apollo/client/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import { CartProvider, useCart, type CartItem } from '../../../contexts/CartContext';
import DeliveryRequestForm from '../DeliveryRequestForm';
import { CONFIRM_SHIPMENT, GET_SHIP_READY_ITEMS, GET_SHIPMENT_METHODS } from '../../../graphql/shipping';
import { GET_WAREHOUSES } from '../../../graphql/shared';

// MUI Dialog under jsdom is slow, and slower still when the whole suite runs in parallel - the same
// budget lift ReceiveModal/LocationActionDialog need. In isolation these finish in under a second.
vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Me',
    userId: 'me',
    roles: [],
    hasRole: () => false,
    isAdmin: false,
    gpBuyerId: null,
    user: null,
  }),
}));

// The real renderer pulls a font/layout stack that jsdom can't run, and none of these tests exercise
// the PDF path - DeliveryRequestDocument only needs the primitives to import.
vi.mock('@react-pdf/renderer', () => ({
  pdf: () => ({ toBlob: () => Promise.resolve(new Blob()) }),
  Document: () => null,
  Page: () => null,
  Text: () => null,
  View: () => null,
  StyleSheet: { create: (s: unknown) => s },
}));

const PROJECT_ID = 'proj-1';

const CART_ITEM: CartItem = {
  id: 'oi-1',
  itemType: 'Opening_Item',
  openingItemId: 'oi-1',
  openingNumber: '0019-EX',
  leaf: 1,
  quantity: 1,
  building: 'A',
  floor: '1',
  location: 'Rm 101',
};

// Every Delivery Request field travels on every confirm, blanks as explicit nulls - which is what
// makes a cleared field mean "cleared" rather than "unchanged".
const BLANK_DETAILS = {
  pickupDate: null as string | null,
  deliveryDate: null as string | null,
  shipperEmail: null as string | null,
  shipperPhone: null as string | null,
  pickupLocation: null as string | null,
  shipmentMethod: null as string | null,
  carrierTagBol: null as string | null,
  weightLbs: null as number | null,
  deliveryAddress: null as string | null,
  specialInstructions: null as string | null,
  gateNumber: null as string | null,
  forkliftOnsite: null as string | null,
  materialComingBack: null as string | null,
  siteMaterialIncluded: null as string | null,
  constructionTempKeys: null as string | null,
  extraFrameAnchors: null as string | null,
  contractorContactName: null as string | null,
  contractorContactPhone: null as string | null,
  ucshContactName: null as string | null,
  ucshContactPhone: null as string | null,
  salesOrderNumber: null as string | null,
};

type Details = Partial<typeof BLANK_DETAILS>;

function confirmVars(details: Details = {}) {
  return {
    input: {
      projectId: PROJECT_ID,
      packingSlipNumber: 'PS-0019-L1',
      items: [{ itemType: 'OPENING_ITEM', openingItemId: 'oi-1', quantity: 1 }],
      ...BLANK_DETAILS,
      ...details,
    },
  };
}

function slipResult(details: Details = {}) {
  return {
    __typename: 'PackingSlip',
    id: 'ps-1',
    packingSlipNumber: 'PS-0019-L1',
    projectId: PROJECT_ID,
    status: 'SCHEDULED',
    shippedBy: 'Me',
    shippedAt: '2026-07-24T00:00:00Z',
    createdAt: '2026-07-24T00:00:00Z',
    pickedUpAt: null,
    pickedUpBy: null,
    deliveredAt: null,
    deliveredBy: null,
    ...BLANK_DETAILS,
    ...details,
  };
}

function shipReadyLeaf() {
  return {
    __typename: 'OpeningItem',
    id: 'oi-1',
    projectId: PROJECT_ID,
    openingId: 'op-1',
    openingNumber: '0019-EX',
    building: 'A',
    floor: '1',
    location: 'Rm 101',
    leaf: 1,
    quantity: 1,
    assemblyCompletedAt: '2026-07-24T00:00:00Z',
    state: 'SHIP_READY',
    aisle: null,
    row: null,
    bay: null,
    createdAt: '2026-07-24T00:00:00Z',
    updatedAt: '2026-07-24T00:00:00Z',
    installedHardware: [],
  };
}

function confirmMock(details: Details = {}): MockedResponse {
  return {
    request: { query: CONFIRM_SHIPMENT, variables: confirmVars(details) },
    result: {
      data: {
        confirmShipment: {
          ...slipResult(details),
          items: [
            {
              __typename: 'PackingSlipItem',
              id: 'psi-1',
              packingSlipId: 'ps-1',
              itemType: 'OPENING_ITEM',
              openingItemId: 'oi-1',
              openingNumber: '0019-EX',
              leaf: 1,
              productCode: 'AD8406',
              hardwareCategory: 'Locksets',
              quantity: 1,
            },
          ],
        },
      },
    },
  };
}

// No warehouses -> nothing to prefill, so the details the tests assert on are exactly the ones they
// typed. The prefill itself is pinned by its own test below.
function warehousesMock(warehouses: Record<string, unknown>[] = [], count = 1): MockedResponse {
  return {
    request: { query: GET_WAREHOUSES, variables: { includeInactive: false } },
    maxUsageCount: count,
    result: { data: { warehouses } },
  };
}

// The server's post-shipment answer: get_ship_ready_items filters on state == SHIP_READY, so the
// leaf that just shipped is simply gone.
function shipReadyAfterShipmentMock(): MockedResponse {
  return {
    request: { query: GET_SHIP_READY_ITEMS, variables: { projectId: PROJECT_ID } },
    result: {
      data: {
        shipReadyItems: { __typename: 'ShipReadyItems', openingItems: [], looseItems: [] },
      },
    },
  };
}

// Seeds one opening item into the cart on mount and exposes the live count, so a test can assert the
// cart emptied without reaching into the context internals.
function CartProbe() {
  const { items, addItem } = useCart();
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    seeded.current = true;
    addItem(CART_ITEM);
  }, [addItem]);
  return <div data-testid="cart-count">{items.length}</div>;
}

// Stands in for ShipReadyBrowser: the same query, mounted behind the dialog, read cache-first.
function ShipReadyProbe() {
  const { data } = useQuery<{ shipReadyItems: { openingItems: { id: string }[] } }>(
    GET_SHIP_READY_ITEMS,
    { variables: { projectId: PROJECT_ID } },
  );
  return <div data-testid="ship-ready-count">{data ? data.shipReadyItems.openingItems.length : -1}</div>;
}

// A cache holding what the Ship view read before the shipment - the snapshot that must not survive.
function seededCache() {
  const cache = new InMemoryCache();
  cache.writeQuery({
    query: GET_SHIP_READY_ITEMS,
    variables: { projectId: PROJECT_ID },
    data: {
      shipReadyItems: {
        __typename: 'ShipReadyItems',
        openingItems: [shipReadyLeaf()],
        looseItems: [],
      },
    },
  });
  return cache;
}

// The form reads the shipment-method list on open (#451). Folded in here rather than added to every
// mock list below: an empty list is the state these tests want - the method field degrades to free
// text and none of them assert on it - and a missing mock would fail each one on an unrelated query.
const shipmentMethodsMock: MockedResponse = {
  request: { query: GET_SHIPMENT_METHODS, variables: { activeOnly: true } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { shipmentMethods: [] } },
};

function renderForm(mocks: MockedResponse[], cache: InMemoryCache, withShipReadyProbe = false) {
  render(
    <MockedProvider mocks={[shipmentMethodsMock, ...mocks]} cache={cache}>
      <MemoryRouter>
        <ToastProvider>
          <CartProvider>
            <CartProbe />
            {withShipReadyProbe && <ShipReadyProbe />}
            <DeliveryRequestForm
              open
              onClose={vi.fn()}
              onShipped={vi.fn()}
              projectId={PROJECT_ID}
              projectName="TUBC 80003"
              jobNumber="23093"
            />
          </CartProvider>
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
}

async function submitShipment(
  mocks: MockedResponse[],
  cache: InMemoryCache,
  withShipReadyProbe = false,
) {
  renderForm(mocks, cache, withShipReadyProbe);
  await waitFor(() => expect(screen.getByTestId('cart-count')).toHaveTextContent('1'));
  fireEvent.change(screen.getByLabelText(/Packing Slip Number/i), {
    target: { value: 'PS-0019-L1' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Confirm Shipment/i }));
}

describe('DeliveryRequestForm', () => {
  it('captures the whole Delivery Request, not just a slip number', () => {
    renderForm([warehousesMock()], seededCache());

    expect(screen.getByLabelText(/Pick-up date/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Delivery date/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Carrier \/ Tag \/ BOL/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Weight \(lbs\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Pickup location/i)).toBeInTheDocument();
    // The eight site questions, in the wording of the paper form.
    expect(screen.getByLabelText(/1\) Delivery address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/4\) Is there a forklift onsite or loading dock\?/i)).toBeInTheDocument();
    expect(
      screen.getByLabelText(/8\) Extra frame anchors and or parts if applicable/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Contractor contact name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/UCSH contact name/i)).toBeInTheDocument();
    // The shipper is the signed-in user and is not a text box.
    expect(screen.getByLabelText('Shipper')).toBeDisabled();
  });

  it('sends every Delivery Request field it was given', async () => {
    const details: Details = {
      pickupDate: '2026-07-21',
      carrierTagBol: 'BOL-8891',
      weightLbs: 420,
      contractorContactName: 'Robert Purcell',
    };
    renderForm([warehousesMock(), confirmMock(details)], seededCache());
    await waitFor(() => expect(screen.getByTestId('cart-count')).toHaveTextContent('1'));

    fireEvent.change(screen.getByLabelText(/Packing Slip Number/i), {
      target: { value: 'PS-0019-L1' },
    });
    fireEvent.change(screen.getByLabelText(/Pick-up date/i), { target: { value: '2026-07-21' } });
    fireEvent.change(screen.getByLabelText(/Carrier \/ Tag \/ BOL/i), {
      target: { value: 'BOL-8891' },
    });
    fireEvent.change(screen.getByLabelText(/Weight \(lbs\)/i), { target: { value: '420' } });
    fireEvent.change(screen.getByLabelText(/Contractor contact name/i), {
      target: { value: 'Robert Purcell' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Confirm Shipment/i }));

    // The mock only answers this exact variable set, so reaching the success view IS the assertion.
    await waitFor(() => expect(screen.getByText('Shipment Confirmed')).toBeInTheDocument());
  });

  it('snapshots the primary warehouse address into the pickup location', async () => {
    renderForm(
      [
        warehousesMock([
          {
            __typename: 'Warehouse',
            id: 'w-2',
            name: 'Coast Meridian',
            code: 'CM',
            address: '1120 1725 Coast Meridian Road',
            city: 'Port Coquitlam',
            province: 'BC',
            postalCode: 'V3C 3T7',
            isPrimary: true,
            isActive: true,
            createdAt: '2026-01-01T00:00:00Z',
            updatedAt: '2026-01-01T00:00:00Z',
          },
        ]),
      ],
      seededCache(),
    );

    await waitFor(() =>
      expect(screen.getByLabelText(/Pickup location/i)).toHaveValue(
        'Coast Meridian\n1120 1725 Coast Meridian Road\nPort Coquitlam BC V3C 3T7',
      ),
    );
  });

  it('offers the Delivery Request rather than a packing slip once confirmed', async () => {
    await submitShipment([warehousesMock(), confirmMock()], seededCache());

    await waitFor(() => expect(screen.getByText('Shipment Confirmed')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /View Delivery Request/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /View Packing Slip/i })).not.toBeInTheDocument();
  });

  // The bug in #337: the Ship view sat behind this dialog still offering the shipped leaf.
  it('refreshes a mounted ship-ready consumer so the shipped leaf leaves the grid', async () => {
    await submitShipment(
      [warehousesMock(), confirmMock(), shipReadyAfterShipmentMock()],
      seededCache(),
      true,
    );

    await waitFor(() => expect(screen.getByText('Shipment Confirmed')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('ship-ready-count')).toHaveTextContent('0'));
  });

  it('empties the cart as soon as the shipment succeeds, not on the next button press', async () => {
    await submitShipment([warehousesMock(), confirmMock()], seededCache());

    await waitFor(() => expect(screen.getByText('Shipment Confirmed')).toBeInTheDocument());
    // Still on the success view - no "Ship More Items" / "Return to Home" click yet.
    expect(screen.getByTestId('cart-count')).toHaveTextContent('0');
  });

  it('evicts the pre-shipment root fields so unmounted views refetch instead of reusing them', async () => {
    const cache = seededCache();
    const shipReadyKeys = () =>
      Object.keys(cache.extract().ROOT_QUERY ?? {}).filter((k) => k.startsWith('shipReadyItems'));
    expect(shipReadyKeys()).not.toHaveLength(0);

    await submitShipment([warehousesMock(), confirmMock()], cache);

    await waitFor(() => expect(screen.getByText('Shipment Confirmed')).toBeInTheDocument());
    expect(shipReadyKeys()).toHaveLength(0);
  });

  // Keyed on extensions.code, so this asserts the real CombinedGraphQLErrors shape the backend's
  // ErrorHandlerExtension produces - not a bare network Error.
  it('replaces the raw state-transition error with a readable one', async () => {
    const rejected: MockedResponse = {
      request: { query: CONFIRM_SHIPMENT, variables: confirmVars() },
      result: {
        errors: [
          {
            message: 'Opening item 9f2 is not Ship_Ready (current: Shipped_Out)',
            extensions: { code: 'INVALID_STATE_TRANSITION' },
          },
        ],
      },
    };
    await submitShipment(
      [warehousesMock([], 2), rejected, shipReadyAfterShipmentMock()],
      seededCache(),
    );

    await waitFor(() => expect(screen.getByText(/no longer ship-ready/i)).toBeInTheDocument());
    expect(screen.queryByText(/not Ship_Ready \(current/)).not.toBeInTheDocument();
    expect(screen.queryByText('Shipment Confirmed')).not.toBeInTheDocument();
  });

  it('keeps the insufficiency detail and notes the refresh', async () => {
    const rejected: MockedResponse = {
      request: { query: CONFIRM_SHIPMENT, variables: confirmVars() },
      result: {
        errors: [
          {
            message:
              'Insufficient loose hardware: AD8406 (Locksets) for opening 0019-EX - requested 4, available 1',
            extensions: { code: 'VALIDATION_ERROR', field: 'items' },
          },
        ],
      },
    };
    await submitShipment(
      [warehousesMock([], 2), rejected, shipReadyAfterShipmentMock()],
      seededCache(),
    );

    await waitFor(() => expect(screen.getByText(/requested 4, available 1/)).toBeInTheDocument());
    expect(screen.getByText(/list has been refreshed/i)).toBeInTheDocument();
  });
});
