import { render, screen, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import DeficientItemsReview from '../DeficientItemsReview';
import { GET_DEFICIENT_ITEMS } from '../../../graphql/warehouse';

vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

const base = {
  __typename: 'DeficientItemRow',
  stockItemId: null,
  inventoryLocationId: null,
  projectId: null,
  projectNumber: null,
  projectDescription: null,
  hardwareCategory: 'HINGE',
  deficientQuantity: 2,
  aisle: null,
  row: null,
  bay: null,
};

const itemsMock: MockedResponse = {
  request: { query: GET_DEFICIENT_ITEMS, variables: { source: null } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      deficientItems: [
        {
          ...base,
          source: 'PROJECT_INVENTORY',
          inventoryLocationId: 'il-1',
          // An archived project: the server names it, so the column does too (#1252).
          projectId: 'proj-gone',
          projectNumber: '19001',
          projectDescription: 'Old Library',
          productCode: 'HG-100',
        },
        { ...base, source: 'STOCK_POOL', stockItemId: 'si-1', productCode: 'HG-200' },
      ],
    },
  },
};

it('names the project a deficient row belongs to and leaves a stock-pool row blank (#1252)', async () => {
  render(
    <MockedProvider mocks={[itemsMock]}>
      <MemoryRouter>
        <DeficientItemsReview />
      </MemoryRouter>
    </MockedProvider>,
  );

  expect(await screen.findByText('Old Library')).toBeInTheDocument();
  expect(screen.getByRole('columnheader', { name: 'Project' })).toBeInTheDocument();
  expect(screen.getByText('HG-200')).toBeInTheDocument();
  expect(screen.getAllByText('Old Library')).toHaveLength(1);
});
