import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  IconButton,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { ArrowLeft, ArrowRight, Plus, Split, X } from 'lucide-react';
import { type ClassificationRow } from './ClassificationGrid';
import {
  GROUP_BY_OPTIONS,
  formatGroupKey,
  distinctProductCodes,
  type GroupByField,
} from './classificationGrouping';
import { type ClassificationOption, isRowClassified } from './types';
import { monoSx, microLabelSx, tabularSx } from '../../theme';

// #568: which key answers each axis value. Numbers for the scope axis, letters for Site/Shop, so a
// two-axis (PO) card reads 1/2 then S/H and a one-axis (assembly) card reads S/H alone.
const KEY_FOR_VALUE: Record<string, string> = {
  BY_UCSH: '1',
  BY_OTHERS: '2',
  SITE_HARDWARE: 's',
  SHOP_HARDWARE: 'h',
};

interface GuidedClassificationProps {
  rows: ClassificationRow[];
  /** Primary axis: scope (By UCH / By Others) for PO, Site/Shop for a one-axis classification. */
  options: ClassificationOption[];
  onClassify: (keys: string[], value: string) => void;
  /** Present only for the two-axis (PO) case. */
  siteShopOptions?: ClassificationOption[];
  onClassifySiteShop?: (keys: string[], value: string) => void;
  siteShopExemptValue?: string;
  /** Group-by levels, owned by the step so the review grid can inherit the same grouping. */
  groupByFields: GroupByField[];
  onChangeGroupByFields: (fields: GroupByField[]) => void;
  /** Fired after the last group is answered - the step moves to review. */
  onComplete: () => void;
  onSkipToReview: () => void;
}

interface LeafGroup {
  key: string;
  label: string;
  rows: ClassificationRow[];
}

// One card per deepest-level group: rows sharing every group-by field value. The composite key is
// stable across classifications (it reads the grouping fields, not the answer), so the card list and
// the user's position hold while they classify.
function buildLeafGroups(rows: ClassificationRow[], fields: GroupByField[]): LeafGroup[] {
  const map = new Map<string, LeafGroup>();
  for (const row of rows) {
    const parts = fields.map((f) => formatGroupKey(f, row[f]));
    const key = parts.join(' › ');
    const existing = map.get(key);
    if (existing) existing.rows.push(row);
    else map.set(key, { key, label: key, rows: [row] });
  }
  return Array.from(map.values()).sort((a, b) => a.key.localeCompare(b.key));
}

interface Card {
  id: string;
  label: string;
  rows: ClassificationRow[];
  groupKey: string;
  isSplit: boolean;
}

function uniqueKeys(rows: ClassificationRow[]): string[] {
  return Array.from(new Set(rows.map((r) => r.classificationKey)));
}

function isTextTarget(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  return (el as HTMLElement).isContentEditable === true;
}

export default function GuidedClassification({
  rows,
  options,
  onClassify,
  siteShopOptions,
  onClassifySiteShop,
  siteShopExemptValue,
  groupByFields,
  onChangeGroupByFields,
  onComplete,
  onSkipToReview,
}: GuidedClassificationProps) {
  const hasSiteShop = !!siteShopOptions && !!onClassifySiteShop;
  const classifyOpts = useMemo(
    () => ({ hasSiteShop, siteShopExemptValue }),
    [hasSiteShop, siteShopExemptValue],
  );

  const [started, setStarted] = useState(false);
  const [index, setIndex] = useState(0);
  const [splitGroupKeys, setSplitGroupKeys] = useState<Set<string>>(new Set());

  const labelMap = useMemo(() => {
    const m: Record<string, { label: string; color: ClassificationOption['color'] }> = {};
    for (const o of [...options, ...(siteShopOptions ?? [])]) m[o.value] = { label: o.label, color: o.color };
    return m;
  }, [options, siteShopOptions]);

  const groups = useMemo(() => buildLeafGroups(rows, groupByFields), [rows, groupByFields]);

  const cards = useMemo<Card[]>(() => {
    const out: Card[] = [];
    for (const g of groups) {
      if (splitGroupKeys.has(g.key) && g.rows.length > 1) {
        for (const r of g.rows) {
          out.push({ id: `${g.key}::${r.id}`, label: g.label, rows: [r], groupKey: g.key, isSplit: true });
        }
      } else {
        out.push({ id: g.key, label: g.label, rows: g.rows, groupKey: g.key, isSplit: false });
      }
    }
    return out;
  }, [groups, splitGroupKeys]);

  const safeIndex = cards.length === 0 ? 0 : Math.min(index, cards.length - 1);
  const currentCard = cards[safeIndex];

  const completeCount = useMemo(
    () => rows.filter((r) => isRowClassified(r, classifyOpts)).length,
    [rows, classifyOpts],
  );

  const goPrev = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  const goNext = useCallback(() => {
    if (safeIndex + 1 >= cards.length) onComplete();
    else setIndex(safeIndex + 1);
  }, [safeIndex, cards.length, onComplete]);

  const splitCurrent = useCallback(() => {
    if (!currentCard || currentCard.isSplit || currentCard.rows.length <= 1) return;
    setSplitGroupKeys((prev) => new Set(prev).add(currentCard.groupKey));
  }, [currentCard]);

  // Whether every row on the card would be fully classified once `value` is applied to the given
  // axis - predicted synchronously so the advance rides the same event as the answer, without an
  // effect that would also fire on plain navigation.
  const classifyPrimary = useCallback(
    (value: string) => {
      if (!currentCard) return;
      onClassify(uniqueKeys(currentCard.rows), value);
      const completes = currentCard.rows.every((r) =>
        isRowClassified({ classification: value, siteShop: r.siteShop }, classifyOpts),
      );
      if (completes) goNext();
    },
    [currentCard, onClassify, classifyOpts, goNext],
  );

  const classifySiteShop = useCallback(
    (value: string) => {
      if (!currentCard || !onClassifySiteShop) return;
      // By-Others rows are out of scope and carry no Site/Shop; classify only the eligible ones.
      const eligible = currentCard.rows.filter(
        (r) => !siteShopExemptValue || r.classification !== siteShopExemptValue,
      );
      onClassifySiteShop(uniqueKeys(eligible), value);
      // Picking Site/Shop back-fills scope on the eligible rows, so the card is complete: eligible
      // rows carry both axes, exempt rows need none.
      const completes = currentCard.rows.every((r) => {
        if (siteShopExemptValue && r.classification === siteShopExemptValue) return true;
        return isRowClassified({ classification: r.classification || 'BY_UCSH', siteShop: value }, classifyOpts);
      });
      if (completes) goNext();
    },
    [currentCard, onClassifySiteShop, siteShopExemptValue, classifyOpts, goNext],
  );

  // Keybinds live only while the cards are on screen, and never fire while a text control is focused.
  useEffect(() => {
    if (!started) return;
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTextTarget(e.target as Element | null) || isTextTarget(document.activeElement)) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); goPrev(); return; }
      if (e.key === 'ArrowRight') { e.preventDefault(); goNext(); return; }
      const k = e.key.toLowerCase();
      if (k === 'x') { e.preventDefault(); splitCurrent(); return; }
      for (const opt of options) {
        if (KEY_FOR_VALUE[opt.value] === k) { e.preventDefault(); classifyPrimary(opt.value); return; }
      }
      for (const opt of siteShopOptions ?? []) {
        if (KEY_FOR_VALUE[opt.value] === k) { e.preventDefault(); classifySiteShop(opt.value); return; }
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [started, options, siteShopOptions, goPrev, goNext, splitCurrent, classifyPrimary, classifySiteShop]);

  // ---- Grouping prompt ----

  const usedFields = useMemo(() => new Set(groupByFields), [groupByFields]);

  const addLevel = useCallback(() => {
    const firstUnused = GROUP_BY_OPTIONS.find((o) => !usedFields.has(o.value));
    if (firstUnused) onChangeGroupByFields([...groupByFields, firstUnused.value]);
  }, [usedFields, groupByFields, onChangeGroupByFields]);

  const removeLevel = useCallback(
    (i: number) => onChangeGroupByFields(groupByFields.filter((_, idx) => idx !== i)),
    [groupByFields, onChangeGroupByFields],
  );

  const changeLevel = useCallback(
    (i: number, value: GroupByField) => onChangeGroupByFields(groupByFields.map((f, idx) => (idx === i ? value : f))),
    [groupByFields, onChangeGroupByFields],
  );

  const startClassifying = useCallback(() => {
    setSplitGroupKeys(new Set());
    setIndex(0);
    setStarted(true);
  }, []);

  const skipLink = (
    <Button variant="text" size="small" onClick={onSkipToReview}>
      Skip to review
    </Button>
  );

  if (!started) {
    return (
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Group the items so you can classify a whole set at once instead of item by item. Pick one or
          more fields to group by, then step through the groups.
        </Typography>

        <Box sx={{ mb: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          {groupByFields.map((field, i) => (
            <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography sx={{ ...microLabelSx, minWidth: 56 }}>Level {i + 1}</Typography>
              <TextField
                select
                size="small"
                value={field}
                onChange={(e) => changeLevel(i, e.target.value as GroupByField)}
                sx={{ minWidth: 200 }}
                inputProps={{ 'aria-label': `Group level ${i + 1}` }}
              >
                {GROUP_BY_OPTIONS.filter((opt) => opt.value === field || !usedFields.has(opt.value)).map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
                ))}
              </TextField>
              <IconButton
                size="small"
                aria-label={`Remove group level ${i + 1}`}
                onClick={() => removeLevel(i)}
                disabled={groupByFields.length <= 1}
              >
                <X size={16} strokeWidth={1.75} />
              </IconButton>
            </Box>
          ))}
          {groupByFields.length < GROUP_BY_OPTIONS.length && (
            <Button
              size="small"
              startIcon={<Plus size={18} strokeWidth={1.75} />}
              onClick={addLevel}
              sx={{ alignSelf: 'flex-start' }}
            >
              Add group level
            </Button>
          )}
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button variant="contained" onClick={startClassifying} disabled={groupByFields.length === 0}>
            Start classifying
          </Button>
          {skipLink}
        </Box>
      </Box>
    );
  }

  if (!currentCard) {
    // Nothing left to walk (everything already classified) - fall straight through to review.
    return (
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" color="success.main" sx={{ fontWeight: 600, mb: 1 }}>
          Everything is classified.
        </Typography>
        <Button variant="contained" onClick={onComplete}>Go to review</Button>
      </Box>
    );
  }

  const canSplit = !currentCard.isSplit && currentCard.rows.length > 1;
  const productCodes = distinctProductCodes(currentCard.rows);

  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', mb: 1 }}>
        <Typography sx={{ fontWeight: 700 }}>
          Group {safeIndex + 1} of {cards.length}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx }}>
          {completeCount} of {rows.length} classified
        </Typography>
        <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Button variant="text" size="small" onClick={() => setStarted(false)}>
            Change grouping
          </Button>
          {skipLink}
        </Box>
      </Box>

      <Paper variant="outlined" sx={{ p: 2, minWidth: 0 }}>
        <Typography sx={{ ...monoSx, fontWeight: 700, fontSize: '0.875rem', wordBreak: 'break-word' }}>
          {currentCard.label}
        </Typography>
        {productCodes.length > 0 && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ ...monoSx, fontSize: '0.6875rem', wordBreak: 'break-word' }}
          >
            {productCodes.join(', ')}
          </Typography>
        )}

        <Box sx={{ overflowX: 'auto', mt: 1.5 }}>
          <Table size="small" sx={{ '& td, & th': { px: 1 } }}>
            <TableHead>
              <TableRow>
                <TableCell sx={microLabelSx}>Opening</TableCell>
                <TableCell sx={microLabelSx}>Product Code</TableCell>
                <TableCell sx={microLabelSx}>Category</TableCell>
                <TableCell sx={microLabelSx} align="right">Qty</TableCell>
                <TableCell sx={microLabelSx}>Scope</TableCell>
                {hasSiteShop && <TableCell sx={microLabelSx}>Site/Shop</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {currentCard.rows.map((r) => {
                const exempt = !!siteShopExemptValue && r.classification === siteShopExemptValue;
                const scope = r.classification ? labelMap[r.classification] : undefined;
                const ss = r.siteShop ? labelMap[r.siteShop] : undefined;
                return (
                  <TableRow key={r.id}>
                    <TableCell sx={monoSx}>{r.openingNumber}</TableCell>
                    <TableCell sx={monoSx}>{r.productCode}</TableCell>
                    <TableCell>{r.hardwareCategory}</TableCell>
                    <TableCell align="right" sx={tabularSx}>{r.itemQuantity}</TableCell>
                    <TableCell>
                      {scope ? (
                        <Chip size="small" label={scope.label} color={scope.color} />
                      ) : (
                        <Chip size="small" label="—" />
                      )}
                    </TableCell>
                    {hasSiteShop && (
                      <TableCell>
                        {exempt ? (
                          <Chip size="small" label="—" />
                        ) : ss ? (
                          <Chip size="small" label={ss.label} color={ss.color} />
                        ) : (
                          <Chip size="small" label="—" />
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Box>

        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 2 }}>
          {options.map((opt) => (
            <Button
              key={opt.value}
              size="small"
              variant="contained"
              color={opt.color}
              onClick={() => classifyPrimary(opt.value)}
            >
              {opt.label} ({KEY_FOR_VALUE[opt.value] ?? '·'})
            </Button>
          ))}
          {siteShopOptions?.map((opt) => (
            <Button
              key={opt.value}
              size="small"
              variant="outlined"
              color={opt.color}
              onClick={() => classifySiteShop(opt.value)}
            >
              {opt.label} ({(KEY_FOR_VALUE[opt.value] ?? '·').toUpperCase()})
            </Button>
          ))}
          {canSplit && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<Split size={16} strokeWidth={1.75} />}
              onClick={splitCurrent}
            >
              Split (X)
            </Button>
          )}
        </Box>
      </Paper>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1.5 }}>
        <Button
          size="small"
          variant="outlined"
          startIcon={<ArrowLeft size={16} strokeWidth={1.75} />}
          onClick={goPrev}
          disabled={safeIndex === 0}
        >
          Prev
        </Button>
        <Button
          size="small"
          variant="outlined"
          endIcon={<ArrowRight size={16} strokeWidth={1.75} />}
          onClick={goNext}
        >
          Next
        </Button>
        <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
          Keys: classify with the letter/number shown, ← → move between groups, X splits a mixed group.
        </Typography>
      </Box>
    </Box>
  );
}
