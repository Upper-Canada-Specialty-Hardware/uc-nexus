import { render, screen } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { ToastProvider } from '../../../components/Toast';
import CustomItemsPage from '../CustomItemsPage';
import CustomItemPicker from '../../po/CustomItemPicker';
import { GET_INVENTORY_ITEM_TYPES } from '../../../graphql/customItems';

/**
 * #1341: a failed catalog read says so. Shown as an empty catalog it invited someone to re-create the
 * types, and the conflicts that followed explained nothing.
 */

vi.setConfig({ testTimeout: 60_000 });

const failedTypes = (activeOnly: boolean): MockedResponse => ({
  request: { query: GET_INVENTORY_ITEM_TYPES, variables: { activeOnly } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  error: new Error('backend unreachable'),
});

function wrap(ui: ReactNode, mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

it('the custom items page says the catalog failed to load instead of showing it empty', async () => {
  wrap(<CustomItemsPage />, [failedTypes(false)]);

  expect(await screen.findByText(/Couldn't load the custom items catalog/)).toBeInTheDocument();
  expect(screen.queryByText('No inventory item types yet. Add one to get started.')).not.toBeInTheDocument();
});

it('the picker says the catalog failed to load instead of sending the user to add types', async () => {
  wrap(<CustomItemPicker open onClose={() => {}} onPick={() => {}} />, [failedTypes(true)]);

  expect(await screen.findByText(/Couldn't load the catalog/)).toBeInTheDocument();
  expect(screen.queryByText(/No active item types/)).not.toBeInTheDocument();
});
