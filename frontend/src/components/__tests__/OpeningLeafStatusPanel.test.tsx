import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import OpeningLeafStatusPanel from '../OpeningLeafStatusPanel';
import { GET_OPENING_LEAF_STATUS } from '../../graphql/shared';

const SLOW = { timeout: 5000 };

function statusMock(projectId: string | null, openingLeafStatus: unknown[]): MockedResponse {
  return {
    request: { query: GET_OPENING_LEAF_STATUS, variables: { projectId } },
    result: { data: { openingLeafStatus } },
  };
}

function leaf(leafNo: number, status: string) {
  return { __typename: 'OpeningLeafState', leaf: leafNo, status };
}

function row(projectId: string, projectName: string, openingNumber: string, leaves: ReturnType<typeof leaf>[]) {
  return {
    __typename: 'OpeningLeafStatus',
    projectId,
    projectName,
    openingNumber,
    leafCount: leaves.length,
    leaves,
  };
}

describe('OpeningLeafStatusPanel', () => {
  it('frames the summary as "shipped" and shows per-leaf status (shipping, project-scoped)', async () => {
    const mocks = [
      statusMock('p1', [
        row('p1', 'Alpha', '101', [leaf(1, 'SHIPPED_OUT'), leaf(2, 'IN_INVENTORY')]),
      ]),
    ];
    render(
      <MockedProvider mocks={mocks}>
        <OpeningLeafStatusPanel projectId="p1" mode="shipping" />
      </MockedProvider>,
    );

    // shipping mode: only leaf 1 counts toward N.
    await screen.findByText('Opening 101: 1 of 2 leaves shipped', undefined, SLOW);
    expect(screen.getByText('Leaf 1: Shipped out')).toBeInTheDocument();
    expect(screen.getByText('Leaf 2: In inventory')).toBeInTheDocument();
  });

  it('frames the summary as "assembled" - a not-yet-assembled leaf still counts against M', async () => {
    const mocks = [
      statusMock('p1', [
        row('p1', 'Alpha', '102', [leaf(1, 'SHIP_READY'), leaf(2, 'NOT_ASSEMBLED')]),
      ]),
    ];
    render(
      <MockedProvider mocks={mocks}>
        <OpeningLeafStatusPanel projectId="p1" mode="assembly" />
      </MockedProvider>,
    );

    // assembly mode: leaf 1 (ship-ready => has an OpeningItem) counts, leaf 2 does not.
    await screen.findByText('Opening 102: 1 of 2 leaves assembled', undefined, SLOW);
    expect(screen.getByText('Leaf 2: Not assembled')).toBeInTheDocument();
  });

  it('groups by project in the global view', async () => {
    const mocks = [
      statusMock(null, [
        row('p1', 'Alpha', '101', [leaf(1, 'SHIPPED_OUT'), leaf(2, 'SHIPPED_OUT')]),
        row('p2', 'Bravo', '101', [leaf(1, 'NOT_ASSEMBLED'), leaf(2, 'NOT_ASSEMBLED')]),
      ]),
    ];
    render(
      <MockedProvider mocks={mocks}>
        <OpeningLeafStatusPanel mode="assembly" grouped />
      </MockedProvider>,
    );

    // both project subheaders render, disambiguating the shared opening number 101.
    await screen.findByText('Alpha', undefined, SLOW);
    expect(screen.getByText('Bravo')).toBeInTheDocument();
    expect(screen.getByText('Opening 101: 2 of 2 leaves assembled')).toBeInTheDocument();
    expect(screen.getByText('Opening 101: 0 of 2 leaves assembled')).toBeInTheDocument();
  });

  it('keeps same-named projects separate by id in the global view', async () => {
    const mocks = [
      statusMock(null, [
        row('p1', 'Same', '101', [leaf(1, 'SHIPPED_OUT'), leaf(2, 'SHIPPED_OUT')]),
        row('p2', 'Same', '101', [leaf(1, 'NOT_ASSEMBLED'), leaf(2, 'NOT_ASSEMBLED')]),
      ]),
    ];
    render(
      <MockedProvider mocks={mocks}>
        <OpeningLeafStatusPanel mode="assembly" grouped />
      </MockedProvider>,
    );

    // Two projects share the description "Same" but have distinct ids. Grouping by projectId keeps
    // them as two subheaders (two "Same"), not one merged group that re-collides opening 101.
    await screen.findByText('Opening 101: 2 of 2 leaves assembled', undefined, SLOW);
    expect(screen.getByText('Opening 101: 0 of 2 leaves assembled')).toBeInTheDocument();
    expect(screen.getAllByText('Same')).toHaveLength(2);
  });

  it('windows a long project group and reveals the rest on demand', async () => {
    const many = Array.from({ length: 35 }, (_, i) =>
      row('p1', 'Alpha', `${1000 + i}`, [leaf(1, 'NOT_ASSEMBLED'), leaf(2, 'NOT_ASSEMBLED')]),
    );
    const mocks = [statusMock(null, many)];
    render(
      <MockedProvider mocks={mocks}>
        <OpeningLeafStatusPanel mode="assembly" grouped />
      </MockedProvider>,
    );

    await screen.findByText('Opening 1000: 0 of 2 leaves assembled', undefined, SLOW);
    // Row 31 sits behind the tail button.
    expect(screen.queryByText('Opening 1030: 0 of 2 leaves assembled')).toBeNull();
    // The group header still tells the whole story.
    expect(screen.getByText('0 of 70 leaves assembled')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show 5 more of 35' }));
    expect(screen.getByText('Opening 1034: 0 of 2 leaves assembled')).toBeInTheDocument();
  });

  it('search filters across the window', async () => {
    const many = Array.from({ length: 35 }, (_, i) =>
      row('p1', 'Alpha', `${1000 + i}`, [leaf(1, 'NOT_ASSEMBLED'), leaf(2, 'NOT_ASSEMBLED')]),
    );
    const mocks = [statusMock(null, many)];
    render(
      <MockedProvider mocks={mocks}>
        <OpeningLeafStatusPanel mode="assembly" grouped />
      </MockedProvider>,
    );

    await screen.findByText('Opening 1000: 0 of 2 leaves assembled', undefined, SLOW);
    fireEvent.change(screen.getByLabelText('Search opening number'), { target: { value: '1034' } });
    // The match renders even though it sat past the window; the rest drop out.
    expect(screen.getByText('Opening 1034: 0 of 2 leaves assembled')).toBeInTheDocument();
    expect(screen.queryByText('Opening 1000: 0 of 2 leaves assembled')).toBeNull();
  });

  it('renders nothing when there are no pair openings', async () => {
    const mocks = [statusMock('p1', [])];
    const { container } = render(
      <MockedProvider mocks={mocks}>
        <OpeningLeafStatusPanel projectId="p1" mode="shipping" />
      </MockedProvider>,
    );

    // Once the empty result resolves the spinner clears and the panel collapses to null (no chips).
    await waitFor(() => expect(container.querySelector('.MuiCircularProgress-root')).toBeNull(), SLOW);
    expect(container.querySelector('.MuiChip-root')).toBeNull();
  });
});
