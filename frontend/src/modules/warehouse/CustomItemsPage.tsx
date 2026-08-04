import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  List,
  ListItemButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef, type GridRowParams } from '@mui/x-data-grid';
import { Plus, RotateCcw, Tag } from 'lucide-react';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { FadeIn } from '../../motion';
import { microLabelSx, monoSx } from '../../theme';
import {
  CREATE_CUSTOM_INVENTORY_ITEM,
  CREATE_INVENTORY_ITEM_ATTRIBUTE,
  CREATE_INVENTORY_ITEM_TYPE,
  UPDATE_CUSTOM_INVENTORY_ITEM,
  UPDATE_INVENTORY_ITEM_ATTRIBUTE,
  UPDATE_INVENTORY_ITEM_TYPE,
} from '../../graphql/customItems';
import {
  useCustomInventoryItems,
  useInventoryItemTypes,
  type CustomInventoryItem,
  type InventoryItemType,
} from '../../hooks/useCustomItems';

/**
 * The catalog of inventory that the hardware schedule never describes (#454).
 *
 * Frames, specialties and consumables travel the same pipeline as schedule hardware - bought,
 * received, stored, shipped - but nothing upstream says what one *is*, because they were never on a
 * TITAN schedule to begin with. This page is where that description lives: a type, the attributes
 * worth recording for that type, and the products catalogued under it.
 *
 * It sits in Warehouse rather than Admin deliberately. The people who know a frame's fire rating are
 * the people receiving it, and a catalog that needs an admin to extend is a catalog that gets worked
 * around with free text on a PO line.
 *
 * Nothing here moves stock. Ordering a catalogued item writes its type's code into the PO line's
 * hardware category, and the pipeline carries it from there exactly as it carries a hinge.
 */
export default function CustomItemsPage() {
  const { showToast } = useToast();
  const { types, loading: typesLoading, refetch: refetchTypes } = useInventoryItemTypes();
  const [pickedTypeId, setPickedTypeId] = useState<string | null>(null);

  // Land on the first type rather than an empty right-hand pane - there is always at least one, the
  // three the migration seeds. Derived rather than written into state on arrival: the list lands a
  // render after the page mounts, and catching up with it in an effect is a cascading render for
  // something a fallback answers.
  const selectedType = useMemo(
    () => types.find((t) => t.id === pickedTypeId) ?? types[0] ?? null,
    [types, pickedTypeId],
  );
  const selectedTypeId = selectedType?.id ?? null;

  const {
    items,
    loading: itemsLoading,
    refetch: refetchItems,
  } = useCustomInventoryItems({ typeId: selectedType?.id, skip: !selectedType });

  const [typeDialogOpen, setTypeDialogOpen] = useState(false);
  const [itemDialogOpen, setItemDialogOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<CustomInventoryItem | null>(null);

  const [updateType] = useMutation(UPDATE_INVENTORY_ITEM_TYPE, {
    onCompleted: () => {
      showToast('Type updated', 'success');
      refetchTypes();
    },
    onError: (e) => showToast(e.message, 'error'),
  });

  const openItemDialog = useCallback((item: CustomInventoryItem | null) => {
    setEditingItem(item);
    setItemDialogOpen(true);
  }, []);

  return (
    <Box>
      <FadeIn>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="flex-start"
          sx={{ mb: 2 }}
          gap={2}
          flexWrap="wrap"
        >
          <Box>
            <Typography variant="h5" sx={{ mb: 0.25 }}>
              Custom Items
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Frames, specialties, consumables - inventory the hardware schedule does not describe.
            </Typography>
          </Box>
          <Button
            variant="outlined"
            startIcon={<Plus size={16} strokeWidth={1.75} />}
            onClick={() => setTypeDialogOpen(true)}
          >
            Add Type
          </Button>
        </Stack>
      </FadeIn>

      {typesLoading && types.length === 0 ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <Box sx={{ width: 240, flexShrink: 0, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
            <Typography sx={{ ...microLabelSx, display: 'block', px: 1.5, pt: 1.25 }}>
              Types
            </Typography>
            <List dense disablePadding sx={{ py: 0.5 }}>
              {types.map((type) => (
                <ListItemButton
                  key={type.id}
                  selected={type.id === selectedTypeId}
                  onClick={() => setPickedTypeId(type.id)}
                  sx={{ py: 0.75 }}
                >
                  <Box sx={{ minWidth: 0, flex: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {type.name}
                      </Typography>
                      {!type.isActive && <Chip size="small" variant="outlined" label="Retired" />}
                    </Box>
                    <Typography component="div" sx={{ ...monoSx, fontSize: '0.7rem', color: 'text.secondary' }}>
                      {type.code}
                    </Typography>
                  </Box>
                </ListItemButton>
              ))}
            </List>
          </Box>

          <Box sx={{ flex: 1, minWidth: 320 }}>
            {selectedType ? (
              <TypePanel
                key={selectedType.id}
                type={selectedType}
                items={items}
                itemsLoading={itemsLoading}
                onRefetchTypes={refetchTypes}
                onAddItem={() => openItemDialog(null)}
                onEditItem={openItemDialog}
                onToggleActive={() =>
                  updateType({ variables: { id: selectedType.id, isActive: !selectedType.isActive } })
                }
              />
            ) : (
              <Alert severity="info">No inventory item types yet. Add one to get started.</Alert>
            )}
          </Box>
        </Box>
      )}

      <TypeDialog
        open={typeDialogOpen}
        onClose={() => setTypeDialogOpen(false)}
        existingCount={types.length}
        onCreated={(created) => {
          setTypeDialogOpen(false);
          refetchTypes();
          setPickedTypeId(created.id);
        }}
      />

      {selectedType && (
        <ItemDialog
          open={itemDialogOpen}
          type={selectedType}
          item={editingItem}
          onClose={() => {
            setItemDialogOpen(false);
            setEditingItem(null);
          }}
          onSaved={() => {
            setItemDialogOpen(false);
            setEditingItem(null);
            refetchItems();
          }}
        />
      )}
    </Box>
  );
}

/** A type's attribute definitions and its item catalog - everything scoped to one type. */
function TypePanel({
  type,
  items,
  itemsLoading,
  onRefetchTypes,
  onAddItem,
  onEditItem,
  onToggleActive,
}: {
  type: InventoryItemType;
  items: CustomInventoryItem[];
  itemsLoading: boolean;
  onRefetchTypes: () => void;
  onAddItem: () => void;
  onEditItem: (item: CustomInventoryItem) => void;
  onToggleActive: () => void;
}) {
  const { showToast } = useToast();
  const [newAttribute, setNewAttribute] = useState('');

  const settle = (message: string) => {
    showToast(message, 'success');
    onRefetchTypes();
  };

  const [createAttribute, { loading: creatingAttribute }] = useMutation(CREATE_INVENTORY_ITEM_ATTRIBUTE, {
    onCompleted: () => {
      setNewAttribute('');
      settle('Attribute added');
    },
    onError: (e) => showToast(e.message, 'error'),
  });
  const [updateAttribute] = useMutation(UPDATE_INVENTORY_ITEM_ATTRIBUTE, {
    onCompleted: () => settle('Attribute updated'),
    onError: (e) => showToast(e.message, 'error'),
  });

  /**
   * Add the attribute at the end.
   *
   * The position comes off the highest sortOrder in use rather than the count, so a retired
   * attribute holding its place cannot make the next one collide with it. One entry point for both
   * the button and Enter, so the in-flight guard covers both - without it a fast double-Enter fires
   * two creates and the second comes back as a name conflict the user did nothing to cause.
   */
  const submitAttribute = () => {
    const name = newAttribute.trim();
    if (!name || creatingAttribute) return;
    const sortOrder = type.attributes.reduce((highest, a) => Math.max(highest, a.sortOrder + 1), 0);
    createAttribute({ variables: { typeId: type.id, name, sortOrder } });
  };

  const activeAttributes = type.attributes.filter((a) => a.isActive);

  const columns = useMemo<GridColDef[]>(() => {
    const base: GridColDef[] = [
      {
        field: 'productCode',
        headerName: 'Product Code',
        flex: 1,
        minWidth: 140,
        renderCell: (params: { row: CustomInventoryItem }) => (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography component="span" sx={monoSx}>
              {params.row.productCode}
            </Typography>
            {!params.row.isActive && <Chip size="small" variant="outlined" label="Retired" />}
          </Box>
        ),
      },
      {
        field: 'description',
        headerName: 'Description',
        flex: 1.4,
        minWidth: 160,
        valueGetter: (_v: unknown, row: CustomInventoryItem) => row.description ?? '—',
      },
    ];
    return [
      ...base,
      ...activeAttributes.map<GridColDef>((attribute) => ({
        field: `attr:${attribute.id}`,
        headerName: attribute.name,
        flex: 1,
        minWidth: 120,
        sortable: false,
        valueGetter: (_v: unknown, row: CustomInventoryItem) =>
          row.values.find((value) => value.attributeId === attribute.id)?.value || '—',
      })),
    ];
  }, [activeAttributes]);

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Tag size={18} strokeWidth={1.75} />
          <Typography variant="h6">{type.name}</Typography>
          <Chip size="small" label={type.code} sx={monoSx} />
        </Box>
        <Button size="small" onClick={onToggleActive}>
          {type.isActive ? 'Retire type' : 'Reactivate type'}
        </Button>
      </Stack>

      {!type.isActive && (
        <Alert severity="warning" sx={{ mt: 1.5 }}>
          This type is retired. Stock received under {type.code} is unaffected and still reads
          correctly; it is only hidden from the pickers that offer new items.
        </Alert>
      )}

      <Divider sx={{ my: 2 }} />

      <Typography sx={{ ...microLabelSx, display: 'block', mb: 0.75 }}>
        Attributes
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        What is worth recording about every {type.name.toLowerCase()} item. Each type keeps its own
        set.
      </Typography>

      <Stack direction="row" spacing={1} sx={{ mb: 1.5, maxWidth: 480 }}>
        <TextField
          size="small"
          label="New attribute"
          placeholder="Fire Rating"
          value={newAttribute}
          onChange={(e) => setNewAttribute(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submitAttribute();
          }}
          fullWidth
        />
        <Button
          variant="outlined"
          startIcon={<Plus size={16} strokeWidth={1.75} />}
          disabled={!newAttribute.trim() || creatingAttribute}
          onClick={submitAttribute}
        >
          Add
        </Button>
      </Stack>

      {type.attributes.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          None yet. Items can still be catalogued - they just carry a code and a description.
        </Typography>
      ) : (
        <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', rowGap: 1 }}>
          {type.attributes.map((attribute) => (
            <Chip
              key={attribute.id}
              label={attribute.name}
              variant={attribute.isActive ? 'filled' : 'outlined'}
              size="small"
              onDelete={
                attribute.isActive
                  ? () => updateAttribute({ variables: { id: attribute.id, isActive: false } })
                  : undefined
              }
              deleteIcon={
                attribute.isActive ? <RotateCcw size={14} strokeWidth={1.75} /> : undefined
              }
              icon={
                attribute.isActive ? undefined : (
                  <Tooltip title="Reactivate">
                    <IconButton
                      size="small"
                      aria-label={`Reactivate ${attribute.name}`}
                      onClick={() => updateAttribute({ variables: { id: attribute.id, isActive: true } })}
                    >
                      <RotateCcw size={13} strokeWidth={1.75} />
                    </IconButton>
                  </Tooltip>
                )
              }
              sx={{ opacity: attribute.isActive ? 1 : 0.6 }}
            />
          ))}
        </Stack>
      )}

      <Divider sx={{ my: 2 }} />

      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography sx={{ ...microLabelSx, display: 'block' }}>Items</Typography>
        <Button
          size="small"
          variant="contained"
          startIcon={<Plus size={16} strokeWidth={1.75} />}
          onClick={onAddItem}
        >
          Add Item
        </Button>
      </Stack>

      <DataGrid
        rows={items}
        columns={columns}
        loading={itemsLoading}
        autoHeight
        density="compact"
        disableRowSelectionOnClick
        onRowClick={(params: GridRowParams) => onEditItem(params.row as CustomInventoryItem)}
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ '& .MuiDataGrid-row': { cursor: 'pointer' } }}
      />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>
        Click a row to edit its description and attribute values. Product codes are fixed once
        created - stock already received carries them.
      </Typography>
    </Box>
  );
}

/** Create a type. The code is derived live so the user sees what inventory will carry before saving. */
function TypeDialog({
  open,
  onClose,
  existingCount,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  existingCount: number;
  onCreated: (created: InventoryItemType) => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Add inventory item type" maxWidth="sm">
      {/* The form is its own component so closing unmounts it, which is what clears a half-typed
          name and a failed attempt's error. */}
      <TypeForm onClose={onClose} existingCount={existingCount} onCreated={onCreated} />
    </Modal>
  );
}

function TypeForm({
  onClose,
  existingCount,
  onCreated,
}: {
  onClose: () => void;
  existingCount: number;
  onCreated: (created: InventoryItemType) => void;
}) {
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  const [createType, { loading }] = useMutation<{ createInventoryItemType: InventoryItemType }>(
    CREATE_INVENTORY_ITEM_TYPE,
    {
      onCompleted: (data) => onCreated(data.createInventoryItemType),
      onError: (e) => setError(e.message),
    },
  );

  // Mirrors the backend's `_normalize_code`. Shown, not sent: the server derives it again from the
  // name, so the preview can never disagree with what is stored.
  const previewCode = useMemo(
    () =>
      name
        .trim()
        .toUpperCase()
        .replace(/[^A-Z0-9]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '')
        .slice(0, 50),
    [name],
  );

  const submit = () => {
    if (!name.trim() || loading) return;
    createType({ variables: { name: name.trim(), sortOrder: existingCount } });
  };

  return (
    <Stack spacing={2} sx={{ mt: 0.5 }}>
      <Alert severity="info">
        A type's code is what purchase orders and inventory carry as the hardware category. It is
        derived from the name and fixed from then on, because stock already on a shelf carries it.
      </Alert>
      {error && <Alert severity="error">{error}</Alert>}
      <TextField
        autoFocus
        size="small"
        label="Name"
        placeholder="Gaskets"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit();
        }}
        fullWidth
      />
      <Box>
        <Typography sx={{ ...microLabelSx, display: 'block' }}>Code</Typography>
        <Typography sx={{ ...monoSx, color: previewCode ? 'text.primary' : 'text.secondary' }}>
          {previewCode || '—'}
        </Typography>
      </Box>
      <Stack direction="row" spacing={1} justifyContent="flex-end">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || loading} onClick={submit}>
          Create
        </Button>
      </Stack>
    </Stack>
  );
}

/** Create or edit one catalogued product, with a field per active attribute. */
function ItemDialog({
  open,
  type,
  item,
  onClose,
  onSaved,
}: {
  open: boolean;
  type: InventoryItemType;
  item: CustomInventoryItem | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={item ? `Edit ${item.productCode}` : `Add ${type.name} item`}
      maxWidth="sm"
    >
      {/* Its own component so closing unmounts it: the form seeds from `item` at mount, which is
          what makes opening a different row show that row rather than the last one's values. */}
      <ItemForm type={type} item={item} onClose={onClose} onSaved={onSaved} />
    </Modal>
  );
}

function ItemForm({
  type,
  item,
  onClose,
  onSaved,
}: {
  type: InventoryItemType;
  item: CustomInventoryItem | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [productCode, setProductCode] = useState(item?.productCode ?? '');
  const [description, setDescription] = useState(item?.description ?? '');
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((item?.values ?? []).map((value) => [value.attributeId, value.value])),
  );
  const [error, setError] = useState<string | null>(null);

  const activeAttributes = useMemo(
    () => type.attributes.filter((a) => a.isActive),
    [type.attributes],
  );

  const [createItem, { loading: creating }] = useMutation(CREATE_CUSTOM_INVENTORY_ITEM, {
    onCompleted: onSaved,
    onError: (e) => setError(e.message),
  });
  const [updateItem, { loading: updating }] = useMutation(UPDATE_CUSTOM_INVENTORY_ITEM, {
    onCompleted: onSaved,
    onError: (e) => setError(e.message),
  });
  const saving = creating || updating;

  const submit = () => {
    if (saving) return;
    // Send every active attribute, including the blanked ones: a value the user cleared has to
    // reach the server as an empty string to be deleted, and omitting it would silently keep it.
    const valuePayload = activeAttributes.map((attribute) => ({
      attributeId: attribute.id,
      value: values[attribute.id] ?? '',
    }));

    if (item) {
      updateItem({
        variables: {
          id: item.id,
          description: description.trim() || null,
          values: valuePayload,
        },
      });
      return;
    }
    if (!productCode.trim()) return;
    createItem({
      variables: {
        typeId: type.id,
        productCode: productCode.trim(),
        description: description.trim() || null,
        values: valuePayload,
      },
    });
  };

  return (
    <Stack spacing={2} sx={{ mt: 0.5 }}>
      {error && <Alert severity="error">{error}</Alert>}
      <TextField
        autoFocus={!item}
        size="small"
        label="Product code"
        value={productCode}
        onChange={(e) => setProductCode(e.target.value)}
        disabled={Boolean(item)}
        helperText={item ? 'Fixed - inventory already received carries this code.' : undefined}
        fullWidth
        sx={{ '& input': monoSx }}
      />
      <TextField
        size="small"
        label="Description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        fullWidth
      />

      {activeAttributes.length > 0 && (
        <Box>
          <Typography sx={{ ...microLabelSx, display: 'block', mb: 1 }}>
            {type.name} attributes
          </Typography>
          <Stack spacing={1.5}>
            {activeAttributes.map((attribute) => (
              <TextField
                key={attribute.id}
                size="small"
                label={attribute.name}
                value={values[attribute.id] ?? ''}
                onChange={(e) => setValues((prev) => ({ ...prev, [attribute.id]: e.target.value }))}
                fullWidth
              />
            ))}
          </Stack>
        </Box>
      )}

      {item && (
        <Button
          size="small"
          sx={{ alignSelf: 'flex-start' }}
          onClick={() => updateItem({ variables: { id: item.id, isActive: !item.isActive } })}
        >
          {item.isActive ? 'Retire item' : 'Reactivate item'}
        </Button>
      )}

      <Stack direction="row" spacing={1} justifyContent="flex-end">
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={saving || (!item && !productCode.trim())}
          onClick={submit}
        >
          {item ? 'Save' : 'Create'}
        </Button>
      </Stack>
    </Stack>
  );
}
