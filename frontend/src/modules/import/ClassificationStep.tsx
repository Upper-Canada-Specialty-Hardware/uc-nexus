import { useMemo, useState } from 'react';
import { Alert, Box, Typography } from '@mui/material';
import { tabularSx } from '../../theme';
import ClassificationGrid, { type ClassificationRow, type GroupByField } from './ClassificationGrid';
import GuidedClassification from './GuidedClassification';
import { SCOPE_OPTIONS, ASSEMBLY_OPTIONS, isRowClassified } from './types';
import type { ImportPurpose } from './types';

interface ClassificationStepProps {
  classificationRows: ClassificationRow[];
  onClassify: (keys: string[], value: string) => void;
  // Issue #216: PO-purpose second axis - the PM sets Site/Shop here, not the PO user at register time.
  onClassifySiteShop: (keys: string[], value: string) => void;
  purpose: ImportPurpose;
  itemCount: number;
  openingCount: number;
  isReimport: boolean;
}

// #568: the step is a two-phase screen. The guided flow walks the unclassified items group by group;
// the existing grid stays on as the review/correction screen you land on afterwards (or straight
// away, when nothing is unclassified).
type Phase = 'guided' | 'review';

export default function ClassificationStep({
  classificationRows,
  onClassify,
  onClassifySiteShop,
  purpose,
  itemCount,
  openingCount,
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

  const classifiedCount = classificationRows.filter((r) => r.classification !== '').length;
  const allClassified = classifiedCount === classificationRows.length;

  // Issue #216: for PO purpose, every in-scope (non-By-Others) item also needs a Site/Shop pick.
  // The Next gate this drives is lifted into ImportWizard (#566); here these counts feed the readouts.
  const inScopeRows = useMemo(
    () => (purpose === 'po' ? classificationRows.filter((r) => r.classification !== 'BY_OTHERS') : []),
    [purpose, classificationRows],
  );
  const siteShopCount = inScopeRows.filter((r) => (r.siteShop ?? '') !== '').length;
  const allSiteShopClassified = siteShopCount === inScopeRows.length;

  // Grouping is owned here so the review grid opens on whatever grouping the guided flow used. Default
  // manufacturer - the user's ask: group by maker so a whole vendor's parts get one answer.
  const [groupByFields, setGroupByFields] = useState<GroupByField[]>(['vendorNo']);

  // Open guided when there is anything to guide and the step is editable; otherwise land on review.
  const [phase, setPhase] = useState<Phase>(() => {
    if (isReadOnly) return 'review';
    return classificationRows.some((r) => !isRowClassified(r, classifyOpts)) ? 'guided' : 'review';
  });

  const missingCount = classificationRows.filter((r) => !isRowClassified(r, classifyOpts)).length;

  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Classification
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, mb: 1 }}>
        {isReimport
          ? `${itemCount} lines need ordering (not available or partial in inventory).`
          : // "Lines", not "hardware items": these rows are aggregated by classification key, so 52
            // of them can carry 70 pieces. Finalize counts the pieces, and calling both "hardware
            // items" made two true numbers look like one of them was wrong.
            `${itemCount} hardware lines across ${openingCount} openings.`}
      </Typography>

      {isReadOnly ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          Shipping-only import: classifications shown for reference only.
        </Alert>
      ) : (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {purpose === 'po'
              ? 'Classify each item as By UCH (in scope) or By Others (excluded from scope), and each in-scope item as Site or Shop hardware. Picking Site or Shop marks an unclassified item By UCH for you.'
              : 'Classify each item group as Site Hardware or Shop Hardware.'}
          </Typography>
          <Typography
            variant="body2"
            sx={{ ...tabularSx, fontWeight: 600, mb: purpose === 'po' ? 0.5 : 2 }}
            color={allClassified ? 'success.main' : 'text.secondary'}
          >
            {classifiedCount} of {classificationRows.length} items classified
          </Typography>
          {purpose === 'po' && (
            <Typography
              variant="body2"
              sx={{ ...tabularSx, fontWeight: 600, mb: 2 }}
              color={allSiteShopClassified ? 'success.main' : 'text.secondary'}
            >
              {siteShopCount} of {inScopeRows.length} in-scope items site/shop classified
            </Typography>
          )}
        </>
      )}

      {!isReadOnly && phase === 'guided' ? (
        <GuidedClassification
          rows={classificationRows}
          options={options}
          onClassify={onClassify}
          siteShopOptions={siteShopOptions}
          onClassifySiteShop={hasSiteShop ? onClassifySiteShop : undefined}
          siteShopExemptValue={siteShopExemptValue}
          groupByFields={groupByFields}
          onChangeGroupByFields={setGroupByFields}
          onComplete={() => setPhase('review')}
          onSkipToReview={() => setPhase('review')}
        />
      ) : (
        <>
          {!isReadOnly && (
            <Typography
              variant="body2"
              sx={{ mb: 1.5, fontWeight: 600 }}
              color={missingCount === 0 ? 'success.main' : 'text.secondary'}
            >
              {missingCount === 0
                ? `Review: all ${classificationRows.length} classified.`
                : `Review: ${classifiedCount} classified, ${missingCount} still missing a classification.`}
            </Typography>
          )}
          <ClassificationGrid
            rows={classificationRows}
            options={options}
            onClassify={onClassify}
            readOnly={isReadOnly}
            siteShopOptions={siteShopOptions}
            onClassifySiteShop={hasSiteShop ? onClassifySiteShop : undefined}
            siteShopExemptValue={siteShopExemptValue}
            initialGroupByFields={groupByFields}
          />
        </>
      )}
    </Box>
  );
}
