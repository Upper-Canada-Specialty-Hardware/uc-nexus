import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import PickPage from '../PickPage';
import { CONFIRM_PICK } from '../../../graphql/warehouse';
import { PICK_CONFIRM_REFETCH_QUERIES } from '../../../graphql/refetch';
import type { PickSheet } from '../pick';

/**
 * #1503: confirmPick is incremental - a short pick leaves the pull open and a second call deducts again.
 * The in-flight guard used to drop the moment the mutation answered, before the sheet refetch had put
 * the confirmed figures in the boxes, so a second confirm could resend the first one's lines.
 */

const SHEET: PickSheet = {
  projectNumber: '80001',
  projectDescription: 'Riverside Tower',
  pullRequest: {
    id: 'pr-1',
    requestNumber: 'PR-0001',
    source: 'SHIPPING_OUT',
    status: 'IN_PROGRESS',
    requestedBy: 'Shipper',
    pickedAt: null,
    pickedBy: null,
  } as unknown as PickSheet['pullRequest'],
  sections: [
    {
      hardwareCategory: 'HINGE',
      productCode: 'HG-100',
      requiredQuantity: 4,
      appliedQuantity: 0,
      remainingQuantity: 4,
      claimableQuantity: 7,
      claimableShortfall: 0,
      openings: [{ openingNumber: '101A', quantity: 4 }],
      locations: [
        {
          inventoryLocationId: 'loc-1',
          warehouseId: 'wh-1',
          warehouseCode: 'MAIN',
          aisle: 'A',
          row: '1',
          bay: '1',
          available: 7,
          receivedAt: '2024-01-01T00:00:00Z',
          // The saved draft seeds the box, so a short pick of 2 is ready to confirm.
          draftQuantity: 2,
          appliedQuantity: 0,
          orderAs: null,
          poNumber: null,
        },
      ],
    },
  ],
};

interface ConfirmOptions {
  refetchQueries?: unknown;
  awaitRefetchQueries?: boolean;
  update?: (cache: unknown, result: { data?: unknown }) => void;
  onError?: (e: Error) => void;
}

const apollo = vi.hoisted(() => ({
  confirm: vi.fn(),
  confirmOptions: {} as ConfirmOptions,
  confirmDoc: null as DocumentNode | null,
}));
const showToast = vi.fn();

vi.mock('@apollo/client/react', () => ({
  useQuery: () => ({ data: { pullPickSheet: SHEET }, loading: false, error: undefined, refetch: vi.fn() }),
  useMutation: (doc: DocumentNode, options: ConfirmOptions) => {
    if (doc === apollo.confirmDoc) {
      apollo.confirmOptions = options;
      return [apollo.confirm, { loading: false }];
    }
    return [vi.fn(), { loading: false }];
  },
}));
vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('../../../hooks/useIdentity', () => ({ useIdentity: () => ({ displayName: 'Picker' }) }));

const FAKE_CACHE = { evict: vi.fn(), gc: vi.fn() };

beforeEach(() => {
  apollo.confirmDoc = CONFIRM_PICK;
  apollo.confirm.mockReset();
  showToast.mockReset();
});

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/app/warehouse/pull-requests/pr-1/pick']}>
      <Routes>
        <Route path="/app/warehouse/pull-requests/:id/pick" element={<PickPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function confirmShortPick() {
  fireEvent.click(screen.getByRole('button', { name: 'Confirm short pick' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm short pick' }));
}

it('waits for the sheet refetch, keeping the refetch list as refetch.ts has it', () => {
  renderPage();
  expect(apollo.confirmOptions.awaitRefetchQueries).toBe(true);
  expect(apollo.confirmOptions.refetchQueries).toBe(PICK_CONFIRM_REFETCH_QUERIES);
});

it('holds the guard when the confirm applied but the sheet refresh failed', () => {
  renderPage();
  confirmShortPick();
  expect(apollo.confirm).toHaveBeenCalledTimes(1);

  // The server applied the pick (update ran with its payload); then the awaited refetch failed.
  apollo.confirmOptions.update?.(FAKE_CACHE, { data: { confirmPick: { outcome: 'SHORT', appliedQuantity: 2 } } });
  apollo.confirmOptions.onError?.(new Error('Failed to fetch'));

  confirmShortPick();
  expect(apollo.confirm).toHaveBeenCalledTimes(1);
  expect(showToast).toHaveBeenLastCalledWith(expect.stringMatching(/reload it before confirming again/i), 'warning');
});

it('lets the confirm be sent again when the confirm itself failed', () => {
  renderPage();
  confirmShortPick();
  apollo.confirmOptions.onError?.(new Error('Contention'));

  confirmShortPick();
  expect(apollo.confirm).toHaveBeenCalledTimes(2);
});
