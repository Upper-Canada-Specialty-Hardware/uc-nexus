import {
  Box,
  Typography,
  Button,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Checkbox,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { AggregatedHardwareItem } from './types';
import { aggregationKey, itemGroupKey } from './types';

interface SelectHardwareItemsStepProps {
  allAggregatedItems: AggregatedHardwareItem[];
  selectedItemKeys: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
  canProceed: boolean;
  onNext: () => void;
  onBack: () => void;
}

export default function SelectHardwareItemsStep({
  allAggregatedItems,
  selectedItemKeys,
  onSelectionChange,
  canProceed,
  onNext,
  onBack,
}: SelectHardwareItemsStepProps) {
  // Group items by (hardware_category, product_code)
  const groups = new Map<string, AggregatedHardwareItem[]>();
  for (const item of allAggregatedItems) {
    const key = itemGroupKey(item);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(item);
  }
  const sortedGroups = Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));

  const totalCount = allAggregatedItems.length;
  const selectedCount = selectedItemKeys.size;

  const handleSelectAll = () => {
    onSelectionChange(new Set(allAggregatedItems.map((hi) => aggregationKey(hi))));
  };

  const handleDeselectAll = () => {
    onSelectionChange(new Set());
  };

  const toggleItem = (key: string) => {
    const next = new Set(selectedItemKeys);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    onSelectionChange(next);
  };

  const toggleGroup = (groupItems: AggregatedHardwareItem[]) => {
    const groupKeys = groupItems.map((hi) => aggregationKey(hi));
    const allSelected = groupKeys.every((k) => selectedItemKeys.has(k));
    const next = new Set(selectedItemKeys);
    if (allSelected) {
      for (const k of groupKeys) next.delete(k);
    } else {
      for (const k of groupKeys) next.add(k);
    }
    onSelectionChange(next);
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h6">
          Select Hardware Items
          <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
            ({selectedCount} of {totalCount} selected)
          </Typography>
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button size="small" variant="outlined" onClick={handleSelectAll}>
            Select All
          </Button>
          <Button size="small" variant="outlined" onClick={handleDeselectAll}>
            Deselect All
          </Button>
        </Box>
      </Box>

      {sortedGroups.map(([groupKey, items]) => {
        const [category, productCode] = groupKey.split('|');
        const groupKeys = items.map((hi) => aggregationKey(hi));
        const selectedInGroup = groupKeys.filter((k) => selectedItemKeys.has(k)).length;
        const allSelected = selectedInGroup === items.length;
        const someSelected = selectedInGroup > 0 && !allSelected;

        return (
          <Accordion key={groupKey} defaultExpanded={false}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                <Checkbox
                  checked={allSelected}
                  indeterminate={someSelected}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => toggleGroup(items)}
                  size="small"
                />
                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                  {productCode}
                </Typography>
                <Chip label={category} size="small" variant="outlined" />
                <Typography variant="body2" color="text.secondary" sx={{ ml: 'auto', mr: 2 }}>
                  {selectedInGroup}/{items.length} items
                </Typography>
              </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ p: 0 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell padding="checkbox" />
                    <TableCell>Opening</TableCell>
                    <TableCell align="right">Qty</TableCell>
                    <TableCell>Vendor</TableCell>
                    <TableCell align="right">Unit Cost</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((hi) => {
                    const key = aggregationKey(hi);
                    return (
                      <TableRow key={key} hover>
                        <TableCell padding="checkbox">
                          <Checkbox
                            checked={selectedItemKeys.has(key)}
                            onChange={() => toggleItem(key)}
                            size="small"
                          />
                        </TableCell>
                        <TableCell>{hi.opening_number}</TableCell>
                        <TableCell align="right">{hi.item_quantity}</TableCell>
                        <TableCell>{hi.vendor_no ?? '(No Vendor)'}</TableCell>
                        <TableCell align="right">
                          {hi.unit_cost != null ? `$${hi.unit_cost.toFixed(2)}` : '\u2014'}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </AccordionDetails>
          </Accordion>
        );
      })}

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
