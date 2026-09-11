import { render, screen } from '@testing-library/react';
import TopBarCompany from '../TopBarCompany';

// A tenant IS a GP company, and nothing on any screen used to say which one the signed-in user was
// on. This is the answer that follows them from page to page, so each of its four states is pinned.
const identity = vi.hoisted(() => ({
  isAdmin: false,
  company: 'TUBC' as string | null,
  user: { id: 'user_1' } as unknown,
}));

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Jay Puzon',
    userId: 'user_1',
    roles: identity.isAdmin ? ['Admin/Manager'] : [],
    hasRole: (role: string) => identity.isAdmin && role === 'Admin/Manager',
    isAdmin: identity.isAdmin,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.company,
    user: identity.user,
  }),
}));

beforeEach(() => {
  identity.isAdmin = false;
  identity.company = 'TUBC';
  identity.user = { id: 'user_1' };
});

test('a scoped user is told their GP company', () => {
  render(<TopBarCompany />);

  expect(screen.getByText('TUBC')).toBeInTheDocument();
});

test('the code is labelled, so it is not a bare four letters to a screen reader', () => {
  render(<TopBarCompany />);

  expect(screen.getByLabelText('Your GP company: TUBC')).toBeInTheDocument();
});

test('Admin/Manager sees every company combined, so no single code is shown', () => {
  identity.isAdmin = true;
  identity.company = null;
  const { container } = render(<TopBarCompany />);

  expect(container).toBeEmptyDOMElement();
});

test('an admin who does hold a company is still shown none', () => {
  // Admin/Manager is unscoped whether or not an assignment happens to be set, so naming one company
  // would say their rows are limited to it.
  identity.isAdmin = true;
  identity.company = 'TUBC';
  const { container } = render(<TopBarCompany />);

  expect(container).toBeEmptyDOMElement();
});

test('nothing renders while Clerk is still resolving the user', () => {
  identity.user = null;
  const { container } = render(<TopBarCompany />);

  expect(container).toBeEmptyDOMElement();
});

test('an unassigned user gets nothing here - that is the gate’s story', () => {
  identity.company = null;
  const { container } = render(<TopBarCompany />);

  expect(container).toBeEmptyDOMElement();
});
