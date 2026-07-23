import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import ManagerAssignPanel from '../ManagerAssignPanel';
import {
  GET_ASSEMBLE_LIST,
  GET_SHOP_ASSEMBLY_MEMBERS,
  ASSIGN_OPENINGS,
} from '../../../graphql/shop-assembly';

vi.setConfig({ testTimeout: 30_000 });

const MEMBERS = [
  { id: 'mgr', firstName: 'Jane', lastName: 'Doe', email: 'jane@x.com', roles: ['Shop Assembly Manager'], imageUrl: '' },
  { id: 'wk', firstName: 'Bob', lastName: 'Lee', email: 'bob@x.com', roles: ['Shop Assembly User'], imageUrl: '' },
];

function opening(overrides: Record<string, unknown> = {}) {
  return {
    id: 'o1',
    shopAssemblyRequestId: null,
    pullRequestId: 'pr1',
    openingId: 'op1',
    pullStatus: 'PULLED',
    assignedToUserId: null,
    assignedTo: null,
    assemblyStatus: 'PENDING',
    completedAt: null,
    openingNumber: '0019-EX',
    building: 'A',
    floor: '2',
    leaf: null,
    items: [
      { id: 'i1', shopAssemblyOpeningId: 'o1', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 2 },
    ],
    ...overrides,
  };
}

const membersMock: MockedResponse = {
  request: { query: GET_SHOP_ASSEMBLY_MEMBERS },
  result: { data: { shopAssemblyMembers: MEMBERS } },
};

function assembleListMock(list: unknown[]): MockedResponse {
  return { request: { query: GET_ASSEMBLE_LIST }, result: { data: { assembleList: list } } };
}

function renderPanel(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <ManagerAssignPanel />
      </ToastProvider>
    </MockedProvider>
  );
}

async function pickMember(name: RegExp) {
  fireEvent.mouseDown(screen.getByRole('combobox'));
  const option = await screen.findByRole('option', { name });
  fireEvent.click(option);
}

it('assigns selected openings to the chosen member with the right variables', async () => {
  let capturedVars: unknown = null;
  const assignMock: MockedResponse = {
    request: {
      query: ASSIGN_OPENINGS,
      variables: { input: { openingIds: ['o1'], assignedToUserId: 'mgr', assignedTo: 'Jane Doe' } },
    },
    result: (vars: unknown) => {
      capturedVars = vars;
      return { data: { assignOpenings: [opening({ assignedToUserId: 'mgr', assignedTo: 'Jane Doe' })] } };
    },
  };

  renderPanel([
    assembleListMock([opening()]),
    membersMock,
    assignMock,
    assembleListMock([opening({ assignedToUserId: 'mgr', assignedTo: 'Jane Doe' })]), // refetch after assign
  ]);

  // The unassigned pulled opening is listed.
  const checkbox = await screen.findByLabelText('select 0019-EX');
  fireEvent.click(checkbox);

  await pickMember(/Jane Doe/);

  const assignBtn = screen.getByRole('button', { name: /Assign 1 to Jane Doe/i });
  fireEvent.click(assignBtn);

  await waitFor(() => expect(capturedVars).toEqual({
    input: { openingIds: ['o1'], assignedToUserId: 'mgr', assignedTo: 'Jane Doe' },
  }));
});

it('keeps the assign button disabled until a member and an opening are both selected', async () => {
  renderPanel([assembleListMock([opening()]), membersMock]);

  // Button starts disabled (nothing selected).
  const btn = await screen.findByRole('button', { name: /Assign/i });
  expect(btn).toBeDisabled();

  // Select an opening only -> still disabled (no member).
  fireEvent.click(await screen.findByLabelText('select 0019-EX'));
  expect(screen.getByRole('button', { name: /Assign/i })).toBeDisabled();

  // Pick a member -> now enabled.
  await pickMember(/Jane Doe/);
  await waitFor(() => expect(screen.getByRole('button', { name: /Assign 1 to Jane Doe/i })).toBeEnabled());
});

it('shows an empty state when there are no unassigned pulled openings', async () => {
  renderPanel([
    assembleListMock([opening({ assignedToUserId: 'wk', assignedTo: 'Bob Lee' })]),
    membersMock,
  ]);

  expect(await screen.findByText(/No unassigned pulled openings available/i)).toBeInTheDocument();
  // The already-assigned opening surfaces in the per-member load summary instead.
  expect(await screen.findByText(/Bob Lee: 1/)).toBeInTheDocument();
});
