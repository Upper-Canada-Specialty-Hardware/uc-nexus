import {
  canTakeAnotherLeaf,
  containerDropId,
  dropTargetContainer,
  leafCount,
  MAX_LEAVES_PER_SKID,
  planContainerDrag,
  type Container,
  type ContainerItem,
  type ContainerType,
} from '../staging';

/**
 * The drag decision behind the staging workspace (#470).
 *
 * `StagingWorkspace.test.tsx` drives the click-equivalent controls because dnd-kit needs a pointer
 * with real geometry and jsdom has none. That left the cross-container move - the one this screen
 * mostly exists for - reachable only by a hand-run browser session. These pin the decision itself,
 * which is the half that can regress silently.
 */

let nextId = 0;

function item(overrides: Partial<ContainerItem> = {}): ContainerItem {
  nextId += 1;
  return {
    id: `ci-${nextId}`,
    itemType: 'LOOSE',
    openingItemId: null,
    openingNumber: '101',
    leaf: null,
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    quantity: 1,
    position: 0,
    ...overrides,
  };
}

function leafItem(overrides: Partial<ContainerItem> = {}): ContainerItem {
  return item({
    itemType: 'OPENING_ITEM',
    openingItemId: `oi-${overrides.openingNumber ?? '101'}-${overrides.leaf ?? 1}`,
    openingNumber: '101',
    leaf: 1,
    hardwareCategory: '',
    productCode: '',
    ...overrides,
  });
}

function container(
  id: string,
  containerType: ContainerType,
  items: ContainerItem[] = [],
): Container {
  return {
    id,
    projectId: 'proj-1',
    containerType,
    name: `${containerType} ${id}`,
    packingSlipId: null,
    createdBy: 'tester',
    items: items.map((i, index) => ({ ...i, position: index })),
  };
}

/** A skid loaded to its ceiling, each leaf its own opening so nothing collides. */
function fullSkid(id: string): Container {
  return container(
    id,
    'SKID',
    Array.from({ length: MAX_LEAVES_PER_SKID }, (_, n) =>
      leafItem({ openingNumber: `${900 + n}`, leaf: 1 }),
    ),
  );
}

beforeEach(() => {
  nextId = 0;
});

describe('dropTargetContainer', () => {
  it('resolves a drop on the container card', () => {
    const box = container('c-1', 'BOX', [item()]);
    expect(dropTargetContainer([box], containerDropId('c-1'))?.id).toBe('c-1');
  });

  it('resolves a drop on a row inside it - landing on a row means landing in the container', () => {
    const box = container('c-1', 'BOX', [item({ id: 'row-1' })]);
    expect(dropTargetContainer([box], 'row-1')?.id).toBe('c-1');
  });

  it('resolves nothing for an id belonging to neither', () => {
    expect(dropTargetContainer([container('c-1', 'BOX')], 'leaf:oi-1')).toBeUndefined();
  });
});

describe('a drag that started in the pool', () => {
  it('is not this function to decide - the caller needs the pool rows and the quantity', () => {
    const box = container('c-1', 'BOX');
    expect(planContainerDrag([box], 'leaf:oi-1', containerDropId('c-1'))).toBeNull();
  });
});

describe('restacking inside one container', () => {
  it('reorders when a row is dropped on another row of the same container', () => {
    const skid = container('c-1', 'SKID', [
      leafItem({ id: 'a', openingNumber: '101' }),
      leafItem({ id: 'b', openingNumber: '102' }),
      leafItem({ id: 'c', openingNumber: '103' }),
    ]);

    const plan = planContainerDrag([skid], 'a', 'c');

    expect(plan).toMatchObject({ action: 'reorder', container: { id: 'c-1' } });
    expect(plan?.action === 'reorder' && plan.items.map((i) => i.id)).toEqual(['b', 'c', 'a']);
  });

  it('writes nothing when a row is dropped on itself', () => {
    const skid = container('c-1', 'SKID', [leafItem({ id: 'a' }), leafItem({ id: 'b', openingNumber: '102' })]);
    expect(planContainerDrag([skid], 'a', 'a')).toEqual({ action: 'none' });
  });

  it('writes nothing when a row is dropped on the card it already sits in', () => {
    const skid = container('c-1', 'SKID', [leafItem({ id: 'a' })]);
    expect(planContainerDrag([skid], 'a', containerDropId('c-1'))).toEqual({ action: 'none' });
  });

  it('writes nothing when the drop lands on something that is not a container or a row', () => {
    const skid = container('c-1', 'SKID', [leafItem({ id: 'a' })]);
    expect(planContainerDrag([skid], 'a', 'nowhere')).toEqual({ action: 'none' });
  });
});

describe('moving an assembled leaf to another container', () => {
  const source = () =>
    container('c-1', 'SKID', [
      leafItem({ id: 'a', openingNumber: '101', leaf: 1 }),
      leafItem({ id: 'b', openingNumber: '102', leaf: 2 }),
    ]);

  it('empties the source and appends to the target, opening and leaf intact', () => {
    const target = container('c-2', 'SKID');
    const plan = planContainerDrag([source(), target], 'a', containerDropId('c-2'));

    expect(plan?.action).toBe('move');
    if (plan?.action !== 'move') return;
    expect(plan.source.id).toBe('c-1');
    expect(plan.sourceItems.map((i) => i.id)).toEqual(['b']);
    expect(plan.target.id).toBe('c-2');
    expect(plan.targetItems).toHaveLength(1);
    expect(plan.targetItems[0]).toMatchObject({
      id: 'new',
      itemType: 'OPENING_ITEM',
      openingItemId: 'oi-101-1',
      openingNumber: '101',
      leaf: 1,
      position: 0,
    });
  });

  it('counts the leaf exactly once across the two writes - it never sits in both', () => {
    const target = container('c-2', 'SKID', [leafItem({ id: 'z', openingNumber: '900' })]);
    const plan = planContainerDrag([source(), target], 'a', containerDropId('c-2'));

    if (plan?.action !== 'move') throw new Error('expected a move');
    const placements = [...plan.sourceItems, ...plan.targetItems].filter(
      (i) => i.openingItemId === 'oi-101-1',
    );
    expect(placements).toHaveLength(1);
  });

  it('appends to the end of the target stack, which is the top of a skid', () => {
    const target = container('c-2', 'SKID', [
      leafItem({ id: 'y', openingNumber: '900' }),
      leafItem({ id: 'z', openingNumber: '901' }),
    ]);
    const plan = planContainerDrag([source(), target], 'a', containerDropId('c-2'));

    if (plan?.action !== 'move') throw new Error('expected a move');
    expect(plan.targetItems.map((i) => i.id)).toEqual(['y', 'z', 'new']);
    expect(plan.targetItems[2].position).toBe(2);
  });

  it('is a move, not a restack, when the drop lands on a row of the other container', () => {
    const target = container('c-2', 'SKID', [leafItem({ id: 'z', openingNumber: '900' })]);
    const plan = planContainerDrag([source(), target], 'a', 'z');

    expect(plan).toMatchObject({ action: 'move', target: { id: 'c-2' } });
  });
});

describe('the thirty-leaf skid ceiling', () => {
  it('refuses a leaf onto a full skid rather than moving it', () => {
    // Refused rather than attempted: the source is emptied first, so a move the server then rejects
    // would take the leaf off a skid it was safely on and leave it nowhere.
    const source = container('c-1', 'SKID', [leafItem({ id: 'a', openingNumber: '101' })]);
    const target = fullSkid('c-2');

    expect(leafCount(target)).toBe(MAX_LEAVES_PER_SKID);
    expect(canTakeAnotherLeaf(target)).toBe(false);
    expect(planContainerDrag([source, target], 'a', containerDropId('c-2'))).toEqual({
      action: 'refuse',
      target,
    });
  });

  it('allows the thirtieth', () => {
    const target = container(
      'c-2',
      'SKID',
      Array.from({ length: MAX_LEAVES_PER_SKID - 1 }, (_, n) => leafItem({ openingNumber: `${900 + n}` })),
    );
    const source = container('c-1', 'SKID', [leafItem({ id: 'a', openingNumber: '101' })]);

    const plan = planContainerDrag([source, target], 'a', containerDropId('c-2'));

    expect(plan?.action).toBe('move');
    expect(plan?.action === 'move' && plan.targetItems).toHaveLength(MAX_LEAVES_PER_SKID);
  });

  it('does not apply to a door cart - only a skid has a ceiling', () => {
    const target = { ...fullSkid('c-2'), containerType: 'DOOR_CART' as const };
    const source = container('c-1', 'SKID', [leafItem({ id: 'a', openingNumber: '101' })]);

    expect(planContainerDrag([source, target], 'a', containerDropId('c-2'))).toMatchObject({
      action: 'move',
    });
  });

  it('does not block loose hardware onto a full skid - the cap counts leaves', () => {
    const source = container('c-1', 'BOX', [item({ id: 'a' })]);
    const target = fullSkid('c-2');

    expect(planContainerDrag([source, target], 'a', containerDropId('c-2'))).toMatchObject({
      action: 'move',
    });
  });
});

describe('moving loose hardware to another container', () => {
  it('tops up a line already holding the same stock rather than adding a second', () => {
    const source = container('c-1', 'BOX', [item({ id: 'a', quantity: 2 })]);
    const target = container('c-2', 'BOX', [item({ id: 'z', quantity: 3 })]);

    const plan = planContainerDrag([source, target], 'a', containerDropId('c-2'));

    if (plan?.action !== 'move') throw new Error('expected a move');
    expect(plan.targetItems).toHaveLength(1);
    expect(plan.targetItems[0]).toMatchObject({ id: 'z', quantity: 5 });
  });

  it('keeps another openings units as their own line', () => {
    // Two openings staging the same product are two quantities to the confirm; merging them would
    // book units against a door they were never pulled for.
    const source = container('c-1', 'BOX', [item({ id: 'a', openingNumber: '101', quantity: 2 })]);
    const target = container('c-2', 'BOX', [item({ id: 'z', openingNumber: '102', quantity: 3 })]);

    const plan = planContainerDrag([source, target], 'a', containerDropId('c-2'));

    if (plan?.action !== 'move') throw new Error('expected a move');
    expect(plan.targetItems).toHaveLength(2);
    expect(plan.targetItems.map((i) => i.quantity)).toEqual([3, 2]);
  });

  it('never merges into an assembled leaf', () => {
    const source = container('c-1', 'BOX', [item({ id: 'a', quantity: 2 })]);
    const target = container('c-2', 'SKID', [leafItem({ id: 'z', openingNumber: '101' })]);

    const plan = planContainerDrag([source, target], 'a', containerDropId('c-2'));

    if (plan?.action !== 'move') throw new Error('expected a move');
    expect(plan.targetItems).toHaveLength(2);
  });
});
