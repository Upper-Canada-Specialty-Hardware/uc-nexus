import { fireEvent, render, screen } from '@testing-library/react';
import QuantityField from '../QuantityField';

// #1604: the owner removes a line at 0, so the field never commits a 0 - or a blank - mid-edit.
it('holds a blank or a 0 while typing, commits a 0 only when settled, and restores a blank', () => {
  const onCommit = vi.fn();
  render(<QuantityField quantity={10} ariaLabel="Qty" onCommit={onCommit} />);
  const field = screen.getByRole('spinbutton', { name: 'Qty' });

  fireEvent.change(field, { target: { value: '' } });
  fireEvent.change(field, { target: { value: '0' } });
  expect(onCommit).not.toHaveBeenCalled();
  fireEvent.change(field, { target: { value: '20' } });
  expect(onCommit).toHaveBeenLastCalledWith(20);

  onCommit.mockClear();
  fireEvent.change(field, { target: { value: '' } });
  fireEvent.blur(field);
  expect(onCommit).not.toHaveBeenCalled();
  expect(field).toHaveValue(10);

  fireEvent.change(field, { target: { value: '0' } });
  fireEvent.keyDown(field, { key: 'Enter' });
  expect(onCommit).toHaveBeenCalledWith(0);
});
