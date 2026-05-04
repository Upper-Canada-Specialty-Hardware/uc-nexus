import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import OrderAsAutocomplete from '../OrderAsAutocomplete';

function Harness({ initial, options }: { initial: string; options: string[] }) {
  const [value, setValue] = useState(initial);
  return (
    <div>
      <OrderAsAutocomplete value={value} onChange={setValue} options={options} placeholder="Order as" />
      <div data-testid="current-value">{value}</div>
    </div>
  );
}

describe('OrderAsAutocomplete', () => {
  it('lets the user pick a suggested option', () => {
    render(<Harness initial="" options={['ABC-SKU-1', 'ABC-SKU-2']} />);

    const input = screen.getByPlaceholderText('Order as');
    fireEvent.mouseDown(input);

    const option = screen.getByText('ABC-SKU-2');
    fireEvent.click(option);

    expect(screen.getByTestId('current-value').textContent).toBe('ABC-SKU-2');
  });

  it('allows typing a brand-new value not in options (freeSolo)', () => {
    render(<Harness initial="" options={['ABC-SKU-1']} />);

    const input = screen.getByPlaceholderText('Order as') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'BRAND-NEW' } });

    expect(screen.getByTestId('current-value').textContent).toBe('BRAND-NEW');
  });

  it('renders the controlled value in the input', () => {
    render(<Harness initial="EXISTING" options={[]} />);

    const input = screen.getByPlaceholderText('Order as') as HTMLInputElement;
    expect(input.value).toBe('EXISTING');
  });

  it('disables the input when disabled prop is set', () => {
    render(
      <OrderAsAutocomplete
        value=""
        onChange={() => {}}
        options={['X']}
        disabled
        placeholder="Order as"
      />,
    );

    const input = screen.getByPlaceholderText('Order as') as HTMLInputElement;
    expect(input).toBeDisabled();
  });

  it('clears the value when the clear button is pressed', () => {
    render(<Harness initial="EXISTING" options={['EXISTING']} />);

    const clearButton = screen.getByLabelText('Clear');
    fireEvent.click(clearButton);

    expect(screen.getByTestId('current-value').textContent).toBe('');
  });
});
