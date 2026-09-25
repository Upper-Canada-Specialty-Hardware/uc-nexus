import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import ViewPOsButton from '../ViewPOsButton';
import { GET_PROJECT_PRODUCT_PO_LINES } from '../../../graphql/import';

function poLine(overrides: Record<string, unknown>) {
  return {
    __typename: 'ProductPOLine',
    poId: 'po-1',
    poNumber: 'PO-1',
    requestNumber: null,
    status: 'GP_REGISTERED',
    orderedQuantity: 0,
    receivedQuantity: 0,
    ...overrides,
  };
}

const MOCKS: MockedResponse[] = [
  {
    request: {
      query: GET_PROJECT_PRODUCT_PO_LINES,
      variables: { projectId: 'proj-1', hardwareCategory: 'HINGE', productCode: 'H-1' },
    },
    result: {
      data: {
        projectProductPoLines: [
          poLine({ poId: 'po-a', poNumber: 'PO-2001', orderedQuantity: 4 }),
          poLine({ poId: 'po-b', poNumber: 'PO-2002', status: 'CLOSED', orderedQuantity: 10, receivedQuantity: 7 }),
        ],
      },
    },
  },
];

function renderButton(count: number, figure: 'ordered' | 'onOrder' = 'ordered') {
  render(
    <MockedProvider mocks={MOCKS}>
      <ViewPOsButton projectId="proj-1" hardwareCategory="HINGE" productCode="H-1" figure={figure} count={count} />
    </MockedProvider>,
  );
}

it('shows nothing when the figure is 0', () => {
  renderButton(0);
  expect(screen.queryByRole('button')).toBeNull();
});

it('lists the POs behind the figure, each a new-tab link into the PO table', async () => {
  renderButton(11);
  fireEvent.click(screen.getByRole('button', { name: /view pos/i }));

  const link = await screen.findByRole('link', { name: 'PO-2001' });
  expect(link).toHaveAttribute('href', '/app/po?po=po-a');
  expect(link).toHaveAttribute('target', '_blank');
  expect(screen.getByRole('link', { name: 'PO-2002' })).toHaveAttribute('href', '/app/po?po=po-b');

  // Ordered: 4 on the open PO, 7 received on the closed one - the list sums to the figure.
  const popover = screen.getByRole('presentation');
  expect(within(popover).getByText('Total').nextSibling).toHaveTextContent('11');
});

it('lists only open POs behind On Order', async () => {
  renderButton(4, 'onOrder');
  fireEvent.click(screen.getByRole('button', { name: /view pos/i }));

  expect(await screen.findByRole('link', { name: 'PO-2001' })).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'PO-2002' })).toBeNull();
});
