import { useState } from 'react';
import {
  Button,
  Stack,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Alert,
  CircularProgress,
  Box,
} from '@mui/material';
import { useLazyQuery } from '@apollo/client/react';
import SearchIcon from '@mui/icons-material/Search';
import Modal from '../../../components/Modal';
import { GET_STOCK_MATCHES_FOR_OPENING } from '../../../graphql/warehouse';
import AllocateStockModal from './AllocateStockModal';
import type { StockItem } from '../StockPoolView';

interface Props {
  openingItemId: string;
  projectId: string;
  defaultCategory?: string;
  defaultProductCode?: string;
  onAllocated?: () => void;
}

export default function FindInStockButton({
  openingItemId,
  projectId,
  defaultCategory,
  defaultProductCode,
  onAllocated,
}: Props) {
  const [open, setOpen] = useState(false);
  const [allocateItem, setAllocateItem] = useState<StockItem | null>(null);

  const [fetchMatches, { data, loading, error }] = useLazyQuery<{
    stockMatchesForOpening: StockItem[];
  }>(GET_STOCK_MATCHES_FOR_OPENING, {
    fetchPolicy: 'network-only',
  });

  const handleOpen = () => {
    setOpen(true);
    fetchMatches({ variables: { openingItemId } });
  };

  const matches = data?.stockMatchesForOpening ?? [];

  return (
    <>
      <Button
        variant="outlined"
        size="small"
        startIcon={<SearchIcon />}
        onClick={handleOpen}
      >
        Find in Stock
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Stock pool matches for this opening"
      >
        <Stack spacing={2}>
          {loading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
              <CircularProgress size={24} />
            </Box>
          )}
          {error && <Alert severity="error">{error.message}</Alert>}
          {!loading && matches.length === 0 && (
            <Typography color="text.secondary">
              No matching stock-pool items found for this opening.
            </Typography>
          )}
          {matches.length > 0 && (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Category</TableCell>
                    <TableCell>Product Code</TableCell>
                    <TableCell align="right">Available</TableCell>
                    <TableCell>Location</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {matches.map((m) => (
                    <TableRow key={m.id}>
                      <TableCell>{m.hardwareCategory}</TableCell>
                      <TableCell>{m.productCode}</TableCell>
                      <TableCell align="right">{m.available}</TableCell>
                      <TableCell>
                        {[m.aisle, m.bay, m.bin].filter(Boolean).join(' / ') || '— unlocated —'}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          variant="contained"
                          disabled={m.available <= 0}
                          onClick={() => {
                            setAllocateItem(m);
                            setOpen(false);
                          }}
                        >
                          Allocate
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Stack>
      </Modal>

      {allocateItem && (
        <AllocateStockModal
          item={allocateItem}
          onClose={() => setAllocateItem(null)}
          onSuccess={() => {
            setAllocateItem(null);
            onAllocated?.();
          }}
          prefillProjectId={projectId}
          prefillCategory={defaultCategory}
          prefillProductCode={defaultProductCode}
        />
      )}
    </>
  );
}
