import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ReceiveModal from '../ReceiveModal';
import { GET_PO_RECEIVING_DETAILS } from '../../../graphql/warehouse';
import { UPLOAD_PO_DOCUMENT } from '../../../graphql/po';
import { GET_WAREHOUSES } from '../../../graphql/shared';

// #1344: with no active warehouse a draft could never be approved, so the dock is told before it
// counts - and the count cannot be submitted.

function warehousesMock(warehouses: unknown[]): MockedResponse {
  return {
    request: { query: GET_WAREHOUSES, variables: { includeInactive: false } },
    result: { data: { warehouses } },
  };
}

const MAIN = {
  __typename: 'Warehouse',
  id: 'wh-1',
  name: 'Main',
  code: 'MAIN',
  company: 'TUBC',
  address: null,
  city: null,
  province: null,
  postalCode: null,
  isPrimary: true,
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
};

const poDetailsMock: MockedResponse = {
  request: { query: GET_PO_RECEIVING_DETAILS, variables: { poId: 'po-1' } },
  result: {
    data: {
      poReceivingDetails: {
        __typename: 'PurchaseOrder',
        id: 'po-1',
        poNumber: 'PO-123',
        requestNumber: 'RQ-77',
        gpCompany: 'UCSH',
        gpVendorId: 'GPV-1',
        vendorNameSnapshot: 'Acme Hardware',
        notes: null,
        status: 'ORDERED',
        lineItems: [
          {
            __typename: 'POLineItem',
            id: 'li-1',
            poId: 'po-1',
            hardwareCategory: 'Hinges',
            productCode: 'HG-100',
            classification: null,
            orderedQuantity: 10,
            receivedQuantity: 7,
            unitCost: 2.5,
            orderAs: null,
            gpLineOrd: 1,
          },
        ],
        receiveRecords: [],
      },
    },
  },
};

const uploadMock: MockedResponse = {
  request: { query: UPLOAD_PO_DOCUMENT, variables: () => true },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      uploadPoDocument: {
        __typename: 'PODocument',
        id: 'doc-slip-1',
        poId: 'po-1',
        fileName: 'slip.pdf',
        contentType: 'application/pdf',
        fileSize: 12,
        documentType: 'PACKING_SLIP',
        uploadedAt: '2026-08-06T00:00:00Z',
        downloadUrl: 'https://example.test/slip.pdf',
      },
    },
  },
};

function renderModal(warehouses: unknown[]) {
  render(
    <MockedProvider mocks={[warehousesMock(warehouses), uploadMock, poDetailsMock]}>
      <MemoryRouter>
        <ToastProvider>
          <ReceiveModal open onClose={vi.fn()} poIds={['po-1']} />
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
}

function countAndAttach() {
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '3' } });
  for (const input of screen.getAllByLabelText(/^Packing slip for /)) {
    fireEvent.change(input, { target: { files: [new File(['slip'], 'slip.pdf', { type: 'application/pdf' })] } });
  }
}

vi.setConfig({ testTimeout: 60_000 });

describe('ReceiveModal with no active warehouse', () => {
  it('says a warehouse must be added first and keeps submit disabled', async () => {
    renderModal([]);
    await screen.findByText('HG-100', undefined, { timeout: 5000 });

    expect(await screen.findByText(/No active warehouse to receive into/)).toBeInTheDocument();
    countAndAttach();
    expect(screen.getByRole('button', { name: 'Submit for Approval' })).toBeDisabled();
  });

  it('says nothing and allows submit once a warehouse exists', async () => {
    renderModal([MAIN]);
    await screen.findByText('HG-100', undefined, { timeout: 5000 });

    countAndAttach();
    expect(screen.queryByText(/No active warehouse to receive into/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Submit for Approval' })).toBeEnabled();
  });
});
