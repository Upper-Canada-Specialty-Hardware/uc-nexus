import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import OpeningStatusTab from '../OpeningStatusTab';
import { GET_ADMIN_OPENING_STATUSES, GET_ADMIN_OPENING_DEEP_DIVE } from '../../../graphql/admin';
import { GET_PROJECTS } from '../../../graphql/shared';

const SLOW = { timeout: 5000 };

function projectsMock(): MockedResponse {
  return {
    request: { query: GET_PROJECTS },
    result: {
      data: {
        projects: [
          {
            __typename: 'Project',
            id: 'p1',
            projectId: 'JOB-1',
            description: 'Alpha Tower',
            client: null,
            jobSiteName: null,
            openingCount: 2,
            gpSetupOk: true,
            gpSetupCheckedAt: null,
            gpSetupIssues: null,
          },
        ],
      },
    },
  };
}

function leaf(leafNo: number, status: string) {
  return { __typename: 'OpeningLeafState', leaf: leafNo, status };
}

function statusRow(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'AdminOpeningStatus',
    openingNumber: '101',
    building: 'A',
    floor: '2',
    location: 'Stair',
    leafCount: 2,
    stage: 'ORDERING',
    owedUnits: 12,
    shippedUnits: 0,
    stagedUnits: 0,
    assembledUnits: 0,
    pulledUnits: 0,
    shippedLooseUnits: 0,
    pulledForShippingUnits: 0,
    orderedUnits: 8,
    poDraftedUnits: 2,
    notPurchasedUnits: 2,
    leaves: [leaf(1, 'NOT_ASSEMBLED'), leaf(2, 'NOT_ASSEMBLED')],
    ...overrides,
  };
}

function statusesMock(rows: unknown[]): MockedResponse {
  return {
    request: { query: GET_ADMIN_OPENING_STATUSES, variables: { projectId: 'p1' } },
    result: { data: { adminOpeningStatuses: rows } },
  };
}

function line(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'AdminOpeningLine',
    leaf: 1,
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    owedQuantity: 4,
    shippedOnLeaf: 0,
    shippedLoose: 0,
    staged: 0,
    pulledForShipping: 0,
    assembledInInventory: 0,
    pulledForAssembly: 0,
    ordered: 4,
    poDrafted: 0,
    notPurchased: 0,
    poLines: [
      {
        __typename: 'AdminPoLineRef',
        poNumber: 'PO0001',
        status: 'GP_REGISTERED',
        orderedQuantity: 100,
        receivedQuantity: 40,
      },
    ],
    ...overrides,
  };
}

function deepDiveMock(overrides: Record<string, unknown> = {}): MockedResponse {
  return {
    request: {
      query: GET_ADMIN_OPENING_DEEP_DIVE,
      variables: { projectId: 'p1', openingNumber: '101' },
    },
    result: {
      data: {
        adminOpeningDeepDive: {
          __typename: 'AdminOpeningDeepDive',
          openingNumber: '101',
          leafCount: 2,
          leaves: [leaf(1, 'NOT_ASSEMBLED'), leaf(2, 'NOT_ASSEMBLED')],
          leafClaims: [],
          lines: [line()],
          loose: [],
          ...overrides,
        },
      },
    },
  };
}

async function pickProject() {
  const picker = await screen.findByLabelText('Project', undefined, SLOW);
  fireEvent.mouseDown(picker);
  fireEvent.change(picker, { target: { value: 'Alpha' } });
  fireEvent.click(await screen.findByText('Alpha Tower', undefined, SLOW));
}

describe('OpeningStatusTab', () => {
  it('loads nothing until a project is picked', async () => {
    render(
      <MockedProvider mocks={[projectsMock(), statusesMock([statusRow()])]}>
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await screen.findByText('Pick a project to see where its openings have got to.', undefined, SLOW);
    expect(screen.queryByText('101')).not.toBeInTheDocument();
  });

  it('shows a stage chip and the track chips once a project is picked', async () => {
    render(
      <MockedProvider mocks={[projectsMock(), statusesMock([statusRow()])]}>
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await pickProject();

    await screen.findByText('101', undefined, SLOW);
    expect(screen.getByText('Ordering')).toBeInTheDocument();
    // 12 owed, 2 unpurchased and 2 drafted => 8 of them are actually bought.
    expect(screen.getByText('Procured 8/12')).toBeInTheDocument();
    expect(screen.getByText('Leaf 1: Not assembled')).toBeInTheDocument();
    expect(screen.getByText('Leaf 2: Not assembled')).toBeInTheDocument();
    expect(screen.getByText('A / 2 / Stair')).toBeInTheDocument();
  });

  it('counts shipped-on-leaf and shipped-loose units into one Shipped chip', async () => {
    const row = statusRow({
      stage: 'COMPLETE',
      shippedUnits: 6,
      shippedLooseUnits: 4,
      orderedUnits: 0,
      poDraftedUnits: 0,
      notPurchasedUnits: 0,
      leaves: [leaf(1, 'SHIPPED_OUT'), leaf(2, 'SHIPPED_OUT')],
    });
    render(
      <MockedProvider mocks={[projectsMock(), statusesMock([row])]}>
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await pickProject();

    await screen.findByText('Complete', undefined, SLOW);
    expect(screen.getByText('Shipped 10')).toBeInTheDocument();
    expect(screen.getByText('Procured 12/12')).toBeInTheDocument();
  });

  it('fetches the per-hardware detail only when a row is expanded', async () => {
    render(
      <MockedProvider mocks={[projectsMock(), statusesMock([statusRow()]), deepDiveMock()]}>
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await pickProject();
    await screen.findByText('101', undefined, SLOW);

    // Nothing from the detail query is on screen before the row is opened.
    expect(screen.queryByText('HG-100')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('101'));

    await screen.findByText('HG-100', undefined, SLOW);
    expect(screen.getByText('On order 4')).toBeInTheDocument();
    expect(screen.getByText('PO0001')).toBeInTheDocument();
    expect(screen.getByText('line 40/100 received')).toBeInTheDocument();
  });

  it('renders one bucket chip per non-zero state and none for the rest', async () => {
    const dive = deepDiveMock({
      lines: [
        line({ ordered: 1, pulledForAssembly: 1, assembledInInventory: 1, shippedLoose: 1, owedQuantity: 4 }),
      ],
    });
    render(
      <MockedProvider mocks={[projectsMock(), statusesMock([statusRow()]), dive]}>
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await pickProject();
    await screen.findByText('101', undefined, SLOW);
    fireEvent.click(screen.getByText('101'));

    await screen.findByText('On order 1', undefined, SLOW);
    expect(screen.getByText('Pulled for assembly 1')).toBeInTheDocument();
    expect(screen.getByText('Assembled 1')).toBeInTheDocument();
    expect(screen.getByText('Shipped loose 1')).toBeInTheDocument();
    // Buckets holding nothing are not rendered at all.
    expect(screen.queryByText(/^Staged/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Not purchased/)).not.toBeInTheDocument();
  });

  it('names the live shipping request holding a leaf', async () => {
    const dive = deepDiveMock({
      leaves: [leaf(1, 'SHIP_READY'), leaf(2, 'NOT_ASSEMBLED')],
      leafClaims: [{ __typename: 'AdminLeafClaim', leaf: 1, requestNumber: 'SOR-9' }],
    });
    render(
      <MockedProvider mocks={[projectsMock(), statusesMock([statusRow()]), dive]}>
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await pickProject();
    await screen.findByText('101', undefined, SLOW);
    fireEvent.click(screen.getByText('101'));

    await screen.findByText('Held by SOR-9', undefined, SLOW);
  });

  it('surfaces loose units no leaf could account for', async () => {
    const dive = deepDiveMock({
      loose: [
        {
          __typename: 'AdminLooseLine',
          hardwareCategory: 'LOCK',
          productCode: 'LK-9',
          pulledForShipping: 0,
          shippedLoose: 4,
        },
      ],
    });
    render(
      <MockedProvider mocks={[projectsMock(), statusesMock([statusRow()]), dive]}>
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await pickProject();
    await screen.findByText('101', undefined, SLOW);
    fireEvent.click(screen.getByText('101'));

    await screen.findByText('Loose units no leaf accounts for', undefined, SLOW);
    expect(screen.getByText('LK-9')).toBeInTheDocument();
  });

  it('filters by opening number', async () => {
    render(
      <MockedProvider
        mocks={[
          projectsMock(),
          statusesMock([statusRow(), statusRow({ openingNumber: '202', building: 'B' })]),
        ]}
      >
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await pickProject();
    await screen.findByText('2 openings', undefined, SLOW);

    fireEvent.change(screen.getByPlaceholderText('Search opening number…'), {
      target: { value: '202' },
    });

    await waitFor(() => expect(screen.queryByText('101')).not.toBeInTheDocument(), SLOW);
    expect(screen.getByText('202')).toBeInTheDocument();
  });

  it('says so when a project has no openings', async () => {
    render(
      <MockedProvider mocks={[projectsMock(), statusesMock([])]}>
        <OpeningStatusTab />
      </MockedProvider>,
    );

    await pickProject();

    await screen.findByText('This project has no openings yet.', undefined, SLOW);
  });
});
