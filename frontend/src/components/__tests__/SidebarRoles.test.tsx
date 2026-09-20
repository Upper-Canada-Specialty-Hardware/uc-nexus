import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NavContent } from '../Sidebar';

/**
 * #729: which modules the rail offers, per role.
 *
 * The rail is the whole answer to "what am I allowed to open", so the retired all-access role's
 * bypass has to be gone in a way a test can see. Only UC NEXUS ADMIN bypasses now; TENANT OWNER is
 * listed by name on every operational module and holds the whole company; a module role opens its
 * own module and nothing else.
 */
const identity = vi.hoisted(() => ({ roles: [] as string[] }));

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    userId: 'user_1',
    roles: identity.roles,
    hasRole: (role: string) => identity.roles.includes(role),
    isNexusAdmin: identity.roles.includes('UC Nexus Admin'),
    isTenantOwner: identity.roles.includes('Tenant Owner'),
    ownsTenant: identity.roles.some((r) => r === 'UC Nexus Admin' || r === 'Tenant Owner'),
    isDbAdmin: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

const EVERY_ITEM = [
  'Home',
  'Purchase Orders',
  'Warehouse',
  'Shop Assembly',
  'Shipping',
  'Tenant Owner',
  'UC Nexus Admin',
];

beforeEach(() => {
  identity.roles = [];
});

function itemButton(label: string): HTMLElement {
  const button = screen.getByText(label).closest('[role="button"]');
  if (!button) throw new Error(`no rail item labelled ${label}`);
  return button as HTMLElement;
}

/** The labels of the items this user can actually press. A gated item renders, but disabled. */
function openableItems(): string[] {
  return EVERY_ITEM.filter((label) => itemButton(label).getAttribute('aria-disabled') !== 'true');
}

function renderRail() {
  render(
    <MemoryRouter>
      <NavContent />
    </MemoryRouter>,
  );
}

it('gives a PO User Home and Purchase Orders, and nothing else', () => {
  identity.roles = ['PO User'];
  renderRail();

  expect(openableItems()).toEqual(['Home', 'Purchase Orders']);
});

it('gives a Warehouse Manager the warehouse alone, with no manager-wide bypass', () => {
  identity.roles = ['Warehouse Manager'];
  renderRail();

  expect(openableItems()).toEqual(['Home', 'Warehouse']);
});

it('gives a Tenant Owner every operational module and their own, but not UC Nexus Admin', () => {
  identity.roles = ['Tenant Owner'];
  renderRail();

  expect(openableItems()).toEqual([
    'Home',
    'Purchase Orders',
    'Warehouse',
    'Shop Assembly',
    'Shipping',
    'Tenant Owner',
  ]);
});

it('gives a UC Nexus Admin everything, holding no module role at all', () => {
  identity.roles = ['UC Nexus Admin'];
  renderRail();

  expect(openableItems()).toEqual(EVERY_ITEM);
});

it('tells a gated user which roles would open the module', async () => {
  identity.roles = ['PO User'];
  renderRail();

  fireEvent.mouseOver(itemButton('Shipping'));

  const tip = await screen.findByRole('tooltip');
  expect(tip.textContent).toContain('Shipping Out');
  expect(tip.textContent).toContain('Shipping Manager');
  expect(tip.textContent).toContain('Tenant Owner');
});
