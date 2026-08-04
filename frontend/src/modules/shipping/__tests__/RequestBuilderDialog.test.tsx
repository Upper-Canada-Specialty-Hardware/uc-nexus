import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import RequestBuilderDialog from '../RequestBuilderDialog';
import { CREATE_SHIPPING_OUT_REQUEST, EDIT_SHIPPING_OUT_REQUEST } from '../../../graphql/shipping';
import { GET_OPENING_ITEMS, GET_PROJECT_INVENTORY_AVAILABILITY } from '../../../graphql/warehouse';

/**
 * Composing a shipping-out request from what the project has rather than from the schedule (#451).
 *
 * The thing being pinned is that a loose line needs no opening. Inventory is keyed by product, not
 * by door, so a request raised off a shelf has nothing to attribute - and the old path forced the
 * composer to invent one, which put a claim on the request the schedule never made.
 */

const PROJECT_ID = 'proj-1';

const availabilityMock: MockedResponse = {
  request: { query: GET_PROJECT_INVENTORY_AVAILABILITY, variables: { projectId: PROJECT_ID } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      projectInventoryAvailability: [
        {
          hardwareCategory: 'HINGE',
          productCode: 'HG-100',
          onHandQuantity: 10,
          deficientQuantity: 0,
          reservedQuantity: 4,
          availableQuantity: 6,
        },
      ],
    },
  },
};

const noLeavesMock: MockedResponse = {
  request: { query: GET_OPENING_ITEMS, variables: { projectId: PROJECT_ID } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { openingItems: [] } },
};

function renderDialog(props: Partial<React.ComponentProps<typeof RequestBuilderDialog>> = {}, mocks: MockedResponse[] = []) {
  const onSaved = vi.fn();
  render(
    <MockedProvider mocks={[availabilityMock, noLeavesMock, ...mocks]}>
      <ToastProvider>
        <RequestBuilderDialog
          open
          onClose={vi.fn()}
          projectId={PROJECT_ID}
          onSaved={onSaved}
          {...props}
        />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onSaved };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

it('offers project inventory with what is free, naming what is spoken for', async () => {
  renderDialog();
  await flush();
  expect(await screen.findByText('HG-100 | HINGE')).toBeInTheDocument();
  expect(screen.getByText('6 free (4 spoken for)')).toBeInTheDocument();
});

it('sends a loose line with no opening at all', async () => {
  const createMock: MockedResponse = {
    request: {
      query: CREATE_SHIPPING_OUT_REQUEST,
      variables: {
        input: {
          projectId: PROJECT_ID,
          requestNumber: 'SOR-9',
          acknowledgeIncompleteLeaves: false,
          items: [
            {
              itemType: 'LOOSE',
              openingNumber: null,
              openingItemId: null,
              leaf: null,
              hardwareCategory: 'HINGE',
              productCode: 'HG-100',
              requestedQuantity: 1,
            },
          ],
        },
      },
    },
    result: {
      data: {
        createShippingOutRequest: {
          id: 'req-1',
          requestNumber: 'SOR-9',
          projectId: PROJECT_ID,
          status: 'PENDING',
          createdBy: 'Shipper',
          createdAt: '2026-08-03T00:00:00',
          integrityNote: null,
          items: [],
        },
      },
    },
  };

  const { onSaved } = renderDialog({}, [createMock]);
  await flush();

  fireEvent.change(screen.getByRole('textbox', { name: /Request number/i }), {
    target: { value: 'SOR-9' },
  });
  fireEvent.click(await screen.findByRole('button', { name: 'Add' }));
  fireEvent.click(screen.getByRole('button', { name: /Create request/i }));

  // The mock only matches if the variables match exactly, so this asserts the null opening.
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
});

it('will not submit an empty request', async () => {
  renderDialog();
  await flush();
  expect(screen.getByRole('button', { name: /Create request/i })).toBeDisabled();
});

it('adds back what the request already holds when working out an edit headroom', async () => {
  // Project availability is net of THIS request's own claim, so an edit that leaves a line alone
  // would otherwise see less headroom than it is actually allowed to keep.
  renderDialog({
    request: {
      id: 'req-1',
      requestNumber: 'SOR-1',
      items: [
        {
          itemType: 'LOOSE',
          openingNumber: null,
          openingItemId: null,
          leaf: null,
          hardwareCategory: 'HINGE',
          productCode: 'HG-100',
          requestedQuantity: 3,
        },
      ],
    },
  });
  await flush();

  expect(screen.getByText('Edit SOR-1')).toBeInTheDocument();
  // 6 free + the 3 this request is holding.
  expect(await screen.findByText('9 free (4 spoken for)')).toBeInTheDocument();
});

/** A request raised from Start a Task: one loose line per opening, all for the same product. */
const SCHEDULE_RAISED = {
  id: 'req-1',
  requestNumber: 'SOR-1',
  items: [
    {
      itemType: 'LOOSE',
      openingNumber: 'A01',
      openingItemId: null,
      leaf: null,
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      requestedQuantity: 2,
    },
    {
      itemType: 'LOOSE',
      openingNumber: 'A02',
      openingItemId: null,
      leaf: null,
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      requestedQuantity: 3,
    },
  ],
};

it('counts every held line of a product, not just the first, when working out headroom', async () => {
  // Availability is already net of BOTH lines. Adding back only the first would cap the box at 8
  // when the request is sitting on 5, and the user could not get back to what they started with.
  renderDialog({ request: SCHEDULE_RAISED });
  await flush();
  expect(await screen.findByText('11 free (4 spoken for)')).toBeInTheDocument();
});

it('reads a product the request already carries under its openings, rather than offering to add it again', async () => {
  // The picker knows nothing about openings, and the seeded lines carry them. Keying the two the
  // same way is what stops Add appending a third, opening-less line for a product already there.
  renderDialog({ request: SCHEDULE_RAISED });
  await flush();

  const qty = await screen.findByRole('spinbutton', { name: /Qty/i });
  expect(qty).toHaveValue(5);
  expect(screen.queryByRole('button', { name: 'Add' })).not.toBeInTheDocument();
});

it('spends a reduction off the newest line, leaving the attributed ones intact', async () => {
  const editMock: MockedResponse = {
    request: {
      query: EDIT_SHIPPING_OUT_REQUEST,
      variables: {
        input: {
          id: 'req-1',
          acknowledgeIncompleteLeaves: false,
          items: [
            {
              itemType: 'LOOSE',
              openingNumber: 'A01',
              openingItemId: null,
              leaf: null,
              hardwareCategory: 'HINGE',
              productCode: 'HG-100',
              requestedQuantity: 2,
            },
            {
              itemType: 'LOOSE',
              openingNumber: 'A02',
              openingItemId: null,
              leaf: null,
              hardwareCategory: 'HINGE',
              productCode: 'HG-100',
              requestedQuantity: 1,
            },
          ],
        },
      },
    },
    result: {
      data: {
        editShippingOutRequest: {
          id: 'req-1',
          requestNumber: 'SOR-1',
          projectId: PROJECT_ID,
          status: 'PENDING',
          createdBy: 'Shipper',
          createdAt: '2026-08-03T00:00:00',
          integrityNote: null,
          items: [],
        },
      },
    },
  };

  const { onSaved } = renderDialog({ request: SCHEDULE_RAISED }, [editMock]);
  await flush();

  // 5 down to 3: the 3 on A02 loses two, and A01 keeps all of its own.
  fireEvent.change(await screen.findByRole('spinbutton', { name: /Qty/i }), { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));

  await waitFor(() => expect(onSaved).toHaveBeenCalled());
});

it('asks before sending a leaf the backend says is short, then re-sends with the acknowledgment', async () => {
  // #341 is warn-and-confirm, not a block. Sending the acknowledgment unconditionally would mean
  // the warning could never reach anyone.
  const refusal = 'These assembled leaves are incomplete: Opening A01 Leaf 1 (1 unit(s) never pulled).';
  const attempt = (acknowledgeIncompleteLeaves: boolean) => ({
    query: CREATE_SHIPPING_OUT_REQUEST,
    variables: {
      input: {
        projectId: PROJECT_ID,
        requestNumber: 'SOR-9',
        acknowledgeIncompleteLeaves,
        items: [
          {
            itemType: 'LOOSE',
            openingNumber: null,
            openingItemId: null,
            leaf: null,
            hardwareCategory: 'HINGE',
            productCode: 'HG-100',
            requestedQuantity: 1,
          },
        ],
      },
    },
  });

  const { onSaved } = renderDialog({}, [
    {
      request: attempt(false),
      result: {
        errors: [
          {
            message: refusal,
            extensions: { code: 'VALIDATION_ERROR', field: 'acknowledge_incomplete_leaves' },
          },
        ],
      },
    } as MockedResponse,
    {
      request: attempt(true),
      result: {
        data: {
          createShippingOutRequest: {
            id: 'req-1',
            requestNumber: 'SOR-9',
            projectId: PROJECT_ID,
            status: 'PENDING',
            createdBy: 'Shipper',
            createdAt: '2026-08-03T00:00:00',
            integrityNote: null,
            items: [],
          },
        },
      },
    },
  ]);
  await flush();

  fireEvent.change(screen.getByRole('textbox', { name: /Request number/i }), {
    target: { value: 'SOR-9' },
  });
  fireEvent.click(await screen.findByRole('button', { name: 'Add' }));
  fireEvent.click(screen.getByRole('button', { name: /Create request/i }));

  // The backend's own words, so the user can see which leaves and why.
  expect(await screen.findByText(refusal)).toBeInTheDocument();
  expect(onSaved).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: /Send them short/i }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
});

it('leaves a refusal nobody can confirm as a plain error', async () => {
  // A leaf already on another request does not become free because someone clicked a button, so
  // this must not offer to re-send.
  const refusal = 'These assembled leaves are already on a live shipping-out request: Opening A01 Leaf 1 (on SOR-2).';
  const { onSaved } = renderDialog({}, [
    {
      request: {
        query: CREATE_SHIPPING_OUT_REQUEST,
        variables: {
          input: {
            projectId: PROJECT_ID,
            requestNumber: 'SOR-9',
            acknowledgeIncompleteLeaves: false,
            items: [
              {
                itemType: 'LOOSE',
                openingNumber: null,
                openingItemId: null,
                leaf: null,
                hardwareCategory: 'HINGE',
                productCode: 'HG-100',
                requestedQuantity: 1,
              },
            ],
          },
        },
      },
      result: {
        errors: [{ message: refusal, extensions: { code: 'VALIDATION_ERROR', field: 'opening_item_id' } }],
      },
    } as MockedResponse,
  ]);
  await flush();

  fireEvent.change(screen.getByRole('textbox', { name: /Request number/i }), {
    target: { value: 'SOR-9' },
  });
  fireEvent.click(await screen.findByRole('button', { name: 'Add' }));
  fireEvent.click(screen.getByRole('button', { name: /Create request/i }));

  expect(await screen.findByText(refusal)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Send them short/i })).not.toBeInTheDocument();
  expect(onSaved).not.toHaveBeenCalled();
});

it('replaces the whole item list on save', async () => {
  const editMock: MockedResponse = {
    request: {
      query: EDIT_SHIPPING_OUT_REQUEST,
      variables: {
        input: {
          id: 'req-1',
          acknowledgeIncompleteLeaves: false,
          items: [
            {
              itemType: 'LOOSE',
              openingNumber: null,
              openingItemId: null,
              leaf: null,
              hardwareCategory: 'HINGE',
              productCode: 'HG-100',
              requestedQuantity: 5,
            },
          ],
        },
      },
    },
    result: {
      data: {
        editShippingOutRequest: {
          id: 'req-1',
          requestNumber: 'SOR-1',
          projectId: PROJECT_ID,
          status: 'PENDING',
          createdBy: 'Shipper',
          createdAt: '2026-08-03T00:00:00',
          integrityNote: null,
          items: [],
        },
      },
    },
  };

  const { onSaved } = renderDialog(
    {
      request: {
        id: 'req-1',
        requestNumber: 'SOR-1',
        items: [
          {
            itemType: 'LOOSE',
            openingNumber: null,
            openingItemId: null,
            leaf: null,
            hardwareCategory: 'HINGE',
            productCode: 'HG-100',
            requestedQuantity: 3,
          },
        ],
      },
    },
    [editMock],
  );
  await flush();

  fireEvent.change(await screen.findByRole('spinbutton', { name: /Qty/i }), { target: { value: '5' } });
  fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));

  await waitFor(() => expect(onSaved).toHaveBeenCalled());
});
