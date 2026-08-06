import { render, screen, fireEvent } from '@testing-library/react';
import CreatePOChooser from '../CreatePOChooser';

// #480: the PO module used to carry two header buttons. They are one button now, and the chooser is
// what keeps both routes reachable - so what matters is that each card fires its own handler and
// only its own, and that dismissing fires neither.

function renderChooser(open = true) {
  const onClose = vi.fn();
  const onFromSchedule = vi.fn();
  const onManual = vi.fn();
  render(
    <CreatePOChooser
      open={open}
      onClose={onClose}
      onFromSchedule={onFromSchedule}
      onManual={onManual}
    />,
  );
  return { onClose, onFromSchedule, onManual };
}

it('offers both routes with their one-line explanations', () => {
  renderChooser();

  expect(screen.getByText('From hardware schedule')).toBeInTheDocument();
  expect(screen.getByText('Order off the schedule, shows what is still owed')).toBeInTheDocument();
  expect(screen.getByText('Manual entry')).toBeInTheDocument();
  expect(screen.getByText('Type lines by hand, no schedule involved')).toBeInTheDocument();
});

it('picks the schedule route without triggering the manual one', () => {
  const { onFromSchedule, onManual } = renderChooser();

  fireEvent.click(screen.getByText('From hardware schedule'));

  expect(onFromSchedule).toHaveBeenCalledTimes(1);
  expect(onManual).not.toHaveBeenCalled();
});

it('picks the manual route without triggering the schedule one', () => {
  const { onFromSchedule, onManual } = renderChooser();

  fireEvent.click(screen.getByText('Manual entry'));

  expect(onManual).toHaveBeenCalledTimes(1);
  expect(onFromSchedule).not.toHaveBeenCalled();
});

it('closes with no action taken', () => {
  const { onClose, onFromSchedule, onManual } = renderChooser();

  fireEvent.click(screen.getByRole('button', { name: 'Close' }));

  expect(onClose).toHaveBeenCalled();
  expect(onFromSchedule).not.toHaveBeenCalled();
  expect(onManual).not.toHaveBeenCalled();
});
