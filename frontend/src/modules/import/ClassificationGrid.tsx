import { useState, useMemo, useCallback } from 'react';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Button,
  Chip,
  MenuItem,
  TextField,
  Typography,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  DataGrid,
  type GridColDef,
  type GridRowSelectionModel,
  type GridRenderCellParams,
} from '@mui/x-data-grid';

export interface ClassificationRow {
  id: string;
  openingNumber: string;
  productCode: string;
  hardwareCategory: string;
  vendorNo: string;
  listPrice: number | null;
  vendorDiscount: number | null;
  unitCost: number;
  itemQuantity: number;
  classificationKey: string;
  classification: string;
}

export type GroupByField = 'hardwareCategory' | 'vendorNo' | 'productCode' | 'openingNumber'
  | 'unitCost' | 'listPrice' | 'vendorDiscount' | 'itemQuantity';

const GROUP_BY_OPTIONS: { value: GroupByField; label: string }[] = [
  { value: 'hardwareCategory', label: 'Hardware Category' },
  { value: 'vendorNo', label: 'Vendor' },
  { value: 'productCode', label: 'Product Code' },
  { value: 'openingNumber', label: 'Opening Number' },
  { value: 'unitCost', label: 'Unit Cost' },
  { value: 'listPrice', label: 'List Price' },
  { value: 'vendorDiscount', label: 'Vendor Discount' },
  { value: 'itemQuantity', label: 'Item Quantity' },
];

interface ClassificationGridProps {
  rows: ClassificationRow[];
  onClassify: (classificationKeys: string[], value: 'SITE_HARDWARE' | 'SHOP_HARDWARE') => void;
  readOnly?: boolean;
}

interface CategoryGridProps {
  groupLabel: string;
  rows: ClassificationRow[];
  columns: GridColDef[];
  onClassify: ClassificationGridProps['onClassify'];
  readOnly?: boolean;
}

function formatGroupKey(field: GroupByField, value: unknown): string {
  if (value == null || value === '') return '(None)';
  if (field === 'unitCost' || field === 'listPrice') return `$${Number(value).toFixed(2)}`;
  if (field === 'vendorDiscount') return `${Number(value)}%`;
  return String(value);
}

function uniqueClassificationKeys(rows: ClassificationRow[]): string[] {
  return Array.from(new Set(rows.map((r) => r.classificationKey)));
}

function CategoryGrid({ groupLabel, rows, columns, onClassify, readOnly }: CategoryGridProps) {
  const [selectionModel, setSelectionModel] = useState<GridRowSelectionModel>({
    type: 'include',
    ids: new Set(),
  });

  const selectedCount = selectionModel.ids.size;
  const classifiedCount = rows.filter((r) => r.classification !== '').length;

  const handleBulkClassify = useCallback(
    (value: 'SITE_HARDWARE' | 'SHOP_HARDWARE') => {
      const selectedRows = rows.filter((r) => selectionModel.ids.has(r.id));
      onClassify(uniqueClassificationKeys(selectedRows), value);
      setSelectionModel({ type: 'include', ids: new Set() });
    },
    [selectionModel, rows, onClassify],
  );

  const handleGroupAll = useCallback(
    (value: 'SITE_HARDWARE' | 'SHOP_HARDWARE', e: React.MouseEvent) => {
      e.stopPropagation();
      onClassify(uniqueClassificationKeys(rows), value);
    },
    [rows, onClassify],
  );

  return (
    <Accordion
      defaultExpanded={false}
      TransitionProps={{ unmountOnExit: true }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', mr: 1 }}>
          <Typography sx={{ fontWeight: 700 }}>{groupLabel}</Typography>
          <Chip
            size="small"
            label={`${classifiedCount}/${rows.length} classified`}
            color={classifiedCount === rows.length ? 'success' : 'default'}
          />
          <Typography variant="body2" color="text.secondary">
            ({rows.length} items)
          </Typography>
          {!readOnly && (
            <Box sx={{ ml: 'auto', display: 'flex', gap: 0.5 }}>
              <Button
                size="small"
                variant="outlined"
                onClick={(e) => handleGroupAll('SITE_HARDWARE', e)}
              >
                Site All
              </Button>
              <Button
                size="small"
                variant="outlined"
                onClick={(e) => handleGroupAll('SHOP_HARDWARE', e)}
              >
                Shop All
              </Button>
            </Box>
          )}
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <DataGrid
          rows={rows}
          columns={columns}
          checkboxSelection={!readOnly}
          density="compact"
          rowHeight={42}
          hideFooter
          disableRowSelectionOnClick
          rowSelectionModel={selectionModel}
          onRowSelectionModelChange={setSelectionModel}
          slots={{
            toolbar: !readOnly && selectedCount > 0
              ? () => (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.5 }}>
                    <Typography variant="body2">{selectedCount} selected</Typography>
                    <Button size="small" onClick={() => handleBulkClassify('SITE_HARDWARE')}>
                      Classify as Site
                    </Button>
                    <Button size="small" onClick={() => handleBulkClassify('SHOP_HARDWARE')}>
                      Classify as Shop
                    </Button>
                  </Box>
                )
              : undefined,
          }}
        />
      </AccordionDetails>
    </Accordion>
  );
}

const ALL_COLUMNS: GridColDef[] = [
  { field: 'openingNumber', headerName: 'Opening #', flex: 0.7 },
  { field: 'productCode', headerName: 'Product Code', flex: 1 },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1 },
  { field: 'vendorNo', headerName: 'Vendor', flex: 0.8 },
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
    valueFormatter: (value: number | null) => value != null ? `${value}%` : '—',
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

// Map GroupByField to the DataGrid field name to hide when grouping
const GROUP_FIELD_MAP: Record<GroupByField, string> = {
  hardwareCategory: 'hardwareCategory',
  vendorNo: 'vendorNo',
  productCode: 'productCode',
  openingNumber: 'openingNumber',
  unitCost: 'unitCost',
  listPrice: 'listPrice',
  vendorDiscount: 'vendorDiscount',
  itemQuantity: 'itemQuantity',
};

export default function ClassificationGrid({ rows, onClassify, readOnly }: ClassificationGridProps) {
  const [groupByField, setGroupByField] = useState<GroupByField>('hardwareCategory');

  const grouped = useMemo(() => {
    const map = new Map<string, ClassificationRow[]>();
    for (const row of rows) {
      const rawValue = row[groupByField];
      const key = formatGroupKey(groupByField, rawValue);
      const existing = map.get(key);
      if (existing) {
        existing.push(row);
      } else {
        map.set(key, [row]);
      }
    }
    return new Map(
      Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b)),
    );
  }, [rows, groupByField]);

  // Build columns: hide the grouped-by field, append classification column
  const columns: GridColDef[] = useMemo(() => {
    const hiddenField = GROUP_FIELD_MAP[groupByField];
    const visible = ALL_COLUMNS.filter((col) => col.field !== hiddenField);
    return [
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
                label={value === 'SITE_HARDWARE' ? 'Site' : 'Shop'}
                color={value === 'SITE_HARDWARE' ? 'success' : 'info'}
              />
            );
          }
          return (
            <ToggleButtonGroup
              size="small"
              exclusive
              value={value || null}
              onChange={(_, newValue) => {
                if (newValue !== null) {
                  onClassify([params.row.classificationKey], newValue);
                }
              }}
              sx={{ height: 28 }}
            >
              <ToggleButton value="SITE_HARDWARE" sx={{ px: 1, fontSize: '0.75rem' }}>
                Site
              </ToggleButton>
              <ToggleButton value="SHOP_HARDWARE" sx={{ px: 1, fontSize: '0.75rem' }}>
                Shop
              </ToggleButton>
            </ToggleButtonGroup>
          );
        },
      },
    ];
  }, [groupByField, onClassify, readOnly]);

  return (
    <Box>
      <Box sx={{ mb: 2 }}>
        <TextField
          select
          size="small"
          label="Group by"
          value={groupByField}
          onChange={(e) => setGroupByField(e.target.value as GroupByField)}
          sx={{ minWidth: 200 }}
        >
          {GROUP_BY_OPTIONS.map((opt) => (
            <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
          ))}
        </TextField>
      </Box>
      {Array.from(grouped.entries()).map(([groupKey, groupRows]) => (
        <CategoryGrid
          key={groupKey}
          groupLabel={groupKey}
          rows={groupRows}
          columns={columns}
          onClassify={onClassify}
          readOnly={readOnly}
        />
      ))}
    </Box>
  );
}
