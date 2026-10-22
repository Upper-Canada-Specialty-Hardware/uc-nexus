
describe('appendById (#1888)', () => {
  it('adds a Load more page without a row already shown', async () => {
    const { appendById } = await import('../requestStages');
    const shown = [{ id: 'a' }, { id: 'b' }];
    expect(appendById(shown, [{ id: 'b' }, { id: 'c' }]).map((r) => r.id)).toEqual(['a', 'b', 'c']);
  });
});
