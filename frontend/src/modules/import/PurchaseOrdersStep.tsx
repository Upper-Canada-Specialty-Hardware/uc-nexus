import { useMemo, useState } from 'react';
import { Box, Button, Typography } from '@mui/material';
import { Plus } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { GET_GP_COST_CODES } from '../../graphql/po';
import { useRelayStatus } from '../../relay/useRelayStatus';
import { tabularSx } from '../../theme';
import { StaggerItem, StaggerList } from '../../motion';
import type { DraftGroup } from './types';
import { DraftCard, SplitLineDialog, type GpCostCode, type ProductMeta, type SplitContext } from './DraftOrganizer';

// ---- Props ----

interface PurchaseOrdersStepProps {
  /** The wizard's project - order-as memory is scoped to it (#509). */
  projectId: string;
  /** The GP job number (#490). Cost codes are per job, so the live list is keyed on it. */
  jobNumber: string | null;
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
}

// ---- Component ----

export default function PurchaseOrdersStep({
  projectId,
  jobNumber,
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
}: PurchaseOrdersStepProps) {
  // #490: one job, so one cost-code read for the whole step rather than one per card. Relay down or
  // job absent -> empty list -> the cards render no cost-code field, and the code is picked at GP
  // registration as before.
  const relay = useRelayStatus({});
  const company = relay.company ?? '';
  const { data: costCodesData } = useQuery<{ gpCostCodes: GpCostCode[] }>(GET_GP_COST_CODES, {
    variables: { company, job: jobNumber ?? '' },
    skip: relay.connected !== true || !company || !jobNumber,
    fetchPolicy: 'cache-first',
  });
  const costCodes = useMemo(() => costCodesData?.gpCostCodes ?? [], [costCodesData]);

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
