import { useRef, useState } from 'react';
import {
  Box,
  Button,
  Stack,
  TextField,
  Alert,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import LocationAutocomplete from '../../../components/LocationAutocomplete';
import ProjectPicker from '../../../components/ProjectPicker';
import { useToast } from '../../../components/Toast';
import { GET_PROJECTS } from '../../../graphql/shared';
import { ALLOCATE_STOCK_TO_PROJECT } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
import type { Project } from '../../../types/project';
import type { StockItem } from '../StockPoolView';
import { useDefinedLocationPick } from '../useDefinedLocationPick';
import { userMessage } from '../../../graphql/userMessage';

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
  // The picked project, or null. A prefill is an id, resolved against the same projects read the
  // picker makes until the user picks for themselves.
  const [picked, setPicked] = useState<Project | null | undefined>(undefined);
  const [category, setCategory] = useState(prefillCategory ?? item.hardwareCategory);
  const [productCode, setProductCode] = useState(prefillProductCode ?? item.productCode);
  const [quantity, setQuantity] = useState<string>('1');
  const [aisle, setAisle] = useState('');
  const [row, setRow] = useState('');
  const [bay, setBay] = useState('');
  const { showToast } = useToast();
  // #1548: Enter and a click in the same moment must not send it twice; set before `loading` re-renders.
  const inFlight = useRef(false);

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const project =
    picked !== undefined
      ? picked
      : (projectsData?.projects.find((p) => p.id === prefillProjectId) ?? null);
  const projectId = project?.id ?? '';
  const [mutate, { loading, error }] = useMutation(ALLOCATE_STOCK_TO_PROJECT, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
    onCompleted: () => {
      inFlight.current = false;
      showToast('Stock allocated to project inventory', 'success');
      onSuccess();
    },
    onError: (err) => {
      inFlight.current = false;
      showToast(userMessage(err), 'error');
    },
  });

  // #1046: the pre-locate bin is optional, but when given it is a strict pick from the stock item's
  // warehouse - the server refuses any bin not on the Locations tab. All three or none.
  const { aisleOptions, rowOptions, bayOptions, isDefinedPick } = useDefinedLocationPick(
    [item.warehouseId],
    aisle,
    row,
    bay,
  );
  const binBlank = !aisle.trim() && !row.trim() && !bay.trim();
  const binOk = binBlank || isDefinedPick;

  const q = Number(quantity);
  const valid =
    projectId &&
    category.trim() &&
    productCode.trim() &&
    Number.isInteger(q) &&
    q >= 1 &&
    q <= item.available &&
    binOk;
  // #1548 (#981): a dead Allocate says what it is waiting for.
  const blockedReason = !projectId
    ? 'Pick the target project.'
    : !category.trim() || !productCode.trim()
      ? 'Enter the target hardware category and product code.'
      : !(Number.isInteger(q) && q >= 1 && q <= item.available)
        ? `Enter a whole number from 1 to ${item.available}.`
        : !binOk
          ? 'Pick an aisle, row and bay defined on the Locations tab, or clear all three to leave it unlocated.'
          : null;

  const handleSubmit = () => {
    if (!valid || loading || inFlight.current) return;
    inFlight.current = true;
    mutate({
      variables: {
        input: {
          stockItemId: item.id,
          projectId,
          targetHardwareCategory: category.trim(),
          targetProductCode: productCode.trim(),
          quantity: q,
          targetAisle: aisle.trim() || null,
          targetRow: row.trim() || null,
          targetBay: bay.trim() || null,
        },
      },
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Allocate ${item.productCode} to a project`}
      // #1548: the primary action is the form's submit, so Enter in the quantity does what the button does,
      // and is refused whenever the button is disabled.
      onSubmit={handleSubmit}
      submitDisabled={!valid || loading}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={!valid || loading}>
            Allocate
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {error && <Alert severity="error">{userMessage(error)}</Alert>}
        <Box sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography component="div" sx={microLabelSx}>
            Source · {item.available} available
          </Typography>
          <Typography sx={monoSx}>
            {item.hardwareCategory} / {item.productCode}
          </Typography>
        </Box>
        {/* #959: the shared picker, so the job number shows beside the name and either one searches -
            near-duplicate job names made the bare name list easy to allocate onto the wrong job. */}
        <ProjectPicker label="Target project" value={project} onChange={setPicked} />
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
          autoFocus
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          inputProps={{ min: 1, max: item.available }}
        />
        <Typography variant="body2" color="text.secondary">
          Optional: pre-locate the new inventory row at a defined location (leave blank for unlocated).
        </Typography>
        <Stack direction="row" spacing={2}>
          <LocationAutocomplete label="Aisle" value={aisle} onChange={setAisle} options={aisleOptions} freeSolo={false} />
          <LocationAutocomplete label="Row" value={row} onChange={setRow} options={rowOptions} freeSolo={false} />
          <LocationAutocomplete label="Bay" value={bay} onChange={setBay} options={bayOptions} freeSolo={false} />
        </Stack>
        {blockedReason && !loading && (
          <Typography variant="body2" color="text.secondary" data-testid="blocked-reason">
            {blockedReason}
          </Typography>
        )}
      </Stack>
    </Modal>
  );
}
