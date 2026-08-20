import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import StagingWorkspace from '../StagingWorkspace';
import { sameStagedStock } from '../staging';
import { GET_STAGING_POOL, SET_CONTAINER_ITEMS } from '../../../graphql/shipping';

/**
 * Arranging the staging pool into what physically goes on the truck (#451).
 *
 * The drag itself is not exercised here - dnd-kit needs a pointer with real geometry, which jsdom
 * does not have. What is pinned is the state each gesture produces, through the click-equivalent
 * controls that exist beside every drag for exactly this reason.
 */

const PROJECT_ID = 'proj-1';
const INFINITE = Number.POSITIVE_INFINITY;

vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

function looseRow(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'StagedLooseItem',
    openingNumber: '101',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    stagedQuantity: 4,
    placedQuantity: 0,
    unplacedQuantity: 4,
    ...overrides,
  };
}

function container(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShipmentContainer',
    id: 'c-1',
    projectId: PROJECT_ID,
    containerType: 'BOX',
    name: 'Box 1',
    packingSlipId: null,
    createdBy: 'tester',
    items: [],
    ...overrides,
  };
}

function poolMock(pool: Record<string, unknown>): MockedResponse {
  return {
    request: { query: GET_STAGING_POOL, variables: { projectId: PROJECT_ID } },
    maxUsageCount: INFINITE,
    result: {
      data: {
        stagingPool: { __typename: 'StagingPool', looseItems: [], containers: [], ...pool },
      },
    },
  };
}

function setItemsMock(containerId: string, items: Record<string, unknown>[], onFire?: () => void): MockedResponse {
  return {
    request: { query: SET_CONTAINER_ITEMS, variables: { input: { containerId, items } } },
    maxUsageCount: INFINITE,
    result: () => {
      onFire?.();
      return { data: { setContainerItems: container({ id: containerId }) } };
    },
  };
}

function looseInput(quantity: number, overrides: Record<string, unknown> = {}) {
  return {
    openingNumber: '101',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    quantity,
    isManual: false,
    ...overrides,
  };
}

/** One pool row, by the group name it carries - the only thing that tells two rows of the same
 *  product apart. */
function poolRow(itemLabel: string) {
  return screen.getByRole('group', { name: itemLabel });
}

function renderWorkspace(mocks: MockedResponse[]) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <StagingWorkspace projectId={PROJECT_ID} />
      </ToastProvider>
    </MockedProvider>,
  );
}

describe('splitting loose hardware', () => {
  it('places only the quantity asked for, so a product can go into two containers', async () => {
    // Four hinges, two into Box 1. Without a quantity control the whole staged amount goes in one
    // container and the split is impossible.
    const fired = vi.fn();
    renderWorkspace([
      poolMock({ looseItems: [looseRow()], containers: [container()] }),
      setItemsMock('c-1', [looseInput(2)], fired),
    ]);

    const qty = await screen.findByRole('spinbutton', { name: 'Quantity of HG-100 for 101 to place' });
    fireEvent.change(qty, { target: { value: '2' } });

    fireEvent.mouseDown(within(poolRow('HG-100 for 101')).getByRole('combobox'));
    fireEvent.click(await screen.findByRole('option', { name: 'Box 1' }));

    await waitFor(() => expect(fired).toHaveBeenCalled());
  });

  it('defaults to everything unplaced, which is the ordinary case', async () => {
    const fired = vi.fn();
    renderWorkspace([
      poolMock({ looseItems: [looseRow()], containers: [container()] }),
      setItemsMock('c-1', [looseInput(4)], fired),
    ]);

    await screen.findByText('HG-100 | HINGE');
    fireEvent.mouseDown(within(poolRow('HG-100 for 101')).getByRole('combobox'));
    fireEvent.click(await screen.findByRole('option', { name: 'Box 1' }));

    await waitFor(() => expect(fired).toHaveBeenCalled());
  });

  it('offers no quantity box for a single unit - there is nothing to split', async () => {
    renderWorkspace([poolMock({ looseItems: [looseRow({ stagedQuantity: 1, unplacedQuantity: 1 })] })]);

    await screen.findByText('HG-100 | HINGE');
    expect(screen.queryByRole('spinbutton', { name: /to place/i })).not.toBeInTheDocument();
  });

  it('corrects a quantity already in a container without emptying the line first', async () => {
    const fired = vi.fn();
    const held = {
      __typename: 'ShipmentContainerItem',
      id: 'ci-1',
      openingItemId: null,
      openingNumber: '101',
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      quantity: 4,
      isManual: false,
      position: 0,
    };
    renderWorkspace([
      poolMock({ containers: [container({ items: [held] })] }),
      setItemsMock('c-1', [looseInput(3)], fired),
    ]);

    const qty = await screen.findByRole('spinbutton', { name: /Quantity of 101 · HG-100 in Box 1/i });
    fireEvent.change(qty, { target: { value: '3' } });

    await waitFor(() => expect(fired).toHaveBeenCalled());
  });

  it('takes the line out when its quantity is corrected to zero', async () => {
    const fired = vi.fn();
    const held = {
      __typename: 'ShipmentContainerItem',
      id: 'ci-1',
      openingItemId: null,
      openingNumber: '101',
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      quantity: 4,
      isManual: false,
      position: 0,
    };
    renderWorkspace([
      poolMock({ containers: [container({ items: [held] })] }),
      setItemsMock('c-1', [], fired),
    ]);

    const qty = await screen.findByRole('spinbutton', { name: /Quantity of 101 · HG-100 in Box 1/i });
    fireEvent.change(qty, { target: { value: '0' } });

    await waitFor(() => expect(fired).toHaveBeenCalled());
  });
});

describe('two openings staging one product', () => {
  it('shows them as separate rows, each naming its opening', async () => {
    // They are separate quantities to the confirm, so merging them on screen would offer units the
    // shipment would then refuse.
    renderWorkspace([
      poolMock({
        looseItems: [looseRow({ openingNumber: '101' }), looseRow({ openingNumber: '102', stagedQuantity: 3, unplacedQuantity: 3 })],
      }),
    ]);

    const rows = await screen.findAllByText('HG-100 | HINGE');
    expect(rows).toHaveLength(2);
    expect(screen.getByText(/^101 ·/)).toBeInTheDocument();
    expect(screen.getByText(/^102 ·/)).toBeInTheDocument();
  });

  it('places one openings units against that opening', async () => {
    const fired = vi.fn();
    renderWorkspace([
      poolMock({
        looseItems: [looseRow({ openingNumber: '101' }), looseRow({ openingNumber: '102', stagedQuantity: 3, unplacedQuantity: 3 })],
        containers: [container()],
      }),
      setItemsMock('c-1', [looseInput(3, { openingNumber: '102' })], fired),
    ]);

    await screen.findByText(/^102 ·/);
    fireEvent.mouseDown(within(poolRow('HG-100 for 102')).getByRole('combobox'));
    fireEvent.click(await screen.findByRole('option', { name: 'Box 1' }));

    await waitFor(() => expect(fired).toHaveBeenCalled());
  });
});

describe('sameStagedStock', () => {
  const row = { openingNumber: '101', hardwareCategory: 'HINGE', productCode: 'HG-100' };
  const base = {
    id: 'ci-1',
    openingItemId: null,
    quantity: 1,
    isManual: false,
    position: 0,
    ...row,
  };

  it('matches the same product owed to the same opening', () => {
    expect(sameStagedStock(base, row)).toBe(true);
  });

  it('does not merge one openings units into another', () => {
    expect(sameStagedStock({ ...base, openingNumber: '102' }, row)).toBe(false);
  });

  it('keeps unattributed stock separate from an attributed line', () => {
    expect(sameStagedStock({ ...base, openingNumber: null }, row)).toBe(false);
  });

  it('never folds a manual line into staged stock, even when the fields coincide', () => {
    // A manual line is off-inventory, so topping it up with a staged placement would put real stock
    // on a line the arithmetic ignores.
    expect(sameStagedStock({ ...base, isManual: true }, row)).toBe(false);
  });
});

describe('adding a manual line', () => {
  it('appends a free-text off-inventory line flagged is_manual', async () => {
    const fired = vi.fn();
    renderWorkspace([
      poolMock({ containers: [container()] }),
      setItemsMock(
        'c-1',
        [
          {
            openingNumber: null,
            hardwareCategory: 'MISC',
            productCode: 'MAN-1',
            quantity: 2,
            isManual: true,
          },
        ],
        fired,
      ),
    ]);

    fireEvent.click(await screen.findByRole('button', { name: 'Add line' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Product code' }), {
      target: { value: 'MAN-1' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Category' }), { target: { value: 'MISC' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: /Quantity of the manual line/i }), {
      target: { value: '2' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add manual line to Box 1' }));

    await waitFor(() => expect(fired).toHaveBeenCalled());
  });
});
