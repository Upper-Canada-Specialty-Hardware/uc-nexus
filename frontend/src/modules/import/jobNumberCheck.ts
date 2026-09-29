/**
 * Whether an uploaded TITAN file is for the project it is being imported into (#855).
 *
 * A TITAN export names its own job in `Submittal_Job_No`, in the same form as a Nexus project number
 * (`22713`). A schedule imported onto the wrong job lands the wrong doors and hardware on it, and
 * every PO and request built from it after, so a mismatch has to be seen before step 1 is left.
 * Compared trimmed and case-insensitively; a file that names no job cannot be checked at all.
 */
export type JobNumberCheck = 'match' | 'mismatch' | 'unknown';

export function checkJobNumber(fileJobNo: string | null | undefined, projectJobNo: string): JobNumberCheck {
  const fileJob = (fileJobNo ?? '').trim().toLowerCase();
  if (!fileJob) return 'unknown';
  return fileJob === projectJobNo.trim().toLowerCase() ? 'match' : 'mismatch';
}
