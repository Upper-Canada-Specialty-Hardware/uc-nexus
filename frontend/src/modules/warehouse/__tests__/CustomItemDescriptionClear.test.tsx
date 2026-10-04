import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ItemForm } from '../CustomItemsPage';
import { UPDATE_CUSTOM_INVENTORY_ITEM } from '../../../graphql/customItems';
import type { CustomInventoryItem, InventoryItemType } from '../../../hooks/useCustomItems';

/**
 * #1485: emptying a catalog item's description has to reach the server as '' - null means "leave it",
 * so the old payload (`trim() || null`) saved "successfully" and the old text stayed.
 */

vi.setConfig({ testTimeout: 60_000 });

const type: InventoryItemType = { id: 't1', code: 'FRAME', name: 'Frame', isActive: true, sortOrder: 0, attributes: [] };
const item: CustomInventoryItem = {
  id: 'i1',
  typeId: 't1',
  hardwareCategory: 'FRAME',
  typeName: 'Frame',
  productCode: 'FR-100',
  description: 'Old description',
  isActive: true,
  values: [],
};

it('sends an emptied description as an empty string so the server clears it', async () => {
  const sent: Record<string, unknown>[] = [];
  const updateMock: MockedResponse = {
    request: { query: UPDATE_CUSTOM_INVENTORY_ITEM, variables: () => true },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: (vars: Record<string, unknown>) => {
      sent.push(vars);
      return {
        data: { updateCustomInventoryItem: { __typename: 'CustomInventoryItem', ...item, description: null, values: [] } },
      };
    },
  };
  const onSaved = vi.fn();
  render(
    <MockedProvider mocks={[updateMock]}>
      <ItemForm type={type} item={item} onClose={() => {}} onSaved={onSaved} />
    </MockedProvider>,
  );

  fireEvent.change(screen.getByLabelText('Description'), { target: { value: '   ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0].description).toBe('');
});
