import { useState, useMemo, useCallback } from 'react';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Button,
  Chip,
  IconButton,
  MenuItem,
  TextField,
  Typography,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import { ChevronDown, Plus, X } from 'lucide-react';
import {
  DataGrid,
  type GridColDef,
  type GridRowSelectionModel,
  type GridRenderCellParams,
} from '@mui/x-data-grid';
import type { ClassificationOption } from './types';
import { monoSx, microLabelSx } from '../../theme';

export interface ClassificationRow {
  id: string;
  openingNumber: string;
  // #486: the opening's own attributes, carried through so the classifier can see what door each
  // item belongs to without leaving the step. Sourced from ParsedOpening (hand / leaf_count /
  // door_type), not from the hardware item.
  hand: string;
  doorQuantity: number | null;
  doorMaterial: string;
  productCode: string;
  hardwareCategory: string;
  vendorNo: string;
  listPrice: number | null;
  vendorDiscount: number | null;
  unitCost: number;
  itemQuantity: number;
  classificationKey: string;
  classification: string;
  // Issue #216: second axis (Site/Shop) for PO-purpose imports; '' = not yet classified.
  siteShop?: string;
}

export type GroupByField = 'hardwareCategory' | 'vendorNo' | 'productCode' | 'openingNumber'
  | 'doorMaterial' | 'unitCost' | 'listPrice' | 'vendorDiscount' | 'itemQuantity';

const GROUP_BY_OPTIONS: { value: GroupByField; label: string }[] = [
  { value: 'hardwareCategory', label: 'Hardware Category' },
  { value: 'vendorNo', label: 'Manufacturer' },
  { value: 'productCode', label: 'Product Code' },
  { value: 'openingNumber', label: 'Opening Number' },
  { value: 'doorMaterial', label: 'Door Material' },
  { value: 'unitCost', label: 'Unit Cost' },
  { value: 'listPrice', label: 'List Price' },
  { value: 'vendorDiscount', label: 'Vendor Discount' },
  { value: 'itemQuantity', label: 'Item Quantity' },
];

interface ClassificationGridProps {
  rows: ClassificationRow[];
  options: ClassificationOption[];
  onClassify: (classificationKeys: string[], value: string) => void;
  readOnly?: boolean;
  // Issue #216: optional second axis (Site/Shop). Rows whose primary classification equals
  // siteShopExemptValue (By Others) don't need it and render an em-dash.
  siteShopOptions?: ClassificationOption[];
  onClassifySiteShop?: (classificationKeys: string[], value: string) => void;
  siteShopExemptValue?: string;
}

interface GroupNode {
  label: string;
  rows: ClassificationRow[];
  children: Map<string, GroupNode> | null;
}

// Issue #216: the optional Site/Shop axis, bundled so it threads through the group tree in one prop.
interface SiteShopAxis {
  options: ClassificationOption[];
  onClassify: (classificationKeys: string[], value: string) => void;
  exemptValue?: string;
}

function siteShopEligibleKeys(rows: ClassificationRow[], exemptValue?: string): string[] {
  return uniqueClassificationKeys(rows.filter((r) => !exemptValue || r.classification !== exemptValue));
}

// TITAN writes Vendor_Discount against List_Price, and when it has no list price it writes a $0.01
// placeholder instead of nothing. The discount it then derives is arithmetically meaningless - a real
// export carries rows reading -1199%, -1499% and -4199% against a $0.01 list and a $12-42 unit cost -
// and a buyer reading a purchasing grid has to mentally discard them. A discount outside +/-100% is
// not a discount, so it shows as a dash and keeps the raw figure in the title for anyone chasing it.
const DISCOUNT_PLAUSIBLE_PCT = 100;

function formatVendorDiscount(value: number | null | undefined): string {
  if (value == null) return '—';
  return Math.abs(value) > DISCOUNT_PLAUSIBLE_PCT ? '—' : `${value}%`;
}

function formatGroupKey(field: GroupByField, value: unknown): string {
  if (value == null || value === '') return '(None)';
  if (field === 'unitCost' || field === 'listPrice') return `$${Number(value).toFixed(2)}`;
  if (field === 'vendorDiscount') return formatVendorDiscount(Number(value));
  return String(value);
}

function uniqueClassificationKeys(rows: ClassificationRow[]): string[] {
  return Array.from(new Set(rows.map((r) => r.classificationKey)));
}

function buildGroupTree(rows: ClassificationRow[], fields: GroupByField[]): Map<string, GroupNode> | null {
  if (fields.length === 0) return null;
  const [field, ...rest] = fields;
  const map = new Map<string, ClassificationRow[]>();
  for (const row of rows) {
    const key = formatGroupKey(field, row[field]);
    const existing = map.get(key);
    if (existing) {
      existing.push(row);
    } else {
      map.set(key, [row]);
    }
  }
  const sorted = Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  const result = new Map<string, GroupNode>();
  for (const [key, groupRows] of sorted) {
    result.set(key, {
      label: key,
      rows: groupRows,
      children: buildGroupTree(groupRows, rest),
    });
  }
  return result;
}

// #485: every text column was sized by flex alone. Each row also carries two ToggleButtonGroups
// that hold a fixed width, so on a narrow viewport the flex columns were squeezed to ~100px - about
// 12-15 characters - and long product codes, categories and manufacturers were clipped. minWidth
// stops the squeeze and lets the grid scroll horizontally instead; the widths mirror the ones
// SelectOpeningsStep already uses. wrap-cell lets the value break across lines rather than
// ellipsize, and title= puts the full value in a hover tooltip either way.
const ALL_COLUMNS: GridColDef[] = [
  {
    field: 'openingNumber',
    headerName: 'Opening #',
    flex: 0.7,
    minWidth: 110,
    cellClassName: 'mono-cell',
    renderCell: (params) => <span title={String(params.value ?? '')}>{params.value}</span>,
  },
  // #486: fixed small widths - these are short values and the row is already crowded by the two
  // toggle groups, so they must not take room from the text columns (#485).
  { field: 'hand', headerName: 'Hand', width: 70 },
  {
    field: 'doorQuantity',
    headerName: 'Door Qty',
    width: 80,
    type: 'number',
    valueFormatter: (value: number | null) => (value != null ? String(value) : '—'),
  },
  { field: 'doorMaterial', headerName: 'Door Material', width: 120, cellClassName: 'wrap-cell' },
  {
    field: 'productCode',
    headerName: 'Product Code',
    flex: 1,
    minWidth: 140,
    cellClassName: 'wrap-cell mono-cell',
  },
  {
    field: 'hardwareCategory',
    headerName: 'Hardware Category',
    flex: 1,
    minWidth: 150,
    cellClassName: 'wrap-cell',
  },
  {
    field: 'vendorNo',
    headerName: 'Manufacturer',
    flex: 0.8,
    minWidth: 120,
    cellClassName: 'wrap-cell mono-cell',
    renderCell: (params) => <span title={String(params.value ?? '')}>{params.value}</span>,
  },
  {
    field: 'listPrice',
    headerName: 'List Price',
    flex: 0.6,
    type: 'number',
    valueFormatter: (value: number | null) => value != null ? `$${value.toFixed(2)}` : '—',
  },
  {
    field: 'vendorDiscount',
    headerName: 'Discount',
    flex: 0.5,
    type: 'number',
    valueFormatter: (value: number | null) => formatVendorDiscount(value),
    renderCell: (params) => {
      const raw = params.value as number | null;
      const shown = formatVendorDiscount(raw);
      const suppressed = raw != null && shown === '—';
      return <span title={suppressed ? `TITAN reported ${raw}% against a placeholder list price` : undefined}>{shown}</span>;
    },
  },
  {
    field: 'unitCost',
    headerName: 'Unit Cost',
    flex: 0.6,
    type: 'number',
    valueFormatter: (value: number) => `$${value.toFixed(2)}`,
  },
  { field: 'itemQuantity', headerName: 'Qty', flex: 0.4, type: 'number' },
];

function buildOptionLookups(options: ClassificationOption[]) {
  const labelMap: Record<string, string> = {};
  const colorMap: Record<string, 'success' | 'info' | 'warning'> = {};
  for (const opt of options) {
    labelMap[opt.value] = opt.label;
    colorMap[opt.value] = opt.color;
  }
  return { labelMap, colorMap };
}

interface LeafGridProps {
  rows: ClassificationRow[];
  columns: GridColDef[];
  options: ClassificationOption[];
  onClassify: ClassificationGridProps['onClassify'];
  readOnly?: boolean;
  siteShop?: SiteShopAxis;
}

function LeafGrid({ rows, columns, options, onClassify, readOnly, siteShop }: LeafGridProps) {
  const [selectionModel, setSelectionModel] = useState<GridRowSelectionModel>({
    type: 'include',
    ids: new Set(),
  });

  const selectedCount = selectionModel.ids.size;

  const handleBulkClassify = useCallback(
    (value: string) => {
      const selectedRows = rows.filter((r) => selectionModel.ids.has(r.id));
      onClassify(uniqueClassificationKeys(selectedRows), value);
      setSelectionModel({ type: 'include', ids: new Set() });
    },
    [selectionModel, rows, onClassify],
  );

  const handleBulkSiteShop = useCallback(
    (value: string) => {
      if (!siteShop) return;
      const selectedRows = rows.filter((r) => selectionModel.ids.has(r.id));
      siteShop.onClassify(siteShopEligibleKeys(selectedRows, siteShop.exemptValue), value);
      setSelectionModel({ type: 'include', ids: new Set() });
    },
    [selectionModel, rows, siteShop],
  );

  return (
    <DataGrid
      rows={rows}
      columns={columns}
      checkboxSelection={!readOnly}
      density="compact"
      getRowHeight={() => 'auto'}
      hideFooter
      disableRowSelectionOnClick
      rowSelectionModel={selectionModel}
      onRowSelectionModelChange={setSelectionModel}
      // MUI X v8 hides the toolbar slot unless showToolbar is set - without it the bulk-classify
      // toolbar below never rendered, so checkbox selection had no effect.
      showToolbar={!readOnly && selectedCount > 0}
      sx={{
        '& .MuiDataGrid-cell.wrap-cell': {
          whiteSpace: 'normal',
          wordBreak: 'break-word',
          lineHeight: 1.4,
          py: 0.75,
        },
        '& .MuiDataGrid-cell.mono-cell': monoSx,
      }}
      slots={{
        toolbar: !readOnly && selectedCount > 0
          ? () => (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.5, flexWrap: 'wrap' }}>
                <Typography sx={microLabelSx}>{selectedCount} selected</Typography>
                {options.map((opt) => (
                  <Button key={opt.value} size="small" color={opt.color} onClick={() => handleBulkClassify(opt.value)}>
                    Classify as {opt.label}
                  </Button>
                ))}
                {siteShop?.options.map((opt) => (
                  <Button key={opt.value} size="small" color={opt.color} onClick={() => handleBulkSiteShop(opt.value)}>
                    Classify as {opt.label}
                  </Button>
                ))}
              </Box>
            )
          : undefined,
      }}
    />
  );
}

interface GroupAccordionProps {
  node: GroupNode;
  columns: GridColDef[];
  options: ClassificationOption[];
  onClassify: ClassificationGridProps['onClassify'];
  readOnly?: boolean;
  depth: number;
  siteShop?: SiteShopAxis;
}

function GroupAccordion({ node, columns, options, onClassify, readOnly, depth, siteShop }: GroupAccordionProps) {
  const { labelMap, colorMap } = useMemo(() => buildOptionLookups(options), [options]);

  const classifiedCount = node.rows.filter((r) => r.classification !== '').length;
  const uniqueClassifications = new Set(node.rows.filter((r) => r.classification !== '').map((r) => r.classification));
  const allSameClassification = classifiedCount === node.rows.length && uniqueClassifications.size === 1;

  const handleGroupAll = useCallback(
    (value: string, e: React.MouseEvent) => {
      e.stopPropagation();
      onClassify(uniqueClassificationKeys(node.rows), value);
    },
    [node.rows, onClassify],
  );

  const handleGroupAllSiteShop = useCallback(
    (value: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (!siteShop) return;
      siteShop.onClassify(siteShopEligibleKeys(node.rows, siteShop.exemptValue), value);
    },
    [node.rows, siteShop],
  );

  const singleValue = allSameClassification ? [...uniqueClassifications][0] : null;

  return (
    <Accordion
      defaultExpanded={false}
      TransitionProps={{ unmountOnExit: true }}
      sx={{ pl: depth * 2 }}
    >
      <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', mr: 1 }}>
          <Typography
            title={node.label}
            sx={{ fontWeight: 700, ...monoSx, fontSize: '0.875rem', whiteSpace: 'normal', wordBreak: 'break-word' }}
          >
            {node.label}
          </Typography>
          <Chip
            size="small"
            label={
              allSameClassification
                ? `All ${labelMap[singleValue!] ?? singleValue}`
                : `${classifiedCount}/${node.rows.length} classified`
            }
            color={
              allSameClassification
                ? (colorMap[singleValue!] ?? 'default')
                : classifiedCount === node.rows.length ? 'success' : 'default'
            }
          />
          <Typography variant="body2" color="text.secondary">
            ({node.rows.length} {node.rows.length === 1 ? 'item' : 'items'})
          </Typography>
          {!readOnly && (
            <Box sx={{ ml: 'auto', display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
              {options.map((opt) => (
                <Button
                  key={opt.value}
                  size="small"
                  variant="outlined"
                  color={opt.color}
                  onClick={(e) => handleGroupAll(opt.value, e)}
                >
                  {opt.label} All
                </Button>
              ))}
              {siteShop?.options.map((opt) => (
                <Button
                  key={opt.value}
                  size="small"
                  variant="outlined"
                  color={opt.color}
                  onClick={(e) => handleGroupAllSiteShop(opt.value, e)}
                >
                  {opt.label} All
                </Button>
              ))}
            </Box>
          )}
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        {node.children ? (
          Array.from(node.children.values()).map((child) => (
            <GroupAccordion
              key={child.label}
              node={child}
              columns={columns}
              options={options}
              onClassify={onClassify}
              readOnly={readOnly}
              depth={depth + 1}
              siteShop={siteShop}
            />
          ))
        ) : (
          <LeafGrid
            rows={node.rows}
            columns={columns}
            options={options}
            onClassify={onClassify}
            readOnly={readOnly}
            siteShop={siteShop}
          />
        )}
      </AccordionDetails>
    </Accordion>
  );
}

export default function ClassificationGrid({
  rows,
  options,
  onClassify,
  readOnly,
  siteShopOptions,
  onClassifySiteShop,
  siteShopExemptValue,
}: ClassificationGridProps) {
  const { labelMap, colorMap } = useMemo(() => buildOptionLookups(options), [options]);

  const siteShop = useMemo<SiteShopAxis | undefined>(
    () =>
      siteShopOptions && onClassifySiteShop
        ? { options: siteShopOptions, onClassify: onClassifySiteShop, exemptValue: siteShopExemptValue }
        : undefined,
    [siteShopOptions, onClassifySiteShop, siteShopExemptValue],
  );

  const [groupByFields, setGroupByFields] = useState<GroupByField[]>([]);

  const usedFields = useMemo(() => new Set(groupByFields), [groupByFields]);

  const handleAddLevel = useCallback(() => {
    const firstUnused = GROUP_BY_OPTIONS.find((opt) => !usedFields.has(opt.value));
    if (firstUnused) {
      setGroupByFields((prev) => [...prev, firstUnused.value]);
    }
  }, [usedFields]);

  const handleRemoveLevel = useCallback((index: number) => {
    setGroupByFields((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleChangeLevel = useCallback((index: number, value: GroupByField) => {
    setGroupByFields((prev) => prev.map((f, i) => (i === index ? value : f)));
  }, []);

  const groupTree = useMemo(
    () => buildGroupTree(rows, groupByFields),
    [rows, groupByFields],
  );

  const columns: GridColDef[] = useMemo(() => {
    const hiddenFields = new Set(groupByFields);
    const visible = ALL_COLUMNS.filter((col) => !hiddenFields.has(col.field as GroupByField));
    const toggleCell = (
      value: string,
      cellOptions: ClassificationOption[],
      onChange: (newValue: string) => void,
    ) => (
      <ToggleButtonGroup
        size="small"
        exclusive
        value={value || null}
        onChange={(_, newValue) => {
          if (newValue !== null) onChange(newValue);
        }}
        sx={{ height: 28 }}
      >
        {cellOptions.map((opt) => (
          <ToggleButton
            key={opt.value}
            value={opt.value}
            sx={{
              px: 1, fontSize: '0.75rem',
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

    const cols: GridColDef[] = [
      ...visible,
      {
        field: 'classification',
        headerName: 'Classification',
        flex: 1,
        minWidth: 160,
        sortable: false,
        renderCell: (params: GridRenderCellParams) => {
          const value = params.row.classification;
          if (readOnly) {
            if (!value) return <Chip size="small" label="—" />;
            return (
              <Chip
                size="small"
                label={labelMap[value] ?? value}
                color={colorMap[value] ?? 'default'}
              />
            );
          }
          return toggleCell(value, options, (newValue) => onClassify([params.row.classificationKey], newValue));
        },
      },
    ];

    if (siteShop) {
      cols.push({
        field: 'siteShop',
        headerName: 'Site/Shop',
        flex: 0.8,
        minWidth: 120,
        sortable: false,
        renderCell: (params: GridRenderCellParams) => {
          // A By-Others item is out of scope, so it carries no site/shop classification.
          if (siteShop.exemptValue && params.row.classification === siteShop.exemptValue) {
            return <Chip size="small" label="—" />;
          }
          const value = params.row.siteShop ?? '';
          if (readOnly) {
            if (!value) return <Chip size="small" label="—" />;
            const opt = siteShop.options.find((o) => o.value === value);
            return <Chip size="small" label={opt?.label ?? value} color={opt?.color ?? 'default'} />;
          }
          return toggleCell(value, siteShop.options, (newValue) =>
            siteShop.onClassify([params.row.classificationKey], newValue),
          );
        },
      });
    }

    return cols;
  }, [groupByFields, onClassify, readOnly, options, labelMap, colorMap, siteShop]);

  return (
    <Box>
      <Box sx={{ mb: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
        {groupByFields.map((field, index) => (
          <Box key={index} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography sx={{ ...microLabelSx, minWidth: 56 }}>Level {index + 1}</Typography>
            <TextField
              select
              size="small"
              value={field}
              onChange={(e) => handleChangeLevel(index, e.target.value as GroupByField)}
              sx={{ minWidth: 200 }}
            >
              {GROUP_BY_OPTIONS
                .filter((opt) => opt.value === field || !usedFields.has(opt.value))
                .map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
                ))}
            </TextField>
            <IconButton
              size="small"
              aria-label={`Remove group level ${index + 1}`}
              onClick={() => handleRemoveLevel(index)}
            >
              <X size={16} strokeWidth={1.75} />
            </IconButton>
          </Box>
        ))}
        {groupByFields.length < GROUP_BY_OPTIONS.length && (
          <Button
            size="small"
            startIcon={<Plus size={18} strokeWidth={1.75} />}
            onClick={handleAddLevel}
            sx={{ alignSelf: 'flex-start' }}
          >
            Add group level
          </Button>
        )}
      </Box>

      {groupTree ? (
        Array.from(groupTree.values()).map((node) => (
          <GroupAccordion
            key={node.label}
            node={node}
            columns={columns}
            options={options}
            onClassify={onClassify}
            readOnly={readOnly}
            depth={0}
            siteShop={siteShop}
          />
        ))
      ) : (
        <LeafGrid
          rows={rows}
          columns={columns}
          options={options}
          onClassify={onClassify}
          readOnly={readOnly}
          siteShop={siteShop}
        />
      )}
    </Box>
  );
}
