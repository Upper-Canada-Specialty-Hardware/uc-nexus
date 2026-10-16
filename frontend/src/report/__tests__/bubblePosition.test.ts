import {
  BUBBLE_SIZE,
  DEFAULT_SPOT,
  EDGE_MARGIN,
  TOP_LIMIT,
  loadSpot,
  pointToSpot,
  saveSpot,
  spotToPoint,
} from '../bubblePosition';

// #1677: the report bubble snaps to an edge and keeps its spot per person.

const W = 1440;
const H = 900;

it('snaps to the edge its centre is nearer', () => {
  expect(pointToSpot(200, 400, W, H).side).toBe('left');
  expect(pointToSpot(W - 300, 400, W, H).side).toBe('right');
});

it('puts the bubble inside the screen on either edge, never past it', () => {
  expect(spotToPoint({ side: 'left', top: 0 }, W, H)).toEqual({ x: EDGE_MARGIN, y: TOP_LIMIT });
  const bottomRight = spotToPoint({ side: 'right', top: 1 }, W, H);
  expect(bottomRight.x + BUBBLE_SIZE + EDGE_MARGIN).toBe(W);
  expect(bottomRight.y + BUBBLE_SIZE + EDGE_MARGIN).toBe(H);
});

it('clamps a drop above the app bar or below the screen', () => {
  expect(pointToSpot(10, -500, W, H).top).toBe(0);
  expect(pointToSpot(10, 5000, W, H).top).toBe(1);
});

it('keeps its relative height through a resize', () => {
  const spot = pointToSpot(W - 60, 500, W, H);
  const { y } = spotToPoint(spot, 800, 600);

  expect(spot.side).toBe('right');
  expect(y).toBeGreaterThan(TOP_LIMIT);
  expect(y + BUBBLE_SIZE).toBeLessThanOrEqual(600 - EDGE_MARGIN);
});

describe('remembered per person', () => {
  // Its own storage, as AppLayout's test does: a bare runner may expose none.
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
      removeItem: (key: string) => store.delete(key),
      clear: () => store.clear(),
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('loads what was saved for the same person only', () => {
    saveSpot('user_a', { side: 'left', top: 0.3 });

    expect(loadSpot('user_a')).toEqual({ side: 'left', top: 0.3 });
    expect(loadSpot('user_b')).toEqual(DEFAULT_SPOT);
  });

  it('falls back to the default on anything it cannot read', () => {
    localStorage.setItem('uc-nexus-report-bubble:user_a', '{"side":"up"}');

    expect(loadSpot('user_a')).toEqual(DEFAULT_SPOT);
  });
});
