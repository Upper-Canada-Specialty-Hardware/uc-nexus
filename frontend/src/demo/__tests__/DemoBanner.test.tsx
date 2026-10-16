import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import theme from '../../theme';
import DemoBanner from '../DemoBanner';
import type { DemoRun } from '../useDemoMode';
import type { DemoResetStatus } from '../useDemoReset';

// #1608: the band that says what the user is looking at, and holds the way out. Since #1657 it is a shared
// copy of UBC; since #1697 anybody in it can reset it, and everybody else is told.

const demo = vi.hoisted(() => ({
  demoMode: true,
  busy: false,
  running: null as DemoRun | null,
  leave: vi.fn(),
}));

vi.mock('../useDemoMode', () => ({ useDemoMode: () => demo }));

const resetting = vi.hoisted(() => ({
  status: null as DemoResetStatus | null,
  building: false,
  resetting: false,
  acknowledging: false,
  reset: vi.fn(),
  dismissNotice: vi.fn(),
}));

vi.mock('../useDemoReset', () => ({ useDemoReset: () => resetting }));

function renderBanner() {
  return render(
    <ThemeProvider theme={theme}>
      <DemoBanner />
    </ThemeProvider>,
  );
}

beforeEach(() => {
  demo.demoMode = true;
  demo.busy = false;
  demo.running = null;
  demo.leave.mockReset();
  resetting.status = null;
  resetting.building = false;
  resetting.reset.mockReset();
  resetting.dismissNotice.mockReset();
});

it('renders nothing out of demo mode', () => {
  demo.demoMode = false;
  const { container } = renderBanner();
  expect(container).toBeEmptyDOMElement();
});

it('says it is a shared copy of UBC with GP simulated', () => {
  renderBanner();
  expect(screen.getByText(/A copy of UBC shared by everybody in demo mode, with GP simulated/)).toBeInTheDocument();
});

it('lets anybody in demo mode leave it', () => {
  renderBanner();
  fireEvent.click(screen.getByRole('button', { name: 'Leave demo mode' }));
  expect(demo.leave).toHaveBeenCalledTimes(1);
});

// #1697: anybody in demo mode resets it, after saying yes to what that does to everybody else.
it('resets the demo once confirmed', () => {
  renderBanner();
  fireEvent.click(screen.getByRole('button', { name: 'Reset demo' }));
  expect(screen.getByText(/Everything anybody has done in demo mode is wiped/)).toBeInTheDocument();
  expect(resetting.reset).not.toHaveBeenCalled();

  const dialog = screen.getByRole('dialog', { name: 'Reset the demo?' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Reset demo' }));
  expect(resetting.reset).toHaveBeenCalledTimes(1);
});

it('waits out a running reset, naming who started it', () => {
  resetting.building = true;
  resetting.status = { building: true, buildStartedAt: '2026-10-16T18:40:00', buildStartedBy: 'Rhea Resetter', notice: null };
  renderBanner();
  expect(screen.getByRole('dialog', { name: 'The demo is being reset' })).toHaveTextContent('Rhea Resetter started a reset');
  // The page behind the wait is hidden from the accessibility tree, as a modal should leave it.
  expect(screen.getByRole('button', { name: 'Reset demo', hidden: true })).toBeDisabled();
});

it('tells somebody who reset the demo and when, until they say they have seen it', () => {
  resetting.status = {
    building: false,
    buildStartedAt: null,
    buildStartedBy: null,
    notice: { resetAt: '2026-10-16T18:41:52', resetBy: 'Rhea Resetter' },
  };
  renderBanner();
  const notice = screen.getByRole('dialog', { name: 'The demo was reset' });
  expect(notice).toHaveTextContent('Rhea Resetter reset the demo on');
  fireEvent.click(within(notice).getByRole('button', { name: 'Got it' }));
  expect(resetting.dismissNotice).toHaveBeenCalledTimes(1);
});

// #1653: leaving is quick, but the banner shows a run in progress rather than just greying the button.
it('shows a run in progress until it ends', () => {
  vi.useFakeTimers();
  try {
    demo.busy = true;
    demo.running = 'leave';
    renderBanner();
    expect(screen.getByRole('button', { name: 'Leave demo mode' })).toBeDisabled();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole('dialog', { name: 'Leaving demo mode' })).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
