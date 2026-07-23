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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_ASSEMBLE_LIST, ASSIGN_OPENINGS, REMOVE_OPENING_FROM_USER } from '../../graphql/shop-assembly';
import { leafSuffix } from '../../utils/leaf';
import OpeningLeafStatusPanel from '../../components/OpeningLeafStatusPanel';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import AssemblyDetailModal from './AssemblyDetailModal';

// --- Types ---

interface AssembleOpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
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
  const [completing, setCompleting] = useState<AssembleOpening | null>(null);

  const {
    data,
    loading,
    refetch,
  } = useQuery<{ assembleList: AssembleOpening[] }>(GET_ASSEMBLE_LIST);

  const openings = data?.assembleList ?? [];

  const [assignOpenings] = useMutation(ASSIGN_OPENINGS, {
    onCompleted: () => {
      showToast('Assigned to you', 'success');
      refetch();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const [removeOpening] = useMutation(REMOVE_OPENING_FROM_USER, {
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
            <Button size="small" variant="contained" onClick={() => setCompleting(opening)}>
              Complete assembly
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
      <Typography variant="h5" gutterBottom>
        Assemble List
      </Typography>

      <OpeningLeafStatusPanel mode="assembly" grouped title="Door leaves assembled (by project)" />

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

      <Stack spacing={2}>
        {PULL_STATUS_SECTIONS.map((section) => {
          const sectionOpenings = grouped[section.key] ?? [];
          return (
            <Box key={section.key}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="h6">{section.label}</Typography>
                <Chip
                  label={section.badgeLabel}
                  color={section.badgeColor}
                  size="small"
                />
                <Typography variant="body2" color="text.secondary">
                  ({sectionOpenings.length})
                </Typography>
              </Stack>

              {sectionOpenings.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ ml: 2, mb: 2 }}>
                  No openings in this category.
                </Typography>
              ) : (
                sectionOpenings.map((opening) => {
                  const actions = renderActions(opening);
                  return (
                    <Accordion key={opening.id} variant="outlined" sx={{ mb: 1 }}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Stack direction="row" spacing={2} alignItems="center">
                          <Typography fontWeight="bold">
                            Opening: {opening.openingNumber || opening.openingId}
                            {leafSuffix(opening.leaf)}
                          </Typography>
                          <Chip
                            label={formatPullStatus(opening.pullStatus)}
                            color={section.badgeColor}
                            size="small"
                            variant="outlined"
                          />
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
                                <TableCell align="right">Quantity</TableCell>
                              </TableRow>
                            </TableHead>
                            <TableBody>
                              {opening.items.map((item) => (
                                <TableRow key={item.id}>
                                  <TableCell>{item.productCode}</TableCell>
                                  <TableCell>{item.hardwareCategory}</TableCell>
                                  <TableCell align="right">{item.quantity}</TableCell>
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
                  );
                })
              )}
            </Box>
          );
        })}
      </Stack>

      {completing && (
        <AssemblyDetailModal
          open={!!completing}
          opening={completing}
          onClose={() => setCompleting(null)}
          onCompleted={() => {
            setCompleting(null);
            refetch();
          }}
          completedBy={displayName}
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
