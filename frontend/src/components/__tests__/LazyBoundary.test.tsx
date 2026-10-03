import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LazyBoundary, isChunkLoadError } from '../LazyBoundary';

function Boom({ error }: { error: Error }): never {
  throw error;
}

let reload: ReturnType<typeof vi.fn>;
let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  reload = vi.fn();
  Object.defineProperty(window, 'location', { value: { ...window.location, reload }, configurable: true });
  window.sessionStorage.clear();
  // React logs caught render errors itself; keep the run quiet and let the tests read the calls.
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  consoleError.mockRestore();
});

describe('LazyBoundary (#1135)', () => {
  it('shows a render error instead of the loading skeleton, and does not reload', () => {
    render(
      <LazyBoundary fallback={<div>skeleton</div>}>
        <Boom error={new TypeError("Cannot read properties of null (reading 'poNumber')")} />
      </LazyBoundary>,
    );
    expect(screen.queryByText('skeleton')).not.toBeInTheDocument();
    expect(screen.getByText('This page hit an error')).toBeInTheDocument();
    expect(screen.getByText(/reading 'poNumber'/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalledWith('A page failed to render:', expect.any(TypeError));
  });

  it('reloads on a stale chunk and holds the skeleton meanwhile', () => {
    render(
      <LazyBoundary fallback={<div>skeleton</div>}>
        <Boom error={new Error('Failed to fetch dynamically imported module: /assets/po-abc.js')} />
      </LazyBoundary>,
    );
    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByText('skeleton')).toBeInTheDocument();
  });

  it('says the page is out of date when a reload already failed to fix the chunk', () => {
    window.sessionStorage.setItem('uc-nexus:lazy-chunk-reload-at', String(Date.now()));
    render(
      <LazyBoundary fallback={<div>skeleton</div>}>
        <Boom error={new Error('Failed to fetch dynamically imported module: /assets/po-abc.js')} />
      </LazyBoundary>,
    );
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText('This page is out of date')).toBeInTheDocument();
  });

  it('tries its children again when the route changes', () => {
    const { rerender } = render(
      <LazyBoundary fallback={<div>skeleton</div>} resetKey="/app/po">
        <Boom error={new Error('broken po page')} />
      </LazyBoundary>,
    );
    expect(screen.getByText('This page hit an error')).toBeInTheDocument();

    rerender(
      <LazyBoundary fallback={<div>skeleton</div>} resetKey="/app/warehouse">
        <div>warehouse page</div>
      </LazyBoundary>,
    );
    expect(screen.getByText('warehouse page')).toBeInTheDocument();
  });

  it('tells chunk-load errors from other errors', () => {
    expect(isChunkLoadError(new Error('Loading chunk 12 failed.'))).toBe(true);
    expect(isChunkLoadError(new TypeError('x is undefined'))).toBe(false);
  });
});
