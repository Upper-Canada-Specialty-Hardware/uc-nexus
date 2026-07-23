import { useMemo } from 'react';
import { Box, Typography, Chip, Stack, CircularProgress, Alert } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_OPENING_LEAF_STATUS } from '../graphql/shared';

// Per-opening door-leaf rollup (#313). Shared between the shipping (project-scoped) and shop-assembly
// (global, grouped by project) views; `mode` reframes the N-of-M summary, `grouped` toggles the
// per-project subheaders.

type LeafStatusValue = 'NOT_ASSEMBLED' | 'IN_INVENTORY' | 'SHIP_READY' | 'SHIPPED_OUT';

interface LeafState {
  leaf: number;
  status: LeafStatusValue;
}

interface OpeningLeafStatusRow {
  projectId: string;
  projectName: string;
  openingNumber: string;
  leafCount: number;
  leaves: LeafState[];
}

type ChipColor = 'default' | 'info' | 'warning' | 'success';

const LEAF_STATUS_DISPLAY: Record<LeafStatusValue, { label: string; color: ChipColor }> = {
  NOT_ASSEMBLED: { label: 'Not assembled', color: 'default' },
  IN_INVENTORY: { label: 'In inventory', color: 'info' },
  SHIP_READY: { label: 'Ship ready', color: 'warning' },
  SHIPPED_OUT: { label: 'Shipped out', color: 'success' },
};

interface OpeningLeafStatusPanelProps {
  /** Scopes the rollup to one project (shipping). Omit for the global shop-assembly view. */
  projectId?: string;
  /** Reframes the N-of-M summary: "assembled" counts any assembled leaf, "shipped" counts shipped-out. */
  mode: 'assembly' | 'shipping';
  /** Group rows under per-project subheaders (global shop-assembly view). */
  grouped?: boolean;
  title?: string;
}

// N of the "N of M" summary. Assembly counts every leaf that has left NOT_ASSEMBLED (an OpeningItem
// exists); shipping counts only leaves already shipped out.
function completedCount(leaves: LeafState[], mode: 'assembly' | 'shipping'): number {
  return leaves.filter((l) =>
    mode === 'shipping' ? l.status === 'SHIPPED_OUT' : l.status !== 'NOT_ASSEMBLED',
  ).length;
}

function summaryColor(done: number, total: number): ChipColor {
  if (done >= total) return 'success';
  if (done > 0) return 'warning';
  return 'default';
}

function OpeningRow({ row, mode }: { row: OpeningLeafStatusRow; mode: 'assembly' | 'shipping' }) {
  const done = completedCount(row.leaves, mode);
  const verb = mode === 'shipping' ? 'shipped' : 'assembled';
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center', py: 0.5 }}>
      <Chip
        size="small"
        color={summaryColor(done, row.leafCount)}
        label={`Opening ${row.openingNumber}: ${done} of ${row.leafCount} leaves ${verb}`}
      />
      {[...row.leaves]
        .sort((a, b) => a.leaf - b.leaf)
        .map((l) => {
          const d = LEAF_STATUS_DISPLAY[l.status] ?? { label: l.status, color: 'default' as ChipColor };
          return (
            <Chip
              key={l.leaf}
              size="small"
              variant="outlined"
              color={d.color}
              label={`Leaf ${l.leaf}: ${d.label}`}
            />
          );
        })}
    </Box>
  );
}

export default function OpeningLeafStatusPanel({
  projectId,
  mode,
  grouped = false,
  title = 'Door-leaf status',
}: OpeningLeafStatusPanelProps) {
  const { data, loading, error } = useQuery<{ openingLeafStatus: OpeningLeafStatusRow[] }>(
    GET_OPENING_LEAF_STATUS,
    { variables: { projectId: projectId ?? null }, fetchPolicy: 'cache-and-network' },
  );

  const rows = useMemo(() => data?.openingLeafStatus ?? [], [data]);

  // Group by project only when asked (global view). Key on projectId, not projectName - two projects
  // can share a description, and the backend carries project_id precisely so their same-numbered
  // openings don't collide under one subheader. Rows arrive sorted by project name then opening.
  const groups = useMemo(() => {
    if (!grouped) return [{ projectId: '', projectName: '', rows }];
    const byProject = new Map<string, { projectName: string; rows: OpeningLeafStatusRow[] }>();
    for (const r of rows) {
      const g = byProject.get(r.projectId) ?? { projectName: r.projectName, rows: [] };
      g.rows.push(r);
      byProject.set(r.projectId, g);
    }
    return Array.from(byProject.entries()).map(([projectId, g]) => ({
      projectId,
      projectName: g.projectName,
      rows: g.rows,
    }));
  }, [rows, grouped]);

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
        <CircularProgress size={20} />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading door-leaf status: {error.message}</Alert>;
  }

  if (rows.length === 0) return null;

  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
        {title}
      </Typography>
      <Stack spacing={grouped ? 1.5 : 0.5}>
        {groups.map((group) => (
          <Box key={group.projectId || 'all'}>
            {grouped && group.projectName && (
              <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                {group.projectName}
              </Typography>
            )}
            <Stack spacing={0.5}>
              {group.rows.map((r) => (
                <OpeningRow key={`${r.projectId}-${r.openingNumber}`} row={r} mode={mode} />
              ))}
            </Stack>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
