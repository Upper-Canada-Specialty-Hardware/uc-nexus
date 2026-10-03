import { useMemo, useState, useEffect } from 'react';
import {
  Drawer,
  Box,
  Button,
  Typography,
  IconButton,
  CircularProgress,
  Alert,
  Chip,
  Divider,
} from '@mui/material';
import { X } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { GET_AUDIT_LOG, GET_WAREHOUSES } from '../../graphql/shared';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

interface AuditLogEntry {
  id: string;
  projectId: string | null;
  entityType: string;
  entityId: string;
  action: string;
  detail: Record<string, unknown> | null;
  performedBy: string;
  createdAt: string;
}

interface AuditHistoryDrawerProps {
  open: boolean;
  onClose: () => void;
  entityId: string;
  entityType: 'INVENTORY_LOCATION' | 'OPENING_ITEM' | 'STOCK_ITEM';
  label?: string;
}

const ACTION_COLORS: Record<string, 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info'> = {
  RECEIVE: 'success',
  ADJUSTMENT: 'warning',
  MOVE: 'info',
  UNLOCATE: 'secondary',
  PUT_AWAY: 'primary',
  PULL_DEDUCTION: 'error',
  SPOT_CHECK: 'warning',
  DESTOCK: 'secondary',
  ALLOCATE_FROM_STOCK: 'primary',
  RECLASSIFY: 'info',
  REPORT_DEFICIENT: 'error',
  RESOLVE_DEFICIENT: 'success',
  TRANSFER: 'info',
  RETURN: 'success',
  PULL_RESTOCK: 'success',
  PULL_CANCELLED: 'error',
  POOL_KIND_CHANGE: 'secondary',
};

const ACTION_LABELS: Record<string, string> = {
  RECEIVE: 'Received',
  ADJUSTMENT: 'Qty Adjusted',
  MOVE: 'Moved',
  UNLOCATE: 'Unlocated',
  PUT_AWAY: 'Put Away',
  PULL_DEDUCTION: 'Pull Deduction',
  SPOT_CHECK: 'Spot Check',
  DESTOCK: 'Destocked',
  ALLOCATE_FROM_STOCK: 'Allocated from Stock',
  RECLASSIFY: 'Reclassified',
  REPORT_DEFICIENT: 'Reported Deficient',
  RESOLVE_DEFICIENT: 'Deficiency Resolved',
  TRANSFER: 'Transferred',
  RETURN: 'Returned',
  PULL_RESTOCK: 'Pull Restocked',
  PULL_CANCELLED: 'Pull Cancelled',
  POOL_KIND_CHANGE: 'Kind Changed',
};

// #974: the words each detail value is shown in, where the stored value is a code.
const DESTOCK_COST_LABELS: Record<string, string> = { ZERO: 'Left behind - $0', KEEP: 'Keeps its cost' };
const RESOLUTION_LABELS: Record<string, string> = {
  SEND_TO_STOCK: 'Sent to stock',
  SCRAP: 'Scrapped',
  REPAIR: 'Repaired',
  RETURN_TO_VENDOR: 'Returned to vendor',
  LEAVE_AS_DEFICIENT: 'Left as deficient',
};
const DISPOSITION_LABELS: Record<string, string> = {
  RETURN_TO_PROJECT: 'Back to project',
  NON_STOCK: 'To stock pool',
  RMA_DEFECTIVE: 'Defective (RMA)',
};
const KIND_LABELS: Record<string, string> = { STOCK: 'Stock', OVERHEAD: 'Overhead' };

/** A category / product pair as the reclassify and allocate details store it. */
function formatProduct(p: unknown): string {
  const { hardwareCategory, productCode } = (p ?? {}) as { hardwareCategory?: string; productCode?: string };
  return [hardwareCategory, productCode].filter(Boolean).join(' / ') || '—';
}

/** A coded value in its words, or the code itself when no word is known for it. */
function labelled(labels: Record<string, string>, code: unknown): string {
  const key = String(code ?? '');
  return labels[key] ?? (key || '—');
}

function formatDateTime(dateStr: string): string {
  return parseServerDate(dateStr).toLocaleString();
}

function formatLocation(loc: Record<string, unknown> | null | undefined): string {
  if (!loc) return '—';
  const { aisle, row, bay } = loc as { aisle?: string; row?: string; bay?: string };
  if (aisle && row && bay) return `${aisle}-${row}-${bay}`;
  return 'Unlocated';
}

function DetailLine({ label, value }: { label: string; value: string | number }) {
  return (
    <Typography variant="body2" color="text.secondary">
      {label}:{' '}
      <Typography component="span" color="text.primary" sx={monoSx}>
        {value}
      </Typography>
    </Typography>
  );
}

function AuditEntry({ entry, warehouseCodes }: { entry: AuditLogEntry; warehouseCodes: Map<string, string> }) {
  const detail = entry.detail ?? {};
  const text = (key: string): string | null => (detail[key] ? String(detail[key]) : null);
  // A location with the building it is in, for the events that can cross warehouses (#974).
  const place = (loc: unknown, warehouseId?: unknown) => {
    const id = warehouseId ?? (loc as { warehouseId?: string } | null)?.warehouseId;
    const code = id ? warehouseCodes.get(String(id)) : undefined;
    const where = formatLocation(loc as Record<string, unknown> | null);
    return code ? `${code} ${where}` : where;
  };
  const reason = text('reasonText');

  const renderDetail = () => {
    switch (entry.action) {
      case 'ADJUSTMENT':
        return (
          <>
            <DetailLine label="Qty" value={`${detail.oldQuantity} → ${detail.newQuantity} (${(detail.adjustment as number) > 0 ? '+' : ''}${detail.adjustment})`} />
            {detail.reason && <DetailLine label="Reason" value={detail.reason as string} />}
          </>
        );
      case 'SPOT_CHECK': {
        // A spot check carries the counted-vs-system pair; fall back to the adjustment quantities on
        // an older row that predates those keys.
        const system = detail.systemQuantity ?? detail.oldQuantity;
        const physical = detail.physicalQuantity ?? detail.newQuantity;
        const delta = (physical as number) - (system as number);
        // The modal writes a machine reason that restates this same pair ("Spot check: system=X,
        // physical=Y") - suppress it rather than print the Count line twice. A human note survives.
        const reason = detail.reason as string | undefined;
        const humanReason = reason && !reason.startsWith('Spot check: system=') ? reason : null;
        return (
          <>
            <DetailLine
              label="Count"
              value={`system ${system} → physical ${physical} (${delta > 0 ? '+' : ''}${delta})`}
            />
            {humanReason && <DetailLine label="Reason" value={humanReason} />}
          </>
        );
      }
      case 'MOVE':
        return (
          <DetailLine
            label="Location"
            value={`${formatLocation(detail.fromLocation as Record<string, unknown>)} → ${formatLocation(detail.toLocation as Record<string, unknown>)}`}
          />
        );
      case 'UNLOCATE':
        return (
          <DetailLine label="From" value={formatLocation(detail.fromLocation as Record<string, unknown>)} />
        );
      case 'PUT_AWAY':
        return (
          <DetailLine label="To" value={formatLocation(detail.toLocation as Record<string, unknown>)} />
        );
      case 'RECEIVE':
        return (
          <>
            <DetailLine label="Qty" value={detail.quantity as number} />
            {detail.poNumber && <DetailLine label="PO" value={detail.poNumber as string} />}
            <DetailLine label="Location" value={formatLocation(detail.location as Record<string, unknown>)} />
          </>
        );
      case 'PULL_DEDUCTION':
        return (
          <>
            <DetailLine label="Qty" value={`${detail.oldQuantity} → ${detail.newQuantity} (-${detail.deducted})`} />
            {detail.pullRequestNumber && <DetailLine label="PR" value={detail.pullRequestNumber as string} />}
          </>
        );
      // #974: every other stock and inventory event shows its quantity and what decided it.
      case 'DESTOCK':
        return (
          <>
            <DetailLine label="Qty" value={detail.quantity as number} />
            {text('destockCost') && <DetailLine label="Cost" value={labelled(DESTOCK_COST_LABELS, detail.destockCost)} />}
            <DetailLine label="To stock" value={place(detail.targetLocation)} />
            {reason && <DetailLine label="Reason" value={reason} />}
          </>
        );
      case 'ALLOCATE_FROM_STOCK':
        return (
          <>
            <DetailLine label="Qty" value={detail.quantity as number} />
            <DetailLine
              label="As"
              value={formatProduct({ hardwareCategory: detail.targetHardwareCategory, productCode: detail.targetProductCode })}
            />
            <DetailLine label="To" value={place(detail.targetLocation)} />
          </>
        );
      case 'RECLASSIFY':
        return (
          <>
            {detail.quantity != null && <DetailLine label="Qty" value={detail.quantity as number} />}
            <DetailLine label="Product" value={`${formatProduct(detail.from)} → ${formatProduct(detail.to)}`} />
            {reason && <DetailLine label="Reason" value={reason} />}
          </>
        );
      case 'REPORT_DEFICIENT':
        return (
          <>
            <DetailLine label="Qty" value={detail.quantity as number} />
            {reason && <DetailLine label="Reason" value={reason} />}
          </>
        );
      case 'RESOLVE_DEFICIENT':
        return (
          <>
            <DetailLine label="Qty" value={detail.quantity as number} />
            <DetailLine label="Resolution" value={labelled(RESOLUTION_LABELS, detail.resolution)} />
            {text('destockCost') && <DetailLine label="Cost" value={labelled(DESTOCK_COST_LABELS, detail.destockCost)} />}
            {text('rmaReference') && <DetailLine label="RMA" value={text('rmaReference')!} />}
            {reason && <DetailLine label="Reason" value={reason} />}
          </>
        );
      case 'TRANSFER':
        return (
          <>
            <DetailLine label="Qty" value={detail.quantity as number} />
            <DetailLine
              label="Location"
              value={`${place(detail.fromLocation, detail.fromWarehouseId)} → ${place(detail.toLocation, detail.toWarehouseId)}`}
            />
          </>
        );
      case 'RETURN':
        return (
          <>
            <DetailLine label="Qty" value={detail.quantity as number} />
            <DetailLine label="Disposition" value={labelled(DISPOSITION_LABELS, detail.disposition)} />
            {text('packingSlipNumber') && <DetailLine label="Packing slip" value={text('packingSlipNumber')!} />}
            {text('rmaReference') && <DetailLine label="RMA" value={text('rmaReference')!} />}
          </>
        );
      case 'PULL_RESTOCK':
        return (
          <>
            {detail.restockedQuantity != null && <DetailLine label="Qty" value={detail.restockedQuantity as number} />}
            {text('pullRequestNumber') && <DetailLine label="PR" value={text('pullRequestNumber')!} />}
            {reason && <DetailLine label="Reason" value={reason} />}
          </>
        );
      case 'PULL_CANCELLED':
        return (
          <>
            {text('pullRequestNumber') && <DetailLine label="PR" value={text('pullRequestNumber')!} />}
            {reason && <DetailLine label="Reason" value={reason} />}
          </>
        );
      case 'POOL_KIND_CHANGE':
        return (
          <>
            {detail.quantity != null && <DetailLine label="Qty" value={detail.quantity as number} />}
            <DetailLine
              label="Kind"
              value={`${labelled(KIND_LABELS, detail.fromKind)} → ${labelled(KIND_LABELS, detail.toKind)}`}
            />
          </>
        );
      default:
        return null;
    }
  };

  return (
    <Box sx={{ py: 1.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
        <Chip
          label={ACTION_LABELS[entry.action] ?? entry.action}
          color={ACTION_COLORS[entry.action] ?? 'default'}
          size="small"
          variant="outlined"
        />
        <Typography variant="caption" color="text.secondary" sx={tabularSx}>
          {formatDateTime(entry.createdAt)}
        </Typography>
      </Box>
      <Box sx={{ ml: 0.5 }}>
        {renderDetail()}
        <Typography variant="caption" color="text.secondary">
          by {entry.performedBy}
        </Typography>
      </Box>
    </Box>
  );
}

const PAGE_SIZE = 50;

export default function AuditHistoryDrawer({
  open,
  onClose,
  entityId,
  entityType,
  label,
}: AuditHistoryDrawerProps) {
  const { data, loading, error, fetchMore } = useQuery<{ auditLog: AuditLogEntry[] }>(GET_AUDIT_LOG, {
    variables: { entityId, entityType, limit: PAGE_SIZE, offset: 0 },
    skip: !open,
    fetchPolicy: 'network-only',
  });

  const entries = useMemo(() => data?.auditLog ?? [], [data]);

  // Warehouse codes for the events that name a building (#974). Inactive ones too: history outlives
  // a warehouse being retired.
  const { data: warehousesData } = useQuery<{ warehouses: { id: string; code: string }[] }>(GET_WAREHOUSES, {
    variables: { includeInactive: true },
    skip: !open,
  });
  const warehouseCodes = useMemo(
    () => new Map((warehousesData?.warehouses ?? []).map((w) => [w.id, w.code])),
    [warehousesData],
  );

  // The base query refetches page 0 (network-only) whenever the drawer reopens or the entity
  // changes, so the "no more rows" flag has to reset alongside it.
  const [reachedEnd, setReachedEnd] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset pagination when the entity or open state changes
    setReachedEnd(false);
  }, [entityId, entityType, open]);

  const hasMore = !reachedEnd && entries.length >= PAGE_SIZE;

  const handleLoadMore = async () => {
    setLoadingMore(true);
    try {
      // Keyset, not offset (#1269): "older than the last entry shown" survives a new entry landing
      // between pages, where an offset would repeat a row.
      const res = await fetchMore({
        variables: { offset: 0, beforeId: entries[entries.length - 1]?.id },
        updateQuery: (prev, { fetchMoreResult }) => ({
          auditLog: [...(prev.auditLog ?? []), ...(fetchMoreResult?.auditLog ?? [])],
        }),
      });
      if ((res.data?.auditLog?.length ?? 0) < PAGE_SIZE) setReachedEnd(true);
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: 400, maxWidth: '90vw' } }}>
      <Box sx={{ p: 2 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            mb: 1.5,
            pb: 0.75,
            borderBottom: '2px solid',
            borderColor: 'text.primary',
          }}
        >
          <Typography component="div" sx={microLabelSx}>
            Audit History
          </Typography>
          <IconButton onClick={onClose} size="small" aria-label="Close audit history">
            <X size={18} strokeWidth={1.75} />
          </IconButton>
        </Box>
        {label && (
          <Typography sx={{ ...monoSx, color: 'text.secondary', mb: 2 }}>{label}</Typography>
        )}

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        )}
        {error && <Alert severity="error">Error loading audit log: {error.message}</Alert>}
        {!loading && !error && entries.length === 0 && (
          <Alert severity="info">No audit history for this item</Alert>
        )}
        {!loading && entries.length > 0 && (
          <Box>
            {entries.map((entry, i) => (
              <Box key={entry.id}>
                <AuditEntry entry={entry} warehouseCodes={warehouseCodes} />
                {i < entries.length - 1 && <Divider />}
              </Box>
            ))}
            {hasMore && (
              <Box sx={{ display: 'flex', justifyContent: 'center', pt: 1.5 }}>
                <Button size="small" onClick={handleLoadMore} disabled={loadingMore}>
                  {loadingMore ? 'Loading…' : 'Load more'}
                </Button>
              </Box>
            )}
          </Box>
        )}
      </Box>
    </Drawer>
  );
}
