import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import ShipmentsList from '../ShipmentsList';
import {
  GET_PACKING_SLIPS,
  MARK_SHIPMENT_DELIVERED,
  MARK_SHIPMENT_PICKED_UP,
} from '../../../graphql/shipping';
import { GET_PROJECTS, GET_WAREHOUSES } from '../../../graphql/shared';

vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

// jsdom cannot run the PDF layout engine, and none of these tests read the document itself.
vi.mock('@react-pdf/renderer', () => ({
  pdf: () => ({ toBlob: () => Promise.resolve(new Blob()) }),
  Document: () => null,
  Page: () => null,
  Text: () => null,
  View: () => null,
  StyleSheet: { create: (s: unknown) => s },
}));

const INFINITE = Number.POSITIVE_INFINITY;

const HEADER = {
  __typename: 'PackingSlip',
  projectId: 'proj-1',
  shippedBy: 'Darren W',
  shippedAt: '2026-07-13T00:00:00Z',
  createdAt: '2026-07-13T00:00:00Z',
  pickupDate: '2026-07-20',
  deliveryDate: '2026-07-21',
  shipperEmail: 'darrenw@ucsh.com',
  shipperPhone: '604 235 2609',
  pickupLocation: 'Coast Meridian\n1120 1725 Coast Meridian Road',
  shipmentMethod: 'Our truck',
  carrierTagBol: 'BOL-8891',
  weightLbs: 420,
  deliveryAddress: '6775 Bell McKinnon Rd., Duncan, BC',
  specialInstructions: null,
  gateNumber: null,
  forkliftOnsite: 'Yes',
  materialComingBack: null,
  siteMaterialIncluded: null,
  constructionTempKeys: null,
  extraFrameAnchors: null,
  contractorContactName: 'Robert Purcell',
  contractorContactPhone: '(250)-715-5238',
  ucshContactName: 'Michael Blackmore',
  ucshContactPhone: null,
  salesOrderNumber: null,
  pickedUpAt: null,
  pickedUpBy: null,
  deliveredAt: null,
  deliveredBy: null,
};

function slip(overrides: Record<string, unknown> = {}) {
  return {
    ...HEADER,
    id: 'ps-1',
    packingSlipNumber: 'PS-0019',
    status: 'SCHEDULED',
    items: [
      {
        __typename: 'PackingSlipItem',
        id: 'psi-1',
        itemType: 'OPENING_ITEM',
        openingNumber: '0019-EX',
        leaf: 1,
        // Snapshotted at confirm (#452), so a reprinted Delivery Request names the same placement
        // the driver's copy did.
        building: 'A',
        floor: '1',
        location: 'Rm 101',
        productCode: null,
        hardwareCategory: null,
        quantity: 1,
      },
      {
        __typename: 'PackingSlipItem',
        id: 'psi-2',
        itemType: 'LOOSE',
        openingNumber: '0019-EX',
        leaf: null,
        building: null,
        floor: null,
        location: null,
        productCode: 'SIL-40002-228',
        hardwareCategory: 'Silentia Folding Screen Caster w/Brake',
        quantity: 37,
      },
    ],
    // How the load was arranged (#451). Every slip read carries it now, so the fixture does too.
    containers: [],
    ...overrides,
  };
}

function packingSlipsMock(slips: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: GET_PACKING_SLIPS, variables: { projectId: null } },
    maxUsageCount: INFINITE,
    result: { data: { packingSlips: slips } },
  };
}

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      projects: [
        {
          __typename: 'Project',
          id: 'proj-1',
          projectId: '23093',
          description: 'Cowichan District Hospital',
          client: null,
          jobSiteName: null,
          openingCount: 2,
          gpSetupOk: true,
          gpSetupCheckedAt: null,
          gpSetupIssues: [],
        },
      ],
    },
  },
};

// The Division Address box on a reprinted Delivery Request comes from the primary warehouse, not
// from the shipment - the list reads it for the same reason the confirm form does.
const warehousesMock: MockedResponse = {
  request: { query: GET_WAREHOUSES, variables: { includeInactive: false } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      warehouses: [
        {
          __typename: 'Warehouse',
          id: 'w-1',
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
      ],
    },
  },
};

function renderList(mocks: MockedResponse[]) {
  render(
    <MockedProvider mocks={[projectsMock, warehousesMock, ...mocks]}>
      <ToastProvider>
        <ShipmentsList />
      </ToastProvider>
    </MockedProvider>,
  );
}

/** The row, then the expansion it owns. */
async function expandRow(packingSlipNumber: string) {
  const toggle = await screen.findByRole('button', { name: `Expand ${packingSlipNumber}` });
  fireEvent.click(toggle);
}

describe('ShipmentsList', () => {
  it('shows where each shipment has got to, with its dates and carrier', async () => {
    renderList([
      packingSlipsMock([
        slip(),
        slip({ id: 'ps-2', packingSlipNumber: 'PS-0020', status: 'PICKED_UP' }),
        slip({ id: 'ps-3', packingSlipNumber: 'PS-0021', status: 'DELIVERED' }),
      ]),
    ]);

    expect(await screen.findByText('PS-0019')).toBeInTheDocument();
    expect(screen.getByText('Scheduled')).toBeInTheDocument();
    expect(screen.getByText('Picked Up')).toBeInTheDocument();
    expect(screen.getByText('Delivered')).toBeInTheDocument();
    expect(screen.getAllByText('BOL-8891')).toHaveLength(3);
    // The all-projects view names the project the shipment belongs to.
    expect(screen.getAllByText('Cowichan District Hospital')).toHaveLength(3);
  });

  it('hides the item lines and the actions until the row is expanded', async () => {
    renderList([packingSlipsMock([slip()])]);
    await screen.findByText('PS-0019');

    expect(screen.queryByText('SIL-40002-228')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delivery Request' })).not.toBeInTheDocument();

    await expandRow('PS-0019');

    expect(await screen.findByText('SIL-40002-228')).toBeInTheDocument();
    // One line per item: the assembled leaf and the loose hardware, both owed to the same opening.
    expect(screen.getAllByText('0019-EX')).toHaveLength(2);
    expect(screen.getByText('Leaf 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delivery Request' })).toBeInTheDocument();
  });

  it('offers only the actions the shipment is up to', async () => {
    renderList([
      packingSlipsMock([
        slip(),
        slip({ id: 'ps-2', packingSlipNumber: 'PS-0020', status: 'PICKED_UP' }),
        slip({ id: 'ps-3', packingSlipNumber: 'PS-0021', status: 'DELIVERED' }),
      ]),
    ]);
    await screen.findByText('PS-0019');

    // Scheduled: still correctable, still to be collected.
    await expandRow('PS-0019');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Mark Picked Up' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mark Delivered' })).not.toBeInTheDocument();

    // Picked up: the paper has left the building, so there is nothing left to edit.
    await expandRow('PS-0020');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Mark Delivered' })).toBeInTheDocument(),
    );
    expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'Mark Picked Up' })).toHaveLength(1);

    // Delivered: the Delivery Request can still be reprinted, and nothing else moves.
    await expandRow('PS-0021');
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Delivery Request' })).toHaveLength(3),
    );
    expect(screen.getAllByRole('button', { name: 'Mark Delivered' })).toHaveLength(1);
  });

  it('moves a scheduled shipment to picked up behind a confirmation', async () => {
    const pickedUp: MockedResponse = {
      request: { query: MARK_SHIPMENT_PICKED_UP, variables: { id: 'ps-1' } },
      result: {
        data: {
          markShipmentPickedUp: {
            ...HEADER,
            id: 'ps-1',
            packingSlipNumber: 'PS-0019',
            status: 'PICKED_UP',
            pickedUpAt: '2026-07-20T15:00:00Z',
            pickedUpBy: 'Darren W',
          },
        },
      },
    };
    renderList([packingSlipsMock([slip()]), pickedUp]);
    await screen.findByText('PS-0019');
    await expandRow('PS-0019');

    fireEvent.click(await screen.findByRole('button', { name: 'Mark Picked Up' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Mark as picked up?')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Mark picked up' }));

    // The mutation answers with the whole slip, so the normalised cache moves the row on its own.
    await waitFor(() => expect(screen.getByText('Picked Up')).toBeInTheDocument());
    expect(screen.queryByText('Scheduled')).not.toBeInTheDocument();
  });

  it('moves a picked-up shipment to delivered', async () => {
    const delivered: MockedResponse = {
      request: { query: MARK_SHIPMENT_DELIVERED, variables: { id: 'ps-1' } },
      result: {
        data: {
          markShipmentDelivered: {
            ...HEADER,
            id: 'ps-1',
            packingSlipNumber: 'PS-0019',
            status: 'DELIVERED',
            pickedUpAt: '2026-07-20T15:00:00Z',
            pickedUpBy: 'Darren W',
            deliveredAt: '2026-07-21T15:00:00Z',
            deliveredBy: 'Darren W',
          },
        },
      },
    };
    renderList([packingSlipsMock([slip({ status: 'PICKED_UP' })]), delivered]);
    await screen.findByText('PS-0019');
    await expandRow('PS-0019');

    fireEvent.click(await screen.findByRole('button', { name: 'Mark Delivered' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Mark delivered' }));

    await waitFor(() => expect(screen.getByText('Delivered')).toBeInTheDocument());
  });

  it('says the load failed rather than that nothing has shipped', async () => {
    // The empty state and a failed query are opposite answers, and only one of them is safe to give
    // somebody reconciling paperwork.
    renderList([
      {
        request: { query: GET_PACKING_SLIPS, variables: { projectId: null } },
        maxUsageCount: INFINITE,
        error: new Error('backend unreachable'),
      },
    ]);

    expect(await screen.findByText(/Error loading shipments/)).toBeInTheDocument();
    expect(screen.queryByText('No shipments match this search.')).not.toBeInTheDocument();
  });

  it('keeps a dirty edit dialog open on a backdrop click', async () => {
    renderList([packingSlipsMock([slip()])]);
    await screen.findByText('PS-0019');
    await expandRow('PS-0019');
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));

    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/Carrier \/ Tag \/ BOL/i), {
      target: { value: 'BOL-9999' },
    });
    // A backdrop click is a mousedown and a click on the dialog's container, which is what MUI
    // matches on ("started and ended on the same element") before it calls onClose with
    // reason: 'backdropClick'. A bare click never reaches that branch.
    const container = document.querySelector('.MuiDialog-container') as Element;
    fireEvent.mouseDown(container);
    fireEvent.click(container);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(within(screen.getByRole('dialog')).getByLabelText(/Carrier \/ Tag \/ BOL/i)).toHaveValue(
      'BOL-9999',
    );

    // Cancel is an explicit dismissal and is never refused.
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    await waitFor(() =>
      expect(screen.queryByText('Edit Delivery Request PS-0019')).not.toBeInTheDocument(),
    );
  });

  it('opens the edit dialog on the stored Delivery Request', async () => {
    renderList([packingSlipsMock([slip()])]);
    await screen.findByText('PS-0019');
    await expandRow('PS-0019');

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Edit Delivery Request PS-0019')).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Carrier \/ Tag \/ BOL/i)).toHaveValue('BOL-8891');
    expect(within(dialog).getByLabelText(/Contractor contact name/i)).toHaveValue('Robert Purcell');
    expect(within(dialog).getByLabelText(/Weight \(lbs\)/i)).toHaveValue(420);
    // The items and the slip number are not editable: changing what shipped is a return.
    expect(within(dialog).queryByLabelText(/Packing Slip Number/i)).not.toBeInTheDocument();
  });
});
