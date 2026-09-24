/**
 * One cost code on a project's GP job whose GL account index does not exist in the company's chart
 * (#425). Jobs replicated from UCSH before 2023 kept UCSH account indexes, so a PO on such a code
 * registers in GP and then fails forever at receipt with "Invalid Account Index".
 */
export interface GpSetupIssue {
  costCode: string;
  accountIndex: number;
}

export interface Project {
  id: string;
  projectId: string;
  description: string | null;
  client: string | null;
  jobSiteName: string | null;
  /** #632: the XML the schedule on file came from (#627 capture). Null on projects last imported
   *  before it existed - the name records on the next fresh upload. */
  scheduleFilename?: string | null;
  /** #637: the GP company (tenant) that owns this job. Every project has one; only a UC Nexus Admin
   *  ever sees more than their own, which is why the pickers badge it for them alone. */
  company: string;
  openingCount: number;
  // GP job setup verdict (#425). null means the backend has never been able to check - no relay has
  // answered yet - and is NOT a quarantine. Only an explicit false is.
  gpSetupOk?: boolean | null;
  gpSetupCheckedAt?: string | null;
  gpSetupIssues?: GpSetupIssue[] | null;
  /** #730: the GP job's own state. Null means the job has never been mirrored - no tag, no restriction. */
  gpJobState?: GpJobState | null;
}

/**
 * The shape every quarantine-aware screen actually needs. Loose on purpose: the PO, receiving and
 * shipping screens each carry their own project-ish object, and none of them should have to widen to
 * the full `Project` just to ask this one question.
 */
export interface GpSetupStatus {
  projectId?: string;
  gpSetupOk?: boolean | null;
  gpSetupCheckedAt?: string | null;
  gpSetupIssues?: GpSetupIssue[] | null;
}

/**
 * Is this project quarantined for broken GP job setup (#425)?
 *
 * Strictly `=== false`. undefined (the field was not requested) and null (never checked) both pass,
 * and that asymmetry is the whole safety property: the verdict only exists while a relay is
 * connected, so treating "unknown" as "broken" would grey out the entire application every time the
 * relay restarted. The server enforces the same rule, so a screen that gets this wrong in the
 * permissive direction still cannot push bad work through.
 */
export function isGpSetupBroken(project: GpSetupStatus | null | undefined): boolean {
  return project?.gpSetupOk === false;
}

/**
 * #730: the state GP holds the job in. ACTIVE (and null, never mirrored) is an open job. INACTIVE is
 * GP's reversible grace period, CLOSED is permanent, and NOT_IN_GP is a job GP has no record of, which
 * is treated the same. GP refuses every NEXUS TO GP WRITE against the last three.
 */
export type GpJobState = 'ACTIVE' | 'INACTIVE' | 'CLOSED' | 'NOT_IN_GP';

export interface GpJobStatus {
  projectId?: string;
  gpJobState?: GpJobState | null;
}

/**
 * Is this project's GP job closed to writes (#730)? Strictly one of the three named states: undefined
 * (not requested), null (never mirrored) and ACTIVE all pass, the same permissive-on-unknown rule as
 * isGpSetupBroken. The server enforces it either way.
 */
export function isGpJobNotOpen(project: GpJobStatus | null | undefined): boolean {
  const state = project?.gpJobState;
  return state === 'INACTIVE' || state === 'CLOSED' || state === 'NOT_IN_GP';
}

type NotOpenGpJobState = Exclude<GpJobState, 'ACTIVE'>;

const GP_JOB_STATE_LABEL: Record<NotOpenGpJobState, string> = {
  INACTIVE: 'Inactive in GP',
  CLOSED: 'Closed in GP',
  NOT_IN_GP: 'Not in GP',
};

const GP_JOB_NOT_OPEN_REASON: Record<NotOpenGpJobState, string> = {
  INACTIVE: 'GP holds this job as inactive, and GP refuses changes to it until the job is made active again in GP.',
  CLOSED: 'GP holds this job as closed, which is permanent, and GP refuses every change to it.',
  NOT_IN_GP: 'GP has no record of this job, so there is nothing in GP to change.',
};

/** #730: the tag text for a job that is not open, or null for an open (or never mirrored) one. */
export function gpJobStateLabel(project: GpJobStatus | null | undefined): string | null {
  if (!isGpJobNotOpen(project)) return null;
  return GP_JOB_STATE_LABEL[project!.gpJobState as NotOpenGpJobState];
}

/** #730: why GP will not take a write against this job, in one sentence. Null for an open job. */
export function gpJobNotOpenReason(project: GpJobStatus | null | undefined): string | null {
  if (!isGpJobNotOpen(project)) return null;
  return GP_JOB_NOT_OPEN_REASON[project!.gpJobState as NotOpenGpJobState];
}
