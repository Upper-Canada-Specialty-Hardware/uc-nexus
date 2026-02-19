import { useState } from 'react';
import {
  Drawer, Box, Typography, IconButton, List, ListItem, ListItemText,
  ListItemSecondaryAction, Button, Divider, Chip,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import { useCart } from '../../contexts/CartContext';
import PackingSlipForm from './PackingSlipForm';

interface ShippingCartProps {
  open: boolean;
  onClose: () => void;
}

export default function ShippingCart({ open, onClose }: ShippingCartProps) {
  const { items, removeItem, clearCart, itemCount } = useCart();
  const [packingSlipOpen, setPackingSlipOpen] = useState(false);

  const openingItems = items.filter((i) => i.itemType === 'Opening_Item');
  const looseItems = items.filter((i) => i.itemType === 'Loose');

  const handleShipped = () => {
    setPackingSlipOpen(false);
    onClose();
  };

  return (
    <>
      <Drawer anchor="right" open={open} onClose={onClose}>
        <Box sx={{ width: 400, display: 'flex', flexDirection: 'column', height: '100%' }}>
          <Box sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
            <ShoppingCartIcon />
            <Typography variant="h6">Shipping Cart</Typography>
          </Box>

          <Divider />

          <Box sx={{ flexGrow: 1, overflow: 'auto', p: 1 }}>
            {itemCount === 0 ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
                <Typography color="text.secondary">Cart is empty</Typography>
              </Box>
            ) : (
              <>
                {openingItems.length > 0 && (
                  <>
                    <Typography variant="subtitle2" sx={{ px: 1, pt: 1 }}>
                      Opening Items
                      <Chip label={openingItems.length} size="small" sx={{ ml: 1 }} />
                    </Typography>
                    <List dense>
                      {openingItems.map((item) => (
                        <ListItem key={item.id}>
                          <ListItemText
                            primary={`Opening ${item.openingNumber}`}
                            secondary="Assembled Opening"
                          />
                          <ListItemSecondaryAction>
                            <IconButton edge="end" size="small" onClick={() => removeItem(item.id)}>
                              <DeleteIcon fontSize="small" />
                            </IconButton>
                          </ListItemSecondaryAction>
                        </ListItem>
                      ))}
                    </List>
                  </>
                )}

                {looseItems.length > 0 && (
                  <>
                    <Typography variant="subtitle2" sx={{ px: 1, pt: 1 }}>
                      Loose Hardware
                      <Chip label={looseItems.length} size="small" sx={{ ml: 1 }} />
                    </Typography>
                    <List dense>
                      {looseItems.map((item) => (
                        <ListItem key={item.id}>
                          <ListItemText
                            primary={`${item.productCode} (${item.hardwareCategory})`}
                            secondary={`Opening ${item.openingNumber} - Qty: ${item.quantity}`}
                          />
                          <ListItemSecondaryAction>
                            <IconButton edge="end" size="small" onClick={() => removeItem(item.id)}>
                              <DeleteIcon fontSize="small" />
                            </IconButton>
                          </ListItemSecondaryAction>
                        </ListItem>
                      ))}
                    </List>
                  </>
                )}
              </>
            )}
          </Box>

          <Divider />

          <Box sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>
              Total items: <strong>{itemCount}</strong>
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant="outlined"
                size="small"
                onClick={clearCart}
                disabled={itemCount === 0}
              >
                Clear Cart
              </Button>
              <Button
                variant="contained"
                size="small"
                onClick={() => setPackingSlipOpen(true)}
                disabled={itemCount === 0}
                sx={{ flexGrow: 1 }}
              >
                Proceed to Ship
              </Button>
            </Box>
          </Box>
        </Box>
      </Drawer>

      <PackingSlipForm
        open={packingSlipOpen}
        onClose={() => setPackingSlipOpen(false)}
        onShipped={handleShipped}
      />
    </>
  );
}
