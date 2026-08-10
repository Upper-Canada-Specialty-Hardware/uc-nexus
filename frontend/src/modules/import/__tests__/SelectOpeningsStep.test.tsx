import { useState } from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import SelectOpeningsStep from '../SelectOpeningsStep';
import {
  BLANK,
  buildFacetOptions,
  hasActiveFacets,
  matchesFacets,
  type FacetField,
  type FacetSelections,
} from '../openingFacets';
import type { ParsedOpening } from '../../../types/hardwareSchedule';

// MUI X DataGrid observes container size; jsdom has no ResizeObserver.
beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    // @ts-expect-error minimal stub for jsdom
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

// Steps that mount MUI X DataGrid render slowly under jsdom.
vi.setConfig({ testTimeout: 60_000 });

// ---- Fixtures ----

function makeOpening(overrides: Partial<ParsedOpening> & { opening_number: string }): ParsedOpening {
  return {
    opening_number: overrides.opening_number,
    building: null,
    floor: null,
    location: null,
    location_to: null,
    location_from: null,
    hand: null,
    width: null,
    length: null,
    door_thickness: null,
    jamb_thickness: null,
    door_type: null,
    frame_type: null,
    interior_exterior: null,
    keying: null,
    heading_no: null,
    single_pair: null,
    assignment_multiplier: null,
    leaf_count: 1,
    ...overrides,
  };
}

// A: floor 1 / Wood / Interior, B: floor 1 / HM / Exterior, third: A / floor 2 / Wood / Interior.
const OPENINGS: ParsedOpening[] = [
  makeOpening({
    opening_number: 'O-1',
    building: 'Building A',
    floor: '1',
    location: 'Lobby',
    door_type: 'Wood',
    frame_type: 'HM',
    hand: 'LH',
    interior_exterior: 'Interior',
  }),
  makeOpening({
    opening_number: 'O-2',
    building: 'Building B',
    floor: '1',
    location: 'Stair',
    door_type: 'HM',
    frame_type: 'HM',
    hand: 'RH',
    interior_exterior: 'Exterior',
  }),
  makeOpening({
    opening_number: 'O-3',
    building: 'Building A',
    floor: '2',
    location: 'Office',
    door_type: 'Wood',
    frame_type: 'AL',
    hand: 'RH',
    interior_exterior: 'Interior',
  }),
];

// ---- Pure facet logic ----

describe('openingFacets', () => {
  const sel = (entries: Array<[FacetField, string[]]>): FacetSelections =>
    new Map(entries.map(([field, values]) => [field, new Set(values)]));

  it('folds a null/empty value into the BLANK bucket, with counts, sorted naturally', () => {
    const openings = [
      makeOpening({ opening_number: 'A', floor: '2' }),
      makeOpening({ opening_number: 'B', floor: '10' }),
      makeOpening({ opening_number: 'C', floor: '1' }),
      makeOpening({ opening_number: 'D', floor: null }),
      makeOpening({ opening_number: 'E', floor: '1' }),
    ];
    // Numeric sort keeps 2 before 10; the null lands in BLANK, which sorts by its literal.
    expect(buildFacetOptions(openings, 'floor')).toEqual([
      { value: '(Blank)', count: 1 },
      { value: '1', count: 2 },
      { value: '2', count: 1 },
      { value: '10', count: 1 },
    ]);
    expect(BLANK).toBe('(Blank)');
  });

  it('is AND across facets and OR within one facet', () => {
    // OR within: either building matches.
    const eitherBuilding = sel([['building', ['Building A', 'Building B']]]);
    expect(OPENINGS.filter((o) => matchesFacets(o, eitherBuilding)).map((o) => o.opening_number)).toEqual([
      'O-1',
      'O-2',
      'O-3',
    ]);

    // AND across: Building A AND floor 2 leaves only O-3.
    const buildingAndFloor = sel([
      ['building', ['Building A']],
      ['floor', ['2']],
    ]);
    expect(OPENINGS.filter((o) => matchesFacets(o, buildingAndFloor)).map((o) => o.opening_number)).toEqual([
      'O-3',
    ]);
  });

  it('treats a missing or empty facet as no constraint', () => {
    expect(hasActiveFacets(new Map())).toBe(false);
    expect(hasActiveFacets(sel([['building', []]]))).toBe(false);
    expect(hasActiveFacets(sel([['building', ['Building A']]]))).toBe(true);
    // Empty selection matches everything.
    expect(OPENINGS.every((o) => matchesFacets(o, sel([['hand', []]])))).toBe(true);
  });
});

// ---- Component: facet composition + column removal ----

/** Stateful wrapper so the selection chip and Select All reflect real selection changes. */
function Harness({ onSelect }: { onSelect?: (s: Set<string>) => void }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  return (
    <SelectOpeningsStep
      openings={OPENINGS}
      selectedOpenings={selected}
      preReconAggregatedItems={[]}
      onOpeningSelectionChange={(s) => {
        setSelected(s);
        onSelect?.(s);
      }}
    />
  );
}

function openFacet(field: string) {
  fireEvent.mouseDown(within(screen.getByTestId(`facet-${field}`)).getByRole('combobox'));
}

function pickOption(name: RegExp) {
  fireEvent.click(screen.getByRole('option', { name }));
}

function closeMenu() {
  // MUI Select's Menu renders an invisible backdrop; clicking it dismisses the popover.
  const backdrop = document.querySelector('.MuiBackdrop-root');
  if (backdrop) fireEvent.click(backdrop);
}

describe('SelectOpeningsStep', () => {
  it('renders a facet dropdown per attribute and no Hardware Items column', () => {
    render(<Harness />);

    // The grid mounted (a real column header) but the removed hardwareCount column is gone.
    expect(screen.getByRole('columnheader', { name: 'Opening #' })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Hardware Items' })).not.toBeInTheDocument();

    // One dropdown for each of the seven facets (all have 2+ distinct values in the fixture).
    for (const field of [
      'building',
      'floor',
      'location',
      'door_type',
      'frame_type',
      'hand',
      'interior_exterior',
    ]) {
      expect(screen.getByTestId(`facet-${field}`)).toBeInTheDocument();
    }
  });

  it('narrows the visible rows by a facet and Select All takes only those', () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);

    expect(screen.getByText('0 of 3 selected')).toBeInTheDocument();

    openFacet('building');
    pickOption(/Building A/);
    closeMenu();

    // Building A is O-1 and O-3; the count reflects the narrowed set.
    expect(screen.getByText('0 of 2 selected')).toBeInTheDocument();
    expect(screen.getByText(/filtered from 3 total/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    expect(onSelect).toHaveBeenLastCalledWith(new Set(['O-1', 'O-3']));
  });

  it('composes facets with AND (Building A + floor 2 => one row)', () => {
    render(<Harness />);

    openFacet('building');
    pickOption(/Building A/);
    closeMenu();
    openFacet('floor');
    pickOption(/^2/);
    closeMenu();

    expect(screen.getByText('0 of 1 selected')).toBeInTheDocument();
  });

  it('intersects the facet filter with the paste-numbers filter', () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);

    // Paste filter to O-1 and O-2, then narrow by Building A: only O-1 is in both.
    fireEvent.change(screen.getByPlaceholderText('Paste opening numbers, one per line...'), {
      target: { value: 'O-1\nO-2' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();

    openFacet('building');
    pickOption(/Building A/);
    closeMenu();

    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    expect(onSelect).toHaveBeenLastCalledWith(new Set(['O-1']));
  });
});
