import { render, screen, fireEvent } from '@testing-library/react';
import OverBuyConfirmModal from '../OverBuyConfirmModal';

// #736: finalize's confirm lists exactly which lines are at risk, and only its explicit button runs it.

const risk = {
  pk: 'HG-100|HINGE',
  projectNeeded: 12,
  wouldBe: 13,
  over: 1,
  drafts: [
    { id: 'a', label: 'ACME', qty: 4 },
    { id: 'b', label: '', qty: 2 },
  ],
};

it('lists each line with its figures and the drafts ordering it', () => {
  render(
    <OverBuyConfirmModal open risks={[risk]} productCodeOf={() => 'HG-100'} onGoBack={() => {}} onConfirm={() => {}} />,
  );

  const list = screen.getByRole('list', { name: 'Lines at risk of over-buying' });
  expect(list).toHaveTextContent('HG-100: needs 12, this would make it 13 (+1 over)');
  expect(list).toHaveTextContent('ACME orders 4 · Unnamed draft orders 2');
});

it('finalizes only from Finalize anyway', () => {
  const onConfirm = vi.fn();
  const onGoBack = vi.fn();
  render(
    <OverBuyConfirmModal open risks={[risk]} productCodeOf={() => 'HG-100'} onGoBack={onGoBack} onConfirm={onConfirm} />,
  );

  fireEvent.click(screen.getByRole('button', { name: 'Go back' }));
  expect(onConfirm).not.toHaveBeenCalled();
  expect(onGoBack).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole('button', { name: 'Finalize anyway' }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});
