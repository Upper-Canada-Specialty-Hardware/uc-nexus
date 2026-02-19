import { useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Box, Typography, Badge, IconButton } from '@mui/material';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import { useCart } from '../../contexts/CartContext';
import ShipReadyBrowser from './ShipReadyBrowser';
import ShippingCart from './ShippingCart';

export default function ShippingModule() {
  const [cartOpen, setCartOpen] = useState(false);
  const { itemCount } = useCart();

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5">Shipping</Typography>
        <IconButton onClick={() => setCartOpen(true)}>
          <Badge badgeContent={itemCount} color="primary">
            <ShoppingCartIcon />
          </Badge>
        </IconButton>
      </Box>
      <Routes>
        <Route path="browse" element={<ShipReadyBrowser />} />
        <Route index element={<Navigate to="browse" replace />} />
      </Routes>
      <ShippingCart open={cartOpen} onClose={() => setCartOpen(false)} />
    </Box>
  );
}
