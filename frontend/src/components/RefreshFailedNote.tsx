import { Alert } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { userMessage } from '../graphql/userMessage';

interface RefreshFailedNoteProps {
  /** What was being refreshed, in the reader's words: "the inventory", "this project". */
  what: string;
  error: unknown;
  sx?: SxProps<Theme>;
}

/**
 * A refresh that failed over data already on screen (#1584). Apollo keeps the last read beside the error, so
 * the screen keeps showing it - replacing loaded rows with an error hid work in progress - and this says the
 * figures may be out of date. A read that never loaded anything gets LoadError, with its Retry, instead.
 */
export default function RefreshFailedNote({ what, error, sx }: RefreshFailedNoteProps) {
  return (
    <Alert severity="warning" sx={[{ mb: 2 }, ...(Array.isArray(sx) ? sx : [sx])]}>
      Couldn&apos;t refresh {what} - this is the last copy that loaded. {userMessage(error, { reading: true })}
    </Alert>
  );
}
