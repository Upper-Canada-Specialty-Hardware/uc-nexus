import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ReceiveDecisionsPage from '../ReceiveDecisionsPage';
import { GET_MY_RECEIVE_DECISIONS, DECIDE_RECEIVE_DECISION } from '../../../graphql/po';
import { GET_PROJECTS } from '../../../graphql/shared';

// The keep-or-ship question, answered. The one behaviour worth pinning beyond "the mutation fires"
// is the navigation contract: "Ship out now" hands over to Start a Task, and it must only do that
// once the choice is actually recorded - otherwise the user builds a shipment against a question
// that is still open.

type DecideVars = { input: { decisionId: string; decision: string } };

function decision(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ReceiveDecision',
    id: 'dec-1',
    status: 'PENDING',
    poId: 'po-1',
    poNumber: 'PO-123',
    projectId: 'proj-1',
    receiveRecordId: 'rr-1',
    receiptNumber: 'RCT0000123',
    receivedAt: '2026-08-02T11:00:00Z',
    receivedBy: 'Wendy Warehouse',
    createdAt: '2026-08-02T11:00:00Z',
    lineItems: [
      {
        __typename: 'ReceiveDecisionLine',
        hardwareCategory: 'Hinges',
        productCode: 'HG-100',
        quantityReceived: 3,
      },
    ],
    ...overrides,
  };
}

function decisionsMock(decisions: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: GET_MY_RECEIVE_DECISIONS },
    result: { data: { myReceiveDecisions: decisions } },
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

/** Prints wherever the router ended up, so a navigation assertion is about the URL and not a spy. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function renderPage(extraMocks: MockedResponse[] = [], decisions = [decision()]) {
  render(
    <MockedProvider mocks={[decisionsMock(decisions), projectsMock(), ...extraMocks]}>
      <MemoryRouter initialEntries={['/app/po/decisions']}>
        <ToastProvider>
          <Routes>
            <Route path="/app/po/decisions" element={<ReceiveDecisionsPage />} />
            <Route path="/app/import" element={<div>Start a Task</div>} />
          </Routes>
          <LocationProbe />
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
}

const SLOW = { timeout: 5000 };

vi.setConfig({ testTimeout: 30_000 });

describe('ReceiveDecisionsPage', () => {
  it('shows what landed, against which PO and under which GP receipt', async () => {
    renderPage();

    await screen.findByText('PO-123', undefined, SLOW);
    expect(screen.getByText('Riverside Tower')).toBeInTheDocument();
    expect(screen.getByText('RCT0000123')).toBeInTheDocument();
    expect(screen.getByText(/3 units received by Wendy Warehouse/)).toBeInTheDocument();
    expect(screen.getByText('HG-100')).toBeInTheDocument();
  });

  it('says the GP receipt is pending when the approval was queued', async () => {
    // A queued approval books nothing until the outbox drains, so GP has numbered nothing yet - but
    // the decision is still owed, and printing a dash would read as "nothing arrived".
    renderPage([], [decision({ receiptNumber: null })]);

    await screen.findByText('PO-123', undefined, SLOW);
    expect(screen.getByText(/GP receipt pending/)).toBeInTheDocument();
  });

  it('records "keep in inventory" and goes nowhere', async () => {
    let captured: DecideVars | null = null;
    const decideMock: MockedResponse<Record<string, unknown>, DecideVars> = {
      request: { query: DECIDE_RECEIVE_DECISION, variables: () => true },
      result: (vars) => {
        captured = vars;
        return {
          data: {
            decideReceiveDecision: {
              __typename: 'ReceiveDecision',
              id: 'dec-1',
              status: 'DECIDED',
              decision: 'KEEP_IN_INVENTORY',
              decidedAt: '2026-08-02T12:00:00Z',
            },
          },
        };
      },
    };
    renderPage([decideMock]);
    await screen.findByText('PO-123', undefined, SLOW);

    fireEvent.click(screen.getByRole('button', { name: 'Keep in project inventory' }));

    await vi.waitFor(
      () => expect(captured).toEqual({ input: { decisionId: 'dec-1', decision: 'KEEP_IN_INVENTORY' } }),
      SLOW,
    );
    expect(screen.getByTestId('location')).toHaveTextContent('/app/po/decisions');
  });

  it('records "ship out" and then hands over to Start a Task, scoped to the project', async () => {
    const decideMock: MockedResponse<Record<string, unknown>, DecideVars> = {
      request: { query: DECIDE_RECEIVE_DECISION, variables: () => true },
      result: {
        data: {
          decideReceiveDecision: {
            __typename: 'ReceiveDecision',
            id: 'dec-1',
            status: 'DECIDED',
            decision: 'SHIP_OUT',
            decidedAt: '2026-08-02T12:00:00Z',
          },
        },
      },
    };
    renderPage([decideMock]);
    await screen.findByText('PO-123', undefined, SLOW);

    fireEvent.click(screen.getByRole('button', { name: 'Ship out now' }));

    await screen.findByText('Start a Task', undefined, SLOW);
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/app/import?projectId=proj-1&purpose=shipping&source=latest',
    );
  });

  it('does not navigate when recording the choice failed', async () => {
    // Otherwise the user lands in the shipping wizard believing a decision was recorded that was not.
    const decideMock: MockedResponse = {
      request: { query: DECIDE_RECEIVE_DECISION, variables: () => true },
      error: new Error('someone else answered this'),
    };
    renderPage([decideMock]);
    await screen.findByText('PO-123', undefined, SLOW);

    fireEvent.click(screen.getByRole('button', { name: 'Ship out now' }));

    await screen.findByText(/someone else answered this/, undefined, SLOW);
    expect(screen.getByTestId('location')).toHaveTextContent('/app/po/decisions');
  });

  it('says so when nothing is waiting', async () => {
    renderPage([], []);

    await screen.findByText('No shipments are waiting on a decision.', undefined, SLOW);
  });
});
