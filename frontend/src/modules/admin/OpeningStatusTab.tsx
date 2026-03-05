import {
  Box,
  CircularProgress,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useQuery } from '@apollo/client/react';
import { GET_OPENING_HARDWARE_STATUS } from '../../graphql/queries';
import { useProject } from '../../contexts/ProjectContext';

interface OpeningHardwareStatusItem {
  hardwareCategory: string;
  productCode: string;
  itemQuantity: number;
  status: string;
}

interface OpeningHardwareStatus {
  openingNumber: string;
  building: string | null;
  floor: string | null;
  location: string | null;
  items: OpeningHardwareStatusItem[];
}

const STATUS_CHIP: Record<string, { label: string; color: 'default' | 'info' | 'success' }> = {
  PO_DRAFTED: { label: 'PO Drafted', color: 'default' },
  ORDERED: { label: 'Ordered', color: 'info' },
  RECEIVED: { label: 'Received', color: 'success' },
};

export default function OpeningStatusTab() {
  const { project } = useProject();

  const { data, loading, error } = useQuery<{ openingHardwareStatus: OpeningHardwareStatus[] }>(
    GET_OPENING_HARDWARE_STATUS,
    {
      variables: { projectId: project?.id },
      skip: !project,
    },
  );

  if (!project) {
    return <Alert severity="info">Select a project first</Alert>;
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading opening status: {error.message}</Alert>;
  }

  const openings = data?.openingHardwareStatus ?? [];

  if (openings.length === 0) {
    return <Alert severity="info">No opening hardware data for this project</Alert>;
  }

  return (
    <Box>
      {openings.map((opening) => {
        const subtitle = [opening.building, opening.floor, opening.location]
          .filter(Boolean)
          .join(' / ');

        return (
          <Accordion key={opening.openingNumber}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Box>
                <Typography variant="subtitle1" fontWeight="bold">
                  {opening.openingNumber}
                </Typography>
                {subtitle && (
                  <Typography variant="body2" color="text.secondary">
                    {subtitle}
                  </Typography>
                )}
              </Box>
            </AccordionSummary>
            <AccordionDetails>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Hardware Category</TableCell>
                      <TableCell>Product Code</TableCell>
                      <TableCell align="right">Quantity</TableCell>
                      <TableCell>Status</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {opening.items.map((item, idx) => {
                      const chip = STATUS_CHIP[item.status] ?? STATUS_CHIP.PO_DRAFTED;
                      return (
                        <TableRow key={idx}>
                          <TableCell>{item.hardwareCategory}</TableCell>
                          <TableCell>{item.productCode}</TableCell>
                          <TableCell align="right">{item.itemQuantity}</TableCell>
                          <TableCell>
                            <Chip label={chip.label} color={chip.color} size="small" />
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Box>
  );
}
