import { useState, useMemo, useCallback } from 'react';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Button,
  Chip,
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
  hardwareCategory: string;
  productCode: string;
  unitCost: number;
  itemCount: number;
  totalQuantity: number;
  classification: string;
}

interface ClassificationGridProps {
  rows: ClassificationRow[];
  onClassify: (keys: string[], value: 'SITE_HARDWARE' | 'SHOP_HARDWARE') => void;
}

interface CategoryGridProps {
  category: string;
  rows: ClassificationRow[];
  columns: GridColDef[];
  onClassify: ClassificationGridProps['onClassify'];
}

function CategoryGrid({ category, rows, columns, onClassify }: CategoryGridProps) {
  const [selectionModel, setSelectionModel] = useState<GridRowSelectionModel>({
    type: 'include',
    ids: new Set(),
  });

  const selectedCount = selectionModel.ids.size;

  const classifiedCount = rows.filter((r) => r.classification !== '').length;

  const handleBulkClassify = useCallback(
    (value: 'SITE_HARDWARE' | 'SHOP_HARDWARE') => {
      const keys = Array.from(selectionModel.ids) as string[];
      onClassify(keys, value);
      setSelectionModel({ type: 'include', ids: new Set() });
    },
    [selectionModel, onClassify],
  );

  const handleCategoryAll = useCallback(
    (value: 'SITE_HARDWARE' | 'SHOP_HARDWARE', e: React.MouseEvent) => {
      e.stopPropagation();
      onClassify(rows.map((r) => r.id), value);
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
          <Typography sx={{ fontWeight: 700 }}>{category}</Typography>
          <Chip
            size="small"
            label={`${classifiedCount}/${rows.length} classified`}
            color={classifiedCount === rows.length ? 'success' : 'default'}
          />
          <Box sx={{ ml: 'auto', display: 'flex', gap: 0.5 }}>
            <Button
              size="small"
              variant="outlined"
              onClick={(e) => handleCategoryAll('SITE_HARDWARE', e)}
            >
              Site All
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={(e) => handleCategoryAll('SHOP_HARDWARE', e)}
            >
              Shop All
            </Button>
          </Box>
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <DataGrid
          rows={rows}
          columns={columns}
          checkboxSelection
          density="compact"
          rowHeight={42}
          hideFooter
          disableRowSelectionOnClick
          rowSelectionModel={selectionModel}
          onRowSelectionModelChange={setSelectionModel}
          slots={{
            toolbar: selectedCount > 0
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

export default function ClassificationGrid({ rows, onClassify }: ClassificationGridProps) {
  const grouped = useMemo(() => {
    const map = new Map<string, ClassificationRow[]>();
    for (const row of rows) {
      const existing = map.get(row.hardwareCategory);
      if (existing) {
        existing.push(row);
      } else {
        map.set(row.hardwareCategory, [row]);
      }
    }
    return new Map(
      Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b)),
    );
  }, [rows]);

  const columns: GridColDef[] = useMemo(
    () => [
      { field: 'productCode', headerName: 'Product Code', flex: 1 },
      {
        field: 'unitCost',
        headerName: 'Unit Cost',
        flex: 0.6,
        valueFormatter: (value: number) => `$${value.toFixed(2)}`,
      },
      { field: 'itemCount', headerName: '# Items', flex: 0.5, type: 'number' },
      { field: 'totalQuantity', headerName: 'Total Qty', flex: 0.5, type: 'number' },
      {
        field: 'classification',
        headerName: 'Classification',
        flex: 1,
        minWidth: 160,
        renderCell: (params: GridRenderCellParams) => (
          <ToggleButtonGroup
            size="small"
            exclusive
            value={params.row.classification || null}
            onChange={(_, newValue) => {
              if (newValue !== null) {
                onClassify([params.row.id], newValue);
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
        ),
      },
    ],
    [onClassify],
  );

  return (
    <Box>
      {Array.from(grouped.entries()).map(([category, categoryRows]) => (
        <CategoryGrid
          key={category}
          category={category}
          rows={categoryRows}
          columns={columns}
          onClassify={onClassify}
        />
      ))}
    </Box>
  );
}
