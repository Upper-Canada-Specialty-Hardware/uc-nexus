// Shared readings of the derived shop-assembly pipeline stage (#344), so the request list, the
// detail ladder and the tests cannot drift apart. Change the wording here, not in each view.
//
// The backend derives the stage; nothing here re-derives it. These functions only decide how a stage
// is *shown*, which is a presentation decision and belongs on this side.

/** The ladder, in order. Mirrors `PIPELINE_STAGE_RANK` in the backend repository - the two are pinned
 * together by a backend test that asserts the enum and the rank table hold the same values. */
export const PIPELINE_STAGES = [
  'REQUESTED',
  'ACCEPTED',
  'PULLING',
  'STAGED',
  'ASSIGNED',
  'IN_PROGRESS',
  'COMPLETED',
  'SHIPPED',
] as const;

/** Off-ladder stages: the two ways a leaf leaves the pipeline without being assembled. Rendering
 * them as a step on the ladder would say they are further along than IN_PROGRESS, which is nonsense. */
export const TERMINAL_STAGES = ['REJECTED', 'CANCELLED'] as const;

const LABELS: Record<string, string> = {
  REQUESTED: 'Requested',
  ACCEPTED: 'Accepted',
  PULLING: 'Awaiting pull',
  STAGED: 'Staged',
  ASSIGNED: 'Assigned',
  IN_PROGRESS: 'In progress',
  COMPLETED: 'Assembled',
  SHIPPED: 'Shipped',
  REJECTED: 'Rejected',
  CANCELLED: 'Pull cancelled',
};

export function stageLabel(stage: string): string {
  return LABELS[stage] ?? stage;
}

/** Colour for a stage chip.
 *
 * DESIGN.md reserves status colour for real system state, so most of the ladder is deliberately
 * neutral: "assigned" is not a warning and "staged" is not a success, they are just where the work
 * is. Only the three readings somebody acts on differently earn colour - a leaf that has shipped is
 * done (success), a leaf being built right now is live (info), and the two ways out of the pipeline
 * are the ones that need explaining (error / warning).
 */
export function stageColor(stage: string): 'default' | 'info' | 'success' | 'warning' | 'error' {
  if (stage === 'SHIPPED' || stage === 'COMPLETED') return 'success';
  if (stage === 'IN_PROGRESS') return 'info';
  if (stage === 'REJECTED') return 'error';
  if (stage === 'CANCELLED') return 'warning';
  return 'default';
}

/** How far along the ladder a stage is, 0..1, or null when it is off the ladder.
 *
 * Used for the progress rail on the detail view. Null rather than 0 so a rejected request renders as
 * "no rail" instead of "at the very start", which would be a lie about a request that got half way
 * through before somebody killed it.
 */
export function stageProgress(stage: string): number | null {
  const index = PIPELINE_STAGES.indexOf(stage as (typeof PIPELINE_STAGES)[number]);
  if (index < 0) return null;
  return index / (PIPELINE_STAGES.length - 1);
}

export interface PipelineUnitFields {
  plannedUnitCount: number;
  /** Null on a server that predates allocation, where every line was fully allocated by construction. */
  allocatedUnitCount?: number | null;
  installedUnitCount: number;
  deficientUnitCount: number;
  replacementPendingUnitCount: number;
}

/** "5/8 units", the same reading the assembly views use: units, not lines. A line of 8 hinges with 5
 * fitted is most of the job, and a line count would report it as untouched.
 *
 * Dispositioned - installed plus condemned plus awaiting-a-replacement - rather than installed alone,
 * because that is the number completion is gated on (#340).
 *
 * Measured against ALLOCATED, not owed. A short unit was never pulled, so it can never be
 * dispositioned; counting it in the denominator would leave a finished request stuck reading "6/8
 * units" forever, which is the one thing a progress label must not do. */
export function unitProgressLabel(row: PipelineUnitFields): string {
  const done = row.installedUnitCount + row.deficientUnitCount + row.replacementPendingUnitCount;
  return `${done}/${row.allocatedUnitCount ?? row.plannedUnitCount} units`;
}

export interface PipelineFlagFields {
  integrityNote?: string | null;
  awaitingReplacementOpeningCount?: number | null;
  replacementAfterShipOpeningCount?: number | null;
  shortUnitCount?: number | null;
}

/** The flags earlier slices introduced, as short chip labels, in the order somebody should read them:
 * the request-level doubt first (#342), then what is owed (#341), then what cannot be fitted at all.
 *
 * Returns an empty array when everything is fine, so a caller renders nothing rather than a row of
 * reassuring chips - a screen that says "no problems" ten times makes the one that says otherwise
 * harder to spot. */
export function pipelineFlags(row: PipelineFlagFields): { label: string; severity: 'warning' | 'error' }[] {
  const flags: { label: string; severity: 'warning' | 'error' }[] = [];
  if (row.integrityNote) flags.push({ label: 'Needs review', severity: 'warning' });
  if (row.awaitingReplacementOpeningCount) {
    flags.push({
      label: `${row.awaitingReplacementOpeningCount} awaiting replacement`,
      severity: 'warning',
    });
  }
  if (row.replacementAfterShipOpeningCount) {
    flags.push({
      label: `${row.replacementAfterShipOpeningCount} arrived after shipping`,
      severity: 'error',
    });
  }
  // Sent short: units the schedule owed that were never available to pull. A warning rather than an
  // error - it was a decision somebody made with the numbers in front of them - but it has to be on
  // the row, because every other count here can read as complete while it is non-zero.
  if (row.shortUnitCount) {
    flags.push({ label: `${row.shortUnitCount} unit(s) never pulled`, severity: 'warning' });
  }
  return flags;
}
