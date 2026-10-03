import { render, screen, fireEvent, configure } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import ReceivesPage from '../ReceivesPage';
import { GET_RECEIVES } from '../../../graphql/warehouse';
import { GET_PROJECTS } from '../../../graphql/shared';

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
