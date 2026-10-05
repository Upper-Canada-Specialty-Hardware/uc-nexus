import { render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { useDropProjectOnCompanySwitch, useOnCompanySwitch } from '../useDropProjectOnCompanySwitch';

// #1528: Shipping Requests kept the old company's ?project= after a switch, as Inventory did before #1469.
let actingCompany: string | null = 'TUBC';
vi.mock('../../company/ActingCompanyContext', () => ({
  useActingCompany: () => ({ company: actingCompany }),
}));

beforeEach(() => {
  actingCompany = 'TUBC';
});

function Page() {
  useDropProjectOnCompanySwitch();
  const { search } = useLocation();
  return <div data-testid="search">{search}</div>;
}

const page = () => (
  <MemoryRouter initialEntries={['/app/shipping/requests?project=proj-1&view=ALL']}>
    <Page />
  </MemoryRouter>
);

it("drops the previous company's project on a switch and keeps the rest of the url", () => {
  const { rerender } = render(page());
  expect(screen.getByTestId('search')).toHaveTextContent('project=proj-1');

  actingCompany = 'UCSH';
  rerender(page());

  expect(screen.getByTestId('search')).not.toHaveTextContent('project=');
  expect(screen.getByTestId('search')).toHaveTextContent('view=ALL');
});

it('keeps the project while the company stays the same, and on the first company being set', () => {
  actingCompany = null;
  const { rerender } = render(page());
  actingCompany = 'TUBC';
  rerender(page());
  rerender(page());

  expect(screen.getByTestId('search')).toHaveTextContent('project=proj-1');
});

it("runs a page's own reset on a switch, not on the first company or a same-company render (#1532)", () => {
  const reset = vi.fn();
  function Filtered() {
    useOnCompanySwitch(reset);
    return null;
  }
  actingCompany = null;
  const { rerender } = render(<Filtered />);
  actingCompany = 'TUBC';
  rerender(<Filtered />);
  rerender(<Filtered />);
  expect(reset).not.toHaveBeenCalled();

  actingCompany = 'UCSH';
  rerender(<Filtered />);
  expect(reset).toHaveBeenCalledTimes(1);
});
