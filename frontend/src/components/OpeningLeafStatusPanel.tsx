import { useMemo, useState } from 'react';
import {
  Box,
  Typography,
  Chip,
  Stack,
  Skeleton,
  Alert,
  TextField,
  Button,
  InputAdornment,
} from '@mui/material';
import { Search } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { GET_OPENING_LEAF_STATUS } from '../graphql/shared';
import { microLabelSx, monoSx, tabularSx } from '../theme';

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
    <Box
      sx={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 0.75,
        alignItems: 'center',
        py: 0.625,
        borderBottom: 1,
        borderColor: 'divider',
        '&:last-of-type': { borderBottom: 0 },
      }}
    >
      <Chip
        size="small"
        color={summaryColor(done, row.leafCount)}
        // Single-leaf doors are the common case; "1 of 1 leaves" reads as a machine talking.
        label={`Opening ${row.openingNumber}: ${done} of ${row.leafCount} ${
          row.leafCount === 1 ? 'leaf' : 'leaves'
        } ${verb}`}
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

/** Rows shown per project group before the "Show N more" tail. Same windowing the shipping browse
 *  uses: a schedule-sized project renders hundreds of openings, and a wall of them buries whatever
 *  sits below this panel. Search is the way to a specific opening; the tail is the way to the rest. */
const WINDOW_SIZE = 30;

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

  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const rows = useMemo(() => data?.openingLeafStatus ?? [], [data]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.openingNumber.toLowerCase().includes(q));
  }, [rows, search]);

  // Group by project only when asked (global view). Key on projectId, not projectName - two projects
  // can share a description, and the backend carries project_id precisely so their same-numbered
  // openings don't collide under one subheader. Rows arrive sorted by project name then opening.
  const groups = useMemo(() => {
    if (!grouped) return [{ projectId: '', projectName: '', rows: filtered }];
    const byProject = new Map<string, { projectName: string; rows: OpeningLeafStatusRow[] }>();
    for (const r of filtered) {
      const g = byProject.get(r.projectId) ?? { projectName: r.projectName, rows: [] };
      g.rows.push(r);
      byProject.set(r.projectId, g);
    }
    return Array.from(byProject.entries()).map(([projectId, g]) => ({
      projectId,
      projectName: g.projectName,
      rows: g.rows,
    }));
  }, [filtered, grouped]);

  if (loading && !data) {
    // Skeletons shaped like the rows they become (DESIGN.md: skeletons over spinners).
    return (
      <Box sx={{ mb: 2 }}>
        <Skeleton width={110} height={14} sx={{ mb: 1 }} />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} height={26} sx={{ mb: 0.5, maxWidth: 480 }} />
        ))}
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading door-leaf status: {error.message}</Alert>;
  }

  if (rows.length === 0) return null;

  const verb = mode === 'shipping' ? 'shipped' : 'assembled';

  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
        <Typography component="div" sx={microLabelSx}>
          {title}
        </Typography>
        {rows.length > WINDOW_SIZE && (
          <TextField
            size="small"
            placeholder="Search opening #"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            // Same affordance as the shipping browse: search glyph in, mono for the identifier.
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <Search size={16} strokeWidth={1.75} />
                  </InputAdornment>
                ),
                sx: monoSx,
              },
              htmlInput: { 'aria-label': 'Search opening number' },
            }}
            sx={{ width: { xs: '100%', sm: 200 } }}
          />
        )}
      </Stack>
      {filtered.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No openings match &ldquo;{search.trim()}&rdquo;.
        </Typography>
      ) : (
        <Stack spacing={grouped ? 1.5 : 0.5}>
          {groups.map((group) => {
            const key = group.projectId || 'all';
            const isExpanded = expanded[key] || !!search.trim();
            const visible = isExpanded ? group.rows : group.rows.slice(0, WINDOW_SIZE);
            const hidden = group.rows.length - visible.length;
            // The group's own N-of-M, so a windowed group still tells its whole story on one line.
            const leafTotal = group.rows.reduce((n, r) => n + r.leafCount, 0);
            const leafDone = group.rows.reduce((n, r) => n + completedCount(r.leaves, mode), 0);
            return (
              <Box key={key}>
                {grouped && group.projectName && (
                  <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mb: 0.5 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {group.projectName}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                      {leafDone} of {leafTotal} {leafTotal === 1 ? 'leaf' : 'leaves'} {verb}
                    </Typography>
                  </Stack>
                )}
                <Stack spacing={0.5}>
                  {visible.map((r) => (
                    <OpeningRow key={`${r.projectId}-${r.openingNumber}`} row={r} mode={mode} />
                  ))}
                </Stack>
                {hidden > 0 && (
                  <Button
                    size="small"
                    onClick={() => setExpanded((prev) => ({ ...prev, [key]: true }))}
                    sx={{ mt: 0.5 }}
                  >
                    Show {hidden} more of {group.rows.length}
                  </Button>
                )}
              </Box>
            );
          })}
        </Stack>
      )}
    </Box>
  );
}
