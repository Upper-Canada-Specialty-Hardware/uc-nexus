import {
  clearRecentErrors,
  moduleFromPath,
  readRecentErrors,
  recordError,
  recordsFromLocation,
} from '../reportContext';

// #1677: what the report bubble sends about where the user was.

describe('recent errors', () => {
  beforeEach(() => clearRecentErrors());

  it('keeps the last ten, oldest first out', () => {
    for (let i = 1; i <= 12; i++) recordError(`error ${i}`);

    const kept = readRecentErrors();

    expect(kept).toHaveLength(10);
    expect(kept[0]).toContain('error 3');
    expect(kept[9]).toContain('error 12');
  });

  it('describes an Error by its stack and an object as json', () => {
    recordError('[GraphQL error]: boom', { code: 'FORBIDDEN' });

    expect(readRecentErrors()[0]).toContain('[GraphQL error]: boom {"code":"FORBIDDEN"}');
  });

  it('cuts a very long error', () => {
    recordError('x'.repeat(5000));

    expect(readRecentErrors()[0].length).toBeLessThan(1100);
  });
});

describe('records read off the url', () => {
  it('names each id by the segment before it', () => {
    expect(
      recordsFromLocation('/app/warehouse/pull-requests/0b9f2c1e-3c4d-4e5f-8a9b-0c1d2e3f4a5b/pick', ''),
    ).toEqual([{ name: 'pull-requests', id: '0b9f2c1e-3c4d-4e5f-8a9b-0c1d2e3f4a5b' }]);
  });

  it('reads document numbers and id-like query parameters', () => {
    expect(recordsFromLocation('/app/po/PO-REQ-1234', '?project=42&tab=lines')).toEqual([
      { name: 'po', id: 'PO-REQ-1234' },
      { name: 'project', id: '42' },
    ]);
  });

  it('finds nothing on a plain page', () => {
    expect(recordsFromLocation('/app/shipping', '')).toEqual([]);
  });
});

it('names the module from the path', () => {
  expect(moduleFromPath('/app/shop-assembly/batches')).toBe('shop-assembly');
  expect(moduleFromPath('/app')).toBe('home');
});
