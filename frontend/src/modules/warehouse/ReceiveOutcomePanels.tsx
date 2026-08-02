import { Alert, Box, Typography } from '@mui/material';
import { monoSx } from '../../theme';

/**
 * What a posted (or queued) GP receipt looks like when it comes back.
 *
 * These moved here from ReceiveModal when receives were split into a draft and an approval: posting
 * to GP happens at approval now, so the panels that report it belong to the approval screen. The
 * copy is unchanged - it is what the relay-offline path has been telling people since #353 PR E, and
 * the GP receipt number it shows is the one moment that number is in front of the person holding the
 * packing slip (#447).
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

/** The relay was down: the receipt is on the durable outbox and will post itself (#353 PR E). */
export function ReceiveQueuedAlert({
  count = 1,
  receipts = [],
}: {
  count?: number;
  receipts?: PostedReceipt[];
}) {
  return (
    <Alert severity="warning" sx={{ mb: 2 }}>
      Queued — the GP relay is offline. {count === 1 ? 'This receipt' : `These ${count} receipts`} will post
      automatically when it reconnects; you don't need to redo it. The hardware will appear in inventory once it
      posts.
      {/* A batch can be part queued and part posted - the relay can drop between two POs. The ones
          that made it still have GP numbers, and this is still the only place to read them. */}
      <PostedReceiptLines receipts={receipts} namePo />
    </Alert>
  );
}

/** It posted: GP numbered the receipt and the hardware is in inventory. */
export function ReceivePostedAlert({
  itemCount,
  receipts,
}: {
  itemCount: number;
  receipts: PostedReceipt[];
}) {
  return (
    <Alert severity="success" sx={{ mb: 2 }}>
      Receive completed successfully! {itemCount} items added to inventory.
      {/* #447: GP numbered the receipt on the way in, and this is the only moment it is in front of
          the person holding the packing slip. */}
      <PostedReceiptLines receipts={receipts} namePo={receipts.length > 1} />
    </Alert>
  );
}
