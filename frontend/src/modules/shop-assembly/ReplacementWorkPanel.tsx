import { useCallback, useState } from 'react';
import { Alert, Box, Button, Chip, Paper, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { GET_REPLACEMENT_WORK, INSTALL_REPLACEMENT } from '../../graphql/shop-assembly';
import {
  REPLACEMENT_INSTALL_REFETCH_QUERIES,
  REPLACEMENT_INSTALL_STALE_ROOT_FIELDS,
} from '../../graphql/refetch';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { leafSuffix } from '../../utils/leaf';
import { microLabelSx, monoSx } from '../../theme';
import { StaggerList, StaggerItem } from '../../motion';

export interface ReplacementWorkRow {
  shopAssemblyOpeningItemId: string;
  shopAssemblyOpeningId: string;
  openingNumber: string;
  leaf: number | null;
  building: string | null;
  floor: string | null;
  hardwareCategory: string;
  productCode: string;
  pendingQuantity: number;
  assignedTo: string | null;
  openingItemId: string | null;
  openingItemState: string | null;
}

interface ReplacementWorkPanelProps {
  /** The signed-in assembler; the panel shows only the work assigned to them. */
  assignedToUserId: string | null;
}

/**
 * Replacement installs outstanding on leaves this assembler already finished (#341).
 *
 * These cannot ride in the My Work grid above: those rows are unfinished ShopAssemblyOpenings, and
 * the leaf here is COMPLETED and stays that way. It is a narrower unit of work - "fit these N units
 * to a leaf that is otherwise done" - so it gets its own section rather than reopening a finished
 * work unit or pretending the leaf is in progress.
 *
 * A row whose leaf has already shipped, or is staged at the dock for a confirmed shipment, is still
 * listed, because the hardware is real and must not be silently stranded; it just cannot be
 * installed from here.
 */
export default function ReplacementWorkPanel({ assignedToUserId }: ReplacementWorkPanelProps) {
  const { showToast } = useToast();
  const [pending, setPending] = useState<ReplacementWorkRow | null>(null);

  const { data, loading } = useQuery<{ replacementWork: ReplacementWorkRow[] }>(GET_REPLACEMENT_WORK, {
    variables: { assignedToUserId },
    skip: !assignedToUserId,
  });

  const [installReplacement, { loading: installing }] = useMutation(INSTALL_REPLACEMENT, {
    update(cache) {
      for (const fieldName of REPLACEMENT_INSTALL_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    refetchQueries: REPLACEMENT_INSTALL_REFETCH_QUERIES,
    onError: (err) => showToast(err.message, 'error'),
  });

  const confirmInstall = useCallback(async () => {
    if (!pending) return;
    const row = pending;
    setPending(null);
    const result = await installReplacement({
      variables: {
        input: {
          shopAssemblyOpeningItemId: row.shopAssemblyOpeningItemId,
          // The whole pending quantity: the units arrived together on one pull line, and splitting
          // them would be an invented distinction the assembler has no way to act on.
          quantity: row.pendingQuantity,
        },
      },
    });
    if (result.data) {
      showToast(
        `Installed ${row.pendingQuantity} x ${row.productCode} on Opening ${row.openingNumber}${leafSuffix(row.leaf)}`,
        'success',
      );
    }
  }, [pending, installReplacement, showToast]);

  const rows = data?.replacementWork ?? [];
  if (!assignedToUserId || loading || rows.length === 0) return null;

  return (
    <Box sx={{ mt: 4, maxWidth: 900 }}>
      <Typography
        component='div'
        sx={{ ...microLabelSx, color: 'text.primary', mb: 0.5, pb: 0.75, borderBottom: 2, borderColor: 'text.primary' }}
      >
        Replacement Installs
      </Typography>
      <Typography variant='body2' color='text.secondary' sx={{ mb: 2 }}>
        Replacement hardware has arrived for leaves you already finished. Fit it, then record it here
        so the leaf's hardware list matches what is actually on it.
      </Typography>

      <StaggerList count={rows.length} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {rows.map((row) => {
          const shipped = row.openingItemState === 'SHIPPED_OUT';
          // SHIP_READY is the same refusal one step earlier, and the backend enforces it: the leaf is
          // picked and staged against a confirmed shipping-out pull, and `confirm_shipment` snapshots
          // its hardware onto the packing slip. Hardware added now would land on a slip for a unit
          // that was checked without it. Unlike the shipped case it is still recoverable - unwind the
          // shipping-out request and the button comes back - so it says so rather than reading as
          // terminal.
          const shipReady = row.openingItemState === 'SHIP_READY';
          const blocked = shipped || shipReady;
          return (
            <StaggerItem key={row.shopAssemblyOpeningItemId}>
              <Paper
                variant='outlined'
                sx={{
                  p: 2,
                  // A blocked row is a real system state, so it carries a status edge rather than
                  // looking identical to one that can just be ticked off.
                  ...(blocked && { borderLeft: '3px solid', borderLeftColor: 'warning.main' }),
                }}
              >
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 2,
                    flexWrap: 'wrap',
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    {/* One element, all mono: this is the leaf's identifier, and splitting it would
                        also split how the row is found. */}
                    <Typography variant='subtitle2' sx={{ ...monoSx, fontWeight: 600 }}>
                      Opening {row.openingNumber}
                      {leafSuffix(row.leaf)}
                    </Typography>
                    <Typography variant='body2' color='text.secondary'>
                      {row.pendingQuantity} x {row.productCode} ({row.hardwareCategory})
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Chip size='small' variant='outlined' label={`${row.pendingQuantity} awaiting install`} />
                    {blocked ? (
                      <Chip
                        size='small'
                        color='warning'
                        label={shipped ? 'Leaf already shipped' : 'Leaf staged for shipment'}
                      />
                    ) : (
                      <Button
                        size='small'
                        variant='contained'
                        disabled={installing}
                        onClick={() => setPending(row)}
                      >
                        Mark Installed
                      </Button>
                    )}
                  </Box>
                </Box>
                {shipped && (
                  <Alert severity='warning' sx={{ mt: 1.5 }}>
                    This leaf shipped before the replacement arrived, so the hardware cannot go on it
                    here. It needs a reallocation or a site shipment.
                  </Alert>
                )}
                {shipReady && (
                  <Alert severity='warning' sx={{ mt: 1.5 }}>
                    This leaf is staged for shipment, and its packing slip is built from what is on it
                    now. Unwind the shipping-out request first if the replacement has to go on before
                    it leaves; otherwise it needs a reallocation or a site shipment.
                  </Alert>
                )}
              </Paper>
            </StaggerItem>
          );
        })}
      </StaggerList>

      <ConfirmDialog
        open={pending !== null}
        title='Record replacement as installed?'
        message={
          pending
            ? `This adds ${pending.pendingQuantity} x ${pending.productCode} to Opening ` +
              `${pending.openingNumber}${leafSuffix(pending.leaf)}'s hardware list. Only do this once the ` +
              `hardware is physically on the leaf.`
            : ''
        }
        confirmLabel='Mark Installed'
        onConfirm={confirmInstall}
        onCancel={() => setPending(null)}
      />
    </Box>
  );
}
