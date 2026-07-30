import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import AssembleListPage from '../AssembleListPage';
import { GET_ASSEMBLE_LIST, RECORD_ASSEMBLY_PROGRESS } from '../../../graphql/shop-assembly';

vi.setConfig({ testTimeout: 30_000 });

// The assembly modal is rendered *from a row of the list* (`openings.find(o => o.id ===
// completingId)`), so anything that empties `assembleList` takes the modal down with it. A progress
// save used to evict that root field; it is refetched by name now instead (see refetch.ts, whose
// own test pins the lists).
//
// This walks the real path end to end - list, row, modal, save, refetch - and asserts the dialog and
// everything typed into it survive. The MockedProvider harness resolves the repair fetch too
// promptly to reproduce the transient empty state on its own, so treat this as the integration half
// of the guarantee and `refetch.test.ts` as the half that fails on the offending edit.

vi.mock('@clerk/clerk-react', () => ({
  useUser: () => ({ user: { id: 'u1', fullName: 'Ada Lovelace', publicMetadata: {} } }),
}));

vi.mock('../../../components/OpeningLeafStatusPanel', () => ({ default: () => null }));

function line(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShopAssemblyOpeningItem',
    id: 'i1',
    shopAssemblyOpeningId: 'o1',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    quantity: 4,
    installedQuantity: 0,
    deficientQuantity: 0,
    replacementPendingQuantity: 0,
    ...overrides,
  };
}

function opening(items: ReturnType<typeof line>[]) {
  return {
    __typename: 'ShopAssemblyOpening',
    id: 'o1',
    shopAssemblyRequestId: null,
    pullRequestId: 'pr1',
    openingId: 'op1',
    pullStatus: 'PULLED',
    assignedToUserId: 'u1',
    assignedTo: 'Ada Lovelace',
    assemblyStatus: 'IN_PROGRESS',
    completedAt: null,
    openingNumber: '0019-EX',
    building: 'A',
    floor: '2',
    leaf: 1,
    items,
  };
}

const listMock = (items = [line()]): MockedResponse => ({
  request: { query: GET_ASSEMBLE_LIST },
  result: { data: { assembleList: [opening(items)] } },
});

const saveMock: MockedResponse = {
  request: {
    query: RECORD_ASSEMBLY_PROGRESS,
    variables: {
      input: {
        openingId: 'o1',
        items: [{ shopAssemblyOpeningItemId: 'i1', installedQuantity: 2 }],
      },
    },
  },
  result: { data: { recordAssemblyProgress: opening([line({ installedQuantity: 2 })]) } },
};

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <AssembleListPage />
      </ToastProvider>
    </MockedProvider>
  );
}

it('keeps the assembly modal open across a Save Progress from the Assemble List', async () => {
  // Listed three times: the initial read, the refetch the save fires, and one spare so a repair
  // fetch cannot starve the test of data and mask the very thing being asserted.
  renderPage([listMock(), saveMock, listMock([line({ installedQuantity: 2 })]), listMock()]);

  // The row's actions live inside the accordion, which starts collapsed.
  fireEvent.click(await screen.findByRole('button', { name: /Opening: 0019-EX/i }));
  fireEvent.click(await screen.findByRole('button', { name: /continue assembly/i }));

  const input = await screen.findByLabelText('Installed units: HG-100');
  fireEvent.change(input, { target: { value: '2' } });

  // Local, unsaved modal state. A progress save never sends the put-away location, and the modal
  // seeds it empty on mount - so if the dialog is torn down and rebuilt this is what is lost.
  const aisle = screen.getByLabelText('Aisle') as HTMLInputElement;
  fireEvent.change(aisle, { target: { value: 'A1' } });

  fireEvent.click(screen.getByRole('button', { name: /save progress/i }));

  // The save resolves, the list refetches - and the modal is still on screen, still holding the
  // leaf and everything typed into it. Before the fix the eviction emptied `assembleList`,
  // `completing` became null, and the dialog was unmounted and re-mounted mid-job.
  await waitFor(() =>
    expect(screen.getByLabelText('Installed units: HG-100')).toHaveValue(2)
  );
  expect(screen.getByText(/Shop Hardware Checklist/i)).toBeInTheDocument();
  expect(screen.getByLabelText('Aisle')).toHaveValue('A1');
});
