import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import RequestWorkspaceCartRail from '../RequestWorkspaceCartRail';
import { productKey, type CartLine, type Headroom } from '../requestCart';

// #1592: clearing a cart quantity to retype it took the line out mid-keystroke (blank parsed as 0), and an
// emptied edit disabled Save without saying why.

const hinge: CartLine = { openingNumber: '101', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 4 };
const headroom: Headroom = new Map([[productKey(hinge), 10]]);

function Harness({ initial, mode }: { initial: CartLine[]; mode: 'create' | 'edit' }) {
  const [cart, setCart] = useState(initial);
  return (
    <RequestWorkspaceCartRail
      cart={cart}
      headroom={headroom}
      onCartChange={setCart}
      onSubmit={() => {}}
      submitting={false}
      mode={mode}
    />
  );
}

it('keeps the line while its quantity is cleared to be retyped', () => {
  render(<Harness initial={[hinge]} mode="create" />);
  const field = screen.getByLabelText('Cart quantity of HG-100 for 101');

  fireEvent.change(field, { target: { value: '' } });
  expect(screen.getByLabelText('Cart quantity of HG-100 for 101')).toBeInTheDocument();

  fireEvent.change(field, { target: { value: '3' } });
  expect(screen.getByLabelText('Cart quantity of HG-100 for 101')).toHaveValue(3);
});

it('puts the quantity back when the field is left blank', () => {
  render(<Harness initial={[hinge]} mode="create" />);
  const field = screen.getByLabelText('Cart quantity of HG-100 for 101');
  fireEvent.change(field, { target: { value: '' } });
  fireEvent.blur(field);
  expect(screen.getByLabelText('Cart quantity of HG-100 for 101')).toHaveValue(4);
});

it('says why Save is off when an edit has every line taken out', () => {
  render(<Harness initial={[]} mode="edit" />);
  expect(screen.getByRole('button', { name: 'Save request' })).toBeDisabled();
  expect(screen.getByText('A request needs at least one line - reject it from Requests instead.')).toBeInTheDocument();
  expect(screen.queryByText(/Nothing added yet/)).not.toBeInTheDocument();
});

it('does not take the line out when a 0 is typed on the way to another number', () => {
  const ten: CartLine = { ...hinge, quantity: 10 };
  render(<Harness initial={[ten]} mode="create" />);
  const field = () => screen.getByLabelText('Cart quantity of HG-100 for 101');

  // "10" edited in place: delete the 1 (reads "0"), then type the 2.
  fireEvent.change(field(), { target: { value: '0' } });
  expect(field()).toBeInTheDocument();
  fireEvent.change(field(), { target: { value: '20' } });

  // The pool holds 10, so the 20 lands at its ceiling - but the line is still there.
  expect(field()).toHaveValue(10);
});

it('takes the line out on a 0 the worker leaves the field with', () => {
  render(<Harness initial={[hinge]} mode="create" />);
  const field = screen.getByLabelText('Cart quantity of HG-100 for 101');
  fireEvent.change(field, { target: { value: '0' } });
  fireEvent.blur(field);
  expect(screen.queryByLabelText('Cart quantity of HG-100 for 101')).not.toBeInTheDocument();
});
