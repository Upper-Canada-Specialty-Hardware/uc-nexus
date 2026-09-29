import type { GridColDef } from '@mui/x-data-grid';
import InfoHeaderLabel from './InfoHeaderLabel';

// Each numeric column on the admin progress grids counts a different thing and they routinely
// disagree (e.g. Received is PO receipts, NOT current inventory). Surface the exact rule on hover
// so the numbers aren't misread cold. renderHeader keeps the column's right alignment via
// headerAlign. The label itself lives in InfoHeaderLabel so a hand-built grid can share it (#856).
export function infoHeader(label: string, tooltip: string): GridColDef['renderHeader'] {
  return () => <InfoHeaderLabel label={label} tooltip={tooltip} />;
}
