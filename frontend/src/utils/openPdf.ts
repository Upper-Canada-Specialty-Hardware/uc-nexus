import type { AlertColor } from '@mui/material';
import type { ToastAction } from '../components/Toast';

type Notify = (message: string, severity?: AlertColor, action?: ToastAction) => void;

/** How long a shown PDF's blob URL lives once the tab has it; the tab keeps its own copy after load. */
export const PDF_URL_TTL_MS = 60_000;
/** A blocked tab's fallback link has to outlive the toast it sits in, so it is kept longer. */
export const BLOCKED_PDF_URL_TTL_MS = 10 * 60_000;

export interface PdfWindow {
  /** Point the tab opened at click time at the generated PDF. */
  show: (blob: Blob) => void;
  /** Close the tab when generation failed. */
  cancel: () => void;
}

/**
 * Open the preview tab now, inside the click (#1338). Browsers only let a click open a tab for a few
 * seconds, so a tab opened after an awaited save and a large render was silently blocked. Call this
 * synchronously in the click handler, then show() the blob once it is ready. Each blob URL is revoked
 * after a while, so a tablet reprinting all day does not keep every PDF in memory.
 */
export function openPdfWindow(notify: Notify): PdfWindow {
  const win = window.open('', '_blank');
  return {
    show(blob) {
      const url = URL.createObjectURL(blob);
      if (win && !win.closed) {
        win.location.href = url;
        window.setTimeout(() => URL.revokeObjectURL(url), PDF_URL_TTL_MS);
        return;
      }
      notify('The browser blocked the new tab for the PDF.', 'warning', {
        label: 'Open PDF',
        onClick: () => window.open(url, '_blank'),
      });
      window.setTimeout(() => URL.revokeObjectURL(url), BLOCKED_PDF_URL_TTL_MS);
    },
    cancel() {
      if (win && !win.closed) win.close();
    },
  };
}
