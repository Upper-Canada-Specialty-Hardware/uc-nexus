import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import PickPage from '../PickPage';
import { CONFIRM_PICK } from '../../../graphql/warehouse';
import type { PickSheet } from '../pick';

/**
 * #1576: a refused confirm used to leave the sheet showing the figures that were refused (a shelf emptied by
 * someone else still read "7 available"), and any failed background refresh replaced a loaded sheet with
 * raw error text and no way back.
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
  onError?: (e: unknown) => void;
}

const apollo = vi.hoisted(() => ({
  confirm: vi.fn(),
  confirmOptions: {} as ConfirmOptions,
  confirmDoc: null as DocumentNode | null,
  query: { data: undefined as unknown, error: undefined as unknown },
  refetch: vi.fn(),
}));
const showToast = vi.fn();

vi.mock('@apollo/client/react', () => ({
  useQuery: () => ({ data: apollo.query.data, loading: false, error: apollo.query.error, refetch: apollo.refetch }),
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

beforeEach(() => {
  apollo.confirmDoc = CONFIRM_PICK;
  apollo.confirm.mockReset();
  apollo.refetch.mockReset();
  apollo.refetch.mockResolvedValue({});
  apollo.query = { data: { pullPickSheet: SHEET }, error: undefined };
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

it('reads the sheet again when the server refuses a confirm, keeping what was typed', () => {
  renderPage();
  const box = screen.getByLabelText(/^Pulled from /);
  fireEvent.change(box, { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm short pick' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm short pick' }));

  apollo.confirmOptions.onError?.(
    new CombinedGraphQLErrors({
      errors: [{ message: 'HINGE HG-100 at A-1-1: 3 entered but only 0 available', extensions: { code: 'VALIDATION_ERROR' } }],
    }),
  );

  expect(apollo.refetch).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText(/^Pulled from /)).toHaveValue(3);
});

it('does not re-read the sheet for a network failure', () => {
  renderPage();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm short pick' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm short pick' }));
  apollo.confirmOptions.onError?.(new TypeError('Failed to fetch'));

  expect(apollo.refetch).not.toHaveBeenCalled();
});

it('keeps a loaded sheet on screen when a background refresh fails', () => {
  apollo.query = { data: { pullPickSheet: SHEET }, error: new TypeError('Failed to fetch') };
  renderPage();

  expect(screen.getByRole('button', { name: 'Confirm short pick' })).toBeInTheDocument();
  expect(screen.getByTestId('pick-sheet-stale')).toHaveTextContent(/figures may be out of date/i);
  expect(screen.queryByText('Failed to fetch')).not.toBeInTheDocument();
});

it('offers a retry when the sheet never loaded', () => {
  apollo.query = { data: undefined, error: new TypeError('Failed to fetch') };
  renderPage();

  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(apollo.refetch).toHaveBeenCalledTimes(1);
});
