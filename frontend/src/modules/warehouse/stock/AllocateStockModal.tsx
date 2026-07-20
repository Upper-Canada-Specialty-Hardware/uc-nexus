import { useState } from 'react';
import {
  Button,
  Stack,
  TextField,
  Alert,
  Typography,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import { useToast } from '../../../components/Toast';
import { GET_PROJECTS } from '../../../graphql/shared';
import { ALLOCATE_STOCK_TO_PROJECT } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import type { StockItem } from '../StockPoolView';

interface Project {
  id: string;
  projectId: string;
  description: string | null;
}

interface Props {
  item: StockItem;
  onClose: () => void;
  onSuccess: () => void;
  prefillProjectId?: string;
  prefillCategory?: string;
  prefillProductCode?: string;
}

export default function AllocateStockModal({
  item,
  onClose,
  onSuccess,
  prefillProjectId,
  prefillCategory,
  prefillProductCode,
}: Props) {
  const [projectId, setProjectId] = useState(prefillProjectId ?? '');
  const [category, setCategory] = useState(prefillCategory ?? item.hardwareCategory);
  const [productCode, setProductCode] = useState(prefillProductCode ?? item.productCode);
  const [quantity, setQuantity] = useState<string>('1');
  const [aisle, setAisle] = useState('');
  const [bay, setBay] = useState('');
  const [bin, setBin] = useState('');
  const { showToast } = useToast();

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const [mutate, { loading, error }] = useMutation(ALLOCATE_STOCK_TO_PROJECT, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      showToast('Stock allocated to project inventory', 'success');
      onSuccess();
    },
    onError: (err) => showToast(err.message, 'error'),
  });

  const q = Number(quantity);
  const valid =
    projectId &&
    category.trim() &&
    productCode.trim() &&
    Number.isInteger(q) &&
    q >= 1 &&
    q <= item.available;

  const handleSubmit = () => {
    if (!valid) return;
    mutate({
      variables: {
        input: {
          stockItemId: item.id,
          projectId,
          targetHardwareCategory: category.trim(),
          targetProductCode: productCode.trim(),
          quantity: q,
          targetAisle: aisle.trim() || null,
          targetBay: bay.trim() || null,
          targetBin: bin.trim() || null,
          performedBy: 'Warehouse',
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Allocate ${item.productCode} to a project`}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSubmit} disabled={!valid || loading}>
            Allocate
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{error.message}</Alert>}
        <Typography variant="body2" color="text.secondary">
          Source: <b>{item.hardwareCategory}</b> / <b>{item.productCode}</b> (available{' '}
          {item.available})
        </Typography>
        <FormControl size="small" required>
          <InputLabel>Target project</InputLabel>
          <Select
            label="Target project"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            {(projectsData?.projects ?? []).map((p) => (
              <MenuItem key={p.id} value={p.id}>
                {p.description || p.projectId}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Stack direction="row" spacing={2}>
          <TextField
            label="Target hardware category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            fullWidth
            required
          />
          <TextField
            label="Target product code"
            value={productCode}
            onChange={(e) => setProductCode(e.target.value)}
            fullWidth
            required
          />
        </Stack>
        <TextField
          label={`Quantity (max ${item.available})`}
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          inputProps={{ min: 1, max: item.available }}
        />
        <Typography variant="body2" color="text.secondary">
          Optional: pre-locate the new inventory row at a specific bin (leave blank for unlocated).
        </Typography>
        <Stack direction="row" spacing={2}>
          <TextField label="Aisle" value={aisle} onChange={(e) => setAisle(e.target.value)} />
          <TextField label="Bay" value={bay} onChange={(e) => setBay(e.target.value)} />
          <TextField label="Bin" value={bin} onChange={(e) => setBin(e.target.value)} />
        </Stack>
      </Stack>
    </Modal>
  );
}
