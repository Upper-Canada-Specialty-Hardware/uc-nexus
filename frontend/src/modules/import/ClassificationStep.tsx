import { useMemo, useState } from 'react';
import { Alert, Box, Typography } from '@mui/material';
import { tabularSx } from '../../theme';
import type { GroupByField } from './classificationGrouping';
import ClassificationReview from './ClassificationReview';
import GuidedClassification from './GuidedClassification';
import { SCOPE_OPTIONS, ASSEMBLY_OPTIONS, isRowClassified } from './types';
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
  const isReadOnly = purpose !== 'po' && purpose !== 'assembly';

  const options = purpose === 'po' ? SCOPE_OPTIONS : ASSEMBLY_OPTIONS;
  // The two-axis (PO) case carries a Site/Shop second axis; a one-axis (assembly) case does not.
  const hasSiteShop = purpose === 'po';
  const siteShopOptions = hasSiteShop ? ASSEMBLY_OPTIONS : undefined;
  const siteShopExemptValue = hasSiteShop ? 'BY_OTHERS' : undefined;
  const classifyOpts = useMemo(
    () => ({ hasSiteShop, siteShopExemptValue }),
    [hasSiteShop, siteShopExemptValue],
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

  const [phase, setPhase] = useState<Phase>(() => {
    if (isReadOnly) return 'review';
    return classificationRows.some((r) => !isRowClassified(r, classifyOpts)) ? 'guided' : 'review';
  });
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

      {isReadOnly && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Shipping-only import: classifications shown for reference only.
        </Alert>
      )}

      {!isReadOnly && phase === 'guided' ? (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            {purpose === 'po'
              ? 'Classify each item as By UCH (in scope) or By Others (excluded from scope), and each in-scope item as Site or Shop hardware. Picking Site or Shop marks an unclassified item By UCH for you.'
              : 'Classify each item group as Site Hardware or Shop Hardware.'}
          </Typography>
          <GuidedClassification
            rows={classificationRows}
            options={options}
            onClassify={onClassify}
            siteShopOptions={siteShopOptions}
            onClassifySiteShop={hasSiteShop ? onClassifySiteShop : undefined}
            siteShopExemptValue={siteShopExemptValue}
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
          rows={classificationRows}
          options={options}
          onClassify={onClassify}
          readOnly={isReadOnly}
          siteShopOptions={siteShopOptions}
          onClassifySiteShop={hasSiteShop ? onClassifySiteShop : undefined}
          siteShopExemptValue={siteShopExemptValue}
          groupByFields={groupByFields}
          justCompletedGuided={completedGuided}
          onBackToGuided={
            isReadOnly
              ? undefined
              : () => {
                  setCompletedGuided(false);
                  setPhase('guided');
                }
          }
        />
      )}
    </Box>
  );
}
