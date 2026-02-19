import { useState, useCallback } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField,
  Typography, Box, CircularProgress, Alert, List, ListItem, ListItemText,
} from '@mui/material';
import { useMutation, useLazyQuery } from '@apollo/client/react';
import { useProject } from '../../contexts/ProjectContext';
import { useRole } from '../../contexts/RoleContext';
import { useCart } from '../../contexts/CartContext';
import { useToast } from '../../components/Toast';
import { useNavigate } from 'react-router-dom';
import { CONFIRM_SHIPMENT } from '../../graphql/mutations';
import { GET_PACKING_SLIP_PDF_URL } from '../../graphql/queries';

interface PackingSlipFormProps {
  open: boolean;
  onClose: () => void;
  onShipped: () => void;
}

interface ShipmentResult {
  confirmShipment: {
    id: string;
    packingSlipNumber: string;
    projectId: string;
    shippedBy: string;
    shippedAt: string;
    pdfFilePath: string;
    createdAt: string;
    items: Array<{
      id: string;
      packingSlipId: string;
      itemType: string;
      openingItemId: string | null;
      openingNumber: string | null;
      productCode: string | null;
      hardwareCategory: string | null;
      quantity: number;
    }>;
  };
}

const SLIP_NUMBER_PATTERN = /^[a-zA-Z0-9_-]{1,50}$/;

export default function PackingSlipForm({ open, onClose, onShipped }: PackingSlipFormProps) {
  const { project } = useProject();
  const { role } = useRole();
  const { items, clearCart } = useCart();
  const { showToast } = useToast();
  const navigate = useNavigate();

  const [view, setView] = useState<'form' | 'success'>('form');
  const [packingSlipNumber, setPackingSlipNumber] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ShipmentResult['confirmShipment'] | null>(null);

  const openingItemCount = items.filter((i) => i.itemType === 'Opening_Item').length;
  const looseItemCount = items.filter((i) => i.itemType === 'Loose').length;

  const [confirmShipment, { loading: confirming }] = useMutation<ShipmentResult>(CONFIRM_SHIPMENT);

  const [fetchPdfUrl, { loading: fetchingPdf }] = useLazyQuery<{
    packingSlipPdfUrl: string;
  }>(GET_PACKING_SLIP_PDF_URL);

  const handleConfirm = useCallback(async () => {
    setError(null);

    if (!SLIP_NUMBER_PATTERN.test(packingSlipNumber)) {
      setError('Packing slip number must be 1-50 characters (alphanumeric, hyphens, underscores).');
      return;
    }

    const shipmentItems = items.map((item) => {
      if (item.itemType === 'Opening_Item') {
        return {
          itemType: 'OPENING_ITEM' as const,
          openingItemId: item.openingItemId,
          quantity: 1,
        };
      }
      return {
        itemType: 'LOOSE' as const,
        openingNumber: item.openingNumber,
        productCode: item.productCode,
        hardwareCategory: item.hardwareCategory,
        quantity: item.quantity,
      };
    });

    try {
      const { data } = await confirmShipment({
        variables: {
          input: {
            projectId: project.id,
            packingSlipNumber,
            shippedBy: role,
            items: shipmentItems,
          },
        },
      });

      if (data?.confirmShipment) {
        setResult(data.confirmShipment);
        setView('success');
        showToast('Shipment confirmed successfully!', 'success');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to confirm shipment');
    }
  }, [confirmShipment, items, packingSlipNumber, project.id, role, showToast]);

  const handleViewPdf = useCallback(async () => {
    if (!result?.pdfFilePath) return;

    try {
      const { data } = await fetchPdfUrl({
        variables: { filePath: result.pdfFilePath },
      });
      if (data?.packingSlipPdfUrl) {
        window.open(data.packingSlipPdfUrl, '_blank');
      }
    } catch (err) {
      showToast('Failed to fetch PDF URL', 'error');
    }
  }, [fetchPdfUrl, result, showToast]);

  const handleShipMore = useCallback(() => {
    clearCart();
    setView('form');
    setPackingSlipNumber('');
    setError(null);
    setResult(null);
    onShipped();
  }, [clearCart, onShipped]);

  const handleReturnHome = useCallback(() => {
    clearCart();
    setView('form');
    setPackingSlipNumber('');
    setError(null);
    setResult(null);
    onClose();
    navigate('/app');
  }, [clearCart, navigate, onClose]);

  const handleClose = () => {
    if (view === 'form') {
      onClose();
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      {view === 'form' ? (
        <>
          <DialogTitle>Create Packing Slip</DialogTitle>
          <DialogContent>
            <TextField
              label="Packing Slip Number"
              value={packingSlipNumber}
              onChange={(e) => setPackingSlipNumber(e.target.value)}
              fullWidth
              margin="normal"
              helperText="1-50 characters: letters, numbers, hyphens, underscores"
              error={!!error && error.includes('Packing slip')}
            />

            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Cart Summary
              </Typography>
              <List dense>
                <ListItem>
                  <ListItemText
                    primary={`Opening Items: ${openingItemCount}`}
                  />
                </ListItem>
                <ListItem>
                  <ListItemText
                    primary={`Loose Items: ${looseItemCount}`}
                  />
                </ListItem>
                <ListItem>
                  <ListItemText
                    primary={`Total Items: ${items.length}`}
                    primaryTypographyProps={{ fontWeight: 'bold' }}
                  />
                </ListItem>
              </List>
            </Box>

            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {error}
              </Alert>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={handleClose} disabled={confirming}>
              Cancel
            </Button>
            <Button
              variant="contained"
              onClick={handleConfirm}
              disabled={confirming || items.length === 0}
              startIcon={confirming ? <CircularProgress size={16} /> : undefined}
            >
              {confirming ? 'Confirming...' : 'Confirm Shipment'}
            </Button>
          </DialogActions>
        </>
      ) : (
        <>
          <DialogTitle>Shipment Confirmed</DialogTitle>
          <DialogContent>
            <Alert severity="success" sx={{ mb: 2 }}>
              Packing slip <strong>{result?.packingSlipNumber}</strong> has been created
              successfully.
            </Alert>

            <Typography variant="body2" color="text.secondary">
              {result?.items.length} item(s) shipped.
            </Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={handleViewPdf} disabled={fetchingPdf}>
              {fetchingPdf ? 'Loading...' : 'View Packing Slip'}
            </Button>
            <Button onClick={handleShipMore}>Ship More Items</Button>
            <Button variant="contained" onClick={handleReturnHome}>
              Return to Home
            </Button>
          </DialogActions>
        </>
      )}
    </Dialog>
  );
}
