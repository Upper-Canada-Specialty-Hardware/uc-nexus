import { useMemo, useState, useCallback, type ReactNode } from 'react';
import {
  Box,
  Typography,
  Chip,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Stack,
  Button,
} from '@mui/material';
import { ChevronDown } from 'lucide-react';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_ASSEMBLE_LIST, ASSIGN_OPENINGS, REMOVE_OPENING_FROM_USER } from '../../graphql/shop-assembly';
import { ASSIGNMENT_STALE_ROOT_FIELDS } from '../../graphql/refetch';
import { leafSuffix } from '../../utils/leaf';
import OpeningLeafStatusPanel from '../../components/OpeningLeafStatusPanel';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import AssemblyDetailModal from './AssemblyDetailModal';
import { assemblyProgress, assemblyStatusLabel, unitProgressLabel } from './openingFilters';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn, StaggerList, StaggerItem } from '../../motion';

// --- Types ---

interface AssembleOpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  // Owed by the schedule vs pulled for the bench. The three progress buckets partition
  // `allocatedQuantity`; `quantity - allocatedQuantity` was never pulled and is not outstanding work.
  quantity: number;
  allocatedQuantity: number;
  installedQuantity: number;
  deficientQuantity: number;
  // Arrived-but-not-yet-fitted replacement units (#341): the third bucket a line is partitioned
  // into, and part of the progress rollup's `remaining`.
  replacementPendingQuantity: number;
}

interface AssembleOpening {
  id: string;
  shopAssemblyRequestId: string;
  openingId: string;
  pullStatus: string;
  assignedToUserId: string | null;
  assignedTo: string | null;
  assemblyStatus: string;
  completedAt: string | null;
  leaf: number | null;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  items: AssembleOpeningItem[];
}

// --- Pull status config ---

interface PullStatusSection {
  key: string;
  label: string;
  badgeLabel: string;
  badgeColor: 'success' | 'warning' | 'error';
}

const PULL_STATUS_SECTIONS: PullStatusSection[] = [
  { key: 'PULLED', label: 'Pulled', badgeLabel: 'Ready', badgeColor: 'success' },
  { key: 'PARTIAL', label: 'Partial', badgeLabel: 'Waiting', badgeColor: 'warning' },
  { key: 'NOT_PULLED', label: 'Not Pulled', badgeLabel: 'Pending', badgeColor: 'error' },
];

// --- Component ---

export default function AssembleListPage() {
  const { displayName, userId } = useIdentity();
  const { showToast } = useToast();
  // The id, not the row: the modal saves progress and this list re-reads, and holding the object
  // would pin the modal to the pre-save snapshot (#340).
  const [completingId, setCompletingId] = useState<string | null>(null);

  const {
    data,
    loading,
    refetch,
  } = useQuery<{ assembleList: AssembleOpening[] }>(GET_ASSEMBLE_LIST);

  const openings = useMemo(() => data?.assembleList ?? [], [data]);
  const completing = useMemo(
    () => openings.find((o) => o.id === completingId) ?? null,
    [openings, completingId]
  );

  const [assignOpenings] = useMutation(ASSIGN_OPENINGS, {
    // Eviction only; `assembleList` is absent because this page refetches it itself in the
    // callbacks below (see refetch.ts). What that cannot reach is the assembler's own board and the
    // pipeline, both on other routes.
    update(cache) {
      for (const fieldName of ASSIGNMENT_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    onCompleted: () => {
      showToast('Assigned to you', 'success');
      refetch();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const [removeOpening] = useMutation(REMOVE_OPENING_FROM_USER, {
    // Eviction only; `assembleList` is absent because this page refetches it itself in the
    // callbacks below (see refetch.ts). What that cannot reach is the assembler's own board and the
    // pipeline, both on other routes.
    update(cache) {
      for (const fieldName of ASSIGNMENT_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    onCompleted: () => {
      showToast('Opening returned to available pool', 'success');
      refetch();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const claim = useCallback(
    (opening: AssembleOpening) => {
      if (!userId) {
        showToast('Still signing in - try again in a moment', 'error');
        return;
      }
      assignOpenings({
        variables: {
          input: { openingIds: [opening.id], assignedToUserId: userId, assignedTo: displayName },
        },
      });
    },
    [assignOpenings, userId, displayName, showToast]
  );

  // Per-opening assemble action, gated on the opening being pulled. Drives the assign -> complete
  // flow directly from this list (#324) so a user never has to bounce to the board / My Work.
  const renderActions = useCallback(
    (opening: AssembleOpening): ReactNode => {
      if (opening.pullStatus !== 'PULLED') return null;
      if (opening.assemblyStatus === 'COMPLETED') {
        return <Chip label="Assembled" color="success" size="small" />;
      }
      if (opening.assignedToUserId == null) {
        return (
          <Button size="small" variant="contained" onClick={() => claim(opening)}>
            Assign to me
          </Button>
        );
      }
      if (opening.assignedToUserId === userId) {
        return (
          <Stack direction="row" spacing={1}>
            <Button size="small" variant="contained" onClick={() => setCompletingId(opening.id)}>
              {opening.assemblyStatus === 'IN_PROGRESS' ? 'Continue assembly' : 'Start assembly'}
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={() => removeOpening({ variables: { openingId: opening.id } })}
            >
              Return
            </Button>
          </Stack>
        );
      }
      return (
        <Typography variant="body2" color="text.secondary">
          Assigned to {opening.assignedTo}
        </Typography>
      );
    },
    [claim, removeOpening, userId]
  );

  // Group openings by pullStatus
  const grouped = useMemo(() => {
    const groups: Record<string, AssembleOpening[]> = {
      PULLED: [],
      PARTIAL: [],
      NOT_PULLED: [],
    };
    for (const opening of openings) {
      const key = opening.pullStatus;
      if (key in groups) {
        groups[key].push(opening);
      } else {
        // Fallback: put unknown statuses in NOT_PULLED
        groups['NOT_PULLED'].push(opening);
      }
    }
    return groups;
  }, [openings]);

  // --- Render ---

  return (
    <Box>
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 0.5 }}>
          Assemble List
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Every approved door leaf, grouped by whether its hardware has actually arrived. Only the
          ready ones can be worked.
        </Typography>
      </FadeIn>

      {loading && !data && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Loading...
        </Typography>
      )}

      {!loading && data && openings.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          No approved shop assembly openings found for this project.
        </Alert>
      )}

      <Stack spacing={3}>
        {PULL_STATUS_SECTIONS.map((section) => {
          const sectionOpenings = grouped[section.key] ?? [];
          return (
            <Box key={section.key}>
              {/* Group header as a rule with a count on it: three groups have to be tellable apart
                  at a glance, and the badge is what says whether the group can be worked at all. */}
              <Stack
                direction="row"
                spacing={1}
                alignItems="center"
                sx={{ mb: 1, pb: 0.75, borderBottom: 2, borderColor: 'text.primary' }}
              >
                <Typography component="div" sx={{ ...microLabelSx, color: 'text.primary' }}>
                  {section.label}
                </Typography>
                <Chip label={section.badgeLabel} color={section.badgeColor} size="small" />
                <Typography variant="body2" color="text.secondary" sx={tabularSx}>
                  {sectionOpenings.length}
                </Typography>
              </Stack>

              {sectionOpenings.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  No openings in this category.
                </Typography>
              ) : (
                <StaggerList count={sectionOpenings.length}>
                  {sectionOpenings.map((opening) => {
                    const actions = renderActions(opening);
                    const progress = assemblyProgress(opening.items ?? []);
                    return (
                      <StaggerItem key={opening.id}>
                        <Accordion variant="outlined" sx={{ mb: 1 }}>
                          <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                            <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
                              {/* One element: an eyebrow plus the identifier in the mono face, but
                                  never split across elements - the accessible name of this summary is
                                  how the row is found. */}
                              <Typography component="div">
                                <Box component="span" sx={microLabelSx}>
                                  Opening:
                                </Box>
                                {/* A real space, as a text node of the summary itself: an accessible
                                    name is assembled from the flattened text of each child element,
                                    and whitespace inside a child span is trimmed away before the
                                    pieces are joined. */}
                                {' '}
                                <Box component="span" sx={{ ...monoSx, fontWeight: 600 }}>
                                  {(opening.openingNumber || opening.openingId) +
                                    leafSuffix(opening.leaf)}
                                </Box>
                              </Typography>
                              <Chip
                                label={formatPullStatus(opening.pullStatus)}
                                color={section.badgeColor}
                                size="small"
                                variant="outlined"
                              />
                              {/* Assembly state is separate from pull state - a leaf can be fully pulled
                                  and half built (#340). */}
                              <Chip
                                label={assemblyStatusLabel(opening.assemblyStatus)}
                                color={opening.assemblyStatus === 'IN_PROGRESS' ? 'info' : 'default'}
                                size="small"
                                variant="outlined"
                              />
                              <Typography variant="body2" color="text.secondary" sx={tabularSx}>
                                {unitProgressLabel(opening.items ?? [])}
                              </Typography>
                              {/* Owed but never pulled. Its own chip rather than part of the progress
                                  count: it is not outstanding work, and the leaf finishes without it. */}
                              {progress.short > 0 && (
                                <Chip
                                  label={`${progress.short} never pulled`}
                                  color="warning"
                                  size="small"
                                  variant="outlined"
                                />
                              )}
                            </Stack>
                          </AccordionSummary>
                          <AccordionDetails>
                            {actions && <Box sx={{ mb: 2 }}>{actions}</Box>}
                            {opening.items.length > 0 ? (
                              <Table size="small">
                                <TableHead>
                                  <TableRow>
                                    <TableCell>Product Code</TableCell>
                                    <TableCell>Hardware Category</TableCell>
                                    <TableCell align="right">Owed</TableCell>
                                    <TableCell align="right">Pulled</TableCell>
                                    <TableCell align="right">Installed</TableCell>
                                    <TableCell align="right">Deficient</TableCell>
                                  </TableRow>
                                </TableHead>
                                <TableBody>
                                  {opening.items.map((item) => (
                                    <TableRow key={item.id} hover>
                                      <TableCell sx={monoSx}>{item.productCode}</TableCell>
                                      <TableCell>{item.hardwareCategory}</TableCell>
                                      <TableCell align="right">{item.quantity}</TableCell>
                                      <TableCell align="right">
                                        {item.allocatedQuantity}
                                        {item.quantity > item.allocatedQuantity && (
                                          <Chip
                                            size="small"
                                            variant="outlined"
                                            color="warning"
                                            label={`${item.quantity - item.allocatedQuantity} never pulled`}
                                            sx={{ ml: 0.5 }}
                                          />
                                        )}
                                      </TableCell>
                                      <TableCell align="right">{item.installedQuantity}</TableCell>
                                      <TableCell align="right">{item.deficientQuantity}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            ) : (
                              <Typography variant="body2" color="text.secondary">
                                No hardware items.
                              </Typography>
                            )}
                          </AccordionDetails>
                        </Accordion>
                      </StaggerItem>
                    );
                  })}
                </StaggerList>
              )}
            </Box>
          );
        })}
      </Stack>

      {/* Reference, not work: the sections above are what this page is for, so the by-project
          leaf-status rollup reads below them rather than burying them under a schedule-sized wall. */}
      <Box sx={{ mt: 4 }}>
        <OpeningLeafStatusPanel mode="assembly" grouped title="Door leaves assembled (by project)" />
      </Box>

      {completing && (
        <AssemblyDetailModal
          // Keyed on the leaf so switching openings remounts and re-seeds the draft counts.
          key={completing.id}
          open={!!completing}
          opening={completing}
          onClose={() => setCompletingId(null)}
          onCompleted={() => {
            setCompletingId(null);
            refetch();
          }}
        />
      )}
    </Box>
  );
}

// --- Helpers ---

function formatPullStatus(status: string): string {
  return status
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
}
