import { describe, expect, it } from 'vitest';
import {
  DEFAULT_COLUMNS,
  DEFAULT_COLUMN_VISIBILITY,
  PANEL_GAP_PX,
  RIGHT_PANEL_MIN_PX,
  gridMinContentWidth,
} from '../openingPanelColumns';

// A 1366px laptop's fullscreen wizard leaves the step about 1318px (24px padding each side), less a
// vertical page scrollbar.
const LAPTOP_CONTENT_PX = 1300;

describe('Select Openings column budget (#1139)', () => {
  it('fits every column whole on a 1366px laptop', () => {
    expect(gridMinContentWidth(DEFAULT_COLUMNS, {})).toBeLessThanOrEqual(LAPTOP_CONTENT_PX);
  });

  it('keeps the hardware preview beside the grid for the default columns at that width', () => {
    const sideBySide = gridMinContentWidth(DEFAULT_COLUMNS, DEFAULT_COLUMN_VISIBILITY) + PANEL_GAP_PX + RIGHT_PANEL_MIN_PX;
    expect(sideBySide).toBeLessThanOrEqual(LAPTOP_CONTENT_PX);
  });

  it('needs the preview moved under the grid once every column is shown there', () => {
    const sideBySide = gridMinContentWidth(DEFAULT_COLUMNS, {}) + PANEL_GAP_PX + RIGHT_PANEL_MIN_PX;
    expect(sideBySide).toBeGreaterThan(LAPTOP_CONTENT_PX);
  });

  it('counts only the columns a person has shown', () => {
    const one = DEFAULT_COLUMNS.slice(0, 1);
    expect(gridMinContentWidth(one, {})).toBe(86 + 50 + 18);
    expect(gridMinContentWidth(one, { opening_number: false })).toBe(50 + 18);
  });
});
