import { useMemo, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import Modal from '../../components/Modal';
import { microLabelSx, monoSx } from '../../theme';
import {
  useCustomInventoryItems,
  useInventoryItemTypes,
  type CustomInventoryItem,
} from '../../hooks/useCustomItems';

interface Props {
  open: boolean;
  onClose: () => void;
  onPick: (item: CustomInventoryItem) => void;
}

/**
 * Order something that was never on a hardware schedule - a frame, a specialty, a consumable (#454).
 *
 * The picker exists so the buyer does not have to remember that a frame's hardware category is
 * spelled FRAME. Picking writes the catalog's own `hardwareCategory` and `productCode` onto the line
 * verbatim, which is what makes the received stock match its catalog entry on the inventory screen -
 * a typo in either field would produce stock nothing can describe.
 *
 * Only active types and items are offered. A retired one is still readable everywhere it already
 * appears; it just should not be ordered again.
 */
export default function CustomItemPicker({ open, onClose, onPick }: Props) {
  return (
    <Modal open={open} onClose={onClose} title="Add a custom item" maxWidth="sm">
      {/* The body is its own component so closing the dialog unmounts it, which is what resets the
          selection - a reopened picker must not still be holding the last item that was added. */}
      <PickerBody onClose={onClose} onPick={onPick} />
    </Modal>
  );
}

function PickerBody({
  onClose,
  onPick,
}: {
  onClose: () => void;
  onPick: (item: CustomInventoryItem) => void;
}) {
  const { types } = useInventoryItemTypes({ activeOnly: true });
  const [pickedTypeId, setPickedTypeId] = useState<string | null>(null);
  const [selected, setSelected] = useState<CustomInventoryItem | null>(null);

  // Default to the first type without an effect: the list arrives after the first render, and a
  // state write to catch up with it is a cascading render for something derivation answers.
  const typeId = pickedTypeId ?? types[0]?.id ?? '';

  const { items, loading } = useCustomInventoryItems({
    typeId: typeId || undefined,
    activeOnly: true,
    skip: !typeId,
  });

  const selectedType = useMemo(() => types.find((t) => t.id === typeId) ?? null, [types, typeId]);

  return (
    <Stack spacing={2} sx={{ mt: 0.5 }}>
      <Alert severity="info">
        Frames, specialties and consumables are catalogued in Warehouse &rarr; Custom Items. Picking
        one here fills in the hardware category and product code the warehouse will receive it
        under.
      </Alert>

      {types.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No active item types. Add one in Warehouse &rarr; Custom Items first.
        </Typography>
      ) : (
        <>
          <FormControl size="small" fullWidth>
            <InputLabel>Type</InputLabel>
            <Select
              label="Type"
              value={typeId}
              onChange={(e) => {
                setPickedTypeId(e.target.value);
                setSelected(null);
              }}
            >
              {types.map((type) => (
                <MenuItem key={type.id} value={type.id}>
                  {type.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Autocomplete
            options={items}
            loading={loading}
            value={selected}
            onChange={(_e, value) => setSelected(value)}
            getOptionLabel={(option) =>
              option.description ? `${option.productCode} — ${option.description}` : option.productCode
            }
            isOptionEqualToValue={(option, value) => option.id === value.id}
            renderInput={(params) => (
              <TextField
                {...params}
                size="small"
                label="Item"
                placeholder={selectedType ? `Search ${selectedType.name.toLowerCase()}` : 'Search'}
              />
            )}
            renderOption={(props, option) => {
              const { key, ...rest } = props as typeof props & { key: string };
              return (
                <Box component="li" key={key} {...rest} sx={{ display: 'block !important' }}>
                  <Typography component="span" sx={monoSx}>
                    {option.productCode}
                  </Typography>
                  {option.description && (
                    <Typography variant="body2" color="text.secondary">
                      {option.description}
                    </Typography>
                  )}
                </Box>
              );
            }}
            noOptionsText={loading ? 'Loading…' : 'No items catalogued for this type yet'}
            fullWidth
          />

          {selected && (
            <Box>
              <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.75 }}>
                Will be ordered as
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mb: 1, flexWrap: 'wrap', rowGap: 1 }}>
                <Chip size="small" label={selected.hardwareCategory} sx={monoSx} />
                <Chip size="small" label={selected.productCode} sx={monoSx} variant="outlined" />
              </Stack>
              {selected.values.length > 0 && (
                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                  {selected.values.map((value) => (
                    <Chip
                      key={value.attributeId}
                      size="small"
                      variant="outlined"
                      label={`${value.attributeName}: ${value.value}`}
                    />
                  ))}
                </Stack>
              )}
            </Box>
          )}
        </>
      )}

      <Stack direction="row" spacing={1} justifyContent="flex-end">
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!selected}
          onClick={() => {
            if (selected) onPick(selected);
          }}
        >
          Add to PO
        </Button>
      </Stack>
    </Stack>
  );
}
