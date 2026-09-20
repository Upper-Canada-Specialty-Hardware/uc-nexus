import { render, screen, configure, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../Toast';
import GpWriteQueuePanel from '../GpWriteQueuePanel';
import { GET_GP_OUTBOX } from '../../graphql/shared';

// A DataGrid assertion in jsdom is slow, and the grid here is deliberately un-virtualized.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

// jsdom reports every element as 0x0, and MUI's DataGrid sizes itself from a measured container: at
// zero width it lays every column out at `width: 0px`, so neither the headers nor the row actions
// reach the accessibility tree. Give the grid real dimensions so the assertions are about the
// component - the same measure the Relay Installs test file takes.
beforeAll(() => {
  for (const [prop, value] of [
    ['clientWidth', 1200],
    ['clientHeight', 800],
    ['offsetWidth', 1200],
    ['offsetHeight', 800],
  ] as const) {
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, value });
  }
});

const INFINITE = Number.POSITIVE_INFINITY;

function entry(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'GpOutboxEntry',
    id: 'queued-1',
    label: 'PO registration PO-REQ-001',
    op: 'create_po',
    company: 'TUBC',
    status: 'PENDING',
    attempts: 1,
    nextAttemptAt: '2026-07-01T12:05:00Z',
    lastError: null,
    failureKind: null,
    entityKey: 'po:po-1',
    createdAt: '2026-07-01T12:00:00Z',
    ...overrides,
  };
}

/** Every variable set the panel asked the list with, so a test can say what it narrowed to. */
const asked: Record<string, unknown>[] = [];

beforeEach(() => {
  asked.length = 0;
});

function mocks(entries: Record<string, unknown>[]): MockedResponse[] {
  return [
    {
      request: {
        query: GET_GP_OUTBOX,
        variables: (v: Record<string, unknown>) => {
          asked.push(v);
          return true;
        },
      },
      result: { data: { gpOutbox: entries } },
      maxUsageCount: INFINITE,
    },
  ];
}

function renderPanel(
  props: { ops?: string[]; heading?: string; compact?: boolean },
  entries: Record<string, unknown>[] = [entry()],
) {
  render(
    <MockedProvider mocks={mocks(entries)}>
      <ToastProvider>
        {/* A wrapper the empty case can be asserted on: the panel renders nothing there, so there
            is no element of its own to look for. */}
        <div data-testid="panel-mount">
          <GpWriteQueuePanel {...props} />
        </div>
      </ToastProvider>
    </MockedProvider>,
  );
}

// The admin queue is unchanged by #754: every column, every write, and its own heading.
it('gives the admin queue every column', async () => {
  renderPanel({});

  expect(await screen.findByText('GP write queue')).toBeInTheDocument();
  expect(await screen.findByRole('columnheader', { name: 'Company' })).toBeInTheDocument();
  expect(screen.getByRole('columnheader', { name: 'Failure' })).toBeInTheDocument();
  expect(screen.getByRole('columnheader', { name: 'Queued at' })).toBeInTheDocument();
});

it('asks for every write when it is not narrowed to an operation', async () => {
  renderPanel({});

  await screen.findByText('GP write queue');
  expect(asked).toContainEqual({});
});

// Inside a module the company is the reader's own and the queued-at time is forensic, so the
// compact mounting drops them and keeps what says whether the write is moving.
it('drops the columns a module does not need', async () => {
  renderPanel({ ops: ['create_po'], compact: true, heading: 'Held PO registrations' });

  expect(await screen.findByText('Held PO registrations')).toBeInTheDocument();
  expect(await screen.findByRole('columnheader', { name: 'Write' })).toBeInTheDocument();
  for (const name of ['Status', 'Tries', 'Next attempt', 'Last error', 'Actions']) {
    expect(screen.getByRole('columnheader', { name })).toBeInTheDocument();
  }
  for (const name of ['Company', 'Failure', 'Queued at']) {
    expect(screen.queryByRole('columnheader', { name })).toBeNull();
  }
});

it('narrows the list to the operation it was pointed at', async () => {
  renderPanel({ ops: ['create_receipt'], compact: true, heading: 'Held GP receive entries' });

  await screen.findByText('Held GP receive entries');
  expect(asked).toContainEqual({ ops: ['create_receipt'] });
});

// A module page says nothing at all while nothing is held - the normal state, and the reason the
// mounting can be unconditional.
it('renders nothing inside a module while no write is held', async () => {
  renderPanel({ ops: ['create_po'], compact: true, heading: 'Held PO registrations' }, []);

  await waitFor(() => expect(asked.length).toBeGreaterThan(0));
  await waitFor(() => expect(screen.getByTestId('panel-mount')).toBeEmptyDOMElement());
});

// The admin came looking for the queue, so an empty one still answers.
it('keeps the admin queue on screen when it is empty', async () => {
  renderPanel({}, []);

  expect(await screen.findByText('GP write queue')).toBeInTheDocument();
});

// An `ambiguous` write may already have posted in GP, and retrying it can duplicate a receipt or
// burn a second PO number. That warning survived the move out of the admin module.
it('warns that an ambiguous write may already have posted before retrying it', async () => {
  renderPanel({ compact: true, heading: 'Held PO registrations' }, [
    entry({ status: 'FAILED', failureKind: 'ambiguous', lastError: 'Relay timed out' }),
  ]);

  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));

  expect(await screen.findByText(/may already have posted in GP/)).toBeInTheDocument();
});
