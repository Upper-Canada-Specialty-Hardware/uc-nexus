import { useNavigate } from 'react-router-dom';
import {
  Box,
  Card,
  CardContent,
  CardActions,
  Typography,
  Button,
  Container,
  Grid,
} from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import WarehouseIcon from '@mui/icons-material/Warehouse';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import EngineeringIcon from '@mui/icons-material/Engineering';
import BuildIcon from '@mui/icons-material/Build';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import { ROLES, type Role, useRole } from '../contexts/RoleContext';

const ROLE_CONFIG: Record<Role, { icon: React.ReactNode; description: string }> = {
  'Hardware Schedule Import': {
    icon: <UploadFileIcon sx={{ fontSize: 48 }} />,
    description: 'Import hardware schedules, create POs, and set up shop assembly requests.',
  },
  'Warehouse Staff': {
    icon: <WarehouseIcon sx={{ fontSize: 48 }} />,
    description: 'Receive deliveries, manage inventory, fulfill pull requests, and ship items.',
  },
  'PO User': {
    icon: <ReceiptLongIcon sx={{ fontSize: 48 }} />,
    description: 'View and manage purchase orders, update vendor info, and track order status.',
  },
  'Shipping Out': {
    icon: <LocalShippingIcon sx={{ fontSize: 48 }} />,
    description: 'Create packing slips and confirm shipments to the job site.',
  },
  'Shop Assembly Manager': {
    icon: <EngineeringIcon sx={{ fontSize: 48 }} />,
    description: 'Approve assembly requests, assign openings to workers, and monitor progress.',
  },
  'Shop Assembly User': {
    icon: <BuildIcon sx={{ fontSize: 48 }} />,
    description: 'View assigned openings, pull hardware, and complete assembly work.',
  },
  'Admin/Manager': {
    icon: <AdminPanelSettingsIcon sx={{ fontSize: 48 }} />,
    description: 'Adjust inventory, relocate items, and manage warehouse corrections.',
  },
};

export default function RoleSelectionPage() {
  const { setRole } = useRole();
  const navigate = useNavigate();

  const handleSelect = (role: Role) => {
    setRole(role);
    navigate('/app');
  };

  return (
    <Container maxWidth="lg" sx={{ py: 6 }}>
      <Typography variant="h4" align="center" gutterBottom>
        Role Selection
      </Typography>
      <Typography variant="subtitle1" align="center" color="text.secondary" sx={{ mb: 4 }}>
        Once Authentication is implemented, it will replace Role Selection (Potential Auth Logins: Microsoft, Google, etc..)
      </Typography>
      <Grid container spacing={3}>
        {ROLES.map((role) => {
          const config = ROLE_CONFIG[role];
          return (
            <Grid key={role} size={{ xs: 12, sm: 6, md: 4 }}>
              <Card
                sx={{
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  transition: 'box-shadow 0.2s',
                  '&:hover': { boxShadow: 6 },
                }}
              >
                <CardContent sx={{ flexGrow: 1, textAlign: 'center' }}>
                  <Box sx={{ color: 'primary.main', mb: 1 }}>{config.icon}</Box>
                  <Typography variant="h6" gutterBottom>
                    {role}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {config.description}
                  </Typography>
                </CardContent>
                <CardActions sx={{ justifyContent: 'center', pb: 2 }}>
                  <Button variant="contained" onClick={() => handleSelect(role)}>
                    Enter
                  </Button>
                </CardActions>
              </Card>
            </Grid>
          );
        })}
      </Grid>
    </Container>
  );
}
