import { render, screen, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import POOpeningsSection from '../POOpeningsSection';
import { GET_PO_OPENINGS } from '../../../graphql/po';

// Issue #302: a PO carries only fungible (category, product) lines, so this section is the only place
// the buyer can see which doors the order is for while a draft moves toward GP-Registered.

function openingsMock(openings: unknown[]): MockedResponse {
  return {
    request: { query: GET_PO_OPENINGS, variables: { poId: 'po-1' } },
    result: { data: { poOpenings: openings } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

const leafOne = {
  openingNumber: '0019-EX',
  leaf: 1,
  building: 'B1',
  floor: 'F2',
  location: 'Lobby',
  items: [
    { hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 3, __typename: 'POOpeningItem' },
    { hardwareCategory: 'LOCKSET', productCode: 'LK-220', quantity: 1, __typename: 'POOpeningItem' },
  ],
  __typename: 'POOpening',
};

function renderSection(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <POOpeningsSection poId="po-1" />
    </MockedProvider>,
  );
}

it('lists each opening with its leaf and the hardware ordered for it', async () => {
  renderSection([openingsMock([leafOne, { ...leafOne, leaf: 2, items: [leafOne.items[0]] }])]);

  // Gate on the data, not the heading: the heading is up during the loading skeleton too.
  expect(await screen.findByText('3x HG-100, 1x LK-220')).toBeInTheDocument();
  expect(screen.getByText('Openings on this PO')).toBeInTheDocument();
  expect(screen.getAllByText('0019-EX')).toHaveLength(2); // one row per leaf
  expect(screen.getByText('Leaf 1')).toBeInTheDocument();
  expect(screen.getByText('Leaf 2')).toBeInTheDocument();
});

it('says "No leaf" rather than inventing one for a frame', async () => {
  // leaf is genuinely null for a frame or an item imported before #311; printing "Leaf 1" would be a
  // claim about a door leaf that nothing in the schedule supports.
  renderSection([openingsMock([{ ...leafOne, leaf: null }])]);

  expect(await screen.findByText('No leaf')).toBeInTheDocument();
  expect(screen.queryByText(/Leaf \d/)).toBeNull();
});

it('renders nothing at all for a PO with no hardware schedule behind it', async () => {
  // A stock PO has no openings. An empty section with a heading would read as missing data.
  const { container } = renderSection([openingsMock([])]);

  // The heading is up while loading, so wait for it to go rather than sampling one tick in.
  await waitFor(() => expect(screen.queryByText('Openings on this PO')).toBeNull());
  expect(container).toBeEmptyDOMElement();
});

it('keeps the rest of the PO usable when the openings query fails', async () => {
  renderSection([
    {
      request: { query: GET_PO_OPENINGS, variables: { poId: 'po-1' } },
      error: new Error('boom'),
    },
  ]);

  expect(await screen.findByText(/could not load the openings/i)).toBeInTheDocument();
  expect(screen.getByText(/line items above are unaffected/i)).toBeInTheDocument();
});

it('shows the opening location when the schedule has one', async () => {
  renderSection([openingsMock([leafOne])]);
  expect(await screen.findByText('B1 / F2 / Lobby')).toBeInTheDocument();
});

it('omits the location line entirely when the schedule left it blank', async () => {
  renderSection([openingsMock([{ ...leafOne, building: null, floor: null, location: null }])]);

  expect(await screen.findByText('0019-EX')).toBeInTheDocument();
  expect(screen.queryByText('B1 / F2 / Lobby')).toBeNull();
});
