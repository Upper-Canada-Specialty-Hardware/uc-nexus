import { appendById } from '../appendById';

describe('appendById (#1888)', () => {
  it('adds a Load more page without a row already shown', () => {
    const shown = [{ id: 'a' }, { id: 'b' }];
    expect(appendById(shown, [{ id: 'b' }, { id: 'c' }]).map((r) => r.id)).toEqual(['a', 'b', 'c']);
  });

  it('keeps the row already shown, not the page copy of it', () => {
    const shown = [{ id: 'a', v: 'shown' }];
    expect(appendById(shown, [{ id: 'a', v: 'page' }])).toEqual([{ id: 'a', v: 'shown' }]);
  });

  it('leaves what is shown untouched when the page is empty', () => {
    const shown = [{ id: 'a' }];
    expect(appendById(shown, [])).toEqual(shown);
  });
});
