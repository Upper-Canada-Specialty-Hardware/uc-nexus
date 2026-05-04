import { useMemo } from 'react';
import { Box, Button, Checkbox, FormControlLabel, InputAdornment, Paper, TextField, Typography } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import VendorSelect from '../../components/VendorSelect';
import OrderAsAutocomplete from '../../components/OrderAsAutocomplete';
import { GET_PRIOR_ORDER_AS_VALUES } from '../../graphql/queries';
import type { AggregatedHardwareItem } from './types';

// ---- Aggregation Types ----

interface AggregatedLineItem {
  productCode: string;
  hardwareCategory: string;
  totalQuantity: number;
  unitCost: number;
  totalCost: number;
}

interface PriorOrderAsForProduct {
  productCode: string;
  values: string[];
}

interface PriorOrderAsQueryData {
  priorOrderAsValues: PriorOrderAsForProduct[];
}

// ---- Props ----

interface PurchaseOrdersStepProps {
  vendorGroups: Map<string, AggregatedHardwareItem[]>;
  vendorPOInfo: Map<string, { vendorId: string | null; notes: string }>;
  selectedVendors: Set<string>;
  unitCostOverrides: Map<string, number>;
  orderAsValues: Map<string, string>;
  onToggleVendor: (vendor: string) => void;
  onUpdateVendorPO: (manufacturerKey: string, field: 'vendorId' | 'notes', value: string | null) => void;
  onUpdateUnitCost: (vendor: string, productCode: string, hardwareCategory: string, newCost: number) => void;
  onUpdateOrderAs: (key: string, value: string) => void;
  onNext: () => void;
  onBack: () => void;
}

// ---- Helpers ----

function aggregateLineItems(
  items: AggregatedHardwareItem[],
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

// ---- Vendor Group Card (per-manufacturer subcomponent so useQuery is hook-safe) ----

interface VendorGroupCardProps {
  vendor: string;
  items: AggregatedHardwareItem[];
  info: { vendorId: string | null; notes: string };
  isSelected: boolean;
  unitCostOverrides: Map<string, number>;
  orderAsValues: Map<string, string>;
  onToggleVendor: (vendor: string) => void;
  onUpdateVendorPO: (manufacturerKey: string, field: 'vendorId' | 'notes', value: string | null) => void;
  onUpdateUnitCost: (vendor: string, productCode: string, hardwareCategory: string, newCost: number) => void;
  onUpdateOrderAs: (key: string, value: string) => void;
}

function VendorGroupCard({
  vendor,
  items,
  info,
  isSelected,
  unitCostOverrides,
  orderAsValues,
  onToggleVendor,
  onUpdateVendorPO,
  onUpdateUnitCost,
  onUpdateOrderAs,
}: VendorGroupCardProps) {
  const aggregated = useMemo(
    () => aggregateLineItems(items, vendor, unitCostOverrides),
    [items, vendor, unitCostOverrides],
  );

  const productCodes = useMemo(
    () => Array.from(new Set(aggregated.map((l) => l.productCode))),
    [aggregated],
  );

  const { data: priorData } = useQuery<PriorOrderAsQueryData>(GET_PRIOR_ORDER_AS_VALUES, {
    variables: { vendorId: info.vendorId ?? '', productCodes },
    skip: !info.vendorId || productCodes.length === 0,
  });

  const priorMap = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const entry of priorData?.priorOrderAsValues ?? []) {
      map.set(entry.productCode, entry.values);
    }
    return map;
  }, [priorData]);

  const poTotal = aggregated.reduce((sum, line) => sum + line.totalCost, 0);

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2, opacity: isSelected ? 1 : 0.5 }}>
      {/* Header: checkbox + manufacturer label + PO total */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <FormControlLabel
          control={<Checkbox checked={isSelected} onChange={() => onToggleVendor(vendor)} />}
          label={
            <Box>
              <Typography variant="caption" color="text.secondary">
                Manufacturer
              </Typography>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                {vendor}
              </Typography>
            </Box>
          }
        />
        <Typography variant="subtitle1" color="primary">
          PO Total: ${poTotal.toFixed(2)}
        </Typography>
      </Box>

      {/* Vendor select + Notes fields */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
        <Box sx={{ flex: 1 }}>
          <VendorSelect
            value={info.vendorId}
            onChange={(id) => onUpdateVendorPO(vendor, 'vendorId', id)}
            disabled={!isSelected}
          />
        </Box>
        <TextField
          label="Notes"
          size="small"
          multiline
          minRows={1}
          maxRows={3}
          disabled={!isSelected}
          value={info.notes}
          onChange={(e) => onUpdateVendorPO(vendor, 'notes', e.target.value)}
          sx={{ flex: 1 }}
          placeholder="Optional notes for this PO"
        />
      </Box>

      {/* Line Items subheading */}
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Line Items ({aggregated.length})
      </Typography>

      {/* Aggregated line items grid */}
      <Box sx={{ display: 'grid', gridTemplateColumns: '1.2fr 1.5fr 1.5fr 0.7fr 0.8fr 0.8fr' }}>
        {/* Header row */}
        <Box sx={{ bgcolor: 'grey.100', p: 0.75 }}>
          <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
            Order As
          </Typography>
        </Box>
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

        {/* Data rows */}
        {aggregated.map((line, idx) => {
          const rowBg = idx % 2 === 0 ? 'background.paper' : 'grey.50';
          const aliasKey = `${line.productCode}|${line.hardwareCategory}`;
          const options = priorMap.get(line.productCode) ?? [];
          return (
            <Box key={`${line.productCode}-${line.hardwareCategory}`} sx={{ display: 'contents' }}>
              <Box sx={{ bgcolor: rowBg, p: 0.75, display: 'flex', alignItems: 'center' }}>
                <OrderAsAutocomplete
                  value={orderAsValues.get(aliasKey) ?? ''}
                  onChange={(next) => onUpdateOrderAs(aliasKey, next)}
                  options={options}
                  disabled={!isSelected}
                  placeholder="Order as"
                />
              </Box>
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
            </Box>
          );
        })}
      </Box>
    </Paper>
  );
}

// ---- Component ----

export default function PurchaseOrdersStep({
  vendorGroups,
  vendorPOInfo,
  selectedVendors,
  unitCostOverrides,
  orderAsValues,
  onToggleVendor,
  onUpdateVendorPO,
  onUpdateUnitCost,
  onUpdateOrderAs,
  onNext,
  onBack,
}: PurchaseOrdersStepProps) {
  const canProceed = useMemo(() => {
    return selectedVendors.size > 0;
  }, [selectedVendors]);

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
        {vendorGroups.size} manufacturer group(s). Select which to create purchase orders for, and pick a vendor (the company you buy from). PO numbers can be assigned later from Microsoft GP.
      </Typography>

      {sortedVendors.map(([vendor, items]) => {
        const info = vendorPOInfo.get(vendor) ?? { vendorId: null, notes: '' };
        const isSelected = selectedVendors.has(vendor);
        return (
          <VendorGroupCard
            key={vendor}
            vendor={vendor}
            items={items}
            info={info}
            isSelected={isSelected}
            unitCostOverrides={unitCostOverrides}
            orderAsValues={orderAsValues}
            onToggleVendor={onToggleVendor}
            onUpdateVendorPO={onUpdateVendorPO}
            onUpdateUnitCost={onUpdateUnitCost}
            onUpdateOrderAs={onUpdateOrderAs}
          />
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
