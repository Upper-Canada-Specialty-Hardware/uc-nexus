import { render, screen } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ReceiveApprovalsPage from '../ReceiveApprovalsPage';
import { GET_RECEIVE_DRAFTS } from '../../../graphql/warehouse';
import { GET_PROJECTS } from '../../../graphql/shared';

// Approving a drafted receive posts a GP receipt and credits inventory, so who may open this queue
// is a real gate rather than navigation tidiness. The role check is on the page (routes in this app
// are authenticated, pages say what they need), which is why it is worth a test of its own.

const mockIdentity = vi.hoisted(() => ({ roles: [] as string[], isAdmin: false }));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    userId: 'u_test',
    roles: mockIdentity.roles,
    hasRole: (role: string) => mockIdentity.roles.includes(role),
    isAdmin: mockIdentity.isAdmin,
    gpBuyerId: null,
    user: null,
  }),
}));

function draft(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ReceiveDraft',
    id: 'draft-1',
    status: 'PENDING_APPROVAL',
    poId: 'po-1',
    poNumber: 'PO-123',
    projectId: 'proj-1',
    warehouseId: 'wh-1',
    createdByUserId: 'u_author',
    createdBy: 'Wendy Warehouse',
    reviewedBy: null,
    reviewedAt: null,
    rejectionReason: null,
    approvalIdempotencyKey: null,
    receiveRecordId: null,
    outboxEntryId: null,
    notes: null,
    totalQuantity: 4,
    createdAt: '2026-08-02T10:00:00Z',
    updatedAt: '2026-08-02T10:00:00Z',
    lineItems: [],
    ...overrides,
  };
}

function draftsMock(status: string, drafts: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: GET_RECEIVE_DRAFTS, variables: { status } },
    result: { data: { receiveDrafts: drafts } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function projectsMock(): MockedResponse {
  return {
    request: { query: GET_PROJECTS },
    result: {
      data: {
        projects: [
          {
            __typename: 'Project',
            id: 'proj-1',
            projectId: 'JOB-1',
            description: 'Riverside Tower',
            client: null,
            jobSiteName: null,
            scheduleFilename: null,
            company: 'TUBC',
            openingCount: 4,
            gpSetupOk: true,
            gpSetupIssues: null,
            gpSetupCheckedAt: null,
          },
        ],
      },
    },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function renderPage(mocks: MockedResponse[] = []) {
  render(
    <MockedProvider mocks={[projectsMock(), ...mocks]}>
      <MemoryRouter>
        <ToastProvider>
          <ReceiveApprovalsPage />
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
}

const SLOW = { timeout: 5000 };

vi.setConfig({ testTimeout: 30_000 });

describe('ReceiveApprovalsPage', () => {
  beforeEach(() => {
    mockIdentity.roles = [];
    mockIdentity.isAdmin = false;
  });

  it('refuses a warehouse user who cannot approve, and points them at their own drafts', async () => {
    mockIdentity.roles = ['Warehouse Staff'];
    renderPage([draftsMock('PENDING_APPROVAL', [draft()])]);

    expect(await screen.findByText(/The Warehouse Manager role is required/, undefined, SLOW)).toBeInTheDocument();
    expect(screen.queryByText('PO-123')).toBeNull();
  });

  it('admits a Warehouse Manager', async () => {
    mockIdentity.roles = ['Warehouse Manager'];
    renderPage([draftsMock('PENDING_APPROVAL', [draft()])]);

    expect(await screen.findByText('PO-123', undefined, SLOW)).toBeInTheDocument();
    expect(screen.getByText('Wendy Warehouse')).toBeInTheDocument();
    expect(screen.getByText('Riverside Tower')).toBeInTheDocument();
  });

  it('admits an admin, because there is no implicit bypass anywhere else either', async () => {
    mockIdentity.isAdmin = true;
    renderPage([draftsMock('PENDING_APPROVAL', [draft()])]);

    expect(await screen.findByText('PO-123', undefined, SLOW)).toBeInTheDocument();
  });

  it('says so when the queue is empty', async () => {
    mockIdentity.roles = ['Warehouse Manager'];
    renderPage([draftsMock('PENDING_APPROVAL', [])]);

    expect(
      await screen.findByText('No receives are waiting for approval.', undefined, SLOW),
    ).toBeInTheDocument();
  });
});
