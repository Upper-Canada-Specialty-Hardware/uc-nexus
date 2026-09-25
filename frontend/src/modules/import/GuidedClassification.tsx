import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  IconButton,
  MenuItem,
  Paper,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { ArrowLeft, ArrowRight, Merge, Plus, Split, X } from 'lucide-react';
import {
  GROUP_BY_OPTIONS,
  distinctProductCodes,
  groupRowsByFields,
  type GroupByField,
} from './classificationGrouping';
import { type ClassificationOption, type ClassificationRow, isRowClassified } from './types';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import ClassificationRowsGrid from './ClassificationRowsGrid';

// #734: each option answers to its position on the row - 1, 2, 3 - so a PO card reads UCH Shop (1),
// UCH Site (2), By Others (3) and a Site/Shop card reads Shop (1), Site (2). Split stays on X.
const keyForIndex = (i: number) => String(i + 1);

interface GuidedClassificationProps {
  rows: ClassificationRow[];
  /** The row of answers: UCH Shop / UCH Site / By Others for PO, Shop / Site otherwise (#734). */
  options: ClassificationOption[];
  onClassify: (keys: string[], value: string) => void;
  /** Group-by levels, owned by the step so the review grid can inherit the same grouping. */
  groupByFields: GroupByField[];
  onChangeGroupByFields: (fields: GroupByField[]) => void;
  /** Fired after the last group is answered - the step moves to review. */
  onComplete: () => void;
  onSkipToReview: () => void;
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
  groupByFields,
  onChangeGroupByFields,
  onComplete,
  onSkipToReview,
}: GuidedClassificationProps) {
  const [started, setStarted] = useState(false);
  const [index, setIndex] = useState(0);
  const [splitGroupKeys, setSplitGroupKeys] = useState<Set<string>>(new Set());

  const labelMap = useMemo(() => {
    const m: Record<string, { label: string; color: ClassificationOption['color'] }> = {};
    for (const o of options) m[o.value] = { label: o.label, color: o.color };
    return m;
  }, [options]);

  // #733: the card's rows are read-only here - the answer comes from the buttons in the sticky header -
  // so each row shows its resolved classification as a chip.
  const chipColumns = useMemo<GridColDef<ClassificationRow>[]>(() => {
    const chip = (value: string | undefined) => {
      const picked = value ? labelMap[value] : undefined;
      return picked ? <Chip size="small" label={picked.label} color={picked.color} /> : <Chip size="small" label="—" />;
    };
    return [
      {
        field: 'classification',
        headerName: 'Classification',
        width: 130,
        renderCell: ({ row }) => chip(row.classification),
      },
    ];
  }, [labelMap]);

  const groups = useMemo(() => groupRowsByFields(rows, groupByFields), [rows, groupByFields]);

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

  const completeCount = useMemo(() => rows.filter((r) => isRowClassified(r)).length, [rows]);

  const goPrev = useCallback(() => {
    setIndex((i) => Math.max(0, i - 1));
  }, []);

  const goNext = useCallback(() => {
    if (safeIndex + 1 >= cards.length) onComplete();
    else setIndex(safeIndex + 1);
  }, [safeIndex, cards.length, onComplete]);

  const splitCurrent = useCallback(() => {
    if (!currentCard || currentCard.isSplit || currentCard.rows.length <= 1) return;
    setSplitGroupKeys((prev) => new Set(prev).add(currentCard.groupKey));
  }, [currentCard]);

  // #632: undo a split - drop the groupKey and the per-line cards recombine into one. Lands on the
  // recombined card by replaying the card-order arithmetic the cards memo will run with the new set.
  const unsplitCurrent = useCallback(() => {
    if (!currentCard || !currentCard.isSplit) return;
    const gk = currentCard.groupKey;
    const next = new Set(splitGroupKeys);
    next.delete(gk);
    setSplitGroupKeys(next);
    let idx = 0;
    for (const g of groups) {
      if (g.key === gk) break;
      idx += next.has(g.key) && g.rows.length > 1 ? g.rows.length : 1;
    }
    setIndex(idx);
  }, [currentCard, splitGroupKeys, groups]);

  // #734: one pick answers the card outright (PO's two stored axes ride together), so every answer
  // advances on the same event.
  const classify = useCallback(
    (value: string) => {
      if (!currentCard) return;
      onClassify(uniqueKeys(currentCard.rows), value);
      goNext();
    },
    [currentCard, onClassify, goNext],
  );

  // Keybinds live only while the cards are on screen, and never fire while a text control is focused.
  useEffect(() => {
    if (!started) return;
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTextTarget(e.target as Element | null) || isTextTarget(document.activeElement)) return;
      // #733: once a cell of the row grid has focus, the arrows move through the grid, not the cards.
      if (e.key.startsWith('Arrow') && (e.target as Element | null)?.closest?.('.MuiDataGrid-root')) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); goPrev(); return; }
      if (e.key === 'ArrowRight') { e.preventDefault(); goNext(); return; }
      const k = e.key.toLowerCase();
      // X toggles: splits a mixed group, recombines a card that came from a split (#632).
      if (k === 'x') {
        e.preventDefault();
        if (currentCard?.isSplit) unsplitCurrent();
        else splitCurrent();
        return;
      }
      const picked = options.find((_, i) => keyForIndex(i) === k);
      if (picked) { e.preventDefault(); classify(picked.value); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [started, options, goPrev, goNext, splitCurrent, unsplitCurrent, currentCard, classify]);

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
        {/* #584: the group identity and the classify actions ride a sticky header pinned to the top of
            the card, so a long group never buries the buttons below the fold - the user classifies off
            the first rows without scrolling to the bottom. The row table below scrolls under this bar.
            Pulled out to the card edges (negative margins) so the bar background and its divider span
            the full width and nothing shows above the bar once it pins. */}
        <Box
          sx={{
            position: 'sticky',
            top: 0,
            zIndex: 2,
            bgcolor: 'background.paper',
            mx: -2,
            mt: -2,
            px: 2,
            pt: 2,
            pb: 1.5,
            borderBottom: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography sx={{ ...monoSx, fontWeight: 700, fontSize: '0.875rem', wordBreak: 'break-word' }}>
                {currentCard.label}
              </Typography>
              {productCodes.length > 0 && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ ...monoSx, display: 'block', fontSize: '0.6875rem', wordBreak: 'break-word' }}
                >
                  {productCodes.join(', ')}
                </Typography>
              )}
            </Box>
          </Box>

          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 1.5 }}>
            {options.map((opt, i) => (
              <Button
                key={opt.value}
                size="small"
                variant="contained"
                color={opt.color}
                onClick={() => classify(opt.value)}
              >
                {opt.label} ({keyForIndex(i)})
              </Button>
            ))}
            {canSplit && (
              <Tooltip
                // Without describeChild MUI hands the tooltip prose to aria-label, and the button's
                // visible name stops being its accessible name.
                describeChild
                title="Give each line of this mixed group its own classification card, so lines that need different answers are asked one at a time."
              >
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<Split size={16} strokeWidth={1.75} />}
                  onClick={splitCurrent}
                >
                  Split (X)
                </Button>
              </Tooltip>
            )}
            {currentCard.isSplit && (
              <Tooltip describeChild title="Recombine this group's per-line cards back into one card.">
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<Merge size={16} strokeWidth={1.75} />}
                  onClick={unsplitCurrent}
                >
                  Unsplit (X)
                </Button>
              </Tooltip>
            )}
          </Box>
        </Box>

        <Box sx={{ mt: 1.5, minWidth: 0 }}>
          <ClassificationRowsGrid rows={currentCard.rows} classificationColumns={chipColumns} />
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
          Keys: classify with the number shown, ← → move between groups, X splits a mixed group
          (or recombines a split one).
        </Typography>
      </Box>
    </Box>
  );
}
