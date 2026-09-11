import { useMemo, useState } from 'react';
import { Box, Button, Chip, Stack, TextField, Typography } from '@mui/material';
import RegisterGpBuyerDialog from './RegisterGpBuyerDialog';
import type { GpBuyersState } from './useGpBuyers';
import { monoSx } from '../../theme';

interface GpIdentityChooserProps {
  /** The shared buyer list state, read for the company chosen in the dialog. */
  state: GpBuyersState;
  /** The buyer id picked in this chooser session, or null while nothing is picked. */
  picked: string | null;
  onPick: (buyerId: string) => void;
  /** A buyer just registered in GP, which the caller commits before returning to the summary. */
  onRegistered: (buyerId: string) => void;
}

/**
 * Pick a GP buyer identity from GP's live buyer master (#409, reshaped by #699).
 *
 * This is the body of the Edit User dialog while the admin is choosing, not a dialog of its own, so
 * the whole width of the dialog goes to the buyer ids and every registered id is visible at once
 * instead of hiding behind a dropdown. The caller owns the picked value, because the dialog's own
 * actions are what commit it.
 *
 * Nothing here ever proposes, ranks or preselects a buyer. A buyer id is not derivable from a name or
 * an email - the production companies hold values like 'donr' next to 'Anna Wyzynski' - and a wrong
 * one is written to Clerk and sits there looking correct until someone tries to raise a PO (taPoHdr
 * rejects an unregistered BUYERID with error 269). The admin chooses, or nothing is chosen.
 *
 * The description GP holds against a buyer is deliberately not shown. The ruling for #699 is that
 * the id alone is what the admin picks by, so the id alone is what the chooser lists.
 */
export default function GpIdentityChooser({ state, picked, onPick, onRegistered }: GpIdentityChooserProps) {
  const [filter, setFilter] = useState('');
  const [registerOpen, setRegisterOpen] = useState(false);
  const { buyers, company } = state;

  const query = filter.trim().toLowerCase();
  const shown = useMemo(
    () => (query ? buyers.filter((b) => b.buyerId.toLowerCase().includes(query)) : buyers),
    [buyers, query],
  );

  return (
    <>
      <Stack spacing={1.5} sx={{ minWidth: 0 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 2, minWidth: 0 }}>
          <TextField
            label="Filter buyer ids"
            placeholder="Type part of an id"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            size="small"
            sx={{ flex: '1 1 220px', minWidth: 0 }}
          />
          <Typography variant="body2" color="text.secondary">
            {query
              ? `${shown.length} of ${buyers.length} buyers`
              : `${buyers.length} buyers registered in ${company}`}
          </Typography>
        </Box>

        {/* The two empty cases read differently: a filter that matched nothing is cleared, an empty
            buyer master is filled. Telling someone to clear a filter they never typed is a dead end. */}
        {buyers.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No buyers are registered in {company} yet. Register one below.
          </Typography>
        ) : shown.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No registered buyer matches that filter. Clear the filter, or register a new GP buyer.
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, minWidth: 0 }}>
            {shown.map((b) => {
              const isPicked = picked === b.buyerId;
              return (
                <Chip
                  key={b.buyerId}
                  label={b.buyerId}
                  onClick={() => onPick(b.buyerId)}
                  aria-pressed={isPicked}
                  color={isPicked ? 'primary' : 'default'}
                  variant={isPicked ? 'filled' : 'outlined'}
                  sx={monoSx}
                />
              );
            })}
          </Box>
        )}

        <Box
          sx={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 2,
            minWidth: 0,
            pt: 1,
            borderTop: 1,
            borderColor: 'divider',
          }}
        >
          <Button size="small" onClick={() => setRegisterOpen(true)}>
            + Register new GP buyer&hellip;
          </Button>
          <Typography variant="body2" color="text.secondary">
            {picked ? (
              <>
                Picked:{' '}
                <Box component="span" sx={monoSx}>
                  {picked}
                </Box>
              </>
            ) : (
              'Nothing picked yet. Click a buyer.'
            )}
          </Typography>
        </Box>
      </Stack>
      <RegisterGpBuyerDialog
        open={registerOpen}
        company={company}
        onClose={() => setRegisterOpen(false)}
        onRegistered={onRegistered}
      />
    </>
  );
}
