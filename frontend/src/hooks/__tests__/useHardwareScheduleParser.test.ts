import { renderHook, act } from '@testing-library/react';
import { useHardwareScheduleParser } from '../useHardwareScheduleParser';
import type { ParseResult } from '../../types/hardwareSchedule';

// ---------------------------------------------------------------------------
// Mock Worker
// ---------------------------------------------------------------------------

class MockWorker {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  postMessage = vi.fn();
  terminate = vi.fn();
}

// We keep a reference to every MockWorker created so tests can trigger
// onmessage / onerror after the hook has wired things up.
let latestMockWorker: MockWorker;

// ---------------------------------------------------------------------------
// Mock FileReader
// ---------------------------------------------------------------------------

class MockFileReader {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  result: string | null = null;
  readAsText = vi.fn().mockImplementation(() => {
    // readAsText stores the text result and then we let tests manually
    // trigger onload / onerror from the outside.
    this.result = '<Contract>mock xml</Contract>';
  });
}

let latestMockFileReader: MockFileReader;

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Must use a real class (not vi.fn arrow) so `new Worker(...)` works.
  // We wrap the mock classes to capture the latest instance created.
  const OriginalMockWorker = MockWorker;
  vi.stubGlobal(
    'Worker',
    class extends OriginalMockWorker {
      constructor(...args: unknown[]) {
        super();
        latestMockWorker = this;
      }
    },
  );

  const OriginalMockFileReader = MockFileReader;
  vi.stubGlobal(
    'FileReader',
    class extends OriginalMockFileReader {
      constructor() {
        super();
        latestMockFileReader = this;
      }
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal mock File object for parseFile() */
function createMockFile(content = '<Contract/>') {
  return new File([content], 'schedule.xml', { type: 'text/xml' });
}

/** Minimal valid ParseResult for testing the 'done' path */
const mockParseResult: ParseResult = {
  project: {
    project_id: 'P-001',
    description: 'Test Project',
    job_site_name: null,
    address: null,
    city: null,
    state: null,
    zip: null,
    contractor: null,
    project_manager: null,
    application: null,
    submittal_job_no: null,
    submittal_assignment_count: null,
    estimator_code: null,
    titan_user_id: null,
  },
  openings: [
    {
      opening_number: '101',
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
    },
  ],
  hardwareItems: [
    {
      opening_number: '101',
      product_code: 'HW-001',
      material_id: 'M-001',
      hardware_category: 'Hinges',
      item_quantity: 3,
      unit_cost: null,
      unit_price: null,
      list_price: null,
      vendor_discount: null,
      markup_pct: null,
      vendor_no: null,
      phase_code: null,
      item_category_code: null,
      product_group_code: null,
      submittal_id: null,
    },
  ],
  validationSummary: {
    totalOpenings: 1,
    totalHardwareItems: 1,
    skippedRows: [],
    warnings: [],
  },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useHardwareScheduleParser', () => {
  // -----------------------------------------------------------------------
  // 1. Initial state
  // -----------------------------------------------------------------------
  it('returns the correct initial state', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    expect(result.current.state).toBe('idle');
    expect(result.current.progress).toEqual({ percent: 0, phase: '' });
    expect(result.current.parseResult).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(typeof result.current.parseFile).toBe('function');
    expect(typeof result.current.reset).toBe('function');
  });

  // -----------------------------------------------------------------------
  // 2. parseFile transitions to 'reading'
  // -----------------------------------------------------------------------
  it('transitions to reading state when parseFile is called', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    act(() => {
      result.current.parseFile(createMockFile());
    });

    expect(result.current.state).toBe('reading');
    expect(result.current.isLoading).toBe(true);
    expect(result.current.progress).toEqual({ percent: 0, phase: 'Reading file' });
    expect(latestMockFileReader.readAsText).toHaveBeenCalledTimes(1);
  });

  // -----------------------------------------------------------------------
  // 3. Full reading -> parsing -> done flow
  // -----------------------------------------------------------------------
  it('transitions through reading -> parsing -> done when worker returns a result', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    // Start the parse
    act(() => {
      result.current.parseFile(createMockFile());
    });
    expect(result.current.state).toBe('reading');

    // Simulate FileReader completing
    act(() => {
      latestMockFileReader.onload!();
    });
    expect(result.current.state).toBe('parsing');
    expect(latestMockWorker.postMessage).toHaveBeenCalledWith({
      type: 'parse',
      xmlContent: latestMockFileReader.result,
    });

    // Simulate worker returning a result
    act(() => {
      latestMockWorker.onmessage!(
        new MessageEvent('message', {
          data: { type: 'result', data: mockParseResult },
        }),
      );
    });

    expect(result.current.state).toBe('done');
    expect(result.current.isLoading).toBe(false);
    expect(result.current.parseResult).toEqual(mockParseResult);
    expect(result.current.progress).toEqual({ percent: 100, phase: 'Complete' });
    expect(result.current.error).toBeNull();
  });

  // -----------------------------------------------------------------------
  // 4. Progress updates
  // -----------------------------------------------------------------------
  it('updates progress when worker sends progress messages', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    // Kick off and get to parsing
    act(() => {
      result.current.parseFile(createMockFile());
    });
    act(() => {
      latestMockFileReader.onload!();
    });
    expect(result.current.state).toBe('parsing');

    // Worker sends a progress update
    act(() => {
      latestMockWorker.onmessage!(
        new MessageEvent('message', {
          data: { type: 'progress', percent: 50, phase: 'Extracting openings' },
        }),
      );
    });

    expect(result.current.progress).toEqual({
      percent: 50,
      phase: 'Extracting openings',
    });
    // State should still be 'parsing' — not 'done' yet
    expect(result.current.state).toBe('parsing');

    // Another progress update
    act(() => {
      latestMockWorker.onmessage!(
        new MessageEvent('message', {
          data: { type: 'progress', percent: 80, phase: 'Extracting hardware items' },
        }),
      );
    });

    expect(result.current.progress).toEqual({
      percent: 80,
      phase: 'Extracting hardware items',
    });
  });

  // -----------------------------------------------------------------------
  // 5. Worker error via message (type: 'error')
  // -----------------------------------------------------------------------
  it('transitions to error state when worker sends an error message', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    act(() => {
      result.current.parseFile(createMockFile());
    });
    act(() => {
      latestMockFileReader.onload!();
    });
    expect(result.current.state).toBe('parsing');

    act(() => {
      latestMockWorker.onmessage!(
        new MessageEvent('message', {
          data: { type: 'error', error: 'Parse failed: invalid XML' },
        }),
      );
    });

    expect(result.current.state).toBe('error');
    expect(result.current.error).toBe('Parse failed: invalid XML');
    expect(result.current.parseResult).toBeNull();
  });

  // -----------------------------------------------------------------------
  // 6. FileReader error
  // -----------------------------------------------------------------------
  it('transitions to error state when FileReader fails', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    act(() => {
      result.current.parseFile(createMockFile());
    });
    expect(result.current.state).toBe('reading');

    // Simulate FileReader error
    act(() => {
      latestMockFileReader.onerror!();
    });

    expect(result.current.state).toBe('error');
    expect(result.current.error).toBe('Failed to read file');
    expect(result.current.parseResult).toBeNull();
  });

  // -----------------------------------------------------------------------
  // 7. reset() clears state and terminates worker
  // -----------------------------------------------------------------------
  it('resets state back to idle and terminates the worker', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    // Drive through the full success flow first
    act(() => {
      result.current.parseFile(createMockFile());
    });
    act(() => {
      latestMockFileReader.onload!();
    });
    act(() => {
      latestMockWorker.onmessage!(
        new MessageEvent('message', {
          data: { type: 'result', data: mockParseResult },
        }),
      );
    });
    expect(result.current.state).toBe('done');
    expect(result.current.parseResult).toEqual(mockParseResult);

    const terminatedWorker = latestMockWorker;

    act(() => {
      result.current.reset();
    });

    expect(result.current.state).toBe('idle');
    expect(result.current.progress).toEqual({ percent: 0, phase: '' });
    expect(result.current.parseResult).toBeNull();
    expect(result.current.error).toBeNull();
    expect(terminatedWorker.terminate).toHaveBeenCalledTimes(1);
  });

  // -----------------------------------------------------------------------
  // 8. Cleanup terminates worker on unmount
  // -----------------------------------------------------------------------
  it('terminates the worker when the hook is unmounted', () => {
    const { result, unmount } = renderHook(() => useHardwareScheduleParser());

    // Get a worker created by driving into parsing state
    act(() => {
      result.current.parseFile(createMockFile());
    });
    act(() => {
      latestMockFileReader.onload!();
    });
    expect(result.current.state).toBe('parsing');

    const workerToTerminate = latestMockWorker;

    unmount();

    expect(workerToTerminate.terminate).toHaveBeenCalled();
  });

  // -----------------------------------------------------------------------
  // 9. Ignores parseFile calls while already reading or parsing
  // -----------------------------------------------------------------------
  it('ignores parseFile when state is reading or parsing', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    act(() => {
      result.current.parseFile(createMockFile());
    });
    expect(result.current.state).toBe('reading');

    // A second FileReader should NOT be created
    const firstReader = latestMockFileReader;
    act(() => {
      result.current.parseFile(createMockFile());
    });
    // latestMockFileReader should still be the first one because the guard
    // returned early before constructing a new FileReader.
    expect(latestMockFileReader).toBe(firstReader);
    expect(firstReader.readAsText).toHaveBeenCalledTimes(1);
  });

  // -----------------------------------------------------------------------
  // 10. Worker onerror handler
  // -----------------------------------------------------------------------
  it('transitions to error state on worker runtime error (onerror)', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    act(() => {
      result.current.parseFile(createMockFile());
    });
    act(() => {
      latestMockFileReader.onload!();
    });
    expect(result.current.state).toBe('parsing');

    // Simulate a worker runtime error via the onerror handler
    act(() => {
      const errorEvent = new ErrorEvent('error', {
        message: 'Worker script threw an exception',
      });
      latestMockWorker.onerror!(errorEvent);
    });

    expect(result.current.state).toBe('error');
    expect(result.current.error).toBe('Worker script threw an exception');
  });

  // -----------------------------------------------------------------------
  // 11. Can parse again after reset
  // -----------------------------------------------------------------------
  it('allows a new parse after reset', () => {
    const { result } = renderHook(() => useHardwareScheduleParser());

    // First parse cycle through to done
    act(() => {
      result.current.parseFile(createMockFile());
    });
    act(() => {
      latestMockFileReader.onload!();
    });
    act(() => {
      latestMockWorker.onmessage!(
        new MessageEvent('message', {
          data: { type: 'result', data: mockParseResult },
        }),
      );
    });
    expect(result.current.state).toBe('done');

    // Reset
    act(() => {
      result.current.reset();
    });
    expect(result.current.state).toBe('idle');

    // Parse again
    act(() => {
      result.current.parseFile(createMockFile());
    });
    expect(result.current.state).toBe('reading');

    act(() => {
      latestMockFileReader.onload!();
    });
    expect(result.current.state).toBe('parsing');
    expect(latestMockWorker.postMessage).toHaveBeenCalledTimes(1);
  });
});
