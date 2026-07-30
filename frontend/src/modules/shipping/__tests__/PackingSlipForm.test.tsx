import { useEffect, useRef } from 'react';
import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { InMemoryCache } from '@apollo/client/cache';
import { useQuery } from '@apollo/client/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import { CartProvider, useCart, type CartItem } from '../../../contexts/CartContext';
import PackingSlipForm from '../PackingSlipForm';
import { CONFIRM_SHIPMENT, GET_SHIP_READY_ITEMS } from '../../../graphql/shipping';

// MUI Dialog under jsdom is slow, and slower still when the whole suite runs in parallel - the same
// budget lift ReceiveModal/LocationActionDialog need. In isolation these three finish in under a second.
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
// the PDF path - PackingSlipDocument only needs the primitives to import.
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

const CONFIRM_VARS = {
  input: {
    projectId: PROJECT_ID,
    packingSlipNumber: 'PS-0019-L1',
    items: [{ itemType: 'OPENING_ITEM', openingItemId: 'oi-1', quantity: 1 }],
  },
};

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

function confirmMock(): MockedResponse {
  return {
    request: { query: CONFIRM_SHIPMENT, variables: CONFIRM_VARS },
    result: {
      data: {
        confirmShipment: {
          __typename: 'PackingSlip',
          id: 'ps-1',
          packingSlipNumber: 'PS-0019-L1',
          projectId: PROJECT_ID,
          shippedBy: 'Me',
          shippedAt: '2026-07-24T00:00:00Z',
          createdAt: '2026-07-24T00:00:00Z',
          items: [
            {
              __typename: 'PackingSlipItem',
              id: 'psi-1',
              packingSlipId: 'ps-1',
              itemType: 'OPENING_ITEM',
              openingItemId: 'oi-1',
              openingNumber: '0019-EX',
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

function renderForm(mocks: MockedResponse[], cache: InMemoryCache, withShipReadyProbe = false) {
  render(
    <MockedProvider mocks={mocks} cache={cache}>
      <MemoryRouter>
        <ToastProvider>
          <CartProvider>
            <CartProbe />
            {withShipReadyProbe && <ShipReadyProbe />}
            <PackingSlipForm
              open
              onClose={vi.fn()}
              onShipped={vi.fn()}
              projectId={PROJECT_ID}
              projectName="TUBC 80003"
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

describe('PackingSlipForm', () => {
  // The bug in #337: the Ship view sat behind this dialog still offering the shipped leaf.
  it('refreshes a mounted ship-ready consumer so the shipped leaf leaves the grid', async () => {
    await submitShipment([confirmMock(), shipReadyAfterShipmentMock()], seededCache(), true);

    await waitFor(() => expect(screen.getByText('Shipment Confirmed')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('ship-ready-count')).toHaveTextContent('0'));
  });

  it('empties the cart as soon as the shipment succeeds, not on the next button press', async () => {
    await submitShipment([confirmMock()], seededCache());

    await waitFor(() => expect(screen.getByText('Shipment Confirmed')).toBeInTheDocument());
    // Still on the success view - no "Ship More Items" / "Return to Home" click yet.
    expect(screen.getByTestId('cart-count')).toHaveTextContent('0');
  });

  it('evicts the pre-shipment root fields so unmounted views refetch instead of reusing them', async () => {
    const cache = seededCache();
    const shipReadyKeys = () =>
      Object.keys(cache.extract().ROOT_QUERY ?? {}).filter((k) => k.startsWith('shipReadyItems'));
    expect(shipReadyKeys()).not.toHaveLength(0);

    await submitShipment([confirmMock()], cache);

    await waitFor(() => expect(screen.getByText('Shipment Confirmed')).toBeInTheDocument());
    expect(shipReadyKeys()).toHaveLength(0);
  });

  // Keyed on extensions.code, so this asserts the real CombinedGraphQLErrors shape the backend's
  // ErrorHandlerExtension produces - not a bare network Error.
  it('replaces the raw state-transition error with a readable one', async () => {
    const rejected: MockedResponse = {
      request: { query: CONFIRM_SHIPMENT, variables: CONFIRM_VARS },
      result: {
        errors: [
          {
            message: 'Opening item 9f2 is not Ship_Ready (current: Shipped_Out)',
            extensions: { code: 'INVALID_STATE_TRANSITION' },
          },
        ],
      },
    };
    await submitShipment([rejected, shipReadyAfterShipmentMock()], seededCache());

    await waitFor(() => expect(screen.getByText(/no longer ship-ready/i)).toBeInTheDocument());
    expect(screen.queryByText(/not Ship_Ready \(current/)).not.toBeInTheDocument();
    expect(screen.queryByText('Shipment Confirmed')).not.toBeInTheDocument();
  });

  it('keeps the insufficiency detail and notes the refresh', async () => {
    const rejected: MockedResponse = {
      request: { query: CONFIRM_SHIPMENT, variables: CONFIRM_VARS },
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
    await submitShipment([rejected, shipReadyAfterShipmentMock()], seededCache());

    await waitFor(() => expect(screen.getByText(/requested 4, available 1/)).toBeInTheDocument());
    expect(screen.getByText(/list has been refreshed/i)).toBeInTheDocument();
  });
});
