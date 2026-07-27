import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import AssemblyDetailModal from '../AssemblyDetailModal';
import { RECORD_ASSEMBLY_PROGRESS, COMPLETE_OPENING } from '../../../graphql/shop-assembly';

vi.setConfig({ testTimeout: 30_000 });

// The modal is a progress editor since #340: it hydrates from persisted per-item counts, saves them
// absolutely, and only lets the leaf be completed once every unit is either installed or condemned.

function item(overrides: Record<string, unknown> = {}) {
  return {
    id: 'i1',
    shopAssemblyOpeningId: 'o1',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    quantity: 4,
    installedQuantity: 0,
    deficientQuantity: 0,
    ...overrides,
  };
}

function opening(items: ReturnType<typeof item>[]) {
  return {
    id: 'o1',
    openingNumber: '0019-EX',
    building: 'A',
    floor: '2',
    leaf: 1,
    items,
  };
}

function renderModal(
  items: ReturnType<typeof item>[],
  mocks: MockedResponse[] = [],
  onCompleted = vi.fn()
) {
  const view = render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <AssemblyDetailModal
          open
          opening={opening(items)}
          onClose={vi.fn()}
          onCompleted={onCompleted}
          completedBy="Ada"
        />
      </ToastProvider>
    </MockedProvider>
  );
  return { ...view, onCompleted };
}

const installedInput = (productCode = 'HG-100') =>
  screen.getByLabelText(`Installed units: ${productCode}`) as HTMLInputElement;

describe('AssemblyDetailModal progress editor', () => {
  it('hydrates the installed input from the persisted count', () => {
    renderModal([item({ installedQuantity: 3 })]);
    expect(installedInput().value).toBe('3');
  });

  it('keeps Mark Complete disabled while units are unaccounted for', () => {
    renderModal([item({ quantity: 4, installedQuantity: 1 })]);

    expect(screen.getByRole('button', { name: /mark complete/i })).toBeDisabled();
    expect(screen.getByText(/3 unit\(s\) still unaccounted for/i)).toBeInTheDocument();
  });

  it('enables Mark Complete once every unit is installed or deficient', () => {
    // 1 already condemned, so typing 3 accounts for all 4.
    renderModal([item({ quantity: 4, installedQuantity: 0, deficientQuantity: 1 })]);

    expect(screen.getByRole('button', { name: /mark complete/i })).toBeDisabled();
    fireEvent.change(installedInput(), { target: { value: '3' } });
    expect(screen.getByRole('button', { name: /mark complete/i })).toBeEnabled();
  });

  it('refuses to enable Mark Complete when every unit was flagged deficient', () => {
    // Fully dispositioned but nothing installed - completing would mint an empty assembled leaf.
    renderModal([item({ quantity: 2, installedQuantity: 0, deficientQuantity: 2 })]);

    expect(screen.getByRole('button', { name: /mark complete/i })).toBeDisabled();
    expect(screen.getByText(/nothing assembled to complete/i)).toBeInTheDocument();
  });

  it('rejects an installed count above what is left after deficiencies', () => {
    renderModal([item({ quantity: 4, installedQuantity: 0, deficientQuantity: 1 })]);

    fireEvent.change(installedInput(), { target: { value: '4' } });
    expect(screen.getByRole('button', { name: /save progress/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /mark complete/i })).toBeDisabled();
  });

  it('Save Progress is disabled until something changes, then sends the absolute count', async () => {
    const saveMock: MockedResponse = {
      request: {
        query: RECORD_ASSEMBLY_PROGRESS,
        variables: {
          input: {
            openingId: 'o1',
            items: [{ shopAssemblyOpeningItemId: 'i1', installedQuantity: 2 }],
            performedBy: 'Ada',
          },
        },
      },
      result: {
        data: {
          recordAssemblyProgress: {
            __typename: 'ShopAssemblyOpening',
            id: 'o1',
            shopAssemblyRequestId: null,
            pullRequestId: 'pr1',
            openingId: 'op1',
            pullStatus: 'PULLED',
            assignedToUserId: 'u1',
            assignedTo: 'Ada',
            assemblyStatus: 'IN_PROGRESS',
            completedAt: null,
            openingNumber: '0019-EX',
            building: 'A',
            floor: '2',
            leaf: 1,
            items: [
              {
                __typename: 'ShopAssemblyOpeningItem',
                ...item({ installedQuantity: 2 }),
              },
            ],
          },
        },
      },
    };

    renderModal([item({ quantity: 4 })], [saveMock]);

    expect(screen.getByRole('button', { name: /save progress/i })).toBeDisabled();
    fireEvent.change(installedInput(), { target: { value: '2' } });
    expect(screen.getByRole('button', { name: /save progress/i })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: /save progress/i }));
    await waitFor(() => expect(screen.getByText(/progress saved/i)).toBeInTheDocument());
  });

  it('saves outstanding progress before completing, then reports completion', async () => {
    const saveMock: MockedResponse = {
      request: {
        query: RECORD_ASSEMBLY_PROGRESS,
        variables: {
          input: {
            openingId: 'o1',
            items: [{ shopAssemblyOpeningItemId: 'i1', installedQuantity: 2 }],
            performedBy: 'Ada',
          },
        },
      },
      result: {
        data: {
          recordAssemblyProgress: {
            __typename: 'ShopAssemblyOpening',
            id: 'o1',
            shopAssemblyRequestId: null,
            pullRequestId: 'pr1',
            openingId: 'op1',
            pullStatus: 'PULLED',
            assignedToUserId: 'u1',
            assignedTo: 'Ada',
            assemblyStatus: 'IN_PROGRESS',
            completedAt: null,
            openingNumber: '0019-EX',
            building: 'A',
            floor: '2',
            leaf: 1,
            items: [
              { __typename: 'ShopAssemblyOpeningItem', ...item({ quantity: 2, installedQuantity: 2 }) },
            ],
          },
        },
      },
    };
    const completeMock: MockedResponse = {
      request: {
        query: COMPLETE_OPENING,
        variables: {
          input: {
            openingId: 'o1',
            aisle: null,
            row: null,
            bay: null,
            completedBy: 'Ada',
          },
        },
      },
      result: {
        data: {
          completeOpening: {
            __typename: 'OpeningItem',
            id: 'oi1',
            projectId: 'p1',
            openingId: 'op1',
            openingNumber: '0019-EX',
            building: 'A',
            floor: '2',
            location: null,
            leaf: 1,
            quantity: 1,
            assemblyCompletedAt: '2026-07-26T00:00:00',
            state: 'IN_INVENTORY',
            aisle: null,
            row: null,
            bay: null,
            createdAt: '2026-07-26T00:00:00',
            updatedAt: '2026-07-26T00:00:00',
            installedHardware: [],
          },
        },
      },
    };

    const { onCompleted } = renderModal([item({ quantity: 2 })], [saveMock, completeMock]);

    fireEvent.change(installedInput(), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: /mark complete/i }));
    // Confirm dialog guards the irreversible step.
    fireEvent.click(screen.getByRole('button', { name: /^mark complete$/i, hidden: false }));

    await waitFor(() => expect(onCompleted).toHaveBeenCalled());
  });

  it('requires a reason before a deficiency can be flagged', async () => {
    renderModal([item({ quantity: 2 })]);

    fireEvent.click(screen.getByRole('button', { name: /flag deficient/i }));
    const confirm = await screen.findByRole('button', { name: /^flag deficient$/i });
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Deficiency reason'), {
      target: { value: 'bent tab' },
    });
    expect(screen.getByRole('button', { name: /^flag deficient$/i })).toBeEnabled();
  });

  it('will not let more units be flagged deficient than are left unrecorded', async () => {
    renderModal([item({ quantity: 3, installedQuantity: 2 })]);

    fireEvent.click(screen.getByRole('button', { name: /flag deficient/i }));
    fireEvent.change(await screen.findByLabelText('Deficiency reason'), {
      target: { value: 'seized' },
    });
    fireEvent.change(screen.getByLabelText('Units deficient'), { target: { value: '2' } });

    expect(screen.getByRole('button', { name: /^flag deficient$/i })).toBeDisabled();
  });
});
