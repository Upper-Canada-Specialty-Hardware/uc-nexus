export interface DismissedOpening {
  openingNumber: string;
  dismissalReason?: string | null;
}

/**
 * One line per dismissal reason, in the order each reason first appears (#1156). Openings dismissed at
 * different times for different reasons used to be listed together under the first one's reason.
 * Openings dismissed with no reason form their own line, shown without one.
 */
export function dismissalLines(openings: DismissedOpening[]): string[] {
  const groups = new Map<string, string[]>();
  for (const o of openings) {
    const reason = o.dismissalReason?.trim() ?? '';
    const numbers = groups.get(reason);
    if (numbers) numbers.push(o.openingNumber);
    else groups.set(reason, [o.openingNumber]);
  }
  return [...groups].map(([reason, numbers]) => (reason ? `${numbers.join(', ')} - ${reason}` : numbers.join(', ')));
}
