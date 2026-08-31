/**
 * The PO-draft organizing UI (#570): one card per draft, plus the split dialog.
 *
 * A draft is no longer a manufacturer group - it is a set of lines the buyer slices freely. Each card
 * carries the include toggle, an editable label, the delivery-date / cost-code / notes, and a ledger
 * whose rows can be moved whole to another draft or split by quantity. Kept out of PurchaseOrdersStep
 * so that step stays the orchestrator (cost-code fetch, layout, dialog state) and the per-card query
 * for prior order-as values stays hook-safe inside a component.
 */
import { useMemo, useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  IconButton,
  InputAdornment,
  Menu,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import { FileText, MoreVertical, Paperclip, X } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import OrderAsAutocomplete from '../../components/OrderAsAutocomplete';
import { GET_PRIOR_ORDER_AS_VALUES } from '../../graphql/shared';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import type { DraftAttachmentType, DraftGroup } from './types';

export interface GpCostCode {
  costCode: string;
  costElement: string;
  description: string | null;
}

export interface ProductMeta {
  productCode: string;
  hardwareCategory: string;
  unitCost: number;
}

interface PriorOrderAsForProduct {
  productCode: string;
  values: string[];
}

interface PriorOrderAsQueryData {
  priorOrderAsValues: PriorOrderAsForProduct[];
}

export interface SplitContext {
  fromId: string;
  pk: string;
  productLabel: string;
  maxQty: number;
}

/** #632: the per-line reconciliation context - where this product already stands project-wide, so the
 *  buyer can judge a quantity without leaving the step. #639 renders it inline on every ledger row
 *  (Need / On Order / Rcvd / Avail) rather than behind a per-row info popover. */
export interface LineContext {
  /** The selected quantity - what this wizard pass says the schedule needs of the product. */
  needed: number;
  /** Placed with a vendor and not yet received, project-wide. */
  onOrder: number;
  /** Cumulative PO receipts, project-wide. */
  received: number;
  /** On the shelf and unclaimed (reservation-aware where loaded). */
  available: number;
}

interface DraftLine {
  pk: string;
  productCode: string;
  hardwareCategory: string;
  qty: number;
  unitCost: number;
  totalCost: number;
}

function buildLines(
  draft: DraftGroup,
  productCatalog: Map<string, ProductMeta>,
  unitCostOverrides: Map<string, number>,
): DraftLine[] {
  const lines: DraftLine[] = [];
  for (const [pk, qty] of draft.lines) {
    const meta = productCatalog.get(pk);
    const productCode = meta?.productCode ?? pk.split('|')[0] ?? pk;
    const hardwareCategory = meta?.hardwareCategory ?? pk.split('|')[1] ?? '';
    const unitCost = unitCostOverrides.get(pk) ?? meta?.unitCost ?? 0;
    lines.push({ pk, productCode, hardwareCategory, qty, unitCost, totalCost: unitCost * qty });
  }
  return lines.sort((a, b) => {
    const cat = a.hardwareCategory.localeCompare(b.hardwareCategory);
    return cat !== 0 ? cat : a.productCode.localeCompare(b.productCode);
  });
}

// ---- Split dialog ----

interface SplitLineDialogProps {
  ctx: SplitContext | null;
  targets: Array<{ id: string; label: string }>;
  onClose: () => void;
  onConfirm: (fromId: string, pk: string, qty: number, toId: string) => void;
}

export function SplitLineDialog({ ctx, targets, onClose, onConfirm }: SplitLineDialogProps) {
  // Held as raw text, not a number, so the buyer can clear the field and retype freely.
  // Nothing is clamped or flagged mid-keystroke - validation waits for blur or the Move click.
  const [qtyText, setQtyText] = useState('1');
  const [toId, setToId] = useState('');

  // Reset the fields whenever a fresh split is opened.
  const ctxKey = ctx ? `${ctx.fromId}|${ctx.pk}` : null;
  const [seenKey, setSeenKey] = useState<string | null>(null);
  if (ctx && ctxKey !== seenKey) {
    setSeenKey(ctxKey);
    setQtyText('1');
    setToId(targets[0]?.id ?? '');
  }

  const max = ctx?.maxQty ?? 1;
  const qty = parseInt(qtyText, 10);
  const qtyValid = !Number.isNaN(qty) && qty >= 1 && qty <= max;
  const valid = ctx != null && toId !== '' && qtyValid;

  return (
    <Dialog open={ctx != null} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ pb: 1 }}>Split line</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        {ctx && (
          <Typography variant="body2" color="text.secondary">
            <Box component="span" sx={monoSx}>
              {ctx.productLabel}
            </Box>{' '}
            has {max} in this draft. Move some to another draft; the rest stays here.
          </Typography>
        )}
        <TextField
          label="Quantity to move"
          type="number"
          size="small"
          value={qtyText}
          onChange={(e) => setQtyText(e.target.value)}
          onBlur={() => {
            // Settle the raw text into the valid range once the buyer is done typing.
            const v = parseInt(qtyText, 10);
            setQtyText(Number.isNaN(v) ? '1' : String(Math.max(1, Math.min(max, v))));
          }}
          slotProps={{ htmlInput: { min: 1, max, step: 1, sx: tabularSx } }}
          sx={{ width: 180 }}
        />
        <TextField
          select
          label="Move to"
          size="small"
          value={toId}
          onChange={(e) => setToId(e.target.value)}
          helperText={targets.length === 0 ? 'Create another draft to move into' : ' '}
        >
          {targets.map((t) => (
            <MenuItem key={t.id} value={t.id}>
              {t.label}
            </MenuItem>
          ))}
        </TextField>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!valid}
          onClick={() => {
            if (ctx && valid) {
              onConfirm(ctx.fromId, ctx.pk, qty, toId);
              onClose();
            }
          }}
        >
          Move{qtyValid ? ` ${qty}` : ''}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// ---- Draft card ----

// #639: the ledger carries four more columns now, so its type is sized against the card rather than
// fixed - cqw resolves against the grid's own size container, so the row shrinks to fit a narrow card
// instead of pushing the page sideways. The mono ramp stays one step under the UI ramp, as elsewhere.
const FS_CELL = 'clamp(0.7rem, 1.5cqw, 0.875rem)';
const FS_MONO = 'clamp(0.66rem, 1.4cqw, 0.8125rem)';
const FS_HEAD = 'clamp(0.5625rem, 1.1cqw, 0.6875rem)';

export interface DraftCardProps {
  projectId: string;
  draft: DraftGroup;
  otherDrafts: Array<{ id: string; label: string }>;
  productCatalog: Map<string, ProductMeta>;
  costCodes: GpCostCode[];
  unitCostOverrides: Map<string, number>;
  orderAsValues: Map<string, string>;
  // #632: the per-product selection pool and how much of it ALL drafts currently hold - the Qty
  // edit's ceiling is pool minus what the siblings hold.
  selectionTotals: Map<string, number>;
  heldByProduct: Map<string, number>;
  lineContextByPk: Map<string, LineContext>;
  onToggleIncluded: (id: string) => void;
  onRenameDraft: (id: string, label: string) => void;
  onUpdateDraftInfo: (id: string, field: 'notes' | 'preferredDeliveryDate' | 'costCode', value: string) => void;
  onUpdateUnitCost: (pk: string, value: number) => void;
  onUpdateOrderAs: (pk: string, value: string) => void;
  onMoveLine: (fromId: string, pk: string, qty: number, toId: string) => void;
  onUpdateLineQty: (id: string, pk: string, qty: number) => void;
  onRemoveLine: (id: string, pk: string) => void;
  onMergeDraft: (fromId: string, intoId: string) => void;
  onRemoveDraft: (id: string) => void;
  onOpenSplit: (ctx: SplitContext) => void;
  // #588: pre-attach documents that land on the PO this draft creates.
  onAddAttachments: (id: string, files: File[]) => void;
  onSetAttachmentType: (id: string, attachmentId: string, documentType: DraftAttachmentType) => void;
  onRemoveAttachment: (id: string, attachmentId: string) => void;
}

export function DraftCard({
  projectId,
  draft,
  otherDrafts,
  productCatalog,
  costCodes,
  unitCostOverrides,
  orderAsValues,
  selectionTotals,
  heldByProduct,
  lineContextByPk,
  onToggleIncluded,
  onRenameDraft,
  onUpdateDraftInfo,
  onUpdateUnitCost,
  onUpdateOrderAs,
  onMoveLine,
  onUpdateLineQty,
  onRemoveLine,
  onMergeDraft,
  onRemoveDraft,
  onOpenSplit,
  onAddAttachments,
  onSetAttachmentType,
  onRemoveAttachment,
}: DraftCardProps) {
  const lines = useMemo(
    () => buildLines(draft, productCatalog, unitCostOverrides),
    [draft, productCatalog, unitCostOverrides],
  );
  const attachments = draft.attachments ?? [];
  const productCodes = useMemo(() => Array.from(new Set(lines.map((l) => l.productCode))), [lines]);

  const { data: priorData } = useQuery<PriorOrderAsQueryData>(GET_PRIOR_ORDER_AS_VALUES, {
    variables: { projectId, productCodes },
    skip: productCodes.length === 0,
  });
  const priorMap = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const entry of priorData?.priorOrderAsValues ?? []) map.set(entry.productCode, entry.values);
    return map;
  }, [priorData]);

  const poTotal = lines.reduce((sum, l) => sum + l.totalCost, 0);
  const isEmpty = draft.lines.size === 0;

  // Card-level actions menu (merge / remove) and the per-row menu (move whole / split / remove), each
  // a single anchored Menu; the row menu remembers which line it was opened for.
  const [cardMenuAnchor, setCardMenuAnchor] = useState<HTMLElement | null>(null);
  const [rowMenu, setRowMenu] = useState<{ anchor: HTMLElement; line: DraftLine } | null>(null);

  return (
    <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, p: 2, mb: 2, opacity: draft.included ? 1 : 0.6 }}>
      {/* Header: include toggle + editable label + PO total + card menu */}
      <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1.5, mb: 2 }}>
        <FormControlLabel
          sx={{ m: 0, minWidth: 0, flex: 1, alignItems: 'flex-end' }}
          control={<Checkbox checked={draft.included} onChange={() => onToggleIncluded(draft.id)} sx={{ py: 0 }} />}
          label={
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={microLabelSx}>Vendor</Typography>
              {/* #632: the label IS the vendor - finalize writes it to vendor_name_snapshot, so the
                  register table and the GP-vendor auto-suggest have a seed. */}
              <TextField
                variant="standard"
                value={draft.label}
                onChange={(e) => onRenameDraft(draft.id, e.target.value)}
                placeholder="Vendor"
                slotProps={{ input: { sx: monoSx }, htmlInput: { 'aria-label': 'Vendor' } }}
                sx={{ minWidth: 0, width: 220, maxWidth: '100%' }}
              />
            </Box>
          }
        />
        <Box sx={{ textAlign: 'right', ml: 'auto' }}>
          <Typography sx={microLabelSx}>PO total</Typography>
          {/* Card's gauge value: the DESIGN ramp's title step (1.25rem), not subtitle1's off-ramp
              1rem. component="p" keeps it out of the heading outline. */}
          <Typography variant="h6" component="p" sx={{ ...tabularSx, fontWeight: 700 }}>
            ${poTotal.toFixed(2)}
          </Typography>
        </Box>
        <IconButton
          size="small"
          aria-label="Draft actions"
          onClick={(e) => setCardMenuAnchor(e.currentTarget)}
        >
          <MoreVertical size={18} strokeWidth={1.75} />
        </IconButton>
        <Menu anchorEl={cardMenuAnchor} open={cardMenuAnchor != null} onClose={() => setCardMenuAnchor(null)}>
          {otherDrafts.map((t) => (
            <MenuItem
              key={t.id}
              onClick={() => {
                onMergeDraft(draft.id, t.id);
                setCardMenuAnchor(null);
              }}
            >
              Merge into {t.label}
            </MenuItem>
          ))}
          {otherDrafts.length > 0 && <Divider />}
          <MenuItem
            disabled={!isEmpty}
            onClick={() => {
              onRemoveDraft(draft.id);
              setCardMenuAnchor(null);
            }}
          >
            {isEmpty ? 'Remove draft' : 'Remove (empty it first)'}
          </MenuItem>
        </Menu>
      </Box>

      {/* Delivery date + cost code + notes */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        <TextField
          label="Preferred delivery date"
          size="small"
          type="date"
          value={draft.info.preferredDeliveryDate}
          onChange={(e) => onUpdateDraftInfo(draft.id, 'preferredDeliveryDate', e.target.value)}
          sx={{ width: 190 }}
          slotProps={{ inputLabel: { shrink: true } }}
        />
        {costCodes.length > 0 && (
          <TextField
            select
            required
            // #627: required at PO-request creation now, not just at GP registration. The error shows
            // only on an included draft that holds lines and has no code yet - a draft that mints no PO
            // (not included, or empty) carries the required marker but no error.
            error={draft.included && !isEmpty && !draft.info.costCode}
            label="Cost code"
            size="small"
            value={draft.info.costCode}
            onChange={(e) => onUpdateDraftInfo(draft.id, 'costCode', e.target.value)}
            sx={{ width: 260, '& .MuiSelect-select': monoSx }}
            helperText={
              draft.included && !isEmpty && !draft.info.costCode ? 'Required for GP registration' : ' '
            }
          >
            <MenuItem value="">
              <em>None</em>
            </MenuItem>
            {costCodes.map((c) => (
              <MenuItem key={`${c.costCode}-${c.costElement}`} value={`${c.costCode}-${c.costElement}`}>
                {c.description ? `${c.costCode} · ${c.description}` : c.costCode}
              </MenuItem>
            ))}
          </TextField>
        )}
        <TextField
          label="Notes"
          size="small"
          multiline
          minRows={1}
          maxRows={3}
          value={draft.info.notes}
          onChange={(e) => onUpdateDraftInfo(draft.id, 'notes', e.target.value)}
          sx={{ flex: 1, minWidth: 200 }}
          placeholder="Optional notes for this PO"
        />
      </Box>

      {/* #588: documents the buyer already has, pre-attached here and uploaded onto the PO this draft
          creates. Only PO Document / Miscellaneous - the other types are produced downstream. */}
      <Box sx={{ mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, mb: attachments.length > 0 ? 1 : 0 }}>
          <Typography sx={microLabelSx}>Documents</Typography>
          {attachments.length === 0 && (
            <Typography variant="caption" color="text.secondary" noWrap sx={{ minWidth: 0, flex: 1 }}>
              Optional - the PO document or misc files, carried onto the created request
            </Typography>
          )}
          <Button
            size="small"
            variant="outlined"
            component="label"
            startIcon={<Paperclip size={15} strokeWidth={1.75} />}
            sx={{ ml: 'auto', flexShrink: 0 }}
          >
            Attach
            <input
              type="file"
              hidden
              multiple
              onChange={(e) => {
                const files = Array.from(e.target.files ?? []);
                if (files.length > 0) onAddAttachments(draft.id, files);
                // Clear so re-selecting the same file re-fires onChange.
                e.target.value = '';
              }}
            />
          </Button>
        </Box>
        {attachments.length > 0 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
            {attachments.map((a) => (
              <Box key={a.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
                <FileText size={16} strokeWidth={1.75} style={{ flexShrink: 0, opacity: 0.6 }} />
                <Typography variant="body2" noWrap title={a.file.name} sx={{ ...monoSx, flex: 1, minWidth: 0 }}>
                  {a.file.name}
                </Typography>
                <TextField
                  select
                  size="small"
                  value={a.documentType}
                  onChange={(e) => onSetAttachmentType(draft.id, a.id, e.target.value as DraftAttachmentType)}
                  slotProps={{ htmlInput: { 'aria-label': `Document type for ${a.file.name}` } }}
                  sx={{ width: 168, flexShrink: 0 }}
                >
                  <MenuItem value="PO_DOCUMENT">PO Document</MenuItem>
                  <MenuItem value="MISCELLANEOUS">Miscellaneous</MenuItem>
                </TextField>
                <IconButton
                  size="small"
                  aria-label={`Remove ${a.file.name}`}
                  onClick={() => onRemoveAttachment(draft.id, a.id)}
                  sx={{ flexShrink: 0 }}
                >
                  <X size={16} strokeWidth={1.75} />
                </IconButton>
              </Box>
            ))}
          </Box>
        )}
      </Box>

      <Typography sx={{ ...microLabelSx, mb: 1 }}>Line items ({lines.length})</Typography>

      {lines.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
          No lines. Move some in from another draft.
        </Typography>
      ) : (
        <Box
          sx={{
            display: 'grid',
            // #639: a size container, so the cqw type ramp above resolves against the card's width.
            containerType: 'inline-size',
            // The three text columns absorb the slack; every numeric track is content-sized, so the
            // 1-4 digit recon columns spend only the width their header needs.
            gridTemplateColumns:
              'minmax(0, 1.15fr) minmax(0, 1.25fr) minmax(0, 1.05fr) clamp(54px, 7cqw, 86px) clamp(76px, 9.5cqw, 116px) auto auto auto auto auto 36px',
            '& .po-head': {
              ...microLabelSx,
              fontSize: FS_HEAD,
              px: 1,
              py: 0.75,
              borderBottom: '2px solid',
              borderColor: 'text.primary',
            },
            '& .po-cell': {
              px: 1,
              py: 0.75,
              fontSize: FS_CELL,
              borderBottom: '1px solid',
              borderColor: 'divider',
              display: 'flex',
              alignItems: 'center',
              minWidth: 0,
            },
            '& .po-cell-right': { justifyContent: 'flex-end' },
            // Numeric tracks: nowrap keeps a header off a second line (the track sizes to it), and the
            // tighter padding keeps the digit columns compact.
            '& .po-num': { whiteSpace: 'nowrap', textAlign: 'right', px: 0.75 },
            '& .po-cell .MuiInputBase-root, & .po-cell .MuiInputBase-input': { fontSize: FS_CELL },
            '& .po-cell .MuiInputAdornment-root .MuiTypography-root': { fontSize: FS_CELL },
            '& .po-mono .MuiInputBase-input': { fontSize: FS_MONO },
            // #639: a hairline sets the read-only project-wide block apart from the order columns.
            '& .po-sep': { borderLeft: '1px solid', borderLeftColor: 'divider' },
          }}
        >
          <Box className="po-head">Order As</Box>
          <Box className="po-head">Scheduled Part Number</Box>
          <Box className="po-head">Hardware Category</Box>
          <Box className="po-head po-num">Qty</Box>
          <Box className="po-head po-num">Unit Cost</Box>
          <Box className="po-head po-num">Total Cost</Box>
          <Box className="po-head po-num po-sep" title="Needed by schedule">
            Need
          </Box>
          <Box className="po-head po-num" title="Already on order project-wide">
            On Order
          </Box>
          <Box className="po-head po-num" title="Received project-wide">
            Rcvd
          </Box>
          <Box className="po-head po-num" title="Available in inventory">
            Avail
          </Box>
          <Box className="po-head" />

          {lines.map((line) => {
            // #639: the recon numbers ride the row itself. Zeros are truthful on a fresh import, so an
            // absent entry falls back to 0 rather than blanking the column.
            const ctx = lineContextByPk.get(line.pk);
            return (
              <Box key={line.pk} sx={{ display: 'contents' }}>
                <Box className="po-cell po-mono">
                  <OrderAsAutocomplete
                    value={orderAsValues.get(line.pk) ?? ''}
                    onChange={(next) => onUpdateOrderAs(line.pk, next)}
                    options={priorMap.get(line.productCode) ?? []}
                    placeholder="Order as"
                  />
                </Box>
                <Box className="po-cell">
                  <Typography variant="body2" sx={{ ...monoSx, fontSize: FS_MONO }}>
                    {line.productCode}
                  </Typography>
                </Box>
                <Box className="po-cell">
                  <Typography variant="body2" sx={{ fontSize: FS_CELL }}>
                    {line.hardwareCategory}
                  </Typography>
                </Box>
                <Box className="po-cell po-cell-right po-num">
                  {/* #632: Qty is editable in place, ceilinged at the product's selection pool minus
                      what sibling drafts hold. Lowering proceeds with less; widening the scope stays
                      the selection steps' job. */}
                  <TextField
                    size="small"
                    type="number"
                    value={line.qty}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      if (!Number.isNaN(val)) onUpdateLineQty(draft.id, line.pk, val);
                    }}
                    slotProps={{
                      input: { sx: tabularSx },
                      htmlInput: {
                        min: 0,
                        max:
                          (selectionTotals.get(line.pk) ?? line.qty) -
                          ((heldByProduct.get(line.pk) ?? line.qty) - line.qty),
                        step: 1,
                        'aria-label': `Quantity of ${line.productCode}`,
                      },
                    }}
                    sx={{ width: '100%' }}
                  />
                </Box>
                <Box className="po-cell po-cell-right po-num">
                  <TextField
                    size="small"
                    type="number"
                    value={line.unitCost}
                    onChange={(e) => {
                      const val = parseFloat(e.target.value);
                      if (!Number.isNaN(val) && val >= 0) onUpdateUnitCost(line.pk, val);
                    }}
                    slotProps={{
                      input: {
                        startAdornment: <InputAdornment position="start">$</InputAdornment>,
                        sx: tabularSx,
                      },
                      htmlInput: { min: 0, step: 0.01 },
                    }}
                    sx={{ width: '100%' }}
                  />
                </Box>
                <Box className="po-cell po-cell-right po-num">
                  <Typography variant="body2" sx={{ ...tabularSx, fontSize: FS_CELL }}>
                    ${line.totalCost.toFixed(2)}
                  </Typography>
                </Box>
                <Box className="po-cell po-cell-right po-num po-sep">
                  <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, fontSize: FS_CELL }}>
                    {ctx?.needed ?? 0}
                  </Typography>
                </Box>
                <Box className="po-cell po-cell-right po-num">
                  <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, fontSize: FS_CELL }}>
                    {ctx?.onOrder ?? 0}
                  </Typography>
                </Box>
                <Box className="po-cell po-cell-right po-num">
                  <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, fontSize: FS_CELL }}>
                    {ctx?.received ?? 0}
                  </Typography>
                </Box>
                <Box className="po-cell po-cell-right po-num">
                  <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, fontSize: FS_CELL }}>
                    {ctx?.available ?? 0}
                  </Typography>
                </Box>
                <Box className="po-cell po-cell-right" sx={{ px: 0 }}>
                  <IconButton
                    size="small"
                    aria-label={`Line actions for ${line.productCode}`}
                    onClick={(e) => setRowMenu({ anchor: e.currentTarget, line })}
                  >
                    <MoreVertical size={16} strokeWidth={1.75} />
                  </IconButton>
                </Box>
              </Box>
            );
          })}
        </Box>
      )}

      <Menu anchorEl={rowMenu?.anchor ?? null} open={rowMenu != null} onClose={() => setRowMenu(null)}>
        {otherDrafts.map((t) => (
          <MenuItem
            key={t.id}
            onClick={() => {
              if (rowMenu) onMoveLine(draft.id, rowMenu.line.pk, rowMenu.line.qty, t.id);
              setRowMenu(null);
            }}
          >
            Move all to {t.label}
          </MenuItem>
        ))}
        {otherDrafts.length > 0 && (
          <MenuItem
            disabled={!rowMenu || rowMenu.line.qty < 2}
            onClick={() => {
              if (rowMenu) {
                onOpenSplit({
                  fromId: draft.id,
                  pk: rowMenu.line.pk,
                  productLabel: rowMenu.line.productCode,
                  maxQty: rowMenu.line.qty,
                });
              }
              setRowMenu(null);
            }}
          >
            Split…
          </MenuItem>
        )}
        {otherDrafts.length > 0 && <Divider />}
        {/* #632: drop the line outright - "not ordering this here". Not a move; the product's
            openings are just claimed by fewer drafts at finalize. */}
        <MenuItem
          onClick={() => {
            if (rowMenu) onRemoveLine(draft.id, rowMenu.line.pk);
            setRowMenu(null);
          }}
        >
          Remove line
        </MenuItem>
      </Menu>
    </Box>
  );
}
