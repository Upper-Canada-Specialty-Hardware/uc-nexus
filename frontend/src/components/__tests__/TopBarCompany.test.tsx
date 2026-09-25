import { fireEvent, render, screen } from '@testing-library/react';
import TopBarCompany from '../TopBarCompany';
import type { ActingCompanyState } from '../../company/ActingCompanyContext';

// A tenant IS a GP company, and nothing on any screen used to say which one the signed-in user was
// on. This is the answer that follows them from page to page. #845: a UC Nexus Admin works in one
// company at a time too, and switches it here.
const identity = vi.hoisted(() => ({ user: { id: 'user_1' } as unknown }));

const acting = vi.hoisted(() => ({
  state: null as unknown as ActingCompanyState,
}));

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({ user: identity.user }),
}));

vi.mock('../../company/ActingCompanyContext', () => ({
  useActingCompany: () => acting.state,
}));

const COMPANIES = [
  { id: 'TUBC', name: 'Test UBC' },
  { id: 'UCSH', name: 'Upper Canada' },
];

function scoped(company: string | null): ActingCompanyState {
  return { company, companies: [], canSwitch: false, setCompany: vi.fn(), resolving: false };
}

function admin(company: string | null, companies = COMPANIES): ActingCompanyState {
  return { company, companies, canSwitch: true, setCompany: vi.fn(), resolving: false };
}

beforeEach(() => {
  identity.user = { id: 'user_1' };
  acting.state = scoped('TUBC');
});

test('a scoped user is told their GP company', () => {
  render(<TopBarCompany />);

  expect(screen.getByText('TUBC')).toBeInTheDocument();
  expect(screen.queryByRole('button')).toBeNull();
});

test('the code is labelled, so it is not a bare four letters to a screen reader', () => {
  render(<TopBarCompany />);

  expect(screen.getByLabelText('Your GP company: TUBC')).toBeInTheDocument();
});

test('nothing renders while Clerk is still resolving the user', () => {
  identity.user = null;
  const { container } = render(<TopBarCompany />);

  expect(container).toBeEmptyDOMElement();
});

test('an unassigned user gets nothing here - that is the gate’s story', () => {
  acting.state = scoped(null);
  const { container } = render(<TopBarCompany />);

  expect(container).toBeEmptyDOMElement();
});

test('a UC Nexus Admin gets a switcher naming the company they are working in', () => {
  acting.state = admin('TUBC');
  render(<TopBarCompany />);

  const button = screen.getByRole('button', { name: /GP company: TUBC - Test UBC/ });
  expect(button).toHaveTextContent('TUBC');
  expect(button).toHaveTextContent('Test UBC');
});

test('the switcher offers every company and switches to the one picked', () => {
  const state = admin('TUBC');
  acting.state = state;
  render(<TopBarCompany />);

  fireEvent.click(screen.getByRole('button', { name: /Switch company/ }));
  const options = screen.getAllByRole('menuitem');
  expect(options).toHaveLength(2);
  fireEvent.click(screen.getByRole('menuitem', { name: /UCSH/ }));

  expect(state.setCompany).toHaveBeenCalledWith('UCSH');
});

test('picking the company already in force is not a switch', () => {
  const state = admin('TUBC');
  acting.state = state;
  render(<TopBarCompany />);

  fireEvent.click(screen.getByRole('button', { name: /Switch company/ }));
  fireEvent.click(screen.getByRole('menuitem', { name: /TUBC/ }));

  expect(state.setCompany).not.toHaveBeenCalled();
});

test('an admin sees nothing until the list is read, rather than a company that may be wrong', () => {
  acting.state = admin('TUBC', []);
  const { container } = render(<TopBarCompany />);

  expect(container).toBeEmptyDOMElement();
});
