/**
 * The manager's batch review form (#643/#644).
 *
 * The arithmetic is pinned in batchAllocation.test.ts; what is worth rendering is the shape of the
 * decision: one opening at a time with prev/next, a per-opening include toggle, the product summary
 * collapsed until asked for, and a Create batch that names how many openings it would dispatch.
 */

import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BatchReviewPanel from '../BatchReviewPanel';
import type { AllocationLine, AllocationReview } from '../types';

function line(
  openingNumber: string,
  productCode: string,
  requestedQuantity: number,
  availableQuantity: number,
): AllocationLine {
  return { openingNumber, hardwareCategory: 'HINGE', productCode, requestedQuantity, availableQuantity };
}

const REVIEW: AllocationReview = {
  requestId: 'r1',
  requestNumber: 'P-100-001',
  projectId: 'p1',
  status: 'PENDING',
  createdBy: 'PM',
  createdAt: '2026-08-31T00:00:00Z',
  integrityNote: null,
  openings: [
    { openingNumber: 'A01', lines: [line('A01', 'HG-100', 2, 3)] },
    { openingNumber: 'A02', lines: [line('A02', 'HG-100', 2, 3)] },
  ],
};

function renderPanel(overrides: Partial<React.ComponentProps<typeof BatchReviewPanel>> = {}) {
  const props = {
    review: REVIEW,
    loading: false,
    busy: false,
    disabledReason: null,
    canReject: true,
    onCreateBatch: vi.fn(),
    onDismissRemaining: vi.fn(),
    onReject: vi.fn(),
    ...overrides,
  };
  render(<BatchReviewPanel {...props} />);
  return props;
}

describe('BatchReviewPanel', () => {
  it('opens on the first pending opening and walks to the next', () => {
    renderPanel();

    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    // The rail lists both, but the detail is one door's lines.
    expect(screen.getByLabelText('Send HG-100 for A01')).toBeInTheDocument();
    expect(screen.queryByLabelText('Send HG-100 for A02')).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Next opening'));

    expect(screen.getByText('2 of 2')).toBeInTheDocument();
    expect(screen.getByLabelText('Send HG-100 for A02')).toBeInTheDocument();
  });

  it('seeds each opening at what the shared pool can still cover, in order', () => {
    // Three hinges, two doors owed two each: the first takes 2 and the second gets what is left.
    renderPanel();

    expect(screen.getByLabelText('Send HG-100 for A01')).toHaveValue(2);
    fireEvent.click(screen.getByLabelText('Next opening'));
    expect(screen.getByLabelText('Send HG-100 for A02')).toHaveValue(1);
  });

  it('shows the shortfall a partial batch would forfeit, and says so', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText('Next opening'));

    // A02 is owed 2 and can only have 1, so batching it gives up the other one for good.
    expect(
      screen.getByText(/Batching this opening sends what is here and forfeits the rest/),
    ).toBeInTheDocument();
  });

  it('counts only the openings a batch would actually dispatch', () => {
    renderPanel();

    expect(screen.getByRole('button', { name: 'Create batch (2 openings)' })).toBeEnabled();

    fireEvent.click(screen.getByLabelText('Include A02 in this batch'));

    expect(screen.getByRole('button', { name: 'Create batch (1 opening)' })).toBeEnabled();
  });

  it('sends only the included openings lines, dropping a zero', () => {
    const props = renderPanel();
    fireEvent.click(screen.getByLabelText('Include A02 in this batch'));
    fireEvent.click(screen.getByRole('button', { name: 'Create batch (1 opening)' }));

    expect(props.onCreateBatch).toHaveBeenCalledWith([
      { openingNumber: 'A01', hardwareCategory: 'HINGE', productCode: 'HG-100', allocatedQuantity: 2 },
    ]);
  });

  it('refuses a batch with nothing on it and says which fix', () => {
    renderPanel({
      review: {
        ...REVIEW,
        openings: [{ openingNumber: 'A01', lines: [line('A01', 'HG-100', 2, 0)] }],
      },
    });

    expect(screen.getByRole('button', { name: 'Create batch (0 openings)' })).toBeDisabled();
    expect(screen.getByText('Tick at least one opening and give it a quantity.')).toBeInTheDocument();
    // The #645 case: an opening with nothing free is not dispatched as an empty cart.
    expect(screen.getByText(/it cannot go on a batch/)).toBeInTheDocument();
  });

  it('keeps the product summary collapsed until it is asked for (#644)', () => {
    renderPanel();

    // The heading is always there; the table under it is not rendered until expanded.
    const summary = screen.getByText('Product summary');
    expect(screen.queryByRole('columnheader', { name: 'Sending' })).not.toBeInTheDocument();

    fireEvent.click(summary);

    const row = within(screen.getByRole('columnheader', { name: 'Sending' }).closest('table')!);
    expect(row.getByText('HG-100')).toBeInTheDocument();
  });

  it('explains itself rather than hiding the actions when the caller is not a manager', () => {
    renderPanel({ disabledReason: 'Allocating is the manager’s.' });

    expect(screen.getByRole('button', { name: 'Create batch (2 openings)' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Dismiss remaining' })).toBeDisabled();
    expect(screen.getByText('Allocating is the manager’s.')).toBeInTheDocument();
  });

  it('offers no whole-request reject once the request has been batched', () => {
    renderPanel({ canReject: false });

    expect(screen.queryByRole('button', { name: 'Reject request' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dismiss remaining' })).toBeInTheDocument();
  });

  it('says so rather than rendering an empty walk when nothing is waiting', () => {
    renderPanel({ review: { ...REVIEW, openings: [] } });

    expect(screen.getByText(/every opening has been batched or dismissed/)).toBeInTheDocument();
  });
});
