import { useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { Check, ChevronDown, Pencil, TriangleAlert } from 'lucide-react';
import { distinctProductCodes, groupRowsByFields, type GroupByField } from './classificationGrouping';
import { type ClassificationOption, type ClassificationRow, isRowClassified } from './types';
import { monoSx, microLabelSx, tabularSx } from '../../theme';

// #586: the review screen. The guided card flow is where classifications are made; this is where the
// user reads back everything they decided and corrects only what's wrong. It leads with a summary
// rollup and shows each group's resolved classification as a static chip - correcting is a deliberate
// act (open a group to reveal its toggles), not the default posture. That is the whole point of the
// redesign: the step should feel like review, not a second pass of classification.

type ChipColor = ClassificationOption['color'] | 'default';

interface ClassificationReviewProps {
  rows: ClassificationRow[];
  options: ClassificationOption[];
  onClassify: (classificationKeys: string[], value: string) => void;
  readOnly?: boolean;
  // Issue #216: optional second axis (Site/Shop). Rows whose primary classification equals
  // siteShopExemptValue (By Others) are out of scope and carry none.
  siteShopOptions?: ClassificationOption[];
  onClassifySiteShop?: (classificationKeys: string[], value: string) => void;
  siteShopExemptValue?: string;
  // The grouping the guided flow used, so review reads back the same sets the user answered.
  groupByFields: GroupByField[];
  // #586: shown once, on the hand-off from a finished guided walk-through, so guided -> review reads
  // as one flow rather than a jarring re-render into a fresh-looking screen.
  justCompletedGuided?: boolean;
  // A way back into the guided card flow, so the two phases connect in both directions.
  onBackToGuided?: () => void;
}

// A slice of the rollup bar: one classification value's share of the rows on an axis.
interface Segment {
  key: string;
  label: string;
  count: number;
  color: ChipColor | 'muted';
}

// sx background for a bar segment / legend dot. 'muted' is the not-yet-answered share.
const SEGMENT_BG: Record<ChipColor | 'muted', string> = {
  success: 'success.main',
  info: 'info.main',
  warning: 'warning.main',
  default: 'text.disabled',
  muted: 'text.disabled',
};

function uniqueKeys(rows: ClassificationRow[]): string[] {
  return Array.from(new Set(rows.map((r) => r.classificationKey)));
}

function buildOptionLookups(options: ClassificationOption[]) {
  const label: Record<string, string> = {};
  const color: Record<string, ChipColor> = {};
  for (const o of options) {
    label[o.value] = o.label;
    color[o.value] = o.color;
  }
  return { label, color };
}

// A proportional stacked bar + legend for one classification axis. The bar shows every share side by
// side so "mostly By UCH, a little By Others" is a glance, not a count you have to add up.
function AxisRollup({ title, segments, total }: { title: string; segments: Segment[]; total: number }) {
  const shown = segments.filter((s) => s.count > 0);
  if (shown.length === 0) return null;
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography sx={microLabelSx}>{title}</Typography>
      <Box
        sx={{
          display: 'flex',
          height: 8,
          mt: 0.75,
          borderRadius: '3px',
          overflow: 'hidden',
          bgcolor: 'action.hover',
        }}
      >
        {shown.map((s) => (
          <Box
            key={s.key}
            title={`${s.label}: ${s.count}`}
            sx={{ width: `${(s.count / total) * 100}%`, minWidth: 3, bgcolor: SEGMENT_BG[s.color] }}
          />
        ))}
      </Box>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, mt: 1 }}>
        {shown.map((s) => (
          <Box key={s.key} sx={{ display: 'flex', alignItems: 'center', gap: 0.625 }}>
            <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: SEGMENT_BG[s.color], flexShrink: 0 }} />
            <Typography variant="body2" color={s.color === 'muted' ? 'text.secondary' : 'text.primary'}>
              <Box component="span" sx={{ ...tabularSx, fontWeight: 700 }}>
                {s.count}
              </Box>{' '}
              {s.label}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

export default function ClassificationReview({
  rows,
  options,
  onClassify,
  readOnly,
  siteShopOptions,
  onClassifySiteShop,
  siteShopExemptValue,
  groupByFields,
  justCompletedGuided,
  onBackToGuided,
}: ClassificationReviewProps) {
  const hasSiteShop = !!siteShopOptions && !!onClassifySiteShop;
  const classifyOpts = useMemo(() => ({ hasSiteShop, siteShopExemptValue }), [hasSiteShop, siteShopExemptValue]);
  const scopeLookup = useMemo(() => buildOptionLookups(options), [options]);
  const ssLookup = useMemo(() => buildOptionLookups(siteShopOptions ?? []), [siteShopOptions]);

  const classifiedCount = useMemo(() => rows.filter((r) => isRowClassified(r, classifyOpts)).length, [rows, classifyOpts]);
  const allClassified = classifiedCount === rows.length;
  const missingCount = rows.length - classifiedCount;

  // Primary axis rollup: one segment per option value, plus a muted "unclassified" tail.
  const primarySegments = useMemo<Segment[]>(() => {
    const segs = options.map((o) => ({
      key: o.value,
      label: o.label,
      count: rows.filter((r) => r.classification === o.value).length,
      color: o.color as ChipColor | 'muted',
    }));
    const unclassified = rows.filter((r) => r.classification === '').length;
    if (unclassified > 0) segs.push({ key: '__none', label: 'Unclassified', count: unclassified, color: 'muted' });
    return segs;
  }, [rows, options]);

  // Second axis rollup, over in-scope rows only (a By Others row carries no Site/Shop).
  const inScopeRows = useMemo(
    () => (hasSiteShop ? rows.filter((r) => r.classification !== '' && r.classification !== siteShopExemptValue) : []),
    [rows, hasSiteShop, siteShopExemptValue],
  );
  const siteShopSegments = useMemo<Segment[]>(() => {
    if (!hasSiteShop || !siteShopOptions) return [];
    const segs = siteShopOptions.map((o) => ({
      key: o.value,
      label: o.label,
      count: inScopeRows.filter((r) => r.siteShop === o.value).length,
      color: o.color as ChipColor | 'muted',
    }));
    const missing = inScopeRows.filter((r) => (r.siteShop ?? '') === '').length;
    if (missing > 0) segs.push({ key: '__none', label: 'Not set', count: missing, color: 'muted' });
    return segs;
  }, [hasSiteShop, siteShopOptions, inScopeRows]);

  const groups = useMemo(() => groupRowsByFields(rows, groupByFields), [rows, groupByFields]);

  // Groups that still need an answer open on arrival, so review lands on exactly what's unresolved;
  // fully-classified groups stay collapsed to their one-line summary. Correcting a settled group is a
  // deliberate expand, never the default.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(groups.filter((g) => g.rows.some((r) => !isRowClassified(r, classifyOpts))).map((g) => g.key)),
  );
  const toggleExpanded = (key: string, open: boolean) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });

  const [handoffDismissed, setHandoffDismissed] = useState(false);

  const renderToggle = (
    value: string,
    toggleOptions: ClassificationOption[],
    onChange: (value: string) => void,
  ) => (
    <ToggleButtonGroup
      size="small"
      exclusive
      value={value || null}
      onChange={(_, next) => {
        if (next !== null) onChange(next);
      }}
      sx={{ height: 28 }}
    >
      {toggleOptions.map((opt) => (
        <ToggleButton
          key={opt.value}
          value={opt.value}
          sx={{
            px: 1,
            fontSize: '0.75rem',
            '&.Mui-selected': {
              backgroundColor: `${opt.color}.main`,
              color: `${opt.color}.contrastText`,
              '&:hover': { backgroundColor: `${opt.color}.dark` },
            },
          }}
        >
          {opt.label}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );

  return (
    <Box sx={{ minWidth: 0 }}>
      {justCompletedGuided && !handoffDismissed && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setHandoffDismissed(true)}>
          That's everything classified. Read it back below and change anything that's off before you continue.
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 2, mb: 2, minWidth: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 2 }}>
          {allClassified ? (
            <Check size={18} strokeWidth={2.25} color="var(--mui-palette-success-main)" />
          ) : (
            <TriangleAlert size={18} strokeWidth={2} color="var(--mui-palette-warning-main)" />
          )}
          <Typography sx={{ fontWeight: 700, ...tabularSx }} color={allClassified ? 'success.main' : 'text.primary'}>
            {allClassified
              ? `All ${rows.length} classified`
              : `${classifiedCount} of ${rows.length} classified · ${missingCount} still need${missingCount === 1 ? 's' : ''} a classification`}
          </Typography>
          {!readOnly && onBackToGuided && (
            <Button variant="text" size="small" sx={{ ml: 'auto' }} onClick={onBackToGuided}>
              Classify by group
            </Button>
          )}
        </Box>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, minWidth: 0 }}>
          <Box sx={{ flex: '1 1 240px', minWidth: 0 }}>
            <AxisRollup
              title={hasSiteShop ? 'Scope' : 'Classification'}
              segments={primarySegments}
              total={rows.length}
            />
          </Box>
          {hasSiteShop && inScopeRows.length > 0 && (
            <Box sx={{ flex: '1 1 240px', minWidth: 0 }}>
              <AxisRollup title="Site / Shop" segments={siteShopSegments} total={inScopeRows.length} />
            </Box>
          )}
        </Box>
      </Paper>

      {!readOnly && !allClassified && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          The groups still missing an answer are open below.
        </Typography>
      )}

      <Box sx={{ minWidth: 0 }}>
        {groups.map((g) => {
          const groupRows = g.rows;
          const incompleteCount = groupRows.filter((r) => !isRowClassified(r, classifyOpts)).length;
          const scopeValues = new Set(groupRows.map((r) => r.classification).filter(Boolean));
          const uniformScope = scopeValues.size === 1 ? [...scopeValues][0] : null;
          const groupAllExempt = uniformScope != null && uniformScope === siteShopExemptValue;

          const ssEligible = groupRows.filter((r) => !siteShopExemptValue || r.classification !== siteShopExemptValue);
          const ssValues = new Set(ssEligible.map((r) => r.siteShop).filter(Boolean));
          const uniformSs = ssValues.size === 1 ? [...ssValues][0] : null;

          const productCodes = groupByFields.includes('productCode') ? [] : distinctProductCodes(groupRows);
          const isOpen = expanded.has(g.key);

          return (
            <Accordion
              key={g.key}
              expanded={isOpen}
              onChange={(_, open) => toggleExpanded(g.key, open)}
              disableGutters
              square
              TransitionProps={{ unmountOnExit: true }}
              sx={{
                boxShadow: 'none',
                bgcolor: 'transparent',
                '&:before': { display: 'none' },
                borderTop: 1,
                borderColor: 'divider',
                '&:last-of-type': { borderBottom: 1, borderColor: 'divider' },
              }}
            >
              <AccordionSummary
                expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}
                sx={{ '&:hover': { bgcolor: 'action.hover' } }}
              >
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, width: '100%', minWidth: 0, mr: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', minWidth: 0 }}>
                    <Typography
                      title={g.label}
                      sx={{ fontWeight: 700, ...monoSx, whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 0 }}
                    >
                      {g.label}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0 }}>
                      ({groupRows.length} {groupRows.length === 1 ? 'item' : 'items'})
                    </Typography>

                    <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 0.75, flexShrink: 0 }}>
                      {incompleteCount > 0 ? (
                        <Chip size="small" color="warning" label={`${incompleteCount} to classify`} />
                      ) : (
                        <>
                          <Chip
                            size="small"
                            color={uniformScope ? scopeLookup.color[uniformScope] : 'default'}
                            label={uniformScope ? scopeLookup.label[uniformScope] : 'Mixed'}
                          />
                          {hasSiteShop && !groupAllExempt && ssEligible.length > 0 && (
                            <Chip
                              size="small"
                              variant="outlined"
                              color={uniformSs ? ssLookup.color[uniformSs] : 'default'}
                              label={uniformSs ? ssLookup.label[uniformSs] : 'Mixed site/shop'}
                            />
                          )}
                        </>
                      )}
                      {!readOnly && (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.375 }}>
                          {incompleteCount > 0 ? (
                            <TriangleAlert size={13} strokeWidth={2} color="var(--mui-palette-warning-main)" />
                          ) : (
                            <Pencil size={13} strokeWidth={2} color="var(--mui-palette-text-secondary)" />
                          )}
                          <Typography
                            variant="caption"
                            sx={{ fontWeight: 600 }}
                            color={incompleteCount > 0 ? 'text.primary' : 'text.secondary'}
                          >
                            {incompleteCount > 0 ? 'Fix' : 'Change'}
                          </Typography>
                        </Box>
                      )}
                    </Box>
                  </Box>
                  {productCodes.length > 0 && (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      title={productCodes.join(', ')}
                      sx={{ ...monoSx, fontSize: '0.6875rem', whiteSpace: 'normal', wordBreak: 'break-word' }}
                    >
                      {productCodes.join(', ')}
                    </Typography>
                  )}
                </Box>
              </AccordionSummary>
              <AccordionDetails>
                {!readOnly && (
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      gap: 1.5,
                      mb: 1.5,
                      pb: 1.5,
                      borderBottom: 1,
                      borderColor: 'divider',
                    }}
                  >
                    <Typography sx={microLabelSx}>Set whole group</Typography>
                    {renderToggle(uniformScope ?? '', options, (value) => onClassify(uniqueKeys(groupRows), value))}
                    {hasSiteShop && siteShopOptions && !groupAllExempt && (
                      renderToggle(uniformSs ?? '', siteShopOptions, (value) =>
                        onClassifySiteShop!(uniqueKeys(ssEligible), value),
                      )
                    )}
                  </Box>
                )}

                <Box sx={{ overflowX: 'auto' }}>
                  <Table size="small" sx={{ '& td, & th': { px: 1 } }}>
                    <TableHead>
                      <TableRow>
                        <TableCell sx={microLabelSx}>Opening</TableCell>
                        <TableCell sx={microLabelSx}>Hand</TableCell>
                        <TableCell sx={microLabelSx}>Door Material</TableCell>
                        <TableCell sx={microLabelSx}>Frame Type</TableCell>
                        <TableCell sx={microLabelSx}>Product Code</TableCell>
                        <TableCell sx={microLabelSx}>Category</TableCell>
                        <TableCell sx={microLabelSx} align="right">Qty</TableCell>
                        <TableCell sx={microLabelSx}>{hasSiteShop ? 'Scope' : 'Classification'}</TableCell>
                        {hasSiteShop && <TableCell sx={microLabelSx}>Site / Shop</TableCell>}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {groupRows.map((r) => {
                        const exempt = !!siteShopExemptValue && r.classification === siteShopExemptValue;
                        return (
                          <TableRow key={r.id}>
                            <TableCell sx={monoSx}>{r.openingNumber}</TableCell>
                            <TableCell>{r.hand || '—'}</TableCell>
                            <TableCell>{r.doorMaterial || '—'}</TableCell>
                            <TableCell>{r.frameType || '—'}</TableCell>
                            <TableCell sx={monoSx}>{r.productCode}</TableCell>
                            <TableCell>{r.hardwareCategory}</TableCell>
                            <TableCell align="right" sx={tabularSx}>{r.itemQuantity}</TableCell>
                            <TableCell>
                              {readOnly ? (
                                r.classification ? (
                                  <Chip size="small" color={scopeLookup.color[r.classification] ?? 'default'} label={scopeLookup.label[r.classification] ?? r.classification} />
                                ) : (
                                  <Chip size="small" label="—" />
                                )
                              ) : (
                                renderToggle(r.classification, options, (value) => onClassify([r.classificationKey], value))
                              )}
                            </TableCell>
                            {hasSiteShop && (
                              <TableCell>
                                {exempt ? (
                                  <Chip size="small" label="—" />
                                ) : readOnly ? (
                                  r.siteShop ? (
                                    <Chip size="small" color={ssLookup.color[r.siteShop] ?? 'default'} label={ssLookup.label[r.siteShop] ?? r.siteShop} />
                                  ) : (
                                    <Chip size="small" label="—" />
                                  )
                                ) : (
                                  renderToggle(r.siteShop ?? '', siteShopOptions!, (value) =>
                                    onClassifySiteShop!([r.classificationKey], value),
                                  )
                                )}
                              </TableCell>
                            )}
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </Box>
              </AccordionDetails>
            </Accordion>
          );
        })}
      </Box>
    </Box>
  );
}
