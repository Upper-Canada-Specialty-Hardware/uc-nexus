import { render, screen, fireEvent, configure } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import ReceivesPage from '../ReceivesPage';
import { GET_RECEIVES } from '../../../graphql/warehouse';
import { GET_PROJECTS } from '../../../graphql/shared';

// The page clears its filter on an acting-company switch (#1537); outside the app shell there is no company
// provider, so the acting company is stood in for.
vi.mock('../../../company/ActingCompanyContext', () => ({ useActingCompany: () => ({ company: 'TUBC' }) }));

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

function makeRows(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => {
    const n = start + i;
    return {
      kind: 'RECORD',
      id: `r-${n}`,
      occurredAt: '2026-08-01T10:00:00',
      status: 'APPROVED',
      poId: `po-${n}`,
      poNumber: `PO-${n}`,
      projectId: null,
      projectName: null,
      lineCount: 1,
      totalQuantity: 1,
      countedBy: `counter-${n}`,
      reviewedBy: null,
      rejectionReason: null,
      receiptNumber: null,
      batchNumber: null,
      gpWriteState: null,
      __typename: 'ReceiveRow',
    };
  });
}

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  result: { data: { projects: [] } },
};

describe('ReceivesPage server paging (#1267)', () => {
  it('offers Load more after a full page and appends the next one from the server', async () => {
    const mocks: MockedResponse[] = [
      projectsMock,
      { request: { query: GET_RECEIVES, variables: { limit: 200, offset: 0 } }, result: { data: { receives: makeRows(1, 200) } } },
      { request: { query: GET_RECEIVES, variables: { limit: 200, offset: 200 } }, result: { data: { receives: makeRows(201, 3) } } },
    ];

    render(
      <MockedProvider mocks={mocks}>
        <MemoryRouter>
          <ReceivesPage />
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText(/200 receive\(s\), newest first - older ones exist/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByText('203 receive(s)')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('does not offer Load more when the first page is short', async () => {
    const mocks: MockedResponse[] = [
      projectsMock,
      { request: { query: GET_RECEIVES, variables: { limit: 200, offset: 0 } }, result: { data: { receives: makeRows(1, 3) } } },
    ];

    render(
      <MockedProvider mocks={mocks}>
        <MemoryRouter>
          <ReceivesPage />
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText('3 receive(s)')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });
});

// #1582: a failed read said "No receives match these filters." under its own error.
it('says the receives could not be read instead of "no receives match"', async () => {
  const mocks: MockedResponse[] = [
    projectsMock,
    { request: { query: GET_RECEIVES, variables: { limit: 200, offset: 0 } }, error: new TypeError('Failed to fetch') },
  ];
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter>
        <ReceivesPage />
      </MemoryRouter>
    </MockedProvider>,
  );

  expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument();
  expect(screen.queryByText('No receives match these filters.')).not.toBeInTheDocument();
});

// #1947: an approved draft whose receipt is still on the GP outbox read as plain "Approved", as if booked.
describe('an approval still on the GP outbox', () => {
  // jsdom reports every element as 0x0, and the grid lays its columns out at zero width from a measured
  // container - so no cell reaches the tree. Real dimensions for these tests only, as GpWriteQueuePanel's take.
  const sized = ['clientWidth', 'clientHeight', 'offsetWidth', 'offsetHeight'] as const;
  const original = new Map<string, PropertyDescriptor | undefined>();
  beforeAll(() => {
    for (const prop of sized) {
      original.set(prop, Object.getOwnPropertyDescriptor(HTMLElement.prototype, prop));
      Object.defineProperty(HTMLElement.prototype, prop, {
        configurable: true,
        value: prop.endsWith('Width') ? 1600 : 800,
      });
    }
  });
  afterAll(() => {
    for (const prop of sized) {
      const descriptor = original.get(prop);
      if (descriptor) Object.defineProperty(HTMLElement.prototype, prop, descriptor);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[prop];
    }
  });

  it('says it is waiting on GP, or that GP refused it, and never shows it as booked', async () => {
    const [booked] = makeRows(1, 1);
    const waiting = { ...booked, kind: 'DRAFT', id: 'd-1', poNumber: 'PO-WAIT', gpWriteState: 'WAITING_ON_GP' };
    const refused = { ...booked, kind: 'DRAFT', id: 'd-2', poNumber: 'PO-FAIL', gpWriteState: 'GP_WRITE_FAILED' };
    const mocks: MockedResponse[] = [
      projectsMock,
      {
        request: { query: GET_RECEIVES, variables: { limit: 200, offset: 0 } },
        result: { data: { receives: [waiting, refused, booked] } },
      },
    ];

    render(
      <MockedProvider mocks={mocks}>
        <MemoryRouter>
          <ReceivesPage />
        </MemoryRouter>
      </MockedProvider>,
    );

    const waitingChip = await screen.findByText('Approved - waiting on GP');
    const refusedChip = screen.getByText('Approved - GP write failed');
    expect(waitingChip.closest('.MuiChip-root')).not.toHaveClass('MuiChip-colorSuccess');
    expect(refusedChip.closest('.MuiChip-root')).toHaveClass('MuiChip-colorError');
    // Only the booked record reads as plain Approved.
    expect(screen.getAllByText('Approved')).toHaveLength(1);
  });
});
