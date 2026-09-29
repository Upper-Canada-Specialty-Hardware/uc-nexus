import hardwareClassifications from '../HardwareClassificationsPage.tsx?raw';
import hardwareStatus from '../HardwareStatusPage.tsx?raw';
import purchasingProgress from '../ProjectPurchasingProgressPage.tsx?raw';
import projects from '../ProjectsPage.tsx?raw';
import users from '../UserManagementPage.tsx?raw';
import warehouses from '../WarehousesPage.tsx?raw';
import dbAccess from '../../nexus-admin/DbAccessPage.tsx?raw';
import relayInstalls from '../../nexus-admin/RelayInstallsPage.tsx?raw';

// #909 / #924: every grid on the tenant owner and UC Nexus Admin screens fits its width through
// `useGridColumnFit` (no sideways scroll, remembered column widths). The fit itself is tested with
// the hook; this only checks each screen is wired to it under its own storage key.
const SCREENS: { name: string; source: string; keys: string[] }[] = [
  { name: 'HardwareClassificationsPage', source: hardwareClassifications, keys: ['tenant-owner.hardware-classifications'] },
  { name: 'HardwareStatusPage', source: hardwareStatus, keys: ['tenant-owner.hardware-status'] },
  { name: 'ProjectPurchasingProgressPage', source: purchasingProgress, keys: ['tenant-owner.project-purchasing-progress'] },
  { name: 'ProjectsPage', source: projects, keys: ['tenant-owner.projects'] },
  { name: 'UserManagementPage', source: users, keys: ['nexus-admin.users', 'tenant-owner.users'] },
  { name: 'WarehousesPage', source: warehouses, keys: ['tenant-owner.warehouses'] },
  { name: 'DbAccessPage', source: dbAccess, keys: ['nexus-admin.db-access.logins'] },
  { name: 'RelayInstallsPage', source: relayInstalls, keys: ['nexus-admin.relay-installs'] },
];

const count = (source: string, needle: string) => source.split(needle).length - 1;

describe('tenant owner and admin grids fit their width', () => {
  it.each(SCREENS)('$name hands every grid the fitted columns', ({ source, keys }) => {
    const grids = count(source, '<DataGrid');
    expect(grids).toBeGreaterThan(0);
    expect(source).toContain('useGridColumnFit(');
    expect(count(source, 'ref={setContainer}')).toBe(grids);
    expect(count(source, '{...gridProps}')).toBe(grids);
    // The fitted columns come from gridProps; a later `columns=` would override them.
    expect(source).not.toMatch(/<DataGrid[^>]*\scolumns=\{/);
    for (const key of keys) expect(source).toContain(`'${key}'`);
  });

  it.each(SCREENS)('$name has no sideways scroll wrapper', ({ source }) => {
    expect(source).not.toMatch(/overflowX\s*:\s*['"](auto|scroll)['"]/);
  });

  it('gives every grid its own storage key', () => {
    const all = SCREENS.flatMap((s) => s.keys);
    expect(new Set(all).size).toBe(all.length);
  });
});
