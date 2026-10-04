import { projectsColumns } from '../projectsColumns';

// #1411: at 1366px with the nav rail expanded the page content is 1366 - 224 (rail) - 48 (gutters) =
// 1094px. The grid spends 2px on borders and useGridColumnFit keeps 18px for a scrollbar, so the column
// floors must sum to 1074px or less - past that the fit squeezes every column under its floor and the
// State and GP Setup chips clip.
const FLOOR_BUDGET = 1366 - 224 - 48 - 2 - 18;

it('column floors fit 1366 with the rail expanded', () => {
  const sum = projectsColumns.reduce((total, c) => total + (c.minWidth ?? 0), 0);
  expect(projectsColumns.every((c) => (c.minWidth ?? 0) > 0)).toBe(true);
  expect(sum).toBeLessThanOrEqual(FLOOR_BUDGET);
});

it('keeps the chip columns at the floors that hold their chips whole', () => {
  const floor = (field: string) => projectsColumns.find((c) => c.field === field)?.minWidth;
  expect(floor('archived')).toBe(190);
  expect(floor('gpSetupOk')).toBe(150);
});
