import { useMemo } from 'react';
import { Box, Checkbox, FormControlLabel, InputAdornment, MenuItem, Paper, TextField, Typography } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import OrderAsAutocomplete from '../../components/OrderAsAutocomplete';
import { GET_PRIOR_ORDER_AS_VALUES } from '../../graphql/shared';
import { GET_GP_COST_CODES } from '../../graphql/po';
import { useRelayStatus } from '../../relay/useRelayStatus';
import type { AggregatedHardwareItem } from './types';
import { monoSx, microLabelSx, tabularSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';

// ---- Aggregation Types ----

interface AggregatedLineItem {
  productCode: string;
  hardwareCategory: string;
  totalQuantity: number;
  unitCost: number;
  totalCost: number;
}

// #490: the job's live GP cost codes, fetched once for the step and shared across every card
// rather than per card - it is one job, so it is one list.
interface GpCostCode {
  costCode: string;
  costElement: string;
  description: string | null;
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
  /** The wizard's project - order-as memory is scoped to it (#509). */
  projectId: string;
  /** The GP job number (#490). Cost codes are per job, so the live list is keyed on it. */
  jobNumber: string | null;
  vendorGroups: Map<string, AggregatedHardwareItem[]>;
  vendorPOInfo: Map<string, { notes: string; preferredDeliveryDate: string; costCode: string }>;
  selectedVendors: Set<string>;
  unitCostOverrides: Map<string, number>;
  orderAsValues: Map<string, string>;
  onToggleVendor: (vendor: string) => void;
  onUpdateVendorPO: (
    manufacturerKey: string,
    field: 'notes' | 'preferredDeliveryDate' | 'costCode',
    value: string | null,
  ) => void;
  onUpdateUnitCost: (vendor: string, productCode: string, hardwareCategory: string, newCost: number) => void;
  onUpdateOrderAs: (key: string, value: string) => void;
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
  projectId: string;
  vendor: string;
  items: AggregatedHardwareItem[];
  info: { notes: string; preferredDeliveryDate: string; costCode: string };
  costCodes: GpCostCode[];
  isSelected: boolean;
  unitCostOverrides: Map<string, number>;
  orderAsValues: Map<string, string>;
  onToggleVendor: (vendor: string) => void;
  onUpdateVendorPO: (
    manufacturerKey: string,
    field: 'notes' | 'preferredDeliveryDate' | 'costCode',
    value: string | null,
  ) => void;
  onUpdateUnitCost: (vendor: string, productCode: string, hardwareCategory: string, newCost: number) => void;
  onUpdateOrderAs: (key: string, value: string) => void;
}

function VendorGroupCard({
  projectId,
  vendor,
  items,
  info,
  costCodes,
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

  // Scoped to the project (#509) - what a part is ordered as is remembered per job. It used to need
  // a Nexus vendor picked first, so the suggestions were usually absent at the one moment they are
  // useful; the project is known here, and it also bounds a query the wizard fires once per card.
  const { data: priorData } = useQuery<PriorOrderAsQueryData>(GET_PRIOR_ORDER_AS_VALUES, {
    variables: { projectId, productCodes },
    skip: productCodes.length === 0,
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
              <Typography sx={microLabelSx}>Manufacturer</Typography>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, ...monoSx, fontSize: '1rem' }}>
                {vendor}
              </Typography>
            </Box>
          }
        />
        <Box sx={{ textAlign: 'right' }}>
          <Typography sx={microLabelSx}>PO Total</Typography>
          <Typography variant="subtitle1" sx={{ ...tabularSx, fontWeight: 700 }}>
            ${poTotal.toFixed(2)}
          </Typography>
        </Box>
      </Box>

      {/* Preferred delivery date + Notes. No vendor field: the GP vendor (PM00200) is picked when the
          draft is registered into GP, and it is the only vendor a PO has (#509). */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
        <TextField
          label="Preferred delivery date"
          size="small"
          type="date"
          disabled={!isSelected}
          value={info.preferredDeliveryDate}
          onChange={(e) => onUpdateVendorPO(vendor, 'preferredDeliveryDate', e.target.value)}
          sx={{ width: 190 }}
          slotProps={{ inputLabel: { shrink: true } }}
        />
        {costCodes.length > 0 && (
          <TextField
            select
            label="Cost code"
            size="small"
            disabled={!isSelected}
            value={info.costCode}
            onChange={(e) => onUpdateVendorPO(vendor, 'costCode', e.target.value)}
            sx={{ width: 260, '& .MuiSelect-select': monoSx }}
            helperText="Optional, carried to GP registration"
          >
            <MenuItem value="">
              <em>None</em>
            </MenuItem>
            {costCodes.map((c) => (
              <MenuItem key={`${c.costCode}-${c.costElement}`} value={`${c.costCode}-${c.costElement}`}>
                {c.description ? `${c.costCode} · ${c.description}` : c.costCode}
              </MenuItem>
            ))}
          </TextField>
        )}
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
      <Typography sx={{ ...microLabelSx, mb: 1 }}>Line Items ({aggregated.length})</Typography>

      {/* Aggregated line items: a ledger - a 2px ink rule under the headers and hairline row rules,
          no zebra fill (the old grey.50/grey.100 pair was invisible in dark mode anyway). */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: '1.2fr 1.5fr 1.5fr 0.7fr 0.8fr 0.8fr',
          '& .po-head': {
            ...microLabelSx,
            px: 1,
            py: 0.75,
            borderBottom: '2px solid',
            borderColor: 'text.primary',
          },
          '& .po-cell': {
            px: 1,
            py: 0.75,
            borderBottom: '1px solid',
            borderColor: 'divider',
            display: 'flex',
            alignItems: 'center',
            minWidth: 0,
          },
          '& .po-cell-right': { justifyContent: 'flex-end' },
        }}
      >
        {/* Header row */}
        <Box className="po-head">Order As</Box>
        {/* TITAN's scheduled part number, read-only from the schedule. "Order As" beside it is the
            vendor-facing alias the buyer types. Data field stays productCode (#482). */}
        <Box className="po-head">Scheduled Part Number</Box>
        <Box className="po-head">Hardware Category</Box>
        <Box className="po-head" sx={{ textAlign: 'right' }}>
          Total Qty
        </Box>
        <Box className="po-head" sx={{ textAlign: 'right' }}>
          Unit Cost
        </Box>
        <Box className="po-head" sx={{ textAlign: 'right' }}>
          Total Cost
        </Box>

        {/* Data rows */}
        {aggregated.map((line) => {
          const aliasKey = `${line.productCode}|${line.hardwareCategory}`;
          const options = priorMap.get(line.productCode) ?? [];
          return (
            <Box key={`${line.productCode}-${line.hardwareCategory}`} sx={{ display: 'contents' }}>
              <Box className="po-cell">
                <OrderAsAutocomplete
                  value={orderAsValues.get(aliasKey) ?? ''}
                  onChange={(next) => onUpdateOrderAs(aliasKey, next)}
                  options={options}
                  disabled={!isSelected}
                  placeholder="Order as"
                />
              </Box>
              <Box className="po-cell">
                <Typography variant="body2" sx={monoSx}>
                  {line.productCode}
                </Typography>
              </Box>
              <Box className="po-cell">
                <Typography variant="body2">{line.hardwareCategory}</Typography>
              </Box>
              <Box className="po-cell po-cell-right">
                <Typography variant="body2" sx={tabularSx}>
                  {line.totalQuantity}
                </Typography>
              </Box>
              <Box className="po-cell po-cell-right">
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
                      sx: tabularSx,
                    },
                    htmlInput: { min: 0, step: 0.01 },
                  }}
                  sx={{ width: 120 }}
                />
              </Box>
              <Box className="po-cell po-cell-right">
                <Typography variant="body2" sx={tabularSx}>
                  ${line.totalCost.toFixed(2)}
                </Typography>
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
  projectId,
  jobNumber,
  vendorGroups,
  vendorPOInfo,
  selectedVendors,
  unitCostOverrides,
  orderAsValues,
  onToggleVendor,
  onUpdateVendorPO,
  onUpdateUnitCost,
  onUpdateOrderAs,
}: PurchaseOrdersStepProps) {
  // #490: one job, so one cost-code read for the whole step rather than one per manufacturer card.
  // Relay down or job absent -> empty list -> the cards render no cost-code field at all, and the
  // code is picked at GP registration as before.
  const relay = useRelayStatus({});
  const company = relay.company ?? '';
  const { data: costCodesData } = useQuery<{ gpCostCodes: GpCostCode[] }>(GET_GP_COST_CODES, {
    variables: { company, job: jobNumber ?? '' },
    skip: relay.connected !== true || !company || !jobNumber,
    fetchPolicy: 'cache-first',
  });
  const costCodes = useMemo(() => costCodesData?.gpCostCodes ?? [], [costCodesData]);

  const sortedVendors = useMemo(
    () => Array.from(vendorGroups.entries()).sort(([a], [b]) => a.localeCompare(b)),
    [vendorGroups],
  );

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 1 }}>
        Purchase Orders
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ ...tabularSx, mb: 3 }}>
        {vendorGroups.size} manufacturer group(s). Select which to create purchase order requests for. The GP vendor to buy from, and the PO number, are chosen later when the request is registered in Microsoft GP.
      </Typography>

      <StaggerList count={sortedVendors.length}>
        {sortedVendors.map(([vendor, items]) => {
          const info = vendorPOInfo.get(vendor) ?? { notes: '', preferredDeliveryDate: '', costCode: '' };
          const isSelected = selectedVendors.has(vendor);
          return (
            <StaggerItem key={vendor}>
              <VendorGroupCard
                projectId={projectId}
                vendor={vendor}
                items={items}
                info={info}
                costCodes={costCodes}
                isSelected={isSelected}
                unitCostOverrides={unitCostOverrides}
                orderAsValues={orderAsValues}
                onToggleVendor={onToggleVendor}
                onUpdateVendorPO={onUpdateVendorPO}
                onUpdateUnitCost={onUpdateUnitCost}
                onUpdateOrderAs={onUpdateOrderAs}
              />
            </StaggerItem>
          );
        })}
      </StaggerList>
    </Box>
  );
}
