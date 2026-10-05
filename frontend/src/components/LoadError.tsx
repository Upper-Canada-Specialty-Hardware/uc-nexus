import { Alert, Button } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { userMessage } from '../graphql/userMessage';

interface LoadErrorProps {
  /** What failed to load, in the reader's words: "the shipping requests", "this project's schedule". */
  what: string;
  /** The query's error. Shown through userMessage (#1553): a network failure in plain words, not Apollo's. */
  error: unknown;
  /** Re-runs the read - usually the query's refetch. A retry that fails again leaves this banner up
   *  (the query keeps its error), so the rejection is swallowed here rather than left unhandled. */
  onRetry?: () => unknown;
  sx?: SxProps<Theme>;
}

/**
 * A read that failed (#1503). Every list here has an empty state - "nothing waiting", "no schedule on
 * file" - and a failed read must never wear it: on a tablet with poor wifi the worker reads "nothing to
 * do" and moves on, or re-uploads a schedule that is already on file. This says the read failed and
 * offers it again, and the screen checks it before any empty state.
 */
export default function LoadError({ what, error, onRetry, sx }: LoadErrorProps) {
  return (
    <Alert
      severity="error"
      sx={sx}
      action={
        onRetry ? (
          <Button color="inherit" size="small" onClick={() => void Promise.resolve(onRetry()).catch(() => undefined)}>
            Retry
          </Button>
        ) : undefined
      }
    >
      Couldn&apos;t load {what}, so this is not an empty list - the read failed. {userMessage(error, { reading: true })}
      {/* #1561: the read line promises no button; this banner has one, so it says so. */}
      {onRetry ? ' Press Retry when the connection is back.' : null}
    </Alert>
  );
}
