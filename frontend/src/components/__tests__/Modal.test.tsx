import { fireEvent, render, screen } from '@testing-library/react';
import { Button } from '@mui/material';
import Modal from '../Modal';

// #1285: onSubmit makes the dialog a form, so Enter in a field does what the primary button does -
// and nothing whenever that button is disabled. Without onSubmit there is no form at all.
function renderModal(props: { onSubmit?: () => void; submitDisabled?: boolean }) {
  return render(
    <Modal
      open
      title="Count"
      onClose={() => {}}
      onSubmit={props.onSubmit}
      submitDisabled={props.submitDisabled}
      actions={
        <Button type="submit" disabled={props.submitDisabled}>
          Apply
        </Button>
      }
    >
      <input aria-label="Physical count" />
    </Modal>,
  );
}

describe('Modal onSubmit', () => {
  it('submits on Enter in a field (the form submits)', () => {
    const onSubmit = vi.fn();
    renderModal({ onSubmit });
    const form = screen.getByLabelText('Physical count').closest('form');
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('submits once when the primary button is clicked', () => {
    const onSubmit = vi.fn();
    renderModal({ onSubmit });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('refuses while the primary action is disabled', () => {
    const onSubmit = vi.fn();
    renderModal({ onSubmit, submitDisabled: true });
    fireEvent.submit(screen.getByLabelText('Physical count').closest('form')!);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('renders no form without onSubmit', () => {
    renderModal({});
    expect(screen.getByLabelText('Physical count').closest('form')).toBeNull();
  });
});
