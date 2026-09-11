import { fireEvent, render, screen } from '@testing-library/react';
import RelayStatusChip from '../RelayStatusChip';

// The indicator says two different things depending on who is looking, and getting that backwards is
// exactly the bug this covers: a scoped user reading "TUBC +2" understands it as "I am on three
// companies" when every row they will ever see belongs to one.
const identity = vi.hoisted(() => ({ isAdmin: true, company: null as string | null }));

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
    user: null,
  }),
}));

const COMPANIES = ['TUBC', 'UCSH', 'UBC'];
const GP_COMPANIES = [
  { id: 'TUBC', name: 'Test UBC' },
  { id: 'UCSH', name: 'UC Shop' },
  { id: 'UBC', name: 'Universal Building Components' },
];

beforeEach(() => {
  identity.isAdmin = true;
  identity.company = null;
});

function renderChip(connected: boolean | null, companies: string[] = COMPANIES) {
  render(<RelayStatusChip connected={connected} companies={companies} gpCompanies={GP_COMPANIES} />);
}

it('shows Admin/Manager the relay’s whole reach, named as GP names it', async () => {
  renderChip(true);

  const chip = screen.getByText('TUBC +2');
  fireEvent.mouseOver(chip);
  const tip = await screen.findByRole('tooltip');
  expect(tip.textContent).toContain('TUBC - Test UBC');
  expect(tip.textContent).toContain('UCSH - UC Shop');
  expect(tip.textContent).toContain('UBC - Universal Building Components');
});

it('shows a scoped user their own company and nothing else', async () => {
  identity.isAdmin = false;
  identity.company = 'TUBC';
  renderChip(true);

  expect(screen.getByText('TUBC')).toBeInTheDocument();
  // The other companies the relay serves are not this user's business, and the "+2" that stood here
  // read as a count of the companies they were on.
  expect(screen.queryByText(/\+\d/)).toBeNull();
  expect(screen.queryByText('UCSH')).toBeNull();
  expect(screen.queryByText('UBC')).toBeNull();

  fireEvent.mouseOver(screen.getByText('TUBC'));
  const tip = await screen.findByRole('tooltip');
  expect(tip.textContent).toContain('Your GP company. Everything you see in Nexus belongs to it.');
});

it('warns when the connected relay is not serving the scoped user’s company', async () => {
  identity.isAdmin = false;
  identity.company = 'TUBC';
  renderChip(true, ['UCSH', 'UBC']);

  const label = screen.getByText('TUBC');
  expect(label.closest('.MuiChip-root')?.className).toContain('Warning');

  fireEvent.mouseOver(label);
  const tip = await screen.findByRole('tooltip');
  expect(tip.textContent).toContain('is not serving TUBC yet');
});

it('says nothing about a company while the relay is down', () => {
  identity.isAdmin = false;
  identity.company = 'TUBC';
  renderChip(false);

  expect(screen.getByText('GP relay not detected')).toBeInTheDocument();
  expect(screen.queryByText('TUBC')).toBeNull();
});
