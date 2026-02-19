import { useMemo } from 'react';
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
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useQuery } from '@apollo/client/react';
import { GET_ASSEMBLE_LIST } from '../../graphql/queries';
import { useProject } from '../../contexts/ProjectContext';

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
  assignedTo: string | null;
  assemblyStatus: string;
  completedAt: string | null;
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
  const { project } = useProject();

  const {
    data,
    loading,
  } = useQuery<{ assembleList: AssembleOpening[] }>(GET_ASSEMBLE_LIST, {
    variables: { projectId: project?.id },
    skip: !project?.id,
    pollInterval: 10000,
  });

  const openings = data?.assembleList ?? [];

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

  // --- No project selected ---

  if (!project) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity="info">
          Please select a project from the navigation bar to view the assemble list.
        </Alert>
      </Box>
    );
  }

  // --- Render ---

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Assemble List
      </Typography>

      {loading && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Loading...
        </Typography>
      )}

      {!loading && openings.length === 0 && (
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
                sectionOpenings.map((opening) => (
                  <Accordion key={opening.id} variant="outlined" sx={{ mb: 1 }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Stack direction="row" spacing={2} alignItems="center">
                        <Typography fontWeight="bold">Opening: {opening.openingId}</Typography>
                        <Chip
                          label={formatPullStatus(opening.pullStatus)}
                          color={section.badgeColor}
                          size="small"
                          variant="outlined"
                        />
                      </Stack>
                    </AccordionSummary>
                    <AccordionDetails>
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
                ))
              )}
            </Box>
          );
        })}
      </Stack>
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
