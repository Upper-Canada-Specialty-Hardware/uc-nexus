import { describe, expect, it, vi, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ToastProvider, useToast } from '../Toast';
import type { AlertColor } from '@mui/material';

function Trigger({ message, severity }: { message: string; severity: AlertColor }) {
  const { showToast } = useToast();
  return <button onClick={() => showToast(message, severity)}>{`show ${message}`}</button>;
}

function renderToasts(triggers: Array<{ message: string; severity: AlertColor }>) {
  return render(
    <ToastProvider>
      {triggers.map((t) => (
        <Trigger key={t.message} {...t} />
      ))}
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe('ToastProvider (#1136)', () => {
  it('keeps an error until it is dismissed', async () => {
    vi.useFakeTimers();
    renderToasts([{ message: 'eConnect error 9191', severity: 'error' }]);
    fireEvent.click(screen.getByText('show eConnect error 9191'));
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(screen.getByText('eConnect error 9191')).toBeInTheDocument();

    // The exit animation finishes on a real frame.
    vi.useRealTimers();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByText('eConnect error 9191')).not.toBeInTheDocument());
  });

  it('still auto-hides a success toast', async () => {
    vi.useFakeTimers();
    renderToasts([{ message: 'Saved', severity: 'success' }]);
    fireEvent.click(screen.getByText('show Saved'));
    expect(screen.getByText('Saved')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    vi.useRealTimers();
    await waitFor(() => expect(screen.queryByText('Saved')).not.toBeInTheDocument());
  });

  it('stacks a success toast under an error instead of replacing it', () => {
    renderToasts([
      { message: 'Register failed', severity: 'error' },
      { message: 'Draft saved', severity: 'success' },
    ]);
    fireEvent.click(screen.getByText('show Register failed'));
    fireEvent.click(screen.getByText('show Draft saved'));
    expect(screen.getByText('Register failed')).toBeInTheDocument();
    expect(screen.getByText('Draft saved')).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(2);
  });

  it('copies an error message', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    renderToasts([{ message: 'GP rejected the PO', severity: 'error' }]);
    fireEvent.click(screen.getByText('show GP rejected the PO'));

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy message' }));
    });
    expect(writeText).toHaveBeenCalledWith('GP rejected the PO');
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('offers no copy button on a success toast', () => {
    renderToasts([{ message: 'Saved', severity: 'success' }]);
    fireEvent.click(screen.getByText('show Saved'));
    expect(screen.queryByRole('button', { name: 'Copy message' })).not.toBeInTheDocument();
  });
});
