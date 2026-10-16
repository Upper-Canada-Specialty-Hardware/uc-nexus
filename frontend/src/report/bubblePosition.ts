/**
 * Where the report bubble sits (#1677): on the left or right edge, some way down the screen.
 *
 * Kept as a side and a fraction of the usable height rather than pixels, so a resize keeps it on its
 * edge at the same relative height instead of stranding it off screen. Remembered per person.
 */

export const BUBBLE_SIZE = 48;
/** Gap to the screen edge it snaps to, and to the bottom. */
export const EDGE_MARGIN = 16;
/** Clear of the app bar, so it never sits on the bar's controls. */
export const TOP_LIMIT = 72;

export type BubbleSide = 'left' | 'right';

export interface BubbleSpot {
  side: BubbleSide;
  /** 0 is just under the app bar, 1 is the bottom margin. */
  top: number;
}

export const DEFAULT_SPOT: BubbleSpot = { side: 'right', top: 0.82 };

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

function verticalRange(viewportHeight: number): number {
  return Math.max(0, viewportHeight - BUBBLE_SIZE - EDGE_MARGIN - TOP_LIMIT);
}

/** The bubble's top-left corner, in viewport pixels, for a spot. */
export function spotToPoint(spot: BubbleSpot, viewportWidth: number, viewportHeight: number) {
  return {
    x: spot.side === 'left' ? EDGE_MARGIN : Math.max(EDGE_MARGIN, viewportWidth - BUBBLE_SIZE - EDGE_MARGIN),
    y: TOP_LIMIT + clamp(spot.top, 0, 1) * verticalRange(viewportHeight),
  };
}

/** The spot nearest a point: the edge its centre is closer to, the height clamped on screen. */
export function pointToSpot(x: number, y: number, viewportWidth: number, viewportHeight: number): BubbleSpot {
  const range = verticalRange(viewportHeight);
  return {
    side: x + BUBBLE_SIZE / 2 < viewportWidth / 2 ? 'left' : 'right',
    top: range === 0 ? 0 : clamp((y - TOP_LIMIT) / range, 0, 1),
  };
}

const storageKey = (userId: string) => `uc-nexus-report-bubble:${userId || 'anonymous'}`;

/** The person's remembered spot, or the default. Storage can be blocked; that is not an error. */
export function loadSpot(userId: string): BubbleSpot {
  try {
    const raw = localStorage.getItem(storageKey(userId));
    if (!raw) return DEFAULT_SPOT;
    const parsed = JSON.parse(raw) as Partial<BubbleSpot>;
    if ((parsed.side === 'left' || parsed.side === 'right') && typeof parsed.top === 'number') {
      return { side: parsed.side, top: clamp(parsed.top, 0, 1) };
    }
  } catch {
    // Blocked or corrupt storage: the default spot.
  }
  return DEFAULT_SPOT;
}

export function saveSpot(userId: string, spot: BubbleSpot): void {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(spot));
  } catch {
    // Blocked storage: it lands in the same place for this visit only.
  }
}
