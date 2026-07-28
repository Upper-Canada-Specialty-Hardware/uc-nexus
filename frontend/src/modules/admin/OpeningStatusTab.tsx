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
import { ChevronDown } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { GET_OPENING_HARDWARE_STATUS } from '../../graphql/admin';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn, StaggerList, StaggerItem } from '../../motion';

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
  const { data, loading, error } = useQuery<{ openingHardwareStatus: OpeningHardwareStatus[] }>(
    GET_OPENING_HARDWARE_STATUS,
  );

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
      <FadeIn>
        <Typography variant="h5" sx={{ mb: 0.25 }}>
          Opening Status
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Where each opening's hardware sits between drafted, ordered, and received.
        </Typography>
      </FadeIn>

      {/* gap (not Stack's margins) so the stagger wrapper's display:contents stays transparent. */}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <StaggerList count={openings.length}>
          {openings.map((opening) => {
            const subtitle = [opening.building, opening.floor, opening.location]
              .filter(Boolean)
              .join(' / ');

            return (
              <StaggerItem key={opening.openingNumber}>
                <Accordion
                  variant="outlined"
                  disableGutters
                  sx={{ '&::before': { display: 'none' }, borderRadius: 1 }}
                >
                  <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                    <Box>
                      <Typography component="div" sx={{ ...monoSx, fontSize: '0.9375rem', fontWeight: 600 }}>
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
                              <TableRow key={idx} hover>
                                <TableCell>{item.hardwareCategory}</TableCell>
                                <TableCell sx={monoSx}>{item.productCode}</TableCell>
                                <TableCell align="right" sx={tabularSx}>
                                  {item.itemQuantity}
                                </TableCell>
                                <TableCell>
                                  <Chip label={chip.label} color={chip.color} size="small" />
                                </TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </TableContainer>
                    <Typography component="div" sx={{ ...microLabelSx, mt: 1 }}>
                      {opening.items.length} item{opening.items.length === 1 ? '' : 's'}
                    </Typography>
                  </AccordionDetails>
                </Accordion>
              </StaggerItem>
            );
          })}
        </StaggerList>
      </Box>
    </Box>
  );
}
