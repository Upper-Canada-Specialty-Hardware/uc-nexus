import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import GpPurchaseOrderDialog from '../GpPurchaseOrderDialog';
import type { PurchaseOrder } from '../index';
import {
  CREATE_PO,
  REGISTER_PO_IN_GP,
  GET_GP_BUYERS,
  GET_GP_COST_CODES,
  GET_GP_VENDORS,
} from '../../../graphql/po';
import { GET_PROJECTS, GET_RELAY_STATUS } from '../../../graphql/shared';

const INFINITE = Number.POSITIVE_INFINITY;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// A stock draft imported with one line (no manufacturer, so no suggestion queries fire).
const stockDraft: PurchaseOrder = {
  id: 'po-1',
  poNumber: null,
  requestNumber: 'REQ-001',
  projectId: null,
  status: 'DRAFT',
  gpCompany: null,
  gpVendorId: null,
  vendorNameSnapshot: 'Ace Hardware Co',
  buyerId: null,
  vendor: null,
  vendorQuoteNumber: null,
  shippingCost: null,
  tariffAmount: null,
  notes: null,
  preferredDeliveryDate: null,
  expectedDeliveryDate: null,
  orderedAt: null,
  createdAt: '2026-07-01T12:00:00Z',
  updatedAt: '2026-07-01T12:00:00Z',
  lineItems: [
    {
      id: 'li-1',
      poId: 'po-1',
      hardwareCategory: 'Hinges',
      productCode: 'HG-100',
      classification: null,
      orderedQuantity: 10,
      receivedQuantity: 0,
      unitCost: 2.5,
      orderAs: 'ML2010',
      manufacturer: null,
      createdAt: '2026-07-01T12:00:00Z',
      updatedAt: '2026-07-01T12:00:00Z',
    },
  ],
  receiveRecords: [],
  documents: [],
  documentData: null,
};

const projectDraft: PurchaseOrder = { ...stockDraft, projectId: 'p1' };

function baseMocks(connected = true): MockedResponse[] {
  return [
    {
      request: { query: GET_RELAY_STATUS },
      result: {
        data: {
          relayStatus: {
            connected,
            company: connected ? 'UCS' : null,
            __typename: 'RelayStatus',
          },
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_PROJECTS },
      result: {
        data: {
          projects: [
            {
              id: 'p1',
              projectId: 'JOB-100',
              description: 'Main St Job',
              client: 'ACME',
              jobSiteName: 'Main St',
              openingCount: 3,
              __typename: 'Project',
            },
          ],
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_GP_BUYERS, variables: { company: 'UCS' } },
      result: { data: { gpBuyers: ['jsmith', 'mdoe'] } },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_GP_VENDORS, variables: { company: 'UCS' } },
      result: {
        data: {
          gpVendors: [
            { vendorId: 'V-ACE', vendorName: 'Ace Hardware Co', vendorClass: null, status: 1, __typename: 'GpVendor' },
            { vendorId: 'V-ALL', vendorName: 'Allegion Hardware', vendorClass: null, status: 1, __typename: 'GpVendor' },
          ],
        },
      },
      maxUsageCount: INFINITE,
    },
  ];
}

function costCodesMock(): MockedResponse {
  return {
    request: { query: GET_GP_COST_CODES, variables: { company: 'UCS', job: 'JOB-100' } },
    result: {
      data: {
        gpCostCodes: [
          { costCode: '310-000', description: 'Hardware', costElement: 3, __typename: 'GpCostCode' },
        ],
      },
    },
    maxUsageCount: INFINITE,
  };
}

function registerData() {
  return {
    registerPoInGp: {
      __typename: 'PurchaseOrder',
      id: 'po-1',
      poNumber: 'PO-2001',
      status: 'GP_REGISTERED',
      gpCompany: 'UCS',
      costCode: '310-000-3',
      gpVendorId: 'V-ACE',
      vendorNameSnapshot: 'Ace Hardware Co',
      vendor: null,
    },
  };
}

function renderDialog(
  props: Partial<React.ComponentProps<typeof GpPurchaseOrderDialog>> = {},
  mocks: MockedResponse[] = baseMocks(),
) {
  const onClose = vi.fn();
  const onSubmitted = vi.fn();
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <GpPurchaseOrderDialog
          open
          onClose={onClose}
          onSubmitted={onSubmitted}
          relayConnected
          {...props}
        />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onClose, onSubmitted };
}

// MUI TextField select: the label is wired to the combobox div via aria-labelledby.
async function pickOption(label: string, optionText: string) {
  await waitFor(() => expect(screen.getByLabelText(label)).not.toHaveAttribute('aria-disabled'));
  fireEvent.mouseDown(screen.getByLabelText(label));
  const listbox = await screen.findByRole('listbox');
  fireEvent.click(within(listbox).getByText(optionText));
  await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
}

async function waitForVendorPreselect() {
  await waitFor(() =>
    expect(screen.getByLabelText('GP Vendor')).toHaveTextContent('Ace Hardware Co'),
  );
}

describe('GpPurchaseOrderDialog', () => {
  it('register mode seeds the draft and pre-selects an exact-match GP vendor as confirmed', async () => {
    renderDialog({ registerPo: stockDraft });

    expect(screen.getByText('Register Purchase Order in GP')).toBeInTheDocument();
    // The draft line item lands in the editable row.
    expect(screen.getByDisplayValue('Hinges')).toBeInTheDocument();
    expect(screen.getByDisplayValue('HG-100')).toBeInTheDocument();
    expect(screen.getByDisplayValue('10')).toBeInTheDocument();
    expect(screen.getByDisplayValue('2.5')).toBeInTheDocument();
    expect(screen.getByDisplayValue('ML2010')).toBeInTheDocument();

    // Company comes from the connected relay; the vendor is matched by exact name.
    await waitFor(() => expect(screen.getByLabelText('GP company')).toHaveValue('UCS'));
    await waitForVendorPreselect();
    expect(
      screen.getByText('Imported as: Ace Hardware Co - confirm the GP vendor'),
    ).toBeInTheDocument();
    // An exact match is confident: no confirmation checkbox.
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('blocks submit until a buyer is picked', async () => {
    const { onSubmitted } = renderDialog({ registerPo: stockDraft });
    await waitForVendorPreselect();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    expect(await screen.findByText('Select a buyer')).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();
  });

  it('requires explicit confirmation of a fuzzy vendor guess before registering', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onSubmitted } = renderDialog(
      { registerPo: { ...stockDraft, vendorNameSnapshot: 'Ace' } },
      [...baseMocks(), registerMock],
    );
    await waitForVendorPreselect(); // fuzzy substring hit pre-fills Ace Hardware Co
    await pickOption('Buyer', 'jsmith');

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(
      await screen.findByText('Confirm the suggested GP vendor before registering'),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(onSubmitted).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole('checkbox', { name: 'This is the correct GP vendor (Ace Hardware Co)' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ input: { gpVendorId: 'V-ACE' } });
  });

  it('registers a project draft with gpCompany, the picked cost code and an idempotency key', async () => {
    const calls: Record<string, unknown>[] = [];
    const registerMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onSubmitted } = renderDialog({ registerPo: projectDraft }, [
      ...baseMocks(),
      costCodesMock(),
      registerMock,
    ]);
    await waitForVendorPreselect();
    await pickOption('Buyer', 'jsmith');

    // A project PO cannot go up without a cost code.
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    expect(
      await screen.findByText('Cost code is required for a project PO'),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);

    await pickOption('Cost code (required)', '310-000 · Hardware');
    fireEvent.change(screen.getByLabelText('Shipping costs (optional)'), {
      target: { value: '25' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({
      input: {
        poId: 'po-1',
        gpVendorId: 'V-ACE',
        gpVendorName: 'Ace Hardware Co',
        buyerId: 'jsmith',
        gpCompany: 'UCS',
        costCode: '310-000-3',
        shippingCost: 25,
        tariffAmount: null,
        idempotencyKey: expect.stringMatching(UUID_RE) as string,
        lineItems: [
          {
            id: 'li-1',
            hardwareCategory: 'Hinges',
            productCode: 'HG-100',
            orderedQuantity: 10,
            unitCost: 2.5,
            classification: null,
            orderAs: 'ML2010',
          },
        ],
      },
    });
  });

  it('create mode submits CREATE_PO with the entered line items and gpCompany', async () => {
    const calls: Record<string, unknown>[] = [];
    const createMock: MockedResponse = {
      request: { query: CREATE_PO, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return {
          data: {
            createPo: {
              __typename: 'PurchaseOrder',
              id: 'po-9',
              poNumber: 'PO-3001',
              requestNumber: 'REQ-009',
              projectId: null,
              status: 'GP_REGISTERED',
              gpCompany: 'UCS',
              gpVendorId: 'V-ALL',
              vendorNameSnapshot: 'Allegion Hardware',
              vendor: null,
              notes: 'rush order',
              createdAt: '2026-07-02T12:00:00Z',
              updatedAt: '2026-07-02T12:00:00Z',
              lineItems: [],
              receiveRecords: [],
              documents: [],
            },
          },
        };
      },
    };
    const { onSubmitted } = renderDialog({}, [...baseMocks(), createMock]);

    expect(screen.getByText('Create Purchase Order in GP')).toBeInTheDocument();
    await pickOption('GP Vendor', 'Allegion Hardware');
    await pickOption('Buyer', 'mdoe');
    fireEvent.change(screen.getByPlaceholderText('e.g. Hinges'), { target: { value: 'Hinges' } });
    fireEvent.change(screen.getByPlaceholderText('e.g. AB123'), { target: { value: 'AB123' } });
    fireEvent.change(screen.getByDisplayValue('1'), { target: { value: '5' } });
    fireEvent.change(screen.getByDisplayValue('0'), { target: { value: '3.5' } });
    fireEvent.change(screen.getByPlaceholderText('e.g. ML2010'), { target: { value: 'ML2010' } });
    fireEvent.change(screen.getByPlaceholderText('Optional notes for this purchase order'), {
      target: { value: 'rush order' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create PO' }));

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({
      input: {
        projectId: null,
        gpVendorId: 'V-ALL',
        gpVendorName: 'Allegion Hardware',
        buyerId: 'mdoe',
        notes: 'rush order',
        costCode: null,
        shippingCost: null,
        tariffAmount: null,
        gpCompany: 'UCS',
        idempotencyKey: expect.stringMatching(UUID_RE) as string,
        lineItems: [
          {
            hardwareCategory: 'Hinges',
            productCode: 'AB123',
            orderedQuantity: 5,
            unitCost: 3.5,
            classification: null,
            orderAs: 'ML2010',
          },
        ],
      },
    });
  });

  it('surfaces the GP failure detail and reuses the same idempotency key on retry', async () => {
    const calls: Record<string, unknown>[] = [];
    const failMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return {
          errors: [
            new GraphQLError('eConnect: vendor on hold', {
              extensions: { code: 'RELAY_CALL_FAILED' },
            }),
          ],
        };
      },
    };
    const okMock: MockedResponse = {
      request: { query: REGISTER_PO_IN_GP, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return { data: registerData() };
      },
    };
    const { onSubmitted } = renderDialog({ registerPo: stockDraft }, [
      ...baseMocks(),
      failMock,
      okMock,
    ]);
    await waitForVendorPreselect();
    await pickOption('Buyer', 'jsmith');

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    // The persistent GP error detail (issue #187), not just a toast; the dialog stays open.
    expect(await screen.findByText('GP could not complete this operation')).toBeInTheDocument();
    expect(screen.getByText('eConnect: vendor on hold')).toBeInTheDocument();
    expect(screen.getByText('RELAY_CALL_FAILED')).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());

    expect(calls).toHaveLength(2);
    const firstKey = (calls[0].input as Record<string, unknown>).idempotencyKey;
    const retryKey = (calls[1].input as Record<string, unknown>).idempotencyKey;
    expect(firstKey).toMatch(UUID_RE);
    expect(retryKey).toBe(firstKey);
  });

  it('blocks submission entirely while the GP relay is down', async () => {
    const { onSubmitted } = renderDialog(
      { registerPo: stockDraft, relayConnected: false },
      baseMocks(false),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Register in GP' }));

    expect(
      await screen.findByText(
        'GP relay not detected on this machine - it must be running to push a PO to GP',
      ),
    ).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();
  });
});
