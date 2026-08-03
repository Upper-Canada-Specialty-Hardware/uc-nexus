import { Box, Typography } from '@mui/material';
import { monoSx } from '../../theme';

/**
 * What a posted GP receipt looks like when it comes back.
 *
 * This moved here from ReceiveModal when receives were split into a draft and an approval: posting
 * to GP happens at approval now, so what reports it belongs beside the approval screen. The GP
 * receipt number it shows is the one moment that number is in front of anybody without opening GP
 * (#447).
 */

/**
 * What GP called each receipt that posted (#447). `receiptNumber` is nullable on the schema, so a
 * receive that committed without one still gets a row - the PO is named either way, and the missing
 * number reads as a gap rather than a missing PO.
 */
export interface PostedReceipt {
  poId: string;
  poNumber: string | null;
  receiptNumber: string | null;
}

/**
 * One line per receipt. `namePo` puts the PO number in front, which the caller asks for whenever the
 * batch is not uniform: with a failure or a queued receipt alongside it, "which PO is this the
 * receipt for" is the whole question.
 */
export function PostedReceiptLines({ receipts, namePo }: { receipts: PostedReceipt[]; namePo: boolean }) {
  if (receipts.length === 0) return null;
  return (
    <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 0.25 }}>
      {receipts.map((r) => (
        <Typography key={r.poId} variant="body2">
          {namePo && (
            <Box component="span" sx={{ ...monoSx, mr: 0.75 }}>
              {r.poNumber ?? 'PO'}
            </Box>
          )}
          {r.receiptNumber ? (
            <>
              GP Receipt{' '}
              <Box component="span" sx={{ ...monoSx, fontWeight: 700 }}>
                {r.receiptNumber}
              </Box>
            </>
          ) : (
            // Committed in GP but the response carried no number. Saying so beats printing a dash
            // the user reads as "nothing posted".
            <Box component="span" sx={{ color: 'text.secondary' }}>
              GP receipt number unavailable
            </Box>
          )}
        </Typography>
      ))}
    </Box>
  );
}

// There were wrapper components here for the queued and posted alerts. They had exactly one
// possible caller, ReceiveDraftReviewModal, which renders both inline because its copy is about
// approving one draft rather than completing a batch - so the wrappers were dead the day they were
// written and their copy had already started to drift from the live version. Deleted rather than
// adopted: one place to change a string beats two that agree today.
