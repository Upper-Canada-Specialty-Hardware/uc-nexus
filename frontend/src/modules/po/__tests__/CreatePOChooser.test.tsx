import { render, screen, fireEvent } from '@testing-library/react';
import CreatePOChooser from '../CreatePOChooser';

// #480/#565: the PO module carries one "Create a PO" button, and the chooser is what keeps every
// route reachable - by-opening and by-hardware off the schedule, plus manual entry. What matters is
// that each card fires its own handler and only its own, and that dismissing fires none.

function renderChooser(open = true) {
  const onClose = vi.fn();
  const onFromSchedule = vi.fn();
  const onFromHardware = vi.fn();
  const onManual = vi.fn();
  render(
    <CreatePOChooser
      open={open}
      onClose={onClose}
      onFromSchedule={onFromSchedule}
      onFromHardware={onFromHardware}
      onManual={onManual}
    />,
  );
  return { onClose, onFromSchedule, onFromHardware, onManual };
}

it('offers all three routes with their one-line explanations', () => {
  renderChooser();

  expect(screen.getByText('From schedule - by opening')).toBeInTheDocument();
  expect(screen.getByText('Pick doors, shows what is still owed')).toBeInTheDocument();
  expect(screen.getByText('From schedule - by hardware')).toBeInTheDocument();
  expect(
    screen.getByText('You know which hardware to buy - pick products, not doors'),
  ).toBeInTheDocument();
  expect(screen.getByText('Manual entry')).toBeInTheDocument();
  expect(screen.getByText('Type lines by hand, no schedule involved')).toBeInTheDocument();
});

it('picks the by-opening schedule route and nothing else', () => {
  const { onFromSchedule, onFromHardware, onManual } = renderChooser();

  fireEvent.click(screen.getByText('From schedule - by opening'));

  expect(onFromSchedule).toHaveBeenCalledTimes(1);
  expect(onFromHardware).not.toHaveBeenCalled();
  expect(onManual).not.toHaveBeenCalled();
});

it('picks the by-hardware schedule route and nothing else', () => {
  const { onFromSchedule, onFromHardware, onManual } = renderChooser();

  fireEvent.click(screen.getByText('From schedule - by hardware'));

  expect(onFromHardware).toHaveBeenCalledTimes(1);
  expect(onFromSchedule).not.toHaveBeenCalled();
  expect(onManual).not.toHaveBeenCalled();
});

it('picks the manual route and nothing else', () => {
  const { onFromSchedule, onFromHardware, onManual } = renderChooser();

  fireEvent.click(screen.getByText('Manual entry'));

  expect(onManual).toHaveBeenCalledTimes(1);
  expect(onFromSchedule).not.toHaveBeenCalled();
  expect(onFromHardware).not.toHaveBeenCalled();
});

it('closes with no action taken', () => {
  const { onClose, onFromSchedule, onFromHardware, onManual } = renderChooser();

  fireEvent.click(screen.getByRole('button', { name: 'Close' }));

  expect(onClose).toHaveBeenCalled();
  expect(onFromSchedule).not.toHaveBeenCalled();
  expect(onFromHardware).not.toHaveBeenCalled();
  expect(onManual).not.toHaveBeenCalled();
});
