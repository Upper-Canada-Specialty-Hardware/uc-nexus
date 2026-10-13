import { fireEvent, render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import theme from '../../theme';
import DemoBanner from '../DemoBanner';

// #1608: the band that says the data is made up, and holds the way out.

const demo = vi.hoisted(() => ({
  demoMode: true,
  canReset: true,
  busy: false,
  leave: vi.fn(),
  reset: vi.fn(),
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
  demo.canReset = true;
  demo.busy = false;
  demo.leave.mockReset();
  demo.reset.mockReset();
});

it('renders nothing out of demo mode', () => {
  demo.demoMode = false;
  const { container } = renderBanner();
  expect(container).toBeEmptyDOMElement();
});

it('says the data is made up and GP is simulated', () => {
  renderBanner();
  expect(screen.getByText(/Everything here is made up, and GP is simulated/)).toBeInTheDocument();
});

it('lets anybody in demo mode leave it', () => {
  demo.canReset = false;
  renderBanner();
  expect(screen.queryByRole('button', { name: 'Reset demo data' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Leave demo mode' }));
  expect(demo.leave).toHaveBeenCalledTimes(1);
});

it('resets only after the reset is confirmed', () => {
  renderBanner();
  fireEvent.click(screen.getByRole('button', { name: 'Reset demo data' }));
  expect(demo.reset).not.toHaveBeenCalled();
  const confirm = screen.getAllByRole('button', { name: 'Reset demo data' }).at(-1)!;
  fireEvent.click(confirm);
  expect(demo.reset).toHaveBeenCalledTimes(1);
});
