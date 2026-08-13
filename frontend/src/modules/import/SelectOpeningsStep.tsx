import { useMemo } from 'react';
import {
  Box,
  Typography,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from '@mui/material';
import { ChevronDown } from 'lucide-react';
import type { ParsedOpening } from '../../types/hardwareSchedule';
import type { AggregatedHardwareItem } from './types';
import { aggregationKey, itemGroupKey } from './types';
import { monoSx, tabularSx } from '../../theme';
import OpeningSelectionPanel from './OpeningSelectionPanel';

// ---- Props ----

interface SelectOpeningsStepProps {
  openings: ParsedOpening[];
  selectedOpenings: Set<string>;
  preReconAggregatedItems: AggregatedHardwareItem[];
  onOpeningSelectionChange: (selected: Set<string>) => void;
}

// ---- Main Component ----
//
// The opening-selection experience lives in OpeningSelectionPanel now, shared with the shipping
// request workspace (#608 follow-up). This step is that panel plus the wizard-only hardware preview:
// a read-only rollup of what the selected openings carry, which the workspace omits.

export default function SelectOpeningsStep({
  openings,
  selectedOpenings,
  preReconAggregatedItems,
  onOpeningSelectionChange,
}: SelectOpeningsStepProps) {
  // ---- Right Panel: Hardware Items Accordion (read-only preview) ----

  const NO_MANUFACTURER = '(No Manufacturer)';

  const manufacturerGroups = useMemo(() => {
    const outer = new Map<string, Map<string, AggregatedHardwareItem[]>>();
    for (const item of preReconAggregatedItems) {
      const manufacturer = item.vendor_no ?? NO_MANUFACTURER;
      const innerKey = itemGroupKey(item);
      if (!outer.has(manufacturer)) outer.set(manufacturer, new Map());
      const inner = outer.get(manufacturer)!;
      if (!inner.has(innerKey)) inner.set(innerKey, []);
      inner.get(innerKey)!.push(item);
    }
    return Array.from(outer.entries())
      .sort(([a], [b]) => {
        if (a === NO_MANUFACTURER) return 1;
        if (b === NO_MANUFACTURER) return -1;
        return a.localeCompare(b);
      })
      .map(
        ([manufacturer, inner]) =>
          [manufacturer, Array.from(inner.entries()).sort(([a], [b]) => a.localeCompare(b))] as const,
      );
  }, [preReconAggregatedItems]);

  const itemTotalCount = preReconAggregatedItems.length;

  // A read-only preview earns less width than the grid you actually work in, so it takes a fixed
  // column (sized by OpeningSelectionPanel's rightPanel slot) instead of half the step.
  const hardwarePreview = (
    <>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="h6">
          Hardware Items
          <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1, ...tabularSx }}>
            ({itemTotalCount} items)
          </Typography>
        </Typography>
      </Box>

      <Box sx={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
        {selectedOpenings.size === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2, textAlign: 'center' }}>
            Select openings to see hardware items
          </Typography>
        ) : manufacturerGroups.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2, textAlign: 'center' }}>
            No hardware items for selected openings
          </Typography>
        ) : (
          manufacturerGroups.map(([manufacturer, productGroups]) => {
            const productCount = productGroups.length;
            const occurrenceCount = productGroups.reduce((sum, [, items]) => sum + items.length, 0);
            const manufacturerTotalCost = productGroups.reduce(
              (sum, [, items]) => sum + items.reduce((s, hi) => s + (hi.unit_cost ?? 0) * hi.item_quantity, 0),
              0,
            );

            return (
              <Accordion key={manufacturer} defaultExpanded={false}>
                <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', flexWrap: 'wrap' }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, ...monoSx }}>
                      {manufacturer}
                    </Typography>
                    <Chip
                      label={`${productCount} product${productCount === 1 ? '' : 's'}`}
                      size="small"
                      variant="outlined"
                    />
                    <Chip label={`Total: $${manufacturerTotalCost.toFixed(2)}`} size="small" variant="outlined" />
                    <Typography variant="body2" color="text.secondary" sx={{ ml: 'auto', mr: 2, ...tabularSx }}>
                      {occurrenceCount}
                    </Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ p: 0, pl: 2 }}>
                  {productGroups.map(([groupKey, items]) => {
                    const [category, productCode] = groupKey.split('|');

                    return (
                      <Accordion key={groupKey} defaultExpanded={false} disableGutters>
                        <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', flexWrap: 'wrap' }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, ...monoSx }}>
                              {productCode}
                            </Typography>
                            <Chip label={category} size="small" variant="outlined" />
                            <Chip
                              label={items[0].unit_cost != null ? `$${items[0].unit_cost.toFixed(2)}` : '—'}
                              size="small"
                              variant="outlined"
                            />
                            <Chip
                              label={`Total: $${items.reduce((sum, hi) => sum + (hi.unit_cost ?? 0) * hi.item_quantity, 0).toFixed(2)}`}
                              size="small"
                              variant="outlined"
                            />
                            <Typography variant="body2" color="text.secondary" sx={{ ml: 'auto', mr: 2, ...tabularSx }}>
                              {items.length}
                            </Typography>
                          </Box>
                        </AccordionSummary>
                        <AccordionDetails sx={{ p: 0 }}>
                          <Table size="small">
                            <TableHead>
                              <TableRow>
                                <TableCell>Opening</TableCell>
                                <TableCell align="right">Qty</TableCell>
                              </TableRow>
                            </TableHead>
                            <TableBody>
                              {items.map((hi) => (
                                <TableRow key={aggregationKey(hi)} hover>
                                  <TableCell sx={monoSx}>{hi.opening_number}</TableCell>
                                  <TableCell align="right">{hi.item_quantity}</TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </AccordionDetails>
                      </Accordion>
                    );
                  })}
                </AccordionDetails>
              </Accordion>
            );
          })
        )}
      </Box>
    </>
  );

  return (
    <Box>
      <OpeningSelectionPanel
        openings={openings}
        selectedOpenings={selectedOpenings}
        onOpeningSelectionChange={onOpeningSelectionChange}
        rightPanel={hardwarePreview}
      />
    </Box>
  );
}
