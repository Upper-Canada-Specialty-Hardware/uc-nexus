import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import DemoModeUserButton from '../DemoModeUserButton';

// #1629: every user turns demo mode on and off for themselves, whatever their roles.

const demo = vi.hoisted(() => ({ demoMode: false, busy: false, enter: vi.fn(), leave: vi.fn() }));

vi.mock('../useDemoMode', () => ({ useDemoMode: () => demo }));

// Clerk's menu is not rendered by the runner; stand-ins show what entry the button would carry.
vi.mock('@clerk/clerk-react', () => {
  const UserButton = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  UserButton.MenuItems = ({ children }: { children: ReactNode }) => <div>{children}</div>;
  UserButton.Action = ({ label, onClick }: { label: string; onClick: () => void }) => (
    <button onClick={onClick}>{label}</button>
  );
  return { UserButton };
});

beforeEach(() => {
  demo.demoMode = false;
  demo.enter.mockReset();
  demo.leave.mockReset();
});

it('offers every user the way in, with no role check', () => {
  render(<DemoModeUserButton />);
  screen.getByRole('button', { name: 'Turn on demo mode' }).click();
  expect(demo.enter).toHaveBeenCalledTimes(1);
});

it('offers the way out while in demo mode', () => {
  demo.demoMode = true;
  render(<DemoModeUserButton />);
  screen.getByRole('button', { name: 'Leave demo mode' }).click();
  expect(demo.leave).toHaveBeenCalledTimes(1);
});
