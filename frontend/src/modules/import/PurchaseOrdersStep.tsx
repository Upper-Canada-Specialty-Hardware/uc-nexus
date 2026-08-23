import { useMemo, useState } from 'react';
import { Alert, Box, Button, Typography } from '@mui/material';
import { Plus } from 'lucide-react';
import { tabularSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';
import type { DraftAttachmentType, DraftGroup } from './types';
import { DraftCard, SplitLineDialog, type GpCostCode, type ProductMeta, type SplitContext } from './DraftOrganizer';

// ---- Props ----

interface PurchaseOrdersStepProps {
  /** The wizard's project - order-as memory is scoped to it (#509). */
  projectId: string;
  /** #490/#627: the GP job's cost codes, read once by the wizard and passed down. When non-empty a
   *  cost code is required on each included draft; empty means the code is picked at GP registration. */
  costCodes: GpCostCode[];
  /** #627: why the cost-code list is unavailable, or null when it loaded. When set, the step shows a
   *  warning that a draft can be created without a code and that it is still required at registration. */
  costCodeWaiverReason: string | null;
  /** #570: the PO drafts the buyer is slicing, owned by the wizard. */
  draftGroups: DraftGroup[];
  /** Per-productKey display metadata (product code, category, base unit cost) for the draft ledgers. */
  productCatalog: Map<string, ProductMeta>;
  unitCostOverrides: Map<string, number>;
  orderAsValues: Map<string, string>;
  onToggleIncluded: (id: string) => void;
  onRenameDraft: (id: string, label: string) => void;
  onUpdateDraftInfo: (id: string, field: 'notes' | 'preferredDeliveryDate' | 'costCode', value: string) => void;
  onUpdateUnitCost: (pk: string, value: number) => void;
  onUpdateOrderAs: (pk: string, value: string) => void;
  onMoveLine: (fromId: string, pk: string, qty: number, toId: string) => void;
  onCreateDraft: () => void;
  onMergeDraft: (fromId: string, intoId: string) => void;
  onRemoveDraft: (id: string) => void;
  // #588: draft-level document pre-attach.
  onAddAttachments: (id: string, files: File[]) => void;
  onSetAttachmentType: (id: string, attachmentId: string, documentType: DraftAttachmentType) => void;
  onRemoveAttachment: (id: string, attachmentId: string) => void;
}

// ---- Component ----

export default function PurchaseOrdersStep({
  projectId,
  costCodes,
  costCodeWaiverReason,
  draftGroups,
  productCatalog,
  unitCostOverrides,
  orderAsValues,
  onToggleIncluded,
  onRenameDraft,
  onUpdateDraftInfo,
  onUpdateUnitCost,
  onUpdateOrderAs,
  onMoveLine,
  onCreateDraft,
  onMergeDraft,
  onRemoveDraft,
  onAddAttachments,
  onSetAttachmentType,
  onRemoveAttachment,
}: PurchaseOrdersStepProps) {
  // The split dialog is a single instance driven by the card that opened it.
  const [splitCtx, setSplitCtx] = useState<SplitContext | null>(null);
  const splitTargets = useMemo(
    () =>
      splitCtx
        ? draftGroups.filter((g) => g.id !== splitCtx.fromId).map((g) => ({ id: g.id, label: g.label }))
        : [],
    [draftGroups, splitCtx],
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 2, mb: 3 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Purchase Orders
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={tabularSx}>
            {draftGroups.length} draft(s), seeded one per manufacturer. Move lines between drafts, split a
            line's quantity, and check the ones to order. The GP vendor and PO number are chosen later at
            registration in Microsoft GP.
          </Typography>
        </Box>
        <Button variant="outlined" startIcon={<Plus size={16} strokeWidth={1.75} />} onClick={onCreateDraft} sx={{ flexShrink: 0 }}>
          New PO draft
        </Button>
      </Box>

      {/* #627: cost codes could not load, so the required-cost-code gate is waived. Say why, and that
          the code is still required when the PO is registered in GP. */}
      {costCodeWaiverReason && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          Cost codes are unavailable ({costCodeWaiverReason}), so a PO draft can be created without one.
          The cost code will still be required when the PO is registered in GP.
        </Alert>
      )}

      <StaggerList count={draftGroups.length}>
        {draftGroups.map((draft) => (
          <StaggerItem key={draft.id}>
            <DraftCard
              projectId={projectId}
              draft={draft}
              otherDrafts={draftGroups
                .filter((g) => g.id !== draft.id)
                .map((g) => ({ id: g.id, label: g.label }))}
              productCatalog={productCatalog}
              costCodes={costCodes}
              unitCostOverrides={unitCostOverrides}
              orderAsValues={orderAsValues}
              onToggleIncluded={onToggleIncluded}
              onRenameDraft={onRenameDraft}
              onUpdateDraftInfo={onUpdateDraftInfo}
              onUpdateUnitCost={onUpdateUnitCost}
              onUpdateOrderAs={onUpdateOrderAs}
              onMoveLine={onMoveLine}
              onMergeDraft={onMergeDraft}
              onRemoveDraft={onRemoveDraft}
              onOpenSplit={setSplitCtx}
              onAddAttachments={onAddAttachments}
              onSetAttachmentType={onSetAttachmentType}
              onRemoveAttachment={onRemoveAttachment}
            />
          </StaggerItem>
        ))}
      </StaggerList>

      <SplitLineDialog
        ctx={splitCtx}
        targets={splitTargets}
        onClose={() => setSplitCtx(null)}
        onConfirm={onMoveLine}
      />
    </Box>
  );
}
