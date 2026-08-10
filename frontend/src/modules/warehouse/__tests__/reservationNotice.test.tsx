import { render, screen } from '@testing-library/react';
import { ReservationNotice } from '../reservationNotice';

// The notice is the shared warn surface behind every inventory-write dialog (#342): it shows the
// combo's reserved count and escalates to a warning when the entered result would leave sound
// on-hand below it. Its render condition is the material logic, so it is tested directly.
describe('ReservationNotice', () => {
  it('warns when the result would strand an active reservation', () => {
    render(<ReservationNotice reserved={4} resulting={2} />);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Leaves 2 on hand');
    expect(alert).toHaveTextContent('below the 4 unit(s) reserved by active requests');
  });

  it('shows the reserved count without a warning when the result still covers it', () => {
    render(<ReservationNotice reserved={4} resulting={4} />);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText('4 unit(s) reserved by active requests.')).toBeInTheDocument();
  });

  it('renders nothing when nothing is reserved', () => {
    const { container } = render(<ReservationNotice reserved={0} resulting={-3} />);
    expect(container).toBeEmptyDOMElement();
  });
});
