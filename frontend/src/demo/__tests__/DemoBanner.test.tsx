import { act, fireEvent, render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import theme from '../../theme';
import DemoBanner from '../DemoBanner';
import type { DemoRun } from '../useDemoMode';

// #1608: the band that says what the user is looking at, and holds the way out. Since #1657 it is a shared
// copy of UBC, and nobody resets it from here.

const demo = vi.hoisted(() => ({
  demoMode: true,
  busy: false,
  running: null as DemoRun | null,
  leave: vi.fn(),
}));

vi.mock('../useDemoMode', () => ({ useDemoMode: () => demo }));

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

it('lets anybody in demo mode leave it, and offers no reset', () => {
  renderBanner();
  expect(screen.queryByRole('button', { name: /reset/i })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Leave demo mode' }));
  expect(demo.leave).toHaveBeenCalledTimes(1);
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
