import { useRef, useState } from 'react';
import {
  Box,
  Button,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Alert,
  Typography,
} from '@mui/material';
import { Plus, X } from 'lucide-react';
import { useApolloClient, useMutation, useQuery } from '@apollo/client/react';
import Modal from '../../../components/Modal';
import LoadError from '../../../components/LoadError';
import LocationAutocomplete from '../../../components/LocationAutocomplete';
import ProjectPicker from '../../../components/ProjectPicker';
import { useToast } from '../../../components/Toast';
import { GET_PROJECTS } from '../../../graphql/shared';
import { ALLOCATE_STOCK_TO_PROJECT, GET_ALLOCATION_TARGETS } from '../../../graphql/warehouse';
import { WAREHOUSE_REFETCH_QUERIES } from '../../../graphql/refetch';
import { microLabelSx, monoSx } from '../../../theme';
import type { Project } from '../../../types/project';
import type { StockItem } from '../StockPoolView';
import { useDefinedLocationPick } from '../useDefinedLocationPick';
import { userMessage } from '../../../graphql/userMessage';
import { isStaleRowRefusal } from '../../../graphql/staleRow';

interface Props {
  item: StockItem;
  onClose: () => void;
  onSuccess: () => void;
  prefillProjectId?: string;
  prefillCategory?: string;
  prefillProductCode?: string;
}

interface AllocationPair {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  stillNeededQuantity: number;
}

interface AllocationTargets {
  scheduleHardware: boolean;
  hasSchedule: boolean;
  pairs: AllocationPair[];
}

/** One target on a scheduled project: a schedule pair, and how many units go under it. */
interface TargetLine {
  pair: string;
  quantity: string;
}

const pairKey = (p: { hardwareCategory: string; productCode: string }) => `${p.hardwareCategory}\u0000${p.productCode}`;

/**
 * The lines a scheduled project opens with (#1647): every pair the pool row's code is scheduled under,
 * its own category first, each given what it still needs until the available units run out. A code on
 * the schedule under two categories is split across both. A code the schedule never names opens one
 * empty line, so the user has to say where the units go.
 */
function initialLines(pairs: AllocationPair[], item: StockItem): TargetLine[] {
  const own = pairs
    .filter((p) => p.productCode === item.productCode)
    .sort(
      (a, b) =>
        Number(b.hardwareCategory === item.hardwareCategory) - Number(a.hardwareCategory === item.hardwareCategory),
    );
  if (own.length === 0) return [{ pair: '', quantity: '1' }];
  let left = item.available;
  const lines: TargetLine[] = [];
  for (const p of own) {
    const q = Math.min(left, p.stillNeededQuantity);
    if (q > 0) {
      lines.push({ pair: pairKey(p), quantity: String(q) });
      left -= q;
    }
  }
  return lines.length > 0 ? lines : [{ pair: pairKey(own[0]), quantity: '1' }];
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
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const { showToast } = useToast();
  const client = useApolloClient();
  // Units this dialog has already landed off the pool row, by earlier lines or an earlier attempt that
  // failed partway: the row the server holds is that much smaller than the one the dialog was opened on.
  const [allocated, setAllocated] = useState(0);
  // #1548: Enter and a click in the same moment must not send it twice; set before `submitting` re-renders.
  const inFlight = useRef(false);

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const project =
    picked !== undefined
      ? picked
      : (projectsData?.projects.find((p) => p.id === prefillProjectId) ?? null);
  const projectId = project?.id ?? '';

  const { data: targetsData, error: targetsError } = useQuery<{ allocationTargets: AllocationTargets }>(
    GET_ALLOCATION_TARGETS,
    { variables: { stockItemId: item.id, projectId }, skip: !projectId, fetchPolicy: 'network-only' },
  );
  const targets = projectId ? targetsData?.allocationTargets : undefined;
  // #1647: schedule hardware going to a scheduled project names one of the schedule's pairs - the
  // server refuses any other. A type-code row is exempt, and a project with no schedule yet takes the
  // units as floating inventory (ruled on #1756); both keep the free-text pair.
  const scheduleMode = !!targets && targets.scheduleHardware && targets.hasSchedule;
  const floating = !!targets && targets.scheduleHardware && !targets.hasSchedule;
  const pairs = targets?.pairs ?? [];
  const pairByKey = new Map(pairs.map((p) => [pairKey(p), p]));

  // The lines follow the project: picking another one starts over from its schedule.
  const [edited, setEdited] = useState<{ projectId: string; lines: TargetLine[] } | null>(null);
  const lines: TargetLine[] = !scheduleMode
    ? []
    : edited?.projectId === projectId
      ? edited.lines
      : initialLines(pairs, item);
  const setLines = (next: TargetLine[]) => setEdited({ projectId, lines: next });
  const setLine = (index: number, patch: Partial<TargetLine>) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  const [mutate] = useMutation(ALLOCATE_STOCK_TO_PROJECT, {
    refetchQueries: WAREHOUSE_REFETCH_QUERIES,
    awaitRefetchQueries: true,
  });

  // #1046: the pre-locate bin is optional, but when given it is a strict pick from the stock item's
  // warehouse - the server refuses any bin not on the Locations tab. All three or none.
  const { aisleOptions, rowOptions, bayOptions, isDefinedPick, registryLoaded, registryError, refetchRegistry, noOptionsText } =
    useDefinedLocationPick([item.warehouseId], aisle, row, bay);
  const binBlank = !aisle.trim() && !row.trim() && !bay.trim();
  const binOk = binBlank || isDefinedPick;

  const available = item.available - allocated;
  const isCount = (raw: string) => Number.isInteger(Number(raw)) && Number(raw) >= 1;
  const q = Number(quantity);
  const lineTotal = lines.reduce((sum, l) => sum + (isCount(l.quantity) ? Number(l.quantity) : 0), 0);
  const duplicatePair = new Set(lines.map((l) => l.pair)).size !== lines.length;
  // #1548 (#981): a dead Allocate says what it is waiting for.
  const blockedReason = !projectId
    ? 'Pick the target project.'
    : !targets && !targetsError
      ? "Reading the project's schedule."
      : scheduleMode
          ? lines.some((l) => !l.pair)
            ? 'Pick a schedule product for every line.'
            : duplicatePair
              ? 'Each schedule product can take one line.'
              : lines.some((l) => !isCount(l.quantity))
                ? 'Enter a whole number of at least 1 on every line.'
                : lineTotal > available
                  ? `The lines add up to ${lineTotal}; only ${available} are available.`
                  : !binOk
                    ? 'Pick an aisle, row and bay defined on the Locations tab, or clear all three to leave it unlocated.'
                    : null
          : !category.trim() || !productCode.trim()
            ? 'Enter the target hardware category and product code.'
            : !(Number.isInteger(q) && q >= 1 && q <= available)
              ? `Enter a whole number from 1 to ${available}.`
              : !binOk
                ? 'Pick an aisle, row and bay defined on the Locations tab, or clear all three to leave it unlocated.'
                : null;
  // A failed read of the schedule leaves the free-text pair; the server still holds it to the rule.
  const valid = blockedReason === null;

  const handleSubmit = async () => {
    if (!valid || submitting || inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setFormError(null);
    const allocations = scheduleMode
      ? lines.map((l) => {
          const p = pairByKey.get(l.pair)!;
          return { category: p.hardwareCategory, code: p.productCode, quantity: Number(l.quantity) };
        })
      : [{ category: category.trim(), code: productCode.trim(), quantity: q }];
    let done = 0;
    let landed = allocated;
    try {
      // One allocation per line, in turn, so a failure partway says exactly how many landed.
      for (const a of allocations) {
        await mutate({
          variables: {
            input: {
              stockItemId: item.id,
              projectId,
              targetHardwareCategory: a.category,
              targetProductCode: a.code,
              quantity: a.quantity,
              targetAisle: aisle.trim() || null,
              targetRow: row.trim() || null,
              targetBay: bay.trim() || null,
              // The pool row's count as it stands after what this dialog already moved off it, so a
              // resend after a lost reply is refused, not applied twice (#1552).
              expectedQuantity: item.quantity - landed,
            },
          },
        });
        done += 1;
        landed += a.quantity;
      }
      showToast('Stock allocated to project inventory', 'success');
      onSuccess();
    } catch (err) {
      setAllocated(landed);
      const message = userMessage(err);
      if (isStaleRowRefusal(err)) {
        // The row moved since this opened - or this very move landed and only its reply was lost
        // (#1552). Close: the refetch redraws the grid, and reopening starts from the fresh count.
        showToast(done > 0 ? `${message} - ${done} of ${allocations.length} allocated.` : message, 'error');
        void client.refetchQueries({ include: WAREHOUSE_REFETCH_QUERIES });
        onClose();
        return;
      }
      const summary = done > 0 ? `${message} - ${done} of ${allocations.length} allocated.` : message;
      // The lines that landed drop out, so allocating again sends only what is still to go.
      if (done > 0) setLines(lines.slice(done));
      setFormError(summary);
      showToast(summary, 'error');
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Allocate ${item.productCode} to a project`}
      // #1548: the primary action is the form's submit, so Enter in the quantity does what the button does,
      // and is refused whenever the button is disabled.
      onSubmit={handleSubmit}
      submitDisabled={!valid || submitting}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={!valid || submitting}>
            Allocate
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        {formError && <Alert severity="error">{formError}</Alert>}
        {targetsError && (
          <Alert severity="warning">The project's schedule could not be read: {userMessage(targetsError, { reading: true })}</Alert>
        )}
        <Box sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography component="div" sx={microLabelSx}>
            Source · {available} available
          </Typography>
          <Typography sx={monoSx}>
            {item.hardwareCategory} / {item.productCode}
          </Typography>
        </Box>
        {/* #959: the shared picker, so the job number shows beside the name and either one searches -
            near-duplicate job names made the bare name list easy to allocate onto the wrong job. */}
        <ProjectPicker label="Target project" value={project} onChange={setPicked} />
        {scheduleMode ? (
          <Stack spacing={1.5}>
            <Typography component="div" sx={microLabelSx}>
              Schedule products · {lineTotal} of {available} allocated
            </Typography>
            {lines.map((line, index) => (
              <Stack key={index} direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
                <TextField
                  select
                  label={`Schedule product ${index + 1}`}
                  value={line.pair}
                  onChange={(e) => setLine(index, { pair: e.target.value })}
                  required
                  sx={{ flex: 1, minWidth: 0 }}
                >
                  {pairs.map((p) => (
                    <MenuItem key={pairKey(p)} value={pairKey(p)}>
                      <Box component="span" sx={{ ...monoSx, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {p.hardwareCategory} / {p.productCode}
                      </Box>
                      <Box component="span" sx={{ ml: 1, color: 'text.secondary', whiteSpace: 'nowrap' }}>
                        · {p.stillNeededQuantity} still needed
                      </Box>
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  label="Quantity"
                  type="number"
                  value={line.quantity}
                  onChange={(e) => setLine(index, { quantity: e.target.value })}
                  required
                  inputProps={{ min: 1, max: available, 'aria-label': `Quantity ${index + 1}` }}
                  sx={{ width: 110, flexShrink: 0 }}
                />
                {lines.length > 1 && (
                  <IconButton
                    aria-label={`Remove line ${index + 1}`}
                    onClick={() => setLines(lines.filter((_, i) => i !== index))}
                    sx={{ mt: 1 }}
                  >
                    <X size={18} strokeWidth={1.75} />
                  </IconButton>
                )}
              </Stack>
            ))}
            <Box>
              <Button
                size="small"
                startIcon={<Plus size={16} strokeWidth={1.75} />}
                onClick={() => setLines([...lines, { pair: '', quantity: '1' }])}
              >
                Add a schedule product
              </Button>
            </Box>
          </Stack>
        ) : (
          <>
            {floating && (
              <Alert severity="info">
                This project has no hardware schedule yet. The units go in as floating inventory: on the project,
                but tied to no schedule line, so nothing claims them until they are.
              </Alert>
            )}
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
              label={`Quantity (max ${available})`}
              autoFocus
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              required
              inputProps={{ min: 1, max: available }}
            />
          </>
        )}
        <Typography variant="body2" color="text.secondary">
          Optional: pre-locate the new inventory row at a defined location (leave blank for unlocated).
        </Typography>
        {/* #1878: a failed registry read left the pickers offering nothing, as if no bin were defined. */}
        {registryError && !registryLoaded && (
          <LoadError what="the defined locations" error={registryError} onRetry={refetchRegistry} />
        )}
        <Stack direction="row" spacing={2}>
          <LocationAutocomplete label="Aisle" value={aisle} onChange={setAisle} options={aisleOptions} freeSolo={false} noOptionsText={noOptionsText} />
          <LocationAutocomplete label="Row" value={row} onChange={setRow} options={rowOptions} freeSolo={false} noOptionsText={noOptionsText} />
          <LocationAutocomplete label="Bay" value={bay} onChange={setBay} options={bayOptions} freeSolo={false} noOptionsText={noOptionsText} />
        </Stack>
        {blockedReason && !submitting && (
          <Typography variant="body2" color="text.secondary" data-testid="blocked-reason">
            {blockedReason}
          </Typography>
        )}
      </Stack>
    </Modal>
  );
}
