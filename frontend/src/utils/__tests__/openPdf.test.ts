import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BLOCKED_PDF_URL_TTL_MS, PDF_URL_TTL_MS, openPdfWindow } from '../openPdf';

describe('openPdfWindow', () => {
  const blob = new Blob(['%PDF'], { type: 'application/pdf' });
  let createUrl: ReturnType<typeof vi.fn>;
  let revokeUrl: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    createUrl = vi.fn(() => 'blob:pdf-1');
    revokeUrl = vi.fn();
    URL.createObjectURL = createUrl as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeUrl as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('opens the tab synchronously, before any blob exists', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({ closed: false, location: {} } as unknown as Window);
    openPdfWindow(vi.fn());
    expect(open).toHaveBeenCalledWith('', '_blank');
    expect(createUrl).not.toHaveBeenCalled();
  });

  it('points the opened tab at the blob and revokes the url later', () => {
    const tab = { closed: false, location: { href: '' } };
    vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
    const notify = vi.fn();
    openPdfWindow(notify).show(blob);
    expect(tab.location.href).toBe('blob:pdf-1');
    expect(notify).not.toHaveBeenCalled();
    expect(revokeUrl).not.toHaveBeenCalled();
    vi.advanceTimersByTime(PDF_URL_TTL_MS);
    expect(revokeUrl).toHaveBeenCalledWith('blob:pdf-1');
  });

  it('offers a link in a toast when the browser blocked the tab', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const notify = vi.fn();
    openPdfWindow(notify).show(blob);
    expect(notify).toHaveBeenCalledWith(
      expect.stringMatching(/blocked/),
      'warning',
      expect.objectContaining({ label: 'Open PDF' }),
    );
    notify.mock.calls[0][2].onClick();
    expect(open).toHaveBeenLastCalledWith('blob:pdf-1', '_blank');
    vi.advanceTimersByTime(PDF_URL_TTL_MS);
    expect(revokeUrl).not.toHaveBeenCalled();
    vi.advanceTimersByTime(BLOCKED_PDF_URL_TTL_MS);
    expect(revokeUrl).toHaveBeenCalledWith('blob:pdf-1');
  });

  it('closes the tab when generation fails', () => {
    const close = vi.fn();
    vi.spyOn(window, 'open').mockReturnValue({ closed: false, close } as unknown as Window);
    openPdfWindow(vi.fn()).cancel();
    expect(close).toHaveBeenCalled();
  });

  it('cancel is safe when no tab opened', () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    expect(() => openPdfWindow(vi.fn()).cancel()).not.toThrow();
  });
});
