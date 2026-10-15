import { act, fireEvent, render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import theme from '../../theme';
import DemoProgressDialog from '../DemoProgressDialog';
import type { DemoRun } from '../useDemoMode';

// #1653: the first switch-on builds the demo for minutes (#1657); it says so while it runs.

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

it('shows a build that is still running, with a bar and the time it has taken', () => {
  renderDialog('enter');
  advance(1000);
  const dialog = screen.getByRole('dialog', { name: 'Setting up demo mode' });
  expect(dialog).toHaveTextContent(/can take a few minutes/);
  expect(screen.getByRole('progressbar', { name: 'Setting up demo mode' })).toBeInTheDocument();
  expect(dialog).toHaveTextContent('0:01 elapsed');
  advance(73_000);
  expect(dialog).toHaveTextContent('1:14 elapsed');
});

it('says what the first switch-on is doing', () => {
  renderDialog('enter');
  advance(1000);
  expect(screen.getByRole('dialog', { name: 'Setting up demo mode' })).toHaveTextContent(/copy of UBC is built/);
});

it('cannot be dismissed while the run goes on', () => {
  renderDialog('enter');
  advance(1000);
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  advance(1000);
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});

it('closes when the run ends', () => {
  const { rerender } = renderDialog('enter');
  advance(1000);
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  rerender(
    <ThemeProvider theme={theme}>
      <DemoProgressDialog running={null} />
    </ThemeProvider>,
  );
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
