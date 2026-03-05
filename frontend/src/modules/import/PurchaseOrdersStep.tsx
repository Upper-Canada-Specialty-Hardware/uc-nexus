import { useMemo } from 'react';
import { Box, Button, Checkbox, FormControlLabel, InputAdornment, Paper, TextField, Typography } from '@mui/material';
import type { ParsedHardwareItem } from '../../types/hardwareSchedule';

// ---- Aggregation Types ----

interface AggregatedLineItem {
  productCode: string;
  hardwareCategory: string;
  totalQuantity: number;
  unitCost: number;
  totalCost: number;
}

// ---- Props ----

interface PurchaseOrdersStepProps {
  vendorGroups: Map<string, ParsedHardwareItem[]>;
  vendorPOInfo: Map<string, { poNumber: string; vendorContact: string }>;
  selectedVendors: Set<string>;
  unitCostOverrides: Map<string, number>;
  vendorAliases: Map<string, string>;
  onToggleVendor: (vendor: string) => void;
  onUpdateVendorPO: (vendorNo: string, field: 'poNumber' | 'vendorContact', value: string) => void;
  onUpdateUnitCost: (vendor: string, productCode: string, hardwareCategory: string, newCost: number) => void;
  onUpdateVendorAlias: (key: string, alias: string) => void;
  onNext: () => void;
  onBack: () => void;
}

// ---- Helpers ----

function aggregateLineItems(
  items: ParsedHardwareItem[],
  vendor: string,
  overrides: Map<string, number>,
): AggregatedLineItem[] {
  const groups = new Map<string, AggregatedLineItem>();

  for (const item of items) {
    const key = `${item.product_code}|${item.hardware_category}`;
    const overrideKey = `${vendor}|${item.product_code}|${item.hardware_category}`;
    const cost = overrides.get(overrideKey) ?? item.unit_cost ?? 0;
    const existing = groups.get(key);
    if (existing) {
      existing.totalQuantity += item.item_quantity;
      existing.totalCost = existing.unitCost * existing.totalQuantity;
    } else {
      groups.set(key, {
        productCode: item.product_code,
        hardwareCategory: item.hardware_category,
        totalQuantity: item.item_quantity,
        unitCost: cost,
        totalCost: cost * item.item_quantity,
      });
    }
  }

  return Array.from(groups.values()).sort((a, b) => {
    const catCmp = a.hardwareCategory.localeCompare(b.hardwareCategory);
    if (catCmp !== 0) return catCmp;
    return a.productCode.localeCompare(b.productCode);
  });
}

// ---- Component ----

export default function PurchaseOrdersStep({
  vendorGroups,
  vendorPOInfo,
  selectedVendors,
  unitCostOverrides,
  vendorAliases,
  onToggleVendor,
  onUpdateVendorPO,
  onUpdateUnitCost,
  onUpdateVendorAlias,
  onNext,
  onBack,
}: PurchaseOrdersStepProps) {
  const canProceed = useMemo(() => {
    if (selectedVendors.size === 0) return false;
    for (const vendor of selectedVendors) {
      const info = vendorPOInfo.get(vendor);
      if (!info || info.poNumber.trim() === '') return false;
    }
    return true;
  }, [selectedVendors, vendorPOInfo]);

  const sortedVendors = useMemo(
    () => Array.from(vendorGroups.entries()).sort(([a], [b]) => a.localeCompare(b)),
    [vendorGroups],
  );

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 1 }}>
        Purchase Orders
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {vendorGroups.size} vendor(s). Select which vendors to create POs for, then enter a PO number for each.
      </Typography>

      {sortedVendors.map(([vendor, items]) => {
        const info = vendorPOInfo.get(vendor) ?? { poNumber: '', vendorContact: '' };
        const aggregated = aggregateLineItems(items, vendor, unitCostOverrides);
        const poTotal = aggregated.reduce((sum, line) => sum + line.totalCost, 0);
        const isSelected = selectedVendors.has(vendor);

        return (
          <Paper key={vendor} variant="outlined" sx={{ p: 2, mb: 2, opacity: isSelected ? 1 : 0.5 }}>
            {/* Header: checkbox + vendor name + PO total */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={isSelected}
                    onChange={() => onToggleVendor(vendor)}
                  />
                }
                label={
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                    {vendor}
                  </Typography>
                }
              />
              <Typography variant="subtitle1" color="primary">
                PO Total: ${poTotal.toFixed(2)}
              </Typography>
            </Box>

            {/* PO Number + Vendor Contact fields */}
            <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
              <TextField
                label="PO Number"
                size="small"
                required
                disabled={!isSelected}
                value={info.poNumber}
                onChange={(e) => onUpdateVendorPO(vendor, 'poNumber', e.target.value)}
                sx={{ flex: 1 }}
              />
              <TextField
                label="Vendor Contact"
                size="small"
                disabled={!isSelected}
                value={info.vendorContact}
                onChange={(e) => onUpdateVendorPO(vendor, 'vendorContact', e.target.value)}
                sx={{ flex: 1 }}
              />
            </Box>

            {/* Line Items subheading */}
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Line Items ({aggregated.length})
            </Typography>

            {/* Aggregated line items grid */}
            <Box sx={{ display: 'grid', gridTemplateColumns: '1.5fr 1.5fr 0.7fr 0.8fr 0.8fr 1.2fr' }}>
              {/* Header row */}
              <Box sx={{ bgcolor: 'grey.100', p: 0.75 }}>
                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                  Product Code
                </Typography>
              </Box>
              <Box sx={{ bgcolor: 'grey.100', p: 0.75 }}>
                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                  Hardware Category
                </Typography>
              </Box>
              <Box sx={{ bgcolor: 'grey.100', p: 0.75, textAlign: 'right' }}>
                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                  Total Qty
                </Typography>
              </Box>
              <Box sx={{ bgcolor: 'grey.100', p: 0.75, textAlign: 'right' }}>
                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                  Unit Cost
                </Typography>
              </Box>
              <Box sx={{ bgcolor: 'grey.100', p: 0.75, textAlign: 'right' }}>
                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                  Total Cost
                </Typography>
              </Box>
              <Box sx={{ bgcolor: 'grey.100', p: 0.75 }}>
                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                  Vendor Alias
                </Typography>
              </Box>

              {/* Data rows */}
              {aggregated.map((line, idx) => {
                const rowBg = idx % 2 === 0 ? 'background.paper' : 'grey.50';
                const aliasKey = `${line.productCode}|${line.hardwareCategory}`;
                return (
                  <Box key={`${line.productCode}-${line.hardwareCategory}`} sx={{ display: 'contents' }}>
                    <Box sx={{ bgcolor: rowBg, p: 0.75 }}>
                      <Typography variant="body2">{line.productCode}</Typography>
                    </Box>
                    <Box sx={{ bgcolor: rowBg, p: 0.75 }}>
                      <Typography variant="body2">{line.hardwareCategory}</Typography>
                    </Box>
                    <Box sx={{ bgcolor: rowBg, p: 0.75, textAlign: 'right' }}>
                      <Typography variant="body2">{line.totalQuantity}</Typography>
                    </Box>
                    <Box sx={{ bgcolor: rowBg, p: 0.75, textAlign: 'right' }}>
                      <TextField
                        size="small"
                        type="number"
                        disabled={!isSelected}
                        value={line.unitCost}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value);
                          if (!isNaN(val) && val >= 0) {
                            onUpdateUnitCost(vendor, line.productCode, line.hardwareCategory, val);
                          }
                        }}
                        slotProps={{
                          input: {
                            startAdornment: <InputAdornment position="start">$</InputAdornment>,
                          },
                          htmlInput: { min: 0, step: 0.01 },
                        }}
                        sx={{ width: 120 }}
                      />
                    </Box>
                    <Box sx={{ bgcolor: rowBg, p: 0.75, textAlign: 'right' }}>
                      <Typography variant="body2">${line.totalCost.toFixed(2)}</Typography>
                    </Box>
                    <Box sx={{ bgcolor: rowBg, p: 0.75, display: 'flex', alignItems: 'center' }}>
                      <TextField
                        size="small"
                        placeholder="Vendor alias"
                        disabled={!isSelected}
                        value={vendorAliases.get(aliasKey) ?? ''}
                        onChange={(e) => onUpdateVendorAlias(aliasKey, e.target.value)}
                        variant="standard"
                        fullWidth
                        slotProps={{ input: { sx: { fontSize: '0.875rem' } } }}
                      />
                    </Box>
                  </Box>
                );
              })}
            </Box>
          </Paper>
        );
      })}

      {/* Bottom navigation */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3 }}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="contained" disabled={!canProceed} onClick={onNext}>
          Next
        </Button>
      </Box>
    </Box>
  );
}
