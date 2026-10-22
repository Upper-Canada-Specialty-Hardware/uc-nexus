import { fireEvent, render, screen } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import CustomItemsPage from '../CustomItemsPage';
import { GET_INVENTORY_ITEM_TYPES } from '../../../graphql/customItems';

/**
 * #1911: a type's code is a PO line's GP item number, which holds 30 characters. The preview shows the
 * code the server will store, so it is cut where the server cuts it.
 */

vi.setConfig({ testTimeout: 60_000 });

const noTypes: MockedResponse = {
  request: { query: GET_INVENTORY_ITEM_TYPES, variables: { activeOnly: false } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { inventoryItemTypes: [] } },
};

it("previews a long name's code cut to gp's 30-character item number", async () => {
  render(
    <MockedProvider mocks={[noTypes]}>
      <ToastProvider>
        <MemoryRouter>
          <CustomItemsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Add Type' }));
  fireEvent.change(await screen.findByLabelText('Name'), {
    target: { value: 'Extra Long Acoustic Door Seal Kits Assorted' },
  });

  expect(screen.getByText('EXTRA_LONG_ACOUSTIC_DOOR_SEAL_')).toBeInTheDocument();
  expect('EXTRA_LONG_ACOUSTIC_DOOR_SEAL_').toHaveLength(30);
});
