import { useState } from 'react';
import { Alert, AlertTitle, Box, Button } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import { formatGpErrorText, type GpError } from '../graphql/gpError';

interface GpErrorAlertProps {
  error: GpError;
  onClose?: () => void;
  /** Heading override; defaults to a GP-write phrasing. */
  title?: string;
}

/**
 * Persistent, detailed, screenshot-friendly display of a GP/eConnect failure (issue #187). Unlike the
 * transient toast, this stays until dismissed and shows the full detail the backend forwards from the
 * relay - message, code, GP proc, error state, description - so the end user can screenshot or copy it.
 */
export default function GpErrorAlert({ error, onClose, title }: GpErrorAlertProps) {
  const [copied, setCopied] = useState(false);
  const ctx = error.relay?.context ?? {};
  const rows: [string, string][] = [];
  if (error.code) rows.push(['Code', error.code]);
  if (error.relay?.error) rows.push(['Relay', error.relay.error]);
  if (ctx.proc) rows.push(['GP proc', String(ctx.proc)]);
  if (ctx.error_state != null) rows.push(['Error state', String(ctx.error_state)]);
  if (ctx.error_description) rows.push(['Description', String(ctx.error_description)]);

  const copy = async () => {
    try {
      await navigator.clipboard?.writeText(formatGpErrorText(error));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may be unavailable; the on-screen detail is still screenshot-able */
    }
  };

  return (
    <Alert severity="error" onClose={onClose} sx={{ '& .MuiAlert-message': { width: '100%' } }}>
      <AlertTitle>{title ?? 'GP could not complete this operation'}</AlertTitle>
      <Box sx={{ fontWeight: 600, mb: rows.length ? 1 : 0, wordBreak: 'break-word' }}>{error.message}</Box>
      {rows.length > 0 && (
        <Box
          component="table"
          sx={{ fontFamily: 'monospace', fontSize: 12.5, borderCollapse: 'collapse', mb: 1, width: '100%' }}
        >
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td
                  style={{
                    color: 'rgba(0,0,0,0.55)',
                    paddingRight: 12,
                    verticalAlign: 'top',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {k}
                </td>
                <td style={{ wordBreak: 'break-word' }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </Box>
      )}
      <Button
        size="small"
        color="inherit"
        startIcon={copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
        onClick={copy}
      >
        {copied ? 'Copied' : 'Copy details'}
      </Button>
    </Alert>
  );
}
