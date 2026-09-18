import { render, screen } from '@testing-library/react';
import TopBarCompany from '../TopBarCompany';

// A tenant IS a GP company, and nothing on any screen used to say which one the signed-in user was
// on. This is the answer that follows them from page to page, so each of its four states is pinned.
const identity = vi.hoisted(() => ({
  isNexusAdmin: false,
  company: 'TUBC' as string | null,
  user: { id: 'user_1' } as unknown,
}));

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Jay Puzon',
    userId: 'user_1',
    roles: identity.isNexusAdmin ? ['UC Nexus Admin'] : [],
    hasRole: (role: string) => identity.isNexusAdmin && role === 'UC Nexus Admin',
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: false,
    ownsTenant: identity.isNexusAdmin,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.company,
    user: identity.user,
  }),
}));

beforeEach(() => {
  identity.isNexusAdmin = false;
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

test('a UC Nexus Admin sees every company combined, so no single code is shown', () => {
  identity.isNexusAdmin = true;
  identity.company = null;
  const { container } = render(<TopBarCompany />);

  expect(container).toBeEmptyDOMElement();
});

test('an admin who does hold a company is still shown none', () => {
  // A UC Nexus Admin is unscoped whether or not an assignment happens to be set, so naming one company
  // would say their rows are limited to it.
  identity.isNexusAdmin = true;
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
