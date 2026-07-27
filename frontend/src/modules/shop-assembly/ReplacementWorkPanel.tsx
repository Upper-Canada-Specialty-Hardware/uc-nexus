import { useCallback, useState } from 'react';
import { Alert, Box, Button, Chip, Paper, Stack, Typography } from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { GET_REPLACEMENT_WORK, INSTALL_REPLACEMENT } from '../../graphql/shop-assembly';
import {
  REPLACEMENT_INSTALL_REFETCH_QUERIES,
  REPLACEMENT_INSTALL_STALE_ROOT_FIELDS,
} from '../../graphql/refetch';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { leafSuffix } from '../../utils/leaf';

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
  /** Recorded as the performer on the install audit row. */
  performedBy?: string;
}

/**
 * Replacement installs outstanding on leaves this assembler already finished (#341).
 *
 * These cannot ride in the My Work grid above: those rows are unfinished ShopAssemblyOpenings, and
 * the leaf here is COMPLETED and stays that way. It is a narrower unit of work - "fit these N units
 * to a leaf that is otherwise done" - so it gets its own section rather than reopening a finished
 * work unit or pretending the leaf is in progress.
 *
 * A row whose leaf has already shipped is still listed, because the hardware is real and must not be
 * silently stranded; it just cannot be installed from here.
 */
export default function ReplacementWorkPanel({ assignedToUserId, performedBy }: ReplacementWorkPanelProps) {
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
          performedBy,
        },
      },
    });
    if (result.data) {
      showToast(
        `Installed ${row.pendingQuantity} x ${row.productCode} on Opening ${row.openingNumber}${leafSuffix(row.leaf)}`,
        'success',
      );
    }
  }, [pending, installReplacement, performedBy, showToast]);

  const rows = data?.replacementWork ?? [];
  if (!assignedToUserId || loading || rows.length === 0) return null;

  return (
    <Box sx={{ mt: 4 }}>
      <Typography variant='h6' gutterBottom>
        Replacement Installs
      </Typography>
      <Typography variant='body2' color='text.secondary' sx={{ mb: 2 }}>
        Replacement hardware has arrived for leaves you already finished. Fit it, then record it here
        so the leaf's hardware list matches what is actually on it.
      </Typography>

      <Stack spacing={1.5}>
        {rows.map((row) => {
          const shipped = row.openingItemState === 'SHIPPED_OUT';
          return (
            <Paper key={row.shopAssemblyOpeningItemId} variant='outlined' sx={{ p: 2 }}>
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 2,
                  flexWrap: 'wrap',
                }}
              >
                <Box>
                  <Typography variant='subtitle2' sx={{ fontWeight: 600 }}>
                    Opening {row.openingNumber}
                    {leafSuffix(row.leaf)}
                  </Typography>
                  <Typography variant='body2' color='text.secondary'>
                    {row.pendingQuantity} x {row.productCode} ({row.hardwareCategory})
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Chip size='small' variant='outlined' label={`${row.pendingQuantity} awaiting install`} />
                  {shipped ? (
                    <Chip size='small' variant='outlined' color='warning' label='Leaf already shipped' />
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
            </Paper>
          );
        })}
      </Stack>

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
