import { renderHook } from '@testing-library/react';
import { useSubmissionKey } from '../useSubmissionKey';

// #1552: a create sent again after a lost reply must carry the key of the attempt that committed.
describe('useSubmissionKey', () => {
  it('keeps the key while the same thing is sent again', () => {
    const { result } = renderHook(() => useSubmissionKey());
    const first = result.current({ projectId: 'p-1', items: [{ code: 'HG-1', qty: 2 }] });
    const again = result.current({ projectId: 'p-1', items: [{ code: 'HG-1', qty: 2 }] });
    expect(first).toBeTruthy();
    expect(again).toBe(first);
  });

  it('mints a new key once what is sent changes', () => {
    const { result } = renderHook(() => useSubmissionKey());
    const first = result.current({ projectId: 'p-1', items: [{ code: 'HG-1', qty: 2 }] });
    const changed = result.current({ projectId: 'p-1', items: [{ code: 'HG-1', qty: 3 }] });
    expect(changed).not.toBe(first);
  });

  it('survives a re-render', () => {
    const { result, rerender } = renderHook(() => useSubmissionKey());
    const first = result.current({ a: 1 });
    rerender();
    expect(result.current({ a: 1 })).toBe(first);
  });
});
