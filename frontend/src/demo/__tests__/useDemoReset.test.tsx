import { act, renderHook, waitFor } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import type { ReactNode } from 'react';
import { GET_DEMO_RESET_STATUS, RESET_DEMO } from '../../graphql/demo';
import { reloadPage, useDemoReset } from '../useDemoReset';

// #1697: a tab that saw a reset running reloads once it has finished, into the rebuilt demo.

vi.mock('../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));

type Failure = { failedAt: string; startedBy: string } | null;

function status(building: boolean, failure: Failure = null) {
  return {
    __typename: 'DemoResetStatus',
    building,
    buildStartedAt: building ? '2026-10-16T18:40:00' : null,
    buildStartedBy: building ? 'Rhea Resetter' : null,
    notice: null,
    failure: failure ? { __typename: 'DemoBuildFailure', ...failure } : null,
  };
}

const read = (building: boolean, failure: Failure = null): MockedResponse => ({
  request: { query: GET_DEMO_RESET_STATUS },
  result: { data: { demoResetStatus: status(building, failure) } },
});

const FAILED = { failedAt: '2026-10-16T18:41:52', startedBy: 'Rhea Resetter' };

function wrapper(mocks: MockedResponse[]) {
  return ({ children }: { children: ReactNode }) => <MockedProvider mocks={mocks}>{children}</MockedProvider>;
}

let reload: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  reload = vi.spyOn(reloadPage, 'run').mockImplementation(() => {});
});
afterEach(() => reload.mockRestore());

it('reloads when a reset it saw running has finished', async () => {
  const { result } = renderHook(() => useDemoReset(true), {
    wrapper: wrapper([
      read(false),
      { request: { query: RESET_DEMO }, result: { data: { resetDemo: status(true) } } },
      read(true),
      read(false),
    ]),
  });
  await waitFor(() => expect(result.current.status).not.toBeNull());
  expect(reload).not.toHaveBeenCalled();

  await act(async () => {
    await result.current.reset();
  });
  expect(result.current.building).toBe(true);

  // The next read says it is done.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 4500));
  });
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
}, 15_000);

// #1937: the failed seed wiped what it built, so reloading would land the tab in an empty demo, silently.
it('shows a reset it saw running that failed instead of reloading into it', async () => {
  const { result } = renderHook(() => useDemoReset(true), {
    wrapper: wrapper([
      read(false),
      { request: { query: RESET_DEMO }, result: { data: { resetDemo: status(true) } } },
      read(true),
      read(false, FAILED),
    ]),
  });
  await waitFor(() => expect(result.current.status).not.toBeNull());

  await act(async () => {
    await result.current.reset();
  });
  expect(result.current.building).toBe(true);
  expect(result.current.failure).toBeNull();

  await act(async () => {
    await new Promise((r) => setTimeout(r, 4500));
  });
  await waitFor(() => expect(result.current.failure).toEqual(expect.objectContaining(FAILED)));
  expect(reload).not.toHaveBeenCalled();
}, 15_000);

it('tells a tab that opened after a failed build, until it is closed there', async () => {
  const { result } = renderHook(() => useDemoReset(true), { wrapper: wrapper([read(false, FAILED)]) });
  await waitFor(() => expect(result.current.failure).toEqual(expect.objectContaining(FAILED)));

  act(() => result.current.closeFailure());
  expect(result.current.failure).toBeNull();
  expect(result.current.status?.failure).toEqual(expect.objectContaining(FAILED));
  expect(reload).not.toHaveBeenCalled();
});

it('never reloads a tab that saw no reset running', async () => {
  const { result } = renderHook(() => useDemoReset(true), { wrapper: wrapper([read(false)]) });
  await waitFor(() => expect(result.current.status).not.toBeNull());
  expect(reload).not.toHaveBeenCalled();
});

it('reads nothing out of demo mode', () => {
  const { result } = renderHook(() => useDemoReset(false), { wrapper: wrapper([]) });
  expect(result.current.status).toBeNull();
});
