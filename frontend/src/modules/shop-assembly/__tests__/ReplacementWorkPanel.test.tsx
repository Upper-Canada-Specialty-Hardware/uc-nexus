import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import ReplacementWorkPanel from '../ReplacementWorkPanel';
import { GET_REPLACEMENT_WORK, INSTALL_REPLACEMENT } from '../../../graphql/shop-assembly';

/**
 * The replacement-install work item (#341). A leaf that was finished with a unit condemned gets its
 * replacement later; fitting it is the one legitimate write to an assembled leaf's hardware after
 * completion, so it is confirm-gated. A leaf that shipped before the replacement arrived is still
 * listed - the hardware is real and must not be silently stranded - but cannot be installed.
 */

vi.setConfig({ testTimeout: 30_000 });

function row(overrides: Record<string, unknown> = {}) {
  return {
    shopAssemblyOpeningItemId: 'sai-1',
    shopAssemblyOpeningId: 'sao-1',
    projectId: 'p1',
    openingNumber: '0019-EX',
    leaf: 1,
    building: 'A',
    floor: '2',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    pendingQuantity: 2,
    assignedToUserId: 'user_1',
    assignedTo: 'Ada',
    openingItemId: 'oi-1',
    openingItemState: 'IN_INVENTORY',
    ...overrides,
  };
}

function workMock(rows: unknown[]): MockedResponse {
  return {
    request: { query: GET_REPLACEMENT_WORK, variables: { assignedToUserId: 'user_1' } },
    result: { data: { replacementWork: rows } },
    maxUsageCount: 5,
  };
}

function installMock(quantity: number): MockedResponse {
  return {
    request: {
      query: INSTALL_REPLACEMENT,
      variables: {
        input: { shopAssemblyOpeningItemId: 'sai-1', quantity },
      },
    },
    result: {
      data: {
        installReplacement: {
          id: 'oi-1',
          openingNumber: '0019-EX',
          leaf: 1,
          state: 'IN_INVENTORY',
          awaitingReplacementQuantity: 0,
          installedHardware: [
            {
              id: 'h1',
              openingItemId: 'oi-1',
              productCode: 'HG-100',
              hardwareCategory: 'HINGE',
              quantity: 4,
            },
          ],
        },
      },
    },
  };
}

function renderPanel(mocks: MockedResponse[], userId: string | null = 'user_1') {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <ReplacementWorkPanel assignedToUserId={userId} />
      </ToastProvider>
    </MockedProvider>
  );
}

it('lists what a finished leaf is still owed', async () => {
  renderPanel([workMock([row()])]);
  expect(await screen.findByText(/Replacement Installs/i)).toBeInTheDocument();
  expect(screen.getByText(/Opening 0019-EX/)).toBeInTheDocument();
  expect(screen.getByText(/2 x HG-100/)).toBeInTheDocument();
});

it('renders nothing when there is no replacement work', async () => {
  const { container } = renderPanel([workMock([])]);
  await waitFor(() => expect(container.querySelector('h6')).toBeNull());
  expect(screen.queryByText(/Replacement Installs/i)).not.toBeInTheDocument();
});

it('confirms before recording the install', async () => {
  renderPanel([workMock([row()]), installMock(2)]);
  fireEvent.click(await screen.findByRole('button', { name: /mark installed/i }));

  expect(await screen.findByText('Record replacement as installed?')).toBeInTheDocument();
  // Nothing has been written yet; the dialog is the decision point.
  expect(screen.getByText(/Only do this once the hardware is physically on the leaf/i)).toBeInTheDocument();
});

it('installs the whole arrived quantity on confirm', async () => {
  renderPanel([workMock([row()]), installMock(2)]);
  fireEvent.click(await screen.findByRole('button', { name: /mark installed/i }));
  // Second "Mark Installed" is the dialog's confirm button.
  const buttons = screen.getAllByRole('button', { name: /mark installed/i });
  fireEvent.click(buttons[buttons.length - 1]);

  expect(await screen.findByText(/Installed 2 x HG-100 on Opening 0019-EX/)).toBeInTheDocument();
});

it('does not offer an install for a leaf that already shipped', async () => {
  renderPanel([workMock([row({ openingItemState: 'SHIPPED_OUT' })])]);
  expect(await screen.findByText(/Leaf already shipped/i)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /mark installed/i })).not.toBeInTheDocument();
  // Still visible, though - that is the whole point of not stranding it.
  expect(screen.getByText(/2 x HG-100/)).toBeInTheDocument();
  expect(screen.getByText(/needs a reallocation or a site shipment/i)).toBeInTheDocument();
});
