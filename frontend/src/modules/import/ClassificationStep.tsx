import { useCallback, useMemo, useState } from 'react';
import { Alert, AlertTitle, Box, Typography } from '@mui/material';
import { tabularSx } from '../../theme';
import type { GroupByField } from './classificationGrouping';
import ClassificationReview from './ClassificationReview';
import GuidedClassification from './GuidedClassification';
import { ASSEMBLY_OPTIONS, PO_OPTIONS, isRowClassified, poChoiceOf, splitPoChoice } from './types';
import type { ClassificationRow, ImportPurpose } from './types';

interface ClassificationStepProps {
  classificationRows: ClassificationRow[];
  onClassify: (keys: string[], value: string) => void;
  // Issue #216: PO-purpose second axis - the PM sets Site/Shop here, not the PO user at register time.
  onClassifySiteShop: (keys: string[], value: string) => void;
  purpose: ImportPurpose;
  itemCount: number;
  isReimport: boolean;
}

// #568/#586: a two-phase step. The guided flow walks the unclassified items group by group; the
// review screen reads the classifications back for confirmation and deliberate correction. Land on
// guided when there is anything to guide, on review otherwise.
type Phase = 'guided' | 'review';

export default function ClassificationStep({
  classificationRows,
  onClassify,
  onClassifySiteShop,
  purpose,
  itemCount,
  isReimport,
}: ClassificationStepProps) {
  // #734: the PO import stores two axes (scope, then Site/Shop) but asks them as one pick - UCH Shop,
  // UCH Site or By Others. The guided card and the review see one axis: each row's two stored answers
  // folded into one value, and a pick split back into the two before it reaches the wizard.
  // Assembly and schedule (#608) carry the single Site/Shop axis as it is.
  const isPo = purpose === 'po';
  const options = isPo ? PO_OPTIONS : ASSEMBLY_OPTIONS;
  const rows = useMemo(
    () => (isPo ? classificationRows.map((r) => ({ ...r, classification: poChoiceOf(r) })) : classificationRows),
    [isPo, classificationRows],
  );
  const classify = useCallback(
    (keys: string[], value: string) => {
      if (!isPo) {
        onClassify(keys, value);
        return;
      }
      const { scope, siteShop } = splitPoChoice(value);
      onClassify(keys, scope);
      if (siteShop) onClassifySiteShop(keys, siteShop);
    },
    [isPo, onClassify, onClassifySiteShop],
  );

  // Count the openings the lines actually belong to, not the selection set - hardware-mode imports
  // pick products directly and carry no selected openings, which read as "across 0 openings".
  const openingCount = useMemo(
    () => new Set(classificationRows.map((r) => r.openingNumber)).size,
    [classificationRows],
  );

  // Grouping is owned here so the review screen opens on whatever grouping the guided flow used.
  // Default manufacturer - the user's ask: group by maker so a whole vendor's parts get one answer.
  const [groupByFields, setGroupByFields] = useState<GroupByField[]>(['vendorNo']);

  const [phase, setPhase] = useState<Phase>(() =>
    rows.some((r) => !isRowClassified(r)) ? 'guided' : 'review',
  );
  // #586: whether review was reached by finishing the guided walk-through (vs. landing straight on it
  // when nothing needed guiding). Drives the one-time hand-off confirmation so the two phases read as
  // one flow. Cleared on any hop back into guided.
  const [completedGuided, setCompletedGuided] = useState(false);

  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="h6" sx={{ mb: 0.5 }}>
        Classification
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, mb: 2 }}>
        {isReimport
          ? `${itemCount} lines need ordering (not available or partial in inventory).`
          : // "Lines", not "hardware items": these rows are aggregated by classification key, so 52
            // of them can carry 70 pieces. Finalize counts the pieces, and calling both "hardware
            // items" made two true numbers look like one of them was wrong.
            `${itemCount} hardware lines across ${openingCount} ${openingCount === 1 ? 'opening' : 'openings'}.`}
      </Typography>

      {/* #734: the directors' rule, on every purpose and in both phases. Shop is the safe default: shop
          hardware can still ship out directly, site hardware can never be pulled into shop. */}
      <Alert severity="warning" sx={{ mb: 2, '& .MuiAlert-message': { minWidth: 0 } }}>
        <AlertTitle sx={{ fontWeight: 700, fontSize: '1rem', mb: 0.25 }}>
          If unsure of UCH classification, assign Shop.
        </AlertTitle>
        <Typography variant="body2">
          Shop hardware can still be shipped out directly, but site hardware can&apos;t be pulled into shop.
        </Typography>
      </Alert>

      {phase === 'guided' ? (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            {isPo
              ? 'Classify each item group as UCH Shop, UCH Site or By Others (excluded from scope).'
              : 'Classify each item group as Shop Hardware or Site Hardware.'}
          </Typography>
          <GuidedClassification
            rows={rows}
            options={options}
            onClassify={classify}
            groupByFields={groupByFields}
            onChangeGroupByFields={setGroupByFields}
            onComplete={() => {
              setCompletedGuided(true);
              setPhase('review');
            }}
            onSkipToReview={() => {
              setCompletedGuided(false);
              setPhase('review');
            }}
          />
        </>
      ) : (
        <ClassificationReview
          rows={rows}
          options={options}
          onClassify={classify}
          readOnly={false}
          groupByFields={groupByFields}
          justCompletedGuided={completedGuided}
          onBackToGuided={() => {
            setCompletedGuided(false);
            setPhase('guided');
          }}
        />
      )}
    </Box>
  );
}
