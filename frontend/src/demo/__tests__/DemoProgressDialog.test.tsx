import { act, fireEvent, render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import theme from '../../theme';
import DemoProgressDialog from '../DemoProgressDialog';
import type { DemoRun } from '../useDemoMode';

// #1653: a reset or a seeding switch-on runs for the better part of a minute; it says so while it runs.

function renderDialog(running: DemoRun | null) {
  return render(
    <ThemeProvider theme={theme}>
      <DemoProgressDialog running={running} />
    </ThemeProvider>,
  );
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

it('shows nothing when no run is in flight', () => {
  renderDialog(null);
  advance(5000);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('stays hidden for a run that ends at once, so a quick switch does not flash it', () => {
  const { rerender } = renderDialog('leave');
  advance(400);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  rerender(
    <ThemeProvider theme={theme}>
      <DemoProgressDialog running={null} />
    </ThemeProvider>,
  );
  advance(5000);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('shows a reset that is still running, with a bar and the time it has taken', () => {
  renderDialog('reset');
  advance(1000);
  const dialog = screen.getByRole('dialog', { name: 'Resetting the demo data' });
  expect(dialog).toHaveTextContent(/can take up to a minute/);
  expect(screen.getByRole('progressbar', { name: 'Resetting the demo data' })).toBeInTheDocument();
  expect(dialog).toHaveTextContent('0:01 elapsed');
  advance(73_000);
  expect(dialog).toHaveTextContent('1:14 elapsed');
});

it('says what a seeding switch-on is doing', () => {
  renderDialog('enter');
  advance(1000);
  expect(screen.getByRole('dialog', { name: 'Setting up demo mode' })).toHaveTextContent(/seeded/);
});

it('cannot be dismissed while the run goes on', () => {
  renderDialog('reset');
  advance(1000);
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  advance(1000);
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});

it('closes when the run ends', () => {
  const { rerender } = renderDialog('reset');
  advance(1000);
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  rerender(
    <ThemeProvider theme={theme}>
      <DemoProgressDialog running={null} />
    </ThemeProvider>,
  );
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
