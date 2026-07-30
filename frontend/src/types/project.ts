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
  openingCount: number;
  // GP job setup verdict (#425). null means the backend has never been able to check - no relay has
  // answered yet - and is NOT a quarantine. Only an explicit false is.
  gpSetupOk?: boolean | null;
  gpSetupCheckedAt?: string | null;
  gpSetupIssues?: GpSetupIssue[] | null;
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
