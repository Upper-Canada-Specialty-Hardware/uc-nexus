import { useState } from 'react';
import {
  Drawer, Box, Typography, IconButton, List, ListItem, ListItemText,
  Button, Divider, Chip,
} from '@mui/material';
import { ShoppingCart, Trash2 } from 'lucide-react';
import { useCart } from '../../contexts/CartContext';
import PackingSlipForm from './PackingSlipForm';
import { leafSuffix } from '../../utils/leaf';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { AnimatedNumber, StaggerItem, StaggerList } from '../../motion';

interface ShippingCartProps {
  open: boolean;
  onClose: () => void;
  projectId: string | undefined;
  projectName: string;
}

export default function ShippingCart({ open, onClose, projectId, projectName }: ShippingCartProps) {
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
            <ShoppingCart size={18} strokeWidth={1.75} />
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
                    <Box
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 1,
                        px: 1,
                        pt: 1,
                        pb: 0.5,
                        borderBottom: '2px solid',
                        borderColor: 'text.primary',
                      }}
                    >
                      <Typography sx={microLabelSx}>Opening Items</Typography>
                      <Chip label={openingItems.length} size="small" />
                    </Box>
                    <List dense disablePadding>
                      <StaggerList count={openingItems.length}>
                        {openingItems.map((item) => (
                          <StaggerItem key={item.id}>
                            <ListItem
                              divider
                              secondaryAction={
                                <IconButton
                                  edge="end"
                                  size="small"
                                  aria-label="Remove from cart"
                                  onClick={() => removeItem(item.id)}
                                >
                                  <Trash2 size={16} strokeWidth={1.75} />
                                </IconButton>
                              }
                            >
                              <ListItemText
                                primary={`Opening ${item.openingNumber}${leafSuffix(item.leaf)}`}
                                secondary="Assembled Opening"
                                slotProps={{ primary: { sx: monoSx } }}
                              />
                            </ListItem>
                          </StaggerItem>
                        ))}
                      </StaggerList>
                    </List>
                  </>
                )}

                {looseItems.length > 0 && (
                  <>
                    <Box
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 1,
                        px: 1,
                        pt: 2,
                        pb: 0.5,
                        borderBottom: '2px solid',
                        borderColor: 'text.primary',
                      }}
                    >
                      <Typography sx={microLabelSx}>Loose Hardware</Typography>
                      <Chip label={looseItems.length} size="small" />
                    </Box>
                    <List dense disablePadding>
                      <StaggerList count={looseItems.length}>
                        {looseItems.map((item) => (
                          <StaggerItem key={item.id}>
                            <ListItem
                              divider
                              secondaryAction={
                                <IconButton
                                  edge="end"
                                  size="small"
                                  aria-label="Remove from cart"
                                  onClick={() => removeItem(item.id)}
                                >
                                  <Trash2 size={16} strokeWidth={1.75} />
                                </IconButton>
                              }
                            >
                              <ListItemText
                                primary={`${item.productCode} (${item.hardwareCategory})`}
                                secondary={`Opening ${item.openingNumber} - Qty: ${item.quantity}`}
                                slotProps={{
                                  primary: { sx: monoSx },
                                  secondary: { sx: tabularSx },
                                }}
                              />
                            </ListItem>
                          </StaggerItem>
                        ))}
                      </StaggerList>
                    </List>
                  </>
                )}
              </>
            )}
          </Box>

          <Divider />

          <Box sx={{ p: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mb: 1.5 }}>
              <Typography sx={microLabelSx}>Total items</Typography>
              <Typography variant="h6" sx={tabularSx}>
                <AnimatedNumber value={itemCount} />
              </Typography>
            </Box>
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
        projectId={projectId}
        projectName={projectName}
      />
    </>
  );
}
