import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { Alert, Box, Button, Chip, Paper, TableCell, TableRow, Typography } from '@mui/material';
import { ArrowRight } from 'lucide-react';
import FitTable, { type FitTableColumn } from '../../components/FitTable';
import LoadError from '../../components/LoadError';
import { GET_STAGING_OVERVIEW } from '../../graphql/shipping';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import type { StagingProjectSummary } from './staging';

// Minimums hold an opening number, a category, a product code and three counts whole; the product
// takes the slack and ellipsizes with the full value on hover.
const LINE_COLUMNS: FitTableColumn[] = [
  { id: 'opening', label: 'Opening', min: 80, weight: 0.6 },
  { id: 'category', label: 'Category', min: 90, weight: 0.8 },
  { id: 'product', label: 'Product', min: 110, weight: 1.6 },
  { id: 'staged', label: 'Staged', min: 64, weight: 0.4, align: 'right' },
  { id: 'placed', label: 'In containers', min: 104, weight: 0.5, align: 'right' },
  { id: 'loose', label: 'Loose', min: 60, weight: 0.4, align: 'right' },
];

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? '' : 's'}`;
}

function ProjectGroup({ summary, onOpen }: { summary: StagingProjectSummary; onOpen: (projectId: string) => void }) {
  const units = summary.looseItems.reduce((s, l) => s + l.stagedQuantity, 0);
  const loose = summary.looseItems.reduce((s, l) => s + l.unplacedQuantity, 0);
  const name = summary.projectDescription || summary.projectNumber;
  return (
    <Paper variant="outlined" sx={{ p: 2, minWidth: 0 }} data-testid={`staging-group-${summary.projectId}`}>
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, mb: 1.5, minWidth: 0 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
            <Typography noWrap sx={{ fontWeight: 700, minWidth: 0 }} title={name}>
              {name}
            </Typography>
            {summary.projectDescription && (
              <Chip size="small" variant="outlined" label={summary.projectNumber} sx={{ ...monoSx, flexShrink: 0 }} />
            )}
          </Box>
          <Typography variant="caption" color="text.secondary" sx={tabularSx}>
            {plural(units, 'unit')} staged · {loose} loose
            {summary.openContainerCount > 0 && ` · ${plural(summary.openContainerCount, 'open container')}`}
          </Typography>
        </Box>
        <Button
          size="small"
          variant="outlined"
          endIcon={<ArrowRight size={16} strokeWidth={1.75} />}
          onClick={() => onOpen(summary.projectId)}
          sx={{ flexShrink: 0 }}
        >
          Open
        </Button>
      </Box>
      {summary.looseItems.length > 0 ? (
        <FitTable storageKey="shipping.staging-overview" columns={LINE_COLUMNS}>
          {summary.looseItems.map((line) => (
            <TableRow key={`${line.openingNumber ?? ''}|${line.hardwareCategory}|${line.productCode}`} hover>
              <TableCell sx={monoSx}>{line.openingNumber ?? '—'}</TableCell>
              <TableCell title={line.hardwareCategory}>{line.hardwareCategory}</TableCell>
              <TableCell sx={monoSx} title={line.productCode}>
                {line.productCode}
              </TableCell>
              <TableCell align="right" sx={tabularSx}>
                {line.stagedQuantity}
              </TableCell>
              <TableCell align="right" sx={tabularSx}>
                {line.placedQuantity}
              </TableCell>
              <TableCell align="right" sx={{ ...tabularSx, fontWeight: line.unplacedQuantity > 0 ? 700 : 400 }}>
                {line.unplacedQuantity}
              </TableCell>
            </TableRow>
          ))}
        </FitTable>
      ) : (
        <Typography variant="body2" color="text.secondary">
          Nothing staged is left loose; its open containers hold only manual lines.
        </Typography>
      )}
    </Paper>
  );
}

/**
 * The staging floor across every project (#1698), which is what the page shows before a project is
 * picked. Staging used to open blank until somebody typed a job into the picker, which assumed the
 * person at the dock already knew which job had something waiting - the one thing this answers.
 */
export default function StagingOverview({ onOpen }: { onOpen: (projectId: string) => void }) {
  const { data, loading, error, refetch } = useQuery<{ stagingOverview: StagingProjectSummary[] }>(
    GET_STAGING_OVERVIEW,
    { fetchPolicy: 'cache-and-network' },
  );
  const summaries = useMemo(() => data?.stagingOverview ?? [], [data]);

  if (error && !data) {
    return <LoadError what="the staged hardware" error={error} onRetry={() => refetch()} />;
  }
  if (loading && !data) {
    return (
      <Typography variant="body2" color="text.secondary">
        Reading the staging floor...
      </Typography>
    );
  }
  if (summaries.length === 0) {
    return (
      <Alert severity="info">
        Nothing is staged. Hardware arrives here once its shipping pull has been picked and sent to staging.
      </Alert>
    );
  }

  return (
    <Box>
      <Typography component="div" sx={{ ...microLabelSx, mb: 1.5 }}>
        Staged across {plural(summaries.length, 'project')} - open one to load its containers
      </Typography>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0, 1fr))' },
          gap: 2,
          alignItems: 'start',
        }}
      >
        {summaries.map((s) => (
          <ProjectGroup key={s.projectId} summary={s} onOpen={onOpen} />
        ))}
      </Box>
    </Box>
  );
}
