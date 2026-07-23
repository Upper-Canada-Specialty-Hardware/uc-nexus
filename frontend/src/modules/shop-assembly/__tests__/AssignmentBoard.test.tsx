import { render, screen, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import AssignmentBoard from '../AssignmentBoard';
import { GET_ASSEMBLE_LIST, GET_SHOP_ASSEMBLY_MEMBERS } from '../../../graphql/shop-assembly';

vi.setConfig({ testTimeout: 30_000 });

// Role is driven per-test through this mutable list (vi.mock factory may read `mock`-prefixed vars).
let mockRoles: string[] = [];
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Me',
    userId: 'me',
    roles: mockRoles,
    hasRole: (r: string) => mockRoles.includes(r),
    isAdmin: false,
    gpBuyerId: null,
    user: null,
  }),
}));

const emptyListMock: MockedResponse = {
  request: { query: GET_ASSEMBLE_LIST },
  result: { data: { assembleList: [] } },
};
const membersMock: MockedResponse = {
  request: { query: GET_SHOP_ASSEMBLY_MEMBERS },
  result: { data: { shopAssemblyMembers: [] } },
};

function renderBoard(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <AssignmentBoard />
      </ToastProvider>
    </MockedProvider>
  );
}

it('shows the manager assign panel for a Shop Assembly Manager', async () => {
  mockRoles = ['Shop Assembly Manager'];
  renderBoard([emptyListMock, membersMock]);
  expect(await screen.findByText('Assign to Team Member')).toBeInTheDocument();
});

it('hides the manager assign panel for a plain Shop Assembly User', async () => {
  mockRoles = ['Shop Assembly User'];
  renderBoard([emptyListMock]);
  // The board itself renders (its heading), but the manager panel does not.
  expect(await screen.findByText('Opening Assignment Board')).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText('Assign to Team Member')).not.toBeInTheDocument());
});
