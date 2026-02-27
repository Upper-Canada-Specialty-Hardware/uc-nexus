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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CloseIcon from '@mui/icons-material/Close';
import AddIcon from '@mui/icons-material/Add';
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

interface GroupNode {
  label: string;
  rows: ClassificationRow[];
  children: Map<string, GroupNode> | null;
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

interface LeafGridProps {
  rows: ClassificationRow[];
  columns: GridColDef[];
  onClassify: ClassificationGridProps['onClassify'];
  readOnly?: boolean;
}

function LeafGrid({ rows, columns, onClassify, readOnly }: LeafGridProps) {
  const [selectionModel, setSelectionModel] = useState<GridRowSelectionModel>({
    type: 'include',
    ids: new Set(),
  });

  const selectedCount = selectionModel.ids.size;

  const handleBulkClassify = useCallback(
    (value: 'SITE_HARDWARE' | 'SHOP_HARDWARE') => {
      const selectedRows = rows.filter((r) => selectionModel.ids.has(r.id));
      onClassify(uniqueClassificationKeys(selectedRows), value);
      setSelectionModel({ type: 'include', ids: new Set() });
    },
    [selectionModel, rows, onClassify],
  );

  return (
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
                <Button size="small" color="success" onClick={() => handleBulkClassify('SITE_HARDWARE')}>
                  Classify as Site
                </Button>
                <Button size="small" color="info" onClick={() => handleBulkClassify('SHOP_HARDWARE')}>
                  Classify as Shop
                </Button>
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
  onClassify: ClassificationGridProps['onClassify'];
  readOnly?: boolean;
  depth: number;
}

function GroupAccordion({ node, columns, onClassify, readOnly, depth }: GroupAccordionProps) {
  const classifiedCount = node.rows.filter((r) => r.classification !== '').length;
  const uniqueClassifications = new Set(node.rows.filter((r) => r.classification !== '').map((r) => r.classification));
  const allSameClassification = classifiedCount === node.rows.length && uniqueClassifications.size === 1;

  const handleGroupAll = useCallback(
    (value: 'SITE_HARDWARE' | 'SHOP_HARDWARE', e: React.MouseEvent) => {
      e.stopPropagation();
      onClassify(uniqueClassificationKeys(node.rows), value);
    },
    [node.rows, onClassify],
  );

  return (
    <Accordion
      defaultExpanded={false}
      TransitionProps={{ unmountOnExit: true }}
      sx={{ pl: depth * 2 }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', mr: 1 }}>
          <Typography sx={{ fontWeight: 700 }}>{node.label}</Typography>
          <Chip
            size="small"
            label={
              allSameClassification
                ? `All ${[...uniqueClassifications][0] === 'SITE_HARDWARE' ? 'Site' : 'Shop'}`
                : `${classifiedCount}/${node.rows.length} classified`
            }
            color={
              allSameClassification
                ? ([...uniqueClassifications][0] === 'SITE_HARDWARE' ? 'success' : 'info')
                : classifiedCount === node.rows.length ? 'success' : 'default'
            }
          />
          <Typography variant="body2" color="text.secondary">
            ({node.rows.length} items)
          </Typography>
          {!readOnly && (
            <Box sx={{ ml: 'auto', display: 'flex', gap: 0.5 }}>
              <Button
                size="small"
                variant="outlined"
                color="success"
                onClick={(e) => handleGroupAll('SITE_HARDWARE', e)}
              >
                Site All
              </Button>
              <Button
                size="small"
                variant="outlined"
                color="info"
                onClick={(e) => handleGroupAll('SHOP_HARDWARE', e)}
              >
                Shop All
              </Button>
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
              onClassify={onClassify}
              readOnly={readOnly}
              depth={depth + 1}
            />
          ))
        ) : (
          <LeafGrid rows={node.rows} columns={columns} onClassify={onClassify} readOnly={readOnly} />
        )}
      </AccordionDetails>
    </Accordion>
  );
}

export default function ClassificationGrid({ rows, onClassify, readOnly }: ClassificationGridProps) {
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
              <ToggleButton
                value="SITE_HARDWARE"
                sx={{
                  px: 1, fontSize: '0.75rem',
                  '&.Mui-selected': {
                    backgroundColor: 'success.main',
                    color: 'success.contrastText',
                    '&:hover': { backgroundColor: 'success.dark' },
                  },
                }}
              >
                Site
              </ToggleButton>
              <ToggleButton
                value="SHOP_HARDWARE"
                sx={{
                  px: 1, fontSize: '0.75rem',
                  '&.Mui-selected': {
                    backgroundColor: 'info.main',
                    color: 'info.contrastText',
                    '&:hover': { backgroundColor: 'info.dark' },
                  },
                }}
              >
                Shop
              </ToggleButton>
            </ToggleButtonGroup>
          );
        },
      },
    ];
  }, [groupByFields, onClassify, readOnly]);

  return (
    <Box>
      <Box sx={{ mb: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
        {groupByFields.map((field, index) => (
          <Box key={index} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="body2" color="text.secondary" sx={{ minWidth: 56 }}>
              Level {index + 1}:
            </Typography>
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
            <IconButton size="small" onClick={() => handleRemoveLevel(index)}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>
        ))}
        {groupByFields.length < GROUP_BY_OPTIONS.length && (
          <Button
            size="small"
            startIcon={<AddIcon />}
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
            onClassify={onClassify}
            readOnly={readOnly}
            depth={0}
          />
        ))
      ) : (
        <LeafGrid rows={rows} columns={columns} onClassify={onClassify} readOnly={readOnly} />
      )}
    </Box>
  );
}
