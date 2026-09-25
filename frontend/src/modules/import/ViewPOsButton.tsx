import { useState } from 'react';
import { useQuery } from '@apollo/client/react';
import { Alert, Box, Chip, CircularProgress, IconButton, Link, Popover, Tooltip, Typography } from '@mui/material';
import { ListTree } from 'lucide-react';
import { GET_PROJECT_PRODUCT_PO_LINES } from '../../graphql/import';
import { formatPoStatus, poStatusChipColor } from '../po/poStatus';
import { monoSx, tabularSx } from '../../theme';
import { linesBehindFigure, poTableHref } from './viewPOs';
import type { ProductPOLine, ViewPOsFigure } from './viewPOs';

const FIGURE_LABEL: Record<ViewPOsFigure, string> = { ordered: 'Ordered', onOrder: 'On order' };

interface ViewPOsButtonProps {
  projectId: string;
  hardwareCategory: string;
  productCode: string;
  figure: ViewPOsFigure;
  /** The figure beside the button. Nothing to list at 0, so the button is not rendered. */
  count: number;
}

/**
 * #732: a small list icon after an Ordered / On Order figure. Clicking it opens a popover listing the
 * placed POs that make up the figure, each with its share and a link that opens the PO in the PO
 * table in a new tab, so the wizard keeps its place. The POs are fetched only when the popover opens.
 */
export default function ViewPOsButton({ projectId, hardwareCategory, productCode, figure, count }: ViewPOsButtonProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const open = anchor !== null;

  const { data, loading, error } = useQuery<{ projectProductPoLines: ProductPOLine[] }>(GET_PROJECT_PRODUCT_PO_LINES, {
    variables: { projectId, hardwareCategory, productCode },
    skip: !open,
    fetchPolicy: 'cache-and-network',
  });

  if (count <= 0) return null;

  const rows = linesBehindFigure(data?.projectProductPoLines ?? [], figure);
  const total = rows.reduce((sum, r) => sum + r.quantity, 0);

  return (
    <>
      <Tooltip title="View POs">
        <IconButton
          size="small"
          aria-label={`View POs behind ${FIGURE_LABEL[figure].toLowerCase()} ${productCode}`}
          onClick={(e) => {
            // The reconciliation grid selects a row on click; the button is not a row click.
            e.stopPropagation();
            setAnchor(e.currentTarget);
          }}
          sx={{ p: 0.25, ml: 0.25, color: 'text.secondary' }}
        >
          <ListTree size={14} strokeWidth={1.75} />
        </IconButton>
      </Tooltip>
      <Popover
        open={open}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        onClick={(e) => e.stopPropagation()}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Box sx={{ p: 1.5, minWidth: 240, maxWidth: 360 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
            {FIGURE_LABEL[figure]} · <Box component="span" sx={monoSx}>{productCode}</Box>
          </Typography>
          {loading && !data ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 1 }}>
              <CircularProgress size={18} />
            </Box>
          ) : error ? (
            <Alert severity="error" sx={{ py: 0 }}>
              Could not load the POs.
            </Alert>
          ) : rows.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No placed POs.
            </Typography>
          ) : (
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1fr) auto auto',
                columnGap: 1.5,
                rowGap: 0.5,
                alignItems: 'center',
              }}
            >
              {rows.map(({ line, quantity }) => (
                <Box key={line.poId} sx={{ display: 'contents' }}>
                  <Link
                    href={poTableHref(line.poId)}
                    target="_blank"
                    rel="noopener noreferrer"
                    variant="body2"
                    sx={{ ...monoSx, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {line.poNumber ?? line.requestNumber ?? 'PO'}
                  </Link>
                  <Chip size="small" label={formatPoStatus(line.status)} color={poStatusChipColor(line.status)} />
                  <Typography variant="body2" sx={{ ...tabularSx, textAlign: 'right' }}>
                    {quantity}
                  </Typography>
                </Box>
              ))}
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ gridColumn: '1 / 3', borderTop: '1px solid', borderColor: 'divider', pt: 0.5 }}
              >
                Total
              </Typography>
              <Typography
                variant="body2"
                sx={{ ...tabularSx, textAlign: 'right', borderTop: '1px solid', borderColor: 'divider', pt: 0.5 }}
              >
                {total}
              </Typography>
            </Box>
          )}
        </Box>
      </Popover>
    </>
  );
}
