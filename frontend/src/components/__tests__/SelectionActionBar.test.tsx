import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import SelectionActionBar, { BarButton } from '../SelectionActionBar';

describe('SelectionActionBar', () => {
  it('renders nothing when nothing is selected', () => {
    const { container } = render(
      <SelectionActionBar count={0} onClear={() => {}}>
        <BarButton label="Move" onClick={() => {}} />
      </SelectionActionBar>,
    );
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
    expect(container.querySelector('button')).toBeNull();
  });

  it('shows the selected count and the action buttons once rows are checked', () => {
    render(
      <SelectionActionBar count={3} onClear={() => {}}>
        <BarButton label="Move" onClick={() => {}} />
      </SelectionActionBar>,
    );
    expect(screen.getByText('3 selected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Move' })).toBeInTheDocument();
  });

  it('fires onClear when the clear button is pressed', () => {
    const onClear = vi.fn();
    render(
      <SelectionActionBar count={2} onClear={onClear}>
        <BarButton label="Move" onClick={() => {}} />
      </SelectionActionBar>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('disables a BarButton and exposes its reason via tooltip wrapper', () => {
    render(
      <SelectionActionBar count={2} onClear={() => {}}>
        <BarButton label="Adjust" onClick={() => {}} disabled reason="Select a single row" />
      </SelectionActionBar>,
    );
    expect(screen.getByRole('button', { name: 'Adjust' })).toBeDisabled();
  });
});
