import { useState, useCallback, useRef } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField,
  Typography, Box, CircularProgress, Alert, List, ListItem, ListItemText,
} from '@mui/material';
import { useMutation, useApolloClient } from '@apollo/client/react';
import { pdf } from '@react-pdf/renderer';
import { useIdentity } from '../../hooks/useIdentity';
import { useCart, type CartItem } from '../../contexts/CartContext';
import { useToast } from '../../components/Toast';
import { useNavigate } from 'react-router-dom';
import { CONFIRM_SHIPMENT } from '../../graphql/shipping';
import { SHIPPING_REFETCH_QUERIES, SHIPPING_STALE_ROOT_FIELDS } from '../../graphql/refetch';
import { extractGpError } from '../../graphql/gpError';
import PackingSlipDocument from './PackingSlipDocument';

interface PackingSlipFormProps {
  open: boolean;
  onClose: () => void;
  onShipped: () => void;
  projectId: string | undefined;
  projectName: string;
}

interface ShipmentResult {
  confirmShipment: {
    id: string;
    packingSlipNumber: string;
    projectId: string;
    shippedBy: string;
    shippedAt: string;
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

// Both ways a confirm can fail because the grid the user acted on disagrees with the server (#337).
// Keyed on extensions.code, not the message text: the backend wording carries a raw uuid and no test
// pins it, so a reword would silently drop us back to showing that string.
const STALE_CART_CODES = new Set(['INVALID_STATE_TRANSITION', 'VALIDATION_ERROR']);
const REFRESHED_SUFFIX = ' The list has been refreshed - please review your cart.';

// "Opening item <uuid> is not Ship_Ready (current: Shipped_Out)" says nothing to a shipper. The
// insufficient-loose-hardware message does (it names the product and the counts), so that one is
// kept and only annotated.
function describeConfirmError(err: unknown): string {
  const gp = extractGpError(err);
  if (!gp) return 'Failed to confirm shipment';
  if (gp.code === 'INVALID_STATE_TRANSITION') {
    return `One or more items are no longer ship-ready - they may already have shipped.${REFRESHED_SUFFIX}`;
  }
  return STALE_CART_CODES.has(gp.code ?? '') ? `${gp.message}${REFRESHED_SUFFIX}` : gp.message;
}

export default function PackingSlipForm({ open, onClose, onShipped, projectId, projectName }: PackingSlipFormProps) {
  const { displayName } = useIdentity();
  const { items, clearCart } = useCart();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const client = useApolloClient();

  const [view, setView] = useState<'form' | 'success'>('form');
  const [packingSlipNumber, setPackingSlipNumber] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ShipmentResult['confirmShipment'] | null>(null);
  const [generatingPdf, setGeneratingPdf] = useState(false);

  // Snapshot cart items at confirm time so they survive clearCart
  const cartSnapshotRef = useRef<CartItem[]>([]);

  const openingItemCount = items.filter((i) => i.itemType === 'Opening_Item').length;
  const looseItemCount = items.filter((i) => i.itemType === 'Loose').length;

  // A shipment contradicts the cached ship-ready stock, the leaf rollup and the warehouse
  // opening-item states, and none of those re-read on their own - which is why the Ship view behind
  // this dialog kept offering the leaf that just left (#337).
  //
  // Not awaited. `awaitRefetchQueries` folds the refetches into the mutate promise
  // (QueryInfo.markMutationResult -> Promise.all), so one slow or failed refetch would reject a
  // shipment that already committed: no success view, no packing-slip PDF, and a retry that can only
  // fail on the duplicate slip number. The shipment is the thing that must be reported truthfully;
  // the grid behind the modal can catch up on its own.
  const [confirmShipment, { loading: confirming }] = useMutation<ShipmentResult>(CONFIRM_SHIPMENT, {
    update(cache) {
      for (const fieldName of SHIPPING_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName });
      }
      cache.gc();
    },
    refetchQueries: SHIPPING_REFETCH_QUERIES,
  });

  const handleConfirm = useCallback(async () => {
    setError(null);

    if (!SLIP_NUMBER_PATTERN.test(packingSlipNumber)) {
      setError('Packing slip number must be 1-50 characters (alphanumeric, hyphens, underscores).');
      return;
    }

    // ConfirmShipmentInput.projectId is ID! but the shipping module leaves it undefined in its
    // "All Projects" mode, where the Ship view still lists items and lets them into the cart. Say so
    // here rather than shipping an undefined variable and surfacing a coercion error.
    if (!projectId) {
      setError('Select a single project before shipping - "All Projects" cannot create a packing slip.');
      return;
    }

    // Snapshot the cart items before mutation (cart gets cleared later)
    cartSnapshotRef.current = [...items];

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
            projectId,
            packingSlipNumber,
            shippedBy: displayName,
            items: shipmentItems,
          },
        },
      });

      if (data?.confirmShipment) {
        setResult(data.confirmShipment);
        setView('success');
        // These items have shipped - the cart must not still hold them behind the success view.
        clearCart();
        showToast('Shipment confirmed successfully!', 'success');
      }
    } catch (err) {
      // A rejection means the view the user acted on disagrees with the server, and the mutation's
      // own invalidation never runs on the error path. Reconcile BEFORE showing the message, so the
      // "list has been refreshed" it may carry is true by the time it is read. A refetch that fails
      // in turn must not replace the error that actually explains the rejection.
      try {
        client.cache.evict({ id: 'ROOT_QUERY', fieldName: 'shipReadyItems' });
        client.cache.gc();
        await client.refetchQueries({ include: SHIPPING_REFETCH_QUERIES });
      } catch {
        /* keep the original failure */
      }
      setError(describeConfirmError(err));
    }
  }, [confirmShipment, items, packingSlipNumber, projectId, displayName, showToast, clearCart, client]);

  const handleViewPdf = useCallback(async () => {
    if (!result) return;

    setGeneratingPdf(true);
    try {
      const cartItems = cartSnapshotRef.current;
      const openingItems = cartItems
        .filter((i) => i.itemType === 'Opening_Item')
        .map((i) => ({
          openingNumber: i.openingNumber ?? '',
          leaf: i.leaf ?? null,
          building: i.building,
          floor: i.floor,
          location: i.location,
        }));
      const looseItems = cartItems
        .filter((i) => i.itemType === 'Loose')
        .map((i) => ({
          openingNumber: i.openingNumber ?? '',
          productCode: i.productCode ?? '',
          hardwareCategory: i.hardwareCategory ?? '',
          quantity: i.quantity,
        }));

      const blob = await pdf(
        <PackingSlipDocument
          packingSlipNumber={result.packingSlipNumber}
          projectName={projectName}
          shippedBy={result.shippedBy}
          shippedAt={new Date(result.shippedAt).toLocaleString()}
          openingItems={openingItems}
          looseItems={looseItems}
        />
      ).toBlob();

      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
    } catch {
      showToast('Failed to generate PDF', 'error');
    } finally {
      setGeneratingPdf(false);
    }
  }, [result, projectName, showToast]);

  // The cart is emptied the moment the shipment succeeds rather than here, so the Ship view never
  // shows a shipped leaf as still carted. These calls stay as the backstop for any path that reaches
  // the success view without that clear having run; clearCart is idempotent.
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
            <Button onClick={handleViewPdf} disabled={generatingPdf}>
              {generatingPdf ? 'Generating...' : 'View Packing Slip'}
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
